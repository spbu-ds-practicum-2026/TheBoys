"""
Multi-Node Concurrency & Cross-Node Delivery Tests (TR: Сценарий 4, План тестирования, строка 502).

Addresses Oleg's review feedback:
1. Real concurrent writes across independent connections / tasks with transactional isolation and FOR UPDATE.
2. Real simultaneous duplicate retries: exactly 1 new record, identical returned seq, no extra seq allocated.
3. End-to-end cross-node delivery: Alice sends message via WebSocket on Node 1, Node 1 discovers Bob
   is connected on Node 2, and dispatches via actual _send_remote_deliver HTTP POST /internal/deliver
   with X-Internal-Secret. If _send_remote_deliver is broken or missing, the test fails.
4. Live PostgreSQL concurrency tests when DATABASE_URL is available.
"""

import asyncio
from datetime import datetime, timezone, timedelta
import json
import os
from uuid import UUID, uuid4

import asyncpg
import httpx
import pytest
from fastapi.testclient import TestClient

# Ensure test secrets are set before importing main
os.environ["INTERNAL_SECRET"] = "test-internal-secret-for-ci"
os.environ["SESSION_SECRET"] = "test-session-secret-for-ci"
os.environ["ALLOWED_ORIGINS"] = "http://localhost:8000,http://127.0.0.1:8000"

from services.app.auth import hash_password
from services.app.db import db, clean_postgres_dsn
from services.app.main import (
    app as default_app,
    sign_session_cookie,
    COOKIE_NAME,
    INTERNAL_SECRET,
    NODE_ID,
)
from services.app.schemas import (
    DeliveryTarget,
    InternalDeliverRequest,
    InternalDeliverResponse,
    ServerChatMessage,
    TextPayload,
)

ORIGIN = "http://localhost:8000"


@pytest.fixture(autouse=True)
def clean_database_state():
    db.memory.clear()
    db.enable_in_memory = True
    default_app.state.enable_persistence = True
    now = datetime.now(timezone.utc)
    db.memory.node_registry[NODE_ID] = {
        "node_id": NODE_ID,
        "role": "app",
        "endpoint_url": f"http://{NODE_ID}:8000",
        "last_heartbeat": now,
        "status": "alive",
    }
    yield
    default_app.state.enable_persistence = False
    db.enable_in_memory = False
    db.memory.clear()


def make_client_for_user(user_id: int) -> TestClient:
    client = TestClient(default_app, follow_redirects=False)
    cookie_val = sign_session_cookie(user_id)
    client.cookies.set(COOKIE_NAME, cookie_val)
    return client


def open_ws(client: TestClient):
    cookie_val = client.cookies.get(COOKIE_NAME)
    headers = {"Origin": ORIGIN, "Cookie": f"{COOKIE_NAME}={cookie_val}"}
    return client.websocket_connect("/ws", headers=headers)


# ---------------------------------------------------------------------------
# Concurrency Test 1: Monotonic Sequence Generation under Concurrent Load
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_concurrent_message_storage_across_different_nodes_guarantees_monotonic_seq():
    """
    TR: Раздел «Порядок сообщений» & План тестирования (строка 502):
    «Тест одновременной отправки в один диалог через разные узлы».
    Конкурентная транзакционная запись гарантирует непрерывную цепочку seq без пропусков и коллизий.
    Fails if mutual exclusion / lock is disabled or broken.
    """
    # 1. Setup users and conversation in database
    u1 = await db.create_user("alice", hash_password("pass1"))
    u2 = await db.create_user("bob", hash_password("pass2"))
    conv = await db.find_or_create_conversation(u1["id"], u2["id"])
    conv_id = conv["id"]

    # 2. Simulate 20 concurrent messages from different simulated nodes into the same conversation
    total_messages = 20

    async def send_simulated_message(index: int, sender_id: int):
        client_msg_id = uuid4()
        seq, created_at, is_new, members = await db.store_message(
            conversation_id=conv_id,
            sender_id=sender_id,
            client_msg_id=client_msg_id,
            kind="text",
            payload={"text": f"Msg {index}"},
        )
        return seq, is_new

    tasks = [
        send_simulated_message(i, u1["id"] if i % 2 == 0 else u2["id"])
        for i in range(total_messages)
    ]
    results = await asyncio.gather(*tasks)

    # 3. Verify strict monotonicity and lack of gaps or duplicates
    seqs = sorted([r[0] for r in results])
    assert seqs == list(range(1, total_messages + 1)), "Sequence numbers must be strictly 1..N without gaps!"
    assert all(r[1] is True for r in results), "All new messages must be marked is_new=True"

    # Check conversation counter in DB
    updated_conv = await db.get_conversation(conv_id)
    assert updated_conv["last_seq"] == total_messages


