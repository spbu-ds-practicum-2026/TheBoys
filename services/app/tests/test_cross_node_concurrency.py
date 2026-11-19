"""
Multi-Node Concurrency & Cross-Node Delivery Tests (TR: Сценарий 4, План тестирования, строка 502).

Addresses Oleg's review feedback:
1. Concurrency on PostgreSQL: concurrent tasks call the real Database.store_message (not a reimplemented copy of the SQL),
   and the result is verified with an independent direct query to the PostgreSQL database.
2. Concurrency duplicate retries on PostgreSQL: concurrent calls to Database.store_message with the same client_msg_id
   yield exactly 1 record in messages, identical seq, and is_new=True only once.
3. True end-to-end cross-node delivery:
   - Second app instance (Node 2) runs on a local port.
   - Bob connects to Node 2 via real WebSocket.
   - Alice connects to Node 1 via WebSocket and sends a message.
   - Node 1 dispatches via _send_remote_deliver (HTTP POST /internal/deliver with X-Internal-Secret).
   - Node 2 receives the delivery and forwards to Bob's live WebSocket.
   - Bob verifies he receives the message with the exact seq confirmed to Alice.
   - NO_PROXY / trust_env=False ensures tests are immune to machine proxy settings.
"""

import asyncio
from datetime import datetime, timezone, timedelta
import json
import os
import socket
import threading
import time
from uuid import UUID, uuid4

import asyncpg
import httpx
import pytest
from fastapi.testclient import TestClient
import websockets.sync.client

# Ensure proxy settings don't intercept localhost testing
os.environ["NO_PROXY"] = "localhost,127.0.0.1,::1"
os.environ["no_proxy"] = "localhost,127.0.0.1,::1"

# Ensure test secrets are set before importing main
os.environ["INTERNAL_SECRET"] = "test-internal-secret-for-ci"
os.environ["SESSION_SECRET"] = "test-session-secret-for-ci"
os.environ["ALLOWED_ORIGINS"] = "http://localhost:8000,http://127.0.0.1:8000,http://localhost,http://127.0.0.1"

from services.app.auth import hash_password
from services.app.db import db, Database, clean_postgres_dsn
from services.app.main import (
    app as default_app,
    create_app,
    sign_session_cookie,
    COOKIE_NAME,
    INTERNAL_SECRET,
    NODE_ID,
)

ORIGIN = "http://127.0.0.1:8000"


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
    u1 = await db.create_user("alice", hash_password("pass1"))
    u2 = await db.create_user("bob", hash_password("pass2"))
    conv = await db.find_or_create_conversation(u1["id"], u2["id"])
    conv_id = conv["id"]

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

    seqs = sorted([r[0] for r in results])
    assert seqs == list(range(1, total_messages + 1)), "Sequence numbers must be strictly 1..N without gaps!"
    assert all(r[1] is True for r in results), "All new messages must be marked is_new=True"

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

    async def send_duplicate():
        return await db.store_message(
            conversation_id=conv_id,
            sender_id=u1["id"],
            client_msg_id=same_client_msg_id,
            kind="text",
            payload={"text": "Same text"},
        )

    results = await asyncio.gather(*[send_duplicate() for _ in range(10)])

    seqs = [r[0] for r in results]
    assert all(s == 1 for s in seqs), "Every concurrent duplicate retry must return seq=1"

    is_new_flags = [r[2] for r in results]
    assert is_new_flags.count(True) == 1, "Exactly one retry must be recognized as new"
    assert is_new_flags.count(False) == 9, "All subsequent concurrent retries must be idempotent"

    updated_conv = await db.get_conversation(conv_id)
    assert updated_conv["last_seq"] == 1


# ---------------------------------------------------------------------------
# Concurrency Test 3: End-to-End Inter-Node Message Delivery
# ---------------------------------------------------------------------------

