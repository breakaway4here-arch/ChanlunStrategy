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
from chanlun.backtest_execution import (  # noqa: E402
    evaluate_forward_returns,
    execute_signal,
)
from chanlun.signal_quality_classifier import build_signal_context  # noqa: E402


DATA_DIR = os.path.join(ROOT, "docs", "data")
SIGNAL_DIR = os.path.join(DATA_DIR, "signals")
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


def _to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_list(values):
    if values is None:
        return []
    return list(values)


def build_signal_snapshot_record(pick, snap_date, source_view):
    """Build a minimal, schema-only signal snapshot row from one pick."""
    if not isinstance(pick, dict):
        return None
    code = pick.get("code")
    if not code:
        return None

    bbp = pick.get("best_buy_point") if isinstance(pick.get("best_buy_point"), dict) else {}
    ref_price = pick.get("ref_price")
    if ref_price is None:
        ref_price = pick.get("reference_price")
    if ref_price is None:
        ref_price = pick.get("current_price")
    if ref_price is None:
        ref_price = bbp.get("reference_price")
    if ref_price is None:
        ref_price = bbp.get("current_price")

    opportunity_score = pick.get("opportunity_score")
    if opportunity_score is None:
        opportunity_score = pick.get("watch_score")
    if opportunity_score is None:
        opportunity_score = pick.get("score")

    return {
        "code": str(code),
        "date": str(snap_date),
        "source_view": str(source_view),
        "opportunity_score": _to_float(opportunity_score),
        "ref_price": _to_float(ref_price),
    }


def iter_signal_records_from_report(data, source_view=None):
    """Yield normalized signal snapshot rows from one report payload.

    Prefer workspace view rows because they contain opportunity_score and the
    user-facing source_view. Fall back to raw pools for older snapshots.
    """
    snap_date = data.get("date")
    if snap_date is None:
        return []

    workspace_views = data.get("workspace", {}).get("views", {}) if isinstance(data.get("workspace"), dict) else {}
    if isinstance(workspace_views, dict) and workspace_views:
        view_names = [source_view] if source_view else ["main", "acceleration", "luojie", "confirming", "baseline"]
        rows = []
        for view_name in view_names:
            for pick in (workspace_views.get(view_name) or []):
                row = build_signal_snapshot_record(pick, snap_date, view_name)
                if row is not None:
                    rows.append(row)
        return rows

    raw_source_map = {
        "picks_fusion": "main",
        "picks_pure": "baseline",
    }
    source_keys = [source_view] if source_view else list(raw_source_map)
    rows = []
    for source_key in source_keys:
        output_view = raw_source_map.get(source_key, source_key)
        for pick in (data.get(source_key) or []):
            row = build_signal_snapshot_record(pick, snap_date, output_view)
            if row is not None:
                rows.append(row)
    return rows


def _pick_local_kline(pick):
    if not isinstance(pick, dict):
        return None
    dates = pick.get("dates")
    opens = pick.get("opens")
    highs = pick.get("highs")
    lows = pick.get("lows")
    closes = pick.get("closes")
    if not (dates and opens and highs and lows and closes):
        return None

    try:
        return {
            "dates": [str(d).split(" ")[0] for d in _as_list(dates)],
            "opens": [float(x) for x in _as_list(opens)],
            "highs": [float(x) for x in _as_list(highs)],
            "lows": [float(x) for x in _as_list(lows)],
            "closes": [float(x) for x in _as_list(closes)],
        }
    except (TypeError, ValueError):
        return None


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
    """Compute returns for one pick.

    1) 优先使用快照内嵌的K线（无网）；
    2) 回退到 `fetch_daily_kline`（兼容历史场景）。
    """
    kline = _pick_local_kline(pick)
    if kline is None:
        kline = daily_kline_after(pick.get("code"), snap_date, horizon=5)
    if not kline:
        return None

    return evaluate_forward_returns(
        kline,
        snap_date,
        entry_mode="immediate_close",
        horizon=5,
    )


def build_signal_snapshot_payload(data, source_view):
    """Build minimal payload for one report payload."""
    return {
        "date": data.get("date"),
        "signal_records": iter_signal_records_from_report(data, source_view),
    }


def write_signal_snapshot_files(output_dir=SIGNAL_DIR):
    """Write `docs/data/signals/YYYY-MM-DD.json` for every daily report.

    Returns:
        list[str]: written output paths.
    """
    os.makedirs(output_dir, exist_ok=True)
    written_paths = []

    for fname in SNAPSHOT_DAYS:
        path = os.path.join(DATA_DIR, fname)
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        snap_date = data.get("date")
        if not snap_date:
            continue

        payloads = iter_signal_records_from_report(data)
        output_path = os.path.join(output_dir, f"{snap_date}.json")
        with open(output_path, "w", encoding="utf-8") as fh:
            json.dump({"date": snap_date, "signals": payloads}, fh, ensure_ascii=False, indent=2)
        written_paths.append(output_path)

    return written_paths


def bucket_key(pick):
    bbp = pick.get("best_buy_point") or {}
    return (
        pick.get("signal_tier") or "?",
        bbp.get("strength") or "?",
        bbp.get("type") or "?",
    )


def _pick_intent(pick):
    bbp = (pick or {}).get("best_buy_point")
    if not isinstance(bbp, dict):
        return execute_signal({})

    if bbp.get("context") is None:
        bbp = dict(bbp)
        bbp["context"] = build_signal_context(pick, bbp)
    return execute_signal(bbp)


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
    a_only = defaultdict(list)
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
        if _pick_intent(pick).get("category") == "A":
            a_only[ver].append(res)
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

    print()
    print("=== ABC-A Execution Intent Comparison ===")
    for ver in ("picks_pure", "picks_fusion"):
        baseline = summarize(overall[ver])
        a_only_summary = summarize(a_only[ver])
        baseline_n = baseline["n"] if baseline else 0
        a_n = a_only_summary["n"] if a_only_summary else 0
        if baseline_n:
            reduction = round((baseline_n - a_n) / baseline_n * 100, 2)
        else:
            reduction = 0.0
        print(f"[{ver}]")
        print(f"  evaluated={baseline_n}, A_only={a_n}, reduction={reduction}%")
        print(f"  baseline_t3_win_rate={baseline['t3_win_rate'] if baseline else None}% "
              f"-> A_t3_win_rate={a_only_summary['t3_win_rate'] if a_only_summary else None}%")
        print(f"  baseline_t3_mean={baseline['t3_mean'] if baseline else None} "
              f"-> A_t3_mean={a_only_summary['t3_mean'] if a_only_summary else None}")
        print(f"  baseline_max_dd_mean={baseline['max_dd_3d_mean'] if baseline else None} "
              f"-> A_max_dd_mean={a_only_summary['max_dd_3d_mean'] if a_only_summary else None}")
        if baseline:
            print(f"  coverage_gap={baseline_n - a_n}")

    write_signal_snapshot_files()


if __name__ == "__main__":
    main()
