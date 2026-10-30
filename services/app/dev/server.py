"""ТОЛЬКО ДЛЯ РАЗРАБОТКИ ИНТЕРФЕЙСА. Заменяется настоящим API узла приложения.

Один процесс, всё состояние в памяти. Реализует REST из services/app/README.md и /ws по схемам
services/app/schemas (контракт PR #4): seq выдаётся как last_seq + 1, повтор по client_msg_id
возвращает уже сохранённое сообщение и номер не расходует. Рабочий services/app/main.py этот модуль
не импортирует.

Запуск из корня репозитория:
    python -m uvicorn services.app.dev.server:app --reload --port 8000
Разорвать все WebSocket-подключения (проверка потери связи):
    curl -X POST localhost:8000/dev/drop-connections
"""
import hashlib
import hmac
import json
import os
import re
import time
from datetime import datetime, timezone
from itertools import count
from uuid import UUID, uuid4

from fastapi import FastAPI, Header, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, TypeAdapter

from services.app.schemas import (
    ClientIncomingEvent,
    DialogSyncItem,
    ErrorCode,
    ServerAckMessage,
    ServerChatMessage,
    ServerDialogSyncMessage,
    ServerErrorMessage,
    ServerHistoryMessage,
    ServerReadAckMessage,
    TextPayload,
    TrackPayload,
)
from services.app.web.pages import mount_web

SESSION_SECRET = os.getenv("SESSION_SECRET", "dev-only-secret").encode()
SESSION_COOKIE_MAX_AGE_SECONDS = int(os.getenv("SESSION_COOKIE_MAX_AGE_SECONDS", "86400"))
COOKIE = "session"

# ~26 мс звука на кадр MPEG-1 Layer III 128 кбит/с 44,1 кГц без заполнения; тишина, но плеер её декодирует.
MP3_FRAME = b"\xff\xfb\x90\x00" + b"\x00" * 413
FRAME_SECONDS = 1152 / 44100


# ---------------------------------------------------------------------------
# Данные в памяти
# ---------------------------------------------------------------------------

def _track(n: int, title: str, artist: str, duration_s: int) -> dict:
    return {
        "id": str(UUID(int=n)),
        "title": title,
        "artist": artist,
        "duration_s": duration_s,
        "audio": MP3_FRAME * int(duration_s / FRAME_SECONDS),
    }


TRACKS = [
    _track(1, "Midnight Echoes", "The Boys Band", 42),
    _track(2, "Лунный свет", "Северное сияние", 35),
    _track(3, "Neon Rain", "Synth Collective", 48),
    _track(4, "Тёплый ветер", "Северное сияние", 30),
    _track(5, "Glass Highway", "The Boys Band", 55),
]
TRACKS_BY_ID = {t["id"]: t for t in TRACKS}

users: dict[int, dict] = {}
conversations: dict[int, dict] = {}
connections: dict[UUID, dict] = {}  # connection_id -> {"user_id", "ws"}
user_ids = count(1)
conversation_ids = count(1)

incoming_adapter = TypeAdapter(ClientIncomingEvent)


# ---------------------------------------------------------------------------
# Вход: cookie «{user_id}.{issued_at}.{hmac}» со сроком действия, как в services/app/main.py
# (sign_session_cookie / verify_session_cookie). main.py не импортируется: ему нужны секреты при загрузке.
# ---------------------------------------------------------------------------

def _cookie_value(user_id: int, issued_at: int | None = None) -> str:
    stamp = int(time.time()) if issued_at is None else issued_at
    payload = f"{user_id}.{stamp}"
    signature = hmac.new(SESSION_SECRET, payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def _user_from_cookie(value: str | None) -> dict | None:
    parts = (value or "").split(".")
    if len(parts) != 3:
        return None
    raw_id, raw_stamp, signature = parts
    expected = hmac.new(SESSION_SECRET, f"{raw_id}.{raw_stamp}".encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        user_id, issued_at = int(raw_id), int(raw_stamp)
    except ValueError:
        return None
    now = int(time.time())
    if issued_at > now + 60 or now - issued_at > SESSION_COOKIE_MAX_AGE_SECONDS:  # будущее время / срок истёк
        return None
    return users.get(user_id)


def get_user(request: Request) -> dict | None:
    return _user_from_cookie(request.cookies.get(COOKIE))


def _allowed_origins() -> set[str]:
    raw = os.getenv("ALLOWED_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000")
    return {o.strip() for o in raw.split(",") if o.strip()}


def _hash_password(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100_000).hex()


def _public(user: dict) -> dict:
    return {"id": user["id"], "login": user["login"]}


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"code": code, "message": message}, status_code=status)


