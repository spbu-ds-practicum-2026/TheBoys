import hashlib
import hmac
import json
import os
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

# Enforce mandatory INTERNAL_SECRET per TR
INTERNAL_SECRET = os.getenv("INTERNAL_SECRET")
if not INTERNAL_SECRET:
    raise RuntimeError("INTERNAL_SECRET environment variable is required")

SESSION_SECRET = os.getenv("SESSION_SECRET", INTERNAL_SECRET)

app = FastAPI(title=f"TheBoys Application Node ({NODE_ID})", version="1.0.0")

# In-memory registry of active local WebSocket connections: connection_id -> WebSocket
active_connections: dict[UUID, WebSocket] = {}
user_connections: dict[int, set[UUID]] = {}

incoming_event_adapter = TypeAdapter(ClientIncomingEvent)


def get_allowed_origins() -> set[str]:
    raw = os.getenv("ALLOWED_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000")
    return {o.strip() for o in raw.split(",") if o.strip()}


def sign_session_cookie(user_id: int) -> str:
    """Generate cryptographically signed session cookie value: '{user_id}.{hmac_sha256}'."""
    sig = hmac.new(SESSION_SECRET.encode(), str(user_id).encode(), hashlib.sha256).hexdigest()
    return f"{user_id}.{sig}"


def verify_session_cookie(cookie_val: str | None) -> int | None:
    """Verify session cookie cryptographic signature and extract user_id."""
    if not cookie_val or "." not in cookie_val:
        return None
    parts = cookie_val.split(".", 1)
    if len(parts) != 2:
        return None
    user_id_str, sig = parts
    expected_sig = hmac.new(SESSION_SECRET.encode(), user_id_str.encode(), hashlib.sha256).hexdigest()
    if hmac.compare_digest(sig, expected_sig):
        try:
            return int(user_id_str)
        except ValueError:
            return None
    return None


@app.get("/health")
async def health_check():
    return {"status": "ok", "node_id": NODE_ID}


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

    # 2. Check signed authentication session cookie
    auth_cookie = websocket.cookies.get("session")
    user_id = verify_session_cookie(auth_cookie)
    if user_id is None:
        # Close with 4401 Unauthorized if missing or signature invalid
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

            # Process validated events
            if event.type == "ping":
                await websocket.send_text(
                    json.dumps({
                        "type": "dialog_sync",
                        "dialogs": [],
                    })
                )
            elif event.type == "send_message":
                # Stub ack for client verification
                await websocket.send_text(
                    json.dumps({
                        "type": "ack",
                        "client_msg_id": str(event.client_msg_id),
                        "conversation_id": event.conversation_id,
                        "seq": 1,
                        "created_at": "2026-10-29T12:00:00Z",
                    })
                )
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
