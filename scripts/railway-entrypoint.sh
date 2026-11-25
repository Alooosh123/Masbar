#!/bin/sh
set -eu

APP_UID="${APP_UID:-10001}"
APP_GID="${APP_GID:-10001}"
SESSION_DB_PATH="${SESSION_DB_PATH:-/app/data/sessions/sessions.sqlite3}"
SESSION_DIR="$(dirname "$SESSION_DB_PATH")"

mkdir -p "$SESSION_DIR"

if [ "$(id -u)" -eq 0 ]; then
  # Railway mounts persistent volumes as root. Fix only the dedicated session
  # directory, then drop to the unprivileged application UID before exec.
  chown "$APP_UID:$APP_GID" "$SESSION_DIR"
  chmod 0700 "$SESSION_DIR"
  exec gosu "$APP_UID:$APP_GID" "$@"
fi

if [ ! -w "$SESSION_DIR" ]; then
  echo "Session directory is not writable by UID $(id -u): $SESSION_DIR" >&2
  echo "On Railway, set RAILWAY_RUN_UID=0 so this entrypoint can prepare the mounted volume and drop back to UID $APP_UID." >&2
  exit 1
fi

exec "$@"
