#!/bin/sh
set -e

# ============================================================================
# TheBoys Database Migration Runner (Shell / psql)
# Applies pending SQL migrations in transactional order
# ============================================================================

PG_USER="${POSTGRES_USER:-theboys_user}"
PG_DB="${POSTGRES_DB:-theboys}"
MIGRATIONS_DIR="$(dirname "$0")/migrations"

echo "=== Running PostgreSQL Migrations for ${PG_DB} as ${PG_USER} ==="

psql -v ON_ERROR_STOP=1 --username "$PG_USER" --dbname "$PG_DB" <<-EOSQL
    CREATE TABLE IF NOT EXISTS schema_migrations (
        version INT PRIMARY KEY,
        name VARCHAR(255) NOT NULL,
        applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
EOSQL

for file in $(ls -1 "$MIGRATIONS_DIR"/*.sql | sort); do
    filename=$(basename "$file")
    version=$(echo "$filename" | cut -d'_' -f1 | sed 's/^0*//')
    name=$(echo "$filename" | sed 's/\.sql$//')

    applied=$(psql -v ON_ERROR_STOP=1 --username "$PG_USER" --dbname "$PG_DB" -t -A -c \
        "SELECT count(*) FROM schema_migrations WHERE version = ${version};")

    if [ "$applied" -eq 0 ]; then
        echo "Applying migration ${filename} (version ${version})..."
        psql -v ON_ERROR_STOP=1 --username "$PG_USER" --dbname "$PG_DB" -f "$file"
        echo "Migration ${filename} successfully applied."
    else
        echo "Migration ${filename} (version ${version}) is already applied. Skipping."
    fi
done

echo "=== All migrations are up to date! ==="
