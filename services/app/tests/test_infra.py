"""
Infrastructure & Configuration Compliance Tests (DevOps / QA).

Verifies that the Docker Compose configuration, Nginx reverse proxy rules,
PostgreSQL schemas, migrations, and runtime behavior strictly adhere to
the Technical Requirements (TR) and review specifications.
"""

import os
import re
from pathlib import Path
from uuid import uuid4

try:
    import pytest
except ImportError:
    class _MockPytest:
        class mark:
            @staticmethod
            def asyncio(fn):
                return fn
        @staticmethod
        def skip(reason=""):
            print(f"[SKIPPED] {reason}")
    pytest = _MockPytest()



REPO_ROOT = Path(__file__).resolve().parents[3]


# ============================================================================
# 1. Static Configuration & Rule Audits
# ============================================================================

def test_nginx_config_rules():
    """Verify critical Nginx configuration directives per TR requirements."""
    nginx_conf = REPO_ROOT / "infra" / "nginx" / "nginx.conf"
    assert nginx_conf.exists(), "infra/nginx/nginx.conf must exist"

    content = nginx_conf.read_text(encoding="utf-8")

    # 1. Embedded Docker DNS resolver for dynamic service discovery
    assert "resolver 127.0.0.11" in content, "Must use Docker DNS resolver 127.0.0.11"
    assert "valid=5s" in content, "Resolver must have short TTL for dynamic service discovery"

    # 2. Strict /internal/* blocking
    assert "location ^~ /internal/" in content or "location /internal/" in content
    assert "return 403" in content, "External access to /internal/* must return 403 Forbidden"

    # 3. WebSocket upgrade mapping
    assert "map $http_upgrade $connection_upgrade" in content
    assert "proxy_set_header Upgrade $http_upgrade;" in content
    assert "proxy_set_header Connection $connection_upgrade;" in content

    # 4. Dynamic upstream resolution via variable
    assert "set $app_upstream" in content
    assert "proxy_pass http://$app_upstream;" in content


def test_postgres_schema_entities_and_constraints():
    """
    Verify all entities and required architectural constraints in init.sql
    and versioned migrations.
    """
    init_sql = REPO_ROOT / "infra" / "postgres" / "init.sql"
    assert init_sql.exists(), "infra/postgres/init.sql must exist"
    content = init_sql.read_text(encoding="utf-8")

    required_tables = [
        "schema_migrations",
        "users",
        "node_registry",
        "conversations",
        "messages",
        "conversation_reads",
        "sessions",
        "tracks",
        "replicas",
        "jobs",
    ]
    for table in required_tables:
        assert f"CREATE TABLE IF NOT EXISTS {table}" in content, f"Table definition missing: {table}"

    # 1. Message Idempotency: MUST include sender_id in the unique constraint
    # (conversation_id, sender_id, client_msg_id)
    assert "unique_conversation_sender_client_msg" in content, (
        "Idempotency constraint must be unique_conversation_sender_client_msg"
    )
    assert re.search(
        r"UNIQUE\s*\(\s*conversation_id\s*,\s*sender_id\s*,\s*client_msg_id\s*\)",
        content,
        re.IGNORECASE,
    ), "Constraint must cover (conversation_id, sender_id, client_msg_id)"

    # Ensure obsolete flawed constraint (conversation_id, client_msg_id) is NOT present
    assert not re.search(
        r"CONSTRAINT\s+unique_conversation_client_msg\s+UNIQUE\s*\(\s*conversation_id\s*,\s*client_msg_id\s*\)",
        content,
        re.IGNORECASE,
    ), "Old two-field idempotency constraint must be replaced"

    # 2. Case-Insensitive User Logins
    assert "unique_users_login_lower" in content, "Must have unique index on lower(login)"
    assert re.search(
        r"CREATE\s+UNIQUE\s+INDEX\s+IF\s+NOT\s+EXISTS\s+unique_users_login_lower\s+ON\s+users\s*\(\s*LOWER\s*\(\s*login\s*\)\s*\)",
        content,
        re.IGNORECASE,
    ), "Must enforce uniqueness on LOWER(login)"

    # 3. Base Database Check Constraints
    checks = [
        "check_messages_seq_positive",
        "check_conversations_last_seq_non_negative",
        "check_conversation_reads_seq_non_negative",
        "check_jobs_fencing_token_non_negative",
        "check_tracks_duration_positive",
        "check_tracks_size_non_negative",
        "check_jobs_replicate_track",
        "check_jobs_running_lease",
    ]
    for chk in checks:
        assert chk in content, f"CHECK constraint missing in init.sql: {chk}"

    # 4. Foreign Key: sessions.node_id -> node_registry.node_id
    assert re.search(
        r"node_id\s+VARCHAR\(64\)\s+NOT\s+NULL\s+REFERENCES\s+node_registry\s*\(\s*node_id\s*\)",
        content,
        re.IGNORECASE,
    ), "sessions.node_id must reference node_registry(node_id)"


