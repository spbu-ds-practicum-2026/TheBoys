-- ============================================================================
-- Migration 0003: Transient Replica Failures Tracking (TR Technical Scenario 7)
-- ============================================================================

CREATE TABLE IF NOT EXISTS replica_failures (
    track_id UUID NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
    node_id VARCHAR(64) NOT NULL REFERENCES node_registry(node_id) ON DELETE CASCADE,
    failed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (track_id, node_id)
);

CREATE INDEX IF NOT EXISTS idx_replica_failures_track_failed_at
    ON replica_failures (track_id, failed_at);

-- Record migration version
INSERT INTO schema_migrations (version, name)
VALUES (3, '0003_replica_failures')
ON CONFLICT (version) DO NOTHING;
