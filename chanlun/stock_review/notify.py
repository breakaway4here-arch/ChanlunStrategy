"""Notification interface for stock review.

Generates summary text from review results. First version only implements
summary generation and a no-op notifier. External webhook channels
(WeChat Work, Feishu, email, etc.) are reserved for future implementation.
"""
from .rule_action import ACTION_PRIORITY


def generate_summary(review_results, report_url=""):
    """Generate a brief summary text from review results.

    High-risk stocks are listed first. Includes counts and report URL.

    Args:
        review_results: list of result dicts from the review pipeline
        report_url: optional URL to the full HTML report

    Returns:
        str: summary text suitable for push notification
    """
    if not review_results:
        return "今日持仓鉴股：无持仓数据"

    # Categorize
    high_risk = []
    watch = []
    hold = []
    add_confirm = []
    other = []

    for r in review_results:
        name = r.get("holding", {}).get("name", "")
        action = r.get("rule_action", {}).get("action", "HOLD")
        reason = r.get("rule_action", {}).get("primary_reason", "")

        entry = f"{name}({action})"
        if action == "STOP":
            high_risk.append(entry)
        elif action == "REDUCE":
            high_risk.append(entry)
        elif action == "WATCH":
            watch.append(entry)
        elif action == "ADD_ON_CONFIRM":
            add_confirm.append(entry)
        elif action == "HOLD":
            hold.append(entry)
        else:
            other.append(entry)

    lines = ["今日持仓鉴股："]

    if high_risk:
        lines.append(f"高风险 {len(high_risk)} 只：{' / '.join(high_risk)}")

    if watch:
        lines.append(f"需关注 {len(watch)} 只")

    if hold:
        lines.append(f"可继续持有 {len(hold)} 只")

    if add_confirm:
        lines.append(f"等待加仓确认 {len(add_confirm)} 只")

    if other:
        lines.append(f"其他 {len(other)} 只")

    if report_url:
        lines.append(f"报告地址：{report_url}")

    return "\n".join(lines)


class NoOpNotifier:
    """No-op notifier that does nothing.

    Future: replace with WeChatWorkNotifier, FeishuNotifier, EmailNotifier, etc.
    """

    def is_configured(self):
        return False

    def send(self, message):
        """Send notification. Currently a no-op."""
        pass
