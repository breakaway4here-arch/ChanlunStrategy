#!/bin/zsh
# 缠论选股日报 — 自动运行并推送
# 由 launchd 工作日 15:05/15:20/15:35/15:50 有限触发，重试缺失数据或待补推提交

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

export TZ=Asia/Shanghai
TODAY=$(date '+%Y-%m-%d')
TODAY_DATA_PATH="docs/data/${TODAY}.json"
INDEX_PATH="docs/index.html"
RETRY_MISSING_ONLY=0
GIT_UPSTREAM="${CHANLUN_GIT_UPSTREAM:-origin/main}"
FORMAL_PUBLISH_JOURNAL_PATH="${CHANLUN_FORMAL_PUBLISH_JOURNAL_PATH:-${SCRIPT_DIR}/.cache/chanlun/formal-publish-targets.json}"

is_today_output_ready() {
    # This is only source readiness. Validation and the locked snapshot repair
    # below decide publication readiness, including interrupted derived files.
    [ -f "$TODAY_DATA_PATH" ]
}

push_with_proxy_fallback() {
    /usr/bin/python3 "${SCRIPT_DIR}/scripts/run_daily_git_network.py" push \
        --retry-delay-seconds "${CHANLUN_DAILY_GIT_RETRY_DELAY_SECONDS:-5}"
}

fetch_with_proxy_fallback() {
    /usr/bin/python3 "${SCRIPT_DIR}/scripts/run_daily_git_network.py" fetch \
        --retry-delay-seconds "${CHANLUN_DAILY_GIT_RETRY_DELAY_SECONDS:-5}"
}

is_today_report_published() {
    local pending_count
    local docs_status

    # Only skip side effects after validating all required public planes and
    # proving their bytes are tracked at the freshly fetched remote revision.
    pending_count=$(git rev-list --count "${GIT_UPSTREAM}..HEAD") || return 1
    [ "$pending_count" -eq 0 ] || return 1
    git ls-files --error-unmatch -- \
        "$INDEX_PATH" "docs/data.json" "docs/data/index.json" \
        "$TODAY_DATA_PATH" "docs/${TODAY}/index.html" \
        "docs/assets/report-v2.css" "docs/assets/report-v2.js" >/dev/null 2>&1 || return 1
    docs_status=$(git status --porcelain=v1 --untracked-files=all -- docs) || return 1
    [ -z "$docs_status" ] || return 1
    git diff --quiet "$GIT_UPSTREAM" -- docs || return 1
    /usr/bin/python3 scripts/validate_today_report.py --public-planes-only "$TODAY"
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

assert_no_pending_kaipanla_publication() {
    local -a kpl_receipts
    local ahead_subjects subject

    kpl_receipts=("${SCRIPT_DIR}/.cache/chanlun/kaipanla"/publication-*.json(N))
    if [ "${#kpl_receipts}" -ne 0 ]; then
        echo "开盘啦 pending 必须先经专用 receipt 校验，拒绝通用补推"
        return 1
    fi
    ahead_subjects=$(git log --format=%s "${GIT_UPSTREAM}..HEAD") || return 1
    while IFS= read -r subject; do
        # This recognizes an unsafe orphan for rejection only; a title never
        # substitutes for a receipt or grants permission to publish anything.
        case "$subject" in
            "chore: 补更"????-??-??"开盘啦题材资料")
                echo "发现无可信 receipt 的开盘啦待推提交，拒绝通用发布"
                return 1
                ;;
        esac
    done <<< "$ahead_subjects"
}

