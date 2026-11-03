#!/bin/zsh
# One finite invocation. No arguments means CLI dry-run, never an implicit send.
set -euo pipefail
REPO_DIR="${0:A:h:h}"
PYTHON_BIN="${OPENING_LIMITUP_PYTHON:-/usr/bin/python3}"
export TZ=Asia/Shanghai
export PYTHONUNBUFFERED=1
cd "$REPO_DIR"
exec "$PYTHON_BIN" "$REPO_DIR/opening_limitup_run.py" "$@"
