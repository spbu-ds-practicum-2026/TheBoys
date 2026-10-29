import hashlib
import hmac
import os
import re
from pathlib import Path
from uuid import UUID, uuid4
from fastapi import FastAPI, File, Form, Header, HTTPException, Request, Response, UploadFile, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(
    title="Boysic — Music Messenger Application Node (Web & API)",
    description="Frontend UI layer and API of the Application Node per TR specification.",
    version="1.0.0",
)

# Mount Static Files (CSS, JS including htmx.min.js, IMG)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

# Jinja2 Templates
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# Session signature secret
SECRET_KEY = os.getenv("SECRET_KEY", "boysic-session-secret-key-2026")

# Valid MPEG-1 Layer III 128 kbps, 44.1 kHz stereo frame (without padding bit = 417 bytes exact)
# Formula: floor(144 * 128000 / 44100) = 417 bytes per frame
# 4 bytes header (b'\xff\xfb\x90\x00') + 413 bytes payload = 417 bytes
_MPEG_FRAME_417 = b"\xff\xfb\x90\x00" + b"\x00" * 413
_DEFAULT_MP3_STREAM = _MPEG_FRAME_417 * 120  # ~50 KB valid, playable MP3 stream

# Storage nodes for hash partitioning per TR: "Узлов не меньше трёх, каждый трек лежит на двух из них"
STORAGE_NODES = ["storage-1", "storage-2", "storage-3"]


def get_replicas_for_track(track_id: str) -> list[str]:
    """Consistent hash partitioning: calculates 2 storage node replicas for a given track UUID."""
    val = hash(track_id)
    idx1 = val % len(STORAGE_NODES)
    idx2 = (idx1 + 1) % len(STORAGE_NODES)
    return [STORAGE_NODES[idx1], STORAGE_NODES[idx2]]


# Catalog of Tracks with UUIDs matching contract of PR #4
TRACKS_CATALOG: list[dict] = [
    {
        "id": "00000000-0000-0000-0000-000000000001",
        "title": "Midnight Echoes",
        "artist": "The Boys Band",
        "duration": "3:42",
        "duration_s": 222,
        "format": "MP3 (128 kbps)",
        "replicas": get_replicas_for_track("00000000-0000-0000-0000-000000000001"),
    },
    {
        "id": "00000000-0000-0000-0000-000000000002",
        "title": "Neon Sunset Drive",
        "artist": "Synthesia Core",
        "duration": "4:15",
        "duration_s": 255,
        "format": "MP3 (128 kbps)",
        "replicas": get_replicas_for_track("00000000-0000-0000-0000-000000000002"),
    },
    {
        "id": "00000000-0000-0000-0000-000000000003",
        "title": "Orbital Resonance",
        "artist": "Pavel & Dmitry",
        "duration": "2:58",
        "duration_s": 178,
        "format": "MP3 (128 kbps)",
        "replicas": get_replicas_for_track("00000000-0000-0000-0000-000000000003"),
    },
    {
        "id": "00000000-0000-0000-0000-000000000004",
        "title": "Consensus Beats",
        "artist": "Distributed Ensemble",
        "duration": "3:10",
        "duration_s": 190,
        "format": "MP3 (128 kbps)",
        "replicas": get_replicas_for_track("00000000-0000-0000-0000-000000000004"),
    },
]

# In-memory storage for user-uploaded MP3 streams: track_id -> bytes
USER_TRACKS_STORE: dict[str, bytes] = {}

# Users database for search and authentication per TR
USERS_DATABASE: list[dict] = [
    {
        "id": 1,
        "login": "alisa",
        "name": "Alice Smirnova",
        "password_hash": hashlib.sha256(b"alice123").hexdigest(),
        "node_id": "app-2",
        "status": "online",
    },
    {
        "id": 2,
        "login": "oleg",
        "name": "Oleg Ivanov",
        "password_hash": hashlib.sha256(b"oleg123").hexdigest(),
        "node_id": "app-1",
        "status": "online",
    },
    {
        "id": 3,
        "login": "pavel",
        "name": "Pavel Grigoryev",
        "password_hash": hashlib.sha256(b"pavel123").hexdigest(),
        "node_id": "app-1",
        "status": "offline",
    },
    {
        "id": 4,
        "login": "artem",
        "name": "Artem Eremenko",
        "password_hash": hashlib.sha256(b"artem123").hexdigest(),
        "node_id": "app-1",
        "status": "online",
    },
    {
        "id": 5,
        "login": "byzov",
        "name": "Dmitry Byzov",
        "password_hash": hashlib.sha256(b"dmitry123").hexdigest(),
        "node_id": "app-1",
        "status": "online",
    },
    {
        "id": 6,
        "login": "bob",
        "name": "Bob Stone",
        "password_hash": hashlib.sha256(b"bob123").hexdigest(),
        "node_id": "app-2",
        "status": "online",
    },
]

