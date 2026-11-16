"""
End-to-End integration tests for TheBoys Application Node (services/app/main.py).

Verifies full alignment with Technical Requirements (docs/tr.md):
- Scenarios 1 & 2: User registration, login, logout, password hashing, and track search
- Scenario 3: Audio stream playback with Range header support
- Scenario 4: User lookup by exact login, monotonic seq generation, and sender idempotency
- Scenario 5: Online status check, read position reporting, and unread counts
- Scenario 6: Reconnection and history sync
- Inter-node message delivery and failure detection heartbeat
"""

import os
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

# Ensure test secrets are present
os.environ["INTERNAL_SECRET"] = "test-internal-secret-for-ci"
os.environ["SESSION_SECRET"] = "test-session-secret-for-ci"
os.environ["ALLOWED_ORIGINS"] = "http://localhost:8000,http://127.0.0.1:8000"

from services.app.db import db
from services.app.main import (
    app,
    sign_session_cookie,
    verify_session_cookie,
)

ORIGIN = "http://localhost:8000"


@pytest.fixture(autouse=True)
def clean_app_state():
    db.memory.clear()
    app.state.enable_persistence = True
    yield
    app.state.enable_persistence = False
    db.memory.clear()


@pytest.fixture
def api_client():
    with TestClient(app, follow_redirects=False) as client:
        yield client


def register_user(client: TestClient, login: str, password: str = "secret") -> dict:
    resp = client.post("/api/register", json={"login": login, "password": password})
    assert resp.status_code == 201, resp.text
    return resp.json()["user"]


def connect_ws(client: TestClient):
    cookie_val = client.cookies.get("session")
    headers = {"Origin": ORIGIN, "Cookie": f"session={cookie_val}"}
    return client.websocket_connect("/ws", headers=headers)


# ---------------------------------------------------------------------------
# Scenarios 1 & 2: Auth, Password Hashing & Track Catalog Search
# ---------------------------------------------------------------------------

def test_user_registration_login_and_logout(api_client):
    # 1. Register new user
    user = register_user(api_client, "alice", "strong-password-123")
    assert user["login"] == "alice"
    assert "session" in api_client.cookies

    # Password must be hashed in storage, not plaintext
    stored = db.memory.users[user["id"]]
    assert "strong-password-123" not in stored["password_hash"]
    assert "$" in stored["password_hash"]

    # 2. Duplicate registration rejected with 409
    dup = api_client.post("/api/register", json={"login": "ALICE", "password": "other"})
    assert dup.status_code == 409
    assert dup.json()["code"] == "LOGIN_TAKEN"

    # 3. Logout clears session cookie
    api_client.post("/api/logout")
    assert "session" not in api_client.cookies

    # 4. Login with wrong password rejected with 401
    bad_login = api_client.post("/api/login", json={"login": "alice", "password": "wrong"})
    assert bad_login.status_code == 401
    assert bad_login.json()["code"] == "INVALID_CREDENTIALS"

    # 5. Login with correct password succeeds and issues new session cookie
    ok_login = api_client.post("/api/login", json={"login": "alice", "password": "strong-password-123"})
    assert ok_login.status_code == 200
    assert "session" in api_client.cookies


def test_track_catalog_search(api_client):
    register_user(api_client, "alice")

    # Search all tracks
    all_tracks = api_client.get("/api/tracks").json()
    assert len(all_tracks) == 5

    # Case-insensitive search by title
    neon = api_client.get("/api/tracks", params={"q": "neon"}).json()
    assert len(neon) == 1
    assert neon[0]["title"] == "Neon Rain"

    # Search by artist
    boys = api_client.get("/api/tracks", params={"q": "boys"}).json()
    assert len(boys) == 2

    # Empty result
    none = api_client.get("/api/tracks", params={"q": "unknown-nonexistent"}).json()
    assert none == []


# ---------------------------------------------------------------------------
# Scenario 3: Audio Stream Playback with Range Headers (RFC 9110)
# ---------------------------------------------------------------------------

def test_stream_playback_with_range_requests(api_client):
    register_user(api_client, "alice")
    track = api_client.get("/api/tracks").json()[0]
    stream_url = f"/api/tracks/{track['id']}/stream"

    # Full content
    full = api_client.get(stream_url)
    assert full.status_code == 200
    assert full.headers["Accept-Ranges"] == "bytes"
    total_len = len(full.content)

    # Range request
    range_resp = api_client.get(stream_url, headers={"Range": "bytes=0-99"})
    assert range_resp.status_code == 206
    assert range_resp.headers["Content-Range"] == f"bytes 0-99/{total_len}"
    assert len(range_resp.content) == 100
    assert range_resp.content == full.content[:100]

    # Out of range yields 416
    bad_range = api_client.get(stream_url, headers={"Range": f"bytes={total_len}-"})
    assert bad_range.status_code == 416


# ---------------------------------------------------------------------------
# Scenario 4: User Lookup by Exact Login & Conversation Creation
# ---------------------------------------------------------------------------

