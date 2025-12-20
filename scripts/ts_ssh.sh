#!/usr/bin/env bash
set -euo pipefail
# Wrapper to make `tailscale ssh` act more like `ssh` when invoked by rsync
# Handles a subset of flags used by rsync: -l USER, -p PORT, -o OPT=VAL (ignored)

USER_OPT=""
PORT_OPT=""
args=("$@")
i=0
while (( i < ${#args[@]} )); do
  a=${args[$i]}
  case "$a" in
    -l)
      ((i++)); USER_OPT=${args[$i]:-}; ((i++));;
    -p)
      # tailscale ssh doesn't need -p; ignore and consume value
      ((i++)); PORT_OPT=${args[$i]:-}; ((i++));;
    -o)
      # ignore one -o option and its value
      ((i++)); ((i++));;
    --)
      ((i++)); break;;
    -*)
      # ignore unknown flags
      ((i++));;
    *)
      break;;
  esac
done

# Next arg should be host
HOST=${args[$i]:-}
if [[ -z "$HOST" ]]; then
  echo "ts_ssh.sh: missing host" >&2
  exit 2
fi
((i++))

# Remaining args are the remote command
CMD=( )
while (( i < ${#args[@]} )); do
  CMD+=("${args[$i]}")
  ((i++))
done

DEST=$HOST
if [[ -n "$USER_OPT" ]]; then
  DEST="$USER_OPT@$HOST"
fi

if ((${#CMD[@]})); then
  exec tailscale ssh "$DEST" -- "${CMD[@]}"
else
  exec tailscale ssh "$DEST"
fi