push_pending_commits() {
    local pending_count

    assert_no_pending_kaipanla_publication || return 1

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
    # Recover only attested KPL commits before generic push/finalization. A clean
    # recovery may change HEAD; the prepare below rechecks journal provenance.
    local -a kpl_receipts
    kpl_receipts=("${SCRIPT_DIR}/.cache/chanlun/kaipanla"/publication-*.json(N))
    if [ "${#kpl_receipts}" -ne 0 ]; then
        if ! /bin/zsh "${SCRIPT_DIR}/scripts/kaipanla_refresh.sh" --recover-pending-only; then
            echo "开盘啦 pending 来源未确认，停止本轮正式发布"
            exit 1
        fi
    fi
    if ! sync_with_remote; then
        echo "远端同步未完成，停止生成，避免产生分叉提交"
        exit 1
    fi
    if ! assert_no_pending_kaipanla_publication; then
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
                echo "正式策略已校验，但分钟级研究输入仍缺失，进入本次收盘后增量补跑"
            else
                if is_today_report_published; then
                    echo "今日正式日报已校验并发布，跳过重复生成和固化"
                    run_optional_kaipanla_refresh
                    exit 0
                fi
                /usr/bin/python3 scripts/finalize_recommendation_ledger.py "$TODAY"
                if ! finalize_and_record_review_snapshot; then
                    echo "账本已固化，但页面回看/固化状态回写失败，停止发布"
                    exit 1
                fi
                if ! publish_ready_report; then
                    exit 1
                fi
                run_optional_kaipanla_refresh
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
    if ! /usr/bin/python3 scripts/validate_today_report.py \
        --public-planes-only "$TODAY"; then
        echo "日报公开文件与最新有效数据不一致，停止暂存和发布"
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
        "docs/data.json" \
        "docs/data/index.json" \
        "docs/data/${TODAY}.json" \
        "docs/${TODAY}/index.html" \
        "docs/assets/report-v2.css" \
        "docs/assets/report-v2.js"
    if [ -f "docs/data/comparison-index.json" ]; then
        if /usr/bin/python3 scripts/validate_today_report.py \
            --comparison-artifact-only "$TODAY"; then
            git add "docs/data/comparison-index.json"
        else
            echo "复盘索引未通过独立校验，本次不暂存；保留上一已发布版本"
        fi
    else
        echo "复盘索引本期未生成，仅提交已校验的正式日报产物"
    fi
    if ! /usr/bin/python3 scripts/stage_selection_performance.py \
        --repo-root "$SCRIPT_DIR" \
        --trade-date "$TODAY" \
        --journal-path "$FORMAL_PUBLISH_JOURNAL_PATH"; then
        echo "选股表现暂存出现异常，停止提交以保护已暂存产物"
        return 1
    fi
    if ! git diff --cached --quiet; then
        git commit -m "chore: 自动更新 ${TODAY} 日报数据"
    else
        echo "无日报数据变更，检查是否存在待补推提交"
    fi
}

run_optional_nextday_research_hook() {
    local market_db_path
    local hook_status
    local -a hook_args

    market_db_path="${CHANLUN_MARKET_HISTORY_DB_PATH:-${SCRIPT_DIR}/.cache/chanlun/market_history.sqlite}"
    hook_args=(
        --report "${SCRIPT_DIR}/${TODAY_DATA_PATH}"
        --db "$market_db_path"
        --as-of "$TODAY"
    )
    if [ -n "${CHANLUN_NEXTDAY_RESEARCH_DIR:-}" ]; then
        hook_args+=(--output-dir "$CHANLUN_NEXTDAY_RESEARCH_DIR")
    fi

    if /usr/bin/python3 "${SCRIPT_DIR}/scripts/nextday_research_hook.py" "${hook_args[@]}"; then
        return 0
    else
        hook_status=$?
        echo "可选次日研究钩子进程异常（exit=${hook_status}），不影响已发布日报"
        return 0
    fi
}

run_optional_kaipanla_refresh() {
    # run.main already fetches KPL on generation/incremental rounds. Only the
    # success paths that skip it need this one force-refresh opportunity.
    if /bin/zsh "${SCRIPT_DIR}/scripts/kaipanla_refresh.sh"; then
        return 0
    else
        echo "开盘啦单项补更未完成，保留已发布日报；后续有限轮次继续核验"
        return 0
    fi
}

publish_ready_report() {
    local push_status

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
    if push_pending_commits; then
        :
    else
        push_status=$?
        return "$push_status"
    fi
    if ! run_optional_nextday_research_hook; then
        echo "可选次日研究调用失败，不影响已发布日报"
    fi
    return 0
}

main "$@"
