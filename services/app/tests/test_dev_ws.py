"""Протокол /ws на dev-сервере: интерфейс разрабатывается против него, поэтому он должен следовать ТР и схемам PR #4."""
import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from services.app.dev import server


@pytest.fixture(autouse=True)
def clean_state():
    server.users.clear()
    server.conversations.clear()
    server.connections.clear()
    yield


def make_user(login: str) -> tuple[TestClient, dict]:
    client = TestClient(server.app, follow_redirects=False)
    response = client.post("/api/register", json={"login": login, "password": "secret"})
    return client, response.json()["user"]


ORIGIN = "http://localhost:8000"


def connect(client: TestClient):
    headers = {"cookie": f"session={client.cookies['session']}", "origin": ORIGIN}
    return client.websocket_connect("/ws", headers=headers)


@pytest.fixture
def pair():
    alice, alice_user = make_user("alice")
    bob, bob_user = make_user("bob")
    conv = alice.post("/api/conversations", json={"peer_id": bob_user["id"]}).json()
    return alice, alice_user, bob, bob_user, conv


def text_event(conv_id: int, text: str, client_msg_id=None) -> dict:
    return {
        "type": "send_message", "client_msg_id": str(client_msg_id or uuid4()),
        "conversation_id": conv_id, "kind": "text", "payload": {"text": text},
    }


def test_one_conversation_per_pair(pair):
    alice, alice_user, bob, bob_user, conv = pair
    again = alice.post("/api/conversations", json={"peer_id": bob_user["id"]}).json()
    from_bob = bob.post("/api/conversations", json={"peer_id": alice_user["id"]}).json()
    assert again["id"] == conv["id"] == from_bob["id"]


def test_connect_sends_dialog_sync_and_unauthorized_is_rejected(pair):
    alice, _, _, _, conv = pair
    with connect(alice) as ws:
        sync = ws.receive_json()
        assert sync["type"] == "dialog_sync"
        assert sync["dialogs"] == [{"conversation_id": conv["id"], "last_seq": 0, "unread_count": 0}]

    anonymous = TestClient(server.app)
    with anonymous.websocket_connect("/ws", headers={"origin": ORIGIN}) as ws:
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
        assert closed.value.code == 4401


def test_foreign_or_missing_origin_is_closed_with_4403(pair):
    alice, *_ = pair
    cookie = f"session={alice.cookies['session']}"
    for headers in ({"cookie": cookie}, {"cookie": cookie, "origin": "http://evil.example"}):
        with alice.websocket_connect("/ws", headers=headers) as ws:
            with pytest.raises(WebSocketDisconnect) as closed:
                ws.receive_json()
            assert closed.value.code == 4403


def test_session_cookie_has_issue_time_signature_and_expires(pair):
    alice, alice_user, *_ = pair
    assert len(alice.cookies["session"].split(".")) == 3  # {user_id}.{issued_at}.{hmac}

    def status_with(cookie: str) -> int:
        return TestClient(server.app).get("/api/conversations", headers={"cookie": f"session={cookie}"}).status_code

    assert status_with(alice.cookies["session"]) == 200
    expired = server._cookie_value(alice_user["id"], issued_at=int(time.time()) - server.SESSION_COOKIE_MAX_AGE_SECONDS - 10)
    assert status_with(expired) == 401
    future = server._cookie_value(alice_user["id"], issued_at=int(time.time()) + 600)
    assert status_with(future) == 401
    tampered = alice.cookies["session"].rsplit(".", 1)[0] + ".badsignature"
    assert status_with(tampered) == 401


def test_message_gets_seq_ack_and_reaches_peer_and_other_tab(pair):
    alice, _, bob, _, conv = pair
    with connect(alice) as tab1, connect(alice) as tab2, connect(bob) as bob_ws:
        for ws in (tab1, tab2, bob_ws):
            ws.receive_json()  # dialog_sync при подключении

        tab1.send_json(text_event(conv["id"], "привет"))
        ack = tab1.receive_json()
        assert ack["type"] == "ack" and ack["seq"] == 1

        for ws in (tab2, bob_ws):
            message = ws.receive_json()
            assert message["type"] == "message" and message["seq"] == 1
            assert message["payload"] == {"text": "привет"}


