#!/usr/bin/env bash
set -euo pipefail
# Install and enable a systemd service to run this Django project as a dev server.
# WARNING: Django's runserver is for development only. Use inside VPN or behind a reverse proxy.
#
# Usage:
#   scripts/remote_systemd_install.sh user@host [--dest PATH] [--port 8000] [--service NAME] [--user USER]

REMOTE=${1:-}
shift || true

DEST=""
PORT="8000"
SERVICE_NAME=""
RUN_AS_USER=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dest) DEST=${2:-}; shift 2 ;;
    --port) PORT=${2:-}; shift 2 ;;
    --service) SERVICE_NAME=${2:-}; shift 2 ;;
    --user) RUN_AS_USER=${2:-}; shift 2 ;;
    -h|--help) echo "Usage: $0 user@host [--dest PATH] [--port N] [--service NAME] [--user USER]"; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

[[ -z "$REMOTE" ]] && { echo "REMOTE required" >&2; exit 2; }
[[ -z "$DEST" ]] && DEST="~/$(basename "$(pwd)")"

# Default service name based on folder
if [[ -z "$SERVICE_NAME" ]]; then
  BASE=$(basename "$DEST")
  SERVICE_NAME="django-${BASE}"
fi

echo "==> Creating systemd unit on $REMOTE as $SERVICE_NAME.service"
SSH_BIN=${SSH_BIN:-ssh}
read -r -a SSH_ARR <<< "$SSH_BIN"
"${SSH_ARR[@]}" "$REMOTE" bash -lc "set -euo pipefail
  DEST_RESOLVED=\"$DEST\"
  cd \"$DEST_RESOLVED\"
  PORT=\"$PORT\"
  SVC=\"$SERVICE_NAME\"
  VENV=\"$DEST_RESOLVED/.venv/bin/python\"
  if [[ ! -x \"$VENV\" ]]; then
    echo 'Python venv not found at .venv; run remote_deploy first.' >&2
    exit 3
  fi
  # Pick user: explicit, then SUDO_USER, then USER
  RUN_AS=\"$RUN_AS_USER\"
  if [[ -z \"$RUN_AS\" ]]; then
    RUN_AS=\"${SUDO_USER:-${USER}}\"
  fi
  echo \"Using user: $RUN_AS\"
  UNIT=/etc/systemd/system/$SVC.service
  TMPUNIT=\"/tmp/$SVC.service.$$\"
  cat > \"$TMPUNIT\" <<EOF
[Unit]
Description=Django Dev Server ($SVC)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$RUN_AS
WorkingDirectory=$DEST_RESOLVED
Environment=PYTHONUNBUFFERED=1
EnvironmentFile=-$DEST_RESOLVED/.env
ExecStart=$VENV manage.py runserver 0.0.0.0:$PORT
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
  sudo mv \"$TMPUNIT\" \"$UNIT\"
  sudo chown root:root \"$UNIT\"
  sudo chmod 0644 \"$UNIT\"
  sudo systemctl daemon-reload
  sudo systemctl enable --now $SVC.service
  echo 'Service installed and started.'
  systemctl --no-pager --full status $SVC.service || true
"

echo "==> Done. Service name: ${SERVICE_NAME}. Use: 'sudo systemctl status ${SERVICE_NAME}'."
