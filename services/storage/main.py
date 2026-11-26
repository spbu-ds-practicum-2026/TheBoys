"""Internal HTTP service for immutable MP3 replicas."""
import asyncio
import hashlib
import logging
import os
import secrets
import tempfile
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse

async def register(pool, node_id, endpoint):
    await pool.execute(
        """INSERT INTO node_registry (node_id, role, endpoint_url)
           VALUES ($1, 'storage', $2)
           ON CONFLICT (node_id) DO UPDATE SET
               endpoint_url = EXCLUDED.endpoint_url,
               last_heartbeat = now(), status = 'alive'""",
        node_id, endpoint,
    )


async def heartbeat(pool, node_id, endpoint):
    while True:
        await asyncio.sleep(5)
        try:
            await register(pool, node_id, endpoint)
        except Exception:
            logging.exception('Storage heartbeat failed')


@asynccontextmanager
async def lifespan(app):
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        yield
        return
    import asyncpg
    async with asyncpg.create_pool(dsn, min_size=1, max_size=2) as pool:
        app.state.pool = pool
        node_id = os.environ["NODE_ID"]
        endpoint = os.environ["NODE_ENDPOINT_URL"]
        await register(pool, node_id, endpoint)
        task = asyncio.create_task(heartbeat(pool, node_id, endpoint))
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


app = FastAPI(lifespan=lifespan)
root = Path(os.environ.get("STORAGE_DIR", "blobs"))


def authorize(x_internal_secret: str = Header(default="")):
    expected = os.environ.get("INTERNAL_SECRET")
    if not expected or not secrets.compare_digest(x_internal_secret.encode(), expected.encode()):
        raise HTTPException(403)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/blobs/{track_id}", dependencies=[Depends(authorize)])
def read_blob(track_id: UUID):
    path = root / str(track_id)
    if not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, media_type="audio/mpeg")


@app.put("/blobs/{track_id}", dependencies=[Depends(authorize)])
async def write_blob(
    track_id: UUID,
    request: Request,
    x_replication_job: int | None = Header(default=None),
    x_fencing_token: int | None = Header(default=None),
):
    root.mkdir(parents=True, exist_ok=True)
    target = root / str(track_id)
    with tempfile.NamedTemporaryFile(dir=root, delete=False) as output:
        staging = Path(output.name)
    try:
        digest = hashlib.sha256()
        with staging.open("wb") as output:
            async for chunk in request.stream():
                output.write(chunk)
                digest.update(chunk)
        if x_replication_job is not None or x_fencing_token is not None:
            pool = getattr(request.app.state, "pool", None)
            if pool is None or x_replication_job is None or x_fencing_token is None:
                raise HTTPException(409, "Missing replication lease")
            current = await pool.fetchval(
                """SELECT id FROM jobs
                   WHERE id = $1 AND track_id = $2 AND fencing_token = $3
                     AND task_type = 'replicate' AND status = 'running'
                     AND lease_until > now()""",
                x_replication_job, track_id, x_fencing_token,
            )
            if current is None:
                raise HTTPException(409, "Replication lease expired")
        try:
            os.link(staging, target)
        except FileExistsError:
            with target.open("rb") as existing:
                if hashlib.file_digest(existing, "sha256").digest() != digest.digest():
                    raise HTTPException(409, "Track already contains different audio")
            return Response(status_code=204)
        return Response(status_code=201)
    finally:
        staging.unlink(missing_ok=True)
