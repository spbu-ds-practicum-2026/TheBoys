from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="Boysic — Modern Messenger & Player (HTMX Edition)")

# Mount Static Files (CSS, JS including htmx.min.js, IMG)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

# Jinja2 Templates
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

def is_htmx_request(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"

@app.get("/", response_class=HTMLResponse)
@app.get("/chats", response_class=HTMLResponse)
async def get_messenger(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="base.html",
        context={
            "title": "Midnight Echoes",
            "artist": "The Boys Band",
            "duration": "3:42",
            "active_tab": "chats"
        }
    )

@app.get("/player", response_class=HTMLResponse)
async def get_player_view(request: Request):
    if is_htmx_request(request):
        return templates.TemplateResponse(
            request=request,
            name="player/player_placeholder.html",
            context={"title": "Midnight Echoes", "artist": "The Boys Band", "duration": "3:42"}
        )
    return templates.TemplateResponse(
        request=request,
        name="base.html",
        context={"title": "Midnight Echoes", "artist": "The Boys Band", "duration": "3:42", "active_tab": "player"}
    )

@app.get("/import", response_class=HTMLResponse)
async def get_import_view(request: Request):
    if is_htmx_request(request):
        return templates.TemplateResponse(
            request=request,
            name="import/import_placeholder.html",
            context={}
        )
    return templates.TemplateResponse(
        request=request,
        name="base.html",
        context={"title": "Midnight Echoes", "artist": "The Boys Band", "duration": "3:42", "active_tab": "import"}
    )

@app.get("/settings", response_class=HTMLResponse)
async def get_settings_view(request: Request):
    if is_htmx_request(request):
        return templates.TemplateResponse(
            request=request,
            name="settings/settings.html",
            context={}
        )
    return templates.TemplateResponse(
        request=request,
        name="base.html",
        context={"title": "Midnight Echoes", "artist": "The Boys Band", "duration": "3:42", "active_tab": "settings"}
    )

# HTMX Partial View Endpoints
@app.get("/htmx/views/{view_name}", response_class=HTMLResponse)
async def get_htmx_view_partial(request: Request, view_name: str):
    if view_name == "player":
        return templates.TemplateResponse(
            request=request,
            name="player/player_placeholder.html",
            context={"title": "Midnight Echoes", "artist": "The Boys Band", "duration": "3:42"}
        )
    elif view_name == "import":
        return templates.TemplateResponse(
            request=request,
            name="import/import_placeholder.html",
            context={}
        )
    elif view_name == "settings":
        return templates.TemplateResponse(
            request=request,
            name="settings/settings.html",
            context={}
        )
    elif view_name == "chats":
        return templates.TemplateResponse(
            request=request,
            name="messenger/chat_window.html",
            context={}
        )
    return HTMLResponse("<div class='htmx-empty'>Not found</div>", status_code=404)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