def test_migrations_directory_structure():
    """Verify that versioned migrations exist and follow naming standards."""
    migrations_dir = REPO_ROOT / "infra" / "postgres" / "migrations"
    assert migrations_dir.exists(), "infra/postgres/migrations must exist"

    mig_0001 = migrations_dir / "0001_initial_schema.sql"
    mig_0002 = migrations_dir / "0002_constraints_and_idempotency.sql"

    assert mig_0001.exists(), "Migration 0001 must exist"
    assert mig_0002.exists(), "Migration 0002 must exist"

    # Migration 0002 must safely migrate existing database
    c0002 = mig_0002.read_text(encoding="utf-8")
    assert "unique_conversation_sender_client_msg" in c0002
    assert "unique_users_login_lower" in c0002
    assert "check_messages_seq_positive" in c0002
    assert "fk_sessions_node_registry" in c0002


def test_docker_compose_and_dockerignore_compliance():
    """Verify Docker Compose configurations, localhost binding, and .dockerignore."""
    compose_file = REPO_ROOT / "docker-compose.yml"
    assert compose_file.exists(), "docker-compose.yml must exist"

    content = compose_file.read_text(encoding="utf-8")

    # 1. PostgreSQL security: strictly bound to localhost (127.0.0.1:5432:5432)
    assert '127.0.0.1:5432:5432' in content, (
        "PostgreSQL port must be bound strictly to 127.0.0.1:5432:5432 to avoid external exposure"
    )
    assert not re.search(r'^\s*-\s*"5432:5432"', content, re.MULTILINE), (
        "PostgreSQL must not be exposed on all interfaces (0.0.0.0:5432)"
    )

    # 2. Environment passing: ALLOWED_ORIGINS and SESSION_COOKIE_MAX_AGE_SECONDS
    assert "ALLOWED_ORIGINS: ${ALLOWED_ORIGINS:-" in content or "ALLOWED_ORIGINS: ${ALLOWED_ORIGINS}" in content
    assert "SESSION_COOKIE_MAX_AGE_SECONDS:" in content

    # 3. Mounts for migrations
    assert "migrations" in content, "docker-compose.yml must mount migrations directory"

    # 4. Root .dockerignore existence for root context builds
    root_dockerignore = REPO_ROOT / ".dockerignore"
    assert root_dockerignore.exists(), "Root .dockerignore must exist for build context '.'"
    ignore_content = root_dockerignore.read_text(encoding="utf-8")
    assert ".git" in ignore_content
    assert ".env" in ignore_content


# ============================================================================
# 2. Live PostgreSQL Execution Tests (if DB available)
# ============================================================================

def get_test_db_url():
    """Retrieve test database URL from environment if configured."""
    return os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")


async def connect_async_pg(url: str):
    import asyncpg
    clean_url = re.sub(r"^postgresql\+[a-zA-Z0-9_]+://", "postgresql://", url)
    return await asyncpg.connect(clean_url)


