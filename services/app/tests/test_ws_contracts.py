from datetime import datetime, timezone
from uuid import UUID, uuid4
import pytest
from fastapi.testclient import TestClient
from pydantic import TypeAdapter, ValidationError

from services.app.main import app
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
        "payload": {"text": "a" * 4001},
    }
    with pytest.raises(ValidationError):
        client_adapter.validate_python(raw)


def test_client_send_mismatched_kind_and_payload():
    msg_id = str(uuid4())
    raw = {
        "type": "send_message",
        "client_msg_id": msg_id,
        "conversation_id": 10,
        "kind": "text",
        "payload": {"track_id": str(uuid4())},
    }
    with pytest.raises(ValidationError) as exc:
        client_adapter.validate_python(raw)
    assert "Payload must be TextPayload when kind is 'text'" in str(exc.value)


def test_client_read_message():
    raw = {
        "type": "read",
        "conversation_id": 5,
        "up_to_seq": 100,
    }
    parsed = client_adapter.validate_python(raw)
    assert isinstance(parsed, ClientReadMessage)
    assert parsed.conversation_id == 5
    assert parsed.up_to_seq == 100


def test_client_read_message_zero_or_negative_seq_rejected():
    with pytest.raises(ValidationError):
        client_adapter.validate_python({"type": "read", "conversation_id": 5, "up_to_seq": 0})
    with pytest.raises(ValidationError):
        client_adapter.validate_python({"type": "read", "conversation_id": 0, "up_to_seq": 1})


def test_client_sync_message_bounds_and_limit():
    raw = {
        "type": "sync",
        "conversation_id": 12,
        "since_seq": 40,
        "limit": 25,
    }
    parsed = client_adapter.validate_python(raw)
    assert isinstance(parsed, ClientSyncMessage)
    assert parsed.conversation_id == 12
    assert parsed.since_seq == 40
    assert parsed.limit == 25

    # Backward history pagination
    raw_back = {
        "type": "sync",
        "conversation_id": 12,
        "before_seq": 15,
        "limit": 50,
    }
    parsed_back = client_adapter.validate_python(raw_back)
    assert parsed_back.before_seq == 15
    assert parsed_back.limit == 50

    # Limit > 100 or < 1 rejected
    with pytest.raises(ValidationError):
        client_adapter.validate_python({"type": "sync", "conversation_id": 1, "limit": 0})
    with pytest.raises(ValidationError):
        client_adapter.validate_python({"type": "sync", "conversation_id": 1, "limit": 101})


def test_client_ping_message():
    raw = {"type": "ping"}
    parsed = client_adapter.validate_python(raw)
    assert isinstance(parsed, ClientPingMessage)


def test_client_typing_message():
    raw = {"type": "typing", "conversation_id": 3}
    parsed = client_adapter.validate_python(raw)
    assert isinstance(parsed, ClientTypingMessage)
    assert parsed.conversation_id == 3


def test_client_invalid_unknown_type():
    with pytest.raises(ValidationError):
        client_adapter.validate_python({"type": "dance"})


def test_client_extra_fields_forbidden():
    with pytest.raises(ValidationError):
        client_adapter.validate_python({"type": "ping", "malicious_field": 123})


# ---------------------------------------------------------------------------
# Server Event Validation Tests
# ---------------------------------------------------------------------------

def test_server_ack_message():
    msg_id = str(uuid4())
    raw = {
        "type": "ack",
        "client_msg_id": msg_id,
        "conversation_id": 8,
        "seq": 15,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    parsed = server_adapter.validate_python(raw)
    assert isinstance(parsed, ServerAckMessage)
    assert parsed.seq == 15


def test_server_chat_message():
    msg_id = str(uuid4())
    track_id = str(uuid4())
    raw = {
        "type": "message",
        "conversation_id": 12,
        "seq": 45,
        "sender_id": 7,
        "client_msg_id": msg_id,
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


def test_server_chat_message_mismatched_payload_fails():
    msg_id = str(uuid4())
    raw = {
        "type": "message",
        "conversation_id": 12,
        "seq": 45,
        "sender_id": 7,
        "client_msg_id": msg_id,
        "kind": "track",
        "payload": {"text": "This is text, not track!"},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    with pytest.raises(ValidationError):
        server_adapter.validate_python(raw)


def test_server_read_ack_message():
    raw = {
        "type": "read_ack",
        "conversation_id": 12,
        "last_read_seq": 45,
        "unread_count": 0,
    }
    parsed = server_adapter.validate_python(raw)
    assert isinstance(parsed, ServerReadAckMessage)
    assert parsed.unread_count == 0


def test_server_dialog_sync():
    raw = {
        "type": "dialog_sync",
        "dialogs": [
            {"conversation_id": 1, "last_seq": 10, "unread_count": 2},
            {"conversation_id": 2, "last_seq": 50, "unread_count": 0},
        ],
    }
    parsed = server_adapter.validate_python(raw)
    assert isinstance(parsed, ServerDialogSyncMessage)
    assert len(parsed.dialogs) == 2


def test_server_history_message():
    msg_id = str(uuid4())
    raw = {
        "type": "history",
        "conversation_id": 10,
        "messages": [
            {
                "type": "message",
                "conversation_id": 10,
                "seq": 1,
                "sender_id": 2,
                "client_msg_id": msg_id,
                "kind": "text",
                "payload": {"text": "Первое сообщение"},
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
    assert parsed.code == "CONVERSATION_NOT_FOUND"


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

    # Authorized with secret
    r_auth = test_client.post(
        "/internal/deliver",
        json=payload,
        headers={"X-Internal-Secret": "super-secret-internal-key"},
    )
    assert r_auth.status_code == 200
    res = r_auth.json()
    assert "delivered" in res
    assert "missed" in res
    assert conn_id in res["missed"]  # Because connection is not in active local memory


def test_health_check_endpoint():
    r = test_client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