def _with_cookie(response: JSONResponse, user: dict) -> JSONResponse:
    response.set_cookie(
        COOKIE, _cookie_value(user["id"]), max_age=SESSION_COOKIE_MAX_AGE_SECONDS,
        httponly=True, samesite="lax", path="/",
    )
    return response


app = FastAPI(title="Boysic — dev-сервер интерфейса", docs_url=None, redoc_url=None)
mount_web(app, get_user)


class Credentials(BaseModel):
    login: str
    password: str


@app.post("/api/register")
def register(body: Credentials):
    login = body.login.strip()
    if not login or not body.password:
        return _error(422, "INVALID_INPUT", "Укажите логин и пароль.")
    if any(u["login"].lower() == login.lower() for u in users.values()):
        return _error(409, "LOGIN_TAKEN", "Логин уже занят.")
    salt = os.urandom(16)
    user = {"id": next(user_ids), "login": login, "salt": salt, "hash": _hash_password(body.password, salt)}
    users[user["id"]] = user
    return _with_cookie(JSONResponse({"user": _public(user)}, status_code=201), user)


@app.post("/api/login")
def login(body: Credentials):
    user = next((u for u in users.values() if u["login"].lower() == body.login.strip().lower()), None)
    if user is None or not hmac.compare_digest(user["hash"], _hash_password(body.password, user["salt"])):
        return _error(401, "INVALID_CREDENTIALS", "Неверный логин или пароль.")
    return _with_cookie(JSONResponse({"user": _public(user)}), user)


@app.post("/api/logout")
def logout():
    response = Response(status_code=204)
    response.delete_cookie(COOKIE, path="/")
    return response


# ---------------------------------------------------------------------------
# Каталог и аудио
# ---------------------------------------------------------------------------

def _require_user(request: Request) -> dict | None:
    return get_user(request)


@app.get("/api/tracks")
def list_tracks(request: Request, q: str = ""):
    if not _require_user(request):
        return _error(401, "UNAUTHORIZED", "Требуется вход.")
    needle = q.strip().lower()
    found = [t for t in TRACKS if needle in t["title"].lower() or needle in t["artist"].lower()]
    return [{k: t[k] for k in ("id", "title", "artist", "duration_s")} for t in found]


@app.get("/api/tracks/{track_id}/stream")
def stream_track(track_id: str, request: Request, range: str | None = Header(default=None)):
    if not _require_user(request):
        return _error(401, "UNAUTHORIZED", "Требуется вход.")
    track = TRACKS_BY_ID.get(track_id)
    if track is None:
        return _error(404, "TRACK_NOT_FOUND", "Трек не найден.")
    data = track["audio"]
    size = len(data)
    base = {"Accept-Ranges": "bytes", "Content-Type": "audio/mpeg"}

    match = re.fullmatch(r"bytes=(\d*)-(\d*)", range or "")
    if not match or match.group(1) == match.group(2) == "":
        return Response(data, headers={**base, "Content-Length": str(size)})

    first, last = match.groups()
    if first == "":  # bytes=-N — последние N байт
        start, end = max(size - int(last), 0), size - 1
    else:
        start = int(first)
        end = min(int(last), size - 1) if last else size - 1  # конец за пределами файла усекается
    if start >= size or start > end:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
    chunk = data[start:end + 1]
    return Response(
        chunk, status_code=206,
        headers={**base, "Content-Range": f"bytes {start}-{end}/{size}", "Content-Length": str(len(chunk))},
    )


# ---------------------------------------------------------------------------
# Пользователи и диалоги
# ---------------------------------------------------------------------------

@app.get("/api/users")
def find_users(request: Request, login: str = ""):
    me = _require_user(request)
    if not me:
        return _error(401, "UNAUTHORIZED", "Требуется вход.")
    needle = login.strip().lower().lstrip("@")
    found = [u for u in users.values() if u["id"] != me["id"] and needle and needle in u["login"].lower()]
    return [_public(u) for u in found[:10]]


