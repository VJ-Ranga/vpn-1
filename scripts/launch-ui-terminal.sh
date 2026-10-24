#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${VPN_UI_PORT:-8766}"
URL="http://127.0.0.1:${PORT}"

if curl --fail --silent "${URL}/api/health" >/dev/null 2>&1; then
  printf 'Northstar VPN already running at %s\n' "$URL"
  xdg-open "$URL" >/dev/null 2>&1 &
  printf 'Close this terminal to return to menu. Existing backend stays running.\n'
  while curl --fail --silent "${URL}/api/health" >/dev/null 2>&1; do sleep 2; done
  exit 0
fi

cd "$ROOT/backend"
python3 -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT" &
backend_pid=$!
trap 'kill "$backend_pid" 2>/dev/null || true' EXIT INT TERM

for _ in $(seq 1 30); do
  if curl --fail --silent "${URL}/api/health" >/dev/null 2>&1; then
    xdg-open "$URL" >/dev/null 2>&1 &
    printf 'Northstar VPN running at %s\n' "$URL"
    printf 'Close this terminal to stop Northstar VPN.\n'
    wait "$backend_pid"
    exit 0
  fi
  sleep 1
done

printf 'Backend did not start.\n' >&2
exit 1
