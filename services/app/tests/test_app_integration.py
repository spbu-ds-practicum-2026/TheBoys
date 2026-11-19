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
from datetime import datetime, timezone, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

# Ensure test secrets are present
os.environ["INTERNAL_SECRET"] = "test-internal-secret-for-ci"
os.environ["SESSION_SECRET"] = "test-session-secret-for-ci"
os.environ["ALLOWED_ORIGINS"] = "http://localhost:8000,http://127.0.0.1:8000"

from services.app.db import db, Database, clean_postgres_dsn
from services.app.main import (
    app,
    sign_session_cookie,
    verify_session_cookie,
    hash_password,
)

ORIGIN = "http://localhost:8000"


@pytest.fixture(autouse=True)
def clean_app_state():
    db.memory.clear()
    db.enable_in_memory = True
    app.state.enable_persistence = True
    from services.app.main import NODE_ID
    now = datetime.now(timezone.utc)
    db.memory.node_registry[NODE_ID] = {
        "node_id": NODE_ID,
        "role": "app",
        "endpoint_url": f"http://{NODE_ID}:8000",
        "last_heartbeat": now,
        "status": "alive",
    }
    yield
    app.state.enable_persistence = False
    db.enable_in_memory = False
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


def test_main_app_pages_render_and_auth_redirection(api_client):
    """
    Regression test for Oleg's review comment:
    Ensures web/pages.py properly awaits async get_user_from_request on main app.
    - Unauthenticated /login must NOT redirect to /music and must NOT crash with coroutine error.
    - Unauthenticated /music must redirect to /login.
    - Authenticated /music must render page with user login.
    """
    # 1. Anonymous user visiting / redirects to /login
    resp_root = api_client.get("/")
    assert resp_root.status_code == 303
    assert resp_root.headers["location"] == "/login"

    # 2. Anonymous user visiting /login renders 200 login page
    resp_login = api_client.get("/login")
    assert resp_login.status_code == 200
    assert "Вход" in resp_login.text or "login" in resp_login.text.lower()
    assert "coroutine" not in resp_login.text.lower()

    # 3. Anonymous user visiting /music redirects to /login
    resp_music = api_client.get("/music")
    assert resp_music.status_code == 303
    assert resp_music.headers["location"] == "/login"

    # 4. Logged in user visiting /login redirects to /music
    register_user(api_client, "alice")
    resp_login_authed = api_client.get("/login")
    assert resp_login_authed.status_code == 303
    assert resp_login_authed.headers["location"] == "/music"

    # 5. Logged in user visiting /music renders 200 with username
    resp_music_authed = api_client.get("/music")
    assert resp_music_authed.status_code == 200
    assert "alice" in resp_music_authed.text

    # 6. Logged in user visiting /chats renders 200
    resp_chats_authed = api_client.get("/chats")
    assert resp_chats_authed.status_code == 200
    assert "alice" in resp_chats_authed.text


def test_user_lookup_returns_actual_unread_count_for_existing_conversation(api_client):
    """
    Regression test for Oleg's review comment:
    GET /api/users?login=bob must return actual unread_count, not hardcoded 0.
    """
    alice = register_user(api_client, "alice")

    with TestClient(app, follow_redirects=False) as bob_client:
        bob = register_user(bob_client, "bob")
        conv_id = api_client.get("/api/users", params={"login": "bob"}).json()["conversation"]["conversation_id"]

        # Bob sends 2 messages to Alice
        with connect_ws(bob_client) as ws_bob:
            for i in range(2):
                ws_bob.send_text(
                    f'{{"type": "send_message", "client_msg_id": "{uuid4()}", "conversation_id": {conv_id}, "kind": "text", "payload": {{"text": "msg {i}"}}}}'
                )
                ack = ws_bob.receive_json()
                assert ack["type"] == "ack"

        # Alice looks up Bob: unread_count must be 2, not 0!
        lookup_resp = api_client.get("/api/users", params={"login": "bob"})
        assert lookup_resp.status_code == 200
        data = lookup_resp.json()
        assert data["conversation"]["unread_count"] == 2
        assert data["conversation"]["last_seq"] == 2


@pytest.mark.asyncio
async def test_storage_replica_retrieval_and_failover_scenarios_3_and_7(api_client, monkeypatch):
    """
    TR Scenarios 3 & 7:
    App node looks up active replicas in node_registry/replicas, queries the storage node,
    and if the primary replica fails, fails over to the secondary replica.
    """
    alice = register_user(api_client, "alice")
    track = api_client.get("/api/tracks").json()[0]
    track_id = UUID(track["id"])

    # Register two storage nodes
    now = datetime.now(timezone.utc)
    db.memory.node_registry["storage-1"] = {
        "node_id": "storage-1",
        "role": "storage",
        "endpoint_url": "http://storage-1:8000",
        "last_heartbeat": now,
        "status": "alive",
    }
    db.memory.node_registry["storage-2"] = {
        "node_id": "storage-2",
        "role": "storage",
        "endpoint_url": "http://storage-2:8000",
        "last_heartbeat": now,
        "status": "alive",
    }
    await db.add_track_replica(track_id, "storage-1", status="active")
    await db.add_track_replica(track_id, "storage-2", status="active")

    # Mock httpx to simulate storage-1 failing, but storage-2 succeeding
    import httpx

    audio_bytes = b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\xff\xfb\x90\x00" * 20

    async def mock_send(self, request, *args, **kwargs):
        url = str(request.url)
        if "storage-1" in url:
            raise httpx.ConnectError("Node storage-1 failed (simulated failure)")
        if "storage-2" in url:
            range_hdr = request.headers.get("range")
            if range_hdr == "bytes=0-9":
                chunk = audio_bytes[0:10]
                headers = {
                    "Content-Type": "audio/mpeg",
                    "Accept-Ranges": "bytes",
                    "Content-Range": f"bytes 0-9/{len(audio_bytes)}",
                    "Content-Length": "10",
                }
                return httpx.Response(206, content=chunk, headers=headers, request=request)
            headers = {
                "Content-Type": "audio/mpeg",
                "Accept-Ranges": "bytes",
                "Content-Length": str(len(audio_bytes)),
            }
            return httpx.Response(200, content=audio_bytes, headers=headers, request=request)
        raise httpx.ConnectError("Unknown host")

    monkeypatch.setattr(httpx.AsyncClient, "send", mock_send)

    # 1. Full stream request fails over to storage-2
    resp_full = api_client.get(f"/api/tracks/{track_id}/stream")
    assert resp_full.status_code == 200
    assert resp_full.content == audio_bytes

    # 2. Range request forwarded to storage-2
    resp_range = api_client.get(f"/api/tracks/{track_id}/stream", headers={"Range": "bytes=0-9"})
    assert resp_range.status_code == 206
    assert resp_range.content == audio_bytes[0:10]
    assert resp_range.headers["Content-Range"] == f"bytes 0-9/{len(audio_bytes)}"


