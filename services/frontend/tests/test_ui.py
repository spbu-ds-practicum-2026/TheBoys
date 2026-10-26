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
            "/static/js/messenger-ui.js"
        ]:
            resp = await client.get(static_file)
            assert resp.status_code == 200, f"Failed to fetch {static_file}"
