# ChanLun Engine Phase 6.10 Weak Trend Filter Backtest Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Backtest weak-trend filters on top of the current best `delay1_v1_bottom_quality_guard` policy without changing production `analyze()`.

**Architecture:** Add backtest-only policy variants in `chanlun/policy_experiment_metrics.py`. The variants reuse the existing shared baseline runner, preserve current policy output schema, and report filter reasons separately so we can judge whether market-state filtering improves T+3 return and drawdown. No new data source is introduced.

**Tech Stack:** Python standard library, `unittest`, existing policy backtest runner and snapshot picks.

---

## Context

Phase 6.9 added execution observability. The latest real backtest showed:

```text
snapshot_rows: 2842
unique_codes: 1103
fetch_attempts: 1103
cache_hits: 1739
kline_missing: 1
kline_invalid: 0
baseline_rows: 1287
```

The best current policy remains:

```text
delay1_v1_bottom_quality_guard
```

Key result:

```text
policy n: 1101
T+3: 0.16
delta T+3: +0.13
win rate: 45.9
loss <=5: 18.7
big drop <=5: 36.9
```

This improves average return but does not improve left-tail risk. Phase 6.10 tests whether market/trend fields can reduce the bad tail.

## Available Fields

Snapshot inspection shows these fields are available on picks:

- `market_regime`
- `market_trend`
- `trend_type`
- `ma_bullish`
- `signal_tier`
- `resonance`
- `fusion_admission`

Important distribution:

```text
all picks:
market_regime: ""=1990, strong=676, None=91, weak=85
trend_type: ""=1411, 无中枢=1269, 盘整=146, 下跌趋势=10, 上涨趋势=6
ma_bullish: False=2587, True=255

bottom candidates:
market_regime: ""=771, strong=536
trend_type: 无中枢=1257, 盘整=50
ma_bullish: False=1293, True=14
```

Implication:

- `ma_bullish=False` is too broad for a first production-like rule.
- `market_regime != strong` is a useful first split, but may be aggressive.
- This phase must remain exploratory and backtest-only.

## Non-Goals

- Do not change production `analyze()`.
- Do not change existing policy behavior.
- Do not change `delay1_v1_bottom_quality_guard`.
- Do not fetch new market data.
- Do not use wall-clock time as a test assertion.
- Do not auto-promote any policy.

## Policy Variants

Add three new backtest-only policies:

```python
"delay1_v1_bottom_quality_market_strong_guard"
"delay1_v1_bottom_quality_market_known_guard"
"delay1_v1_bottom_quality_market_or_ma_guard"
```

### 1. `delay1_v1_bottom_quality_market_strong_guard`

Base behavior:

- Same as `delay1_v1_bottom_quality_guard`.

Extra filter:

- Applies only to `best_buy_point.type == "底背驰候选"`.
- Drop if `market_regime != "strong"`.

Reason:

```text
bottom_market_not_strong
```

Purpose:

- Test the strict “only bottom-fish in strong market” hypothesis.

### 2. `delay1_v1_bottom_quality_market_known_guard`

Base behavior:

- Same as `delay1_v1_bottom_quality_guard`.

Extra filter:

- Applies only to `best_buy_point.type == "底背驰候选"`.
- Drop if `market_regime` is missing, blank, or `None`.
- Keep explicit `strong` and explicit `weak`.

Reason:

```text
bottom_market_unknown
```

Purpose:

- Separate “unknown market state” from “weak market”.

### 3. `delay1_v1_bottom_quality_market_or_ma_guard`

Base behavior:

- Same as `delay1_v1_bottom_quality_guard`.

Extra filter:

- Applies only to `best_buy_point.type == "底背驰候选"`.
- Drop if both are true:
  - `market_regime != "strong"`
  - `ma_bullish is not True`

Reason:

```text
bottom_market_not_strong_no_ma
```

Purpose:

- Test a softer rule: allow non-strong market only when the individual stock still has MA bullish support.

## Task 1: Add Trend Filter Helpers And Policies

**Files:**

- Modify: `chanlun/policy_experiment_metrics.py`
- Test: `tests/test_policy_experiment_metrics.py`

**Step 1: Write failing policy registry test**

Update `test_list_policy_experiments()` to include the three new names.

Run:

```bash
python3 -m unittest tests.test_policy_experiment_metrics.PolicyExperimentMetricsTests.test_list_policy_experiments
```

Expected before implementation: FAIL.

**Step 2: Add policy config entries**

Add:

```python
"delay1_v1_bottom_quality_market_strong_guard": {
    "cooldown_days": None,
    "bottom_quality_reasons": "all",
    "bottom_trend_reasons": ("market_not_strong",),
},
"delay1_v1_bottom_quality_market_known_guard": {
    "cooldown_days": None,
    "bottom_quality_reasons": "all",
    "bottom_trend_reasons": ("market_unknown",),
},
"delay1_v1_bottom_quality_market_or_ma_guard": {
    "cooldown_days": None,
    "bottom_quality_reasons": "all",
    "bottom_trend_reasons": ("market_not_strong_no_ma",),
},
```

