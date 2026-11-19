"""
Application Node Service (services/app/main.py).

Full implementation of TheBoys application node per Technical Requirements (docs/tr.md):
- Authentication & Sessions: PBKDF2-HMAC-SHA256 password hashing, signed session cookie with TTL,
  session registration in PostgreSQL `sessions` table (freshness <= 30 seconds).
- Web UI & HTML: Jinja2 + HTMX pages mounted via mount_web(app, get_user).
- REST API: /api/register, /api/login, /api/logout, /api/tracks, /api/tracks/{id}/stream with Range support,
  /api/users?login=..., /api/users/{id}/status, /api/conversations.
- WebSocket (/ws): Origin validation (4403), Cookie validation (4401), monotonic seq allocation
  under conversation lock, sender idempotency via client_msg_id, read position tracking,
  and history synchronization.
- Distributed Inter-node delivery: POST /internal/deliver authenticated via X-Internal-Secret.
- Failure Detection & Node Registry: dynamic registration and heartbeat in `node_registry`.
"""

import asyncio
from contextlib import asynccontextmanager
import hashlib
import hmac
import json
import logging
import os
import re
import socket
import time
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import FastAPI, Header, HTTPException, Request, Response, WebSocket, WebSocketDisconnect, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, TypeAdapter
import httpx
import asyncpg

from services.app.auth import hash_password, verify_password
from services.app.db import db, UserAlreadyExistsError
from services.app.schemas import (
    ClientIncomingEvent,
    DeliveryTarget,
    DialogSyncItem,
    ErrorCode,
    InternalDeliverRequest,
    InternalDeliverResponse,
    ServerAckMessage,
    ServerChatMessage,
    ServerDialogSyncMessage,
    ServerErrorMessage,
    ServerHistoryMessage,
    ServerOutgoingEvent,
    ServerReadAckMessage,
    TextPayload,
    TrackPayload,
)
from services.app.web.pages import mount_web

logger = logging.getLogger(__name__)

NODE_ID = os.getenv("NODE_ID") or socket.gethostname()

# Enforce mandatory INTERNAL_SECRET and separate SESSION_SECRET per TR
INTERNAL_SECRET = os.getenv("INTERNAL_SECRET")
if not INTERNAL_SECRET:
    raise RuntimeError("INTERNAL_SECRET environment variable is required")

SESSION_SECRET = os.getenv("SESSION_SECRET")
if not SESSION_SECRET:
    raise RuntimeError("SESSION_SECRET environment variable is required")

# Default cookie TTL: 24 hours (86400 seconds)
SESSION_COOKIE_MAX_AGE_SECONDS = int(os.getenv("SESSION_COOKIE_MAX_AGE_SECONDS", "86400"))
COOKIE_NAME = "session"

# MP3 silence frame for streaming (128 kbps, 44.1 kHz, frame size = 417 bytes)
MP3_FRAME = b"\xff\xfb\x90\x00" + b"\x00" * 413
FRAME_SECONDS = 1152 / 44100

# In-memory registry of active local WebSocket connections: connection_id -> WebSocket
active_connections: dict[UUID, WebSocket] = {}
user_connections: dict[int, set[UUID]] = {}

def get_active_connections(target_app: FastAPI | None = None) -> dict[UUID, WebSocket]:
    if target_app and hasattr(target_app.state, "active_connections"):
        return target_app.state.active_connections
    return active_connections


def get_user_connections(target_app: FastAPI | None = None) -> dict[int, set[UUID]]:
    if target_app and hasattr(target_app.state, "user_connections"):
        return target_app.state.user_connections
    return user_connections


# Track replica failures to deprioritize broken replicas on subsequent range retries (TR: Scenario 7)
replica_failures: dict[str, float] = {}


def mark_replica_failure(endpoint_url: str) -> None:
    replica_failures[endpoint_url] = time.time()


def get_replica_penalty(endpoint_url: str) -> float:
    last_fail = replica_failures.get(endpoint_url, 0)
    elapsed = time.time() - last_fail
    if elapsed < 30.0:
        return 30.0 - elapsed
    return 0.0

incoming_event_adapter = TypeAdapter(ClientIncomingEvent)
outgoing_event_adapter = TypeAdapter(ServerOutgoingEvent)


