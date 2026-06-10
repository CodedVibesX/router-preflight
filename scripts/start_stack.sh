#!/usr/bin/env bash
# Boot a local Weave Router stack built from source, then wait for /health.
#
# This is the from-source recipe used for the recorded run in this repo:
# embedded Postgres (zonky binaries), the pstest Pub/Sub shim the router's
# invalidation bus expects, and the router server itself with its ONNX
# embedder assets. If you run the router via its own docker-compose.yml
# you do not need this script at all.
#
# Required environment:
#   WVR_RUNTIME  dir containing pg/ pgdata/ assets/ onnxruntime/
#   WVR_BIN      dir containing the built router binaries (server, fakepubsub)
# Optional:
#   WVR_PG_PORT  default 5432
#   WVR_DB_URL   default postgres://router@127.0.0.1:$WVR_PG_PORT/router?sslmode=disable
set -euo pipefail

RUNTIME="${WVR_RUNTIME:?set WVR_RUNTIME to the runtime dir (pg/, pgdata/, assets/, onnxruntime/)}"
BIN="${WVR_BIN:?set WVR_BIN to the dir with the built router binaries}"
PG_PORT="${WVR_PG_PORT:-5432}"
LOG_DIR="${WVR_LOG_DIR:-/tmp/router-preflight-stack}"
mkdir -p "$LOG_DIR"

pkill -f "$BIN/server" 2>/dev/null || true
pkill -f "$BIN/fakepubsub" 2>/dev/null || true

"$RUNTIME/pg/bin/pg_ctl" -D "$RUNTIME/pgdata" -l "$LOG_DIR/pg.log" \
  -o "-p $PG_PORT -k /tmp" -w start >/dev/null 2>&1 || true

"$BIN/fakepubsub" > "$LOG_DIR/fakepubsub.log" 2>&1 &
sleep 0.3

export DATABASE_URL="${WVR_DB_URL:-postgres://router@127.0.0.1:$PG_PORT/router?sslmode=disable}"
export PUBSUB_EMULATOR_HOST=127.0.0.1:8085
export PUBSUB_PROJECT_ID=router-local
export PUBSUB_TOPIC_ROUTER_INVALIDATION=router-installation-invalidate
export PUBSUB_SUBSCRIPTION_ROUTER_INVALIDATION=router-installation-invalidate
export ROUTER_ONNX_ASSETS_DIR="$RUNTIME/assets"
export ROUTER_ONNX_LIBRARY_DIR="$RUNTIME/onnxruntime/lib"
export LD_LIBRARY_PATH="$RUNTIME/onnxruntime/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

"$BIN/server" > "$LOG_DIR/server.log" 2>&1 &

for _ in $(seq 1 40); do
  if curl -fsS http://localhost:8080/health >/dev/null 2>&1; then
    echo "stack up: router :8080, postgres :$PG_PORT, pubsub shim :8085 (logs in $LOG_DIR)"
    exit 0
  fi
  sleep 0.5
done
echo "router did not come up; see $LOG_DIR/server.log" >&2
exit 1