def test_retry_with_same_client_msg_id_does_not_consume_seq(pair):
    alice, _, bob, _, conv = pair
    msg_id = uuid4()
    with connect(alice) as ws, connect(bob) as bob_ws:
        ws.receive_json()
        bob_ws.receive_json()

        ws.send_json(text_event(conv["id"], "один", msg_id))
        first = ws.receive_json()
        ws.send_json(text_event(conv["id"], "один", msg_id))  # повтор после «обрыва»
        retry = ws.receive_json()
        ws.send_json(text_event(conv["id"], "два"))
        second = ws.receive_json()

        assert first["seq"] == retry["seq"] == 1
        assert second["seq"] == 2  # пропусков нет

        delivered = [bob_ws.receive_json() for _ in range(2)]
        assert [m["seq"] for m in delivered] == [1, 2]  # получатель не видит дубль


def test_track_card_gets_server_side_metadata(pair):
    alice, _, bob, _, conv = pair
    track = server.TRACKS[0]
    with connect(alice) as ws, connect(bob) as bob_ws:
        ws.receive_json()
        bob_ws.receive_json()
        ws.send_json({
            "type": "send_message", "client_msg_id": str(uuid4()), "conversation_id": conv["id"],
            "kind": "track", "payload": {"track_id": track["id"]},
        })
        assert ws.receive_json()["type"] == "ack"
        card = bob_ws.receive_json()
        assert card["kind"] == "track"
        assert card["payload"]["title"] == track["title"] and card["payload"]["duration_s"] == track["duration_s"]


def test_unread_counter_read_ack_and_invalid_position(pair):
    alice, _, bob, _, conv = pair
    with connect(alice) as ws:
        ws.receive_json()
        for text in ("a", "b", "c"):
            ws.send_json(text_event(conv["id"], text))
            ws.receive_json()

    listing = bob.get("/api/conversations").json()
    assert listing[0]["last_seq"] == 3 and listing[0]["unread_count"] == 3

    with connect(bob) as ws:
        assert ws.receive_json()["dialogs"][0]["unread_count"] == 3
        ws.send_json({"type": "read", "conversation_id": conv["id"], "up_to_seq": 2})
        assert ws.receive_json() == {"type": "read_ack", "conversation_id": conv["id"], "last_read_seq": 2, "unread_count": 1}

        ws.send_json({"type": "read", "conversation_id": conv["id"], "up_to_seq": 1})  # назад не двигается
        assert ws.receive_json()["last_read_seq"] == 2

        ws.send_json({"type": "read", "conversation_id": conv["id"], "up_to_seq": 99})
        error = ws.receive_json()
        assert error["type"] == "error" and error["code"] == "INVALID_READ_POSITION"


def test_sync_opens_from_latest_and_pages_both_ways(pair):
    alice, _, _, _, conv = pair
    with connect(alice) as ws:
        ws.receive_json()
        for n in range(1, 8):
            ws.send_json(text_event(conv["id"], f"m{n}"))
            ws.receive_json()

        ws.send_json({"type": "sync", "conversation_id": conv["id"], "before_seq": 8, "limit": 3})
        latest = ws.receive_json()
        assert [m["seq"] for m in latest["messages"]] == [5, 6, 7] and latest["has_more"] is True

        ws.send_json({"type": "sync", "conversation_id": conv["id"], "before_seq": 5, "limit": 10})
        older = ws.receive_json()
        assert [m["seq"] for m in older["messages"]] == [1, 2, 3, 4] and older["has_more"] is False

        ws.send_json({"type": "sync", "conversation_id": conv["id"], "since_seq": 5, "limit": 1})
        forward = ws.receive_json()
        assert [m["seq"] for m in forward["messages"]] == [6] and forward["has_more"] is True


def test_invalid_event_is_rejected_with_error(pair):
    alice, *_ = pair
    with connect(alice) as ws:
        ws.receive_json()
        ws.send_json({"type": "send_message", "conversation_id": 1})
        assert ws.receive_json()["code"] == "INVALID_PAYLOAD"


def test_online_status_and_drop_connections(pair):
    alice, _, bob, bob_user, _ = pair
    assert alice.get(f"/api/users/{bob_user['id']}/status").json() == {"online": False}
    with connect(bob) as ws:
        ws.receive_json()
        assert alice.get(f"/api/users/{bob_user['id']}/status").json() == {"online": True}
        assert alice.post("/dev/drop-connections").json() == {"dropped": 1}
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()
    assert alice.get(f"/api/users/{bob_user['id']}/status").json() == {"online": False}