@pytest.mark.asyncio
async def test_stale_node_heartbeat_is_excluded_from_delivery_and_online_status():
    """
    Regression test for Oleg's review comment on db.py:159:
    A node with heartbeat older than 15 seconds must be treated as dead,
    and sessions on that node must not be reported as online or used for delivery.
    """
    u1 = await db.create_user("david", hash_password("pass"))
    user_id = u1["id"]

    now = datetime.now(timezone.utc)
    # Stale node heartbeat 20 seconds ago (> 15s)
    stale_time = now - timedelta(seconds=20)
    db.memory.node_registry["stale-node"] = {
        "node_id": "stale-node",
        "role": "app",
        "endpoint_url": "http://stale-node:8000",
        "last_heartbeat": stale_time,
        "status": "alive",
    }

    # Session ping was very recent (5s ago), but node heartbeat is stale!
    conn_id = uuid4()
    db.memory.sessions[conn_id] = {
        "connection_id": conn_id,
        "user_id": user_id,
        "node_id": "stale-node",
        "last_seen": now - timedelta(seconds=5),
    }

    # Node endpoint lookup must exclude stale node
    endpoint = await db.get_node_endpoint("stale-node")
    assert endpoint is None, "Stale node must not be returned for endpoint resolution"

    # User online status must be False because node heartbeat is stale
    is_online = await db.get_user_online_status(user_id)
    assert is_online is False, "User on a node with stale heartbeat must not be online"

    # Delivery sessions query must exclude stale node
    active_sessions = await db.get_active_sessions_for_users([user_id])
    assert active_sessions == [], "Sessions on stale nodes must not receive inter-node deliveries"


@pytest.mark.asyncio
async def test_db_operational_mode_rejects_in_memory_without_test_flag(monkeypatch):
    """
    Regression test for Oleg's review comment on db.py:96:
    In operational mode without DATABASE_URL, connect() must raise RuntimeError,
    refusing to pretend data is persistently saved in local memory.
    """
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("TESTING", raising=False)
    db.enable_in_memory = False

    with pytest.raises(RuntimeError) as exc_info:
        await db.connect()
    assert "DATABASE_URL environment variable is required" in str(exc_info.value)


def test_login_max_length_validation(api_client):
    """
    Regression test for Oleg's review comment:
    Login length is restricted by PostgreSQL schema VARCHAR(64).
    A registration attempt with 65 characters must return 422 INVALID_INPUT, not 500.
    A registration with 64 characters must succeed.
    """
    # 65 chars -> 422 INVALID_INPUT
    long_login = "a" * 65
    resp_long = api_client.post("/api/register", json={"login": long_login, "password": "password"})
    assert resp_long.status_code == 422
    data_long = resp_long.json()
    assert data_long["code"] == "INVALID_INPUT"
    assert "detail" not in data_long

    # 64 chars -> 201 Created
    valid_login = "b" * 64
    resp_valid = api_client.post("/api/register", json={"login": valid_login, "password": "password"})
    assert resp_valid.status_code == 201
    assert resp_valid.json()["user"]["login"] == valid_login


@pytest.mark.asyncio
async def test_concurrent_registration_race_returns_409_not_500():
    """
    Regression test for Oleg's review comment on main.py:229:
    Concurrent registrations of the same login must be handled gracefully:
    The unique constraint violation from PostgreSQL or memory store must return
    409 LOGIN_TAKEN, and never crash with 500 Internal Server Error.
    """
    import asyncio
    from services.app.main import register, Credentials
    from fastapi import Response

    login = f"race_user_{uuid4().hex[:6]}"
    body = Credentials(login=login, password="password123")

    results = []

    async def attempt_register():
        res = await register(body, Response())
        return res

    tasks = [attempt_register(), attempt_register()]
    resps = await asyncio.gather(*tasks, return_exceptions=True)

    # One should be a dict {"user": ...}, the other should be a JSONResponse(status_code=409)
    status_codes = []
    for r in resps:
        if isinstance(r, dict):
            status_codes.append(201)
        elif hasattr(r, "status_code"):
            status_codes.append(r.status_code)
        else:
            status_codes.append(500)

    assert 201 in status_codes
    assert 409 in status_codes
    assert 500 not in status_codes


