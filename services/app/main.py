import os
from typing import Annotated
from uuid import UUID
from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.responses import JSONResponse

from services.app.schemas import (
    InternalDeliverRequest,
    InternalDeliverResponse,
)

NODE_ID = os.getenv("NODE_ID", "app-1")
INTERNAL_SECRET = os.getenv("INTERNAL_SECRET", "super-secret-internal-key")
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")

app = FastAPI(title=f"TheBoys Application Node ({NODE_ID})", version="1.0.0")

# In-memory registry of active local WebSocket connections: connection_id -> WebSocket
active_connections: dict[UUID, WebSocket] = {}


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
    if not x_internal_secret or x_internal_secret != INTERNAL_SECRET:
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
    # Origin verification
    origin = websocket.headers.get("origin")
    if ALLOWED_ORIGINS != ["*"] and origin and origin not in ALLOWED_ORIGINS:
        await websocket.close(code=4403, reason="Forbidden origin")
        return

    # Check authentication cookie
    auth_cookie = websocket.cookies.get("session")
    if not auth_cookie:
        # Close with 4401 Unauthorized if not authenticated
        await websocket.close(code=4401, reason="Unauthorized")
        return

    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            # Echo / stub for contract validation
            await websocket.send_text(data)
    except WebSocketDisconnect:
        pass


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("services.app.main:app", host="0.0.0.0", port=8000, reload=True)
