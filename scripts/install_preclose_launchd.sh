#!/bin/zsh
# Install the two independent pre-close LaunchAgents without overwriting.

set -euo pipefail

SCRIPT_DIR="${0:A:h}"
REPO_DIR="${SCRIPT_DIR:h}"
PRODUCTION_ROOT="/Users/yangfan/yf_source/ChanlunStrategy/.worktrees/production-runtime"
TEMPLATE_DIR="${REPO_DIR}/launchd"
AGENT_DIR="${HOME}/Library/LaunchAgents"
ENV_FILE="${CHANLUN_PRECLOSE_ENV_FILE:-${HOME}/.config/chanlun-strategy/preclose.env}"
DOMAIN="gui/${UID}"
LABELS=(
  com.breakaway4here.chanlun-preclose
  com.breakaway4here.chanlun-preclose-reconcile
)

sanitize_launchctl_print() {
  /bin/launchctl print "$1" | /usr/bin/awk '
    /inherited environment = \{/ { inside = 1; print; next }
    inside && /^[[:space:]]*}/ { inside = 0; print; next }
    inside { sub(/=>.*/, "=> [redacted]"); print; next }
    { print }
  '
}

if [[ "$REPO_DIR" != "$PRODUCTION_ROOT" ]]; then
  print -u2 "installer must run from the production checkout"
  exit 1
fi

for label in "${LABELS[@]}"; do
  /usr/bin/plutil -lint "${TEMPLATE_DIR}/${label}.plist"
done

/usr/bin/python3 -c \
  'import sys; from chanlun.preclose_notify import load_preclose_env; values=load_preclose_env(sys.argv[1]); required=("PRECLOSE_API_BASE","PRECLOSE_WRITE_TOKEN","WXPUSHER_APP_TOKEN","WXPUSHER_UID"); raise SystemExit(0 if all(values.get(key) for key in required) else 1)' \
  "$ENV_FILE"

/bin/mkdir -p "$AGENT_DIR" "${REPO_DIR}/.cache/chanlun/preclose/logs"
for label in "${LABELS[@]}"; do
  target="${AGENT_DIR}/${label}.plist"
  if [[ -e "$target" ]]; then
    print -u2 "already exists: ${target}"
    exit 1
  fi
done

for label in "${LABELS[@]}"; do
  /bin/cp "${TEMPLATE_DIR}/${label}.plist" "${AGENT_DIR}/${label}.plist"
  /bin/chmod 600 "${AGENT_DIR}/${label}.plist"
  /bin/launchctl bootstrap "$DOMAIN" "${AGENT_DIR}/${label}.plist"
  sanitize_launchctl_print "${DOMAIN}/${label}"
done