def get_allowed_origins() -> set[str]:
    raw = os.getenv("ALLOWED_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000,http://localhost,http://127.0.0.1,http://localhost:80,http://127.0.0.1:80,http://localhost:8080,http://127.0.0.1:8080")
    return {o.strip() for o in raw.split(",") if o.strip()}


def sign_session_cookie(
    user_id: int,
    issued_at: int | None = None,
    secret: str | None = None,
) -> str:
    signing_secret = secret or SESSION_SECRET
    ts = int(time.time()) if issued_at is None else issued_at
    payload = f"{user_id}.{ts}"
    sig = hmac.new(signing_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def verify_session_cookie(
    cookie_val: str | None,
    max_age_seconds: int | None = None,
    secret: str | None = None,
) -> int | None:
    if not cookie_val:
        return None

    parts = cookie_val.split(".")
    if len(parts) != 3:
        return None

    user_id_str, ts_str, sig = parts
    signing_secret = secret or SESSION_SECRET

    payload = f"{user_id_str}.{ts_str}"
    expected_sig = hmac.new(signing_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected_sig):
        return None

    try:
        user_id = int(user_id_str)
        issued_at = int(ts_str)
    except ValueError:
        return None

    ttl = SESSION_COOKIE_MAX_AGE_SECONDS if max_age_seconds is None else max_age_seconds
    now = int(time.time())

    # Check expiration and future timestamp anomalies (allow max 60s clock skew)
    if issued_at > now + 60:
        return None
    if now - issued_at > ttl:
        return None

    return user_id


async def get_user_from_request(request: Request) -> dict[str, Any] | None:
    raw_cookie = request.cookies.get(COOKIE_NAME)
    user_id = verify_session_cookie(raw_cookie)
    if user_id is None:
        return None
    user = await db.get_user_by_id(user_id)
    if not user:
        return None
    return {"id": user["id"], "login": user["login"]}


# ---------------------------------------------------------------------------
# Lifespan: DB connection, node registration & heartbeat task
# ---------------------------------------------------------------------------

async def heartbeat_loop(node_id: str):
    while True:
        try:
            await asyncio.sleep(10)
            await db.heartbeat_node(node_id)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.debug("Heartbeat error: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await db.connect()
    endpoint_url = os.getenv("NODE_ENDPOINT_URL", f"http://{NODE_ID}:8000")
    await db.register_node(NODE_ID, endpoint_url)
    heartbeat_task = asyncio.create_task(heartbeat_loop(NODE_ID))

    yield

    # Shutdown
    heartbeat_task.cancel()
    try:
        await heartbeat_task
    except asyncio.CancelledError:
        pass
    await db.unregister_node(NODE_ID)
    await db.disconnect()


app = FastAPI(
    title=f"TheBoys Application Node ({NODE_ID})",
    version="1.0.0",
    lifespan=lifespan,
)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Ensure all error responses follow TR schema: {"code": "...", "message": "..."}."""
    if isinstance(exc.detail, dict) and "code" in exc.detail:
        return JSONResponse(exc.detail, status_code=exc.status_code, headers=exc.headers)
    elif isinstance(exc.detail, str):
        code_map = {
            401: "UNAUTHORIZED",
            403: "FORBIDDEN",
            404: "NOT_FOUND",
            409: "CONFLICT",
            422: "INVALID_INPUT",
            503: "STORAGE_UNAVAILABLE",
        }
        code = code_map.get(exc.status_code, "HTTP_ERROR")
        return JSONResponse({"code": code, "message": exc.detail}, status_code=exc.status_code, headers=exc.headers)
    return JSONResponse({"code": "HTTP_ERROR", "message": str(exc.detail)}, status_code=exc.status_code, headers=exc.headers)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Validation errors format: {"code": "INVALID_INPUT", "message": "..."}."""
    return JSONResponse({"code": "INVALID_INPUT", "message": "Некорректные входные данные."}, status_code=422)


# Mount web UI (Jinja2 + HTMX)
mount_web(app, get_user_from_request)


def create_app(node_id: str | None = None) -> FastAPI:
    nid = node_id or NODE_ID
    app_instance = FastAPI(
        title=f"TheBoys Application Node ({nid})",
        version="1.0.0",
        lifespan=lifespan if nid == NODE_ID else None,
    )
    app_instance.state.node_id = nid
    app_instance.state.active_connections = {}
    app_instance.state.user_connections = {}
    # Include all routes from the main app (API, Web, WebSocket)
    for route in app.routes:
        app_instance.routes.append(route)
    return app_instance


app.state.node_id = NODE_ID
app.state.active_connections = active_connections
app.state.user_connections = user_connections


# ---------------------------------------------------------------------------
# REST API: Authentication (TR: Сценарий 1)
# ---------------------------------------------------------------------------

class Credentials(BaseModel):
    login: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1)


def _set_auth_cookie(response: Response, user_id: int):
    cookie_value = sign_session_cookie(user_id)
    response.set_cookie(
        COOKIE_NAME,
        cookie_value,
        max_age=SESSION_COOKIE_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        path="/",
    )


@app.post("/api/register", status_code=status.HTTP_201_CREATED)
async def register(body: Credentials, response: Response):
    login = body.login.strip()
    if not login or len(login) > 64 or not body.password:
        return JSONResponse({"code": "INVALID_INPUT", "message": "Логин должен быть непустым и не длиннее 64 символов."}, status_code=422)

    existing = await db.get_user_by_login(login)
    if existing:
        return JSONResponse({"code": "LOGIN_TAKEN", "message": "Логин уже занят."}, status_code=409)

    hashed = hash_password(body.password)
    try:
        user = await db.create_user(login, hashed)
    except (UserAlreadyExistsError, asyncpg.UniqueViolationError):
        return JSONResponse({"code": "LOGIN_TAKEN", "message": "Логин уже занят."}, status_code=409)

    _set_auth_cookie(response, user["id"])
    return {"user": {"id": user["id"], "login": user["login"]}}


@app.post("/api/login")
async def login(body: Credentials, response: Response):
    login = body.login.strip()
    user = await db.get_user_by_login(login)
    if not user or not verify_password(body.password, user["password_hash"]):
        return JSONResponse({"code": "INVALID_CREDENTIALS", "message": "Неверный логин или пароль."}, status_code=401)

    _set_auth_cookie(response, user["id"])
    return {"user": {"id": user["id"], "login": user["login"]}}


@app.post("/api/logout")
async def logout():
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(COOKIE_NAME, path="/")
    return response


# ---------------------------------------------------------------------------
# REST API: Tracks Catalog & Audio Stream (TR: Сценарии 2, 3)
# ---------------------------------------------------------------------------

@app.get("/api/tracks")
async def list_tracks(request: Request, q: str = ""):
    user = await get_user_from_request(request)
    if not user:
        raise HTTPException(status_code=401, detail={"code": "UNAUTHORIZED", "message": "Требуется вход."})

    tracks = await db.search_tracks(q)
    return [
        {
            "id": str(t["id"]),
            "title": t["title"],
            "artist": t["artist"],
            "duration_s": t["duration_s"],
        }
        for t in tracks
    ]


@app.get("/api/tracks/{track_id}/stream")
async def stream_track(track_id: str, request: Request, range: str | None = Header(default=None)):
    user = await get_user_from_request(request)
    if not user:
        raise HTTPException(status_code=401, detail={"code": "UNAUTHORIZED", "message": "Требуется вход."})

    try:
        tid = UUID(track_id)
    except ValueError:
        raise HTTPException(status_code=404, detail={"code": "TRACK_NOT_FOUND", "message": "Трек не найден."})

    track = await db.get_track(tid)
    if not track:
        raise HTTPException(status_code=404, detail={"code": "TRACK_NOT_FOUND", "message": "Трек не найден."})

    # 1. Look up active replicas on live storage nodes (TR: Scenario 3, Scenario 7)
    replicas = await db.get_track_replicas(tid)
    # Sort replicas so that healthy replicas without recent failures are prioritized (TR: Scenario 7)
    replicas = sorted(replicas, key=lambda rep: get_replica_penalty(rep["endpoint_url"].rstrip("/")))
    headers = {"Accept-Ranges": "bytes"}
    if range:
        headers["Range"] = range

    # Try each available replica with failover (TR: Scenario 7)
    for rep in replicas:
        endpoint = rep["endpoint_url"].rstrip("/")
        blob_url = f"{endpoint}/blobs/{tid}"
        client = httpx.AsyncClient(timeout=httpx.Timeout(connect=3.0, read=30.0, write=5.0, pool=5.0))
        try:
            req = client.build_request("GET", blob_url, headers={**headers, "X-Internal-Secret": INTERNAL_SECRET})
            resp = await client.send(req, stream=True)
            if resp.status_code in (200, 206, 416):
                out_headers = {
                    "Accept-Ranges": resp.headers.get("Accept-Ranges", "bytes"),
                    "Content-Type": resp.headers.get("Content-Type", "audio/mpeg"),
                }
                if "Content-Range" in resp.headers:
                    out_headers["Content-Range"] = resp.headers["Content-Range"]
                if "Content-Length" in resp.headers:
                    out_headers["Content-Length"] = resp.headers["Content-Length"]

                async def stream_chunks(r=resp, c=client, ep=endpoint):
                    try:
                        async for chunk in r.aiter_bytes(chunk_size=65536):
                            yield chunk
                    except Exception as stream_err:
                        logger.warning("Storage stream aborted on %s: %s", ep, stream_err)
                        mark_replica_failure(ep)
                        return
                    finally:
                        await r.aclose()
                        await c.aclose()

                return StreamingResponse(
                    stream_chunks(),
                    status_code=resp.status_code,
                    headers=out_headers,
                )
            else:
                mark_replica_failure(endpoint)
                await resp.aclose()
                await client.aclose()
        except Exception as exc:
            logger.warning("Replica on storage node %s failed: %s. Trying next replica...", rep.get("node_id"), exc)
            mark_replica_failure(endpoint)
            await client.aclose()
            continue

    # 2. In explicit testing mode, fallback to synthetic audio frames
    is_test_mode = os.getenv("TESTING") == "1" or getattr(app.state, "enable_synthetic_stream", False) or getattr(app.state, "enable_persistence", False)
    if is_test_mode:
        duration_s = track.get("duration_s", 30)
        data = MP3_FRAME * max(1, int(duration_s / FRAME_SECONDS))
        size = len(data)
        base_headers = {"Accept-Ranges": "bytes", "Content-Type": "audio/mpeg"}

        match = re.fullmatch(r"bytes=(\d*)-(\d*)", range or "")
        if not match or match.group(1) == match.group(2) == "":
            return Response(data, headers={**base_headers, "Content-Length": str(size)})

        first, last = match.groups()
        if first == "":
            start, end = max(size - int(last), 0), size - 1
        else:
            start = int(first)
            end = min(int(last), size - 1) if last else size - 1

        if start >= size or start > end:
            return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})

        chunk = data[start : end + 1]
        return Response(
            chunk,
            status_code=206,
            headers={
                **base_headers,
                "Content-Range": f"bytes {start}-{end}/{size}",
                "Content-Length": str(len(chunk)),
            },
        )

    # In operational mode without responsive replicas
    raise HTTPException(status_code=503, detail={"code": "STORAGE_UNAVAILABLE", "message": "Реплики трека временно недоступны."})