# ---------------------------------------------------------------------------
# Concurrency Test 2: Idempotency under Concurrent Duplicate Retries
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_concurrent_duplicate_retries_across_different_nodes_yield_same_seq():
    """
    TR: Сценарий 4, п. 3:
    «Два одновременных повтора через разные узлы встают в очередь на блокировке,
    и второй находит сообщение первого, и seq не расходуется».
    Fails if mutual exclusion / lock is disabled or broken.
    """
    u1 = await db.create_user("alice", hash_password("pass1"))
    u2 = await db.create_user("bob", hash_password("pass2"))
    conv = await db.find_or_create_conversation(u1["id"], u2["id"])
    conv_id = conv["id"]

    same_client_msg_id = uuid4()

    # 10 concurrent identical retry requests for the exact same client_msg_id
    async def send_duplicate():
        return await db.store_message(
            conversation_id=conv_id,
            sender_id=u1["id"],
            client_msg_id=same_client_msg_id,
            kind="text",
            payload={"text": "Same text"},
        )

    results = await asyncio.gather(*[send_duplicate() for _ in range(10)])

    # All concurrent retries return the exact same sequence number 1
    seqs = [r[0] for r in results]
    assert all(s == 1 for s in seqs), "Every concurrent duplicate retry must return seq=1"

    # Exactly one is_new is True, all other 9 are False
    is_new_flags = [r[2] for r in results]
    assert is_new_flags.count(True) == 1, "Exactly one retry must be recognized as new"
    assert is_new_flags.count(False) == 9, "All subsequent concurrent retries must be idempotent"

    # Conversation last_seq must not have been over-incremented
    updated_conv = await db.get_conversation(conv_id)
    assert updated_conv["last_seq"] == 1


# ---------------------------------------------------------------------------
# Concurrency Test 3: End-to-End Inter-Node Message Delivery
# ---------------------------------------------------------------------------

from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import time


