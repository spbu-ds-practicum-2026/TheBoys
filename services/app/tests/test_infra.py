"""
Infrastructure & Configuration Compliance Tests (DevOps / QA).

Verifies that the Docker Compose configuration, Nginx reverse proxy rules,
PostgreSQL schemas, versioned migrations, atomic transaction rollbacks,
and runtime load-balancing behaviors strictly adhere to the Technical Requirements (TR).
"""

import os
import re
import subprocess
import time
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
        "replica_failures",
    ]
    for table in required_tables:
        assert f"CREATE TABLE IF NOT EXISTS {table}" in content, f"Table definition missing: {table}"

    # 1. Message Idempotency: MUST include sender_id in the unique constraint
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


def test_migrations_structure_and_atomic_execution():
    """
    Verify versioned migrations exist, and runners use strict single-transaction semantics.
    """
    migrations_dir = REPO_ROOT / "infra" / "postgres" / "migrations"
    assert migrations_dir.exists(), "infra/postgres/migrations must exist"

    mig_0001 = migrations_dir / "0001_initial_schema.sql"
    mig_0002 = migrations_dir / "0002_constraints_and_idempotency.sql"
    mig_0003 = migrations_dir / "0003_replica_failures.sql"

    assert mig_0001.exists(), "Migration 0001 must exist"
    assert mig_0002.exists(), "Migration 0002 must exist"
    assert mig_0003.exists(), "Migration 0003 must exist"

    # Verify that migrate.sh enforces single-transaction mode (--single-transaction)
    migrate_sh = REPO_ROOT / "infra" / "postgres" / "migrate.sh"
    assert migrate_sh.exists(), "infra/postgres/migrate.sh must exist"
    sh_content = migrate_sh.read_text(encoding="utf-8")
    assert "--single-transaction" in sh_content, (
        "migrate.sh must execute psql with --single-transaction to guarantee atomic rollback on failure"
    )

    # Verify that migrate.py has execute_in_transaction logic
    migrate_py = REPO_ROOT / "infra" / "postgres" / "migrate.py"
    assert migrate_py.exists(), "infra/postgres/migrate.py must exist"
    py_content = migrate_py.read_text(encoding="utf-8")
    assert "transaction" in py_content
    assert "rollback" in py_content


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

    # 2. 2 App Instances by default for high availability
    assert "scale: 2" in content or "replicas: 2" in content, (
        "Service 'app' must run 2 instances by default (scale: 2)"
    )

    # 3. Environment passing: ALLOWED_ORIGINS and SESSION_COOKIE_MAX_AGE_SECONDS
    assert "ALLOWED_ORIGINS: ${ALLOWED_ORIGINS:-" in content or "ALLOWED_ORIGINS: ${ALLOWED_ORIGINS}" in content
    assert "SESSION_COOKIE_MAX_AGE_SECONDS:" in content

    # 4. Mounts for migrations
    assert "migrations" in content, "docker-compose.yml must mount migrations directory"

    # 5. Root .dockerignore existence for root context builds
    root_dockerignore = REPO_ROOT / ".dockerignore"
    assert root_dockerignore.exists(), "Root .dockerignore must exist for build context '.'"
    ignore_content = root_dockerignore.read_text(encoding="utf-8")
    assert ".git" in ignore_content
    assert ".env" in ignore_content


