#!/usr/bin/env bash
set -euo pipefail
# Stop remote dev server
# Usage: scripts/remote_stop.sh user@host [--dest PATH]

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
  if [[ -f runserver.pid ]]; then
    PID=\"\$(cat runserver.pid)\"
    if kill -0 \"$PID\" 2>/dev/null; then
      kill \"$PID\"
      echo 'Stopped PID' \"$PID\"
    fi
    rm -f runserver.pid
  else
    echo 'No PID file found.'
  fi
"
