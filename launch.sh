#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if command -v python3 >/dev/null 2>&1; then
    PYTHON=python3
elif command -v python >/dev/null 2>&1; then
    PYTHON=python
else
    echo "Python not found. Install Python 3 and add it to PATH." >&2
    exit 1
fi

echo "Installing flasher requirements..."
"$PYTHON" -m pip install -r flasher/requirements.txt
exec "$PYTHON" -m flasher "$@"