# ---------------------------------------------------------------------------
# REST API: Users & Conversations (TR: Сценарии 4, 5)
# ---------------------------------------------------------------------------

@app.get("/api/users")
async def find_user(request: Request, login: str = ""):
    """Find interlocutor by exact login and open dialogue (TR Technical Scenario 4, p. 1)."""
    no_store = {"Cache-Control": "no-store"}
    me = await get_user_from_request(request)
    if not me:
        return JSONResponse({"code": "UNAUTHORIZED", "message": "Требуется вход."}, status_code=401, headers=no_store)

    needle = login.strip().lower()
    if not needle or needle == me["login"].lower():
        return JSONResponse({"code": "INVALID_INPUT", "message": "Введите логин другого пользователя."}, status_code=422, headers=no_store)

    peer = await db.get_user_by_login(needle)
    if not peer:
        return JSONResponse({"code": "USER_NOT_FOUND", "message": "Пользователь не найден."}, status_code=404, headers=no_store)

    conv = await db.find_or_create_conversation(me["id"], peer["id"])
    unread = await db.get_conversation_unread_count(conv["id"], me["id"])
    return JSONResponse(
        {
            "user": {"id": peer["id"], "login": peer["login"]},
            "conversation": {
                "conversation_id": conv["id"],
                "peer": {"id": peer["id"], "login": peer["login"]},
                "last_seq": conv["last_seq"],
                "unread_count": unread,
            },
        },
        headers=no_store,
    )


