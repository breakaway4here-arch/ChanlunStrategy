#!/bin/zsh
# Install only the new observation label. Never replace an existing LaunchAgent.
set -euo pipefail
SCRIPT_DIR="${0:A:h}"
PRODUCTION_ROOT="/Users/yangfan/yf_source/ChanlunStrategy/.worktrees/production-runtime"
RELEASE_ROOT="${1:-$PRODUCTION_ROOT}"
EXPECTED_COMMIT="${2:-}"
MARKET_DB="${3:-${PRODUCTION_ROOT}/.cache/chanlun/market_history.sqlite}"
LABEL="com.breakaway4here.chanlun-intraday-observation"
ENV_FILE="${CHANLUN_OBSERVATION_ENV_FILE:-${HOME}/.config/chanlun-strategy/preclose.env}"
AGENT_DIR="${HOME}/Library/LaunchAgents"
if [[ "$RELEASE_ROOT" != /* || "$MARKET_DB" != /* || ! -d "$RELEASE_ROOT" || ! -f "$MARKET_DB" ]]; then
  print -u2 "release root and existing market database must be absolute paths"
  exit 1
fi
ACTUAL_COMMIT="$(/usr/bin/git -C "$RELEASE_ROOT" rev-parse --verify HEAD)"
if [[ -n "$EXPECTED_COMMIT" && "$ACTUAL_COMMIT" != "$EXPECTED_COMMIT" ]]; then
  print -u2 "release checkout is not the expected commit"
  exit 1
fi
if [[ -n "$(/usr/bin/git -C "$RELEASE_ROOT" status --porcelain --untracked-files=normal -- . ':(exclude).codegraph/**' ':(exclude).idea/**')" ]]; then
  print -u2 "release checkout must be clean"
  exit 1
fi
for required in intraday_observation_run.py chanlun/intraday_observation_context.py chanlun/intraday_observation_data.py chanlun/intraday_observation_delivery.py scripts/intraday_observation_run.sh; do
  /usr/bin/git -C "$RELEASE_ROOT" ls-files --error-unmatch "$required" >/dev/null
done
TARGET="${AGENT_DIR}/${LABEL}.plist"
if [[ -e "$TARGET" ]]; then
  print -u2 "already exists: ${TARGET}"
  exit 1
fi
/usr/bin/plutil -lint "${RELEASE_ROOT}/launchd/${LABEL}.plist"
cd "$RELEASE_ROOT"
/usr/bin/python3 -c 'import sys; from chanlun.preclose_notify import load_preclose_env; values=load_preclose_env(sys.argv[1]); raise SystemExit(0 if values.get("WXPUSHER_APP_TOKEN") and values.get("WXPUSHER_UID") else 1)' "$ENV_FILE"
/bin/mkdir -p "$AGENT_DIR" "${RELEASE_ROOT}/.cache/chanlun/intraday-observation/logs"
# Render only this new label against the selected clean checkout. O_EXCL keeps
# an existing installation untouched, even if another installer races us.
/usr/bin/python3 - "$RELEASE_ROOT" "$MARKET_DB" "$ENV_FILE" "$TARGET" "$LABEL" <<'PY'
import os
import plistlib
import sys
from pathlib import Path

root, market_db, env_file, target, label = sys.argv[1:]
with (Path(root) / "launchd" / (label + ".plist")).open("rb") as source:
    value = plistlib.load(source)
if value.get("Label") != label or value.get("RunAtLoad") is not False:
    raise SystemExit("invalid observation scheduler template")
value["WorkingDirectory"] = root
value["ProgramArguments"] = ["/bin/zsh", str(Path(root) / "scripts/intraday_observation_run.sh")]
value["EnvironmentVariables"]["CHANLUN_MARKET_HISTORY_DB_PATH"] = market_db
value["EnvironmentVariables"]["CHANLUN_OBSERVATION_ENV_FILE"] = str(Path(env_file).expanduser())
logs = Path(root) / ".cache/chanlun/intraday-observation/logs"
value["StandardOutPath"] = str(logs / "launchd.stdout.log")
value["StandardErrorPath"] = str(logs / "launchd.stderr.log")
descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
with os.fdopen(descriptor, "wb") as output:
    output.write(plistlib.dumps(value))
    output.flush()
    os.fsync(output.fileno())
PY
/bin/launchctl bootstrap "gui/${UID}" "$TARGET"
/bin/launchctl print "gui/${UID}/${LABEL}" | /usr/bin/awk '
  /inherited environment = \{/ { inside = 1; print; next }
  inside && /^[[:space:]]*}/ { inside = 0; print; next }
  inside { sub(/=>.*/, "=> [redacted]"); print; next }
  { print }
'