# Conversations data store per TR
CONVERSATIONS_DATA: list[dict] = [
    {
        "id": 1,
        "partner_id": 1,
        "name": "Alice Smirnova",
        "name_ru": "Алиса Смирнова",
        "handle": "@alisa",
        "initials": "AS",
        "status": "online",
        "status_text": "online [node app-2]",
        "status_text_ru": "в сети [узел app-2]",
        "unread_count": 2,
        "last_seq": 4,
        "last_time": "19:42",
        "last_message": "Hello! Full-text search and storage are ready...",
    },
    {
        "id": 2,
        "partner_id": 2,
        "name": "Oleg Ivanov",
        "name_ru": "Олег Иванов",
        "handle": "@oleg",
        "initials": "OI",
        "status": "online",
        "status_text": "online [node app-1]",
        "status_text_ru": "в сети [узел app-1]",
        "unread_count": 1,
        "last_seq": 2,
        "last_time": "19:30",
        "last_message": "🎵 Neon Sunset Drive — Synthesia Core",
    },
    {
        "id": 3,
        "partner_id": 3,
        "name": "Pavel Grigoryev",
        "name_ru": "Павел Григорьев",
        "handle": "@pavel",
        "initials": "PG",
        "status": "offline",
        "status_text": "last seen 45 min ago",
        "status_text_ru": "был(а) в сети 45 мин назад",
        "unread_count": 0,
        "last_seq": 1,
        "last_time": "18:12",
        "last_message": "Database schema committed",
    },
    {
        "id": 4,
        "partner_id": 4,
        "name": "Artem Eremenko",
        "name_ru": "Артём Еременко",
        "handle": "@artem",
        "initials": "AE",
        "status": "online",
        "status_text": "online [node app-1]",
        "status_text_ru": "в сети [узел app-1]",
        "unread_count": 0,
        "last_seq": 1,
        "last_time": "17:55",
        "last_message": "Docker Compose cluster is up",
    },
]


