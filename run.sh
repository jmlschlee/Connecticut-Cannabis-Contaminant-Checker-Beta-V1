#!/usr/bin/env bash
# CannaScope Beta V5 launcher (macOS / Linux)
set -e
cd "$(dirname "$0")"
python3 -m venv .venv 2>/dev/null || true
# shellcheck disable=SC1091
. .venv/bin/activate
pip install -q --upgrade pip >/dev/null 2>&1 || true
pip install -q -r requirements.txt
python cannascope_beta_v5.py "$@"
