#!/bin/zsh
# 缠论选股日报 — 自动运行并推送
# 由 launchd 每个工作日收盘后触发；第二次触发用于增量补齐缺失行情

set -e

SCRIPT_DIR="${0:A:h}"
if [ "${CHANLUN_DOCS_PUBLISH_LOCK_HELD:-0}" != "1" ]; then
    : ${CHANLUN_DOCS_PUBLISH_LOCK_PATH:="${SCRIPT_DIR}/.cache/chanlun/docs-publish.lock"}
    export CHANLUN_DOCS_PUBLISH_LOCK_PATH
    exec /usr/bin/python3 "${SCRIPT_DIR}/scripts/run_with_docs_publish_lock.py" \
        --lock-path "$CHANLUN_DOCS_PUBLISH_LOCK_PATH" -- /bin/zsh "$0" "$@"
fi

source ~/.zshrc 2>/dev/null || true
cd "$SCRIPT_DIR"

: ${CHANLUN_MARKET_DATA_MODE:=sqlite}
: ${CHANLUN_RECALL_STRATEGY_MODE:=active}
: ${CHANLUN_STOCK_SELECTION_SHADOW_MODE:=shadow}
: ${CHANLUN_LLM_PROVIDER:=codex}
: ${CHANLUN_CODEX_MODEL:=gpt-5.6-luna}
export CHANLUN_MARKET_DATA_MODE
export CHANLUN_RECALL_STRATEGY_MODE
export CHANLUN_STOCK_SELECTION_SHADOW_MODE
export CHANLUN_LLM_PROVIDER
export CHANLUN_CODEX_MODEL

TODAY=$(date '+%Y-%m-%d')
TODAY_DATA_PATH="docs/data/${TODAY}.json"
INDEX_PATH="docs/index.html"
RETRY_MISSING_ONLY=0
GIT_UPSTREAM="${CHANLUN_GIT_UPSTREAM:-origin/main}"
FORMAL_PUBLISH_JOURNAL_PATH="${CHANLUN_FORMAL_PUBLISH_JOURNAL_PATH:-${SCRIPT_DIR}/.cache/chanlun/formal-publish-targets.json}"

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
    local runtime_status

    if ! fetch_with_proxy_fallback; then
        return 1
    fi

    if git merge-base --is-ancestor "$GIT_UPSTREAM" HEAD; then
        return 0
    fi

    if git merge-base --is-ancestor HEAD "$GIT_UPSTREAM"; then
        runtime_status=$(git status --porcelain=v1 --untracked-files=all)
        if [ -n "$runtime_status" ]; then
            echo "运行目录含未提交内容，拒绝在正式重试期间快进"
            return 1
        fi
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

finalize_review_snapshot() {
    local market_db_path

    market_db_path="${CHANLUN_MARKET_HISTORY_DB_PATH:-${SCRIPT_DIR}/.cache/chanlun/market_history.sqlite}"
    /usr/bin/python3 scripts/repair_strategy_scorecard_snapshot.py \
        --report-date "$TODAY" \
        --docs-dir "${SCRIPT_DIR}/docs" \
        --ledger-path "${SCRIPT_DIR}/.cache/chanlun/recommendation_ledger.jsonl" \
        --market-db-path "$market_db_path"
}

prepare_formal_publish_state() {
    /usr/bin/python3 scripts/formal_publish_guard.py prepare \
        --repo-root "$SCRIPT_DIR" \
        --trade-date "$TODAY" \
        --journal-path "$FORMAL_PUBLISH_JOURNAL_PATH"
}

preflight_formal_publish_state() {
    /usr/bin/python3 scripts/formal_publish_guard.py preflight \
        --repo-root "$SCRIPT_DIR" \
        --trade-date "$TODAY" \
        --journal-path "$FORMAL_PUBLISH_JOURNAL_PATH"
}

record_formal_publish_targets() {
    /usr/bin/python3 scripts/formal_publish_guard.py record \
        --repo-root "$SCRIPT_DIR" \
        --trade-date "$TODAY" \
        --journal-path "$FORMAL_PUBLISH_JOURNAL_PATH"
}

finalize_and_record_review_snapshot() {
    local finalize_status

    if finalize_review_snapshot; then
        finalize_status=0
    else
        finalize_status=$?
    fi
    if ! record_formal_publish_targets; then
        echo "盘后固化后的正式产物来源日志写入失败"
        return 1
    fi
    return $finalize_status
}

