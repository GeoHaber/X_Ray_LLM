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

VENV_DIR=".venv"

# Create virtualenv if it doesn't exist
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment in $VENV_DIR ..."
    python3 -m venv "$VENV_DIR"
    echo "Installing dependencies ..."
    "$VENV_DIR/bin/pip" install --quiet -r requirements.txt
fi

# Activate the virtual environment
# shellcheck disable=SC1091
. "$VENV_DIR/bin/activate"

echo "Using Python: $(which python3)"
echo ""

python3 ui_server.py "$@"