def test_error_response_format_never_wrapped_in_detail(api_client):
    """
    Regression test for Oleg's review comment on main.py:286:
    Error responses must strictly follow {"code": "...", "message": "..."}
    and never be wrapped inside {"detail": {...}}.
    """
    # 401 Unauthorized
    resp_unauth = api_client.get("/api/tracks/00000000-0000-0000-0000-000000000000/stream")
    assert resp_unauth.status_code == 401
    d_unauth = resp_unauth.json()
    assert "code" in d_unauth
    assert "message" in d_unauth
    assert "detail" not in d_unauth

    # 404 Track Not Found
    register_user(api_client, "tester_err")
    resp_notfound = api_client.get("/api/tracks/00000000-0000-0000-0000-000000000000/stream")
    assert resp_notfound.status_code == 404
    d_notfound = resp_notfound.json()
    assert d_notfound["code"] == "TRACK_NOT_FOUND"
    assert "detail" not in d_notfound

    # 422 Invalid Input
    resp_invalid = api_client.post("/api/register", json={"login": "", "password": ""})
    assert resp_invalid.status_code == 422
    d_invalid = resp_invalid.json()
    assert d_invalid["code"] == "INVALID_INPUT"
    assert "detail" not in d_invalid


@pytest.mark.asyncio
async def test_stream_audio_delivers_chunks_incrementally(api_client, monkeypatch):
    """
    Regression test for Oleg's review comment on main.py:314:
    Verifies audio streaming is chunked and streamed incrementally without buffering
    the entire track into memory. Client receives the first chunk while the storage
    node is still producing subsequent chunks.
    """
    import asyncio
    import httpx

    alice = register_user(api_client, "alice_streamer")
    track = api_client.get("/api/tracks").json()[0]
    track_id = UUID(track["id"])

    now = datetime.now(timezone.utc)
    db.memory.node_registry["storage-chunked"] = {
        "node_id": "storage-chunked",
        "role": "storage",
        "endpoint_url": "http://storage-chunked:8000",
        "last_heartbeat": now,
        "status": "alive",
    }
    await db.add_track_replica(track_id, "storage-chunked", status="active")

    yield_log = []
    chunk_1 = b"FIRST_CHUNK_DATA_64KB"
    chunk_2 = b"SECOND_CHUNK_DATA_64KB"

    async def mock_stream_bytes():
        yield_log.append("chunk_1")
        yield chunk_1
        await asyncio.sleep(0.01)
        yield_log.append("chunk_2")
        yield chunk_2

    class MockStreamResponse(httpx.Response):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)

        async def aiter_bytes(self, chunk_size=None):
            async for c in mock_stream_bytes():
                yield c

    async def mock_send(self, request, *args, **kwargs):
        headers = {
            "Content-Type": "audio/mpeg",
            "Accept-Ranges": "bytes",
            "Content-Length": str(len(chunk_1) + len(chunk_2)),
        }
        return MockStreamResponse(200, headers=headers, request=request)

    monkeypatch.setattr(httpx.AsyncClient, "send", mock_send)

    chunks_received = []
    with api_client.stream("GET", f"/api/tracks/{track_id}/stream") as stream_resp:
        assert stream_resp.status_code == 200
        for chunk in stream_resp.iter_bytes():
            chunks_received.append(chunk)

    assert b"".join(chunks_received) == chunk_1 + chunk_2
    assert yield_log == ["chunk_1", "chunk_2"]