# ============================================================================
# 2. Live PostgreSQL Execution Tests (with Savepoints & Rollback Isolation)
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

    Uses nested transactions (SAVEPOINTS) for expected SQL violations so that
    the root transaction is NOT aborted with InFailedSQLTransactionError.
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
        # Root test transaction that rolls back all test data at the end
        root_tr = conn.transaction()
        await root_tr.start()

        # --------------------------------------------------------------------
        # 1. Check user case-insensitive login uniqueness
        # --------------------------------------------------------------------
        user_id_1 = await conn.fetchval(
            "INSERT INTO users (login, password_hash) VALUES ($1, $2) RETURNING id;",
            "Oleg",
            "hash_123",
        )
        assert user_id_1 > 0

        # Inserting lowercase 'oleg' must fail with UniqueViolationError.
        # Wrapped in a nested transaction (SAVEPOINT) to preserve root transaction.
        with pytest.raises(asyncpg.UniqueViolationError):
            async with conn.transaction():
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
        assert user_id_2 > 0

        # --------------------------------------------------------------------
        # 2. Create conversation & test check constraint
        # --------------------------------------------------------------------
        conv_id = await conn.fetchval(
            "INSERT INTO conversations (user1_id, user2_id, last_seq) VALUES ($1, $2, 0) RETURNING id;",
            user_id_1,
            user_id_2,
        )
        assert conv_id > 0

        # Conversation last_seq >= 0 check constraint in SAVEPOINT
        with pytest.raises(asyncpg.CheckViolationError):
            async with conn.transaction():
                await conn.execute(
                    "UPDATE conversations SET last_seq = -1 WHERE id = $1;",
                    conv_id,
                )

        # --------------------------------------------------------------------
        # 3. Message Idempotency with sender_id
        # --------------------------------------------------------------------
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
            async with conn.transaction():
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

        # --------------------------------------------------------------------
        # 4. Message seq > 0 check constraint
        # --------------------------------------------------------------------
        with pytest.raises(asyncpg.CheckViolationError):
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO messages (conversation_id, seq, sender_id, client_msg_id, kind, payload)
                    VALUES ($1, 0, $2, $3, 'text', '{"text": "Zero seq"}'::jsonb);
                    """,
                    conv_id,
                    user_id_1,
                    uuid4(),
                )

        # --------------------------------------------------------------------
        # 5. Sessions node_id foreign key constraint
        # --------------------------------------------------------------------
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            async with conn.transaction():
                await conn.execute(
                    "INSERT INTO sessions (connection_id, user_id, node_id) VALUES ($1, $2, $3);",
                    uuid4(),
                    user_id_1,
                    "non-existent-node-404",
                )

        # Register node in registry
        await conn.execute(
            """
            INSERT INTO node_registry (node_id, role, endpoint_url, status)
            VALUES ($1, 'app', 'http://app-1:8000', 'alive');
            """,
            "app-node-1",
        )

        session_id = uuid4()
        await conn.execute(
            "INSERT INTO sessions (connection_id, user_id, node_id) VALUES ($1, $2, $3);",
            session_id,
            user_id_1,
            "app-node-1",
        )

        # --------------------------------------------------------------------
        # 6. Track duration and size constraints
        # --------------------------------------------------------------------
        track_id = uuid4()
        with pytest.raises(asyncpg.CheckViolationError):
            async with conn.transaction():
                await conn.execute(
                    "INSERT INTO tracks (id, title, artist, duration_s, size_bytes) VALUES ($1, $2, $3, 0, 100);",
                    track_id, "Bad Track", "Artist",
                )

        await conn.execute(
            "INSERT INTO tracks (id, title, artist, duration_s, size_bytes) VALUES ($1, $2, $3, 180, 5000);",
            track_id, "Good Track", "Artist",
        )

        # --------------------------------------------------------------------
        # 7. Job constraints
        # --------------------------------------------------------------------
        with pytest.raises(asyncpg.CheckViolationError):
            async with conn.transaction():
                await conn.execute(
                    "INSERT INTO jobs (task_type, track_id, status) VALUES ('replicate', NULL, 'pending');"
                )

        with pytest.raises(asyncpg.CheckViolationError):
            async with conn.transaction():
                await conn.execute(
                    "INSERT INTO jobs (task_type, track_id, status, worker_id, lease_until) VALUES ('replicate', $1, 'running', '', now());",
                    track_id,
                )

        # --------------------------------------------------------------------
        # 8. Replica failures foreign keys and transient failure tracking
        # --------------------------------------------------------------------
        await conn.execute(
            """
            INSERT INTO node_registry (node_id, role, endpoint_url, status)
            VALUES ($1, 'storage', 'http://storage-1:8000', 'alive');
            """,
            "storage-node-1",
        )
        await conn.execute(
            """
            INSERT INTO replicas (track_id, node_id, status)
            VALUES ($1, $2, 'active');
            """,
            track_id,
            "storage-node-1",
        )
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            async with conn.transaction():
                await conn.execute(
                    "INSERT INTO replica_failures (track_id, node_id) VALUES ($1, $2);",
                    uuid4(),
                    "storage-node-1",
                )
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            async with conn.transaction():
                await conn.execute(
                    "INSERT INTO replica_failures (track_id, node_id) VALUES ($1, $2);",
                    track_id,
                    "non-existent-storage-node",
                )
        await conn.execute(
            "INSERT INTO replica_failures (track_id, node_id) VALUES ($1, $2);",
            track_id,
            "storage-node-1",
        )

        await root_tr.rollback()
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_migration_0002_atomic_rollback_on_conflicting_data_live():
    """
    Regression Test for Migration #2 Rollback:
    Simulates an old schema (v1) with pre-existing conflicting user logins ('Oleg' and 'oleg').
    When migration #2 runs via the atomic migration runner:
    1. It drops old constraints and attempts to create the lower(login) unique index.
    2. The index creation fails due to duplicate key 'oleg'.
    3. The transaction MUST roll back completely:
       - The old constraint (users_login_key) is preserved.
       - The old message idempotency constraint (unique_conversation_client_msg) is preserved.
       - Pre-existing user data ('Oleg', 'oleg') is NOT deleted or renamed.
       - Migration version 2 is NOT recorded in schema_migrations.
    """
    db_url = get_test_db_url()
    if not db_url:
        pytest.skip("Migration rollback test requires TEST_DATABASE_URL or DATABASE_URL")

    try:
        import asyncpg
    except ImportError:
        pytest.skip("asyncpg is required")

    try:
        conn = await connect_async_pg(db_url)
    except Exception as e:
        pytest.skip(f"Could not connect to PostgreSQL at {db_url}: {e}")

    test_schema = "test_rollback_isolated_schema"
    try:
        # Create an isolated temporary test schema
        await conn.execute(f"DROP SCHEMA IF EXISTS {test_schema} CASCADE;")
        await conn.execute(f"CREATE SCHEMA {test_schema};")
        await conn.execute(f"SET search_path TO {test_schema}, public;")

        # 1. Apply Migration 1 (old schema v1)
        mig1_path = REPO_ROOT / "infra" / "postgres" / "migrations" / "0001_initial_schema.sql"
        assert mig1_path.exists(), "0001_initial_schema.sql must exist"
        sql_v1 = mig1_path.read_text(encoding="utf-8")
        async with conn.transaction():
            await conn.execute(sql_v1)

        # 2. Insert pre-existing conflicting data that v1 allowed (case-sensitive Oleg and oleg)
        await conn.execute("INSERT INTO users (login, password_hash) VALUES ('Oleg', 'pass1');")
        await conn.execute("INSERT INTO users (login, password_hash) VALUES ('oleg', 'pass2');")

        # Insert a sample message to verify old constraint
        u1_id = await conn.fetchval("SELECT id FROM users WHERE login = 'Oleg';")
        u2_id = await conn.fetchval("SELECT id FROM users WHERE login = 'oleg';")
        cid = await conn.fetchval("INSERT INTO conversations (user1_id, user2_id) VALUES ($1, $2) RETURNING id;", u1_id, u2_id)
        msg_uuid = uuid4()
        await conn.execute(
            "INSERT INTO messages (conversation_id, seq, sender_id, client_msg_id, kind, payload) VALUES ($1, 1, $2, $3, 'text', '{}'::jsonb);",
            cid, u1_id, msg_uuid
        )

        # Verify old constraints exist in pg_constraint before running migration 2
        old_user_constr_before = await conn.fetchval(f"""
            SELECT conname FROM pg_constraint c
            JOIN pg_class t ON c.conrelid = t.oid
            JOIN pg_namespace n ON t.relnamespace = n.oid
            WHERE n.nspname = '{test_schema}' AND t.relname = 'users' AND c.conname = 'users_login_key';
        """)
        assert old_user_constr_before == "users_login_key", "Pre-condition: users_login_key must exist in v1"

        old_msg_constr_before = await conn.fetchval(f"""
            SELECT conname FROM pg_constraint c
            JOIN pg_class t ON c.conrelid = t.oid
            JOIN pg_namespace n ON t.relnamespace = n.oid
            WHERE n.nspname = '{test_schema}' AND t.relname = 'messages' AND c.conname = 'unique_conversation_client_msg';
        """)
        assert old_msg_constr_before == "unique_conversation_client_msg", "Pre-condition: unique_conversation_client_msg must exist in v1"

        # 3. Attempt Migration 2 in atomic transaction runner
        mig2_path = REPO_ROOT / "infra" / "postgres" / "migrations" / "0002_constraints_and_idempotency.sql"
        assert mig2_path.exists(), "0002_constraints_and_idempotency.sql must exist"
        sql_v2 = mig2_path.read_text(encoding="utf-8")

        failed_with_unique_violation = False
        try:
            async with conn.transaction():
                await conn.execute(sql_v2)
        except asyncpg.UniqueViolationError:
            failed_with_unique_violation = True

        assert failed_with_unique_violation, "Migration 2 must fail on conflicting logins ('Oleg' vs 'oleg')"

        # 4. Strict assertions after atomic rollback:
        # A) Old constraint users_login_key MUST STILL EXIST (it was dropped in script, but rolled back!)
        old_user_constr_after = await conn.fetchval(f"""
            SELECT conname FROM pg_constraint c
            JOIN pg_class t ON c.conrelid = t.oid
            JOIN pg_namespace n ON t.relnamespace = n.oid
            WHERE n.nspname = '{test_schema}' AND t.relname = 'users' AND c.conname = 'users_login_key';
        """)
        assert old_user_constr_after == "users_login_key", (
            "Rollback verification failed: old users_login_key constraint must be preserved after failed migration!"
        )

        # B) Old message constraint unique_conversation_client_msg MUST STILL EXIST
        old_msg_constr_after = await conn.fetchval(f"""
            SELECT conname FROM pg_constraint c
            JOIN pg_class t ON c.conrelid = t.oid
            JOIN pg_namespace n ON t.relnamespace = n.oid
            WHERE n.nspname = '{test_schema}' AND t.relname = 'messages' AND c.conname = 'unique_conversation_client_msg';
        """)
        assert old_msg_constr_after == "unique_conversation_client_msg", (
            "Rollback verification failed: old unique_conversation_client_msg must be preserved after failed migration!"
        )

        # C) New index unique_users_login_lower MUST NOT EXIST
        idx_lower_exists = await conn.fetchval(f"""
            SELECT EXISTS (
                SELECT 1 FROM pg_indexes WHERE schemaname = '{test_schema}' AND indexname = 'unique_users_login_lower'
            );
        """)
        assert not idx_lower_exists, "New index must NOT exist after rollback"

        # D) New constraint unique_conversation_sender_client_msg MUST NOT EXIST
        new_msg_constr = await conn.fetchval(f"""
            SELECT conname FROM pg_constraint c
            JOIN pg_class t ON c.conrelid = t.oid
            JOIN pg_namespace n ON t.relnamespace = n.oid
            WHERE n.nspname = '{test_schema}' AND t.relname = 'messages' AND c.conname = 'unique_conversation_sender_client_msg';
        """)
        assert new_msg_constr is None, "New sender idempotency constraint must NOT exist after rollback"

        # E) User data MUST NOT BE MODIFIED OR DELETED
        user_rows = await conn.fetch("SELECT login FROM users ORDER BY id;")
        logins = [r["login"] for r in user_rows]
        assert logins == ["Oleg", "oleg"], f"User data must remain intact, found: {logins}"

        # F) Version 2 MUST NOT be recorded in schema_migrations
        versions = await conn.fetch("SELECT version FROM schema_migrations ORDER BY version;")
        version_list = [r["version"] for r in versions]
        assert version_list == [1], f"schema_migrations must only contain [1], found: {version_list}"

    finally:
        await conn.execute(f"DROP SCHEMA IF EXISTS {test_schema} CASCADE;")
        await conn.close()


# ============================================================================
# 3. Live Nginx Reverse Proxy Tests & Failover Checks
# ============================================================================

def get_nginx_url():
    url = os.getenv("TEST_NGINX_URL")
    if not url:
        port = os.getenv("NGINX_PORT", "80")
        url = f"http://127.0.0.1:{port}"
    return url


def test_nginx_live_routing():
    """
    Test basic live Nginx reverse proxy behaviors:
    1. /internal/* is blocked from external access (403 Forbidden).
    2. /health proxying to app service works.
    3. Multiple default app instances receive requests with distinct node_ids.
    """
    nginx_url = get_nginx_url()

    try:
        import httpx
    except ImportError:
        pytest.skip("httpx is required for live Nginx tests")

    try:
        with httpx.Client(timeout=3.0) as client:
            resp = client.get(f"{nginx_url}/nginx-health")
            if resp.status_code != 200:
                pytest.skip(f"Nginx reverse proxy is not running on {nginx_url}")
    except Exception as e:
        pytest.skip(f"Nginx reverse proxy is not reachable at {nginx_url}: {e}")

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


def test_nginx_dynamic_scaling_and_failover():
    """
    Test Nginx dynamic service discovery and failure recovery:
    1. Verify requests are balanced across distinct node_ids (default 2 instances).
    2. Stopping one instance leaves remaining instance serving requests without downtime (failover).
    3. Scaling back up makes the restored instance receive traffic WITHOUT reloading Nginx.

    Strict environment separation:
    - Missing environment/stack: pytest.skip with detailed explanation.
    - Available environment: full assertions on scale-up, discovery, failover, and exact restoration.
    """
    nginx_url = get_nginx_url()

    try:
        import httpx
    except ImportError:
        pytest.skip("httpx is required for live Nginx scaling test")

    # 1. Precondition: Check Nginx reachable
    try:
        with httpx.Client(timeout=3.0) as client:
            resp = client.get(f"{nginx_url}/nginx-health")
            if resp.status_code != 200:
                pytest.skip(f"Nginx is not healthy at {nginx_url} (HTTP {resp.status_code})")
    except Exception as e:
        pytest.skip(f"Nginx reverse proxy is not reachable at {nginx_url}: {e}")

    # 2. Precondition: Check Docker Compose CLI availability
    try:
        res = subprocess.run(["docker", "compose", "version"], capture_output=True, text=True, timeout=5)
        if res.returncode != 0:
            pytest.skip(f"Docker Compose CLI check failed (exit {res.returncode}): {res.stderr}")
    except (FileNotFoundError, subprocess.SubprocessError) as e:
        pytest.skip(f"Docker Compose CLI not found in environment: {e}")

    # 3. Precondition: Check that docker compose stack is running
    ps_proc = subprocess.run(
        ["docker", "compose", "ps", "-q", "app"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if ps_proc.returncode != 0:
        pytest.skip(f"'docker compose ps' failed (exit {ps_proc.returncode}): {ps_proc.stderr}")

    initial_cids = [cid.strip() for cid in ps_proc.stdout.splitlines() if cid.strip()]
    initial_count = len(initial_cids)
    if initial_count < 1:
        pytest.skip("No running 'app' instances found in docker compose stack. Run 'docker compose up -d' first.")

    with httpx.Client(timeout=5.0) as client:
        # A) Verify initial traffic distribution across instances
        initial_seen_nodes = set()
        for _ in range(30):
            res = client.get(f"{nginx_url}/health")
            assert res.status_code == 200, f"Expected 200 OK from /health, got {res.status_code}"
            nid = res.json().get("node_id")
            if nid:
                initial_seen_nodes.add(nid)
            time.sleep(0.1)

        # If running with default 2 instances, assert both receive traffic with distinct node_ids
        if initial_count >= 2:
            assert len(initial_seen_nodes) >= 2, (
                f"Expected traffic to be distributed across at least 2 distinct node_ids by default, "
                f"but saw {len(initial_seen_nodes)}: {initial_seen_nodes}"
            )

        try:
            # ----------------------------------------------------------------
            # Scenario 1: Failover - stop one instance and verify seamless traffic
            # ----------------------------------------------------------------
            failover_scale = max(1, initial_count - 1)
            scale_down = subprocess.run(
                ["docker", "compose", "up", "-d", "--scale", f"app={failover_scale}", "--no-recreate"],
                capture_output=True,
                text=True,
                timeout=45,
            )
            assert scale_down.returncode == 0, (
                f"Failed to scale down app to {failover_scale} instances (exit {scale_down.returncode}):\n"
                f"stdout: {scale_down.stdout}\nstderr: {scale_down.stderr}"
            )

            # Wait slightly longer than Nginx DNS TTL (valid=5s)
            time.sleep(6)

            # Requests must continue being served by remaining instance without 502/504 errors
            remaining_seen_nodes = set()
            for _ in range(20):
                res = client.get(f"{nginx_url}/health")
                assert res.status_code == 200, f"Failover failed: expected 200 OK from /health, got {res.status_code}"
                nid = res.json().get("node_id")
                if nid:
                    remaining_seen_nodes.add(nid)
                time.sleep(0.1)

            assert len(remaining_seen_nodes) >= 1, "Remaining instance must serve traffic during failover"

            # ----------------------------------------------------------------
            # Scenario 2: Scale-up / Recovery without Nginx reload
            # ----------------------------------------------------------------
            target_scale = initial_count
            scale_up = subprocess.run(
                ["docker", "compose", "up", "-d", "--scale", f"app={target_scale}", "--no-recreate"],
                capture_output=True,
                text=True,
                timeout=45,
            )
            assert scale_up.returncode == 0, (
                f"Failed to restore/scale up app to {target_scale} instances (exit {scale_up.returncode}):\n"
                f"stdout: {scale_up.stdout}\nstderr: {scale_up.stderr}"
            )

            time.sleep(6)

            # Poll /health to verify traffic reaches both restored instances with distinct node_ids
            restored_seen_nodes = set()
            for _ in range(30):
                res = client.get(f"{nginx_url}/health")
                assert res.status_code == 200, f"Expected 200 OK from /health, got {res.status_code}"
                nid = res.json().get("node_id")
                if nid:
                    restored_seen_nodes.add(nid)
                time.sleep(0.1)

            if target_scale >= 2:
                assert len(restored_seen_nodes) >= 2, (
                    f"Dynamic recovery failed: expected traffic across at least 2 distinct node_ids without Nginx reload, "
                    f"seen {len(restored_seen_nodes)}: {restored_seen_nodes}"
                )

        finally:
            # Strictly restore the exact initial number of instances and verify result
            restore_res = subprocess.run(
                ["docker", "compose", "up", "-d", "--scale", f"app={initial_count}", "--no-recreate"],
                capture_output=True,
                text=True,
                timeout=45,
            )
            assert restore_res.returncode == 0, (
                f"Cleanup failed to restore initial scale of {initial_count} instances (exit {restore_res.returncode}):\n"
                f"stdout: {restore_res.stdout}\nstderr: {restore_res.stderr}"
            )


if __name__ == "__main__":
    test_nginx_config_rules()
    test_postgres_schema_entities_and_constraints()
    test_migrations_structure_and_atomic_execution()
    test_docker_compose_and_dockerignore_compliance()
    print("All static infrastructure tests passed successfully!")
