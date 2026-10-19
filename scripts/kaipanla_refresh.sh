#!/bin/zsh
# Finite late optional supplement opportunities; share the publisher's lock.
set -euo pipefail
SCRIPT_DIR="${0:A:h}"
REPO_DIR="${SCRIPT_DIR:h}"
PYTHON="${CHANLUN_KPL_PYTHON:-/usr/bin/python3}"
RECOVER_ONLY=0
if [[ "$#" -gt 0 ]]; then
    [[ "$#" == 1 && "$1" == --recover-pending-only ]] || { print -u2 "未知补更参数"; exit 2; }
    RECOVER_ONLY=1
fi
TODAY=$(TZ=Asia/Shanghai /bin/date '+%Y-%m-%d')
PENDING_RECEIPT="${REPO_DIR}/.cache/chanlun/kaipanla/publication-${TODAY}.json"
PENDING_FILES=("${REPO_DIR}/.cache/chanlun/kaipanla"/publication-*.json(N))
# No receipt means no recovery I/O, including no readiness or network request.
if [[ "$RECOVER_ONLY" == 1 && "${#PENDING_FILES}" == 0 ]]; then
    exit 0
fi
if [[ "${#PENDING_FILES}" -gt 0 && ( "${#PENDING_FILES}" != 1 || "${PENDING_FILES[1]}" != "$PENDING_RECEIPT" ) ]]; then
    print -u2 "存在非本日或多个开盘啦 pending receipt，停止并等待复查"
    exit 1
fi
LOCK_PATH=$(/usr/bin/python3 -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve())' "${REPO_DIR}/.cache/chanlun/docs-publish.lock")
if [[ "${CHANLUN_DOCS_PUBLISH_LOCK_HELD:-0}" != "1" || "${CHANLUN_DOCS_PUBLISH_LOCK_PATH:-}" != "$LOCK_PATH" ]] \
        || ! /usr/bin/python3 "${SCRIPT_DIR}/refresh_kaipanla_context.py" --docs-dir "${REPO_DIR}/docs" --check-lock; then
    export CHANLUN_DOCS_PUBLISH_LOCK_PATH="$LOCK_PATH"
    exec /usr/bin/python3 "${SCRIPT_DIR}/refresh_kaipanla_context.py" \
        --docs-dir "${REPO_DIR}/docs" --lock-timeout 20 \
        --with-lock /bin/zsh "$0" "$@"
fi
cd "$REPO_DIR"
WEEKDAY=$(TZ=Asia/Shanghai /bin/date '+%u')
[[ "$WEEKDAY" -le 5 ]] || exit 0
# A holiday/missing/unofficial report never triggers the optional source request.
if ! "$PYTHON" "${SCRIPT_DIR}/refresh_kaipanla_context.py" --docs-dir docs --report-date "$TODAY" --check-ready; then
    if [[ "${#PENDING_FILES}" -gt 0 ]]; then
        print -u2 "pending 补更目标未就绪，禁止继续通用发布"
        exit 1
    fi
    print -u2 "今日正式收盘报告未就绪，跳过开盘啦补更"
    exit 0
fi
[[ "$(git branch --show-current)" == "main" ]] || { print -u2 "补更发布要求 main 分支"; exit 1; }
TARGETS=("docs/data/${TODAY}.json" "docs/data.json" "docs/index.html" "docs/${TODAY}/index.html")
# Keep unrelated working files, but never combine another task's index/targets.
git diff --cached --quiet || { print -u2 "已有暂存改动，停止补更"; exit 1; }
[[ -z "$(git status --porcelain=v1 --untracked-files=all -- "${TARGETS[@]}")" ]] || { print -u2 "补更目标已有改动，停止补更"; exit 1; }