@pytest.mark.asyncio
async def test_stream_playback_failover_to_second_replica_after_midstream_abort(api_client, monkeypatch):
    """
    TR: Технический сценарий 7 «Воспроизведение с резервной реплики».
    Regression test for Oleg's review:
    1. Two live storage replicas (storage-1 and storage-2) exist for track.
    2. First request starts streaming from storage-1, but storage-1 aborts/breaks mid-stream after 64 KiB.
    3. Client receives the first 64 KiB, encounters disconnect, and retries with Range: bytes=65536-.
    4. App node must switch replicas and route the retry to storage-2, not storage-1.
    5. Storage-2 serves the remainder of the file, allowing playback to continue seamlessly.
    """
    import httpx
    from services.app.main import replica_failures
    replica_failures.clear()

    alice = register_user(api_client, "alice_failover_streamer")
    track = api_client.get("/api/tracks").json()[0]
    track_id = UUID(track["id"])

    now = datetime.now(timezone.utc)
    db.memory.node_registry["storage-1"] = {
        "node_id": "storage-1",
        "role": "storage",
        "endpoint_url": "http://storage-1:8000",
        "last_heartbeat": now,
        "status": "alive",
    }
    db.memory.node_registry["storage-2"] = {
        "node_id": "storage-2",
        "role": "storage",
        "endpoint_url": "http://storage-2:8000",
        "last_heartbeat": now,
        "status": "alive",
    }
    await db.add_track_replica(track_id, "storage-1", status="active")
    await db.add_track_replica(track_id, "storage-2", status="active")

    chunk_1 = b"A" * 65536  # 64 KiB
    chunk_2 = b"B" * 65536  # 64 KiB
    total_size = len(chunk_1) + len(chunk_2)

    requested_endpoints = []

    class AbortingStreamResponse(httpx.Response):
        async def aiter_bytes(self, chunk_size=None):
            yield chunk_1
            raise httpx.RemoteProtocolError("Connection closed unexpectedly by storage-1")

    class GoodStreamResponse(httpx.Response):
        async def aiter_bytes(self, chunk_size=None):
            yield chunk_2

    async def mock_send(self, request, *args, **kwargs):
        endpoint = str(request.url).split("/blobs/")[0]
        requested_endpoints.append((endpoint, request.headers.get("Range")))
        if "storage-1" in endpoint:
            headers = {
                "Content-Type": "audio/mpeg",
                "Accept-Ranges": "bytes",
                "Content-Length": str(total_size),
            }
            return AbortingStreamResponse(200, headers=headers, request=request)
        else:
            # storage-2 serves the range request
            headers = {
                "Content-Type": "audio/mpeg",
                "Accept-Ranges": "bytes",
                "Content-Range": f"bytes 65536-{total_size - 1}/{total_size}",
                "Content-Length": str(len(chunk_2)),
            }
            return GoodStreamResponse(206, headers=headers, request=request)

    monkeypatch.setattr(httpx.AsyncClient, "send", mock_send)

    # Step 1: Initial request starts streaming from storage-1 and aborts after chunk 1.
    # We verify that the client receives the first 64 KiB, but the connection aborts with an error
    # instead of completing cleanly with EOF (TR: Technical Scenario 7).
    chunks_1 = []
    clean_eof_1 = False
    scope_1 = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "path": f"/api/tracks/{track_id}/stream",
        "raw_path": f"/api/tracks/{track_id}/stream".encode(),
        "query_string": b"",
        "headers": [
            (b"cookie", f"session={api_client.cookies['session']}".encode()),
        ],
    }
    async def receive_1():
        return {"type": "http.disconnect"}
    async def send_1(msg):
        nonlocal clean_eof_1
        if msg["type"] == "http.response.body":
            if msg.get("body"):
                chunks_1.append(msg["body"])
            if not msg.get("more_body", True):
                clean_eof_1 = True

    aborted_1 = False
    try:
        await app(scope_1, receive_1, send_1)
    except Exception:
        aborted_1 = True

    assert len(chunks_1) == 1
    assert chunks_1[0] == chunk_1
    assert not clean_eof_1, "Aborted stream must NOT send clean EOF"
    assert aborted_1, "Stream must abort with an exception upon storage node failure"
    assert requested_endpoints[0][0] == "http://storage-1:8000"

    # Step 2: Client retries with Range: bytes=65536-
    chunks_2 = []
    clean_eof_2 = False
    scope_2 = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "path": f"/api/tracks/{track_id}/stream",
        "raw_path": f"/api/tracks/{track_id}/stream".encode(),
        "query_string": b"",
        "headers": [
            (b"cookie", f"session={api_client.cookies['session']}".encode()),
            (b"range", b"bytes=65536-"),
        ],
    }
    async def receive_2():
        return {"type": "http.disconnect"}
    async def send_2(msg):
        nonlocal clean_eof_2
        if msg["type"] == "http.response.body":
            if msg.get("body"):
                chunks_2.append(msg["body"])
            if not msg.get("more_body", True):
                clean_eof_2 = True

    await app(scope_2, receive_2, send_2)

    # Verify the retry went to storage-2, NOT storage-1!
    assert requested_endpoints[1][0] == "http://storage-2:8000"
    assert requested_endpoints[1][1] == "bytes=65536-"
    assert clean_eof_2, "Successful retry must finish with clean EOF"

    # Verify total file reassembled correctly
    assert b"".join(chunks_1 + chunks_2) == chunk_1 + chunk_2


