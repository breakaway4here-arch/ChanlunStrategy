#!/bin/zsh
# One late optional supplement refresh; share the report publisher's lock.
set -euo pipefail
SCRIPT_DIR="${0:A:h}"
REPO_DIR="${SCRIPT_DIR:h}"
PYTHON="${CHANLUN_KPL_PYTHON:-/usr/bin/python3}"
LOCK_PATH=$(/usr/bin/python3 -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve())' "${REPO_DIR}/.cache/chanlun/docs-publish.lock")
if [[ "${CHANLUN_DOCS_PUBLISH_LOCK_HELD:-0}" != "1" || "${CHANLUN_DOCS_PUBLISH_LOCK_PATH:-}" != "$LOCK_PATH" ]]; then
    export CHANLUN_DOCS_PUBLISH_LOCK_PATH="$LOCK_PATH"
    exec /usr/bin/python3 "${SCRIPT_DIR}/refresh_kaipanla_context.py" \
        --docs-dir "${REPO_DIR}/docs" --lock-timeout 20 \
        --with-lock /bin/zsh "$0" "$@"
fi
cd "$REPO_DIR"
TODAY=$(TZ=Asia/Shanghai /bin/date '+%Y-%m-%d')
WEEKDAY=$(TZ=Asia/Shanghai /bin/date '+%u')
[[ "$WEEKDAY" -le 5 ]] || exit 0
# A holiday/missing/unofficial report never triggers the optional source request.
if ! "$PYTHON" "${SCRIPT_DIR}/refresh_kaipanla_context.py" --docs-dir docs --report-date "$TODAY" --check-ready; then
    print -u2 "今日正式收盘报告未就绪，跳过开盘啦补更"
    exit 0
fi
[[ "$(git branch --show-current)" == "main" ]] || { print -u2 "补更发布要求 main 分支"; exit 1; }
TARGETS=("docs/data/${TODAY}.json" "docs/data.json" "docs/index.html" "docs/${TODAY}/index.html")
# Keep unrelated working files, but never combine another task's index/targets.
git diff --cached --quiet || { print -u2 "已有暂存改动，停止补更"; exit 1; }
[[ -z "$(git status --porcelain=v1 --untracked-files=all -- "${TARGETS[@]}")" ]] || { print -u2 "补更目标已有改动，停止补更"; exit 1; }

network_git() {
    local proxy
    for proxy in 127.0.0.1:17891 127.0.0.1:7897; do
        if /usr/bin/python3 - "$proxy" "$@" <<'PY'
import os,signal,subprocess,sys
command=['git','-c','http.https://github.com.proxy='+sys.argv[1],
         '-c','https.https://github.com.proxy='+sys.argv[1]]+sys.argv[2:]
process=subprocess.Popen(command,start_new_session=True)
try:
    raise SystemExit(process.wait(timeout=30))
except subprocess.TimeoutExpired:
    os.killpg(process.pid,signal.SIGTERM)
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid,signal.SIGKILL)
        process.wait()
    print('Git network attempt exceeded 30 seconds',file=sys.stderr)
    raise SystemExit(1)
PY
        then return 0; fi
    done
    return 1
}
network_git fetch origin main || exit 1
if ! git merge-base --is-ancestor origin/main HEAD; then
    git merge-base --is-ancestor HEAD origin/main || { print -u2 "main 存在分歧，停止补更"; exit 1; }
    git merge --ff-only origin/main
