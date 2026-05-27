#!/usr/bin/env python3
"""QA 影子统计：强势启动候选 30min 确认等级分布。

用法:
    python3 scripts/qa_startup_confirm_grades.py docs/data/2026-05-27.json
"""

import json
import sys


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/qa_startup_confirm_grades.py <path_to_json>")
        sys.exit(1)

    path = sys.argv[1]
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    # Support both direct and reports-indexed formats
    if "reports" in payload:
        latest = payload["dates"][-1]
        report = payload["reports"][latest]
    else:
        report = payload

    grades = {"S": 0, "A": 0, "B": 0, "C": 0}
    daily_grades = {"strong": 0, "weak": 0, "pullback": 0}
    total = 0

    for key in ("picks_pure", "picks_fusion"):
        for pick in report.get(key, []):
            bp = pick.get("best_buy_point", {})
            if bp.get("type") != "强势启动候选":
                continue
            total += 1
            g = bp.get("sublevel_confirm_grade", "?")
            grades[g] = grades.get(g, 0) + 1
            dg = bp.get("daily_startup_grade", "?")
            daily_grades[dg] = daily_grades.get(dg, 0) + 1

    print(f"total startup candidates: {total}")
    print(f"Daily grades: strong={daily_grades.get('strong', 0)}, "
          f"weak={daily_grades.get('weak', 0)}, pullback={daily_grades.get('pullback', 0)}")
    print(f"Sublevel confirm: S={grades.get('S', 0)}, A={grades.get('A', 0)}, "
          f"B={grades.get('B', 0)}, C={grades.get('C', 0)}")

    # 模拟收紧后的结果
    would_keep_buy23 = grades.get("S", 0)
    would_keep_hard = grades.get("S", 0) + grades.get("A", 0)  # S+A
    print(f"\nShadow QA:")
    print(f"  would_keep_if_require_buy23: {would_keep_buy23}")
    print(f"  would_keep_if_require_daily_hard_plus_any_confirm (S+A): {would_keep_hard}")


if __name__ == "__main__":
    main()
