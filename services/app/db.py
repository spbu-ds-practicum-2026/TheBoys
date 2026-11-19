"""
Database Access Layer for TheBoys Application Node.

Implements all database operations required by Technical Requirements (docs/tr.md):
- Node registry and heartbeat tracking in table `node_registry`
- User authentication and lookup in table `users`
- Monotonic message ordering (`seq = last_seq + 1`) and sender idempotency in tables `conversations` and `messages`
- Active WebSocket session management in table `sessions` (freshness: <= 30 seconds)
- Read position tracking and unread counts in table `conversation_reads`
- Track catalog and search in table `tracks`
- Seamless in-memory fallback when live PostgreSQL is offline (e.g. for standalone unit tests)
"""

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone
from itertools import count
from typing import Any
from uuid import UUID

import asyncpg

logger = logging.getLogger(__name__)

# Initial seed tracks per TR & dev catalog
INITIAL_TRACKS = [
    {"id": UUID(int=1), "title": "Midnight Echoes", "artist": "The Boys Band", "duration_s": 42},
    {"id": UUID(int=2), "title": "Лунный свет", "artist": "Северное сияние", "duration_s": 35},
    {"id": UUID(int=3), "title": "Neon Rain", "artist": "Synth Collective", "duration_s": 48},
    {"id": UUID(int=4), "title": "Тёплый ветер", "artist": "Северное сияние", "duration_s": 30},
    {"id": UUID(int=5), "title": "Glass Highway", "artist": "The Boys Band", "duration_s": 55},
]


def clean_postgres_dsn(raw_url: str | None) -> str | None:
    if not raw_url:
        return None
    # Convert postgresql+asyncpg://... to postgresql://...
    return re.sub(r"^postgresql\+[a-zA-Z0-9_]+://", "postgresql://", raw_url)


class UserAlreadyExistsError(Exception):
    """Raised when trying to create a user with a login that already exists."""
    pass


class InMemoryStore:
    """Thread-safe in-memory store for unit test execution when PostgreSQL is offline."""

    def __init__(self):
        self.users: dict[int, dict[str, Any]] = {}
        self.conversations: dict[int, dict[str, Any]] = {}
        self.messages: dict[int, list[dict[str, Any]]] = {}  # conv_id -> list of messages
        self.reads: dict[tuple[int, int], int] = {}  # (conv_id, user_id) -> last_read_seq
        self.sessions: dict[UUID, dict[str, Any]] = {}  # conn_id -> session info
        self.node_registry: dict[str, dict[str, Any]] = {}
        self.tracks: dict[UUID, dict[str, Any]] = {t["id"]: dict(t) for t in INITIAL_TRACKS}
        self.replicas: dict[UUID, list[dict[str, Any]]] = {}
        self.user_ids = count(1)
        self.conversation_ids = count(1)
        self._real_lock: asyncio.Lock | None = None

    @property
    def _lock(self) -> asyncio.Lock:
        curr_loop = None
        try:
            curr_loop = asyncio.get_running_loop()
        except RuntimeError:
            pass
        if self._real_lock is None or (
            curr_loop is not None
            and getattr(self._real_lock, "_loop", None) is not None
            and self._real_lock._loop is not curr_loop
        ):
            self._real_lock = asyncio.Lock()
        return self._real_lock

    def clear(self):
        self.users.clear()
        self.conversations.clear()
        self.messages.clear()
        self.reads.clear()
        self.sessions.clear()
        self.node_registry.clear()
        self.tracks = {t["id"]: dict(t) for t in INITIAL_TRACKS}
        self.replicas.clear()
        self._real_lock = None


