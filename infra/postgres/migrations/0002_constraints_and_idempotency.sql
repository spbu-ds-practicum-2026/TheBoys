-- ============================================================================
-- Migration 0002: Constraints, Node Foreign Key, and Sender Idempotency
-- ============================================================================

-- 1. Idempotency Key & Message Constraints
ALTER TABLE messages
    DROP CONSTRAINT IF EXISTS unique_conversation_client_msg;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'unique_conversation_sender_client_msg'
    ) THEN
        ALTER TABLE messages
            ADD CONSTRAINT unique_conversation_sender_client_msg
            UNIQUE (conversation_id, sender_id, client_msg_id);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'check_messages_seq_positive'
    ) THEN
        ALTER TABLE messages
            ADD CONSTRAINT check_messages_seq_positive
            CHECK (seq > 0);
    END IF;
END $$;

-- 2. Case-Insensitive User Logins
ALTER TABLE users
    DROP CONSTRAINT IF EXISTS users_login_key;

CREATE UNIQUE INDEX IF NOT EXISTS unique_users_login_lower
    ON users (LOWER(login));

-- 3. Conversation Counter Constraint
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'check_conversations_last_seq_non_negative'
    ) THEN
        ALTER TABLE conversations
            ADD CONSTRAINT check_conversations_last_seq_non_negative
            CHECK (last_seq >= 0);
    END IF;
END $$;

-- 4. Conversation Reads Position Constraint
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'check_conversation_reads_seq_non_negative'
    ) THEN
        ALTER TABLE conversation_reads
            ADD CONSTRAINT check_conversation_reads_seq_non_negative
            CHECK (last_read_seq >= 0);
    END IF;
END $$;

-- 5. Foreign Key: sessions.node_id -> node_registry.node_id
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_sessions_node_registry'
    ) THEN
        ALTER TABLE sessions
            ADD CONSTRAINT fk_sessions_node_registry
            FOREIGN KEY (node_id) REFERENCES node_registry(node_id) ON DELETE CASCADE;
    END IF;
END $$;

-- 6. Track Constraints (Duration and Size)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'check_tracks_duration_positive'
    ) THEN
        ALTER TABLE tracks
            ADD CONSTRAINT check_tracks_duration_positive
            CHECK (duration_s > 0);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'check_tracks_size_non_negative'
    ) THEN
        ALTER TABLE tracks
            ADD CONSTRAINT check_tracks_size_non_negative
            CHECK (size_bytes >= 0);
    END IF;
END $$;

-- 7. Job Constraints (Fencing token, replication track_id, running status lease)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'check_jobs_fencing_token_non_negative'
    ) THEN
        ALTER TABLE jobs
            ADD CONSTRAINT check_jobs_fencing_token_non_negative
            CHECK (fencing_token >= 0);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'check_jobs_replicate_track'
    ) THEN
        ALTER TABLE jobs
            ADD CONSTRAINT check_jobs_replicate_track
            CHECK (task_type != 'replicate' OR track_id IS NOT NULL);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'check_jobs_running_lease'
    ) THEN
        ALTER TABLE jobs
            ADD CONSTRAINT check_jobs_running_lease
            CHECK (status != 'running' OR (worker_id IS NOT NULL AND length(trim(worker_id)) > 0 AND lease_until IS NOT NULL));
    END IF;
END $$;

-- Record migration version
INSERT INTO schema_migrations (version, name)
VALUES (2, '0002_constraints_and_idempotency')
ON CONFLICT (version) DO NOTHING;
