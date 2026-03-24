#!/bin/bash
# Start all sovara services in development mode.
# Usage: ./dev.sh
# Stop:  Ctrl-C (kills all background processes)

set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"
WEB_APP="$ROOT/ui/web_app"
VSCODE_EXT="$ROOT/ui/vscode_extension"

# Trap Ctrl-C to kill all background processes
cleanup() {
    echo ""
    echo "Stopping all dev services..."
    kill 0 2>/dev/null
    wait 2>/dev/null
    echo "Done."
}
trap cleanup EXIT INT TERM

echo "=== sovara ==="
echo ""

# 1. Python server
echo "[so-server]  Starting..."
uv run so-server start 2>&1 | sed 's/^/[so-server]  /' &

# 2. Web app client (Vite dev server)
echo "[web-client] Starting on :5173..."
cd "$WEB_APP" && npm run dev 2>&1 | sed 's/^/[web-client] /' &

# 3. VS Code extension (webpack watch)
echo "[vscode-ext] Starting watch..."
cd "$VSCODE_EXT" && npm run watch 2>&1 | sed 's/^/[vscode-ext] /' &

echo ""
echo "All services starting. Press Ctrl-C to stop all."
echo ""

# Wait for all background jobs
wait
