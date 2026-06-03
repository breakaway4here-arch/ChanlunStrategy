"""
模拟 P0+P1 过滤效果（不重跑流水线，纯统计）。

P0: fusion + 底背驰候选 + distance_from_reference_pct > 3% → 剔除
P1: confirmations 仅靠 'EMA5收复+止跌结构'（且无 '关键位不破'）→ 剔除

实际线上 P1 改了 sublevel_confirm 后这种组合不会进入推荐；
回测里我们筛掉它来模拟新规则下的 fusion 整体表现。
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from backtest_recommendation_quality import (  # noqa: E402
    iter_snapshot_picks, evaluate, summarize,
)


def p0_drops(ver, pick):
    """B 方案：所有底背驰候选距源价 >3% 都过滤（不分 pure / fusion）。"""
    bbp = pick.get("best_buy_point") or {}
    if bbp.get("type") != "底背驰候选":
        return False
    dist = bbp.get("distance_from_reference_pct")
    return dist is not None and float(dist) > 3


def p1_drops(pick):
    """P1: 删 (stop_fall_bars + ema5_reclaim) 这条升中分支。
    线上 confirmations 命名: '止跌结构' + 'EMA5收复'，且不含 '关键位不破' 和 '30min底分型'
    （否则其他分支已能升中）。"""
    bbp = pick.get("best_buy_point") or {}
    sigs = set(bbp.get("confirmations") or [])
    if "止跌结构" not in sigs or "EMA5收复" not in sigs:
        return False
    # 如果还含'关键位不破'，则 (key_level_ok and ema5_reclaim) 分支仍升中 → 不会被 P1 砍掉
    if "关键位不破" in sigs:
        return False
    # 含 30min底分型+MACD 则 has_fractal_macd 升中 → 也不会被 P1 砍
    if "30min底分型" in sigs:
        return False
    return True


def main():
    kept_fusion = []
    dropped_p0 = []
    dropped_p1 = []
    all_fusion = []
    kept_pure = []
    dropped_pure_p1 = []  # 这里其实是 pure 路径下 P0+P1 砍掉的集合
    all_pure = []

    for snap_date, ver, pick in iter_snapshot_picks():
        res = evaluate(pick, snap_date)
        if res is None:
            continue

        if ver == "picks_fusion":
            all_fusion.append(res)
            if p0_drops(ver, pick):
                dropped_p0.append(res)
                continue
            if p1_drops(pick):
                dropped_p1.append(res)
                continue
            kept_fusion.append(res)
        elif ver == "picks_pure":
            all_pure.append(res)
            if p0_drops(ver, pick) or p1_drops(pick):
                dropped_pure_p1.append(res)
            else:
                kept_pure.append(res)

    print("=== Fusion: 改前（基线）===")
    print(summarize(all_fusion))
    print()
    print(f"=== Fusion: P0 砍掉 (底背驰候选, dist>3%) ===")
    print(f"n={len(dropped_p0)}")
    print(summarize(dropped_p0))
    print()
    print(f"=== Fusion: P1 砍掉 (止跌+EMA5 单独升中) ===")
    print(f"n={len(dropped_p1)}")
    print(summarize(dropped_p1))
    print()
    print(f"=== Fusion: 改后（保留 {len(kept_fusion)}/{len(all_fusion)}）===")
    print(summarize(kept_fusion))
    print()
    print("=== Pure: 改前（基线）===")
    print(summarize(all_pure))
    print()
    print(f"=== Pure: 砍掉 (P0+P1 合计) ===")
    print(f"n={len(dropped_pure_p1)}")
    print(summarize(dropped_pure_p1))
    print()
    print(f"=== Pure: 改后（保留 {len(kept_pure)}/{len(all_pure)}）===")
    print(summarize(kept_pure))


if __name__ == "__main__":
    main()