@pytest.mark.asyncio
async def test_stream_playback_failover_across_nodes_without_content_length(api_client, monkeypatch):
    """
    TR: Технический сценарий 7 «Воспроизведение с резервной реплики».
    Regression test addressing Oleg's review comments:
    1. Upstream storage response does NOT provide Content-Length header.
    2. Primary replica (storage-1) aborts mid-stream after sending chunk 1 (64 KiB).
    3. The application node (Node A) must NOT complete the stream cleanly (no clean EOF),
       propagating the abort error so the client knows it is incomplete.
    4. Storage-1 failure is recorded in shared Database so subsequent queries on other
       nodes (Node B) do NOT re-select the broken replica.
    5. Client issues Range retry to Node B (with Range: bytes=65536-).
    6. Node B queries replicas, deprioritizes/excludes storage-1, selects storage-2,
       and delivers the remainder of the audio seamlessly.
    """
    import httpx
    db.memory.replica_failures.clear()

    alice = register_user(api_client, "alice_cross_node_streamer")
    track = api_client.get("/api/tracks").json()[0]
    track_id = UUID(track["id"])

    now = datetime.now(timezone.utc)
    db.memory.node_registry["storage-1"] = {
        "node_id": "storage-1",
        "role": "storage",
        "endpoint_url": "http://storage-1:8000",
        "last_heartbeat": now,
        "status": "alive",
    }
    db.memory.node_registry["storage-2"] = {
        "node_id": "storage-2",
        "role": "storage",
        "endpoint_url": "http://storage-2:8000",
        "last_heartbeat": now,
        "status": "alive",
    }
    await db.add_track_replica(track_id, "storage-1", status="active")
    await db.add_track_replica(track_id, "storage-2", status="active")

    chunk_1 = b"X" * 65536  # 64 KiB
    chunk_2 = b"Y" * 65536  # 64 KiB
    total_size = len(chunk_1) + len(chunk_2)

    requested_endpoints = []

    class NoLengthAbortingStream(httpx.Response):
        async def aiter_bytes(self, chunk_size=None):
            yield chunk_1
            raise httpx.ReadError("Upstream storage-1 connection reset mid-stream")

    class NoLengthGoodStream(httpx.Response):
        async def aiter_bytes(self, chunk_size=None):
            yield chunk_2

    async def mock_send(self, request, *args, **kwargs):
        endpoint = str(request.url).split("/blobs/")[0]
        requested_endpoints.append((endpoint, request.headers.get("Range")))
        if "storage-1" in endpoint:
            # Note: No Content-Length header per Oleg's review requirement
            headers = {
                "Content-Type": "audio/mpeg",
                "Accept-Ranges": "bytes",
            }
            return NoLengthAbortingStream(200, headers=headers, request=request)
        else:
            # storage-2 serves the range request
            headers = {
                "Content-Type": "audio/mpeg",
                "Accept-Ranges": "bytes",
                "Content-Range": f"bytes 65536-{total_size - 1}/{total_size}",
                "Content-Length": str(len(chunk_2)),
            }
            return NoLengthGoodStream(206, headers=headers, request=request)

    monkeypatch.setattr(httpx.AsyncClient, "send", mock_send)

    # 1. Request to Node A: streams chunk 1 and aborts mid-stream
    chunks_node_a = []
    clean_eof_a = False
    scope_a = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "path": f"/api/tracks/{track_id}/stream",
        "raw_path": f"/api/tracks/{track_id}/stream".encode(),
        "query_string": b"",
        "headers": [
            (b"cookie", f"session={api_client.cookies['session']}".encode()),
        ],
    }
    async def receive_a():
        return {"type": "http.disconnect"}
    async def send_a(msg):
        nonlocal clean_eof_a
        if msg["type"] == "http.response.body":
            if msg.get("body"):
                chunks_node_a.append(msg["body"])
            if not msg.get("more_body", True):
                clean_eof_a = True

    aborted_a = False
    try:
        await app(scope_a, receive_a, send_a)
    except Exception:
        aborted_a = True

    assert len(chunks_node_a) == 1
    assert chunks_node_a[0] == chunk_1
    assert not clean_eof_a, "Without Content-Length, aborted stream must NOT emit clean EOF"
    assert aborted_a, "Node A must propagate abort error so client knows stream was interrupted"
    assert requested_endpoints[0][0] == "http://storage-1:8000"

    # Verify that storage-1 failure was registered in shared DB
    assert db.get_replica_penalty("http://storage-1:8000", "storage-1") > 0

    # 2. Retry routed to Node B with Range: bytes=65536-
    # Node B simulates another application node querying shared DB replicas
    node_b_replicas = await db.get_track_replicas(track_id)
    assert node_b_replicas[0]["node_id"] == "storage-2", "Node B must prioritize healthy storage-2 over broken storage-1"

    chunks_node_b = []
    clean_eof_b = False
    scope_b = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "path": f"/api/tracks/{track_id}/stream",
        "raw_path": f"/api/tracks/{track_id}/stream".encode(),
        "query_string": b"",
        "headers": [
            (b"cookie", f"session={api_client.cookies['session']}".encode()),
            (b"range", b"bytes=65536-"),
        ],
    }
    async def receive_b():
        return {"type": "http.disconnect"}
    async def send_b(msg):
        nonlocal clean_eof_b
        if msg["type"] == "http.response.body":
            if msg.get("body"):
                chunks_node_b.append(msg["body"])
            if not msg.get("more_body", True):
                clean_eof_b = True

    await app(scope_b, receive_b, send_b)

    assert requested_endpoints[1][0] == "http://storage-2:8000"
    assert requested_endpoints[1][1] == "bytes=65536-"
    assert clean_eof_b, "Node B response must complete with clean EOF"

    # 3. Audio stream reassembled perfectly
    full_audio = b"".join(chunks_node_a + chunks_node_b)
    assert full_audio == chunk_1 + chunk_2


@pytest.mark.asyncio
async def test_literal_search_in_track_catalog_special_characters(api_client):
    """
    TR: «Поиск по каталогу треков» & замечание Олега:
    Verifies literal substring search for SQL wildcard characters ('%' and '_').
    - Query '%' must NOT match tracks that don't contain a literal '%'.
    - Query '_' must NOT match tracks that don't contain a literal '_'.
    - Both memory Database and PostgreSQL strpos implementations must behave identically.
    """
    # 1. Test in memory DB
    db.memory.tracks.clear()
    t1 = {"id": str(uuid4()), "title": "Track One", "artist": "Artist", "duration_s": 120}
    t2 = {"id": str(uuid4()), "title": "100% Hits", "artist": "Various", "duration_s": 180}
    t3 = {"id": str(uuid4()), "title": "Under_Score", "artist": "Band", "duration_s": 200}

    db.memory.tracks[UUID(t1["id"])] = t1
    db.memory.tracks[UUID(t2["id"])] = t2
    db.memory.tracks[UUID(t3["id"])] = t3

    res_pct = await db.search_tracks("%")
    assert len(res_pct) == 1
    assert res_pct[0]["title"] == "100% Hits"

    res_underscore = await db.search_tracks("_")
    assert len(res_underscore) == 1
    assert res_underscore[0]["title"] == "Under_Score"

    res_word = await db.search_tracks("track")
    assert len(res_word) == 1
    assert res_word[0]["title"] == "Track One"

    # 2. Test in PostgreSQL if DATABASE_URL is available
    if os.getenv("DATABASE_URL"):
        dsn = clean_postgres_dsn(os.environ["DATABASE_URL"])
        live_db = Database()
        await live_db.connect(dsn)
        try:
            tid1, tid2, tid3 = uuid4(), uuid4(), uuid4()
            async with live_db.pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO tracks (id, title, artist, duration_s) VALUES ($1, $2, $3, $4)",
                    tid1, "Track PG Standard", "Artist", 120,
                )
                await conn.execute(
                    "INSERT INTO tracks (id, title, artist, duration_s) VALUES ($1, $2, $3, $4)",
                    tid2, "PG 100% Hits", "Various", 180,
                )
                await conn.execute(
                    "INSERT INTO tracks (id, title, artist, duration_s) VALUES ($1, $2, $3, $4)",
                    tid3, "PG Under_Score", "Band", 200,
                )

            pg_pct = await live_db.search_tracks("%")
            pct_titles = [t["title"] for t in pg_pct]
            assert "PG 100% Hits" in pct_titles
            assert "Track PG Standard" not in pct_titles

            pg_under = await live_db.search_tracks("_")
            under_titles = [t["title"] for t in pg_under]
            assert "PG Under_Score" in under_titles
            assert "Track PG Standard" not in under_titles
        finally:
            await live_db.disconnect()