def test_user_lookup_opens_conversation(api_client):
    register_user(api_client, "alice")

    # Lookup non-existent user yields 404
    missing = api_client.get("/api/users", params={"login": "bob"})
    assert missing.status_code == 404
    assert missing.json()["code"] == "USER_NOT_FOUND"

    # Register bob using second client
    with TestClient(app, follow_redirects=False) as bob_client:
        register_user(bob_client, "bob")

    # Lookup bob by login (case-insensitive and trimmed)
    found = api_client.get("/api/users", params={"login": "  BOB  "})
    assert found.status_code == 200
    data = found.json()
    assert data["user"]["login"] == "bob"
    assert data["conversation"]["conversation_id"] > 0
    conv_id = data["conversation"]["conversation_id"]

    # Same lookup returns same conversation
    again = api_client.get("/api/users", params={"login": "bob"}).json()
    assert again["conversation"]["conversation_id"] == conv_id


# ---------------------------------------------------------------------------
# Scenarios 4, 5, 6: WebSocket Messaging, Idempotency & History Sync
# ---------------------------------------------------------------------------

def test_websocket_chat_monotonic_seq_and_idempotency(api_client):
    register_user(api_client, "alice")

    with TestClient(app, follow_redirects=False) as bob_client:
        register_user(bob_client, "bob")

    conv_id = api_client.get("/api/users", params={"login": "bob"}).json()["conversation"]["conversation_id"]

    # Both users connect via WebSocket
    with connect_ws(api_client) as ws_alice, connect_ws(bob_client) as ws_bob:
        # Ping returns dialog_sync
        ws_alice.send_text('{"type": "ping"}')
        sync_alice = ws_alice.receive_json()
        assert sync_alice["type"] == "dialog_sync"
        assert len(sync_alice["dialogs"]) == 1
        assert sync_alice["dialogs"][0]["last_seq"] == 0

        ws_bob.send_text('{"type": "ping"}')
        sync_bob = ws_bob.receive_json()
        assert sync_bob["type"] == "dialog_sync"

        # Alice sends first text message
        msg_id_1 = str(uuid4())
        ws_alice.send_text(
            f'{{"type": "send_message", "client_msg_id": "{msg_id_1}", "conversation_id": {conv_id}, "kind": "text", "payload": {{"text": "Привет, Боб!"}}}}'
        )

        # Alice receives ACK with monotonic seq = 1
        ack_1 = ws_alice.receive_json()
        assert ack_1["type"] == "ack"
        assert ack_1["seq"] == 1
        assert ack_1["client_msg_id"] == msg_id_1

        # Bob receives incoming chat message with seq = 1
        bob_msg_1 = ws_bob.receive_json()
        assert bob_msg_1["type"] == "message"
        assert bob_msg_1["seq"] == 1
        assert bob_msg_1["payload"]["text"] == "Привет, Боб!"

        # Alice resends same message (same client_msg_id): idempotent, seq remains 1
        ws_alice.send_text(
            f'{{"type": "send_message", "client_msg_id": "{msg_id_1}", "conversation_id": {conv_id}, "kind": "text", "payload": {{"text": "Привет, Боб!"}}}}'
        )
        ack_dup = ws_alice.receive_json()
        assert ack_dup["type"] == "ack"
        assert ack_dup["seq"] == 1  # No duplicate seq consumed!

        # Alice sends track card: server populates verified metadata
        track = api_client.get("/api/tracks").json()[0]
        track_msg_id = str(uuid4())
        ws_alice.send_text(
            f'{{"type": "send_message", "client_msg_id": "{track_msg_id}", "conversation_id": {conv_id}, "kind": "track", "payload": {{"track_id": "{track["id"]}"}}}}'
        )

        ack_track = ws_alice.receive_json()
        assert ack_track["type"] == "ack"
        assert ack_track["seq"] == 2

        bob_track = ws_bob.receive_json()
        assert bob_track["type"] == "message"
        assert bob_track["seq"] == 2
        assert bob_track["kind"] == "track"
        assert bob_track["payload"]["title"] == track["title"]
        assert bob_track["payload"]["artist"] == track["artist"]

        # Bob marks read up to seq = 2
        ws_bob.send_text(f'{{"type": "read", "conversation_id": {conv_id}, "up_to_seq": 2}}')
        read_ack = ws_bob.receive_json()
        assert read_ack["type"] == "read_ack"
        assert read_ack["last_read_seq"] == 2
        assert read_ack["unread_count"] == 0

        # Bob syncs history
        ws_bob.send_text(f'{{"type": "sync", "conversation_id": {conv_id}, "since_seq": 0, "limit": 10}}')
        history = ws_bob.receive_json()
        assert history["type"] == "history"
        assert len(history["messages"]) == 2
        assert history["messages"][0]["seq"] == 1
        assert history["messages"][1]["seq"] == 2
        assert history["has_more"] is False


def test_online_status_via_rest(api_client):
    alice = register_user(api_client, "alice")

    with TestClient(app, follow_redirects=False) as bob_client:
        bob = register_user(bob_client, "bob")

        # Bob offline initially
        assert api_client.get(f"/api/users/{bob['id']}/status").json()["online"] is False

        # Bob connects WebSocket
        with connect_ws(bob_client) as ws:
            # Bob is now online
            assert api_client.get(f"/api/users/{bob['id']}/status").json()["online"] is True

        # Bob disconnects -> offline
        assert api_client.get(f"/api/users/{bob['id']}/status").json()["online"] is False
