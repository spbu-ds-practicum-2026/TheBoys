from datetime import datetime
from typing import Annotated, Any, Literal, Union
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator


# ---------------------------------------------------------------------------
# Message Payloads
# ---------------------------------------------------------------------------

class TextPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(..., min_length=1, max_length=4000)


class TrackPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    track_id: UUID
    title: str = Field(..., min_length=1, max_length=255)
    artist: str = Field(..., min_length=1, max_length=255)
    duration_s: int = Field(..., ge=0)


# ---------------------------------------------------------------------------
# Client -> Server WebSocket Events
# ---------------------------------------------------------------------------

class ClientSendMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["send_message"] = "send_message"
    client_msg_id: UUID
    conversation_id: int = Field(..., gt=0)
    kind: Literal["text", "track"]
    payload: Union[TextPayload, TrackPayload]

    @model_validator(mode="after")
    def validate_payload_matches_kind(self) -> "ClientSendMessage":
        if self.kind == "text" and not isinstance(self.payload, TextPayload):
            raise ValueError("Payload must be TextPayload when kind is 'text'")
        if self.kind == "track" and not isinstance(self.payload, TrackPayload):
            raise ValueError("Payload must be TrackPayload when kind is 'track'")
        return self


class ClientReadMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["read"] = "read"
    conversation_id: int = Field(..., gt=0)
    up_to_seq: int = Field(..., ge=1)


class ClientSyncMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["sync"] = "sync"
    conversation_id: int = Field(..., gt=0)
    since_seq: int = Field(default=0, ge=0)


class ClientPingMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["ping"] = "ping"


class ClientTypingMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["typing"] = "typing"
    conversation_id: int = Field(..., gt=0)


ClientIncomingEvent = Annotated[
    Union[
        ClientSendMessage,
        ClientReadMessage,
        ClientSyncMessage,
        ClientPingMessage,
        ClientTypingMessage,
    ],
    Field(discriminator="type"),
]


# ---------------------------------------------------------------------------
# Server -> Client WebSocket Events
# ---------------------------------------------------------------------------

class ServerAckMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["ack"] = "ack"
    client_msg_id: UUID
    conversation_id: int
    seq: int = Field(..., ge=1)
    created_at: datetime


class ServerChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["message"] = "message"
    conversation_id: int
    seq: int = Field(..., ge=1)
    sender_id: int
    client_msg_id: UUID
    kind: Literal["text", "track"]
    payload: Union[TextPayload, TrackPayload, dict[str, Any]]
    created_at: datetime


class ServerReadAckMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["read_ack"] = "read_ack"
    conversation_id: int
    last_read_seq: int = Field(..., ge=0)
    unread_count: int = Field(..., ge=0)


class DialogSyncItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conversation_id: int
    last_seq: int = Field(..., ge=0)
    unread_count: int = Field(..., ge=0)


class ServerDialogSyncMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["dialog_sync"] = "dialog_sync"
    dialogs: list[DialogSyncItem]


class ServerHistoryMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["history"] = "history"
    conversation_id: int
    messages: list[ServerChatMessage]


class ServerPeerTypingMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["peer_typing"] = "peer_typing"
    conversation_id: int
    user_id: int


class ServerErrorMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["error"] = "error"
    code: str
    message: str
    client_msg_id: UUID | None = None


ServerOutgoingEvent = Annotated[
    Union[
        ServerAckMessage,
        ServerChatMessage,
        ServerReadAckMessage,
        ServerDialogSyncMessage,
        ServerHistoryMessage,
        ServerPeerTypingMessage,
        ServerErrorMessage,
    ],
    Field(discriminator="type"),
]


# ---------------------------------------------------------------------------
# Inter-node Delivery (/internal/deliver)
# ---------------------------------------------------------------------------

class InternalDeliverRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    connection_ids: list[str] = Field(..., min_length=1)
    user_id: int
    event: ServerOutgoingEvent


class InternalDeliverResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    delivered: list[str]
    missed: list[str]
