#!/usr/bin/env bash
set -euo pipefail

# Deploy this Django project to a remote Linux machine over SSH (e.g., via Tailscale).
# - Syncs files with rsync (excludes venv/.git/tmp)
# - Creates a Python venv and installs requirements
# - Applies Django migrations
# - Starts the dev server in background (nohup) on the chosen port
#
# Usage:
#   scripts/remote_deploy.sh user@host [--dest /path/on/remote] [--port 8000] [--copy-env]
#
# Examples:
#   scripts/remote_deploy.sh andre@myhost --dest ~/apps/Django --port 8000 --copy-env
#   scripts/remote_deploy.sh root@100.93.108.124 --dest /opt/erp --port 8000

REMOTE=${1:-}
shift || true

DEST=""
PORT="8000"
COPY_ENV=0
SYSTEMD=0
SERVICE_NAME=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dest)
      DEST=${2:-}
      shift 2 ;;
    --port)
      PORT=${2:-}
      shift 2 ;;
    --copy-env)
      COPY_ENV=1
      shift ;;
    --systemd)
      SYSTEMD=1
      shift ;;
    --service)
      SERVICE_NAME=${2:-}
      shift 2 ;;
    -h|--help)
      echo "Usage: $0 user@host [--dest PATH] [--port N] [--copy-env]" ; exit 0 ;;
    *) echo "Unknown arg: $1" >&2 ; exit 1 ;;
  esac
done

if [[ -z "$REMOTE" ]]; then
  echo "REMOTE host required. Usage: $0 user@host [--dest PATH] [--port N] [--copy-env]" >&2
  exit 2
fi

# Resolve default destination to '~/Django' (project folder name) on remote
if [[ -z "$DEST" ]]; then
  PROJECT_NAME=$(basename "$(pwd)")
  DEST="~/${PROJECT_NAME}"
fi

echo "==> Syncing project to $REMOTE:$DEST"
EXCLUDES=(
  "--exclude=.git/" "--exclude=.venv/" "--exclude=venv/" "--exclude=venv312/"
  "--exclude=__pycache__/" "--exclude=*.pyc" "--exclude=backups/"
  "--exclude=runserver.log" "--exclude=runserver.pid" "--exclude=current_port.txt"
)
SSH_BIN=${SSH_BIN:-ssh}
# Support multi-word SSH_BIN like "tailscale ssh"
read -r -a SSH_ARR <<< "$SSH_BIN"
"${SSH_ARR[@]}" "$REMOTE" "mkdir -p $DEST"
rsync -az -e "$SSH_BIN" --delete "${EXCLUDES[@]}" ./ "$REMOTE":"$DEST"/

if [[ $COPY_ENV -eq 1 && -f .env ]]; then
  echo "==> Copying .env to remote"
  rsync -az .env "$REMOTE":"$DEST"/.env
fi

echo "==> Bootstrapping virtualenv and installing requirements on remote"
"${SSH_ARR[@]}" "$REMOTE" bash -lc "set -eo pipefail
  cd $DEST
  PY=\"\$(command -v python3 || true)\"
  if [[ -z \"$PY\" ]]; then
    PY=\"\$(command -v python || true)\"
  fi
  if [[ -z \"$PY\" ]]; then
    echo 'Python não encontrado no sistema remoto (python3 ou python).'
    exit 3
  fi
  if [[ ! -x .venv/bin/python ]]; then
    \"$PY\" -m venv .venv
  fi
  .venv/bin/python -m pip install --upgrade pip wheel
  if [[ -f requirements.txt ]]; then
    .venv/bin/pip install -r requirements.txt
  fi
  echo '==> Applying migrations'
  .venv/bin/python manage.py migrate --noinput
  echo '==> Starting dev server on 0.0.0.0:$PORT'
  # stop previous if any
  if [[ -f runserver.pid ]]; then
    PID=\"\$(cat runserver.pid || true)\"
    if [[ -n \"$PID\" ]] && kill -0 \"$PID\" 2>/dev/null; then
      kill \"$PID\" || true
      sleep 0.3
    fi
    rm -f runserver.pid
  fi
  nohup env PYTHONUNBUFFERED=1 .venv/bin/python manage.py runserver 0.0.0.0:$PORT > runserver.log 2>&1 &
  echo $! > runserver.pid
  echo $PORT > current_port.txt
  echo 'Server started. Logs: runserver.log'
  tail -n 5 runserver.log || true
"

echo "==> Done. Test on: http://<remote-ip>:$PORT/"
echo "Note: ensure your remote .env has ALLOWED_HOSTS including the remote hostname/IP."

if [[ $SYSTEMD -eq 1 ]]; then
  echo "==> Installing/starting systemd service on remote"
  scripts/remote_systemd_install.sh "$REMOTE" --dest "$DEST" --port "$PORT" ${SERVICE_NAME:+--service "$SERVICE_NAME"}
fi