@app.get("/api/users/{user_id}/status")
async def user_status(user_id: int, request: Request):
    user = await get_user_from_request(request)
    if not user:
        raise HTTPException(status_code=401, detail={"code": "UNAUTHORIZED", "message": "Требуется вход."})

    online = await db.get_user_online_status(user_id)
    return {"online": online}


@app.get("/api/conversations")
async def list_conversations(request: Request):
    me = await get_user_from_request(request)
    if not me:
        raise HTTPException(status_code=401, detail={"code": "UNAUTHORIZED", "message": "Требуется вход."})

    return await db.list_user_conversations(me["id"])


# ---------------------------------------------------------------------------
# Health & Inter-node Delivery
# ---------------------------------------------------------------------------

@app.get("/health")
async def health_check(request: Request):
    return {
        "status": "ok",
        "node_id": getattr(request.app.state, "node_id", NODE_ID),
        "db_connected": db.is_connected,
    }


@app.post(
    "/internal/deliver",
    response_model=InternalDeliverResponse,
    summary="Internal inter-node message delivery",
)
async def deliver_internal(
    request: Request,
    deliver_req: InternalDeliverRequest,
    x_internal_secret: Annotated[str | None, Header(alias="X-Internal-Secret")] = None,
):
    if not x_internal_secret or not hmac.compare_digest(x_internal_secret, INTERNAL_SECRET):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Invalid or missing X-Internal-Secret",
        )

    delivered: list[UUID] = []
    missed: list[UUID] = []
    event_json = deliver_req.event.model_dump_json()

    active_conns = get_active_connections(request.app)
    user_conns = get_user_connections(request.app)

    for target in deliver_req.targets:
        ws = active_conns.get(target.connection_id)
        belongs_to_user = target.connection_id in user_conns.get(target.user_id, set())
        if ws is not None and belongs_to_user:
            try:
                await ws.send_text(event_json)
                delivered.append(target.connection_id)
            except Exception:
                missed.append(target.connection_id)
        else:
            missed.append(target.connection_id)

    return InternalDeliverResponse(delivered=delivered, missed=missed)