def is_htmx_request(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


def sign_session(user_id: int) -> str:
    sig = hmac.new(SECRET_KEY.encode(), str(user_id).encode(), hashlib.sha256).hexdigest()
    return f"{user_id}.{sig}"


def verify_session(cookie: str | None) -> int | None:
    if not cookie or "." not in cookie:
        return None
    parts = cookie.split(".", 1)
    if len(parts) != 2:
        return None
    user_id_str, sig = parts
    expected = hmac.new(SECRET_KEY.encode(), user_id_str.encode(), hashlib.sha256).hexdigest()
    if hmac.compare_digest(sig, expected):
        try:
            return int(user_id_str)
        except ValueError:
            return None
    return None


def get_common_context(request: Request, active_tab: str = "music") -> dict:
    return {
        "request": request,
        "active_tab": active_tab,
        "tracks": TRACKS_CATALOG,
        "dialogs": CONVERSATIONS_DATA,
        "current_track": TRACKS_CATALOG[0],
    }


# -----------------------------------------------------------------------------
# Canonical Section Views (Supporting full page loads and HTMX partial swaps)
# -----------------------------------------------------------------------------

# TR: "После регистрации пользователь попадает в раздел «Музыка»"
@app.get("/", response_class=HTMLResponse)
@app.get("/music", response_class=HTMLResponse)
async def get_music_view(request: Request):
    ctx = get_common_context(request, active_tab="music")
    if is_htmx_request(request):
        return templates.TemplateResponse(request=request, name="music/catalog.html", context=ctx)
    return templates.TemplateResponse(request=request, name="base.html", context=ctx)


@app.get("/chats", response_class=HTMLResponse)
async def get_chats_view(request: Request):
    ctx = get_common_context(request, active_tab="chats")
    if is_htmx_request(request):
        return templates.TemplateResponse(request=request, name="messenger/chats_view.html", context=ctx)
    return templates.TemplateResponse(request=request, name="base.html", context=ctx)


@app.get("/import", response_class=HTMLResponse)
async def get_import_view(request: Request):
    ctx = get_common_context(request, active_tab="import")
    if is_htmx_request(request):
        return templates.TemplateResponse(request=request, name="import/import_placeholder.html", context=ctx)
    return templates.TemplateResponse(request=request, name="base.html", context=ctx)


@app.get("/settings", response_class=HTMLResponse)
async def get_settings_view(request: Request):
    ctx = get_common_context(request, active_tab="settings")
    if is_htmx_request(request):
        return templates.TemplateResponse(request=request, name="settings/settings.html", context=ctx)
    return templates.TemplateResponse(request=request, name="base.html", context=ctx)


@app.get("/htmx/views/{view_name}", response_class=HTMLResponse)
async def get_htmx_partial_alias(request: Request, view_name: str):
    view_map = {
        "music": ("music/catalog.html", "music"),
        "chats": ("messenger/chats_view.html", "chats"),
        "import": ("import/import_placeholder.html", "import"),
        "settings": ("settings/settings.html", "settings"),
    }
    if view_name not in view_map:
        raise HTTPException(status_code=404, detail="View not found")
    tpl, tab = view_map[view_name]
    ctx = get_common_context(request, active_tab=tab)
    return templates.TemplateResponse(request=request, name=tpl, context=ctx)


# -----------------------------------------------------------------------------
# REST API (Tracks, Audio Streaming with RFC 9110 Range, Conversations, Auth)
# -----------------------------------------------------------------------------

# TR: "Каталог треков и поиск по названию и исполнителю" GET /api/tracks?q=...
@app.get("/api/tracks", response_class=JSONResponse)
async def list_tracks(q: str | None = None):
    results = TRACKS_CATALOG
    if q:
        term = q.lower().strip()
        results = [t for t in results if term in t["title"].lower() or term in t["artist"].lower()]
    return {"tracks": results}


# Upload new MP3 file and register for streaming
@app.post("/api/tracks/upload", response_class=JSONResponse)
async def upload_track(
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    artist: str | None = Form(default=None),
):
    contents = await file.read()
    if not contents:
        contents = _MPEG_FRAME_417 * 100

    new_id = str(uuid4())
    track_title = title.strip() if title else Path(file.filename or "Track").stem
    track_artist = artist.strip() if artist else "Local Artist"

    USER_TRACKS_STORE[new_id] = contents

    new_track_entry = {
        "id": new_id,
        "title": track_title,
        "artist": track_artist,
        "duration": "3:30",
        "duration_s": 210,
        "format": "MP3 (128 kbps)",
        "replicas": get_replicas_for_track(new_id),
    }
    TRACKS_CATALOG.insert(0, new_track_entry)
    return {"status": "ok", "track": new_track_entry}


# TR: "GET /api/tracks/{id}/stream" with RFC 9110 compliant Range handling
@app.get("/api/tracks/{track_id}/stream")
async def stream_track(track_id: str, range: str | None = Header(default=None)):
    lookup_id = track_id
    if track_id.startswith("track-"):
        try:
            num = int(track_id.split("-")[-1])
            lookup_id = f"00000000-0000-0000-0000-{num:012d}"
        except ValueError:
            pass

    data = USER_TRACKS_STORE.get(lookup_id) or USER_TRACKS_STORE.get(track_id)
    if data is None:
        matched = next((t for t in TRACKS_CATALOG if t["id"] in (lookup_id, track_id)), None)
        if not matched:
            raise HTTPException(status_code=404, detail="Track not found")
        data = _DEFAULT_MP3_STREAM

    total_size = len(data)

    if range:
        match = re.match(r"bytes=(\d+)-(\d*)", range)
        if match:
            start = int(match.group(1))
            end_str = match.group(2)

            # Per RFC 9110: 416 returned only if start >= total_size
            if start >= total_size:
                return Response(
                    status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
                    headers={"Content-Range": f"bytes */{total_size}"},
                )

            # If end is omitted or beyond file size, truncate to total_size - 1
            end = min(int(end_str), total_size - 1) if end_str else total_size - 1

            if start > end:
                return Response(
                    status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
                    headers={"Content-Range": f"bytes */{total_size}"},
                )

            chunk = data[start : end + 1]
            headers = {
                "Content-Range": f"bytes {start}-{end}/{total_size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(len(chunk)),
                "Content-Type": "audio/mpeg",
            }
            return Response(content=chunk, status_code=status.HTTP_206_PARTIAL_CONTENT, headers=headers)

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(total_size),
        "Content-Type": "audio/mpeg",
    }
    return Response(content=data, status_code=status.HTTP_200_OK, headers=headers)


