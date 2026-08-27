#!/bin/zsh
# Independent post-close, read-only reconciliation. It never invokes or gates
# the formal daily task and writes only below the dedicated pre-close cache.

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
    TRADE_DATE="$(/bin/date '+%Y-%m-%d')"
    exec "$PYTHON_BIN" "$REPO_DIR/scripts/preclose_reconcile.py" \
        --trade-date "$TRADE_DATE" \
        --root "$REPO_DIR/.cache/chanlun/preclose" \
        --docs-dir "$REPO_DIR/docs" \
        --formal-market-db "$MARKET_DB" \
        --env-file "$ENV_FILE" \
        --poll --poll-seconds 30 --stop-at 15:35:00 \
        >>"$LOG_DIR/preclose-reconcile.log" 2>&1
fi

exec "$PYTHON_BIN" "$REPO_DIR/scripts/preclose_reconcile.py" "$@" \
    >>"$LOG_DIR/preclose-reconcile.log" 2>&1