@app.get("/api/users/{user_id}/status")
def user_status(user_id: int, request: Request):
    if not _require_user(request):
        return _error(401, "UNAUTHORIZED", "Требуется вход.")
    return {"online": any(c["user_id"] == user_id for c in connections.values())}


def _unread(conv: dict, user_id: int) -> int:
    last_read = conv["last_read"].get(user_id, 0)
    return sum(1 for m in conv["messages"] if m["sender_id"] != user_id and m["seq"] > last_read)


def _conversation_view(conv: dict, user_id: int) -> dict:
    peer_id = conv["members"][0] if conv["members"][1] == user_id else conv["members"][1]
    return {
        "id": conv["id"],
        "peer": _public(users[peer_id]),
        "last_seq": conv["last_seq"],
        "unread_count": _unread(conv, user_id),
    }


@app.get("/api/conversations")
def list_conversations(request: Request):
    me = _require_user(request)
    if not me:
        return _error(401, "UNAUTHORIZED", "Требуется вход.")
    return [_conversation_view(c, me["id"]) for c in conversations.values() if me["id"] in c["members"]]


class OpenConversation(BaseModel):
    peer_id: int


@app.post("/api/conversations")
def open_conversation(body: OpenConversation, request: Request):
    me = _require_user(request)
    if not me:
        return _error(401, "UNAUTHORIZED", "Требуется вход.")
    if body.peer_id == me["id"] or body.peer_id not in users:
        return _error(404, "USER_NOT_FOUND", "Пользователь не найден.")
    members = tuple(sorted((me["id"], body.peer_id)))  # одна пара — один диалог
    conv = next((c for c in conversations.values() if c["members"] == members), None)
    if conv is None:
        conv = {"id": next(conversation_ids), "members": members, "last_seq": 0, "messages": [], "last_read": {}}
        conversations[conv["id"]] = conv
    return _conversation_view(conv, me["id"])


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------

def _chat_message(raw: dict) -> dict:
    payload = TextPayload(**raw["payload"]) if raw["kind"] == "text" else TrackPayload(**raw["payload"])
    event = ServerChatMessage(
        conversation_id=raw["conversation_id"], seq=raw["seq"], sender_id=raw["sender_id"],
        client_msg_id=raw["client_msg_id"], kind=raw["kind"], payload=payload, created_at=raw["created_at"],
    )
    return event.model_dump(mode="json")


async def _send(ws: WebSocket, event) -> None:
    await ws.send_text(event.model_dump_json())


async def _deliver_to_user(user_id: int, event: dict, skip: UUID | None = None) -> None:
    for connection_id, conn in list(connections.items()):
        if conn["user_id"] == user_id and connection_id != skip:
            try:
                await conn["ws"].send_text(json.dumps(event))
            except Exception:
                connections.pop(connection_id, None)


def _dialog_sync(user_id: int) -> ServerDialogSyncMessage:
    return ServerDialogSyncMessage(dialogs=[
        DialogSyncItem(conversation_id=c["id"], last_seq=c["last_seq"], unread_count=_unread(c, user_id))
        for c in conversations.values() if user_id in c["members"]
    ])


def _error_event(code: ErrorCode, message: str, client_msg_id: UUID | None = None) -> ServerErrorMessage:
    return ServerErrorMessage(code=code, message=message, client_msg_id=client_msg_id)


async def _handle_send(ws: WebSocket, connection_id: UUID, user_id: int, event) -> None:
    conv = conversations.get(event.conversation_id)
    if conv is None:
        await _send(ws, _error_event(ErrorCode.CONVERSATION_NOT_FOUND, "Диалог не найден.", event.client_msg_id))
        return
    if user_id not in conv["members"]:
        await _send(ws, _error_event(ErrorCode.NOT_A_MEMBER, "Вы не участник диалога.", event.client_msg_id))
        return

    # Повтор: ищем (отправитель, client_msg_id) до выдачи номера — seq не расходуется.
    stored = next(
        (m for m in conv["messages"] if m["sender_id"] == user_id and m["client_msg_id"] == str(event.client_msg_id)),
        None,
    )
    is_new = stored is None
    if is_new:
        if event.kind == "track":
            track = TRACKS_BY_ID.get(str(event.payload.track_id))
            if track is None:
                await _send(ws, _error_event(ErrorCode.TRACK_NOT_FOUND, "Трек не найден.", event.client_msg_id))
                return
            payload = {k: track[k] for k in ("title", "artist", "duration_s")} | {"track_id": track["id"]}
        else:
            payload = {"text": event.payload.text}
        conv["last_seq"] += 1
        stored = {
            "conversation_id": conv["id"], "seq": conv["last_seq"], "sender_id": user_id,
            "client_msg_id": str(event.client_msg_id), "kind": event.kind, "payload": payload,
            "created_at": datetime.now(timezone.utc),
        }
        conv["messages"].append(stored)

    await _send(ws, ServerAckMessage(
        client_msg_id=event.client_msg_id, conversation_id=conv["id"], seq=stored["seq"], created_at=stored["created_at"],
    ))
    if is_new:
        message = _chat_message(stored)
        for member in conv["members"]:
            await _deliver_to_user(member, message, skip=connection_id if member == user_id else None)


