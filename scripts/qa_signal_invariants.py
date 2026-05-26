#!/usr/bin/env python3
"""QA 层2：静态信号不变量检查。

对生成的 JSON 报告进行结构化检查。

用法:
    python3 scripts/qa_signal_invariants.py docs/data/2026-05-24.json
"""

import json
import sys

ALLOWED_BEST_TYPES = {
    "一买",
    "二买",
    "三买",
    "二买候选",
    "盘整低吸候选",
    "中枢低吸候选",
    "三买候选",
    "底背驰候选",
    "强势启动候选",
}

FORBIDDEN_BEST_TYPES = {
    "类二买",
    "二买待确认",
    "swing底背驰参考",
    "swing底背驰候选种子",
    "中枢震荡低吸参考",
    "盘整背驰参考",
    "三买已错过",
}

FORMAL_BUY_TYPES = {"一买", "二买", "三买"}


def load_report(payload):
    if "reports" not in payload:
        return payload
    latest = payload["dates"][-1]
    return payload["reports"][latest]


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/qa_signal_invariants.py <path_to_json>")
        sys.exit(1)

    path = sys.argv[1]
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    report = load_report(payload)
    errors = []

    for key in ("picks_pure", "picks_fusion"):
        for pick in report.get(key, []):

            # 0. best_buy_point must be in ALLOWED_BEST_TYPES
            best = pick.get("best_buy_point", {})
            best_type = best.get("type", "")
            if best_type in FORBIDDEN_BEST_TYPES:
                errors.append(f"{pick['code']}: best_buy_point={best_type} (forbidden)")
            if best_type and best_type not in ALLOWED_BEST_TYPES:
                errors.append(f"{pick['code']}: best_buy_point={best_type} (not in allowed set {ALLOWED_BEST_TYPES})")

            # 0b. best_buy_point must not be reference or blocked tier
            best_tier = best.get("tier", "")
            if best_tier in ("reference", "blocked"):
                errors.append(f"{pick['code']}: best_buy_point tier={best_tier} (must be formal or candidate)")

            # 1. Every item in buy_points must be in ALLOWED_BEST_TYPES
            for bp in pick.get("buy_points", []):
                bp_type = bp.get("type", "")
                if bp_type in FORBIDDEN_BEST_TYPES:
                    errors.append(f"{pick['code']}: forbidden type {bp_type} in buy_points")
                if bp_type and bp_type not in ALLOWED_BEST_TYPES:
                    errors.append(f"{pick['code']}: unknown type {bp_type} in buy_points (not in allowed set)")

            # 2. Candidate invariants — check ALL candidate buy_points, not just best
            for bp in pick.get("buy_points", []):
                bp_type = bp.get("type", "")
                if bp.get("tier") == "candidate" or bp_type.endswith("候选"):
                    if not bp.get("source_type"):
                        errors.append(f"{pick['code']}: candidate {bp_type} missing source_type")
                    if not bp.get("confirmed_by"):
                        errors.append(f"{pick['code']}: candidate {bp_type} missing confirmed_by")
                    confirmations = bp.get("confirmations", [])
                    if not confirmations:
                        errors.append(f"{pick['code']}: candidate {bp_type} has empty confirmations")
                    if not bp.get("strength"):
                        errors.append(f"{pick['code']}: candidate {bp_type} missing strength")

                    # source_type mapping
                    src = bp.get("source_type", "")
                    expected_map = {
                        "二买候选": "二买待确认",
                        "盘整低吸候选": "盘整背驰参考",
                        "中枢低吸候选": "中枢震荡低吸参考",
                        "三买候选": "三买待确认",
                        "底背驰候选": "swing底背驰参考",
                    }
                    if bp_type in expected_map and src != expected_map[bp_type]:
                        errors.append(f"{pick['code']}: {bp_type}.source_type={src}, expected={expected_map[bp_type]}")

                    # 底背驰候选 specific checks
                    if bp_type == "底背驰候选":
                        if bp.get("seed_type") != "swing底背驰候选种子":
                            errors.append(f"{pick['code']}: 底背驰候选 seed_type={bp.get('seed_type')}, expected=swing底背驰候选种子")
                        if not bp.get("seed_reason"):
                            errors.append(f"{pick['code']}: 底背驰候选 missing seed_reason")

            # 3. Check all buy_points for structural invariants
            for bp in pick.get("buy_points", []):
                bp_type = bp.get("type", "")

                # 无中枢时不能有三买/三买候选
                if pick.get("trend_type") == "无中枢" and bp_type in ("三买", "三买候选"):
                    errors.append(f"{pick['code']}: {bp_type} but trend_type=无中枢")

                # 不能有类二买
                if bp_type == "类二买":
                    errors.append(f"{pick['code']}: 类二买 in buy_points")

                # 三买不能有已涨警告
                if bp_type == "三买" and "已涨" in bp.get("reason", ""):
                    errors.append(f"{pick['code']}: 三买 with 已涨 warning")

                # 不能有禁止类型出现在 buy_points 中
                if bp_type in FORBIDDEN_BEST_TYPES:
                    errors.append(f"{pick['code']}: forbidden type {bp_type} in buy_points")

            # 4. 二买.index > 一买.index
            firsts = [bp for bp in pick.get("buy_points", []) if bp["type"] == "一买"]
            seconds = [bp for bp in pick.get("buy_points", []) if bp["type"] == "二买"]
            for first in firsts:
                for second in seconds:
                    fi = first.get("index", 0)
                    si = second.get("index", 0)
                    if si is not None and fi is not None and si <= fi:
                        errors.append(f"{pick['code']}: 二买.index={si} <= 一买.index={fi}")

            # 5. swing底背驰参考 alone must never become best
            if best_type == "swing底背驰参考":
                errors.append(f"{pick['code']}: swing底背驰参考 is best_buy_point")

            # 6. 三买/三买候选 must not appear when daily pivot count is zero
            pivot_count = pick.get("pivots", {}).get("count", 0)
            if best_type in ("三买", "三买候选") and pivot_count == 0:
                errors.append(f"{pick['code']}: {best_type} but pivot count is 0")

    # 7. Diagnostics checks
    diag = report.get("diagnostics", {})
    if diag:
        upgrade_pure = diag.get("sublevel_upgrade_pure", {})
        upgrade_fusion = diag.get("sublevel_upgrade_fusion", {})
        for label, ud in [("pure", upgrade_pure), ("fusion", upgrade_fusion)]:
            if ud.get("candidate_upgraded", 0) > 0:
                if ud.get("requested_30min", 0) == 0:
                    errors.append(f"diagnostics: {label} candidate_upgraded>0 but requested_30min=0")
                if ud.get("fetched_30min", 0) == 0:
                    errors.append(f"diagnostics: {label} candidate_upgraded>0 but fetched_30min=0")

    if errors:
        print("FAIL:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    else:
        print("PASS: all signal invariants satisfied")


if __name__ == "__main__":
    main()
