"""Страницы и статические файлы интерфейса, проверенные на dev-сервере."""
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from services.app.dev import server

APP_DIR = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def clean_state():
    server.users.clear()
    server.conversations.clear()
    server.connections.clear()
    yield


def register(client: TestClient, login: str, password: str = "secret") -> dict:
    response = client.post("/api/register", json={"login": login, "password": password})
    assert response.status_code == 201, response.text
    return response.json()["user"]


@pytest.fixture
def client():
    with TestClient(server.app, follow_redirects=False) as c:
        yield c


class Outline(HTMLParser):
    """Для каждого элемента с id запоминает id его предков."""

    def __init__(self):
        super().__init__()
        self.stack: list[str | None] = []
        self.ancestors: dict[str, list[str]] = {}

    def handle_starttag(self, tag, attrs):
        if tag in ("meta", "link", "img", "input", "br", "use", "source"):
            return
        element_id = dict(attrs).get("id")
        if element_id:
            self.ancestors[element_id] = [i for i in self.stack if i]
        self.stack.append(element_id)

    def handle_endtag(self, tag):
        if self.stack and tag not in ("meta", "link", "img", "input", "br", "use", "source"):
            self.stack.pop()


def test_anonymous_is_sent_to_login(client):
    assert client.get("/").headers["location"] == "/login"
    assert client.get("/music").headers["location"] == "/login"
    assert client.get("/chats").headers["location"] == "/login"
    assert client.get("/login").status_code == 200


def test_expired_session_in_htmx_request_redirects_whole_page(client):
    response = client.get("/music", headers={"HX-Request": "true"})
    assert response.status_code == 200
    assert response.headers["HX-Redirect"] == "/login"


def test_logged_in_user_skips_login_page(client):
    register(client, "alice")
    assert client.get("/login").headers["location"] == "/music"
    assert client.get("/").headers["location"] == "/music"


def test_full_page_and_htmx_fragment(client):
    register(client, "alice")

    full = client.get("/music")
    assert full.status_code == 200
    assert "<html" in full.text and 'id="player"' in full.text and 'id="catalog-root"' in full.text
    assert 'data-user-login="alice"' in full.text

    fragment = client.get("/music", headers={"HX-Request": "true"})
    assert "<html" not in fragment.text and 'id="catalog-root"' in fragment.text
    assert 'id="player"' not in fragment.text
    assert fragment.headers["Vary"] == "HX-Request, HX-History-Restore-Request"

    chats = client.get("/chats", headers={"HX-Request": "true"})
    assert 'id="chats-root"' in chats.text and 'id="catalog-root"' not in chats.text


def test_history_restore_gets_full_page(client):
    register(client, "alice")
    response = client.get("/music", headers={"HX-Request": "true", "HX-History-Restore-Request": "true"})
    assert "<html" in response.text and 'id="main"' in response.text


def test_player_is_outside_htmx_swap_target(client):
    register(client, "alice")
    outline = Outline()
    outline.feed(client.get("/chats").text)
    assert "main" not in outline.ancestors["player"]
    assert "main" in outline.ancestors["chats-root"]


def test_navigation_links_work_without_javascript(client):
    register(client, "alice")
    page = client.get("/music").text
    for href in ("/music", "/chats"):
        assert re.search(rf'<a [^>]*href="{href}"[^>]*hx-get="{href}"', page)


def test_user_login_is_escaped_in_page(client):
    client.post("/api/register", json={"login": "<b>x</b>", "password": "secret"})
    page = client.get("/music").text
    assert "<b>x</b>" not in page
    assert "&lt;b&gt;x&lt;/b&gt;" in page


def test_templates_have_no_inline_handlers():
    pattern = re.compile(r"\son[a-z]+\s*=", re.IGNORECASE)
    for path in (APP_DIR / "templates").rglob("*.html"):
        assert not pattern.search(path.read_text(encoding="utf-8")), f"inline-обработчик в {path.name}"


def test_scripts_never_use_inner_html():
    for path in (APP_DIR / "static" / "js").glob("*.js"):
        if path.name == "htmx.min.js":
            continue
        source = path.read_text(encoding="utf-8")
        assert "innerHTML" not in source and "insertAdjacentHTML" not in source, path.name


def test_static_files_served(client):
    assert client.get("/static/css/app.css").status_code == 200
    assert client.get("/static/js/app.js").status_code == 200
    assert client.get("/static/js/htmx.min.js").status_code == 200


# ---------- регистрация, вход, каталог, аудио ----------

def test_register_login_and_errors(client):
    register(client, "alice")
    taken = client.post("/api/register", json={"login": "alice", "password": "x"})
    assert taken.status_code == 409 and taken.json()["code"] == "LOGIN_TAKEN"

    client.post("/api/logout")
    wrong = client.post("/api/login", json={"login": "alice", "password": "bad"})
    assert wrong.status_code == 401 and wrong.json()["code"] == "INVALID_CREDENTIALS"
    ok = client.post("/api/login", json={"login": "alice", "password": "secret"})
    assert ok.status_code == 200 and ok.json()["user"]["login"] == "alice"


def test_password_is_not_stored_in_plain_text(client):
    register(client, "alice", "secret-password")
    stored = server.users[1] if 1 in server.users else next(iter(server.users.values()))
    assert "secret-password" not in repr(stored)


def test_track_search_and_empty_result(client):
    register(client, "alice")
    assert len(client.get("/api/tracks").json()) == len(server.TRACKS)
    by_title = client.get("/api/tracks", params={"q": "midnight"}).json()
    assert [t["title"] for t in by_title] == ["Midnight Echoes"]
    by_artist = client.get("/api/tracks", params={"q": "северное"}).json()
    assert len(by_artist) == 2
    assert client.get("/api/tracks", params={"q": "zzzzzz"}).json() == []


def test_stream_supports_range(client):
    register(client, "alice")
    track = client.get("/api/tracks").json()[0]
    url = f"/api/tracks/{track['id']}/stream"
    full = client.get(url)
    size = len(full.content)
    assert full.status_code == 200 and full.headers["Accept-Ranges"] == "bytes"

    part = client.get(url, headers={"Range": "bytes=100-199"})
    assert part.status_code == 206
    assert part.headers["Content-Range"] == f"bytes 100-199/{size}"
    assert part.content == full.content[100:200]

    tail = client.get(url, headers={"Range": f"bytes={size - 10}-{size + 500}"})
    assert tail.status_code == 206 and len(tail.content) == 10

    assert client.get(url, headers={"Range": f"bytes={size}-"}).status_code == 416


def test_stream_requires_login(client):
    assert client.get(f"/api/tracks/{server.TRACKS[0]['id']}/stream").status_code == 401


def test_navigation_requests_replace_each_other(client):
    # Быстрый переход «Музыка» → «Чаты»: запоздавший ответ первого раздела не должен заменить второй.
    register(client, "alice")
    links = re.findall(r'<a [^>]*hx-get="[^"]*"[^>]*>', client.get("/music").text)
    assert links and all('hx-sync="#main:replace"' in link for link in links)