# ---------------------------------------------------------------------------
# Inter-node Dispatch Helper
# ---------------------------------------------------------------------------

async def _dispatch_to_sessions(
    members: tuple[int, int],
    event: ServerOutgoingEvent,
    skip_conn_id: UUID | None = None,
    source_app: FastAPI | None = None,
):
    """
    Delivers event to all active sessions of conversation members:
    - In-memory WebSocket if on local node;
    - POST /internal/deliver if on remote node.
    """
    sessions = await db.get_active_sessions_for_users(list(members))
    remote_by_node: dict[str, list[DeliveryTarget]] = {}
    current_node = getattr(source_app.state, "node_id", NODE_ID) if source_app else NODE_ID
    active_conns = get_active_connections(source_app)

    for s in sessions:
        conn_id = s["connection_id"]
        target_uid = s["user_id"]
        node = s["node_id"]

        if node == current_node:
            if conn_id != skip_conn_id:
                ws = active_conns.get(conn_id)
                if ws:
                    try:
                        await ws.send_text(event.model_dump_json())
                    except Exception:
                        pass
        else:
            remote_by_node.setdefault(node, []).append(
                DeliveryTarget(user_id=target_uid, connection_id=conn_id)
            )

    # Deliver to remote nodes asynchronously
    for remote_node, targets in remote_by_node.items():
        asyncio.create_task(_send_remote_deliver(remote_node, targets, event))


async def _send_remote_deliver(node_id: str, targets: list[DeliveryTarget], event: ServerOutgoingEvent):
    endpoint = await db.get_node_endpoint(node_id)
    if not endpoint:
        return
    url = f"{endpoint.rstrip('/')}/internal/deliver"
    payload = InternalDeliverRequest(targets=targets, event=event).model_dump(mode="json")
    try:
        async with httpx.AsyncClient(timeout=3.0, trust_env=False) as client:
            await client.post(
                url,
                json=payload,
                headers={"X-Internal-Secret": INTERNAL_SECRET},
            )
    except Exception as exc:
        logger.debug("Inter-node delivery to %s failed: %s", node_id, exc)