async def _handle_read(ws: WebSocket, user_id: int, event) -> None:
    conv = conversations.get(event.conversation_id)
    if conv is None or user_id not in conv["members"]:
        await _send(ws, _error_event(ErrorCode.NOT_A_MEMBER, "Вы не участник диалога."))
        return
    if event.up_to_seq > conv["last_seq"]:
        await _send(ws, _error_event(ErrorCode.INVALID_READ_POSITION, "Позиция больше последнего сообщения."))
        return
    position = max(conv["last_read"].get(user_id, 0), event.up_to_seq)
    conv["last_read"][user_id] = position
    await _send(ws, ServerReadAckMessage(
        conversation_id=conv["id"], last_read_seq=position, unread_count=_unread(conv, user_id),
    ))


async def _handle_sync(ws: WebSocket, user_id: int, event) -> None:
    conv = conversations.get(event.conversation_id)
    if conv is None or user_id not in conv["members"]:
        await _send(ws, _error_event(ErrorCode.NOT_A_MEMBER, "Вы не участник диалога."))
        return
    messages = conv["messages"]
    if event.before_seq is not None:
        older = [m for m in messages if m["seq"] < event.before_seq]
        chunk = older[-event.limit:]  # ближайшие к before_seq, по возрастанию seq
        has_more = bool(chunk) and chunk[0]["seq"] > 1
    else:
        newer = [m for m in messages if m["seq"] > (event.since_seq or 0)]
        chunk = newer[:event.limit]
        has_more = len(newer) > len(chunk)
    await _send(ws, ServerHistoryMessage(
        conversation_id=conv["id"], messages=[_chat_message(m) for m in chunk], has_more=has_more,
    ))


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    # Как в services/app/main.py: сначала Origin (4403), затем cookie (4401); рукопожатие принимаем,
    # чтобы клиент получил код закрытия.
    origin = ws.headers.get("origin")
    await ws.accept()
    if not origin or origin not in _allowed_origins():
        await ws.close(code=4403, reason="Forbidden origin")
        return
    user = _user_from_cookie(ws.cookies.get(COOKIE))
    if user is None:
        await ws.close(code=4401, reason="Unauthorized")
        return

    connection_id = uuid4()
    connections[connection_id] = {"user_id": user["id"], "ws": ws}
    try:
        await _send(ws, _dialog_sync(user["id"]))
        while True:
            raw = await ws.receive_text()
            try:
                event = incoming_adapter.validate_python(json.loads(raw))
            except Exception as exc:
                await _send(ws, _error_event(ErrorCode.INVALID_PAYLOAD, str(exc)))
                continue
            if event.type == "ping":
                await _send(ws, _dialog_sync(user["id"]))
            elif event.type == "send_message":
                await _handle_send(ws, connection_id, user["id"], event)
            elif event.type == "read":
                await _handle_read(ws, user["id"], event)
            elif event.type == "sync":
                await _handle_sync(ws, user["id"], event)
    except WebSocketDisconnect:
        pass
    finally:
        connections.pop(connection_id, None)


@app.post("/dev/drop-connections")
async def drop_connections():
    """Разрывает все WebSocket-подключения: клиенты должны переподключиться сами."""
    dropped = list(connections.values())
    connections.clear()
    for conn in dropped:
        try:
            await conn["ws"].close(code=1012)
        except Exception:
            pass
    return {"dropped": len(dropped)}


@app.get("/health")
def health():
    return {"status": "ok", "mode": "dev"}