def test_cross_node_message_delivery_through_dispatch_and_http_deliver():
    """
    TR: Сценарий 4, пп. 4-5:
    «Сессиям на других узлах сообщение передаётся через POST /internal/deliver».

    End-to-end verification requested in Oleg's review:
    1. Node 1 is default_app (NODE_ID="app-1").
    2. Node 2 is a separate instance create_app("app-2") running on a free local port.
    3. Bob connects to Node 2 via real WebSocket.
    4. Alice connects to Node 1 via WebSocket and sends a message.
    5. Node 1 discovers Bob is on remote Node 2, and calls _send_remote_deliver.
    6. _send_remote_deliver calls POST http://127.0.0.1:{port}/internal/deliver with X-Internal-Secret.
    7. Node 2 receives the delivery and forwards to Bob's open WebSocket.
    8. Bob receives the message with the exact seq confirmed to Alice.
    """
    import uvicorn

    # Create distinct app instance for Node 2
    app_node2 = create_app(node_id="app-2")
    app_node2.state.enable_persistence = True

    # Bind to free local port
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    config = uvicorn.Config(app_node2, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()

    # Wait for Node 2 to become ready
    for _ in range(50):
        try:
            r = httpx.get(f"http://127.0.0.1:{port}/health", timeout=0.5, trust_env=False)
            if r.status_code == 200:
                break
        except Exception:
            time.sleep(0.05)

    try:
        remote_node_url = f"http://127.0.0.1:{port}"

        # 1. Register users and conversation
        client_alice = TestClient(default_app, follow_redirects=False)
        client_bob = TestClient(app_node2, follow_redirects=False)

        resp_alice = client_alice.post("/api/register", json={"login": "alice_node1", "password": "pass"})
        assert resp_alice.status_code == 201
        u1 = resp_alice.json()["user"]

        resp_bob = client_bob.post("/api/register", json={"login": "bob_node2", "password": "pass"})
        assert resp_bob.status_code == 201
        u2 = resp_bob.json()["user"]

        conv_id = client_alice.get("/api/users", params={"login": "bob_node2"}).json()["conversation"]["conversation_id"]

        # 2. Register remote Node 2 in node_registry with alive status and fresh heartbeat
        now = datetime.now(timezone.utc)
        db.memory.node_registry["app-2"] = {
            "node_id": "app-2",
            "role": "app",
            "endpoint_url": remote_node_url,
            "last_heartbeat": now,
            "status": "alive",
        }

        # 3. Bob connects real WebSocket to Node 2
        bob_cookie = sign_session_cookie(u2["id"])
        ws_headers = {"Origin": ORIGIN, "Cookie": f"session={bob_cookie}"}

        with websockets.sync.client.connect(
            f"ws://127.0.0.1:{port}/ws",
            additional_headers=ws_headers,
        ) as ws_bob:
            # Drain initial dialog_sync / ping
            ws_bob.send('{"type": "ping"}')
            _ = ws_bob.recv()

            # 4. Alice connects to Node 1 via WebSocket
            with open_ws(client_alice) as ws_alice:
                # Drain initial sync
                ws_alice.send_text('{"type": "ping"}')
                _ = ws_alice.receive_json()

                # Alice sends chat message on Node 1
                msg_id = str(uuid4())
                ws_alice.send_text(
                    f'{{"type": "send_message", "client_msg_id": "{msg_id}", "conversation_id": {conv_id}, "kind": "text", "payload": {{"text": "Привет, Боб на узле 2!"}}}}'
                )

                # Alice receives ACK on Node 1 with seq = 1
                ack = ws_alice.receive_json()
                assert ack["type"] == "ack"
                assert ack["seq"] == 1

                # 5. Bob receives real delivery event on Node 2 via WebSocket
                raw_event = ws_bob.recv(timeout=3.0)
                event = json.loads(raw_event)

                assert event["type"] == "message"
                assert event["seq"] == ack["seq"]
                assert event["sender_id"] == u1["id"]
                assert event["client_msg_id"] == msg_id
                assert event["payload"]["text"] == "Привет, Боб на узле 2!"

    finally:
        server.should_exit = True
        server_thread.join(timeout=2.0)


# ---------------------------------------------------------------------------
# Concurrency Test 4 & 5: Real Live PostgreSQL Concurrency via Database.store_message
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="PostgreSQL not running (run with DATABASE_URL or in docker)")
@pytest.mark.asyncio
async def test_live_postgres_concurrent_writes_with_for_update_monotonic_seq():
    """
    TR: Раздел «Порядок сообщений», План тестирования (строка 502):
    Tests concurrent message writes across independent PostgreSQL connections
    calling the actual Database.store_message implementation.
    Verifies FOR UPDATE locking, monotonic sequence numbers 1..N, and lack of gaps.
    """
    dsn = clean_postgres_dsn(os.environ["DATABASE_URL"])
    live_db = Database()
    await live_db.connect(dsn)

    try:
        # Create test users and conversation using live Database instance
        u1 = await live_db.create_user(f"alice_pg_{uuid4().hex[:8]}", "dummyhash")
        u2 = await live_db.create_user(f"bob_pg_{uuid4().hex[:8]}", "dummyhash")
        conv = await live_db.find_or_create_conversation(u1["id"], u2["id"])
        conv_id = conv["id"]

        total = 10

        # Concurrent calls directly calling the actual store_message implementation
        async def send_via_real_store_message(idx: int):
            seq, created_at, is_new, members = await live_db.store_message(
                conversation_id=conv_id,
                sender_id=u1["id"] if idx % 2 == 0 else u2["id"],
                client_msg_id=uuid4(),
                kind="text",
                payload={"text": f"msg {idx}"},
            )
            return seq

        seqs = await asyncio.gather(*[send_via_real_store_message(i) for i in range(total)])
        assert sorted(seqs) == list(range(1, total + 1)), "PostgreSQL FOR UPDATE in store_message must produce strictly monotonic seqs 1..N"

        # Direct database verification using an independent query
        async with live_db.pool.acquire() as conn:
            rows = await conn.fetch("SELECT seq FROM messages WHERE conversation_id = $1 ORDER BY seq ASC", conv_id)
            stored_seqs = [r["seq"] for r in rows]
            assert stored_seqs == list(range(1, total + 1))
            final_last_seq = await conn.fetchval("SELECT last_seq FROM conversations WHERE id = $1", conv_id)
            assert final_last_seq == total
    finally:
        await live_db.disconnect()


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="PostgreSQL not running (run with DATABASE_URL or in docker)")
@pytest.mark.asyncio
async def test_live_postgres_concurrent_duplicate_retries_idempotency():
    """
    TR: Сценарий 4, п. 3:
    Tests concurrent duplicate retries with the same client_msg_id calling the actual
    Database.store_message implementation on real PostgreSQL.
    """
    dsn = clean_postgres_dsn(os.environ["DATABASE_URL"])
    live_db = Database()
    await live_db.connect(dsn)

    try:
        u1 = await live_db.create_user(f"alice_pg_dup_{uuid4().hex[:8]}", "dummyhash")
        u2 = await live_db.create_user(f"bob_pg_dup_{uuid4().hex[:8]}", "dummyhash")
        conv = await live_db.find_or_create_conversation(u1["id"], u2["id"])
        conv_id = conv["id"]

        same_client_msg_id = uuid4()

        # Concurrent duplicate retries calling the actual store_message
        async def send_duplicate_real_store_message():
            return await live_db.store_message(
                conversation_id=conv_id,
                sender_id=u1["id"],
                client_msg_id=same_client_msg_id,
                kind="text",
                payload={"text": "same text"},
            )

        results = await asyncio.gather(*[send_duplicate_real_store_message() for _ in range(5)])
        seqs = [r[0] for r in results]
        is_news = [r[2] for r in results]

        assert all(s == 1 for s in seqs)
        assert is_news.count(True) == 1
        assert is_news.count(False) == 4

        # Direct database verification using an independent query
        async with live_db.pool.acquire() as conn:
            cnt = await conn.fetchval(
                "SELECT count(*) FROM messages WHERE conversation_id = $1 AND client_msg_id = $2",
                conv_id,
                same_client_msg_id,
            )
            assert cnt == 1
            final_last_seq = await conn.fetchval("SELECT last_seq FROM conversations WHERE id = $1", conv_id)
            assert final_last_seq == 1
    finally:
        await live_db.disconnect()
