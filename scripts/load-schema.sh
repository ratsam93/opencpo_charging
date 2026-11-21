#!/usr/bin/env bash
# Load opencpo-core/db/schema.sql into the running postgres container.
#
# opencpo-core's own migrations do not work (db/migrations is missing and
# alembic fails), so a fresh install needs this once. setup.sh does the same
# thing during a first install; use this script when you started the stack with
# plain `docker compose up`.
#
# Usage: scripts/load-schema.sh [--force] [--no-restart]
#   --force       load even if the ocpp schema already has tables (will fail on
#                 duplicates; only useful after dropping the schema)
#   --no-restart  do not restart ocpp-core afterwards
set -euo pipefail

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCHEMA="$INSTALL_DIR/opencpo-core/db/schema.sql"
FORCE=0; RESTART=1
for a in "$@"; do
  case "$a" in
    --force) FORCE=1 ;;
    --no-restart) RESTART=0 ;;
    -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
    *) echo "unknown option: $a" >&2; exit 2 ;;
  esac
done

[ -f "$SCHEMA" ] || { echo "schema not found: $SCHEMA (clone opencpo-core first)" >&2; exit 1; }
cd "$INSTALL_DIR"

psql_in() {  # reads SQL from stdin
  docker compose exec -T postgres sh -c 'psql -v ON_ERROR_STOP=1 -q -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
}
count_tables() {
  docker compose exec -T postgres sh -c \
    'psql -tA -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "select count(*) from information_schema.tables where table_schema='"'"'ocpp'"'"'"' | tr -d '[:space:]'
}

before="$(count_tables)"
if [ "${before:-0}" -gt 0 ] && [ "$FORCE" = 0 ]; then
  echo "schema already loaded ($before tables in schema ocpp); nothing to do."
  exit 0
fi

echo "loading $SCHEMA ..."
psql_in < "$SCHEMA"
after="$(count_tables)"
echo "done: $after tables in schema ocpp"
[ "${after:-0}" -gt 0 ] || { echo "no tables created, check the output above" >&2; exit 1; }

if [ "$RESTART" = 1 ]; then
  docker compose restart ocpp-core >/dev/null
  echo "restarted ocpp-core"
fi
