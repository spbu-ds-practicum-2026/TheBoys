import re
from pathlib import Path
from fastapi import FastAPI, Header, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(
    title="Boysic — Music Messenger Application Node",
    description="Application node implementing UI pages, music catalog, audio streaming with Range support, and chat contracts per TR.",
    version="1.0.0",
)

# Mount Static Files (CSS, JS including htmx.min.js, IMG)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

# Jinja2 Templates
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# Standard Catalog of Tracks (matching TR: MP3 files replicated on 2 storage nodes)
TRACKS_CATALOG = [
    {
        "id": "track-1",
        "title": "Midnight Echoes",
        "artist": "The Boys Band",
        "duration": "3:42",
        "duration_s": 222,
        "format": "MP3 (128 kbps)",
        "replicas": ["storage-1", "storage-2"],
    },
    {
        "id": "track-2",
        "title": "Neon Sunset Drive",
        "artist": "Synthesia Core",
        "duration": "4:15",
        "duration_s": 255,
        "format": "MP3 (128 kbps)",
        "replicas": ["storage-2", "storage-3"],
    },
    {
        "id": "track-3",
        "title": "Orbital Resonance",
        "artist": "Pavel & Dmitry",
        "duration": "2:58",
        "duration_s": 178,
        "format": "MP3 (128 kbps)",
        "replicas": ["storage-1", "storage-3"],
    },
    {
        "id": "track-4",
        "title": "Consensus Beats",
        "artist": "Distributed Ensemble",
        "duration": "3:10",
        "duration_s": 190,
        "format": "MP3 (128 kbps)",
        "replicas": ["storage-1", "storage-2"],
    },
]

# Standard Dialogs list with unread counters and online presence
DIALOGS_DATA = [
    {
        "id": 1,
        "name": "Alice Smirnova",
        "name_ru": "Алиса Смирнова",
        "handle": "@alisa",
        "initials": "AS",
        "status": "online",
        "status_text": "online [node app-2]",
        "status_text_ru": "в сети [узел app-2]",
        "unread_count": 2,
        "last_time": "19:42",
        "last_message": "Hello! Full-text search and storage are ready...",
    },
    {
        "id": 2,
        "name": "Oleg Ivanov",
        "name_ru": "Олег Иванов",
        "handle": "@oleg",
        "initials": "OI",
        "status": "online",
        "status_text": "online [node app-1]",
        "status_text_ru": "в сети [узел app-1]",
        "unread_count": 1,
        "last_time": "19:30",
        "last_message": "🎵 Midnight Echoes — The Boys Band",
    },
    {
        "id": 3,
        "name": "Pavel Grigoryev",
        "name_ru": "Павел Григорьев",
        "handle": "@pavel",
        "initials": "PG",
        "status": "offline",
        "status_text": "last seen 45 min ago",
        "status_text_ru": "был(а) в сети 45 мин назад",
        "unread_count": 0,
        "last_time": "18:12",
        "last_message": "Database schema committed",
    },
    {
        "id": 4,
        "name": "Artem Eremenko",
        "name_ru": "Артём Еременко",
        "handle": "@artem",
        "initials": "AE",
        "status": "online",
        "status_text": "online [node app-1]",
        "status_text_ru": "в сети [узел app-1]",
        "unread_count": 0,
        "last_time": "17:55",
        "last_message": "Docker Compose cluster is up",
    },
]

# Generate a minimal valid MPEG-1 Layer 3 silent stream buffer for demonstration
# Standard 418-byte frame for 128 kbps 44.1 kHz stereo
_MPEG_FRAME = b"\xff\xfb\x90\x00" + b"\x00" * 414
_SYNTHETIC_MP3_STREAM = _MPEG_FRAME * 120  # ~50 KB valid MP3 audio stream


def is_htmx_request(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


def get_common_context(request: Request, active_tab: str = "music") -> dict:
    return {
        "request": request,
        "active_tab": active_tab,
        "tracks": TRACKS_CATALOG,
        "dialogs": DIALOGS_DATA,
        "current_track": TRACKS_CATALOG[0],
    }


# Health check endpoint
@app.get("/health", response_class=JSONResponse)
async def health_check():
    return {"status": "ok", "service": "frontend", "node": "app-1"}


# -----------------------------------------------------------------------------
# HTML Views (supporting both full page load and HTMX partial swaps)
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


# Dedicated HTMX Partial View Endpoint
@app.get("/htmx/views/{view_name}", response_class=HTMLResponse)
async def get_htmx_view_partial(request: Request, view_name: str):
    if view_name == "music":
        ctx = get_common_context(request, active_tab="music")
        return templates.TemplateResponse(request=request, name="music/catalog.html", context=ctx)
    elif view_name == "chats":
        ctx = get_common_context(request, active_tab="chats")
        return templates.TemplateResponse(request=request, name="messenger/chats_view.html", context=ctx)
    elif view_name == "import":
        ctx = get_common_context(request, active_tab="import")
        return templates.TemplateResponse(request=request, name="import/import_placeholder.html", context=ctx)
    elif view_name == "settings":
        ctx = get_common_context(request, active_tab="settings")
        return templates.TemplateResponse(request=request, name="settings/settings.html", context=ctx)
    return HTMLResponse("<div class='htmx-empty'>Not found</div>", status_code=404)


# -----------------------------------------------------------------------------
# REST API (Tracks, Audio Streaming with Range header, Dialogs)
# -----------------------------------------------------------------------------

@app.get("/api/tracks", response_class=JSONResponse)
async def list_tracks():
    return {"tracks": TRACKS_CATALOG}


# TR: "клиент запрашивает трек через GET /api/tracks/{id}/stream; при перемотке заголовок Range"
@app.get("/api/tracks/{track_id}/stream")
async def stream_track(track_id: str, range: str | None = Header(default=None)):
    matched = next((t for t in TRACKS_CATALOG if t["id"] == track_id), None)
    if not matched:
        raise HTTPException(status_code=404, detail="Track not found")

    data = _SYNTHETIC_MP3_STREAM
    total_size = len(data)

    if range:
        match = re.match(r"bytes=(\d+)-(\d*)", range)
        if match:
            start = int(match.group(1))
            end_str = match.group(2)
            end = int(end_str) if end_str else total_size - 1
            if start >= total_size or end >= total_size or start > end:
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


@app.get("/api/dialogs", response_class=JSONResponse)
async def list_dialogs():
    return {"dialogs": DIALOGS_DATA}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("services.frontend.main:app", host="0.0.0.0", port=8000, reload=True)