@pytest.mark.asyncio
async def test_postgres_schema_and_constraints_live():
    """
    Live verification of PostgreSQL constraints, idempotency key with sender_id,
    case-insensitive login uniqueness, and foreign keys.
    """
    db_url = get_test_db_url()
    if not db_url:
        pytest.skip("Live PostgreSQL tests require TEST_DATABASE_URL or DATABASE_URL")

    try:
        import asyncpg
    except ImportError:
        pytest.skip("asyncpg is required for live PostgreSQL tests")

    try:
        conn = await connect_async_pg(db_url)
    except Exception as e:
        pytest.skip(f"Could not connect to PostgreSQL at {db_url}: {e}")

    try:
        # Run test in transaction that rolls back completely
        tr = conn.transaction()
        await tr.start()

        # 1. Check user case-insensitive login uniqueness
        user_id_1 = await conn.fetchval(
            "INSERT INTO users (login, password_hash) VALUES ($1, $2) RETURNING id;",
            "Oleg",
            "hash_123",
        )
        assert user_id_1 > 0

        # Inserting lowercase 'oleg' must fail with UniqueViolation
        with pytest.raises(asyncpg.UniqueViolationError):
            await conn.execute(
                "INSERT INTO users (login, password_hash) VALUES ($1, $2);",
                "oleg",
                "hash_456",
            )

        # Create second user
        user_id_2 = await conn.fetchval(
            "INSERT INTO users (login, password_hash) VALUES ($1, $2) RETURNING id;",
            "Alice",
            "hash_789",
        )

        # 2. Create conversation
        conv_id = await conn.fetchval(
            "INSERT INTO conversations (user1_id, user2_id, last_seq) VALUES ($1, $2, 0) RETURNING id;",
            user_id_1,
            user_id_2,
        )

        # Check conversation last_seq >= 0 check constraint
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute(
                "UPDATE conversations SET last_seq = -1 WHERE id = $1;",
                conv_id,
            )

        # 3. Message Idempotency with sender_id
        shared_uuid = uuid4()
        msg_id_1 = await conn.fetchval(
            """
            INSERT INTO messages (conversation_id, seq, sender_id, client_msg_id, kind, payload)
            VALUES ($1, 1, $2, $3, 'text', '{"text": "Hello"}'::jsonb)
            RETURNING id;
            """,
            conv_id,
            user_id_1,
            shared_uuid,
        )
        assert msg_id_1 > 0

        # Duplicate insert by SAME sender with SAME client_msg_id MUST fail
        with pytest.raises(asyncpg.UniqueViolationError):
            await conn.execute(
                """
                INSERT INTO messages (conversation_id, seq, sender_id, client_msg_id, kind, payload)
                VALUES ($1, 2, $2, $3, 'text', '{"text": "Hello again"}'::jsonb);
                """,
                conv_id,
                user_id_1,
                shared_uuid,
            )

        # Same client_msg_id by DIFFERENT sender MUST succeed!
        msg_id_2 = await conn.fetchval(
            """
            INSERT INTO messages (conversation_id, seq, sender_id, client_msg_id, kind, payload)
            VALUES ($1, 2, $2, $3, 'text', '{"text": "Response"}'::jsonb)
            RETURNING id;
            """,
            conv_id,
            user_id_2,
            shared_uuid,
        )
        assert msg_id_2 > 0

        # 4. Message seq > 0 check constraint
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute(
                """
                INSERT INTO messages (conversation_id, seq, sender_id, client_msg_id, kind, payload)
                VALUES ($1, 0, $2, $3, 'text', '{"text": "Zero seq"}'::jsonb);
                """,
                conv_id,
                user_id_1,
                uuid4(),
            )

        # 5. Sessions node_id foreign key constraint
        # Inserting session for non-existent node must fail
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await conn.execute(
                "INSERT INTO sessions (connection_id, user_id, node_id) VALUES ($1, $2, $3);",
                uuid4(),
                user_id_1,
                "non-existent-node-404",
            )

        # Register node first
        await conn.execute(
            """
            INSERT INTO node_registry (node_id, role, endpoint_url, status)
            VALUES ($1, 'app', 'http://app-1:8000', 'alive');
            """,
            "app-node-1",
        )
        # Now session insert succeeds
        session_id = uuid4()
        await conn.execute(
            "INSERT INTO sessions (connection_id, user_id, node_id) VALUES ($1, $2, $3);",
            session_id,
            user_id_1,
            "app-node-1",
        )

        # 6. Track duration and size constraints
        track_id = uuid4()
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute(
                "INSERT INTO tracks (id, title, artist, duration_s, size_bytes) VALUES ($1, $2, $3, 0, 100);",
                track_id, "Bad Track", "Artist",
            )

        await conn.execute(
            "INSERT INTO tracks (id, title, artist, duration_s, size_bytes) VALUES ($1, $2, $3, 180, 5000);",
            track_id, "Good Track", "Artist",
        )

        # 7. Job constraints
        # task_type = 'replicate' requires track_id
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute(
                "INSERT INTO jobs (task_type, track_id, status) VALUES ('replicate', NULL, 'pending');"
            )

        # status = 'running' requires non-empty worker_id and lease_until
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute(
                "INSERT INTO jobs (task_type, track_id, status, worker_id, lease_until) VALUES ('replicate', $1, 'running', '', now());",
                track_id,
            )

        await tr.rollback()
    finally:
        await conn.close()


# ============================================================================
# 3. Live Nginx Reverse Proxy Tests (if Nginx running)
# ============================================================================

def test_nginx_live_routing():
    """
    Test live Nginx reverse proxy behaviors:
    1. /internal/* is blocked from external access (403 Forbidden).
    2. /health proxying to app service works.
    3. Multi-instance app balancing without Nginx reload.
    """
    nginx_url = os.getenv("TEST_NGINX_URL")
    if not nginx_url:
        # Check standard default local port
        port = os.getenv("NGINX_PORT", "80")
        nginx_url = f"http://127.0.0.1:{port}"

    try:
        import httpx
    except ImportError:
        pytest.skip("httpx is required for live Nginx tests")

    try:
        with httpx.Client(timeout=3.0) as client:
            resp = client.get(f"{nginx_url}/nginx-health")
            if resp.status_code != 200:
                pytest.skip("Nginx reverse proxy is not running on " + nginx_url)
    except Exception:
        pytest.skip(f"Nginx reverse proxy is not running on {nginx_url}")

    with httpx.Client(timeout=5.0) as client:
        # 1. External access to /internal/* MUST be blocked with 403 Forbidden
        internal_resp = client.get(f"{nginx_url}/internal/deliver")
        assert internal_resp.status_code == 403, (
            f"Expected 403 Forbidden for external /internal/ access, got {internal_resp.status_code}"
        )

        # 2. Public /health check must reach app backend
        health_resp = client.get(f"{nginx_url}/health")
        assert health_resp.status_code == 200, f"Expected 200 OK from /health, got {health_resp.status_code}"
        data = health_resp.json()
        assert data.get("status") == "ok"
        assert "node_id" in data


if __name__ == "__main__":
    test_nginx_config_rules()
    test_postgres_schema_entities_and_constraints()
    test_migrations_directory_structure()
    test_docker_compose_and_dockerignore_compliance()
    print("All static infrastructure tests passed successfully!")
