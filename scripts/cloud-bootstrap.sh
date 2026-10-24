#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -c 'import sys; assert (3, 11) <= sys.version_info[:2] <= (3, 13), "Python 3.11–3.13 required"'
if ! command -v ffmpeg >/dev/null || ! command -v ffprobe >/dev/null; then
  sudo apt-get update -qq
  sudo apt-get install -y --no-install-recommends ffmpeg
fi
python3 -m venv .venv
.venv/bin/python -m pip install --disable-pip-version-check --only-binary=:all: -r requirements.txt
npm ci --ignore-scripts
SKIP_BUNDLED_FFMPEG=1 npm run build
.venv/bin/python scripts/fetch-stremio.py
mkdir -p .runtime/stremio
chmod 700 .runtime
.venv/bin/python - <<'PY'
import pathlib,secrets,json
root=pathlib.Path('.runtime')
secret=root/'playback-secret'
if not secret.exists():
    secret.write_text(secrets.token_hex(32));secret.chmod(0o600)
settings=root/'stremio/server-settings.json'
if not settings.exists():
    settings.write_text(json.dumps({'cacheRoot':str((root/'stremio').resolve()),
        'cacheSize':536870912,'localAddonEnabled':False,'remoteHttps':False,
        'btMaxConnections':55,'btDownloadSpeedSoftLimit':8388608,
        'btDownloadSpeedHardLimit':10485760,'btMinPeersForStable':5,
        'transcodeHardwareAccel':False}))
PY
printf '\nTest-video build and Stremio download complete.\n'
