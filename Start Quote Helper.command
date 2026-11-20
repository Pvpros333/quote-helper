#!/bin/bash
# Double-click this file in Finder to start Quote Helper.
# First run sets up a private Python environment (takes a minute); later runs start instantly.
cd "$(dirname "$0")" || exit 1

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is not installed."
  echo "Install it from https://www.python.org/downloads/macos/ and then double-click this file again."
  read -r -p "Press Return to close."
  exit 1
fi

if [ ! -x .venv/bin/python ]; then
  echo "First-time setup: creating Python environment…"
  python3 -m venv .venv || { read -r -p "Setup failed. Press Return to close."; exit 1; }
fi

STAMP=".venv/.requirements-installed"
if [ ! -f "$STAMP" ] || ! cmp -s requirements.txt "$STAMP"; then
  echo "Installing / updating components…"
  .venv/bin/python -m pip install --quiet --upgrade pip
  .venv/bin/python -m pip install --quiet -r requirements.txt \
    || { read -r -p "Install failed (check internet). Press Return to close."; exit 1; }
  cp requirements.txt "$STAMP"
fi

exec .venv/bin/python app.py