main() {
    local run_status

    echo "=== 缠论选股日报 $(date '+%Y-%m-%d %H:%M:%S') ==="

    if ! preflight_formal_publish_state; then
        echo "正式发布来源无法确认，停止运行以保护用户改动"
        exit 1
    fi
    if ! sync_with_remote; then
        echo "远端同步未完成，停止生成，避免产生分叉提交"
        exit 1
    fi
    if ! prepare_formal_publish_state; then
        echo "远端同步后的正式发布来源无法确认，停止运行"
        exit 1
    fi

    if is_today_output_ready; then
        if /usr/bin/python3 scripts/validate_today_report.py "$TODAY"; then
            if /usr/bin/python3 scripts/validate_today_report.py \
                --needs-sublevel-retry "$TODAY"; then
                RETRY_MISSING_ONLY=1
                echo "正式策略已校验，但分钟级研究输入仍缺失，进入 15:20 增量补跑"
            else
                /usr/bin/python3 scripts/finalize_recommendation_ledger.py "$TODAY"
                if ! finalize_and_record_review_snapshot; then
                    echo "账本已固化，但页面回看/固化状态回写失败，停止发布"
                    exit 1
                fi
                if ! publish_ready_report; then
                    exit 1
                fi
                echo "今日产物已存在且行情与选股输入校验通过，跳过补跑"
                exit 0
            fi
        else
            RETRY_MISSING_ONLY=1
            echo "今日产物行情或选股输入校验失败，进入缺失数据增量补跑"
        fi
    fi

    export CHANLUN_DAILY_RETRY_MISSING_ONLY=$RETRY_MISSING_ONLY
    if [ "$RETRY_MISSING_ONLY" -eq 1 ]; then
        echo "日报补跑模式：只刷新缺失、过期或未收盘的日线数据"
    else
        echo "日报首跑模式：使用行情数据库优先，按需刷新日线数据"
    fi

    if /usr/bin/python3 -c 'import run; import chanlun.data_fetcher as df, chanlun.market_news as mn; df.SESSION.trust_env = False; mn.SESSION.trust_env = False; run.main(False)' 2>&1; then
        run_status=0
    else
        run_status=$?
    fi
    if ! record_formal_publish_targets; then
        echo "正式任务运行后的产物来源日志写入失败，停止发布"
        exit 1
    fi

    if [ $run_status -eq 0 ]; then
        if is_today_output_ready; then
            if ! /usr/bin/python3 scripts/validate_today_report.py "$TODAY"; then
                echo "正式日报校验失败，保留本地产物但不提交，等待下一次收盘后增量补跑"
                exit 1
            fi
            /usr/bin/python3 scripts/finalize_recommendation_ledger.py "$TODAY"
            if ! finalize_and_record_review_snapshot; then
                echo "账本已固化，但页面回看/固化状态回写失败，停止发布"
                exit 1
            fi
            if ! publish_ready_report; then
                exit 1
            fi
        else
            echo "run.py 返回成功，但今日产物未生成，跳过推送"
            exit 1
        fi
    else
        echo "run.py 执行失败，跳过推送"
        exit $run_status
    fi
}

commit_today_report_if_changed() {
    if ! git diff --cached --quiet; then
        echo "索引已有未提交改动，拒绝自动提交"
        return 1
    fi
    if ! /usr/bin/python3 scripts/stage_report_asset_version_updates.py \
        --repo-root "$SCRIPT_DIR" \
        --docs-dir "$SCRIPT_DIR/docs" \
        --journal-path "$FORMAL_PUBLISH_JOURNAL_PATH"; then
        echo "历史入口资源版本暂存失败，停止自动提交"
        return 1
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
    else
        echo "无日报数据变更，检查是否存在待补推提交"
    fi
}

publish_ready_report() {
    if ! fetch_with_proxy_fallback; then
        echo "提交前远端回读失败，保留已校验产物，等待下一次补推"
        return 1
    fi
    if ! git merge-base --is-ancestor "$GIT_UPSTREAM" HEAD; then
        echo "提交前发现远端 main 已前进，拒绝在脏产物上自动合并"
        return 1
    fi
    if ! commit_today_report_if_changed; then
        return 1
    fi
    push_pending_commits
}

main "$@"
