#!/bin/zsh
# 缠论选股日报 — 自动运行并推送
# 由 launchd 每个工作日收盘后触发；第二次触发用于增量补齐缺失行情

set -e

source ~/.zshrc 2>/dev/null || true
SCRIPT_DIR="${0:A:h}"
cd "$SCRIPT_DIR"

: ${CHANLUN_MARKET_DATA_MODE:=sqlite}
: ${CHANLUN_RECALL_STRATEGY_MODE:=active}
export CHANLUN_MARKET_DATA_MODE
export CHANLUN_RECALL_STRATEGY_MODE

TODAY=$(date '+%Y-%m-%d')
TODAY_DATA_PATH="docs/data/${TODAY}.json"
INDEX_PATH="docs/index.html"
RETRY_MISSING_ONLY=0
GIT_UPSTREAM="${CHANLUN_GIT_UPSTREAM:-origin/main}"

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

push_with_proxy_fallback() {
    local proxy

    for proxy in 127.0.0.1:17891 127.0.0.1:7897; do
        echo "尝试推送（GitHub proxy: ${proxy}）..."
        if git \
            -c "http.https://github.com.proxy=${proxy}" \
            -c "https.https://github.com.proxy=${proxy}" \
            push; then
            echo "推送成功 $(date '+%H:%M:%S')，使用代理 ${proxy}"
            return 0
        fi
        echo "代理 ${proxy} 推送失败，尝试下一个"
    done

    echo "推送失败：两条代理路径均未完成推送，请查看上方 Git 错误"
    return 1
}

fetch_with_proxy_fallback() {
    local proxy

    for proxy in 127.0.0.1:17891 127.0.0.1:7897; do
        echo "尝试同步远端（GitHub proxy: ${proxy}）..."
        if git \
            -c "http.https://github.com.proxy=${proxy}" \
            -c "https.https://github.com.proxy=${proxy}" \
            fetch origin main; then
            echo "远端同步成功 $(date '+%H:%M:%S')，使用代理 ${proxy}"
            return 0
        fi
        echo "代理 ${proxy} 同步失败，尝试下一个"
    done

    echo "远端同步失败：两条代理路径均不可用"
    return 1
}

sync_with_remote() {
    if ! fetch_with_proxy_fallback; then
        return 1
    fi

    if git merge-base --is-ancestor "$GIT_UPSTREAM" HEAD; then
        return 0
    fi

    if git merge-base --is-ancestor HEAD "$GIT_UPSTREAM"; then
        echo "本地落后 ${GIT_UPSTREAM}，执行安全快进"
        git merge --ff-only "$GIT_UPSTREAM"
        return $?
    fi

    echo "本地与 ${GIT_UPSTREAM} 已分叉，拒绝自动改写工作区"
    return 1
}

push_pending_commits() {
    local pending_count

    if ! pending_count=$(git rev-list --count "${GIT_UPSTREAM}..HEAD"); then
        echo "无法判断待推送提交数量"
        return 1
    fi

    if [ "$pending_count" -eq 0 ]; then
        return 0
    fi

    echo "发现 ${pending_count} 个待推送提交，开始补推"
    push_with_proxy_fallback
}

echo "=== 缠论选股日报 $(date '+%Y-%m-%d %H:%M:%S') ==="

if ! sync_with_remote; then
    echo "远端同步未完成，停止生成，避免产生分叉提交"
    exit 1
fi

if is_today_output_ready; then
    if /usr/bin/python3 scripts/validate_today_report.py "$TODAY"; then
        if ! push_pending_commits; then
            exit 1
        fi
        echo "今日产物已存在且行情校验通过，跳过补跑"
        exit 0
    fi
    RETRY_MISSING_ONLY=1
    echo "今日产物行情校验失败，进入缺失数据增量补跑"
fi

export CHANLUN_DAILY_RETRY_MISSING_ONLY=$RETRY_MISSING_ONLY
if [ "$RETRY_MISSING_ONLY" -eq 1 ]; then
    echo "日报补跑模式：只刷新缺失、过期或未收盘的日线数据"
else
    echo "日报首跑模式：使用行情数据库优先，按需刷新日线数据"
fi

/usr/bin/python3 -c 'import run; import chanlun.data_fetcher as df, chanlun.market_news as mn; df.SESSION.trust_env = False; mn.SESSION.trust_env = False; run.main(False)' 2>&1
run_status=$?

if [ $run_status -eq 0 ]; then
    if is_today_output_ready; then
        if ! /usr/bin/python3 scripts/validate_today_report.py "$TODAY"; then
            echo "正式日报校验失败，保留本地产物但不提交，等待下一次收盘后增量补跑"
            exit 1
        fi
        git add \
            "docs/index.html" \
            docs/data.json \
            "docs/data/comparison-index.json" \
            "docs/data/index.json" \
            "docs/data/${TODAY}.json" \
            "docs/${TODAY}/index.html" \
            "docs/assets/report-v2.css" \
            "docs/assets/report-v2.js"
        if ! git diff --cached --quiet; then
            git commit -m "chore: 自动更新 ${TODAY} 日报数据"
            if ! push_pending_commits; then
                exit 1
            fi
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