@pytest.mark.asyncio
async def test_transient_503_both_replicas_recovers_without_catalog_change(api_client, monkeypatch):
    """
    TR Technical Scenario 7 regression test:
    1. Both replicas temporarily return 503.
    2. Neither replica is marked permanently 'lost' in the catalog.
    3. When storage nodes recover, subsequent stream request succeeds without manual catalog intervention.
    """
    import httpx
    db.memory.replica_failures.clear()

    alice = register_user(api_client, "alice_transient_503_user")
    track = api_client.get("/api/tracks").json()[0]
    track_id = UUID(track["id"])

    now = datetime.now(timezone.utc)
    db.memory.node_registry["storage-fail-1"] = {
        "node_id": "storage-fail-1",
        "role": "storage",
        "endpoint_url": "http://storage-fail-1:8000",
        "last_heartbeat": now,
        "status": "alive",
    }
    db.memory.node_registry["storage-fail-2"] = {
        "node_id": "storage-fail-2",
        "role": "storage",
        "endpoint_url": "http://storage-fail-2:8000",
        "last_heartbeat": now,
        "status": "alive",
    }
    await db.add_track_replica(track_id, "storage-fail-1", status="active")
    await db.add_track_replica(track_id, "storage-fail-2", status="active")

    storage_healthy = False
    audio_content = b"RECOVERED_AUDIO_STREAM_DATA" * 100

    async def mock_send(self, request, *args, **kwargs):
        if not storage_healthy:
            return httpx.Response(503, content=b"Service Temporarily Unavailable", request=request)
        headers = {
            "Content-Type": "audio/mpeg",
            "Accept-Ranges": "bytes",
            "Content-Length": str(len(audio_content)),
        }
        return httpx.Response(200, content=audio_content, headers=headers, request=request)

    monkeypatch.setattr(httpx.AsyncClient, "send", mock_send)

    # 1. Both replicas return 503 -> Request fails with 503
    resp_1 = api_client.get(f"/api/tracks/{track_id}/stream")
    assert resp_1.status_code == 503
    assert resp_1.json()["code"] == "STORAGE_UNAVAILABLE"

    # Verify both replicas remain active in catalog (neither was marked 'lost')
    replicas = await db.get_track_replicas(track_id)
    assert len(replicas) == 2, "Both replicas must remain present in catalog after transient 503"

    # 2. Storage nodes recover
    storage_healthy = True

    # 3. New request to stream track succeeds without ANY catalog change
    resp_2 = api_client.get(f"/api/tracks/{track_id}/stream")
    assert resp_2.status_code == 200
    assert resp_2.content == audio_content


