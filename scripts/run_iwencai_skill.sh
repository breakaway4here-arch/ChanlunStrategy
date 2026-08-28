#!/bin/zsh

set -euo pipefail

readonly profile_path="${IWENCAI_PROFILE:-${HOME}/.zshrc}"
readonly skills_root="${IWENCAI_SKILLS_ROOT:-${CODEX_HOME:-${HOME}/.codex}/skills}"
readonly python_bin="${IWENCAI_PYTHON_BIN:-/usr/bin/python3}"

if [[ -z "${IWENCAI_API_KEY:-}" ]]; then
  if [[ ! -r "${profile_path}" ]]; then
    print -u2 "问财环境配置不可读：${profile_path}"
    exit 2
  fi

  # The profile is only a credential fallback. Optional interactive setup may
  # fail in a non-interactive process; the credential check remains the gate.
  # shellcheck disable=SC1090
  source "${profile_path}" >/dev/null 2>&1 || true
fi

if [[ -z "${IWENCAI_API_KEY:-}" ]]; then
  print -u2 "IWENCAI_API_KEY 未配置"
  exit 2
fi

if (( $# < 1 )); then
  print -u2 "用法：$0 <skill-name> [skill arguments...]"
  exit 2
fi

readonly skill_name="$1"
shift

case "${skill_name}" in
  news-search)
    skill_script="${skills_root}/news-search/scripts/news_search.py"
    ;;
  announcement-search)
    skill_script="${skills_root}/announcement-search/scripts/announcement_search.py"
    ;;
  report-search)
    skill_script="${skills_root}/report-search/scripts/report_search.py"
    ;;
  hithink-event-query|hithink-market-query|hithink-zhishu-query|hithink-industry-query|hithink-sector-selector|hithink-finance-query|hithink-business-query)
    skill_script="${skills_root}/${skill_name}/scripts/cli.py"
    ;;
  *)
    print -u2 "未允许的问财 skill：${skill_name}"
    exit 2
    ;;
esac

if [[ ! -f "${skill_script}" ]]; then
  print -u2 "skill 脚本不存在：${skill_script}"
  exit 2
fi

if [[ ! -x "${python_bin}" ]]; then
  print -u2 "Python 解释器不可执行：${python_bin}"
  exit 2
fi

exec "${python_bin}" "${skill_script}" "$@"
