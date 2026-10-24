#!/usr/bin/env bash
set -euo pipefail
root="$(dirname "$(dirname "$(readlink -f "$0")")")"
if ! command -v node >/dev/null; then
  for candidate in "$HOME"/.nvm/versions/node/*/bin/node; do
    if [[ -x "$candidate" ]]; then export PATH="$(dirname "$candidate"):$PATH"; fi
  done
fi
if [[ ! -x "$root/node_modules/.bin/electron" ]]; then
  printf 'Run npm install in %s first.\n' "$root" >&2
  exit 1
fi
if [[ ! -f "$root/frontend/dist/index.html" ]]; then
  npm --prefix "$root/frontend" run build
fi
if [[ -x "$root/backend/.venv/bin/python" ]] && "$root/backend/.venv/bin/python" -c 'import fastapi, uvicorn, keyring, httpx' 2>/dev/null; then
  export VPN_PYTHON="$root/backend/.venv/bin/python"
fi
unset ELECTRON_RUN_AS_NODE
exec "$root/node_modules/.bin/electron" "$root" "$@"
