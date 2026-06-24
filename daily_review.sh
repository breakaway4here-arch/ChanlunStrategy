#!/bin/bash
# 每日盘后缠论持仓诊断 + 推送

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if [ -f "$SCRIPT_DIR/.env" ]; then
  set -a
  . "$SCRIPT_DIR/.env"
  set +a
fi

PYTHON_BIN="${PYTHON_BIN:-python3}"
DATE=$(date +%Y-%m-%d)

echo "===== $(date) ====="
echo "[1/2] 运行持仓诊断..."
"$PYTHON_BIN" -u review_holdings.py 2>&1

echo "[2/2] 推送报告..."
"$PYTHON_BIN" -u push_review.py --date "$DATE" 2>&1

echo "===== 完成 ====="