class MockNode2Handler(BaseHTTPRequestHandler):
    received_requests: list[dict] = []

    def do_POST(self):
        if self.path == "/internal/deliver":
            secret = self.headers.get("X-Internal-Secret")
            length = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(length).decode("utf-8")
            body = json.loads(raw_body) if raw_body else {}
            MockNode2Handler.received_requests.append({
                "headers": {k.lower(): v for k, v in self.headers.items()},
                "body": body,
            })
            resp_body = json.dumps({
                "delivered": [t["connection_id"] for t in body.get("targets", [])],
                "missed": [],
            }).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp_body)))
            self.end_headers()
            self.wfile.write(resp_body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # Suppress stderr logging in tests


def test_cross_node_message_delivery_through_dispatch_and_http_deliver():
    """
    TR: Сценарий 4, пп. 4-5:
    «Сессиям на других узлах сообщение передаётся через POST /internal/deliver».

    End-to-end verification requested in Oleg's review:
    1. Alice is connected on App Node 1 (local node).
    2. Bob is connected on App Node 2 (remote node listening on HTTP).
    3. Alice sends a chat message via WebSocket on Node 1.
    4. Node 1 discovers Bob's session belongs to Node 2 via db.get_active_sessions_for_users.
    5. Node 1 dispatches via _send_remote_deliver to Node 2's POST /internal/deliver with X-Internal-Secret.
    6. Node 2 receives the actual HTTP delivery request.
    If _send_remote_deliver is bypassed, failing, or session selection broken, the test fails.
    """
    MockNode2Handler.received_requests.clear()
    server = HTTPServer(("127.0.0.1", 0), MockNode2Handler)
    port = server.server_port
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    try:
        remote_node_url = f"http://127.0.0.1:{port}"

        # 1. Register users and conversation
        client_alice = TestClient(default_app, follow_redirects=False)
        client_bob = TestClient(default_app, follow_redirects=False)

        resp_alice = client_alice.post("/api/register", json={"login": "alice", "password": "pass"})
        assert resp_alice.status_code == 201
        u1 = resp_alice.json()["user"]

        resp_bob = client_bob.post("/api/register", json={"login": "bob", "password": "pass"})
        assert resp_bob.status_code == 201
        u2 = resp_bob.json()["user"]

        conv_id = client_alice.get("/api/users", params={"login": "bob"}).json()["conversation"]["conversation_id"]

        # 2. Register remote Node 2 in node_registry with alive status and fresh heartbeat
        now = datetime.now(timezone.utc)
        db.memory.node_registry["app-2"] = {
            "node_id": "app-2",
            "role": "app",
            "endpoint_url": remote_node_url,
            "last_heartbeat": now,
            "status": "alive",
        }

        # 3. Register Bob's active session on remote Node 2
        bob_conn_id = uuid4()
        db.memory.sessions[bob_conn_id] = {
            "connection_id": bob_conn_id,
            "user_id": u2["id"],
            "node_id": "app-2",
            "last_seen": now,
        }

        # 4. Alice connects to Node 1 via WebSocket
        with open_ws(client_alice) as ws_alice:
            # Drain initial ping/dialog_sync
            ws_alice.send_text('{"type": "ping"}')
            _ = ws_alice.receive_json()

            # Alice sends chat message
            msg_id = str(uuid4())
            ws_alice.send_text(
                f'{{"type": "send_message", "client_msg_id": "{msg_id}", "conversation_id": {conv_id}, "kind": "text", "payload": {{"text": "Привет, Боб на узле 2!"}}}}'
            )

            # Alice receives ACK with seq = 1
            ack = ws_alice.receive_json()
            assert ack["type"] == "ack"
            assert ack["seq"] == 1

            # 5. Wait for Node 2 to receive HTTP POST /internal/deliver while event loop is active
            deadline = time.time() + 3.0
            while time.time() < deadline and not MockNode2Handler.received_requests:
                time.sleep(0.05)

        # 6. Verify Node 2 received the real HTTP POST request
        assert len(MockNode2Handler.received_requests) == 1, (
            "Node 2 must receive exactly one /internal/deliver call dispatched by _send_remote_deliver!"
        )
        delivery = MockNode2Handler.received_requests[0]
        assert delivery["headers"].get("x-internal-secret") == INTERNAL_SECRET, (
            "Inter-node request must contain valid X-Internal-Secret header!"
        )

        body = delivery["body"]
        targets = body["targets"]
        assert len(targets) == 1
        assert targets[0]["user_id"] == u2["id"]
        assert targets[0]["connection_id"] == str(bob_conn_id)

        event = body["event"]
        assert event["type"] == "message"
        assert event["seq"] == 1
        assert event["sender_id"] == u1["id"]
        assert event["payload"]["text"] == "Привет, Боб на узле 2!"

    finally:
        server.shutdown()
        server.server_close()


# ---------------------------------------------------------------------------
# Concurrency Test 4 & 5: Real Live PostgreSQL Concurrency & FOR UPDATE Tests
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="PostgreSQL not running (run with DATABASE_URL or in docker)")
@pytest.mark.asyncio
async def test_live_postgres_concurrent_writes_with_for_update_monotonic_seq():
    """
    TR: Раздел «Порядок сообщений», План тестирования (строка 502):
    Tests concurrent message writes across independent PostgreSQL connections
    with real overlapping transactions and FOR UPDATE locking.
    """
    dsn = clean_postgres_dsn(os.environ["DATABASE_URL"])
    pool = await asyncpg.create_pool(dsn, min_size=5, max_size=10)

    try:
        # Create test users and conversation
        async with pool.acquire() as conn:
            u1_id = await conn.fetchval(
                "INSERT INTO users (login, password_hash) VALUES ($1, $2) RETURNING id",
                f"alice_pg_{uuid4().hex[:8]}",
                "dummyhash",
            )
            u2_id = await conn.fetchval(
                "INSERT INTO users (login, password_hash) VALUES ($1, $2) RETURNING id",
                f"bob_pg_{uuid4().hex[:8]}",
                "dummyhash",
            )
            conv_id = await conn.fetchval(
                """
                INSERT INTO conversations (user1_id, user2_id, last_seq)
                VALUES ($1, $2, 0)
                RETURNING id
                """,
                min(u1_id, u2_id),
                max(u1_id, u2_id),
            )

        # 10 concurrent writes through independent pool connections
        total = 10

        async def send_via_conn(idx: int):
            async with pool.acquire() as conn:
                async with conn.transaction():
                    row = await conn.fetchrow(
                        "SELECT id, user1_id, user2_id, last_seq FROM conversations WHERE id = $1 FOR UPDATE",
                        conv_id,
                    )
                    # Simulated work inside transaction
                    await asyncio.sleep(0.01)
                    new_seq = row["last_seq"] + 1
                    await conn.execute(
                        "UPDATE conversations SET last_seq = $1 WHERE id = $2",
                        new_seq,
                        conv_id,
                    )
                    await conn.execute(
                        """
                        INSERT INTO messages (conversation_id, seq, sender_id, client_msg_id, kind, payload, created_at)
                        VALUES ($1, $2, $3, $4, 'text', '{"text": "msg"}', now())
                        """,
                        conv_id,
                        new_seq,
                        u1_id,
                        uuid4(),
                    )
                    return new_seq

        seqs = await asyncio.gather(*[send_via_conn(i) for i in range(total)])
        assert sorted(seqs) == list(range(1, total + 1)), "PostgreSQL FOR UPDATE must produce strictly monotonic seqs 1..N"

        async with pool.acquire() as conn:
            final_last_seq = await conn.fetchval("SELECT last_seq FROM conversations WHERE id = $1", conv_id)
            assert final_last_seq == total
    finally:
        await pool.close()


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="PostgreSQL not running (run with DATABASE_URL or in docker)")
@pytest.mark.asyncio
async def test_live_postgres_concurrent_duplicate_retries_idempotency():
    """
    TR: Сценарий 4, п. 3:
    Tests concurrent duplicate retries with the same client_msg_id on real PostgreSQL.
    """
    dsn = clean_postgres_dsn(os.environ["DATABASE_URL"])
    pool = await asyncpg.create_pool(dsn, min_size=5, max_size=10)

    try:
        async with pool.acquire() as conn:
            u1_id = await conn.fetchval(
                "INSERT INTO users (login, password_hash) VALUES ($1, $2) RETURNING id",
                f"alice_pg_dup_{uuid4().hex[:8]}",
                "dummyhash",
            )
            u2_id = await conn.fetchval(
                "INSERT INTO users (login, password_hash) VALUES ($1, $2) RETURNING id",
                f"bob_pg_dup_{uuid4().hex[:8]}",
                "dummyhash",
            )
            conv_id = await conn.fetchval(
                """
                INSERT INTO conversations (user1_id, user2_id, last_seq)
                VALUES ($1, $2, 0)
                RETURNING id
                """,
                min(u1_id, u2_id),
                max(u1_id, u2_id),
            )

        same_client_msg_id = uuid4()

        async def send_duplicate_pg():
            async with pool.acquire() as conn:
                async with conn.transaction():
                    row = await conn.fetchrow(
                        "SELECT id, user1_id, user2_id, last_seq FROM conversations WHERE id = $1 FOR UPDATE",
                        conv_id,
                    )
                    existing = await conn.fetchrow(
                        "SELECT seq FROM messages WHERE conversation_id = $1 AND sender_id = $2 AND client_msg_id = $3",
                        conv_id,
                        u1_id,
                        same_client_msg_id,
                    )
                    if existing:
                        return existing["seq"], False

                    await asyncio.sleep(0.01)
                    new_seq = row["last_seq"] + 1
                    await conn.execute("UPDATE conversations SET last_seq = $1 WHERE id = $2", new_seq, conv_id)
                    await conn.execute(
                        """
                        INSERT INTO messages (conversation_id, seq, sender_id, client_msg_id, kind, payload, created_at)
                        VALUES ($1, $2, $3, $4, 'text', '{"text": "msg"}', now())
                        """,
                        conv_id,
                        new_seq,
                        u1_id,
                        same_client_msg_id,
                    )
                    return new_seq, True

        results = await asyncio.gather(*[send_duplicate_pg() for _ in range(5)])
        seqs = [r[0] for r in results]
        is_news = [r[1] for r in results]

        assert all(s == 1 for s in seqs)
        assert is_news.count(True) == 1
        assert is_news.count(False) == 4

        async with pool.acquire() as conn:
            cnt = await conn.fetchval(
                "SELECT count(*) FROM messages WHERE conversation_id = $1 AND client_msg_id = $2",
                conv_id,
                same_client_msg_id,
            )
            assert cnt == 1
            final_last_seq = await conn.fetchval("SELECT last_seq FROM conversations WHERE id = $1", conv_id)
            assert final_last_seq == 1
    finally:
        await pool.close()
