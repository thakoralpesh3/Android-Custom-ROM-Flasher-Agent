#!/usr/bin/env bash
# ==============================================================================
# DroidFlash Agent - Launcher Script
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PYTHON_BIN="python3"

# Check if python3 is available
if ! command -v "$PYTHON_BIN" &> /dev/null; then
    echo "❌ Error: Python 3 is required to run DroidFlash Agent."
    echo "Press Enter to exit..."
    read -r
    exit 1
fi

MODE="${1:---gui}"

case "$MODE" in
    --gui|--dashboard)
        echo "🚀 Launching DroidFlash Web GUI Dashboard..."
        exec "$PYTHON_BIN" "$SCRIPT_DIR/app.py" --gui "${@:2}"
        ;;
    --wizard|--cli)
        echo "🧙 Starting DroidFlash Interactive Terminal Wizard..."
        exec "$PYTHON_BIN" "$SCRIPT_DIR/app.py" --wizard "${@:2}"
        ;;
    --check)
        exec "$PYTHON_BIN" "$SCRIPT_DIR/app.py" --check
        ;;
    --sync-github)
        echo "🐙 Syncing DroidFlash Agent to GitHub..."
        "$PYTHON_BIN" "$SCRIPT_DIR/app.py" --sync-github "${@:2}"
        EXIT_CODE=$?
        echo ""
        echo "Press Enter to exit..."
        read -r
        exit $EXIT_CODE
        ;;
    --setup-tools)
        echo "🛠️ Downloading and setting up Android Platform Tools..."
        "$PYTHON_BIN" "$SCRIPT_DIR/app.py" --setup-tools
        EXIT_CODE=$?
        echo ""
        echo "Press Enter to exit..."
        read -r
        exit $EXIT_CODE
        ;;
    *)
        exec "$PYTHON_BIN" "$SCRIPT_DIR/app.py" "$@"
        ;;
esac
