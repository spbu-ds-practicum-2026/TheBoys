"""
Application Node Service (services/app) - Contract Verification & Protocol Stub.

NOTE: This service implements the WebSocket contract verification layer, schema validation,
Origin checks, cryptographic cookie validation, and inter-node event delivery (/internal/deliver).
Business logic requiring persistent database transactions (monotonic seq allocation from
conversations table, database message persistence, session tracking in the sessions table,
and history retrieval) is implemented as part of the full backend integration with PostgreSQL.
This stub correctly validates client events and rejects invalid schemas/commands without
emitting fake sequential sequences.
"""

import hashlib
import hmac
import json
import os
import time
from typing import Annotated
from uuid import UUID, uuid4
from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect, status
from pydantic import TypeAdapter

from services.app.schemas import (
    ClientIncomingEvent,
    InternalDeliverRequest,
    InternalDeliverResponse,
)

NODE_ID = os.getenv("NODE_ID", "app-1")

# Enforce mandatory INTERNAL_SECRET and separate SESSION_SECRET per TR and review P1
INTERNAL_SECRET = os.getenv("INTERNAL_SECRET")
if not INTERNAL_SECRET:
    raise RuntimeError("INTERNAL_SECRET environment variable is required")

SESSION_SECRET = os.getenv("SESSION_SECRET")
if not SESSION_SECRET:
    raise RuntimeError("SESSION_SECRET environment variable is required")

# Default cookie TTL: 24 hours (86400 seconds)
SESSION_COOKIE_MAX_AGE_SECONDS = int(os.getenv("SESSION_COOKIE_MAX_AGE_SECONDS", "86400"))

app = FastAPI(
    title=f"TheBoys Application Node ({NODE_ID}) [Contract Verification Stub]",
    version="1.0.0",
)

# In-memory registry of active local WebSocket connections: connection_id -> WebSocket
active_connections: dict[UUID, WebSocket] = {}
user_connections: dict[int, set[UUID]] = {}

incoming_event_adapter = TypeAdapter(ClientIncomingEvent)


def get_allowed_origins() -> set[str]:
    raw = os.getenv("ALLOWED_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000")
    return {o.strip() for o in raw.split(",") if o.strip()}


def sign_session_cookie(
    user_id: int,
    issued_at: int | None = None,
    secret: str | None = None,
) -> str:
    """
    Generate cryptographically signed session cookie with timestamp (Review P2):
    format: '{user_id}.{issued_at}.{hmac_sha256}'
    Signed with SESSION_SECRET (Review P1).
    """
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
    """
    Verify session cookie cryptographic signature and expiration timestamp (Review P2).
    Signed with SESSION_SECRET (Review P1).
    """
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


@app.get("/health")
async def health_check():
    return {"status": "ok", "node_id": NODE_ID, "stub_mode": True}


@app.post(
    "/internal/deliver",
    response_model=InternalDeliverResponse,
    status_code=status.HTTP_200_OK,
    summary="Inter-node event delivery",
)
async def deliver_internal(
    request: InternalDeliverRequest,
    x_internal_secret: Annotated[str | None, Header(alias="X-Internal-Secret")] = None,
):
    current_secret = os.getenv("INTERNAL_SECRET")
    if not current_secret:
        raise RuntimeError("INTERNAL_SECRET environment variable is required")

    if not x_internal_secret or not hmac.compare_digest(x_internal_secret, current_secret):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid internal secret")

    delivered: list[UUID] = []
    missed: list[UUID] = []

    event_json = request.event.model_dump_json()

    for target in request.targets:
        ws = active_connections.get(target.connection_id)
        if ws is not None:
            try:
                await ws.send_text(event_json)
                delivered.append(target.connection_id)
            except Exception:
                missed.append(target.connection_id)
        else:
            missed.append(target.connection_id)

    return InternalDeliverResponse(delivered=delivered, missed=missed)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    # 1. Origin verification (Origin is required and must match allowed origins)
    origin = websocket.headers.get("origin")
    allowed_origins = get_allowed_origins()
    if not origin or origin not in allowed_origins:
        # Per ASGI spec, accept handshake before closing with custom code (4403)
        await websocket.accept()
        await websocket.close(code=4403, reason="Forbidden origin")
        return

    # 2. Check signed authentication session cookie with expiration
    auth_cookie = websocket.cookies.get("session")
    user_id = verify_session_cookie(auth_cookie)
    if user_id is None:
        # Close with 4401 Unauthorized if missing, expired, or signature invalid
        await websocket.accept()
        await websocket.close(code=4401, reason="Unauthorized")
        return

    # 3. Connection accepted & registered in active node connections
    await websocket.accept()
    connection_id = uuid4()
    active_connections[connection_id] = websocket
    user_connections.setdefault(user_id, set()).add(connection_id)

    try:
        while True:
            raw_text = await websocket.receive_text()
            try:
                data = json.loads(raw_text)
                event = incoming_event_adapter.validate_python(data)
            except Exception as e:
                # Send error frame back on schema violation
                await websocket.send_text(
                    json.dumps({
                        "type": "error",
                        "code": "INVALID_PAYLOAD",
                        "message": str(e),
                    })
                )
                continue

            # Process validated events (Protocol validation stub):
            # In stub mode, we do NOT emit synthetic database records or fake seq numbers (Review 3.2).
            # Business logic requiring PostgreSQL (monotonic last_seq increment, session persistence,
            # history slices) belongs to the database integration phase.
            if event.type == "ping":
                # Alive heartbeat acknowledgement
                pass
            elif event.type == "send_message":
                # Reject execution in contract-stub mode: cannot allocate real monotonic seq without DB
                await websocket.send_text(
                    json.dumps({
                        "type": "error",
                        "code": "INTERNAL_ERROR",
                        "message": "Persistence layer offline: running in contract verification stub mode. Real monotonic seq allocation requires PostgreSQL.",
                        "client_msg_id": str(event.client_msg_id),
                    })
                )
            elif event.type == "read":
                # Real read position updating requires database check up_to_seq <= last_seq
                await websocket.send_text(
                    json.dumps({
                        "type": "error",
                        "code": "INTERNAL_ERROR",
                        "message": "Persistence layer offline: running in contract verification stub mode. Read position tracking requires PostgreSQL.",
                    })
                )
            elif event.type == "sync":
                # History querying requires PostgreSQL messages table
                await websocket.send_text(
                    json.dumps({
                        "type": "error",
                        "code": "INTERNAL_ERROR",
                        "message": "Persistence layer offline: running in contract verification stub mode. History sync requires PostgreSQL.",
                    })
                )
            elif event.type == "typing":
                # Ephemeral typing notification (optional UX extension)
                pass
    except WebSocketDisconnect:
        pass
    finally:
        active_connections.pop(connection_id, None)
        if user_id in user_connections:
            user_connections[user_id].discard(connection_id)
            if not user_connections[user_id]:
                del user_connections[user_id]


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("services.app.main:app", host="0.0.0.0", port=8000, reload=True)
