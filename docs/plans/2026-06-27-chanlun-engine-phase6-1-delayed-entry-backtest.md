# ChanLun Engine Phase 6.1 Delayed Entry Backtest Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Measure whether delaying entry by one trading bar improves historical recommendation quality before changing any production signal behavior.

**Architecture:** Add a read-only backtest script that reuses `docs/data/YYYY-MM-DD.json` snapshots and `fetch_daily_kline`. Compare immediate entry against next-bar open and next-bar close entry. Keep production `analyze()` and report generation unchanged.

**Tech Stack:** Python standard library, existing `chanlun.data_fetcher.fetch_daily_kline`, existing `chanlun.backtest_metrics.summarize_return_samples`, `unittest`.

---

## Scope

Do:
- Add delayed-entry return calculation helpers.
- Add a script that compares:
  - `immediate_close`: recommendation-day close as reference.
  - `delay1_open`: next trading day's open as reference.
  - `delay1_close`: next trading day's close as reference.
- Group results by `picks_pure` / `picks_fusion` and `best_buy_point.type`.
- Print machine-readable JSON summary.
- Clearly report skipped samples and market-data coverage.

Do not:
- Change production `analyze()`.
- Change `locate_buy_sell_points`.
- Apply delayed entry to reports.
- Fetch data concurrently.

## Why This Comes First

The current backtest evaluates returns from the snapshot date close. It does not test actual `best_buy_point.index + 1` execution. A production delay rule would be premature until we know which execution baseline is better.

## Task 1: Extract Forward Return Evaluation Helper

**Files:**
- Modify: `scripts/backtest_recommendation_quality.py`
- Create: `chanlun/backtest_execution.py`
- Test: `tests/test_backtest_execution.py`

**Required behavior:**

Create `evaluate_forward_returns(kline, snap_date, entry_mode, horizon=5)`:
- `entry_mode="immediate_close"` uses snap date close as ref and forward bars after snap date.
- `entry_mode="delay1_open"` uses next trading day open as ref and evaluates subsequent bars from that next day.
- `entry_mode="delay1_close"` uses next trading day close as ref and evaluates bars after that next day close.
- Return current metric sample keys:
  - `t1_close_pct`
  - `t3_close_pct`
  - `max_up_3d`
  - `max_dd_3d`
  - `n_forward_days`
  - `entry_mode`
  - `entry_date`
  - `ref_date`
- Return `None` when there is not enough kline coverage.

**Validation:**

```bash
python3 -m unittest tests.test_backtest_execution -v
```

Expected: pass with synthetic kline arrays.

## Task 2: Keep Existing Backtest Compatible

**Files:**
- Modify: `scripts/backtest_recommendation_quality.py`
- Test: existing tests via full suite.

**Required behavior:**
- Existing `evaluate(pick, snap_date)` still returns same shape for current callers.
- Existing script output remains compatible.
- Implementation may delegate to `evaluate_forward_returns(..., "immediate_close")`.

**Validation:**

```bash
python3 scripts/backtest_recommendation_quality.py
```

Expected:
- Script still runs.
- If market data fails, it reports skipped coverage, not strategy failure.

## Task 3: Add Delayed Entry Comparison Script

**Files:**
- Create: `scripts/backtest_delayed_entry.py`
- Test: `tests/test_backtest_delayed_entry_script.py`

**Required behavior:**
- CLI:
  - `--output-json /tmp/delayed_entry.json`
  - optional `--limit-days N` for tests/smoke.
- Iterate snapshot picks from `scripts.backtest_recommendation_quality.iter_snapshot_picks`.
- For each pick, evaluate all three modes.
- Summarize by:
  - overall version (`picks_pure`, `picks_fusion`)
  - `(version, best_buy_point.type)`
- Output JSON:

```json
{
  "summary": {
    "snapshot_days": 25,
    "picks_seen": 2842,
    "evaluated_by_mode": {
      "immediate_close": 0,
      "delay1_open": 0,
      "delay1_close": 0
    },
    "skipped": 0
  },
  "overall": {
    "picks_fusion": {
      "immediate_close": {},
      "delay1_open": {},
      "delay1_close": {}
    }
  },
  "by_type": {}
}
```

**Validation:**

```bash
python3 -m unittest tests.test_backtest_delayed_entry_script -v
python3 scripts/backtest_delayed_entry.py --limit-days 1 --output-json /tmp/delayed_entry_smoke.json
```

Expected:
- Test passes.
- Smoke writes JSON even if all samples are skipped due market data.

## Final Verification

```bash
python3 -m py_compile chanlun/backtest_execution.py scripts/backtest_recommendation_quality.py scripts/backtest_delayed_entry.py
python3 -m unittest tests.test_backtest_execution tests.test_backtest_delayed_entry_script -v
python3 -m unittest discover tests
```

For real backtest:

```bash
python3 scripts/backtest_delayed_entry.py --output-json /tmp/chanlun_delayed_entry_backtest.json
```

Run this script sequentially, not concurrently with other kline-fetching scripts.

## Commit

```bash
git add chanlun/backtest_execution.py scripts/backtest_recommendation_quality.py scripts/backtest_delayed_entry.py tests/test_backtest_execution.py tests/test_backtest_delayed_entry_script.py
git commit -m "feat: 添加延迟入场回测"
```
