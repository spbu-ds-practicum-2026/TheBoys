import os
import time
from datetime import datetime, timezone
from uuid import UUID, uuid4
import pytest
from fastapi.testclient import TestClient
from pydantic import TypeAdapter, ValidationError

# Set environment before importing main
os.environ["INTERNAL_SECRET"] = "test-internal-secret-for-ci"
os.environ["SESSION_SECRET"] = "test-session-secret-for-ci"
os.environ["ALLOWED_ORIGINS"] = "http://localhost:8000, http://127.0.0.1:8000"

from services.app.main import (
    app,
    active_connections,
    sign_session_cookie,
    verify_session_cookie,
    SESSION_COOKIE_MAX_AGE_SECONDS,
)
from services.app.schemas.ws import (
    ClientIncomingEvent,
    ClientPingMessage,
    ClientReadMessage,
    ClientSendMessage,
    ClientSyncMessage,
    ClientTypingMessage,
    DeliveryTarget,
    DialogSyncItem,
    ErrorCode,
    InternalDeliverRequest,
    InternalDeliverResponse,
    ServerAckMessage,
    ServerChatMessage,
    ServerDialogSyncMessage,
    ServerErrorMessage,
    ServerHistoryMessage,
    ServerOutgoingEvent,
    ServerPeerTypingMessage,
    ServerReadAckMessage,
    TextPayload,
    TrackPayload,
    TrackSendPayload,
)

client_adapter = TypeAdapter(ClientIncomingEvent)
server_adapter = TypeAdapter(ServerOutgoingEvent)
test_client = TestClient(app)


# ---------------------------------------------------------------------------
# Client Event Validation Tests
# ---------------------------------------------------------------------------

def test_client_send_text_message():
    msg_id = str(uuid4())
    raw = {
        "type": "send_message",
        "client_msg_id": msg_id,
        "conversation_id": 10,
        "kind": "text",
        "payload": {"text": "Привет! Как трек?"},
    }
    parsed = client_adapter.validate_python(raw)
    assert isinstance(parsed, ClientSendMessage)
    assert str(parsed.client_msg_id) == msg_id
    assert parsed.conversation_id == 10
    assert parsed.kind == "text"
    assert isinstance(parsed.payload, TextPayload)
    assert parsed.payload.text == "Привет! Как трек?"


def test_client_send_track_message_requires_only_track_id():
    """Client sends only track_id to prevent spoofing title/artist/duration."""
    msg_id = str(uuid4())
    track_id = str(uuid4())
    raw = {
        "type": "send_message",
        "client_msg_id": msg_id,
        "conversation_id": 42,
        "kind": "track",
        "payload": {
            "track_id": track_id,
        },
    }
    parsed = client_adapter.validate_python(raw)
    assert isinstance(parsed, ClientSendMessage)
    assert parsed.kind == "track"
    assert isinstance(parsed.payload, TrackSendPayload)
    assert str(parsed.payload.track_id) == track_id


def test_client_send_text_blank_or_spaces_rejected():
    """Empty strings or strings with only whitespace must be rejected."""
    msg_id = str(uuid4())
    for bad_text in ["", "   ", "\t\n  "]:
        raw = {
            "type": "send_message",
            "client_msg_id": msg_id,
            "conversation_id": 10,
            "kind": "text",
            "payload": {"text": bad_text},
        }
        with pytest.raises(ValidationError):
            client_adapter.validate_python(raw)


def test_client_send_text_too_long_rejected():
    """Text longer than 4000 characters must be rejected."""
    msg_id = str(uuid4())
    raw = {
        "type": "send_message",
        "client_msg_id": msg_id,
        "conversation_id": 10,
        "kind": "text",
        "payload": {"text": "A" * 4001},
    }
    with pytest.raises(ValidationError):
        client_adapter.validate_python(raw)


def test_client_send_mismatched_kind_and_payload():
    """kind='text' cannot accept TrackSendPayload, and kind='track' cannot accept TextPayload."""
    msg_id = str(uuid4())

    # Text kind with track payload
    raw_text_mismatch = {
        "type": "send_message",
        "client_msg_id": msg_id,
        "conversation_id": 1,
        "kind": "text",
        "payload": {"track_id": str(uuid4())},
    }
    with pytest.raises(ValidationError):
        client_adapter.validate_python(raw_text_mismatch)

    # Track kind with text payload
    raw_track_mismatch = {
        "type": "send_message",
        "client_msg_id": msg_id,
        "conversation_id": 1,
        "kind": "track",
        "payload": {"text": "Just text"},
    }
    with pytest.raises(ValidationError):
        client_adapter.validate_python(raw_track_mismatch)