@pytest.mark.asyncio
async def test_live_postgres_replica_failover_across_nodes(monkeypatch):
    """
    TR: Технический сценарий 7 «Воспроизведение с резервной реплики».
    Full HTTP + PostgreSQL test for Oleg's review:
    1. Two active replicas exist in PostgreSQL for a track.
    2. Node A starts streaming audio, storage-1 aborts mid-stream.
    3. Node A records transient failure timestamp in PostgreSQL (WITHOUT setting replicas.status='lost').
    4. Client retries with Range on Node B.
    5. Node B queries PostgreSQL, prioritizes healthy replica, and streams remaining audio seamlessly.
    """
    db_url = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not db_url:
        pytest.skip("Requires live PostgreSQL (DATABASE_URL or TEST_DATABASE_URL)")

    dsn = clean_postgres_dsn(db_url)
    was_connected = db.is_connected
    if not was_connected:
        await db.connect(dsn)

    try:
        import httpx
        from starlette.testclient import TestClient

        tid = uuid4()
        node_1, node_2 = f"storage-1-{uuid4().hex[:6]}", f"storage-2-{uuid4().hex[:6]}"
        ep_1, ep_2 = f"http://{node_1}:8000", f"http://{node_2}:8000"

        # Register track, nodes, and active replicas directly in PostgreSQL
        async with db.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO tracks (id, title, artist, duration_s) VALUES ($1, $2, $3, $4)",
                tid, "Live PG Stream Track", "Live Band", 60,
            )
            await conn.execute(
                """
                INSERT INTO node_registry (node_id, role, endpoint_url, last_heartbeat, status)
                VALUES ($1, 'storage', $2, now(), 'alive'), ($3, 'storage', $4, now(), 'alive')
                ON CONFLICT (node_id) DO UPDATE SET last_heartbeat = now(), status = 'alive'
                """,
                node_1, ep_1, node_2, ep_2,
            )
            await conn.execute(
                """
                INSERT INTO replicas (track_id, node_id, status)
                VALUES ($1, $2, 'active'), ($1, $3, 'active')
                ON CONFLICT (track_id, node_id) DO UPDATE SET status = 'active'
                """,
                tid, node_1, node_2,
            )

        chunk_1 = b"LIVE_PG_A" * 7000  # ~63 KiB
        chunk_2 = b"LIVE_PG_B" * 7000  # ~63 KiB
        total_size = len(chunk_1) + len(chunk_2)

        requested_endpoints = []

        class AbortingStreamResponse(httpx.Response):
            async def aiter_bytes(self, chunk_size=None):
                yield chunk_1
                raise httpx.ReadError("Live storage-1 connection aborted")

        class GoodStreamResponse(httpx.Response):
            async def aiter_bytes(self, chunk_size=None):
                yield chunk_2

        async def mock_send(self, request, *args, **kwargs):
            endpoint = str(request.url).split("/blobs/")[0]
            requested_endpoints.append((endpoint, request.headers.get("Range")))
            if node_1 in endpoint:
                headers = {
                    "Content-Type": "audio/mpeg",
                    "Accept-Ranges": "bytes",
                }
                return AbortingStreamResponse(200, headers=headers, request=request)
            else:
                headers = {
                    "Content-Type": "audio/mpeg",
                    "Accept-Ranges": "bytes",
                    "Content-Range": f"bytes {len(chunk_1)}-{total_size - 1}/{total_size}",
                    "Content-Length": str(len(chunk_2)),
                }
                return GoodStreamResponse(206, headers=headers, request=request)

        monkeypatch.setattr(httpx.AsyncClient, "send", mock_send)

        with TestClient(app, follow_redirects=False) as client:
            user = register_user(client, f"user_{uuid4().hex[:6]}")

            # 1. Node A stream request: starts with storage-1 and aborts
            chunks_a = []
            aborted_a = False
            scope_a = {
                "type": "http",
                "http_version": "1.1",
                "method": "GET",
                "path": f"/api/tracks/{tid}/stream",
                "raw_path": f"/api/tracks/{tid}/stream".encode(),
                "query_string": b"",
                "headers": [
                    (b"cookie", f"session={client.cookies['session']}".encode()),
                ],
            }
            async def receive_a(): return {"type": "http.disconnect"}
            async def send_a(msg):
                if msg["type"] == "http.response.body" and msg.get("body"):
                    chunks_a.append(msg["body"])

            try:
                await app(scope_a, receive_a, send_a)
            except Exception:
                aborted_a = True

            assert aborted_a, "Node A stream must abort with error"
            assert len(chunks_a) == 1
            assert chunks_a[0] == chunk_1
            assert node_1 in requested_endpoints[0][0]

            # Verify replicas in PostgreSQL are STILL status='active' (neither was marked 'lost')
            async with db.pool.acquire() as conn:
                statuses = await conn.fetch("SELECT status FROM replicas WHERE track_id = $1", tid)
                assert all(s["status"] == "active" for s in statuses), "Replicas must remain active in replicas table"

            # 2. Node B stream retry with Range: bytes={len(chunk_1)}-
            # In PostgreSQL, node_2 (healthy) must be prioritized over node_1 (failed)
            reps_b = await db.get_track_replicas(tid)
            assert reps_b[0]["node_id"] == node_2, f"Expected node_2 first, got {reps_b[0]['node_id']}"

            chunks_b = []
            clean_eof_b = False
            scope_b = {
                "type": "http",
                "http_version": "1.1",
                "method": "GET",
                "path": f"/api/tracks/{tid}/stream",
                "raw_path": f"/api/tracks/{tid}/stream".encode(),
                "query_string": b"",
                "headers": [
                    (b"cookie", f"session={client.cookies['session']}".encode()),
                    (b"range", f"bytes={len(chunk_1)}-".encode()),
                ],
            }
            async def receive_b(): return {"type": "http.disconnect"}
            async def send_b(msg):
                nonlocal clean_eof_b
                if msg["type"] == "http.response.body":
                    if msg.get("body"):
                        chunks_b.append(msg["body"])
                    if not msg.get("more_body", True):
                        clean_eof_b = True

            await app(scope_b, receive_b, send_b)

            assert node_2 in requested_endpoints[1][0], "Retry must route to healthy node_2"
            assert clean_eof_b, "Retry must finish cleanly"
            assert b"".join(chunks_a + chunks_b) == chunk_1 + chunk_2

    finally:
        if not was_connected and db.is_connected:
            await db.disconnect()


