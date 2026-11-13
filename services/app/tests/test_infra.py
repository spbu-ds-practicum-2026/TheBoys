"""
Infrastructure & Configuration Compliance Tests (DevOps / QA).

Verifies that the Docker Compose configuration, Nginx rules,
and PostgreSQL schemas strictly adhere to the Technical Requirements (TR).
"""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


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


def test_postgres_schema_entities():
    """Verify all entities from TR architecture and data models are defined in init.sql."""
    init_sql = REPO_ROOT / "infra" / "postgres" / "init.sql"
    assert init_sql.exists(), "infra/postgres/init.sql must exist"

    content = init_sql.read_text(encoding="utf-8")

    required_tables = [
        "CREATE TABLE IF NOT EXISTS users",
        "CREATE TABLE IF NOT EXISTS node_registry",
        "CREATE TABLE IF NOT EXISTS conversations",
        "CREATE TABLE IF NOT EXISTS messages",
        "CREATE TABLE IF NOT EXISTS conversation_reads",
        "CREATE TABLE IF NOT EXISTS sessions",
        "CREATE TABLE IF NOT EXISTS tracks",
        "CREATE TABLE IF NOT EXISTS replicas",
        "CREATE TABLE IF NOT EXISTS jobs",
    ]

    for table in required_tables:
        assert table in content, f"Table definition missing: {table}"

    # Verify key architectural constraints
    assert "unique_conversation_pair" in content, "Must prevent duplicate conversations between same users"
    assert "unique_conversation_seq" in content, "Messages must have strictly unique seq per conversation"
    assert "unique_conversation_client_msg" in content, "Client message idempotency constraint required"
    assert "unique_active_job_per_track" in content, "Track replication job deduplication required"


def test_docker_compose_structure():
    """Verify Docker Compose file contains required services and network topology."""
    compose_file = REPO_ROOT / "docker-compose.yml"
    assert compose_file.exists(), "docker-compose.yml must exist in repository root"

    content = compose_file.read_text(encoding="utf-8")

    assert "postgres:" in content
    assert "app:" in content
    assert "nginx:" in content
    assert "theboys_net:" in content
    assert "INTERNAL_SECRET:" in content
    assert "SESSION_SECRET:" in content
    assert "01-init.sql" in content


if __name__ == "__main__":
    test_nginx_config_rules()
    test_postgres_schema_entities()
    test_docker_compose_structure()
    print("All infra tests passed successfully!")