def test_client_read_message():
    raw = {
        "type": "read",
        "conversation_id": 7,
        "up_to_seq": 88,
    }
    parsed = client_adapter.validate_python(raw)
    assert isinstance(parsed, ClientReadMessage)
    assert parsed.conversation_id == 7
    assert parsed.up_to_seq == 88


def test_client_read_message_zero_or_negative_seq_rejected():
    for bad_seq in [0, -1, -50]:
        raw = {
            "type": "read",
            "conversation_id": 7,
            "up_to_seq": bad_seq,
        }
        with pytest.raises(ValidationError):
            client_adapter.validate_python(raw)


def test_client_sync_message_bounds_and_limit():
    raw_default = {
        "type": "sync",
        "conversation_id": 15,
    }
    parsed_default = client_adapter.validate_python(raw_default)
    assert isinstance(parsed_default, ClientSyncMessage)
    assert parsed_default.since_seq == 0
    assert parsed_default.limit == 50

    raw_before = {
        "type": "sync",
        "conversation_id": 15,
        "before_seq": 200,
        "limit": 100,
    }
    parsed_before = client_adapter.validate_python(raw_before)
    assert parsed_before.before_seq == 200
    assert parsed_before.limit == 100


def test_client_sync_message_mutually_exclusive_bounds_rejected():
    """since_seq and before_seq cannot both be provided simultaneously."""
    raw_both = {
        "type": "sync",
        "conversation_id": 15,
        "since_seq": 5,
        "before_seq": 3,
    }
    with pytest.raises(ValidationError) as exc_info:
        client_adapter.validate_python(raw_both)
    assert "mutually exclusive" in str(exc_info.value)


def test_client_ping_message():
    raw = {"type": "ping"}
    parsed = client_adapter.validate_python(raw)
    assert isinstance(parsed, ClientPingMessage)
    assert parsed.type == "ping"


def test_client_typing_message():
    raw = {"type": "typing", "conversation_id": 12}
    parsed = client_adapter.validate_python(raw)
    assert isinstance(parsed, ClientTypingMessage)
    assert parsed.conversation_id == 12


def test_client_invalid_unknown_type():
    raw = {"type": "unknown_action", "foo": "bar"}
    with pytest.raises(ValidationError):
        client_adapter.validate_python(raw)


def test_client_extra_fields_forbidden():
    raw = {"type": "ping", "extra_token": "not_allowed"}
    with pytest.raises(ValidationError):
        client_adapter.validate_python(raw)


# ---------------------------------------------------------------------------
# Server Event Validation Tests
# ---------------------------------------------------------------------------

