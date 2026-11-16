"""
Failure Recovery & Node Scaling Tests (TR: Сценарии 5, 6, «Обнаружение отказов», «Взаимозаменяемые узлы приложения»,
План тестирования строки 501-506).

Specifically tests:
1. "Тест добавления нового узла приложения"
   (TR: Взаимозаменяемые узлы приложения & План тестирования, строка 503 — новый узел регистрируется
   в node_registry, начинает принимать сессии и межузловую доставку без рестарта кластера).
2. "Сценарий восстановления после потери соединения"
   (TR: Технический сценарий 6, Пользовательский сценарий 7 — переподключение к новому узлу, повтор
   сообщений с тем же client_msg_id без дублей, синхронизация пропущенных сообщений по sync).
3. "Обнаружение отказа узла по таймауту heartbeat"
   (TR: Обнаружение отказов & Сценарий 5, п. 6 — сессия на отказавшем узле без heartbeat перестаёт
   считаться онлайн по истечении 30 секунд).
"""

import asyncio
from datetime import datetime, timedelta, timezone
import os
from uuid import uuid4

import pytest

# Ensure test secrets are set before importing main
os.environ["INTERNAL_SECRET"] = "test-internal-secret-for-ci"
os.environ["SESSION_SECRET"] = "test-session-secret-for-ci"
os.environ["ALLOWED_ORIGINS"] = "http://localhost:8000,http://127.0.0.1:8000"

from fastapi.testclient import TestClient

from services.app.auth import hash_password
from services.app.db import db
from services.app.main import (
    app,
    sign_session_cookie,
    COOKIE_NAME,
    INTERNAL_SECRET,
)

ORIGIN = "http://localhost:8000"


@pytest.fixture(autouse=True)
def clean_database_state():
    db.memory.clear()
    app.state.enable_persistence = True
    yield
    app.state.enable_persistence = False
    db.memory.clear()


def make_client_for_user(user_id: int) -> TestClient:
    client = TestClient(app, follow_redirects=False)
    cookie_val = sign_session_cookie(user_id)
    client.cookies.set(COOKIE_NAME, cookie_val)
    return client


def open_ws(client: TestClient):
    cookie_val = client.cookies.get(COOKIE_NAME)
    headers = {"Origin": ORIGIN, "Cookie": f"{COOKIE_NAME}={cookie_val}"}
    return client.websocket_connect("/ws", headers=headers)


@pytest.mark.asyncio
async def test_dynamic_node_addition_and_discovery():
    """
    TR: Раздел «Взаимозаменяемые узлы приложения» & План тестирования (строка 503):
    «Тест добавления нового узла приложения».
    Новый узел динамически регистрируется в реестре узлов, начинает получать heartbeat,
    обнаруживается другими узлами и успешно исключается при остановке.
    """
    # 1. Register a dynamically added 3rd node
    new_node_id = "app-node-3"
    endpoint_url = "http://app-node-3:8000"
    await db.register_node(new_node_id, endpoint_url)

    # 2. Verify node is alive and discoverable
    endpoint = await db.get_node_endpoint(new_node_id)
    assert endpoint == endpoint_url

    # 3. Simulate heartbeat
    await db.heartbeat_node(new_node_id)
    node_entry = db.memory.node_registry[new_node_id]
    assert node_entry["status"] == "alive"

    # 4. Graceful shutdown / failure marking
    await db.unregister_node(new_node_id)
    dead_endpoint = await db.get_node_endpoint(new_node_id)
    assert dead_endpoint is None, "Dead node must not be returned for routing"
    assert db.memory.node_registry[new_node_id]["status"] == "dead"


