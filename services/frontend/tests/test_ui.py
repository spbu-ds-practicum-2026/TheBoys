import io
import pytest
from httpx import ASGITransport, AsyncClient
from services.frontend.main import app


@pytest.mark.asyncio
async def test_music_landing_page_loads_by_default():
    """TR DoD: Пользователь попадает в раздел «Музыка» и видит каталог треков."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Both / and /music render the primary Music Catalog
        for path in ["/", "/music"]:
            response = await client.get(path)
            assert response.status_code == 200
            assert "Boysic" in response.text
            # Primary section header & search
            assert "Каталог треков" in response.text or "Music Catalog" in response.text
            assert "catalog-search-input" in response.text
            assert "Midnight Echoes" in response.text
            assert "The Boys Band" in response.text
            # Persistent mini-player present in shell
            assert "persistent-mini-player" in response.text
            assert "global-audio-element" in response.text


@pytest.mark.asyncio
async def test_chats_view_loads_dialogs_and_messages():
    """TR DoD: Пользователь открывает чаты, видит диалоги, счётчики и сообщения по seq."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/chats")
        assert response.status_code == 200
        # Dialogs list with unread counters
        assert "dialogs-deck-list" in response.text
        assert "Alice Smirnova" in response.text or "Алиса Смирнова" in response.text
        assert "deck-unread-badge" in response.text
        # Chat canvas with messages flow and composer
        assert "spatial-messages-flow" in response.text
        assert "composer-input" in response.text
        # Track card component in chat
        assert "sound-module-card" in response.text


@pytest.mark.asyncio
async def test_import_view_loads():
    """TR DoD: Загрузка аудиофайлов в формате MP3."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/import")
        assert response.status_code == 200
        assert "music-file-picker" in response.text
        assert ".mp3" in response.text
        assert "import-dropzone-box" in response.text
        assert "import-pipeline-tracker" in response.text


@pytest.mark.asyncio
async def test_settings_view_loads_cluster_topology():
    """TR DoD: Параметры системы и топология узлов приложения и хранения."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/settings")
        assert response.status_code == 200
        assert "Параметры системы" in response.text or "System Settings" in response.text
        assert "app-1" in response.text
        assert "storage-1" in response.text
        assert "POST /internal/deliver" in response.text


@pytest.mark.asyncio
async def test_htmx_partial_views():
    """TR: HTMX partial view swapping without full page reload."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = {"HX-Request": "true"}

        resp_music = await client.get("/music", headers=headers)
        assert resp_music.status_code == 200
        assert "music-catalog-stage" in resp_music.text
        assert "<!DOCTYPE html>" not in resp_music.text

        resp_chats = await client.get("/chats", headers=headers)
        assert resp_chats.status_code == 200
        assert "chats-view-layout" in resp_chats.text
        assert "<!DOCTYPE html>" not in resp_chats.text

        resp_import = await client.get("/import", headers=headers)
        assert resp_import.status_code == 200
        assert "import-dropzone-box" in resp_import.text
        assert "<!DOCTYPE html>" not in resp_import.text

        resp_settings = await client.get("/settings", headers=headers)
        assert resp_settings.status_code == 200
        assert "bento-settings-stage" in resp_settings.text
        assert "<!DOCTYPE html>" not in resp_settings.text

        # HTMX dedicated partial routes /htmx/views/*
        for v in ["music", "chats", "import", "settings"]:
            resp = await client.get(f"/htmx/views/{v}")
            assert resp.status_code == 200


@pytest.mark.asyncio
async def test_audio_streaming_endpoint_with_range():
    """TR 1.7: клиент запрашивает трек через GET /api/tracks/{id}/stream с заголовком Range."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        track_id = "00000000-0000-0000-0000-000000000001"
        # 1. Full stream request (200 OK)
        resp = await client.get(f"/api/tracks/{track_id}/stream")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "audio/mpeg"
        assert resp.headers["accept-ranges"] == "bytes"
        assert int(resp.headers["content-length"]) > 0

        # Also supports legacy track-1 alias
        resp_alias = await client.get("/api/tracks/track-1/stream")
        assert resp_alias.status_code == 200

        # 2. HTTP Range request (206 Partial Content)
        range_headers = {"Range": "bytes=0-416"}
        resp_range = await client.get(f"/api/tracks/{track_id}/stream", headers=range_headers)
        assert resp_range.status_code == 206
        assert resp_range.headers["content-type"] == "audio/mpeg"
        assert resp_range.headers["content-range"].startswith("bytes 0-416/")
        assert resp_range.headers["content-length"] == "417"

        # 3. Invalid / Out of bounds Range request (416 Range Not Satisfiable)
        bad_range_headers = {"Range": "bytes=9999999-99999999"}
        resp_bad = await client.get(f"/api/tracks/{track_id}/stream", headers=bad_range_headers)
        assert resp_bad.status_code == 416

        # 4. Unknown track returns 404
        resp_404 = await client.get("/api/tracks/00000000-0000-0000-0000-999999999999/stream")
        assert resp_404.status_code == 404


