#!/bin/zsh
# Isolated 14:45 advisory. Python validates and reads only the dedicated 0600
# preclose.env; this wrapper deliberately does not source formal strategy flags.

set -euo pipefail

unset IWENCAI_API_KEY IWENCAI_BASE_URL OPENAI_API_KEY DEEPSEEK_API_KEY ANTHROPIC_API_KEY

SCRIPT_DIR="${0:A:h}"
REPO_DIR="${SCRIPT_DIR:h}"
PYTHON_BIN="${CHANLUN_PRECLOSE_PYTHON:-/usr/bin/python3}"
LOG_DIR="${REPO_DIR}/.cache/chanlun/preclose/logs"
ENV_FILE="${CHANLUN_PRECLOSE_ENV_FILE:-${HOME}/.config/chanlun-strategy/preclose.env}"
MARKET_DB="${CHANLUN_MARKET_HISTORY_DB_PATH:-${REPO_DIR}/.cache/chanlun/market_history.sqlite}"

mkdir -p "$LOG_DIR"
cd "$REPO_DIR"

if (( $# == 0 )); then
    exec "$PYTHON_BIN" "$REPO_DIR/preclose_run.py" \
        --scheduled \
        --root "$REPO_DIR/.cache/chanlun/preclose" \
        --formal-market-db "$MARKET_DB" \
        --env-file "$ENV_FILE" \
        >>"$LOG_DIR/preclose-run.log" 2>&1
fi

exec "$PYTHON_BIN" "$REPO_DIR/preclose_run.py" "$@" \
    >>"$LOG_DIR/preclose-run.log" 2>&1
