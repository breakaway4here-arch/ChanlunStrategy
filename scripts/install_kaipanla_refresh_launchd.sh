#!/bin/zsh
# Install only this finite late supplement job; do not trigger it at installation.
set -euo pipefail
SCRIPT_DIR="${0:A:h}"
REPO_DIR="${SCRIPT_DIR:h}"
RUNTIME_ROOT="/Users/yangfan/yf_source/ChanlunStrategy/.worktrees/production-runtime"
LABEL="com.breakaway4here.chanlun-kaipanla-refresh"
TEMPLATE="${REPO_DIR}/launchd/${LABEL}.plist"
TARGET="${HOME}/Library/LaunchAgents/${LABEL}.plist"
DOMAIN="gui/${UID}"
[[ "$REPO_DIR" == "$RUNTIME_ROOT" ]] || { print -u2 "installer must run from the production checkout"; exit 1; }
/usr/bin/plutil -lint "$TEMPLATE"
[[ ! -e "$TARGET" ]] || { print -u2 "already exists: ${TARGET}"; exit 1; }
/bin/mkdir -p "${HOME}/Library/LaunchAgents" "${REPO_DIR}/.cache/chanlun/kaipanla/logs"
/bin/cp "$TEMPLATE" "$TARGET"
/bin/chmod 600 "$TARGET"
if ! /bin/launchctl bootstrap "$DOMAIN" "$TARGET"; then
    /bin/rm -f "$TARGET"
    exit 1
fi
/bin/launchctl print "${DOMAIN}/${LABEL}" | /usr/bin/awk '
    /inherited environment = \{/ { inside = 1; print; next }
    inside && /^[[:space:]]*}/ { inside = 0; print; next }
    inside { sub(/=>.*/, "=> [redacted]"); print; next }
    { print }
'
