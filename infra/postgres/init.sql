-- ============================================================================
-- TheBoys Distributed Music Messenger: PostgreSQL Initial Schema (Stage 2 TR)
-- ============================================================================

-- 0. Versioning & Migration Tracking
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INT PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 1. Users (Case-Insensitive Unique Logins per TR & Web Contract)
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    login VARCHAR(64) NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS unique_users_login_lower
    ON users (LOWER(login));

-- 2. Node Registry (Heartbeat & Failure Detection)
CREATE TABLE IF NOT EXISTS node_registry (
    node_id VARCHAR(64) PRIMARY KEY,
    role VARCHAR(32) NOT NULL CHECK (role IN ('app', 'storage', 'worker')),
    endpoint_url TEXT NOT NULL,
    last_heartbeat TIMESTAMPTZ NOT NULL DEFAULT now(),
    status VARCHAR(16) NOT NULL DEFAULT 'alive' CHECK (status IN ('alive', 'dead'))
);

CREATE INDEX IF NOT EXISTS idx_node_registry_role_heartbeat
    ON node_registry (role, last_heartbeat);

-- 3. Conversations (Last Seq monotonic counter & pair uniqueness)
CREATE TABLE IF NOT EXISTS conversations (
    id SERIAL PRIMARY KEY,
    user1_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    user2_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    last_seq INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT check_distinct_users CHECK (user1_id != user2_id),
    CONSTRAINT check_conversations_last_seq_non_negative CHECK (last_seq >= 0)
);

-- Guarantee exactly one conversation per pair of users regardless of order
CREATE UNIQUE INDEX IF NOT EXISTS unique_conversation_pair
    ON conversations (LEAST(user1_id, user2_id), GREATEST(user1_id, user2_id));

-- 4. Messages (Monotonic Ordering & Sender Idempotency)
CREATE TABLE IF NOT EXISTS messages (
    id BIGSERIAL PRIMARY KEY,
    conversation_id INT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    seq INT NOT NULL,
    sender_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    client_msg_id UUID NOT NULL,
    kind VARCHAR(16) NOT NULL CHECK (kind IN ('text', 'track')),
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT check_messages_seq_positive CHECK (seq > 0),
    CONSTRAINT unique_conversation_seq UNIQUE (conversation_id, seq),
    CONSTRAINT unique_conversation_sender_client_msg UNIQUE (conversation_id, sender_id, client_msg_id)
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation_seq
    ON messages (conversation_id, seq);

-- 5. Read Positions
CREATE TABLE IF NOT EXISTS conversation_reads (
    conversation_id INT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    last_read_seq INT NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (conversation_id, user_id),
    CONSTRAINT check_conversation_reads_seq_non_negative CHECK (last_read_seq >= 0)
);

-- 6. Active Client Sessions (WebSockets bound to registered app node)
CREATE TABLE IF NOT EXISTS sessions (
    connection_id UUID PRIMARY KEY,
    user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    node_id VARCHAR(64) NOT NULL REFERENCES node_registry(node_id) ON DELETE CASCADE,
    last_seen TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sessions_user_last_seen
    ON sessions (user_id, last_seen);

-- 7. Track Catalog
CREATE TABLE IF NOT EXISTS tracks (
    id UUID PRIMARY KEY,
    title TEXT NOT NULL,
    artist TEXT NOT NULL,
    duration_s INT NOT NULL,
    size_bytes BIGINT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT check_tracks_duration_positive CHECK (duration_s > 0),
    CONSTRAINT check_tracks_size_non_negative CHECK (size_bytes >= 0)
);

CREATE INDEX IF NOT EXISTS idx_tracks_search_title
    ON tracks (LOWER(title));
CREATE INDEX IF NOT EXISTS idx_tracks_search_artist
    ON tracks (LOWER(artist));

-- 8. Storage Node Replicas (2 replicas per track)
CREATE TABLE IF NOT EXISTS replicas (
    id SERIAL PRIMARY KEY,
    track_id UUID NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
    node_id VARCHAR(64) NOT NULL REFERENCES node_registry(node_id) ON DELETE CASCADE,
    status VARCHAR(16) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'lost')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT unique_track_replica_node UNIQUE (track_id, node_id)
);

CREATE INDEX IF NOT EXISTS idx_replicas_track_status
    ON replicas (track_id, status);

-- 9. Background Job Queue (Worker leases & fencing tokens)
CREATE TABLE IF NOT EXISTS jobs (
    id SERIAL PRIMARY KEY,
    task_type VARCHAR(32) NOT NULL,
    track_id UUID REFERENCES tracks(id) ON DELETE CASCADE,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    status VARCHAR(16) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'running', 'completed', 'failed')),
    worker_id VARCHAR(64),
    fencing_token INT NOT NULL DEFAULT 0,
    lease_until TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT check_jobs_fencing_token_non_negative CHECK (fencing_token >= 0),
    CONSTRAINT check_jobs_replicate_track CHECK (task_type != 'replicate' OR track_id IS NOT NULL),
    CONSTRAINT check_jobs_running_lease CHECK (status != 'running' OR (worker_id IS NOT NULL AND length(trim(worker_id)) > 0 AND lease_until IS NOT NULL))
);

-- Ensure a track has at most one active replication job at a time
CREATE UNIQUE INDEX IF NOT EXISTS unique_active_job_per_track
    ON jobs (track_id, task_type)
    WHERE status IN ('pending', 'running');

-- Register initial migration versions for newly initialized databases
INSERT INTO schema_migrations (version, name) VALUES
    (1, '0001_initial_schema'),
    (2, '0002_constraints_and_idempotency')
ON CONFLICT (version) DO NOTHING;