fi
git merge-base --is-ancestor origin/main HEAD
[[ "$(git rev-parse HEAD)" == "$(git rev-parse origin/main)" ]] || { print -u2 "已有未推送提交，停止补更"; exit 1; }
# A fast-forward may have changed report files; gate again before source access.
"$PYTHON" "${SCRIPT_DIR}/refresh_kaipanla_context.py" --docs-dir docs --report-date "$TODAY" --check-ready
git diff --cached --quiet
[[ -z "$(git status --porcelain=v1 --untracked-files=all -- "${TARGETS[@]}")" ]] || exit 1
SOURCE_HEAD=$(git rev-parse HEAD)
ROLLBACK_ACTIVE=0
COMMIT_SHA=""
RESULT=$(/usr/bin/mktemp "${TMPDIR:-/private/tmp}/chanlun-kpl-result.XXXXXXXX")
finish_refresh() {
    local exit_code="$1"
    local retain_receipt=0
    if [[ "$exit_code" -ne 0 && "$ROLLBACK_ACTIVE" == "1" ]]; then
        if [[ -n "$COMMIT_SHA" ]]; then
            retain_receipt=1
            print -u2 "开盘啦资料已提交但尚未推送：pending SHA ${COMMIT_SHA}；main -> origin/main"
            print -u2 "补推命令：git -C '${REPO_DIR}' push origin HEAD:main"
        elif /usr/bin/python3 "${SCRIPT_DIR}/refresh_kaipanla_context.py" \
                --docs-dir docs --report-date "$TODAY" --source-head "$SOURCE_HEAD" \
                --rollback-receipt "$RESULT" >&2; then
            print -u2 "已精确恢复本批未提交的四个补更目标"
        else
            retain_receipt=1
            print -u2 "补更恢复条件不满足或恢复失败，保留现场供复查"
        fi
    fi
    if [[ "$retain_receipt" == "1" ]]; then
        print -u2 "补更receipt：${RESULT}；原HEAD：${SOURCE_HEAD}"
    else
        /bin/rm -f "$RESULT"
    fi
}
trap 'finish_refresh $?' EXIT
"$PYTHON" "${SCRIPT_DIR}/refresh_kaipanla_context.py" --docs-dir docs --report-date "$TODAY" \
    --cache-dir "${REPO_DIR}/.cache/chanlun/kaipanla" > "$RESULT"
/bin/cat "$RESULT"
RESULT_STATUS=$(/usr/bin/python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["status"])' "$RESULT")
[[ "$RESULT_STATUS" == "updated" ]] || exit 0
ROLLBACK_ACTIVE=1
/usr/bin/python3 - "$RESULT" "$SOURCE_HEAD" <<'PY'
import json,sys
from pathlib import Path
path=Path(sys.argv[1]);receipt=json.loads(path.read_bytes())
receipt.update(source_head=sys.argv[2],source_branch='main',target_branch='origin/main')
path.write_text(json.dumps(receipt,ensure_ascii=False))
PY
# Synchronize immediately before commit; a newer remote stops this batch safely.
network_git fetch origin main || exit 1
git merge-base --is-ancestor origin/main HEAD || { print -u2 "补更期间远端 main 已更新，保留本批未提交资料供复查"; exit 1; }
git diff --cached --quiet || { print -u2 "补更期间出现其它暂存内容，停止提交"; exit 1; }
/usr/bin/python3 - "$RESULT" "$TODAY" <<'PY'
import hashlib,json,sys
from pathlib import Path
receipt=json.loads(Path(sys.argv[1]).read_bytes())
day=sys.argv[2]
expected={'data/'+day+'.json','data.json','index.html',day+'/index.html'}
if set(receipt['targets'])!=expected or set(receipt['target_sha256'])!=expected:
    raise SystemExit('supplement target receipt mismatch')
for relative,expected_sha in receipt['target_sha256'].items():
    if hashlib.sha256((Path('docs')/relative).read_bytes()).hexdigest()!=expected_sha:
        raise SystemExit('supplement target changed before staging: '+relative)
PY
git add -- "${TARGETS[@]}"
/usr/bin/python3 - "$RESULT" <<'PY'
import hashlib,json,subprocess,sys
from pathlib import Path
receipt=json.loads(Path(sys.argv[1]).read_bytes())
allowed={'docs/'+relative:sha for relative,sha in receipt['target_sha256'].items()}
staged=subprocess.check_output(['git','diff','--cached','--name-only','-z']).decode().split('\0')
staged=[value for value in staged if value]
if not staged or set(staged)-set(allowed):
    raise SystemExit('unexpected staged publication files')
for relative in staged:
    blob=subprocess.check_output(['git','show',':'+relative])
    if hashlib.sha256(blob).hexdigest()!=allowed[relative]:
        raise SystemExit('staged publication bytes differ: '+relative)
PY
git commit -m "chore: 补更${TODAY}开盘啦题材资料"
COMMIT_SHA=$(git rev-parse HEAD)
network_git push origin HEAD:main || exit 1
