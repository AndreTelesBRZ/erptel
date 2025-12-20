#!/usr/bin/env bash
set -euo pipefail

# Helper to migrate data from local SQLite (default) to PostgreSQL using
# Django dumpdata/loaddata. You can run this script from any directory.
# It will: dump from SQLite, run migrations on Postgres (based on .env),
# load the dump, then check pg_trgm.

# Resolve project root (folder that contains manage.py)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT_DIR"

# Pick python: prefer current virtualenv, then .venv in project, else python3
if [[ -n "${VIRTUAL_ENV:-}" && -x "$VIRTUAL_ENV/bin/python" ]]; then
  PY="$VIRTUAL_ENV/bin/python"
elif [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
  PY="$ROOT_DIR/.venv/bin/python"
else
  PY="$(command -v python3 || command -v python)"
fi

echo "Using Python: $PY"

TS="$(date +%Y%m%d_%H%M%S)"
BACKUP_DIR="${BACKUP_DIR:-$ROOT_DIR/backups}"
mkdir -p "$BACKUP_DIR"

echo "[1/3] Dumping data from SQLite -> $BACKUP_DIR/dump_$TS.json"
# Force SQLite regardless of .env by unsetting Postgres envs for this call
env -u POSTGRES_DB -u PGDATABASE -u POSTGRES_USER -u PGUSER -u POSTGRES_PASSWORD -u PGPASSWORD -u POSTGRES_HOST -u PGHOST -u POSTGRES_PORT -u PGPORT \
  DB_ENGINE=sqlite \
  "$PY" manage.py dumpdata \
  --natural-foreign --natural-primary \
  --exclude contenttypes --exclude auth.permission --exclude admin.logentry \
  --indent 2 > "$BACKUP_DIR/dump_$TS.json"

echo "[2/3] Applying migrations on PostgreSQL (using .env)"
"$PY" manage.py migrate --noinput

echo "[3/3] Loading data into PostgreSQL"
"$PY" manage.py loaddata "$BACKUP_DIR/dump_$TS.json"

echo "Checking pg_trgm extension and trigram indexes (optional)"
"$PY" manage.py check_search || true

echo "Done. You can now run the server with Postgres configured."
