#!/bin/sh
# X-Ray Scanner — Web UI launcher (Linux / macOS)
set -e

echo "============================================"
echo "  X-Ray Scanner - Web UI"
echo "============================================"
echo ""
echo "Starting server on http://localhost:8077"
echo "Press Ctrl+C to stop"
echo ""

# Use uv if available for managed dependencies, otherwise plain python
if command -v uv >/dev/null 2>&1; then
    uv run python ui_server.py "$@"
else
    python3 ui_server.py "$@"
fi