class Database:
    def __init__(self):
        self.pool: asyncpg.Pool | None = None
        self.memory = InMemoryStore()
        self.enable_in_memory: bool = False

    @property
    def is_connected(self) -> bool:
        return self.pool is not None

    async def connect(self, dsn: str | None = None) -> bool:
        target_dsn = clean_postgres_dsn(dsn or os.getenv("DATABASE_URL"))
        is_test_mode = os.getenv("TESTING") == "1" or self.enable_in_memory
        if not target_dsn:
            if is_test_mode:
                logger.info("TESTING mode: running with in-memory persistence.")
                return False
            raise RuntimeError(
                "DATABASE_URL environment variable is required in operational mode. "
                "In-memory persistence is strictly restricted to explicit testing mode."
            )

        try:
            self.pool = await asyncpg.create_pool(
                target_dsn,
                min_size=2,
                max_size=10,
                command_timeout=10,
            )
            logger.info("Connected to PostgreSQL successfully.")
            if is_test_mode:
                await self.seed_tracks_if_empty()
            return True
        except Exception as e:
            if is_test_mode:
                logger.warning("Could not connect to PostgreSQL (%s). Falling back to in-memory persistence for test mode.", e)
                self.pool = None
                return False
            logger.error("Could not connect to PostgreSQL: %s", e)
            raise RuntimeError(f"Could not connect to PostgreSQL: {e}")

    async def disconnect(self):
        if self.pool:
            await self.pool.close()
            self.pool = None

    # ---------------------------------------------------------------------------
    # Node Registry & Heartbeat (TR: Обнаружение отказов)
    # ---------------------------------------------------------------------------

    async def register_node(self, node_id: str, endpoint_url: str):
        if self.pool:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO node_registry (node_id, role, endpoint_url, last_heartbeat, status)
                    VALUES ($1, 'app', $2, now(), 'alive')
                    ON CONFLICT (node_id) DO UPDATE
                    SET role = 'app', endpoint_url = EXCLUDED.endpoint_url,
                        last_heartbeat = now(), status = 'alive'
                    """,
                    node_id,
                    endpoint_url,
                )
        else:
            self.memory.node_registry[node_id] = {
                "node_id": node_id,
                "role": "app",
                "endpoint_url": endpoint_url,
                "last_heartbeat": datetime.now(timezone.utc),
                "status": "alive",
            }

    async def heartbeat_node(self, node_id: str):
        if self.pool:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    "UPDATE node_registry SET last_heartbeat = now(), status = 'alive' WHERE node_id = $1",
                    node_id,
                )
        else:
            if node_id in self.memory.node_registry:
                self.memory.node_registry[node_id]["last_heartbeat"] = datetime.now(timezone.utc)
                self.memory.node_registry[node_id]["status"] = "alive"

    async def unregister_node(self, node_id: str):
        if self.pool:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    "UPDATE node_registry SET status = 'dead' WHERE node_id = $1",
                    node_id,
                )
        else:
            if node_id in self.memory.node_registry:
                self.memory.node_registry[node_id]["status"] = "dead"

    async def get_node_endpoint(self, node_id: str) -> str | None:
        if self.pool:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT endpoint_url FROM node_registry
                    WHERE node_id = $1
                      AND status = 'alive'
                      AND last_heartbeat >= now() - INTERVAL '15 seconds'
                    """,
                    node_id,
                )
                return row["endpoint_url"] if row else None
        else:
            node = self.memory.node_registry.get(node_id)
            if node and node["status"] == "alive":
                now = datetime.now(timezone.utc)
                if (now - node["last_heartbeat"]).total_seconds() <= 15:
                    return node["endpoint_url"]
            return None

    # ---------------------------------------------------------------------------
    # Users & Auth (TR: Сценарий 1)
    # ---------------------------------------------------------------------------

    async def create_user(self, login: str, password_hash: str) -> dict[str, Any]:
        login_clean = login.strip()
        if self.pool:
            async with self.pool.acquire() as conn:
                try:
                    row = await conn.fetchrow(
                        """
                        INSERT INTO users (login, password_hash)
                        VALUES ($1, $2)
                        RETURNING id, login, password_hash, created_at
                        """,
                        login_clean,
                        password_hash,
                    )
                    return dict(row)
                except asyncpg.UniqueViolationError:
                    raise UserAlreadyExistsError(f"User '{login_clean}' already exists")
        else:
            async with self.memory._lock:
                for u in self.memory.users.values():
                    if u["login"].lower() == login_clean.lower():
                        raise UserAlreadyExistsError(f"User '{login_clean}' already exists")
                new_id = next(self.memory.user_ids)
                user = {
                    "id": new_id,
                    "login": login_clean,
                    "password_hash": password_hash,
                    "created_at": datetime.now(timezone.utc),
                }
                self.memory.users[new_id] = user
                return dict(user)

    async def get_user_by_login(self, login: str) -> dict[str, Any] | None:
        login_clean = login.strip().lower()
        if self.pool:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT id, login, password_hash, created_at FROM users WHERE LOWER(login) = $1",
                    login_clean,
                )
                return dict(row) if row else None
        else:
            for u in self.memory.users.values():
                if u["login"].lower() == login_clean:
                    return dict(u)
            return None

    async def get_user_by_id(self, user_id: int) -> dict[str, Any] | None:
        if self.pool:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT id, login, password_hash, created_at FROM users WHERE id = $1",
                    user_id,
                )
                return dict(row) if row else None
        else:
            u = self.memory.users.get(user_id)
            return dict(u) if u else None

    # ---------------------------------------------------------------------------
    # Tracks Catalog (TR: Сценарии 2, 3)
    # ---------------------------------------------------------------------------

    async def seed_tracks_if_empty(self):
        if not self.pool:
            return
        async with self.pool.acquire() as conn:
            count_tracks = await conn.fetchval("SELECT count(*) FROM tracks")
            if count_tracks == 0:
                for t in INITIAL_TRACKS:
                    await conn.execute(
                        """
                        INSERT INTO tracks (id, title, artist, duration_s, size_bytes)
                        VALUES ($1, $2, $3, $4, 0)
                        ON CONFLICT (id) DO NOTHING
                        """,
                        t["id"],
                        t["title"],
                        t["artist"],
                        t["duration_s"],
                    )

    async def search_tracks(self, query: str = "") -> list[dict[str, Any]]:
        needle = query.strip().lower()
        if self.pool:
            async with self.pool.acquire() as conn:
                if not needle:
                    rows = await conn.fetch(
                        "SELECT id, title, artist, duration_s FROM tracks ORDER BY title ASC"
                    )
                else:
                    rows = await conn.fetch(
                        """
                        SELECT id, title, artist, duration_s FROM tracks
                        WHERE strpos(LOWER(title), $1) > 0 OR strpos(LOWER(artist), $1) > 0
                        ORDER BY title ASC
                        """,
                        needle,
                    )
                return [dict(r) for r in rows]
        else:
            found = [
                t for t in self.memory.tracks.values()
                if not needle or needle in t["title"].lower() or needle in t["artist"].lower()
            ]
            return [dict(t) for t in sorted(found, key=lambda x: x["title"])]

    async def get_track(self, track_id: UUID | str) -> dict[str, Any] | None:
        tid = UUID(str(track_id))
        if self.pool:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT id, title, artist, duration_s FROM tracks WHERE id = $1",
                    tid,
                )
                return dict(row) if row else None
        else:
            t = self.memory.tracks.get(tid)
            return dict(t) if t else None

    async def get_track_replicas(self, track_id: UUID | str) -> list[dict[str, Any]]:
        """
        Returns active replicas on live storage nodes with fresh heartbeat (TR: Technical Scenario 3, 7).
        """
        tid = UUID(str(track_id))
        if self.pool:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT r.node_id, n.endpoint_url
                    FROM replicas r
                    JOIN node_registry n ON n.node_id = r.node_id
                    WHERE r.track_id = $1
                      AND r.status = 'active'
                      AND n.status = 'alive'
                      AND n.last_heartbeat >= now() - INTERVAL '15 seconds'
                    ORDER BY r.id ASC
                    """,
                    tid,
                )
                return [dict(r) for r in rows]
        else:
            now = datetime.now(timezone.utc)
            reps = self.memory.replicas.get(tid, [])
            alive = []
            for r in reps:
                if r.get("status") == "active":
                    node = self.memory.node_registry.get(r["node_id"])
                    if node and node["status"] == "alive":
                        if (now - node["last_heartbeat"]).total_seconds() <= 15:
                            alive.append({
                                "node_id": r["node_id"],
                                "endpoint_url": node["endpoint_url"],
                            })
            return alive

    async def add_track_replica(self, track_id: UUID | str, node_id: str, status: str = "active"):
        tid = UUID(str(track_id))
        if self.pool:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO replicas (track_id, node_id, status)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (track_id, node_id) DO UPDATE SET status = EXCLUDED.status
                    """,
                    tid,
                    node_id,
                    status,
                )
        else:
            reps = self.memory.replicas.setdefault(tid, [])
            for r in reps:
                if r["node_id"] == node_id:
                    r["status"] = status
                    return
            reps.append({"track_id": tid, "node_id": node_id, "status": status})

    # ---------------------------------------------------------------------------
    # Conversations & User Lookup (TR: Сценарий 4, п. 1; Сценарий 5)
    # ---------------------------------------------------------------------------

    async def find_or_create_conversation(self, me_id: int, peer_id: int) -> dict[str, Any]:
        u1, u2 = sorted((me_id, peer_id))
        if self.pool:
            async with self.pool.acquire() as conn:
                # Try finding existing conversation
                row = await conn.fetchrow(
                    """
                    SELECT id, user1_id, user2_id, last_seq
                    FROM conversations
                    WHERE (user1_id = $1 AND user2_id = $2) OR (user1_id = $2 AND user2_id = $1)
                    """,
                    u1,
                    u2,
                )
                if not row:
                    # Insert new conversation (LEAST / GREATEST index guarantees uniqueness)
                    row = await conn.fetchrow(
                        """
                        INSERT INTO conversations (user1_id, user2_id, last_seq)
                        VALUES ($1, $2, 0)
                        ON CONFLICT ((LEAST(user1_id, user2_id)), (GREATEST(user1_id, user2_id)))
                        DO UPDATE SET user1_id = conversations.user1_id
                        RETURNING id, user1_id, user2_id, last_seq
                        """,
                        u1,
                        u2,
                    )
                return dict(row)
        else:
            async with self.memory._lock:
                for c in self.memory.conversations.values():
                    if {c["user1_id"], c["user2_id"]} == {u1, u2}:
                        return dict(c)
                new_id = next(self.memory.conversation_ids)
                conv = {"id": new_id, "user1_id": u1, "user2_id": u2, "last_seq": 0}
                self.memory.conversations[new_id] = conv
                self.memory.messages[new_id] = []
                return dict(conv)

    async def get_conversation(self, conv_id: int) -> dict[str, Any] | None:
        if self.pool:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT id, user1_id, user2_id, last_seq FROM conversations WHERE id = $1",
                    conv_id,
                )
                return dict(row) if row else None
        else:
            c = self.memory.conversations.get(conv_id)
            return dict(c) if c else None

    async def list_user_conversations(self, user_id: int) -> list[dict[str, Any]]:
        if self.pool:
            async with self.pool.acquire() as conn:
                # One query calculates unread counts and conversation peers (TR: Technical Scenario 5, p. 5)
                rows = await conn.fetch(
                    """
                    SELECT c.id AS conversation_id,
                           c.last_seq,
                           u.id AS peer_id,
                           u.login AS peer_login,
                           count(m.seq) AS unread_count
                    FROM conversations c
                    JOIN users u ON u.id = (CASE WHEN c.user1_id = $1 THEN c.user2_id ELSE c.user1_id END)
                    LEFT JOIN conversation_reads cr ON cr.conversation_id = c.id AND cr.user_id = $1
                    LEFT JOIN messages m ON m.conversation_id = c.id
                                        AND m.seq > COALESCE(cr.last_read_seq, 0)
                                        AND m.sender_id != $1
                    WHERE c.user1_id = $1 OR c.user2_id = $1
                    GROUP BY c.id, c.last_seq, u.id, u.login
                    ORDER BY c.id ASC
                    """,
                    user_id,
                )
                return [
                    {
                        "conversation_id": r["conversation_id"],
                        "peer": {"id": r["peer_id"], "login": r["peer_login"]},
                        "last_seq": r["last_seq"],
                        "unread_count": r["unread_count"],
                    }
                    for r in rows
                ]
        else:
            result = []
            for c in self.memory.conversations.values():
                if user_id not in (c["user1_id"], c["user2_id"]):
                    continue
                peer_id = c["user2_id"] if c["user1_id"] == user_id else c["user1_id"]
                peer = self.memory.users.get(peer_id, {"id": peer_id, "login": f"user-{peer_id}"})
                last_read = self.memory.reads.get((c["id"], user_id), 0)
                msgs = self.memory.messages.get(c["id"], [])
                unread = sum(1 for m in msgs if m["sender_id"] != user_id and m["seq"] > last_read)
                result.append({
                    "conversation_id": c["id"],
                    "peer": {"id": peer["id"], "login": peer["login"]},
                    "last_seq": c["last_seq"],
                    "unread_count": unread,
                })
            return result

    async def get_conversation_unread_count(self, conv_id: int, user_id: int) -> int:
        """Computes exact unread count for user in specific conversation (TR Technical Scenario 5, p. 5)."""
        if self.pool:
            async with self.pool.acquire() as conn:
                val = await conn.fetchval(
                    """
                    SELECT count(m.seq)
                    FROM messages m
                    LEFT JOIN conversation_reads cr
                           ON cr.conversation_id = m.conversation_id
                          AND cr.user_id = $2
                    WHERE m.conversation_id = $1
                      AND m.sender_id != $2
                      AND m.seq > COALESCE(cr.last_read_seq, 0)
                    """,
                    conv_id,
                    user_id,
                )
                return val or 0
        else:
            last_read = self.memory.reads.get((conv_id, user_id), 0)
            msgs = self.memory.messages.get(conv_id, [])
            return sum(1 for m in msgs if m["sender_id"] != user_id and m["seq"] > last_read)

    async def get_user_online_status(self, user_id: int) -> bool:
        if self.pool:
            async with self.pool.acquire() as conn:
                # Online if active session has ping <= 30 seconds on a node with heartbeat <= 15s (TR: Scenario 5, p. 2)
                val = await conn.fetchval(
                    """
                    SELECT EXISTS(
                        SELECT 1 FROM sessions s
                        JOIN node_registry n ON n.node_id = s.node_id
                        WHERE s.user_id = $1
                          AND n.status = 'alive'
                          AND n.last_heartbeat >= now() - INTERVAL '15 seconds'
                          AND s.last_seen >= now() - INTERVAL '30 seconds'
                    )
                    """,
                    user_id,
                )
                return bool(val)
        else:
            now = datetime.now(timezone.utc)
            for s in self.memory.sessions.values():
                if s["user_id"] == user_id:
                    session_diff = (now - s["last_seen"]).total_seconds()
                    if session_diff > 30:
                        continue
                    node = self.memory.node_registry.get(s["node_id"])
                    if not node or node["status"] != "alive":
                        continue
                    node_diff = (now - node["last_heartbeat"]).total_seconds()
                    if node_diff <= 15:
                        return True
            return False

    # ---------------------------------------------------------------------------
    # Monotonic Ordering & Message Storage (TR: Сценарий 4, пп. 3, 4)
    # ---------------------------------------------------------------------------

    async def store_message(
        self,
        conversation_id: int,
        sender_id: int,
        client_msg_id: UUID,
        kind: str,
        payload: dict[str, Any],
    ) -> tuple[int, datetime, bool, tuple[int, int]]:
        """
        In a single atomic transaction:
        - Locks conversation row FOR UPDATE
        - Checks idempotency: if (conversation_id, sender_id, client_msg_id) exists, returns existing seq
        - If new: last_seq += 1, inserts into messages, updates conversation.last_seq
        Returns: (seq, created_at, is_new, (user1_id, user2_id))
        """
        if self.pool:
            async with self.pool.acquire() as conn:
                async with conn.transaction():
                    conv = await conn.fetchrow(
                        "SELECT id, user1_id, user2_id, last_seq FROM conversations WHERE id = $1 FOR UPDATE",
                        conversation_id,
                    )
                    if not conv:
                        raise ValueError(f"Conversation {conversation_id} not found")
                    if sender_id not in (conv["user1_id"], conv["user2_id"]):
                        raise PermissionError("Sender is not a member of this conversation")

                    members = (conv["user1_id"], conv["user2_id"])

                    # Check idempotency
                    existing = await conn.fetchrow(
                        """
                        SELECT seq, created_at FROM messages
                        WHERE conversation_id = $1 AND sender_id = $2 AND client_msg_id = $3
                        """,
                        conversation_id,
                        sender_id,
                        client_msg_id,
                    )
                    if existing:
                        return existing["seq"], existing["created_at"], False, members

                    # Allocate new monotonic seq
                    new_seq = conv["last_seq"] + 1
                    await conn.execute(
                        "UPDATE conversations SET last_seq = $1 WHERE id = $2",
                        new_seq,
                        conversation_id,
                    )

                    created_at = datetime.now(timezone.utc)
                    await conn.execute(
                        """
                        INSERT INTO messages (conversation_id, seq, sender_id, client_msg_id, kind, payload, created_at)
                        VALUES ($1, $2, $3, $4, $5, $6, $7)
                        """,
                        conversation_id,
                        new_seq,
                        sender_id,
                        client_msg_id,
                        kind,
                        json.dumps(payload),
                        created_at,
                    )
                    return new_seq, created_at, True, members
        else:
            async with self.memory._lock:
                conv = self.memory.conversations.get(conversation_id)
                if not conv:
                    raise ValueError(f"Conversation {conversation_id} not found")
                if sender_id not in (conv["user1_id"], conv["user2_id"]):
                    raise PermissionError("Sender is not a member of this conversation")
                members = (conv["user1_id"], conv["user2_id"])

                msgs = self.memory.messages.setdefault(conversation_id, [])
                for m in msgs:
                    if m["sender_id"] == sender_id and m["client_msg_id"] == client_msg_id:
                        return m["seq"], m["created_at"], False, members

                # Realistic async context switch point: guarantees that atomicity
                # and lack of duplicate seqs is strictly enforced by self.memory._lock.
                await asyncio.sleep(0.0001)

                conv["last_seq"] += 1
                seq = conv["last_seq"]
                created_at = datetime.now(timezone.utc)
                stored = {
                    "conversation_id": conversation_id,
                    "seq": seq,
                    "sender_id": sender_id,
                    "client_msg_id": client_msg_id,
                    "kind": kind,
                    "payload": payload,
                    "created_at": created_at,
                }
                msgs.append(stored)
                return seq, created_at, True, members

    # ---------------------------------------------------------------------------
    # Read Position & Unread Counters (TR: Сценарий 5, п. 4)
    # ---------------------------------------------------------------------------

    async def update_read_position(
        self,
        conversation_id: int,
        user_id: int,
        up_to_seq: int,
    ) -> tuple[int, int]:
        """
        Updates read position in conversation_reads, capped by last_seq.
        Returns: (last_read_seq, unread_count)
        """
        if self.pool:
            async with self.pool.acquire() as conn:
                conv = await conn.fetchrow(
                    "SELECT last_seq, user1_id, user2_id FROM conversations WHERE id = $1",
                    conversation_id,
                )
                if not conv or user_id not in (conv["user1_id"], conv["user2_id"]):
                    raise PermissionError("Not a member")

                if up_to_seq > conv["last_seq"]:
                    raise ValueError("Position exceeds last_seq")

                # Atomic upsert ensuring read position only increases
                await conn.execute(
                    """
                    INSERT INTO conversation_reads (conversation_id, user_id, last_read_seq, updated_at)
                    VALUES ($1, $2, $3, now())
                    ON CONFLICT (conversation_id, user_id)
                    DO UPDATE SET last_read_seq = GREATEST(conversation_reads.last_read_seq, EXCLUDED.last_read_seq),
                                  updated_at = now()
                    """,
                    conversation_id,
                    user_id,
                    up_to_seq,
                )

                # Compute new unread count
                row = await conn.fetchrow(
                    """
                    SELECT cr.last_read_seq,
                           count(m.seq) AS unread_count
                    FROM conversation_reads cr
                    LEFT JOIN messages m ON m.conversation_id = cr.conversation_id
                                        AND m.seq > cr.last_read_seq
                                        AND m.sender_id != $2
                    WHERE cr.conversation_id = $1 AND cr.user_id = $2
                    GROUP BY cr.last_read_seq
                    """,
                    conversation_id,
                    user_id,
                )
                return row["last_read_seq"], row["unread_count"]
        else:
            async with self.memory._lock:
                conv = self.memory.conversations.get(conversation_id)
                if not conv or user_id not in (conv["user1_id"], conv["user2_id"]):
                    raise PermissionError("Not a member")
                if up_to_seq > conv["last_seq"]:
                    raise ValueError("Position exceeds last_seq")

                current = self.memory.reads.get((conversation_id, user_id), 0)
                new_pos = max(current, up_to_seq)
                self.memory.reads[(conversation_id, user_id)] = new_pos

                msgs = self.memory.messages.get(conversation_id, [])
                unread = sum(1 for m in msgs if m["sender_id"] != user_id and m["seq"] > new_pos)
                return new_pos, unread

    # ---------------------------------------------------------------------------
    # History Sync (TR: Сценарий 4, п. 4; Сценарий 6, п. 4)
    # ---------------------------------------------------------------------------

    async def get_history(
        self,
        conversation_id: int,
        user_id: int,
        before_seq: int | None = None,
        since_seq: int | None = None,
        limit: int = 50,
    ) -> tuple[list[dict[str, Any]], bool]:
        """
        Retrieves ordered history slice.
        Returns: (messages, has_more)
        """
        if self.pool:
            async with self.pool.acquire() as conn:
                conv = await conn.fetchrow(
                    "SELECT user1_id, user2_id FROM conversations WHERE id = $1",
                    conversation_id,
                )
                if not conv or user_id not in (conv["user1_id"], conv["user2_id"]):
                    raise PermissionError("Not a member")

                if before_seq is not None:
                    rows = await conn.fetch(
                        """
                        SELECT id, conversation_id, seq, sender_id, client_msg_id, kind, payload, created_at
                        FROM messages
                        WHERE conversation_id = $1 AND seq < $2
                        ORDER BY seq DESC
                        LIMIT $3
                        """,
                        conversation_id,
                        before_seq,
                        limit,
                    )
                    # Ordered ascending
                    chunk = [dict(r) for r in reversed(rows)]
                    has_more = bool(chunk) and chunk[0]["seq"] > 1
                else:
                    after_val = since_seq or 0
                    rows = await conn.fetch(
                        """
                        SELECT id, conversation_id, seq, sender_id, client_msg_id, kind, payload, created_at
                        FROM messages
                        WHERE conversation_id = $1 AND seq > $2
                        ORDER BY seq ASC
                        LIMIT $3 + 1
                        """,
                        conversation_id,
                        after_val,
                        limit,
                    )
                    has_more = len(rows) > limit
                    chunk = [dict(r) for r in rows[:limit]]

                # Deserialize json payloads if needed
                for m in chunk:
                    if isinstance(m["payload"], str):
                        m["payload"] = json.loads(m["payload"])
                return chunk, has_more
        else:
            async with self.memory._lock:
                conv = self.memory.conversations.get(conversation_id)
                if not conv or user_id not in (conv["user1_id"], conv["user2_id"]):
                    raise PermissionError("Not a member")
                all_msgs = self.memory.messages.get(conversation_id, [])

                if before_seq is not None:
                    older = [m for m in all_msgs if m["seq"] < before_seq]
                    chunk = older[-limit:]
                    has_more = bool(chunk) and chunk[0]["seq"] > 1
                else:
                    after_val = since_seq or 0
                    newer = [m for m in all_msgs if m["seq"] > after_val]
                    chunk = newer[:limit]
                    has_more = len(newer) > len(chunk)
                return [dict(m) for m in chunk], has_more

    # ---------------------------------------------------------------------------
    # Active Sessions (TR: Сценарий 4, п. 4; Сценарий 5, п. 1)
    # ---------------------------------------------------------------------------

    async def register_session(self, connection_id: UUID, user_id: int, node_id: str):
        if self.pool:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO sessions (connection_id, user_id, node_id, last_seen)
                    VALUES ($1, $2, $3, now())
                    ON CONFLICT (connection_id) DO UPDATE
                    SET last_seen = now(), node_id = EXCLUDED.node_id
                    """,
                    connection_id,
                    user_id,
                    node_id,
                )
        else:
            self.memory.sessions[connection_id] = {
                "connection_id": connection_id,
                "user_id": user_id,
                "node_id": node_id,
                "last_seen": datetime.now(timezone.utc),
            }

    async def touch_session(self, connection_id: UUID):
        if self.pool:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    "UPDATE sessions SET last_seen = now() WHERE connection_id = $1",
                    connection_id,
                )
        else:
            if connection_id in self.memory.sessions:
                self.memory.sessions[connection_id]["last_seen"] = datetime.now(timezone.utc)

    async def remove_session(self, connection_id: UUID):
        if self.pool:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    "DELETE FROM sessions WHERE connection_id = $1",
                    connection_id,
                )
        else:
            self.memory.sessions.pop(connection_id, None)

    async def get_active_sessions_for_users(self, user_ids: list[int]) -> list[dict[str, Any]]:
        if not user_ids:
            return []
        if self.pool:
            async with self.pool.acquire() as conn:
                # Fresh sessions <= 30s on alive nodes with heartbeat <= 15s (TR: Scenario 4, 5, failure detection)
                rows = await conn.fetch(
                    """
                    SELECT s.connection_id, s.user_id, s.node_id
                    FROM sessions s
                    JOIN node_registry n ON n.node_id = s.node_id
                    WHERE s.user_id = ANY($1::int[])
                      AND n.status = 'alive'
                      AND n.last_heartbeat >= now() - INTERVAL '15 seconds'
                      AND s.last_seen >= now() - INTERVAL '30 seconds'
                    """,
                    user_ids,
                )
                return [dict(r) for r in rows]
        else:
            now = datetime.now(timezone.utc)
            results = []
            for s in self.memory.sessions.values():
                if s["user_id"] in user_ids:
                    session_diff = (now - s["last_seen"]).total_seconds()
                    if session_diff > 30:
                        continue
                    node = self.memory.node_registry.get(s["node_id"])
                    if not node or node["status"] != "alive":
                        continue
                    node_diff = (now - node["last_heartbeat"]).total_seconds()
                    if node_diff <= 15:
                        results.append({
                            "connection_id": s["connection_id"],
                            "user_id": s["user_id"],
                            "node_id": s["node_id"],
                        })
            return results


# Global singleton instance
db = Database()