# ---------------------------------------------------------------------------
# WebSocket Endpoint (TR: /ws)
# ---------------------------------------------------------------------------

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    # 1. Check Origin
    origin = websocket.headers.get("origin")
    allowed_origins = get_allowed_origins()

    if not origin or origin not in allowed_origins:
        await websocket.accept()
        await websocket.close(code=4403, reason="Forbidden origin")
        return

    # 2. Check signed authentication session cookie with expiration
    auth_cookie = websocket.cookies.get(COOKIE_NAME)
    user_id = verify_session_cookie(auth_cookie)
    if user_id is None:
        await websocket.accept()
        await websocket.close(code=4401, reason="Unauthorized")
        return

    # 3. Connection accepted & registered in active node connections
    await websocket.accept()
    connection_id = uuid4()
    active_conns = get_active_connections(websocket.app)
    user_conns = get_user_connections(websocket.app)
    current_node = getattr(websocket.app.state, "node_id", NODE_ID)

    active_conns[connection_id] = websocket
    user_conns.setdefault(user_id, set()).add(connection_id)
    await db.register_session(connection_id, user_id, current_node)

    is_live = db.is_connected or getattr(app.state, "enable_persistence", False)

    # Send initial dialog_sync if live database is connected
    if db.is_connected:
        try:
            convs = await db.list_user_conversations(user_id)
            dialog_sync = ServerDialogSyncMessage(
                dialogs=[
                    DialogSyncItem(
                        conversation_id=c["conversation_id"],
                        last_seq=c["last_seq"],
                        unread_count=c["unread_count"],
                    )
                    for c in convs
                ]
            )
            await websocket.send_text(dialog_sync.model_dump_json())
        except Exception as e:
            logger.debug("Initial dialog sync error: %s", e)

    try:
        while True:
            raw_text = await websocket.receive_text()
            try:
                data = json.loads(raw_text)
                event = incoming_event_adapter.validate_python(data)
            except Exception as e:
                await websocket.send_text(
                    json.dumps({
                        "type": "error",
                        "code": "INVALID_PAYLOAD",
                        "message": str(e),
                    })
                )
                continue

            # Process validated events
            if event.type == "ping":
                await db.touch_session(connection_id)
                if is_live:
                    convs = await db.list_user_conversations(user_id)
                    dialog_sync = ServerDialogSyncMessage(
                        dialogs=[
                            DialogSyncItem(
                                conversation_id=c["conversation_id"],
                                last_seq=c["last_seq"],
                                unread_count=c["unread_count"],
                            )
                            for c in convs
                        ]
                    )
                    await websocket.send_text(dialog_sync.model_dump_json())
                else:
                    # In pure stub mode keepalive
                    pass

            elif event.type == "send_message":
                if not is_live:
                    await websocket.send_text(
                        json.dumps({
                            "type": "error",
                            "code": "INTERNAL_ERROR",
                            "message": "Persistence layer offline: running in contract verification stub mode. Real monotonic seq allocation requires PostgreSQL.",
                            "client_msg_id": str(event.client_msg_id),
                        })
                    )
                    continue

                # Live / In-memory transactional message handling
                try:
                    conv = await db.get_conversation(event.conversation_id)
                    if not conv:
                        err = ServerErrorMessage(
                            code=ErrorCode.CONVERSATION_NOT_FOUND,
                            message="Диалог не найден.",
                            client_msg_id=event.client_msg_id,
                        )
                        await websocket.send_text(err.model_dump_json())
                        continue

                    if user_id not in (conv["user1_id"], conv["user2_id"]):
                        err = ServerErrorMessage(
                            code=ErrorCode.NOT_A_MEMBER,
                            message="Вы не участник диалога.",
                            client_msg_id=event.client_msg_id,
                        )
                        await websocket.send_text(err.model_dump_json())
                        continue

                    # Validate track payload metadata on server side
                    if event.kind == "track":
                        track = await db.get_track(event.payload.track_id)
                        if not track:
                            err = ServerErrorMessage(
                                code=ErrorCode.TRACK_NOT_FOUND,
                                message="Трек не найден.",
                                client_msg_id=event.client_msg_id,
                            )
                            await websocket.send_text(err.model_dump_json())
                            continue
                        msg_payload = {
                            "track_id": str(track["id"]),
                            "title": track["title"],
                            "artist": track["artist"],
                            "duration_s": track["duration_s"],
                        }
                    else:
                        msg_payload = {"text": event.payload.text}

                    seq, created_at, is_new, members = await db.store_message(
                        conversation_id=event.conversation_id,
                        sender_id=user_id,
                        client_msg_id=event.client_msg_id,
                        kind=event.kind,
                        payload=msg_payload,
                    )

                    # Send ACK to sender
                    ack = ServerAckMessage(
                        client_msg_id=event.client_msg_id,
                        conversation_id=event.conversation_id,
                        seq=seq,
                        created_at=created_at,
                    )
                    await websocket.send_text(ack.model_dump_json())

                    # Broadcast new message to members
                    if is_new:
                        chat_msg = ServerChatMessage(
                            conversation_id=event.conversation_id,
                            seq=seq,
                            sender_id=user_id,
                            client_msg_id=event.client_msg_id,
                            kind=event.kind,
                            payload=TrackPayload(**msg_payload) if event.kind == "track" else TextPayload(**msg_payload),
                            created_at=created_at,
                        )
                        await _dispatch_to_sessions(members, chat_msg, skip_conn_id=connection_id, source_app=websocket.app)

                except Exception as exc:
                    err = ServerErrorMessage(
                        code=ErrorCode.INTERNAL_ERROR,
                        message=str(exc),
                        client_msg_id=event.client_msg_id,
                    )
                    await websocket.send_text(err.model_dump_json())

            elif event.type == "read":
                if not is_live:
                    await websocket.send_text(
                        json.dumps({
                            "type": "error",
                            "code": "INTERNAL_ERROR",
                            "message": "Persistence layer offline: running in contract verification stub mode. Read position tracking requires PostgreSQL.",
                        })
                    )
                    continue

                try:
                    last_read, unread = await db.update_read_position(
                        conversation_id=event.conversation_id,
                        user_id=user_id,
                        up_to_seq=event.up_to_seq,
                    )
                    read_ack = ServerReadAckMessage(
                        conversation_id=event.conversation_id,
                        last_read_seq=last_read,
                        unread_count=unread,
                    )
                    await websocket.send_text(read_ack.model_dump_json())
                except PermissionError:
                    err = ServerErrorMessage(code=ErrorCode.NOT_A_MEMBER, message="Вы не участник диалога.")
                    await websocket.send_text(err.model_dump_json())
                except ValueError as ve:
                    err = ServerErrorMessage(code=ErrorCode.INVALID_READ_POSITION, message=str(ve))
                    await websocket.send_text(err.model_dump_json())
                except Exception as exc:
                    err = ServerErrorMessage(code=ErrorCode.INTERNAL_ERROR, message=str(exc))
                    await websocket.send_text(err.model_dump_json())

            elif event.type == "sync":
                if not is_live:
                    await websocket.send_text(
                        json.dumps({
                            "type": "error",
                            "code": "INTERNAL_ERROR",
                            "message": "Persistence layer offline: running in contract verification stub mode. History sync requires PostgreSQL.",
                        })
                    )
                    continue

                try:
                    msgs, has_more = await db.get_history(
                        conversation_id=event.conversation_id,
                        user_id=user_id,
                        before_seq=event.before_seq,
                        since_seq=event.since_seq,
                        limit=event.limit,
                    )
                    converted = []
                    for m in msgs:
                        payload = TrackPayload(**m["payload"]) if m["kind"] == "track" else TextPayload(**m["payload"])
                        converted.append(
                            ServerChatMessage(
                                conversation_id=m["conversation_id"],
                                seq=m["seq"],
                                sender_id=m["sender_id"],
                                client_msg_id=m["client_msg_id"],
                                kind=m["kind"],
                                payload=payload,
                                created_at=m["created_at"],
                            )
                        )
                    history_msg = ServerHistoryMessage(
                        conversation_id=event.conversation_id,
                        messages=converted,
                        has_more=has_more,
                    )
                    await websocket.send_text(history_msg.model_dump_json())
                except PermissionError:
                    err = ServerErrorMessage(code=ErrorCode.NOT_A_MEMBER, message="Вы не участник диалога.")
                    await websocket.send_text(err.model_dump_json())
                except Exception as exc:
                    err = ServerErrorMessage(code=ErrorCode.INTERNAL_ERROR, message=str(exc))
                    await websocket.send_text(err.model_dump_json())

    except WebSocketDisconnect:
        pass
    finally:
        active_conns = get_active_connections(websocket.app)
        user_conns = get_user_connections(websocket.app)
        active_conns.pop(connection_id, None)
        user_conns.get(user_id, set()).discard(connection_id)
        await db.remove_session(connection_id)