def test_server_ack_message():
    client_id = str(uuid4())
    raw = {
        "type": "ack",
        "client_msg_id": client_id,
        "conversation_id": 2,
        "seq": 10,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    parsed = server_adapter.validate_python(raw)
    assert isinstance(parsed, ServerAckMessage)
    assert parsed.seq == 10
    assert str(parsed.client_msg_id) == client_id


def test_server_chat_message():
    client_id = str(uuid4())
    track_id = str(uuid4())
    raw = {
        "type": "message",
        "conversation_id": 2,
        "seq": 11,
        "sender_id": 1,
        "client_msg_id": client_id,
        "kind": "track",
        "payload": {
            "track_id": track_id,
            "title": "Midnight Echoes",
            "artist": "The Boys Band",
            "duration_s": 222,
        },
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    parsed = server_adapter.validate_python(raw)
    assert isinstance(parsed, ServerChatMessage)
    assert parsed.kind == "track"
    assert isinstance(parsed.payload, TrackPayload)
    assert parsed.payload.title == "Midnight Echoes"
    assert parsed.payload.duration_s == 222


def test_server_chat_message_mismatched_payload_fails():
    client_id = str(uuid4())
    raw = {
        "type": "message",
        "conversation_id": 2,
        "seq": 11,
        "sender_id": 1,
        "client_msg_id": client_id,
        "kind": "track",
        "payload": {
            "text": "This is text instead of track",
        },
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    with pytest.raises(ValidationError):
        server_adapter.validate_python(raw)


def test_server_read_ack_message():
    raw = {
        "type": "read_ack",
        "conversation_id": 3,
        "last_read_seq": 50,
        "unread_count": 0,
    }
    parsed = server_adapter.validate_python(raw)
    assert isinstance(parsed, ServerReadAckMessage)
    assert parsed.last_read_seq == 50
    assert parsed.unread_count == 0


def test_server_dialog_sync():
    raw = {
        "type": "dialog_sync",
        "dialogs": [
            {"conversation_id": 1, "last_seq": 100, "unread_count": 5},
            {"conversation_id": 2, "last_seq": 20, "unread_count": 0},
        ],
    }
    parsed = server_adapter.validate_python(raw)
    assert isinstance(parsed, ServerDialogSyncMessage)
    assert len(parsed.dialogs) == 2
    assert parsed.dialogs[0].unread_count == 5


def test_server_history_message():
    client_id = str(uuid4())
    raw = {
        "type": "history",
        "conversation_id": 5,
        "messages": [
            {
                "type": "message",
                "conversation_id": 5,
                "seq": 1,
                "sender_id": 2,
                "client_msg_id": client_id,
                "kind": "text",
                "payload": {"text": "Старое сообщение"},
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        ],
        "has_more": False,
    }
    parsed = server_adapter.validate_python(raw)
    assert isinstance(parsed, ServerHistoryMessage)
    assert len(parsed.messages) == 1
    assert parsed.has_more is False


def test_server_error_message_with_enum():
    raw = {
        "type": "error",
        "code": ErrorCode.CONVERSATION_NOT_FOUND,
        "message": "Диалог не найден",
        "client_msg_id": str(uuid4()),
    }
    parsed = server_adapter.validate_python(raw)
    assert isinstance(parsed, ServerErrorMessage)
    assert parsed.code == ErrorCode.CONVERSATION_NOT_FOUND


def test_server_error_message_rejects_arbitrary_string_code():
    """code must be an exact ErrorCode member, arbitrary strings must fail."""
    raw = {
        "type": "error",
        "code": "WHATEVER",
        "message": "Some message",
        "client_msg_id": str(uuid4()),
    }
    with pytest.raises(ValidationError):
        server_adapter.validate_python(raw)


def test_server_peer_typing_message():
    """peer_typing is an optional UX extension schema."""
    raw = {
        "type": "peer_typing",
        "conversation_id": 10,
        "user_id": 42,
    }
    parsed = server_adapter.validate_python(raw)
    assert isinstance(parsed, ServerPeerTypingMessage)
    assert parsed.conversation_id == 10
    assert parsed.user_id == 42


# ---------------------------------------------------------------------------
# Session Cookie Signing & Expiry Tests
# ---------------------------------------------------------------------------

def test_session_cookie_signature_and_verification():
    user_id = 123
    cookie_val = sign_session_cookie(user_id)
    parts = cookie_val.split(".")
    assert len(parts) == 3
    assert int(parts[0]) == user_id
    assert verify_session_cookie(cookie_val) == user_id


def test_session_cookie_expired_fails():
    user_id = 55
    past_ts = int(time.time()) - (SESSION_COOKIE_MAX_AGE_SECONDS + 10)
    expired_cookie = sign_session_cookie(user_id, issued_at=past_ts)
    assert verify_session_cookie(expired_cookie) is None


def test_session_cookie_future_clock_skew_fails():
    user_id = 55
    future_ts = int(time.time()) + 120  # More than 60s skew allowance
    future_cookie = sign_session_cookie(user_id, issued_at=future_ts)
    assert verify_session_cookie(future_cookie) is None


def test_session_cookie_tampered_fails():
    user_id = 77
    cookie_val = sign_session_cookie(user_id)
    parts = cookie_val.split(".")
    tampered = f"{parts[0]}.{parts[1]}.badhexsignature"
    assert verify_session_cookie(tampered) is None


def test_session_cookie_signed_with_internal_secret_fails():
    """SESSION_SECRET and INTERNAL_SECRET must be separated and not interchangeable."""
    import hmac
    import hashlib
    user_id = 99
    now_ts = int(time.time())
    payload = f"{user_id}.{now_ts}".encode("utf-8")
    fake_sig = hmac.new(
        os.environ["INTERNAL_SECRET"].encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()
    wrong_key_cookie = f"{user_id}.{now_ts}.{fake_sig}"
    assert verify_session_cookie(wrong_key_cookie) is None


# ---------------------------------------------------------------------------
# Inter-node Delivery Tests
# ---------------------------------------------------------------------------

def test_internal_deliver_request_serialization():
    conn_id = uuid4()
    req = InternalDeliverRequest(
        targets=[DeliveryTarget(user_id=8, connection_id=conn_id)],
        event=ServerAckMessage(
            client_msg_id=uuid4(),
            conversation_id=1,
            seq=4,
            created_at=datetime.now(timezone.utc),
        ),
    )
    dumped = req.model_dump()
    assert dumped["targets"][0]["connection_id"] == conn_id
    assert dumped["targets"][0]["user_id"] == 8
    assert dumped["event"]["type"] == "ack"


def test_internal_deliver_endpoint_via_client():
    secret = os.environ["INTERNAL_SECRET"]
    conn_id = str(uuid4())
    payload = {
        "targets": [{"user_id": 8, "connection_id": conn_id}],
        "event": {
            "type": "ack",
            "client_msg_id": str(uuid4()),
            "conversation_id": 1,
            "seq": 4,
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    }

    # Unauthorized without secret
    r_no_auth = test_client.post("/internal/deliver", json=payload)
    assert r_no_auth.status_code == 403

    # Authorized with configured secret
    r_auth = test_client.post(
        "/internal/deliver",
        json=payload,
        headers={"X-Internal-Secret": secret},
    )
    assert r_auth.status_code == 200
    res = r_auth.json()
    assert "delivered" in res
    assert "missed" in res
    assert conn_id in res["missed"]  # Not in active local memory


def test_health_check_endpoint():
    r = test_client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# WebSocket Endpoint Tests (Origin, Cookie signing, closure codes, delivery)
# ---------------------------------------------------------------------------

def test_websocket_missing_origin_closed_with_4403():
    """Connections without Origin header must be closed with 4403."""
    with test_client.websocket_connect("/ws") as ws:
        msg = ws.receive()
        assert msg["type"] == "websocket.close"
        assert msg["code"] == 4403


def test_websocket_forbidden_origin_closed_with_4403():
    """Connections with disallowed Origin must be closed with 4403."""
    headers = {"Origin": "http://evil-attacker.com"}
    with test_client.websocket_connect("/ws", headers=headers) as ws:
        msg = ws.receive()
        assert msg["type"] == "websocket.close"
        assert msg["code"] == 4403


def test_websocket_missing_cookie_closed_with_4401():
    """Connections with allowed Origin but missing session cookie close with 4401."""
    headers = {"Origin": "http://localhost:8000"}
    with test_client.websocket_connect("/ws", headers=headers) as ws:
        msg = ws.receive()
        assert msg["type"] == "websocket.close"
        assert msg["code"] == 4401


def test_websocket_invalid_signed_cookie_closed_with_4401():
    """Connections with tampered/invalid session signature close with 4401."""
    headers = {"Origin": "http://localhost:8000"}
    cookies = {"session": "42.1700000000.tampered-signature-value"}
    with test_client.websocket_connect("/ws", headers=headers, cookies=cookies) as ws:
        msg = ws.receive()
        assert msg["type"] == "websocket.close"
        assert msg["code"] == 4401


def test_websocket_valid_session_connected_and_handles_events():
    """Connections with valid signed cookie connect, register, and process events in contract stub mode."""
    user_id = 99
    valid_cookie = sign_session_cookie(user_id)
    headers = {"Origin": "http://localhost:8000"}
    cookies = {"session": valid_cookie}

    with test_client.websocket_connect("/ws", headers=headers, cookies=cookies) as ws:
        # Check that connection was registered in active connections
        assert len(active_connections) == 1
        registered_conn_id = list(active_connections.keys())[0]

        # 1. Send ping (keepalive, accepted without error)
        ws.send_text('{"type": "ping"}')

        # 2. Send send_message -> stub explicitly returns error informing that real seq/DB is in next task (no fake seq)
        client_msg_id = str(uuid4())
        ws.send_text(
            f'{{"type": "send_message", "client_msg_id": "{client_msg_id}", "conversation_id": 1, "kind": "text", "payload": {{"text": "Hello"}}}}'
        )
        stub_resp = ws.receive_json()
        assert stub_resp["type"] == "error"
        assert stub_resp["code"] == "INTERNAL_ERROR"
        assert "contract verification stub" in stub_resp["message"]
        assert stub_resp["client_msg_id"] == client_msg_id

        # 3. Deliver event via /internal/deliver to this active connection
        secret = os.environ["INTERNAL_SECRET"]
        deliver_payload = {
            "targets": [{"user_id": user_id, "connection_id": str(registered_conn_id)}],
            "event": {
                "type": "ack",
                "client_msg_id": str(uuid4()),
                "conversation_id": 1,
                "seq": 4,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        }
        deliver_res = test_client.post(
            "/internal/deliver",
            json=deliver_payload,
            headers={"X-Internal-Secret": secret},
        )
        assert deliver_res.status_code == 200
        res_data = deliver_res.json()
        assert str(registered_conn_id) in res_data["delivered"]
        assert len(res_data["missed"]) == 0

        # Receive delivered event on websocket
        delivered_event = ws.receive_json()
        assert delivered_event["type"] == "ack"
        assert delivered_event["seq"] == 4

    # Once closed, connection is deregistered
    assert len(active_connections) == 0
