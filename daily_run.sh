#!/bin/zsh
# 缠论选股日报 — 自动运行并推送
# 由 launchd 每个工作日 14:35 触发，15:05 做一次补偿触发

source ~/.zshrc 2>/dev/null || true
SCRIPT_DIR="${0:A:h}"
cd "$SCRIPT_DIR"

TODAY=$(date '+%Y-%m-%d')
TODAY_DATA_PATH="docs/data/${TODAY}.json"
INDEX_PATH="docs/index.html"

is_today_output_ready() {
    if [ ! -f "$TODAY_DATA_PATH" ]; then
        return 1
    fi

    if [ ! -f "$INDEX_PATH" ]; then
        return 1
    fi

    data_mtime=$(stat -f '%Sm' -t '%Y-%m-%d' "$TODAY_DATA_PATH" 2>/dev/null || true)
    index_mtime=$(stat -f '%Sm' -t '%Y-%m-%d' "$INDEX_PATH" 2>/dev/null || true)

    [ "$data_mtime" = "$TODAY" ] && [ "$index_mtime" = "$TODAY" ]
}

echo "=== 缠论选股日报 $(date '+%Y-%m-%d %H:%M:%S') ==="

if is_today_output_ready; then
    if /usr/bin/python3 scripts/validate_today_report.py "$TODAY"; then
        echo "今日产物已存在且行情校验通过，跳过补跑"
        exit 0
    fi
    echo "今日产物行情校验失败，强制重跑"
fi

/usr/bin/python3 -c 'import run; import chanlun.data_fetcher as df, chanlun.market_news as mn; df.SESSION.trust_env = False; mn.SESSION.trust_env = False; run.main(False)' 2>&1
run_status=$?

if [ $run_status -eq 0 ]; then
    if is_today_output_ready; then
        git add docs/index.html docs/data.json docs/data/ docs/20*/
        if ! git diff --cached --quiet; then
            git commit -m "chore: 自动更新 ${TODAY} 日报数据"
            git push
            echo "推送成功 $(date '+%H:%M:%S')"
        else
            echo "无数据变更，跳过推送"
        fi
    else
        echo "run.py 返回成功，但今日产物未生成，跳过推送"
        exit 1
    fi
else
    echo "run.py 执行失败，跳过推送"
    exit $run_status
fi