network_git() {
    /usr/bin/python3 "${SCRIPT_DIR}/run_daily_git_network.py" "$@" --timeout-seconds 30
}
validate_pending() {
    # A receipt proves this exact single supplement commit, never arbitrary ahead work.
    /usr/bin/python3 - "$PENDING_RECEIPT" "$TODAY" "$REPO_DIR" <<'PY'
import hashlib,json,re,subprocess,sys
from pathlib import Path
path=Path(sys.argv[1]);day=sys.argv[2];root=Path(sys.argv[3]).resolve()
if path.is_symlink(): raise SystemExit('pending receipt must not be a symlink')
receipt=json.loads(path.read_bytes())
def git(*args): return subprocess.check_output(['git',*args]).decode().strip()
expected={'data/'+day+'.json','data.json','index.html',day+'/index.html'}
if (subprocess.run(['git','diff','--cached','--quiet']).returncode
    or git('status','--porcelain=v1','--untracked-files=all','--',*['docs/'+r for r in sorted(expected)])):
    raise SystemExit('pending supplement index/targets changed')
commit=receipt.get('commit_sha','');source=receipt.get('source_head','')
if (receipt.get('status')!='updated' or receipt.get('report_date')!=day
    or receipt.get('source_branch')!='main' or receipt.get('target_branch')!='origin/main'
    or receipt.get('repository')!=str(root)
    or receipt.get('origin_url_sha256')!=hashlib.sha256(git('remote','get-url','origin').encode()).hexdigest()
    or set(receipt.get('targets',[]))!=expected or set(receipt.get('target_sha256',{}))!=expected
    or not re.fullmatch('[0-9a-f]{40}',commit) or not re.fullmatch('[0-9a-f]{40}',source)
    or git('rev-parse','HEAD')!=commit or git('rev-list','--parents','-n','1',commit).split()!=[commit,source]
    or git('log','-1','--format=%s',commit)!='chore: 补更'+day+'开盘啦题材资料'):
    raise SystemExit('pending supplement identity/ancestry mismatch')
changed=set(git('diff-tree','--no-commit-id','--name-only','-r',commit).splitlines())
if not changed or changed-{'docs/'+relative for relative in expected}:
    raise SystemExit('pending commit contains non-supplement files')
for relative,sha in receipt['target_sha256'].items():
    target=root/'docs'/relative
    blob=subprocess.check_output(['git','show',commit+':docs/'+relative])
    if (target.is_symlink() or not re.fullmatch('[0-9a-f]{64}',str(sha))
        or hashlib.sha256(target.read_bytes()).hexdigest()!=sha or hashlib.sha256(blob).hexdigest()!=sha):
        raise SystemExit('pending supplement bytes changed: '+relative)
remote=git('rev-parse','origin/main')
if subprocess.run(['git','merge-base','--is-ancestor',commit,'origin/main']).returncode==0:
    print('remote_contains '+commit)
elif remote==source:
    print('pending '+commit)
else:
    raise SystemExit('remote main changed; pending supplement requires review')
PY
}
network_git fetch || exit 1
if [[ -e "$PENDING_RECEIPT" || -L "$PENDING_RECEIPT" ]]; then
    PENDING_STATE=$(validate_pending) || exit 1
    PENDING_SHA="${PENDING_STATE##* }"
    if [[ "$PENDING_STATE" == pending\ * ]]; then
        # Pin the validated SHA so a concurrent HEAD change cannot publish another commit.
        network_git push --push-ref "${PENDING_SHA}:refs/heads/main" || exit 1
    fi
    /bin/rm -f "$PENDING_RECEIPT"
    print "开盘啦本批提交已确认发布：${PENDING_SHA}"
    exit 0
fi
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
SOURCE_ORIGIN_URL=$(git remote get-url origin)
ROLLBACK_ACTIVE=0
COMMIT_SHA=""
RESULT=$(/usr/bin/mktemp "${TMPDIR:-/private/tmp}/chanlun-kpl-result.XXXXXXXX")
finish_refresh() {
    local exit_code="$1"
    local retain_receipt=0
    if [[ "$exit_code" -ne 0 && "$ROLLBACK_ACTIVE" == "1" ]]; then
        if [[ -n "$COMMIT_SHA" ]]; then
            retain_receipt=1
            if [[ -f "$PENDING_RECEIPT" && ! -L "$PENDING_RECEIPT" ]]; then
                /bin/rm -f "$RESULT"
                RESULT="$PENDING_RECEIPT"
            fi
            print -u2 "开盘啦提交交付尚未确认：pending SHA ${COMMIT_SHA}；main -> origin/main"
            print -u2 "续推入口：/bin/zsh '${SCRIPT_DIR}/kaipanla_refresh.sh'（重新核验 receipt）"
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
network_git fetch || exit 1
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
/usr/bin/python3 - "$RESULT" "$PENDING_RECEIPT" "$COMMIT_SHA" "$REPO_DIR" "$SOURCE_ORIGIN_URL" <<'PY'
import hashlib,json,os,sys,tempfile
from pathlib import Path
receipt=json.loads(Path(sys.argv[1]).read_bytes())
receipt.update(commit_sha=sys.argv[3],repository=str(Path(sys.argv[4]).resolve()),
               origin_url_sha256=hashlib.sha256(sys.argv[5].encode()).hexdigest())
target=Path(sys.argv[2]);target.parent.mkdir(parents=True,exist_ok=True)
fd,temporary=tempfile.mkstemp(prefix=target.name+'.',dir=str(target.parent))
try:
    with os.fdopen(fd,'w') as stream:
        json.dump(receipt,stream,ensure_ascii=False);stream.flush();os.fsync(stream.fileno())
    os.replace(temporary,target)
finally:
    if os.path.exists(temporary): os.unlink(temporary)
PY
validate_pending >/dev/null || exit 1
network_git push --push-ref "${COMMIT_SHA}:refs/heads/main" || exit 1
/bin/rm -f "$PENDING_RECEIPT"