**Step 3: Add helper**

Add:

```python
_BOTTOM_TREND_REASON_LABELS = {
    "market_not_strong": "bottom_market_not_strong",
    "market_unknown": "bottom_market_unknown",
    "market_not_strong_no_ma": "bottom_market_not_strong_no_ma",
}
```

Add:

```python
def bottom_trend_guard_reasons(pick: Optional[dict]) -> List[str]:
    bbp = (pick or {}).get("best_buy_point")
    if not isinstance(bbp, dict) or bbp.get("type") != "底背驰候选":
        return []

    regime = (pick or {}).get("market_regime")
    regime_text = str(regime or "").strip().lower()
    ma_bullish = (pick or {}).get("ma_bullish") is True

    reasons = []
    if not regime_text:
        reasons.append("market_unknown")
    if regime_text != "strong":
        reasons.append("market_not_strong")
    if regime_text != "strong" and not ma_bullish:
        reasons.append("market_not_strong_no_ma")
    return reasons
```

Add:

```python
def _bottom_trend_reason_label(reason: str) -> str:
    return _BOTTOM_TREND_REASON_LABELS.get(reason, reason)
```

**Step 4: Wire into `should_filter_for_policy()`**

After bottom-quality checks and before cooldown:

```python
trend_reasons = cfg.get("bottom_trend_reasons")
guard_trend_reasons = bottom_trend_guard_reasons(pick)
for reason in _as_str_list(trend_reasons):
    if reason in guard_trend_reasons:
        return True, _bottom_trend_reason_label(reason)
```

Important:

- Quality guard must run first.
- Trend filter only sees samples that pass quality guard.
- Cooldown remains last.

**Step 5: Add unit tests**

Add tests for:

- non-bottom candidate is not filtered by trend rules,
- bottom candidate with `market_regime="strong"` is kept,
- bottom candidate with blank regime is filtered by all three trend policies,
- bottom candidate with `market_regime="weak"` and `ma_bullish=True` is filtered by strict strong policy but kept by market-or-ma policy,
- bottom candidate with `market_regime="weak"` and `ma_bullish=False` is filtered by market-or-ma policy.

Run:

```bash
python3 -m unittest tests.test_policy_experiment_metrics
```

Expected: OK.

## Task 2: Ensure Runner Output Covers New Reasons

**Files:**

- Modify: `tests/test_policy_experiment_runner_script.py`

No runner code should be required if reason rendering is generic.

Add or extend a test payload with:

```python
"policy_filtered_by_reason": {"bottom_market_not_strong": 2}
```

Assert Markdown contains:

```text
bottom_market_not_strong
```

Run:

```bash
python3 -m unittest tests.test_policy_experiment_runner_script
```

Expected: OK.

## Task 3: Verification And Real Backtest

**Files:**

- Create: `docs/plans/2026-06-27-chanlun-engine-phase6-10-weak-trend-filter-backtest-result.md`

Run:

```bash
python3 -m unittest tests.test_policy_experiment_metrics tests.test_policy_experiment_runner_script
python3 -m unittest tests.test_policy_experiment_metrics tests.test_policy_experiment_runner_script tests.test_historical_experiment_metrics tests.test_engine_experiment_runner_script
python3 -m unittest discover -s tests
python3 -m py_compile chanlun/policy_experiment_metrics.py scripts/run_policy_experiments.py
git diff --check
```

Then run real backtest:

```bash
/usr/bin/time -p python3 scripts/run_policy_experiments.py \
  --policies delay1_v1_bottom_quality_guard,delay1_v1_bottom_quality_market_strong_guard,delay1_v1_bottom_quality_market_known_guard,delay1_v1_bottom_quality_market_or_ma_guard \
  --output-json /tmp/phase6_10_weak_trend_filter_metrics.json \
  --output-md /tmp/phase6_10_weak_trend_filter_metrics.md
```

Result doc must include:

- exact test results,
- real backtest command and timing,
- execution summary,
- policy metrics table,
- filter reason counts,
- promotion/rejection decision for each new policy.

## Acceptance Criteria

- Three new policies are registered.
- Existing policies keep their previous behavior.
- Trend filters only apply to `底背驰候选`.
- Quality guard runs before trend guard.
- Runner Markdown renders new reasons without special-case code.
- Full tests pass.
- Real backtest completes.
- Result MD is committed and pushed.

## Promotion Gate

Do not promote unless a new policy satisfies all:

- T+3 mean >= `delay1_v1_bottom_quality_guard`
- T+3 win rate >= `delay1_v1_bottom_quality_guard`
- `t3_loss_5pct_rate` <= `delay1_v1_bottom_quality_guard`
- `big_drop_5pct_rate` <= `delay1_v1_bottom_quality_guard`
- retained ratio >= `70%`
