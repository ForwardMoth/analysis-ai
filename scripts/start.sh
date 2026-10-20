#!/bin/zsh
# Starts the AI Interview web UI and opens it in the browser (reuses a running server).
cd "${0:A:h}/.." || exit 1
source .venv/bin/activate
exec python src/app.py --port 8765 --open
