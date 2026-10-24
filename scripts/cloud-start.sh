#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p .runtime
nohup bash scripts/cloud-run.sh >.runtime/cloud.log 2>&1 </dev/null &
.venv/bin/python - <<'PY'
import time,urllib.request,json
for _ in range(100):
    try:
        with urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=1) as r:
            j=json.load(r)
            if j.get('engineReady') and j.get('transport')=='Stremio EngineFS TCP/UDP':break
    except (OSError,ValueError):pass
    time.sleep(.3)
else:raise SystemExit('Server did not start. See .runtime/cloud.log and .runtime/backend.log')
PY
if [[ -n "${CODESPACE_NAME:-}" ]]; then
  if gh codespace ports visibility 8000:public --codespace "$CODESPACE_NAME"; then
    printf '\nOpen: https://%s-8000.app.github.dev/\n' "$CODESPACE_NAME"
  else
    printf '\nSet port 8000 visibility to Public in the Ports tab. Stremio ports must stay private.\n'
  fi
fi
