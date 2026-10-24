#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p .runtime
exec 9>.runtime/cloud.lock
flock -n 9 || exit 0
.venv/bin/python - <<'PY'
import socket
for port in [11470,8000]:
    with socket.socket() as s:
        try:s.bind(('127.0.0.1',port))
        except OSError:raise SystemExit(f'Port {port} is already in use; no existing process was stopped.')
PY
export STREMIO_URL=http://127.0.0.1:11470
export STREMIO_STATE_PATH="$PWD/.runtime/stremio"
export TORRENT_CACHE_BYTES=536870912 TORRENT_MAX_SESSIONS=1
export FFMPEG_BIN="$(command -v ffmpeg)" FFPROBE_BIN="$(command -v ffprobe)"
PLAYBACK_SECRET=$(cat .runtime/playback-secret)
export PLAYBACK_SECRET
APP_PATH="$STREMIO_STATE_PATH" CASTING_DISABLED=1 NO_CORS=1 \
  node .runtime/bin/stremio-server.js >.runtime/stremio.log 2>&1 &
stremio_pid=$!
cleanup() {
  kill "$stremio_pid" "${backend_pid:-}" 2>/dev/null || true
  wait "$stremio_pid" "${backend_pid:-}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM
.venv/bin/python - <<'PY'
import time,urllib.request,json
for _ in range(50):
    try:
        with urllib.request.urlopen('http://127.0.0.1:11470/heartbeat',timeout=1) as r:
            if json.load(r).get('success'):break
    except (OSError,ValueError):pass
    time.sleep(.2)
else:raise SystemExit('Stremio did not start. See .runtime/stremio.log')
PY
.venv/bin/python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --no-access-log >.runtime/backend.log 2>&1 &
backend_pid=$!
printf 'Test-video is running on port 8000. Stremio ports remain private.\n'
wait -n "$stremio_pid" "$backend_pid"
