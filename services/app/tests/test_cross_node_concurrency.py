"""
Multi-Node Concurrency & Cross-Node Delivery Tests (TR: Сценарий 4, План тестирования, строка 502).

Specifically tests:
1. "Тест одновременной отправки в один диалог через разные узлы"
   (TR: Порядок сообщений — одновременные отправки в один диалог через разные узлы
   встают в очередь на блокировке FOR UPDATE,seq идут без пропусков).
2. "Межузловая доставка сообщений"
   (TR: Сценарий 4, пп. 4-5 — рассылка во все сессии участников на своём и других узлах
   через POST /internal/deliver с заголовком X-Internal-Secret).
3. "Идемпотентность повторов через разные узлы"
   (TR: Сценарий 4, п. 3 — два одновременных повтора через разные узлы встают в очередь
   на блокировке, и второй находит сообщение первого).
"""

import asyncio
import os
from uuid import uuid4

import pytest

# Ensure test secrets are set before importing main
os.environ["INTERNAL_SECRET"] = "test-internal-secret-for-ci"
os.environ["SESSION_SECRET"] = "test-session-secret-for-ci"
os.environ["ALLOWED_ORIGINS"] = "http://localhost:8000,http://127.0.0.1:8000"

from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.app.auth import hash_password
from services.app.db import db
from services.app.main import (
    app as default_app,
    get_user_from_request,
    sign_session_cookie,
    COOKIE_NAME,
    INTERNAL_SECRET,
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
    default_app.state.enable_persistence = True
    yield
    default_app.state.enable_persistence = False
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


@pytest.mark.asyncio
async def test_concurrent_message_storage_across_different_nodes_guarantees_monotonic_seq():
    """
    TR: Раздел «Порядок сообщений» & План тестирования (строка 502):
    «Тест одновременной отправки в один диалог через разные узлы».
    Конкурентная транзакционная запись гарантирует непрерывную цепочку seq без пропусков и коллизий.
    """
    # 1. Setup users and conversation in database
    u1 = await db.create_user("alice", hash_password("pass1"))
    u2 = await db.create_user("bob", hash_password("pass2"))
    conv = await db.find_or_create_conversation(u1["id"], u2["id"])
    conv_id = conv["id"]

    # 2. Simulate 20 concurrent messages from different nodes into the same conversation
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


@pytest.mark.asyncio
async def test_concurrent_duplicate_retries_across_different_nodes_yield_same_seq():
    """
    TR: Сценарий 4, п. 3:
    «Два одновременных повтора через разные узлы встают в очередь на блокировке,
    и второй находит сообщение первого, и seq не расходуется».
    """
    u1 = await db.create_user("alice", hash_password("pass1"))
    u2 = await db.create_user("bob", hash_password("pass2"))
    conv = await db.find_or_create_conversation(u1["id"], u2["id"])
    conv_id = conv["id"]

    same_client_msg_id = uuid4()

    # 5 concurrent identical requests for the same client_msg_id
    async def send_duplicate():
        return await db.store_message(
            conversation_id=conv_id,
            sender_id=u1["id"],
            client_msg_id=same_client_msg_id,
            kind="text",
            payload={"text": "Same text"},
        )

    results = await asyncio.gather(*[send_duplicate() for _ in range(5)])

    # All 5 return the exact same sequence number 1
    seqs = [r[0] for r in results]
    assert all(s == 1 for s in seqs)

    # Exactly one is_new is True, the other 4 are False
    is_new_flags = [r[2] for r in results]
    assert is_new_flags.count(True) == 1
    assert is_new_flags.count(False) == 4

    # Conversation last_seq must be exactly 1
    updated_conv = await db.get_conversation(conv_id)
    assert updated_conv["last_seq"] == 1


def test_cross_node_message_delivery_simulation():
    """
    TR: Сценарий 4, пп. 4-5:
    «Сессиям на других узлах сообщение передаётся через POST /internal/deliver».
    Проверяем доставку сообщения активной сессии через POST /internal/deliver.
    """
    # 1. Register users and conversation
    client_alice = TestClient(default_app, follow_redirects=False)
    client_bob = TestClient(default_app, follow_redirects=False)

    alice = client_alice.post("/api/register", json={"login": "alice", "password": "password"}).json()["user"]
    bob = client_bob.post("/api/register", json={"login": "bob", "password": "password"}).json()["user"]

    conv_id = client_alice.get("/api/users", params={"login": "bob"}).json()["conversation"]["conversation_id"]

    # 2. Bob connects WebSocket (registers active session)
    with open_ws(client_bob) as ws_bob:
        # Drain initial ping/dialog_sync
        ws_bob.send_text('{"type": "ping"}')
        _ = ws_bob.receive_json()

        # Get Bob's active connection_id from sessions
        active_bob_sessions = [s for s in db.memory.sessions.values() if s["user_id"] == bob["id"]]
        assert len(active_bob_sessions) == 1
        bob_conn_id = active_bob_sessions[0]["connection_id"]

        # 3. Simulate Node A sending POST /internal/deliver to this node for Bob
        chat_msg = ServerChatMessage(
            conversation_id=conv_id,
            seq=42,
            sender_id=alice["id"],
            client_msg_id=uuid4(),
            kind="text",
            payload=TextPayload(text="Привет из другого узла!"),
            created_at="2026-11-16T21:00:00Z",
        )
        deliver_payload = {
            "targets": [{"user_id": bob["id"], "connection_id": str(bob_conn_id)}],
            "event": chat_msg.model_dump(mode="json"),
        }

        deliver_resp = client_alice.post(
            "/internal/deliver",
            json=deliver_payload,
            headers={"X-Internal-Secret": INTERNAL_SECRET},
        )
        assert deliver_resp.status_code == 200
        data = deliver_resp.json()
        assert str(bob_conn_id) in data["delivered"]
        assert data["missed"] == []

        # 4. Bob receives the chat message in real time
        received = ws_bob.receive_json()
        assert received["type"] == "message"
        assert received["seq"] == 42
        assert received["sender_id"] == alice["id"]
        assert received["payload"]["text"] == "Привет из другого узла!"