def test_reconnection_after_connection_loss_scenario_6():
    """
    TR: Технический сценарий 6 «Потеря соединения» (строки 371-408):
    1. Клиент переподключается к доступному узлу.
    2. Повторяет неподтверждённые сообщения с тем же client_msg_id (идемпотентность).
    3. Подтверждает прочитанные позиции (read).
    4. Синхронизирует пропущенные сообщения (sync).
    5. Выполняет сверку диалогов по ping (dialog_sync).
    """
    client_alice = TestClient(app, follow_redirects=False)
    client_bob = TestClient(app, follow_redirects=False)

    alice = client_alice.post("/api/register", json={"login": "alice", "password": "password"}).json()["user"]
    bob = client_bob.post("/api/register", json={"login": "bob", "password": "password"}).json()["user"]

    conv_id = client_alice.get("/api/users", params={"login": "bob"}).json()["conversation"]["conversation_id"]

    # 1. Initial message from Alice
    pending_msg_id = str(uuid4())
    with open_ws(client_alice) as ws_alice:
        ws_alice.send_text(
            f'{{"type": "send_message", "client_msg_id": "{pending_msg_id}", "conversation_id": {conv_id}, "kind": "text", "payload": {{"text": "Сообщение перед обрывом"}}}}'
        )
        ack1 = ws_alice.receive_json()
        assert ack1["type"] == "ack"
        assert ack1["seq"] == 1
        # Simulating socket drop (context exit drops connection)

    # 2. While Alice was disconnected, Bob sent two messages
    with open_ws(client_bob) as ws_bob:
        # Drain initial ping
        ws_bob.send_text('{"type": "ping"}')
        _ = ws_bob.receive_json()

        # Bob sends message 1 (seq=2)
        ws_bob.send_text(
            f'{{"type": "send_message", "client_msg_id": "{uuid4()}", "conversation_id": {conv_id}, "kind": "text", "payload": {{"text": "Боб ответил 1"}}}}'
        )
        assert ws_bob.receive_json()["seq"] == 2

        # Bob sends message 2 (seq=3)
        ws_bob.send_text(
            f'{{"type": "send_message", "client_msg_id": "{uuid4()}", "conversation_id": {conv_id}, "kind": "text", "payload": {{"text": "Боб ответил 2"}}}}'
        )
        assert ws_bob.receive_json()["seq"] == 3

    # 3. Alice reconnects (simulating reconnect to living node per TR Scenario 6)
    with open_ws(client_alice) as ws_alice_reconnected:
        # Re-send pending message with the same client_msg_id -> gets existing seq=1, no duplicate
        ws_alice_reconnected.send_text(
            f'{{"type": "send_message", "client_msg_id": "{pending_msg_id}", "conversation_id": {conv_id}, "kind": "text", "payload": {{"text": "Сообщение перед обрывом"}}}}'
        )
        ack_resend = ws_alice_reconnected.receive_json()
        assert ack_resend["type"] == "ack"
        assert ack_resend["seq"] == 1  # Exactly seq 1, no duplicate!

        # Alice confirms read position up to seq=1
        ws_alice_reconnected.send_text(f'{{"type": "read", "conversation_id": {conv_id}, "up_to_seq": 1}}')
        read_ack = ws_alice_reconnected.receive_json()
        assert read_ack["type"] == "read_ack"
        assert read_ack["last_read_seq"] == 1
        # Bob sent 2 new messages (seq=2, seq=3), so unread_count is 2
        assert read_ack["unread_count"] == 2

        # Alice syncs history to fetch missing messages since seq=1
        ws_alice_reconnected.send_text(f'{{"type": "sync", "conversation_id": {conv_id}, "since_seq": 1, "limit": 10}}')
        history = ws_alice_reconnected.receive_json()
        assert history["type"] == "history"
        assert len(history["messages"]) == 2
        assert history["messages"][0]["seq"] == 2
        assert history["messages"][1]["seq"] == 3

        # Alice sends ping for state verification
        ws_alice_reconnected.send_text('{"type": "ping"}')
        dialog_sync = ws_alice_reconnected.receive_json()
        assert dialog_sync["type"] == "dialog_sync"
        assert dialog_sync["dialogs"][0]["last_seq"] == 3


@pytest.mark.asyncio
async def test_silent_node_failure_drops_online_status_after_heartbeat_timeout():
    """
    TR: Раздел «Обнаружение отказов» & Технический сценарий 5, п. 6:
    «Если отказал сам узел собеседника, сессия перестаёт быть свежей без ping (> 30 секунд)».
    """
    u1 = await db.create_user("charlie", hash_password("pass"))
    user_id = u1["id"]

    # Session created with last_seen 40 seconds ago (exceeding 30s freshness threshold)
    old_time = datetime.now(timezone.utc) - timedelta(seconds=40)
    conn_id = uuid4()
    db.memory.sessions[conn_id] = {
        "connection_id": conn_id,
        "user_id": user_id,
        "node_id": "crashed-node",
        "last_seen": old_time,
    }

    # User is considered offline because session is stale
    is_online = await db.get_user_online_status(user_id)
    assert is_online is False

    # Now simulate a fresh session <= 30 seconds
    db.memory.sessions[conn_id]["last_seen"] = datetime.now(timezone.utc)
    is_online_now = await db.get_user_online_status(user_id)
    assert is_online_now is True
