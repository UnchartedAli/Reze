#!/usr/bin/env bash
# End-to-end check of the Docker image, the way a managed host runs it:
#   build -> start with PORT injected -> /healthz -> page smoke test -> restart -> no re-migration.
# Developer: UnchartedAli · Channel: @yamods
#
# Requires Docker. Uses a throw-away password and volume; nothing is kept afterwards.
#   bash scripts/docker_e2e.sh [port]        (default port 3000)
set -euo pipefail

PORT="${1:-3000}"
NAME="reze-e2e-$$"
VOLUME="reze-e2e-data-$$"
PASS="e2e-$(head -c 12 /dev/urandom | od -An -tx1 | tr -d ' \n')"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

cleanup() {
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  docker volume rm "$VOLUME" >/dev/null 2>&1 || true
}
trap cleanup EXIT

wait_healthy() {
  for _ in $(seq 1 60); do
    if curl -fsS "http://127.0.0.1:${PORT}/healthz" >/dev/null 2>&1; then return 0; fi
    sleep 2
  done
  echo "FAIL: /healthz did not answer on port ${PORT}"; docker logs "$NAME" | tail -40; return 1
}

echo "== build";  docker build -t reze:e2e "$ROOT"
echo "== run with PORT=${PORT} and a named volume"
docker run -d --name "$NAME" \
  -e PORT="$PORT" -e REZE_PANEL_USERNAME=admin -e REZE_PANEL_PASSWORD="$PASS" \
  -e REZE_SECRET_KEY="e2e-secret-$PASS-local-only" -e REZE_TIMEZONE=UTC \
  -p "${PORT}:${PORT}" -v "$VOLUME:/app/data" reze:e2e >/dev/null
wait_healthy
wait_docker_healthy() {
  for _ in $(seq 1 60); do
    status="$(docker inspect -f '{{.State.Health.Status}}' "$NAME" 2>/dev/null || true)"
    if [ "$status" = "healthy" ]; then return 0; fi
    sleep 3
  done
  echo "FAIL: the image HEALTHCHECK did not report healthy (last: ${status:-unknown})"; return 1
}
wait_docker_healthy
echo "== image HEALTHCHECK: healthy"

echo "== page smoke test"
REZE_PANEL_PASSWORD="$PASS" python3 "$ROOT/scripts/smoke_panel.py" "http://127.0.0.1:${PORT}" admin

echo "== restart keeps data, without re-running migrations"
docker restart "$NAME" >/dev/null
wait_healthy
SINCE="$(docker inspect -f '{{.State.StartedAt}}' "$NAME")"
APPLIED="$(docker logs --since "$SINCE" "$NAME" 2>&1 | grep -c 'Applying database migration' || true)"
if [ "$APPLIED" != "0" ]; then echo "FAIL: $APPLIED migration(s) ran on restart"; exit 1; fi
echo "== restart: no migrations re-applied"
echo "PASS"
