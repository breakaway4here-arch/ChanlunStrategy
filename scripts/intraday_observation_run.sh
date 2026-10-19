#!/bin/zsh
# Independent 14:45 frozen-input observation; old daily/preclose jobs are untouched.
set -euo pipefail
unset IWENCAI_API_KEY IWENCAI_BASE_URL OPENAI_API_KEY DEEPSEEK_API_KEY ANTHROPIC_API_KEY
SCRIPT_DIR="${0:A:h}"
REPO_DIR="${SCRIPT_DIR:h}"
PYTHON_BIN="${CHANLUN_OBSERVATION_PYTHON:-/usr/bin/python3}"
ENV_FILE="${CHANLUN_OBSERVATION_ENV_FILE:-${HOME}/.config/chanlun-strategy/preclose.env}"
MARKET_DB="${CHANLUN_MARKET_HISTORY_DB_PATH:-${REPO_DIR}/.cache/chanlun/market_history.sqlite}"
ROOT="${REPO_DIR}/.cache/chanlun/intraday-observation"
if (( $# == 0 )); then
  SHANGHAI_HHMM="$(TZ=Asia/Shanghai /bin/date +%H%M)"
  if (( 10#$SHANGHAI_HHMM < 1445 || 10#$SHANGHAI_HHMM >= 1458 )); then
    exit 0
  fi
fi
/bin/mkdir -p "$ROOT/logs"
cd "$REPO_DIR"
if (( $# == 0 )); then
  exec "$PYTHON_BIN" "$REPO_DIR/intraday_observation_run.py" \
    --scheduled --send --root "$ROOT" --formal-market-db "$MARKET_DB" \
    --env-file "$ENV_FILE" >>"$ROOT/logs/run.log" 2>&1
fi
exec "$PYTHON_BIN" "$REPO_DIR/intraday_observation_run.py" "$@" >>"$ROOT/logs/run.log" 2>&1
