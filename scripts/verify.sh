#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check commerceops tests scripts/check_lightrag.py
.venv/bin/python -m commerceops evaluate
.venv/bin/python scripts/check_lightrag.py
