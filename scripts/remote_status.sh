#!/usr/bin/env bash
set -euo pipefail
# Show status of remote dev server
# Usage: scripts/remote_status.sh user@host [--dest PATH]

REMOTE=${1:-}
shift || true
DEST=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dest) DEST=${2:-}; shift 2 ;;
    -h|--help) echo "Usage: $0 user@host [--dest PATH]"; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done
[[ -z "$REMOTE" ]] && { echo "REMOTE required" >&2; exit 2; }
[[ -z "$DEST" ]] && DEST="~/$(basename "$(pwd)")"

SSH_BIN=${SSH_BIN:-ssh}
read -r -a SSH_ARR <<< "$SSH_BIN"
"${SSH_ARR[@]}" "$REMOTE" bash -lc "set -euo pipefail
  cd $DEST
  echo -n 'PID: '; cat runserver.pid 2>/dev/null || echo '-'
  echo -n 'PORT: '; cat current_port.txt 2>/dev/null || echo '-'
  if [[ -f runserver.pid ]]; then
    ps -p \"\$(cat runserver.pid)\" -o pid,cmd --no-headers || true
  fi
  echo '--- tail runserver.log ---'
  tail -n 40 runserver.log 2>/dev/null || echo 'no log'
"
