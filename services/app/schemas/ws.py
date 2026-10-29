"""
WebSocket schemas for TheBoys messenger application node.

Contracts strictly conform to Technical Requirements (docs/tr.md):
- Discriminator: "type" field across all event models.
- extra = "forbid" to reject unexpected client attributes.
- Sequential ordering: monotonic per-dialogue seq numbers.
- Separation of Concerns: Client sends only track_id; metadata verified by server.
- Optional UX Extensions: typing and peer_typing are optional UX extensions not in core TR.
"""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal, Union
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Error Codes
# ---------------------------------------------------------------------------

class ErrorCode(StrEnum):
    CONVERSATION_NOT_FOUND = "CONVERSATION_NOT_FOUND"
    NOT_A_MEMBER = "NOT_A_MEMBER"
    TRACK_NOT_FOUND = "TRACK_NOT_FOUND"
    INVALID_PAYLOAD = "INVALID_PAYLOAD"
    INVALID_READ_POSITION = "INVALID_READ_POSITION"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    RATE_LIMITED = "RATE_LIMITED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


# ---------------------------------------------------------------------------
# Message Payloads
# ---------------------------------------------------------------------------

class TextPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(..., min_length=1, max_length=4000)

    @field_validator("text")
    @classmethod
    def validate_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Text cannot be empty or contain only whitespace")
        return v


class TrackSendPayload(BaseModel):
    """
    Client sends only track_id; metadata (title, artist, duration) is fetched
    securely by the server from the catalog in PostgreSQL to prevent spoofing.
    """
    model_config = ConfigDict(extra="forbid")
    track_id: UUID


class TrackPayload(BaseModel):
    """
    Server-provided verified track metadata attached to delivered chat messages
    and history events.
    """
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
    payload: Union[TextPayload, TrackSendPayload]

    @model_validator(mode="after")
    def validate_payload_matches_kind(self) -> "ClientSendMessage":
        if self.kind == "text" and not isinstance(self.payload, TextPayload):
            raise ValueError("Payload must be TextPayload when kind is 'text'")
        if self.kind == "track" and not isinstance(self.payload, TrackSendPayload):
            raise ValueError("Payload must be TrackSendPayload when kind is 'track'")
        return self


class ClientReadMessage(BaseModel):
    """
    Client reports the end of its continuous window of delivered messages (up_to_seq).
    Only accepted from conversation participants where up_to_seq > current_last_read_seq
    and up_to_seq <= last_seq.
    """
    model_config = ConfigDict(extra="forbid")
    type: Literal["read"] = "read"
    conversation_id: int = Field(..., gt=0)
    up_to_seq: int = Field(..., ge=1)


class ClientSyncMessage(BaseModel):
    """
    Sync missing messages after connection loss, gaps in seq, or scrolling history.
    - since_seq: fetch forward (strictly seq > since_seq)
    - before_seq: fetch backward (strictly seq < before_seq) for older history scrolling
    - limit: max messages to return (1..100, default 50)

    Semantics:
    - since_seq and before_seq are mutually exclusive pagination directions.
    - If neither is provided, defaults to since_seq = 0 (load initial history from start).
    - When scrolling backward from a conversation last_seq, client passes before_seq = last_seq + 1.
    """
    model_config = ConfigDict(extra="forbid")
    type: Literal["sync"] = "sync"
    conversation_id: int = Field(..., gt=0)
    since_seq: int | None = Field(default=None, ge=0)
    before_seq: int | None = Field(default=None, ge=1)
    limit: int = Field(default=50, ge=1, le=100)

    @model_validator(mode="after")
    def validate_bounds(self) -> "ClientSyncMessage":
        if self.since_seq is not None and self.before_seq is not None:
            raise ValueError("since_seq and before_seq are mutually exclusive")
        if self.since_seq is None and self.before_seq is None:
            self.since_seq = 0
        return self


class ClientPingMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["ping"] = "ping"


class ClientTypingMessage(BaseModel):
    """
    Optional UX typing indicator extension.
    Not part of core TR specification; broadcast ephemerally without persisting to database.
    """
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
    conversation_id: int = Field(..., gt=0)
    seq: int = Field(..., ge=1)
    created_at: datetime


class ServerChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["message"] = "message"
    conversation_id: int = Field(..., gt=0)
    seq: int = Field(..., ge=1)
    sender_id: int = Field(..., gt=0)
    client_msg_id: UUID
    kind: Literal["text", "track"]
    payload: Union[TextPayload, TrackPayload]
    created_at: datetime

    @model_validator(mode="after")
    def validate_payload_matches_kind(self) -> "ServerChatMessage":
        if self.kind == "text" and not isinstance(self.payload, TextPayload):
            raise ValueError("Payload must be TextPayload when kind is 'text'")
        if self.kind == "track" and not isinstance(self.payload, TrackPayload):
            raise ValueError("Payload must be TrackPayload when kind is 'track'")
        return self


class ServerReadAckMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["read_ack"] = "read_ack"
    conversation_id: int = Field(..., gt=0)
    last_read_seq: int = Field(..., ge=0)
    unread_count: int = Field(..., ge=0)


class DialogSyncItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conversation_id: int = Field(..., gt=0)
    last_seq: int = Field(..., ge=0)
    unread_count: int = Field(..., ge=0)


class ServerDialogSyncMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["dialog_sync"] = "dialog_sync"
    dialogs: list[DialogSyncItem]


class ServerHistoryMessage(BaseModel):
    """
    History response slice.
    - messages: ordered strictly ascending by seq.
    - has_more:
        - When querying with since_seq: has_more=True if there are newer messages beyond max(returned_seq).
        - When querying with before_seq: has_more=True if there are older messages remaining before min(returned_seq), i.e. min(returned_seq) > 1.
    """
    model_config = ConfigDict(extra="forbid")
    type: Literal["history"] = "history"
    conversation_id: int = Field(..., gt=0)
    messages: list[ServerChatMessage]
    has_more: bool = False


class ServerPeerTypingMessage(BaseModel):
    """
    Optional UX typing indicator extension.
    Not part of core TR specification; broadcast ephemerally without persisting to database.
    """
    model_config = ConfigDict(extra="forbid")
    type: Literal["peer_typing"] = "peer_typing"
    conversation_id: int = Field(..., gt=0)
    user_id: int = Field(..., gt=0)


class ServerErrorMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["error"] = "error"
    code: ErrorCode
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

class DeliveryTarget(BaseModel):
    """Target session connection on remote application node."""
    model_config = ConfigDict(extra="forbid")
    user_id: int = Field(..., gt=0)
    connection_id: UUID


class InternalDeliverRequest(BaseModel):
    """
    Inter-node delivery envelope sent via POST /internal/deliver.
    Allows targeting multiple connections across multiple users on the same node.
    """
    model_config = ConfigDict(extra="forbid")
    targets: list[DeliveryTarget] = Field(..., min_length=1)
    event: ServerOutgoingEvent


class InternalDeliverResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    delivered: list[UUID]
    missed: list[UUID]
