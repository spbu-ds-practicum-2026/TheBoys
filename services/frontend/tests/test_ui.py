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
        # 1. Full stream request (200 OK)
        resp = await client.get("/api/tracks/track-1/stream")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "audio/mpeg"
        assert resp.headers["accept-ranges"] == "bytes"
        assert int(resp.headers["content-length"]) > 0

        # 2. HTTP Range request (206 Partial Content)
        range_headers = {"Range": "bytes=0-417"}
        resp_range = await client.get("/api/tracks/track-1/stream", headers=range_headers)
        assert resp_range.status_code == 206
        assert resp_range.headers["content-type"] == "audio/mpeg"
        assert resp_range.headers["content-range"].startswith("bytes 0-417/")
        assert resp_range.headers["content-length"] == "418"

        # 3. Invalid / Out of bounds Range request (416 Range Not Satisfiable)
        bad_range_headers = {"Range": "bytes=9999999-99999999"}
        resp_bad = await client.get("/api/tracks/track-1/stream", headers=bad_range_headers)
        assert resp_bad.status_code == 416

        # 4. Unknown track returns 404
        resp_404 = await client.get("/api/tracks/track-unknown/stream")
        assert resp_404.status_code == 404


@pytest.mark.asyncio
async def test_api_tracks_and_dialogs_endpoints():
    """REST API endpoints for tracks catalog and dialogs list."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp_tracks = await client.get("/api/tracks")
        assert resp_tracks.status_code == 200
        tracks_data = resp_tracks.json()
        assert "tracks" in tracks_data
        assert len(tracks_data["tracks"]) >= 4
        assert tracks_data["tracks"][0]["title"] == "Midnight Echoes"

        resp_dialogs = await client.get("/api/dialogs")
        assert resp_dialogs.status_code == 200
        dialogs_data = resp_dialogs.json()
        assert "dialogs" in dialogs_data
        assert len(dialogs_data["dialogs"]) >= 4
        assert dialogs_data["dialogs"][0]["unread_count"] > 0


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
