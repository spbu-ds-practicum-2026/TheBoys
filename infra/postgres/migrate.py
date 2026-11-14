"""
Database Migration Manager for TheBoys Distributed System.

Provides versioned schema migration tracking, execution of pending migrations,
and schema inspection for PostgreSQL.
"""

import argparse
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse


MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def get_db_params():
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        # Strip async driver prefix if present (e.g. postgresql+asyncpg://)
        clean_url = re.sub(r"^postgresql\+[a-zA-Z0-9_]+://", "postgresql://", database_url)
        parsed = urlparse(clean_url)
        return {
            "user": parsed.username or os.getenv("POSTGRES_USER", "theboys_user"),
            "password": parsed.password or os.getenv("POSTGRES_PASSWORD", "theboys_secret_pass"),
            "host": parsed.hostname or os.getenv("POSTGRES_HOST", "127.0.0.1"),
            "port": parsed.port or int(os.getenv("POSTGRES_PORT", "5432")),
            "database": (parsed.path.lstrip("/") if parsed.path else "") or os.getenv("POSTGRES_DB", "theboys"),
        }
    return {
        "user": os.getenv("POSTGRES_USER", "theboys_user"),
        "password": os.getenv("POSTGRES_PASSWORD", "theboys_secret_pass"),
        "host": os.getenv("POSTGRES_HOST", "127.0.0.1"),
        "port": int(os.getenv("POSTGRES_PORT", "5432")),
        "database": os.getenv("POSTGRES_DB", "theboys"),
    }


def list_migration_files():
    if not MIGRATIONS_DIR.exists():
        return []
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    parsed = []
    for f in files:
        match = re.match(r"^(\d+)_(.*)\.sql$", f.name)
        if match:
            version = int(match.group(1))
            name = f.stem
            parsed.append((version, name, f))
    return sorted(parsed, key=lambda x: x[0])


def connect_postgres():
    """Connect using available PostgreSQL driver: psycopg, asyncpg, or fallback."""
    params = get_db_params()

    # Try psycopg (v3)
    try:
        import psycopg
        conn = psycopg.connect(
            dbname=params["database"],
            user=params["user"],
            password=params["password"],
            host=params["host"],
            port=params["port"],
            autocommit=False,
        )
        return "psycopg", conn
    except ImportError:
        pass

    # Try psycopg2
    try:
        import psycopg2
        conn = psycopg2.connect(
            dbname=params["database"],
            user=params["user"],
            password=params["password"],
            host=params["host"],
            port=params["port"],
        )
        conn.autocommit = False
        return "psycopg2", conn
    except ImportError:
        pass

    # Try asyncpg via asyncio loop runner
    try:
        import asyncio
        import asyncpg

        class AsyncpgSyncAdapter:
            def __init__(self, loop, conn):
                self.loop = loop
                self.conn = conn

            def execute(self, query):
                return self.loop.run_until_complete(self.conn.execute(query))

            def fetch(self, query):
                return self.loop.run_until_complete(self.conn.fetch(query))

            def close(self):
                self.loop.run_until_complete(self.conn.close())
                self.loop.close()

        loop = asyncio.new_event_loop()
        conn = loop.run_until_complete(
            asyncpg.connect(
                user=params["user"],
                password=params["password"],
                host=params["host"],
                port=params["port"],
                database=params["database"],
            )
        )
        return "asyncpg", AsyncpgSyncAdapter(loop, conn)
    except ImportError:
        pass

    return None, None


def ensure_migrations_table(driver, conn):
    query = """
    CREATE TABLE IF NOT EXISTS schema_migrations (
        version INT PRIMARY KEY,
        name VARCHAR(255) NOT NULL,
        applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """
    if driver in ("psycopg", "psycopg2"):
        with conn.cursor() as cur:
            cur.execute(query)
        conn.commit()
    elif driver == "asyncpg":
        conn.execute(query)


def get_applied_versions(driver, conn) -> set[int]:
    query = "SELECT version FROM schema_migrations ORDER BY version;"
    if driver in ("psycopg", "psycopg2"):
        with conn.cursor() as cur:
            cur.execute(query)
            rows = cur.fetchall()
            return {r[0] for r in rows}
    elif driver == "asyncpg":
        rows = conn.fetch(query)
        return {r["version"] for r in rows}
    return set()


def apply_migrations():
    migration_files = list_migration_files()
    if not migration_files:
        print("No migration files found in", MIGRATIONS_DIR)
        return 0

    driver, conn = connect_postgres()
    if not conn:
        print("Error: No PostgreSQL driver found (install psycopg, psycopg2, or asyncpg).")
        print("Alternatively, execute migrations inside Docker container via migrate.sh:")
        print("  docker compose exec -T postgres sh /docker-entrypoint-initdb.d/migrate.sh")
        return 1

    try:
        ensure_migrations_table(driver, conn)
        applied = get_applied_versions(driver, conn)

        pending = [m for m in migration_files if m[0] not in applied]
        if not pending:
            print("Database is up to date. No pending migrations.")
            return 0

        print(f"Found {len(pending)} pending migration(s):")
        for version, name, path in pending:
            print(f"Applying migration {name} (v{version})...")
            sql_content = path.read_text(encoding="utf-8")
            if driver in ("psycopg", "psycopg2"):
                with conn.cursor() as cur:
                    cur.execute(sql_content)
                conn.commit()
            elif driver == "asyncpg":
                conn.execute(sql_content)
            print(f"Successfully applied {name}.")

        print("All migrations applied successfully!")
        return 0
    except Exception as e:
        if driver in ("psycopg", "psycopg2") and conn:
            conn.rollback()
        print(f"Migration failed: {e}", file=sys.stderr)
        return 1
    finally:
        if conn:
            conn.close()


def show_status():
    migration_files = list_migration_files()
    driver, conn = connect_postgres()
    if not conn:
        print("Warning: Cannot connect to database (no driver or DB unreachable). Listing files on disk:")
        for version, name, _ in migration_files:
            print(f"  [?] {version:04d}_{name}")
        return 1

    try:
        ensure_migrations_table(driver, conn)
        applied = get_applied_versions(driver, conn)

        print("Migration status:")
        for version, name, _ in migration_files:
            status = "[APPLIED]" if version in applied else "[PENDING]"
            print(f"  {status} {version:04d}_{name}")
        return 0
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="TheBoys PostgreSQL Migration Runner")
    parser.add_argument("command", choices=["apply", "status"], default="apply", nargs="?",
                        help="Action to perform: apply migrations or view status")
    args = parser.parse_args()

    if args.command == "status":
        sys.exit(show_status())
    else:
        sys.exit(apply_migrations())


if __name__ == "__main__":
    main()
