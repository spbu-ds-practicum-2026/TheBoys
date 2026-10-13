from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="TheBoys Messenger")

# Mount Static Files
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

# Jinja2 Templates
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

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
        }
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)