@pytest.mark.asyncio
async def test_api_tracks_and_search():
    """TR: Поиск треков по названию и артисту."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # All tracks
        resp = await client.get("/api/tracks")
        assert resp.status_code == 200
        data = resp.json()
        assert "tracks" in data
        assert len(data["tracks"]) >= 4

        # Search query by title
        resp_q = await client.get("/api/tracks?q=midnight")
        assert resp_q.status_code == 200
        tracks_q = resp_q.json()["tracks"]
        assert len(tracks_q) == 1
        assert tracks_q[0]["title"] == "Midnight Echoes"

        # Search query by artist
        resp_a = await client.get("/api/tracks?q=synthesia")
        assert resp_a.status_code == 200
        tracks_a = resp_a.json()["tracks"]
        assert len(tracks_a) == 1
        assert tracks_a[0]["artist"] == "Synthesia Core"


@pytest.mark.asyncio
async def test_track_upload_and_stream():
    """TR 1.14: Загрузка MP3 трека через POST /api/tracks/upload и стриминг."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        fake_mp3 = io.BytesIO(b"\xff\xfb\x90\x00" + b"\x00" * 413)
        files = {"file": ("my_cool_tune.mp3", fake_mp3, "audio/mpeg")}
        data = {"title": "Cool Synthwave", "artist": "CyberArtist"}

        resp_up = await client.post("/api/tracks/upload", files=files, data=data)
        assert resp_up.status_code == 200
        result = resp_up.json()
        assert result["status"] == "ok"
        uploaded_id = result["track"]["id"]
        assert result["track"]["title"] == "Cool Synthwave"
        assert len(result["track"]["replicas"]) == 2

        # Verify streaming of the uploaded track
        resp_stream = await client.get(f"/api/tracks/{uploaded_id}/stream")
        assert resp_stream.status_code == 200
        assert resp_stream.headers["content-type"] == "audio/mpeg"


@pytest.mark.asyncio
async def test_conversations_and_messages_endpoints():
    """TR FT4: API диалогов, отправка сообщений и монотонный seq."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. List conversations
        resp_conv = await client.get("/api/conversations")
        assert resp_conv.status_code == 200
        convs = resp_conv.json()["conversations"]
        assert len(convs) >= 4

        # 2. Mark read
        resp_read = await client.post("/api/conversations/1/read")
        assert resp_read.status_code == 200
        assert resp_read.json()["unread_count"] == 0

        # 3. Post message
        resp_msg = await client.post(
            "/api/conversations/1/messages",
            json={"text": "Integration test message"},
        )
        assert resp_msg.status_code == 200
        data_msg = resp_msg.json()
        assert "seq" in data_msg
        assert data_msg["seq"] >= 5


@pytest.mark.asyncio
async def test_users_search_and_auth_endpoints():
    """TR FT1 & 1.8: Поиск пользователя по логину, регистрация и вход."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Search users
        resp_users = await client.get("/api/users?login=alisa")
        assert resp_users.status_code == 200
        users = resp_users.json()["users"]
        assert len(users) == 1
        assert users[0]["login"] == "alisa"

        # 2. Register new user
        reg_resp = await client.post(
            "/api/register",
            json={"username": "bob_tester", "password": "securepwd123"},
        )
        assert reg_resp.status_code == 200
        assert reg_resp.json()["status"] == "ok"
        assert reg_resp.json()["user"]["login"] == "bob_tester"

        # 3. Login
        login_resp = await client.post(
            "/api/login",
            json={"username": "bob_tester", "password": "securepwd123"},
        )
        assert login_resp.status_code == 200
        assert "session_token" in login_resp.json()


@pytest.mark.asyncio
async def test_static_assets_served():
    """Static assets (CSS, JS, images) are served."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for static_file in [
            "/static/css/glass.css",
            "/static/css/messenger.css",
            "/static/css/settings.css",
            "/static/js/messenger-ui.js",
            "/static/js/htmx.min.js",
        ]:
            resp = await client.get(static_file)
            assert resp.status_code == 200, f"Failed to fetch {static_file}"