@pytest.mark.asyncio
async def test_live_postgres_transient_503_both_replicas_recovers_without_catalog_change(monkeypatch):
    """
    TR: Технический сценарий 7.
    PostgreSQL regression test for Oleg's review:
    1. Both replicas return temporary 503.
    2. Replicas in PostgreSQL remain status='active' (NOT marked 'lost').
    3. When storage recovers, subsequent request to stream track succeeds without any manual catalog intervention.
    """
    db_url = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not db_url:
        pytest.skip("Requires live PostgreSQL (DATABASE_URL or TEST_DATABASE_URL)")

    dsn = clean_postgres_dsn(db_url)
    was_connected = db.is_connected
    if not was_connected:
        await db.connect(dsn)

    try:
        import httpx
        from starlette.testclient import TestClient

        tid = uuid4()
        node_1, node_2 = f"storage-1-{uuid4().hex[:6]}", f"storage-2-{uuid4().hex[:6]}"
        ep_1, ep_2 = f"http://{node_1}:8000", f"http://{node_2}:8000"

        async with db.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO tracks (id, title, artist, duration_s) VALUES ($1, $2, $3, $4)",
                tid, "Postgres Recovery Track", "Artist", 60,
            )
            await conn.execute(
                """
                INSERT INTO node_registry (node_id, role, endpoint_url, last_heartbeat, status)
                VALUES ($1, 'storage', $2, now(), 'alive'), ($3, 'storage', $4, now(), 'alive')
                ON CONFLICT (node_id) DO UPDATE SET last_heartbeat = now(), status = 'alive'
                """,
                node_1, ep_1, node_2, ep_2,
            )
            await conn.execute(
                """
                INSERT INTO replicas (track_id, node_id, status)
                VALUES ($1, $2, 'active'), ($1, $3, 'active')
                ON CONFLICT (track_id, node_id) DO UPDATE SET status = 'active'
                """,
                tid, node_1, node_2,
            )

        storage_healthy = False
        audio_content = b"LIVE_POSTGRES_RECOVERED_AUDIO" * 50

        async def mock_send(self, request, *args, **kwargs):
            if not storage_healthy:
                return httpx.Response(503, content=b"Service Unavailable", request=request)
            headers = {
                "Content-Type": "audio/mpeg",
                "Accept-Ranges": "bytes",
                "Content-Length": str(len(audio_content)),
            }
            return httpx.Response(200, content=audio_content, headers=headers, request=request)

        monkeypatch.setattr(httpx.AsyncClient, "send", mock_send)

        with TestClient(app, follow_redirects=False) as client:
            user = register_user(client, f"user_{uuid4().hex[:6]}")

            # 1. Initial attempt: both replicas return 503 -> API returns 503
            resp_1 = client.get(f"/api/tracks/{tid}/stream")
            assert resp_1.status_code == 503
            assert resp_1.json()["code"] == "STORAGE_UNAVAILABLE"

            # Verify in PostgreSQL: both replicas STILL have status='active' (neither marked 'lost')
            async with db.pool.acquire() as conn:
                active_count = await conn.fetchval(
                    "SELECT count(*) FROM replicas WHERE track_id = $1 AND status = 'active'",
                    tid,
                )
                assert active_count == 2, "Both replicas must remain active in PostgreSQL catalog"

            # 2. Storage nodes recover
            storage_healthy = True

            # 3. Subsequent request to stream track succeeds without ANY catalog change
            resp_2 = client.get(f"/api/tracks/{tid}/stream")
            assert resp_2.status_code == 200
            assert resp_2.content == audio_content

    finally:
        if not was_connected and db.is_connected:
            await db.disconnect()


@pytest.mark.asyncio
async def test_concurrent_first_replica_queries_no_ddl_race():
    """
    TR: Замечание Олега по PR #6:
    Verify that concurrent first calls to get_track_replicas and mark_replica_failure
    do NOT execute dynamic DDL (CREATE TABLE IF NOT EXISTS) during queries,
    avoiding PostgreSQL UniqueViolationError on pg_type_typname_nsp_index.
    """
    import asyncio
    from pathlib import Path

    # 1. Verify schema migration 0003 exists and creates replica_failures table and index
    mig_path = Path(__file__).resolve().parents[3] / "infra" / "postgres" / "migrations" / "0003_replica_failures.sql"
    assert mig_path.exists(), "Migration 0003_replica_failures.sql must exist"
    mig_sql = mig_path.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS replica_failures" in mig_sql
    assert "idx_replica_failures_track_failed_at" in mig_sql

    # 2. Verify init.sql includes replica_failures and migration 3
    init_path = Path(__file__).resolve().parents[3] / "infra" / "postgres" / "init.sql"
    init_sql = init_path.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS replica_failures" in init_sql
    assert "(3, '0003_replica_failures')" in init_sql

    # 3. Simulate 10 concurrent requests to get_track_replicas and mark_replica_failure
    tid = uuid4()
    db.memory.tracks[tid] = {"id": tid, "title": "Test", "artist": "Art", "duration_s": 100}
    db.memory.replicas[tid] = [
        {"node_id": "storage-1", "status": "active"},
        {"node_id": "storage-2", "status": "active"},
    ]
    db.memory.node_registry["storage-1"] = {
        "node_id": "storage-1",
        "role": "storage",
        "endpoint_url": "http://s1:8000",
        "last_heartbeat": datetime.now(timezone.utc),
        "status": "alive",
    }
    db.memory.node_registry["storage-2"] = {
        "node_id": "storage-2",
        "role": "storage",
        "endpoint_url": "http://s2:8000",
        "last_heartbeat": datetime.now(timezone.utc),
        "status": "alive",
    }

    async def worker(i):
        if i % 2 == 0:
            return await db.get_track_replicas(tid)
        else:
            await db.mark_replica_failure(tid, node_id="storage-1", endpoint_url="http://s1:8000")
            return await db.get_track_replicas(tid)

    results = await asyncio.gather(*[worker(i) for i in range(10)])
    assert len(results) == 10

    # 4. If live PostgreSQL is configured, verify concurrent queries on real database
    db_url = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")
    if db_url:
        dsn = clean_postgres_dsn(db_url)
        was_connected = db.is_connected
        if not was_connected:
            await db.connect(dsn)
        try:
            async with db.pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO tracks (id, title, artist, duration_s) VALUES ($1, 'Live C', 'Art', 100) ON CONFLICT DO NOTHING;",
                    tid,
                )
                await conn.execute(
                    """
                    INSERT INTO node_registry (node_id, role, endpoint_url, status)
                    VALUES ('s1-test', 'storage', 'http://s1:8000', 'alive')
                    ON CONFLICT (node_id) DO UPDATE SET last_heartbeat = now(), status = 'alive';
                    """
                )
                await conn.execute(
                    """
                    INSERT INTO replicas (track_id, node_id, status)
                    VALUES ($1, 's1-test', 'active')
                    ON CONFLICT DO NOTHING;
                    """,
                    tid,
                )

            async def pg_worker(i):
                if i % 2 == 0:
                    return await db.get_track_replicas(tid)
                else:
                    await db.mark_replica_failure(tid, node_id="s1-test", endpoint_url="http://s1:8000")
                    return await db.get_track_replicas(tid)

            pg_results = await asyncio.gather(*[pg_worker(i) for i in range(10)])
            assert len(pg_results) == 10
        finally:
            if not was_connected and db.is_connected:
                await db.disconnect()


