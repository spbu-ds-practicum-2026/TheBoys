import pytest
from httpx import ASGITransport, AsyncClient
from services.frontend.main import app

@pytest.mark.asyncio
async def test_messenger_page_loads():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/")
        assert response.status_code == 200
        assert "Boysic" in response.text
        # Russian keywords preserved for backward compatibility & dual-language support
        assert "Плеер" in response.text
        assert "Чаты" in response.text
        assert "Импорт своей музыки" in response.text
        assert "Midnight Echoes" in response.text
        assert "Алиса Смирнова" in response.text
        # English default & UI elements
        assert "Chats" in response.text
        assert "Player" in response.text
        assert "Import Music" in response.text
        assert "Alice Smirnova" in response.text
        assert "lang-toggle-btn" in response.text
        assert "avatar-gray" in response.text

@pytest.mark.asyncio
async def test_static_files_accessible():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for static_file in [
            "/static/css/glass.css",
            "/static/css/messenger.css",
            "/static/css/settings.css",
            "/static/js/messenger-ui.js",
            "/static/js/htmx.min.js"
        ]:
            resp = await client.get(static_file)
            assert resp.status_code == 200, f"Failed to fetch {static_file}"

@pytest.mark.asyncio
async def test_htmx_endpoints():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = {"HX-Request": "true"}
        
        # Test HTMX partial routes for views
        resp_player = await client.get("/player", headers=headers)
        assert resp_player.status_code == 200
        assert "Music Player" in resp_player.text or "Плеер" in resp_player.text
        
        resp_import = await client.get("/import", headers=headers)
        assert resp_import.status_code == 200
        assert "Import Music" in resp_import.text or "Импорт своей музыки" in resp_import.text
        
        resp_settings = await client.get("/settings", headers=headers)
        assert resp_settings.status_code == 200
        assert "Параметры" in resp_settings.text or "System Settings" in resp_settings.text
        
        # Test HTMX generic partials
        resp_partial_import = await client.get("/htmx/views/import")
        assert resp_partial_import.status_code == 200
        assert "Import Music" in resp_partial_import.text or "Импорт своей музыки" in resp_partial_import.text

@pytest.mark.asyncio
async def test_full_views_and_cosmic_features():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Direct GET /settings loads base with settings view set to display: flex
        resp_settings = await client.get("/settings")
        assert resp_settings.status_code == 200
        assert 'id="view-settings" class="spatial-stage" style="display: flex;' in resp_settings.text
        assert 'id="spatial-toggle-cursor"' in resp_settings.text
        assert 'id="spatial-toggle-black-hole"' in resp_settings.text
        assert 'id="spatial-toggle-blur"' in resp_settings.text
        assert 'id="spatial-toggle-haptics"' in resp_settings.text
        assert 'id="cosmic-canvas"' in resp_settings.text
        assert 'id="solar-cursor-spotlight"' in resp_settings.text

        # 2. Direct GET /import loads base with import view set to display: flex
        resp_import = await client.get("/import")
        assert resp_import.status_code == 200
        assert 'id="view-import" class="spatial-stage" style="display: flex;' in resp_import.text
        assert 'id="import-dropzone-box"' in resp_import.text
        assert 'id="import-pipeline-tracker"' in resp_import.text

        # 3. Chat header must not contain redundant header action buttons
        resp_chats = await client.get("/chats")
        assert resp_chats.status_code == 200
        assert "header-action-btn" not in resp_chats.text
