#!/usr/bin/env sh
# Create a virtualenv on first run, install dependencies, start InternProMax.
set -e
cd "$(dirname "$0")"
PY="${PYTHON:-python3}"
if [ ! -d .venv ]; then
  "$PY" -m venv .venv
  .venv/bin/pip install --upgrade pip >/dev/null
fi
.venv/bin/pip install -q -r requirements.txt
exec .venv/bin/python -m internpromax "$@"
