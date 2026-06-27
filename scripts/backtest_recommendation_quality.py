"""
最小回测：用历史推荐快照评估"推荐后 1-3 日表现"基线。

输入：docs/data/YYYY-MM-DD.json（每天的 picks_pure / picks_fusion）
输出：按 tier / strength / best_buy_point.type 分组的 T+1/T+3 涨跌、命中率、最大回撤

执行入口：python3 scripts/backtest_recommendation_quality.py
"""

import json
import os
import sys
from collections import defaultdict

# Make 'chanlun' import work when running from chanlun_strategy/
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from config import DAY_LOOKBACK
from chanlun.data_fetcher import fetch_daily_kline  # noqa: E402
from chanlun.backtest_metrics import summarize_return_samples  # noqa: E402
from chanlun.backtest_execution import evaluate_forward_returns  # noqa: E402


DATA_DIR = os.path.join(ROOT, "docs", "data")
SNAPSHOT_DAYS = sorted(
    f for f in os.listdir(DATA_DIR)
    if f.endswith(".json") and f[0].isdigit() and "_" not in f
)


def iter_snapshot_picks():
    """Yield (snapshot_date, version, pick) for every recommendation found."""
    for fname in SNAPSHOT_DAYS:
        path = os.path.join(DATA_DIR, fname)
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        snap_date = data["date"]
        for ver in ("picks_pure", "picks_fusion"):
            for pick in (data.get(ver) or []):
                yield snap_date, ver, pick


def daily_kline_after(code, snap_date, horizon=5):
    """Fetch a kline slice that should include snap_date and at least `horizon` bars after."""
    k = fetch_daily_kline(code, count=DAY_LOOKBACK)
    if not k:
        return None
    dates = list(k["dates"])
    if str(snap_date) not in [str(d).split(" ")[0] for d in dates]:
        return None
    return {
        "dates": [str(d).split(" ")[0] for d in dates],
        "opens": [float(x) for x in k["opens"]],
        "highs": [float(x) for x in k["highs"]],
        "lows": [float(x) for x in k["lows"]],
        "closes": [float(x) for x in k["closes"]],
    }


def evaluate(pick, snap_date):
    """Compute returns relative to recommendation-day close (legacy behavior)."""
    kline = daily_kline_after(pick["code"], snap_date, horizon=5)
    if not kline:
        return None

    return evaluate_forward_returns(
        kline,
        snap_date,
        entry_mode="immediate_close",
        horizon=5,
    )


def bucket_key(pick):
    bbp = pick.get("best_buy_point") or {}
    return (
        pick.get("signal_tier") or "?",
        bbp.get("strength") or "?",
        bbp.get("type") or "?",
    )


def confirm_combo_key(pick):
    bbp = pick.get("best_buy_point") or {}
    sigs = tuple(sorted(bbp.get("confirmations") or []))
    return (bbp.get("type") or "?", sigs or ("<none>",))


def distance_bucket(pick):
    bbp = pick.get("best_buy_point") or {}
    d = bbp.get("distance_from_reference_pct")
    if d is None:
        return "?"
    d = float(d)
    if d <= 3:
        return "0-3%"
    if d <= 6:
        return "3-6%"
    if d <= 10:
        return "6-10%"
    return ">10%"


def summarize(samples):
    """Backward-compatible wrapper for existing callers."""
    return summarize_return_samples(samples)


def main():
    print(f"Scanning {len(SNAPSHOT_DAYS)} snapshot days: {SNAPSHOT_DAYS}")
    buckets = defaultdict(list)
    overall = defaultdict(list)  # by version
    combo_buckets = defaultdict(list)   # (ver, type, signals)
    dist_buckets = defaultdict(list)    # (ver, type, dist_bucket)
    skipped_no_kline = 0
    seen = 0

    for snap_date, ver, pick in iter_snapshot_picks():
        seen += 1
        res = evaluate(pick, snap_date)
        if res is None:
            skipped_no_kline += 1
            continue
        key = (ver,) + bucket_key(pick)
        buckets[key].append(res)
        overall[ver].append(res)
        ct, sigs = confirm_combo_key(pick)
        combo_buckets[(ver, ct, sigs)].append(res)
        dist_buckets[(ver, ct, distance_bucket(pick))].append(res)

    print(f"Total picks scanned: {seen}, evaluated: {seen - skipped_no_kline}, "
          f"skipped (no kline cover): {skipped_no_kline}")
    print()

    for ver in ("picks_pure", "picks_fusion"):
        s = summarize(overall[ver])
        print(f"=== Overall [{ver}] ===")
        print(json.dumps(s, ensure_ascii=False, indent=2))
        print()

    print("=== By (version, tier, strength, type) ===")
    rows = []
    for key, samples in buckets.items():
        s = summarize(samples)
        if not s:
            continue
        rows.append((key, s))
    rows.sort(key=lambda x: (x[0][0], -x[1]["n"]))
    for (ver, tier, strength, btype), s in rows:
        print(f"  [{ver}] tier={tier} strength={strength} type={btype}")
        print(f"    n={s['n']} t1_mean={s['t1_mean']} t3_mean={s['t3_mean']} "
              f"win_rate={s['t3_win_rate']}% loss5%={s['t3_loss_5pct_rate']}% "
              f"max_up_mean={s['max_up_3d_mean']} max_dd_mean={s['max_dd_3d_mean']}")

    print()
    print("=== By confirmations combo (n>=10 only) ===")
    combo_rows = []
    for key, samples in combo_buckets.items():
        if len(samples) < 10:
            continue
        s = summarize(samples)
        combo_rows.append((key, s))
    combo_rows.sort(key=lambda x: (x[0][0], x[0][1], x[1]["t3_win_rate"] or 0))
    for (ver, btype, sigs), s in combo_rows:
        sig_str = "+".join(sigs) if sigs else "<none>"
        print(f"  [{ver}] type={btype} signals={sig_str}")
        print(f"    n={s['n']} t3_mean={s['t3_mean']} win={s['t3_win_rate']}% "
              f"loss5%={s['t3_loss_5pct_rate']}% dd_mean={s['max_dd_3d_mean']}")

    print()
    print("=== By distance_from_reference_pct bucket (n>=15 only) ===")
    dist_rows = []
    for key, samples in dist_buckets.items():
        if len(samples) < 15:
            continue
        s = summarize(samples)
        dist_rows.append((key, s))
    dist_rows.sort(key=lambda x: (x[0][0], x[0][1], x[0][2]))
    for (ver, btype, dbucket), s in dist_rows:
        print(f"  [{ver}] type={btype} dist={dbucket}")
        print(f"    n={s['n']} t3_mean={s['t3_mean']} win={s['t3_win_rate']}% "
              f"loss5%={s['t3_loss_5pct_rate']}% dd_mean={s['max_dd_3d_mean']}")


if __name__ == "__main__":
    main()
