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
from fastapi.responses import JSONResponse
from pydantic import BaseModel, TypeAdapter
import httpx

from services.app.auth import hash_password, verify_password
from services.app.db import db
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

# Mount web UI (Jinja2 + HTMX)
mount_web(app, get_user_from_request)


# ---------------------------------------------------------------------------
# REST API: Authentication (TR: Сценарий 1)
# ---------------------------------------------------------------------------

class Credentials(BaseModel):
    login: str
    password: str


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
    if not login or not body.password:
        return JSONResponse({"code": "INVALID_INPUT", "message": "Укажите логин и пароль."}, status_code=422)

    existing = await db.get_user_by_login(login)
    if existing:
        return JSONResponse({"code": "LOGIN_TAKEN", "message": "Логин уже занят."}, status_code=409)

    hashed = hash_password(body.password)
    user = await db.create_user(login, hashed)
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

    # Prepare streaming audio data (synthetic valid MPEG-1 Layer III audio)
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
    unread = 0
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
async def health_check():
    return {
        "status": "ok",
        "node_id": NODE_ID,
        "db_connected": db.is_connected,
    }


@app.post(
    "/internal/deliver",
    response_model=InternalDeliverResponse,
    summary="Internal inter-node message delivery",
)
async def deliver_internal(
    request: InternalDeliverRequest,
    x_internal_secret: Annotated[str | None, Header(alias="X-Internal-Secret")] = None,
):
    if not x_internal_secret or not hmac.compare_digest(x_internal_secret, INTERNAL_SECRET):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Invalid or missing X-Internal-Secret",
        )

    delivered: list[UUID] = []
    missed: list[UUID] = []
    event_json = request.event.model_dump_json()

    for target in request.targets:
        ws = active_connections.get(target.connection_id)
        belongs_to_user = target.connection_id in user_connections.get(target.user_id, set())
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
):
    """
    Delivers event to all active sessions of conversation members:
    - In-memory WebSocket if on local node;
    - POST /internal/deliver if on remote node.
    """
    sessions = await db.get_active_sessions_for_users(list(members))
    remote_by_node: dict[str, list[DeliveryTarget]] = {}

    for s in sessions:
        conn_id = s["connection_id"]
        target_uid = s["user_id"]
        node = s["node_id"]

        if node == NODE_ID:
            if conn_id != skip_conn_id:
                ws = active_connections.get(conn_id)
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
        async with httpx.AsyncClient(timeout=3.0) as client:
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
    active_connections[connection_id] = websocket
    user_connections.setdefault(user_id, set()).add(connection_id)
    await db.register_session(connection_id, user_id, NODE_ID)

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
                        await _dispatch_to_sessions(members, chat_msg, skip_conn_id=connection_id)

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
        active_connections.pop(connection_id, None)
        user_connections.get(user_id, set()).discard(connection_id)
        await db.remove_session(connection_id)
