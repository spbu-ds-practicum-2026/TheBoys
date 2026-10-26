from datetime import datetime, timezone
from uuid import uuid4
import pytest
from pydantic import TypeAdapter, ValidationError

from services.app.schemas.ws import (
    ClientIncomingEvent,
    ClientPingMessage,
    ClientReadMessage,
    ClientSendMessage,
    ClientSyncMessage,
    ClientTypingMessage,
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
)

client_adapter = TypeAdapter(ClientIncomingEvent)
server_adapter = TypeAdapter(ServerOutgoingEvent)


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


def test_client_send_track_message():
    msg_id = str(uuid4())
    track_id = str(uuid4())
    raw = {
        "type": "send_message",
        "client_msg_id": msg_id,
        "conversation_id": 42,
        "kind": "track",
        "payload": {
            "track_id": track_id,
            "title": "Blinding Lights",
            "artist": "The Weeknd",
            "duration_s": 200,
        },
    }
    parsed = client_adapter.validate_python(raw)
    assert isinstance(parsed, ClientSendMessage)
    assert parsed.kind == "track"
    assert isinstance(parsed.payload, TrackPayload)
    assert str(parsed.payload.track_id) == track_id
    assert parsed.payload.title == "Blinding Lights"
    assert parsed.payload.artist == "The Weeknd"
    assert parsed.payload.duration_s == 200


def test_client_send_mismatched_kind_and_payload():
    msg_id = str(uuid4())
    raw = {
        "type": "send_message",
        "client_msg_id": msg_id,
        "conversation_id": 10,
        "kind": "track",
        "payload": {"text": "Это не трек!"},
    }
    with pytest.raises(ValidationError):
        client_adapter.validate_python(raw)


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


def test_client_sync_message():
    raw = {
        "type": "sync",
        "conversation_id": 5,
        "since_seq": 20,
    }
    parsed = client_adapter.validate_python(raw)
    assert isinstance(parsed, ClientSyncMessage)
    assert parsed.since_seq == 20


def test_client_ping_message():
    raw = {"type": "ping"}
    parsed = client_adapter.validate_python(raw)
    assert isinstance(parsed, ClientPingMessage)


def test_client_typing_message():
    raw = {"type": "typing", "conversation_id": 7}
    parsed = client_adapter.validate_python(raw)
    assert isinstance(parsed, ClientTypingMessage)
    assert parsed.conversation_id == 7


def test_client_invalid_unknown_type():
    with pytest.raises(ValidationError):
        client_adapter.validate_python({"type": "magic_spell"})


def test_client_invalid_missing_fields():
    with pytest.raises(ValidationError):
        client_adapter.validate_python({"type": "send_message", "conversation_id": 1})


def test_client_extra_fields_forbidden():
    with pytest.raises(ValidationError):
        client_adapter.validate_python({"type": "ping", "unauthorized_extra": "hack"})


# ---------------------------------------------------------------------------
# Server Event Validation Tests
# ---------------------------------------------------------------------------

def test_server_ack_message():
    msg_id = str(uuid4())
    now = datetime.now(timezone.utc)
    raw = {
        "type": "ack",
        "client_msg_id": msg_id,
        "conversation_id": 1,
        "seq": 15,
        "created_at": now.isoformat(),
    }
    parsed = server_adapter.validate_python(raw)
    assert isinstance(parsed, ServerAckMessage)
    assert parsed.seq == 15
    assert str(parsed.client_msg_id) == msg_id


def test_server_chat_message():
    msg_id = str(uuid4())
    now = datetime.now(timezone.utc)
    raw = {
        "type": "message",
        "conversation_id": 3,
        "seq": 10,
        "sender_id": 99,
        "client_msg_id": msg_id,
        "kind": "text",
        "payload": {"text": "Всё работает!"},
        "created_at": now.isoformat(),
    }
    parsed = server_adapter.validate_python(raw)
    assert isinstance(parsed, ServerChatMessage)
    assert parsed.sender_id == 99
    assert parsed.seq == 10


def test_server_read_ack_message():
    raw = {
        "type": "read_ack",
        "conversation_id": 3,
        "last_read_seq": 10,
        "unread_count": 0,
    }
    parsed = server_adapter.validate_python(raw)
    assert isinstance(parsed, ServerReadAckMessage)
    assert parsed.last_read_seq == 10
    assert parsed.unread_count == 0


def test_server_dialog_sync():
    raw = {
        "type": "dialog_sync",
        "dialogs": [
            {"conversation_id": 1, "last_seq": 50, "unread_count": 2},
            {"conversation_id": 2, "last_seq": 12, "unread_count": 0},
        ],
    }
    parsed = server_adapter.validate_python(raw)
    assert isinstance(parsed, ServerDialogSyncMessage)
    assert len(parsed.dialogs) == 2
    assert parsed.dialogs[0].last_seq == 50


def test_server_history_message():
    msg_id = str(uuid4())
    now = datetime.now(timezone.utc)
    raw = {
        "type": "history",
        "conversation_id": 1,
        "messages": [
            {
                "conversation_id": 1,
                "seq": 1,
                "sender_id": 2,
                "client_msg_id": msg_id,
                "kind": "text",
                "payload": {"text": "hello"},
                "created_at": now.isoformat(),
            }
        ],
    }
    parsed = server_adapter.validate_python(raw)
    assert isinstance(parsed, ServerHistoryMessage)
    assert len(parsed.messages) == 1


def test_server_peer_typing():
    raw = {
        "type": "peer_typing",
        "conversation_id": 1,
        "user_id": 2,
    }
    parsed = server_adapter.validate_python(raw)
    assert isinstance(parsed, ServerPeerTypingMessage)
    assert parsed.user_id == 2


def test_server_error_message():
    raw = {
        "type": "error",
        "code": "FORBIDDEN",
        "message": "User not in conversation",
    }
    parsed = server_adapter.validate_python(raw)
    assert isinstance(parsed, ServerErrorMessage)
    assert parsed.code == "FORBIDDEN"


# ---------------------------------------------------------------------------
# Inter-node Delivery Tests (/internal/deliver)
# ---------------------------------------------------------------------------

def test_internal_deliver_request_serialization():
    msg_id = uuid4()
    now = datetime.now(timezone.utc)
    chat_event = ServerChatMessage(
        conversation_id=8,
        seq=33,
        sender_id=12,
        client_msg_id=msg_id,
        kind="text",
        payload={"text": "Доставка между узлами"},
        created_at=now,
    )
    req = InternalDeliverRequest(
        connection_ids=["conn-1", "conn-2"],
        user_id=14,
        event=chat_event,
    )
    dumped = req.model_dump(mode="json")
    assert dumped["connection_ids"] == ["conn-1", "conn-2"]
    assert dumped["user_id"] == 14
    assert dumped["event"]["type"] == "message"
    assert dumped["event"]["seq"] == 33

    # Restore from dumped json
    restored = InternalDeliverRequest.model_validate(dumped)
    assert restored.user_id == 14
    assert isinstance(restored.event, ServerChatMessage)
    assert restored.event.seq == 33


def test_internal_deliver_response():
    resp = InternalDeliverResponse(delivered=["conn-1"], missed=["conn-2"])
    dumped = resp.model_dump(mode="json")
    assert dumped == {"delivered": ["conn-1"], "missed": ["conn-2"]}