# TR: "GET /api/conversations"
@app.get("/api/conversations", response_class=JSONResponse)
async def list_conversations():
    return {"conversations": CONVERSATIONS_DATA}


@app.get("/api/dialogs", response_class=JSONResponse)
async def list_dialogs_alias():
    return {"dialogs": CONVERSATIONS_DATA}


# Mark conversation as read
@app.post("/api/conversations/{conv_id}/read", response_class=JSONResponse)
async def mark_conversation_read(conv_id: int):
    conv = next((c for c in CONVERSATIONS_DATA if c["id"] == conv_id), None)
    if conv:
        conv["unread_count"] = 0
    return {"status": "ok", "conversation_id": conv_id, "unread_count": 0}


# Send message to conversation (assigns monotonic seq per TR)
@app.post("/api/conversations/{conv_id}/messages", response_class=JSONResponse)
async def post_conversation_message(conv_id: int, request: Request):
    conv = next((c for c in CONVERSATIONS_DATA if c["id"] == conv_id), None)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    body = await request.json()
    conv["last_seq"] += 1
    assigned_seq = conv["last_seq"]
    conv["last_message"] = body.get("text") or body.get("title") or "New message"

    return {"status": "ok", "seq": assigned_seq}


# TR: "GET /api/users?login=..."
@app.get("/api/users", response_class=JSONResponse)
async def search_users(login: str | None = None):
    results = USERS_DATABASE
    if login:
        q = login.lower().lstrip("@").strip()
        results = [u for u in results if q in u["login"].lower() or q in u["name"].lower()]
    return {"users": [{"id": u["id"], "login": u["login"], "name": u["name"], "status": u["status"]} for u in results]}


# TR: "POST /api/register"
@app.post("/api/register", response_class=JSONResponse)
async def register_user(request: Request, response: Response):
    body = await request.json()
    username = body.get("username", "").strip()
    password = body.get("password", "")

    if not username or not password:
        raise HTTPException(status_code=400, detail="Username and password required")

    existing = next((u for u in USERS_DATABASE if u["login"] == username), None)
    if existing:
        raise HTTPException(status_code=409, detail="Username already exists")

    new_id = len(USERS_DATABASE) + 1
    new_user = {
        "id": new_id,
        "login": username,
        "name": username.capitalize(),
        "password_hash": hashlib.sha256(password.encode()).hexdigest(),
        "node_id": "app-1",
        "status": "online",
    }
    USERS_DATABASE.append(new_user)

    cookie = sign_session(new_id)
    response.set_cookie(key="session", value=cookie, httponly=True)
    return {
        "status": "ok",
        "user": {"id": new_id, "login": username, "name": new_user["name"]},
        "session_token": cookie,
    }


# TR: "POST /api/login"
@app.post("/api/login", response_class=JSONResponse)
async def login_user(request: Request, response: Response):
    body = await request.json()
    username = body.get("username", "").strip()
    password = body.get("password", "")

    user = next((u for u in USERS_DATABASE if u["login"] == username), None)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    req_hash = hashlib.sha256(password.encode()).hexdigest()
    if not hmac.compare_digest(req_hash, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    cookie = sign_session(user["id"])
    response.set_cookie(key="session", value=cookie, httponly=True)
    return {
        "status": "ok",
        "user": {"id": user["id"], "login": user["login"], "name": user["name"]},
        "session_token": cookie,
    }


# Current user profile
@app.get("/api/me", response_class=JSONResponse)
async def get_me(request: Request):
    cookie = request.cookies.get("session")
    user_id = verify_session(cookie)
    if not user_id:
        return {"authenticated": False}
    user = next((u for u in USERS_DATABASE if u["id"] == user_id), None)
    if not user:
        return {"authenticated": False}
    return {"authenticated": True, "user": {"id": user["id"], "login": user["login"], "name": user["name"]}}


# Health Check
@app.get("/health", response_class=JSONResponse)
async def health_check():
    return {"status": "ok", "service": "frontend"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("services.frontend.main:app", host="0.0.0.0", port=8000, reload=True)
