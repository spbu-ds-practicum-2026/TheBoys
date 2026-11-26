"""Repair missing track replicas using the PostgreSQL job queue."""
import asyncio
import hashlib
import logging
import os
import socket

import asyncpg
import httpx


async def claim(pool, worker_id):
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("""
            UPDATE replicas r SET status = 'lost'
            FROM node_registry n
            WHERE r.node_id = n.node_id AND r.status = 'active'
              AND n.role = 'storage'
              AND n.last_heartbeat < now() - interval '30 seconds'
        """)
        await conn.execute("""
            WITH live AS (
                SELECT node_id FROM node_registry
                WHERE role = 'storage' AND status = 'alive'
                  AND last_heartbeat >= now() - interval '15 seconds'
            )
            INSERT INTO jobs (task_type, track_id)
            SELECT 'replicate', r.track_id
            FROM replicas r LEFT JOIN live USING (node_id)
            WHERE r.status = 'active'
            GROUP BY r.track_id HAVING count(*) = 1 AND count(live.node_id) = 1
                AND (SELECT count(*) FROM live) >= 2
            ON CONFLICT DO NOTHING
        """)
        return await conn.fetchrow("""
            WITH next_job AS (
                SELECT id FROM jobs WHERE task_type = 'replicate'
                  AND (status = 'pending' OR (status = 'running' AND lease_until < now()))
                ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1
            )
            UPDATE jobs j SET status = 'running', worker_id = $1,
                fencing_token = fencing_token + 1,
                lease_until = now() + interval '20 seconds', updated_at = now()
            FROM next_job WHERE j.id = next_job.id
            RETURNING j.id, j.track_id, j.fencing_token
        """, worker_id)


async def copy_track(client, track, source, target, job):
    headers = {
        "X-Replication-Job": str(job["id"]),
        "X-Fencing-Token": str(job["fencing_token"]),
    }
    async with client.stream("GET", f"{source}/blobs/{track}") as audio:
        audio.raise_for_status()
        response = await client.put(
            f"{target}/blobs/{track}", content=audio.aiter_bytes(), headers=headers,
        )
        response.raise_for_status()


async def repair(pool, client, job):
    track = job["track_id"]
    nodes = await pool.fetch("""
        SELECT n.node_id, n.endpoint_url, r.status = 'active' AS has_copy
        FROM node_registry n LEFT JOIN replicas r
            ON r.node_id = n.node_id AND r.track_id = $1
        WHERE n.role = 'storage' AND n.status = 'alive'
          AND n.last_heartbeat >= now() - interval '15 seconds'
    """, track)
    sources = [node for node in nodes if node["has_copy"]]
    targets = [node for node in nodes if not node["has_copy"]]
    target = None
    if len(sources) == 1 and targets:
        target = max(targets, key=lambda node: hashlib.sha256(
            f"{track}:{node['node_id']}".encode()
        ).digest())
        copying = asyncio.create_task(copy_track(
            client, track, sources[0]["endpoint_url"], target["endpoint_url"], job,
        ))
        try:
            while not (await asyncio.wait({copying}, timeout=5))[0]:
                renewed = await pool.fetchval("""
                    UPDATE jobs SET lease_until = now() + interval '20 seconds'
                    WHERE id = $1 AND fencing_token = $2 AND status = 'running'
                      AND lease_until > now() RETURNING id
                """, job["id"], job["fencing_token"])
                if renewed is None:
                    return
            await copying
        finally:
            if not copying.done():
                copying.cancel()
                await asyncio.gather(copying, return_exceptions=True)

    async with pool.acquire() as conn, conn.transaction():
        finished = await conn.fetchval("""
            UPDATE jobs SET status = 'completed', lease_until = NULL, updated_at = now()
            WHERE id = $1 AND fencing_token = $2 AND status = 'running'
              AND lease_until > now()
            RETURNING id
        """, job["id"], job["fencing_token"])
        if finished is not None and target is not None:
            await conn.execute("""
                INSERT INTO replicas (track_id, node_id) VALUES ($1, $2)
                ON CONFLICT (track_id, node_id) DO UPDATE SET status = 'active'
            """, track, target["node_id"])
    if finished is not None and target is not None:
        logging.info("Restored %s on %s from %s", track, target["node_id"], sources[0]["node_id"])


async def main():
    logging.basicConfig(level=logging.INFO)
    worker_id = socket.gethostname()
    headers = {"X-Internal-Secret": os.environ["INTERNAL_SECRET"]}
    async with asyncpg.create_pool(os.environ["DATABASE_URL"], min_size=1, max_size=3) as pool:
        async with httpx.AsyncClient(headers=headers, timeout=10) as client:
            while True:
                try:
                    job = await claim(pool, worker_id)
                    if job is not None:
                        await repair(pool, client, job)
                except Exception:
                    logging.exception("Replication cycle failed; expired jobs can be retried")
                await asyncio.sleep(3)


if __name__ == "__main__":
    asyncio.run(main())
