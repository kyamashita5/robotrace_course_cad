#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1 && ! command -v python >/dev/null 2>&1; then
    echo "[ERROR] Python was not found. Install Python 3.10 or newer." >&2
    exit 1
fi

if ! command -v uv >/dev/null 2>&1; then
    echo "[ERROR] uv was not found. Install uv and add it to PATH." >&2
    exit 1
fi

if [ ! -x ".venv/bin/python" ]; then
    echo "[INFO] Creating virtual environment: .venv"
    uv venv
fi

echo "[INFO] Installing/updating dependencies"
uv pip install -e .

echo "[INFO] Starting Robotrace Course CAD"
exec .venv/bin/robotrace-course-cad "$@"
