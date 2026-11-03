#!/bin/sh
# Browser test: Home Assistant (container) + fake portal + Playwright.
# Developer tooling. Needs docker; caches live under ~/.cache/claude-work/mef.
#   tests/browser/run.sh            full run (screenshots in $WORK/out/shots)
#   REUSE=1 tests/browser/run.sh    keep a running Home Assistant (card edits are live)
set -eu
REPO=$(cd "$(dirname "$0")/../.." && pwd)
WORK=${WORK:-$HOME/.cache/claude-work/mef/browser}
HA_IMAGE=${HA_IMAGE:-homeassistant/home-assistant:2026.10.4}
PW_IMAGE=${PW_IMAGE:-mcr.microsoft.com/playwright/python:v1.56.0-noble}
PORTAL_IMAGE=${PORTAL_IMAGE:-python:3.14-slim}

start() {
  mkdir -p "$WORK"
  # The containers run as root: clean up through one.
  docker run --rm -v "$WORK:/w" alpine sh -c "rm -rf /w/config /w/out"
  mkdir -p "$WORK/config/.storage" "$WORK/out/shots"
  cat > "$WORK/config/configuration.yaml" <<'Y'
default_config:
logger:
  default: warning
  logs:
    custom_components.mon_espace_famille: debug
Y
  cat > "$WORK/config/.storage/lovelace" <<'J'
{"version":1,"minor_version":1,"key":"lovelace","data":{"config":{"views":[
 {"title":"Planning","path":"planning","cards":[{"type":"custom:mon-espace-famille-planning-card"}]},
 {"title":"Row","path":"row","cards":[{"type":"custom:mon-espace-famille-planning-card","layout":"row"}]},
 {"title":"Wide","path":"wide","panel":true,"cards":[{"type":"custom:mon-espace-famille-planning-card","layout":"row"}]}]}}}
J
  docker rm -f mef-ha mef-portal >/dev/null 2>&1 || true
  docker network inspect mef-net >/dev/null 2>&1 || docker network create mef-net >/dev/null
  docker run -d --name mef-portal --network mef-net \
    -v "$REPO/tests:/t:ro" "$PORTAL_IMAGE" \
    sh -c 'pip install -q aiohttp && python /t/browser/fake_portal.py 8099' >/dev/null
  docker run -d --name mef-ha --network mef-net -e TZ=Europe/Paris \
    -e MEF_API_BASE=http://mef-portal:8099/api/v2/ \
    -v "$WORK/config:/config" \
    -v "$REPO/custom_components/mon_espace_famille:/config/custom_components/mon_espace_famille:ro" \
    "$HA_IMAGE" >/dev/null
}

if [ "${REUSE:-}" = 1 ] && docker inspect mef-ha >/dev/null 2>&1; then
  docker run --rm -v "$WORK:/w" alpine sh -c "rm -rf /w/out/shots; mkdir -p /w/out/shots"
else
  start
  if [ "${REUSE:-}" != 1 ]; then
    trap 'docker logs mef-ha > "$WORK/out/ha.log" 2>&1; docker rm -f mef-ha mef-portal >/dev/null 2>&1' EXIT
  fi
fi
docker run --rm --name mef-pw --network mef-net -e OUT=/out \
  -v "$WORK/out:/out" -v "$REPO/tests:/t:ro" "$PW_IMAGE" \
  sh -c "pip install -q playwright==1.56.0 && python /t/browser/browser_check.py"
