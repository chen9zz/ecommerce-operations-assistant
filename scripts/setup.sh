#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
if [ ! -x .venv/bin/python ]; then
  project_python="${PYTHON:-python3}"
  "$project_python" -c 'import sys; assert sys.version_info >= (3,12), "需要 Python 3.12+；可通过 PYTHON 指定解释器"'
  "$project_python" -m venv .venv
fi
.venv/bin/python -m pip install -e '.[dev]'
if [ "${1:-}" = '--with-lightrag' ]; then
  .venv/bin/python -m pip install ../LightRAG
fi
printf '%s\n' '安装完成。运行 sh run.sh 后打开 http://127.0.0.1:8877'
