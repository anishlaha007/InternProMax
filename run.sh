#!/usr/bin/env sh
# Create a virtualenv on first run, install dependencies, start InternProMax.
set -e
cd "$(dirname "$0")"
PY="${PYTHON:-python3}"
# A virtualenv breaks when its folder is moved: rebuild it if so (your data in ./data is untouched).
if [ -d .venv ] && ! .venv/bin/pip --version >/dev/null 2>&1; then
  echo "Rebuilding the Python environment (the folder was moved)..."
  rm -rf .venv
fi
if [ ! -d .venv ]; then
  "$PY" -m venv .venv
  .venv/bin/pip install --upgrade pip >/dev/null
fi
.venv/bin/pip install -q -r requirements.txt
exec .venv/bin/python -m internpromax "$@"
