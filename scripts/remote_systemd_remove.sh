#!/usr/bin/env bash
set -euo pipefail
# Remove a previously installed systemd service for this project on the remote host.
# Usage: scripts/remote_systemd_remove.sh user@host [--service NAME]

REMOTE=${1:-}
shift || true
SERVICE_NAME=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --service) SERVICE_NAME=${2:-}; shift 2 ;;
    -h|--help) echo "Usage: $0 user@host [--service NAME]"; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

[[ -z "$REMOTE" ]] && { echo "REMOTE required" >&2; exit 2; }

if [[ -z "$SERVICE_NAME" ]]; then
  BASE=$(basename "$(pwd)")
  SERVICE_NAME="django-${BASE}"
fi

SSH_BIN=${SSH_BIN:-ssh}
read -r -a SSH_ARR <<< "$SSH_BIN"
"${SSH_ARR[@]}" "$REMOTE" bash -lc "set -euo pipefail
  SVC=\"$SERVICE_NAME\"
  UNIT=/etc/systemd/system/$SVC.service
  if systemctl list-unit-files | grep -q ^$SVC\.service; then
    sudo systemctl disable --now $SVC.service || true
  fi
  if [[ -f \"$UNIT\" ]]; then
    sudo rm -f \"$UNIT\"
    sudo systemctl daemon-reload
    echo 'Removed unit file.'
  else
    echo 'Unit file not found.'
  fi
"
