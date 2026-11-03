#!/bin/zsh
# Template delivery only in this batch. Run --install only after deployment approval.
set -euo pipefail
LABEL="com.breakaway4here.chanlun-opening-limitup"
RUNTIME="/Users/yangfan/yf_source/ChanlunStrategy/.worktrees/opening-limitup-runtime"
REPO_DIR="${0:A:h:h}"
SOURCE="$RUNTIME/launchd/$LABEL.plist"
TARGET="$HOME/Library/LaunchAgents/$LABEL.plist"
ACTION="${1:---dry-run}"
if [[ "$ACTION" == "--dry-run" ]]; then
  print "仅预览，未安装：周一至周五09:40；休市/过时由CLI守卫；个人微信一次提醒。"
  print "待验收部署后：/bin/zsh $RUNTIME/scripts/opening_limitup_install_launchd.sh --install"
  print "停用：/bin/zsh $RUNTIME/scripts/opening_limitup_install_launchd.sh --uninstall"
  exit 0
fi
if [[ "$REPO_DIR" != "$RUNTIME" ]]; then
  print -u2 "安装/停用只能从已验收的 opening-limitup-runtime 执行，本工作树仅供实现验证。"
  exit 2
fi
case "$ACTION" in
  --install)
    [[ "$(/bin/date +%z)" == "+0800" ]] || { print -u2 "主机时区必须为上海(+0800)"; exit 2; }
    [[ -f "$SOURCE" && -f "$RUNTIME/opening_limitup_run.py" ]] || { print -u2 "缺少已部署文件"; exit 2; }
    /usr/bin/plutil -lint "$SOURCE"
    [[ ! -e "$TARGET" ]] || { print -u2 "已有同名任务，先按验收方案停用后更新"; exit 2; }
    mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
    /bin/cp "$SOURCE" "$TARGET"
    /bin/chmod 600 "$TARGET"
    /bin/launchctl bootstrap "gui/$(/usr/bin/id -u)" "$TARGET"
    print "已安装；RunAtLoad=false，未主动触发/发送。"
    ;;
  --uninstall)
    if [[ -f "$TARGET" ]]; then
      /bin/launchctl bootout "gui/$(/usr/bin/id -u)" "$TARGET"
      /bin/rm "$TARGET"
    fi
    print "已停用本提醒，不改其他任务。"
    ;;
  *) print -u2 "用法：$0 [--dry-run|--install|--uninstall]"; exit 2 ;;
esac
