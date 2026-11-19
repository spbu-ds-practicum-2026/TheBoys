"""Страницы и фрагменты HTMX узла приложения.

Один набор маршрутов: запрос с заголовком HX-Request получает фрагмент раздела, остальные —
страницу целиком. Кто сейчас вошёл, определяет функция get_user, которую передаёт узел.
"""
from collections.abc import Callable
from pathlib import Path

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

APP_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = APP_DIR / "static"
templates = Jinja2Templates(directory=APP_DIR / "templates")

SECTIONS = {"music": "music/catalog.html", "chats": "chats/view.html"}

GetUser = Callable[[Request], dict | None]


def _wants_fragment(request: Request) -> bool:
    # При возврате по истории HTMX просит страницу целиком и сам выбирает из неё #main.
    return (
        request.headers.get("HX-Request") == "true"
        and request.headers.get("HX-History-Restore-Request") != "true"
    )


def create_router(get_user: GetUser) -> APIRouter:
    router = APIRouter()

    async def _get_current_user(request: Request) -> dict | None:
        user = get_user(request)
        if hasattr(user, "__await__"):
            return await user
        return user

    async def section(request: Request, name: str) -> Response:
        user = await _get_current_user(request)
        if user is None:
            if _wants_fragment(request):
                # Сессия кончилась посреди работы: вместо замены раздела страницей входа уводим на неё целиком.
                return Response(status_code=200, headers={"HX-Redirect": "/login"})
            return RedirectResponse("/login", status_code=303)

        fragment = SECTIONS[name]
        template = fragment if _wants_fragment(request) else "shell.html"
        response = templates.TemplateResponse(
            request, template, {"user": user, "active": name, "fragment": fragment}
        )
        # Один адрес отдаёт и фрагмент, и страницу — кэш браузера не должен их путать.
        response.headers["Vary"] = "HX-Request, HX-History-Restore-Request"
        return response

    @router.get("/", include_in_schema=False)
    async def index(request: Request):
        user = await _get_current_user(request)
        target = "/music" if user else "/login"
        return RedirectResponse(target, status_code=303)

    @router.get("/login", include_in_schema=False)
    async def login_page(request: Request):
        user = await _get_current_user(request)
        if user:
            return RedirectResponse("/music", status_code=303)
        return templates.TemplateResponse(request, "login.html", {})

    @router.get("/music", include_in_schema=False)
    async def music(request: Request):
        return await section(request, "music")

    @router.get("/chats", include_in_schema=False)
    async def chats(request: Request):
        return await section(request, "chats")

    return router


def mount_web(app: FastAPI, get_user: GetUser) -> None:
    """Подключает страницы и статические файлы к приложению."""
    app.include_router(create_router(get_user))
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
