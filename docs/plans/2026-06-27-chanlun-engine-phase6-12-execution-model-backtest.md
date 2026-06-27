# ChanLun Engine Phase 6.12 Execution Model Backtest Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add backtest-only execution-model A/B metrics so we can tell whether the weak return uplift comes from signal quality or from the current entry-price model.

**Architecture:** Keep production `analyze()` untouched. Extend the existing policy backtest runner to re-evaluate the same accepted candidate sample under explicit entry modes, then render the comparison in JSON and Markdown.

**Tech Stack:** Python 3, `unittest`, existing `chanlun.backtest_execution.evaluate_forward_returns`, existing `scripts/run_policy_experiments.py`.

---

## Context

Phase 6.11 showed:

```text
delay1_v1: T+3=0.03, ΔT+3=0.00
delay1_v1_bottom_quality_market_known_guard: T+3=0.41, ΔT+3=+0.38
```

This means the one-bar confirmation direction is not wrong, but the current uplift is still small. The next question is whether the bottleneck is:

- signal quality, or
- the execution model: signal-day close, next-day open, confirmation-day close.

Existing useful code:

- `chanlun.backtest_execution.evaluate_forward_returns(kline, snap_date, entry_mode, horizon=5)`
- Supported entry modes:
  - `immediate_close`
  - `delay1_open`
  - `delay1_close`
- `chanlun.policy_experiment_metrics.run_policy_experiment_metrics()`
- `scripts/run_policy_experiments.py`

## Non-Goals

- Do not modify production `analyze()`.
- Do not modify candidate plugin/provider architecture.
- Do not add live trading behavior.
- Do not implement stop-loss or take-profit in this phase.
- Do not delete or rewrite `scripts/backtest_delayed_entry.py`; it can remain as an older standalone helper.

## Design

Add three backtest-only policy names that reuse the Phase 6.10 best filter:

```python
delay1_v1_bottom_quality_market_known_guard_entry_signal_close
delay1_v1_bottom_quality_market_known_guard_entry_next_open
delay1_v1_bottom_quality_market_known_guard_entry_confirm_close
```

Mapping:

```python
entry_signal_close  -> immediate_close
entry_next_open     -> delay1_open
entry_confirm_close -> delay1_close
```

These policies should:

1. Apply the same filter rules as `delay1_v1_bottom_quality_market_known_guard`.
2. Evaluate accepted rows using the explicit entry mode.
3. Keep the existing baseline summary as the reference.
4. Report `entry_mode` and `policy_not_evaluable`.
5. Preserve the Phase 6.11 `breakdown` dimensions.

The current `_run_one_policy()` reuses `baseline_sample`, so it cannot compare entry models yet. Store the normalized kline in `evaluated_rows` during shared baseline construction and only re-evaluate when a policy declares an explicit `entry_mode`.

## Task 1: Add Execution-Variant Policy Config

**Files:**

- Modify: `chanlun/policy_experiment_metrics.py`
- Test: `tests/test_policy_experiment_metrics.py`

**Step 1: Write failing tests**

Add tests that assert:

1. The three new policy names are supported.
2. The execution variant keeps the same filter behavior as `delay1_v1_bottom_quality_market_known_guard`.
3. A variant with explicit `entry_mode` re-evaluates samples instead of reusing `baseline_sample`.
4. `coverage["policy_not_evaluable"]` increments when explicit entry-mode evaluation returns `None`.
5. Result payload includes:

```python
result["execution_model"]["entry_mode"] == "delay1_open"
result["execution_model"]["label"] == "entry_next_open"
```

Suggested test shape:

```python
@patch("chanlun.policy_experiment_metrics._fetch_daily_kline_cached")
@patch("chanlun.policy_experiment_metrics._evaluate_pick_sample")
@patch("chanlun.policy_experiment_metrics.iter_snapshot_picks")
def test_execution_variant_uses_explicit_entry_mode(...):
    # baseline call returns baseline sample
    # explicit variant call returns different sample for delay1_open
    # assert policy_summary uses variant sample
```

**Step 2: Run failing test**

```bash
python3 -m unittest tests.test_policy_experiment_metrics
```

Expected before implementation: FAIL because policy names and `execution_model` do not exist.

**Step 3: Implement minimal code**

In `POLICY_EXPERIMENTS`, add:

```python
"delay1_v1_bottom_quality_market_known_guard_entry_signal_close": {
    "cooldown_days": None,
    "bottom_quality_reasons": "all",
    "bottom_trend_reasons": ("market_unknown",),
    "entry_label": "entry_signal_close",
    "entry_mode": "immediate_close",
},
"delay1_v1_bottom_quality_market_known_guard_entry_next_open": {
    "cooldown_days": None,
    "bottom_quality_reasons": "all",
    "bottom_trend_reasons": ("market_unknown",),
    "entry_label": "entry_next_open",
    "entry_mode": "delay1_open",
},
"delay1_v1_bottom_quality_market_known_guard_entry_confirm_close": {
    "cooldown_days": None,
    "bottom_quality_reasons": "all",
    "bottom_trend_reasons": ("market_unknown",),
    "entry_label": "entry_confirm_close",
    "entry_mode": "delay1_close",
},
```

In `_build_shared_baseline_context()`, add the normalized kline to each evaluated row:

```python
"normalized_kline": normalized_kline,
```

In `_run_one_policy()`:

- initialize `policy_not_evaluable = 0`
- resolve explicit entry mode:

```python
entry_mode = cfg.get("entry_mode")
if entry_mode:
    policy_sample = _evaluate_pick_sample(item.get("normalized_kline"), snap_date, entry_mode)
else:
    policy_sample = item.get("baseline_sample")
```

- if explicit re-evaluation returns `None`, increment `policy_not_evaluable`, still record accepted breakdown, then continue
- add coverage field:

```python
"policy_not_evaluable": policy_not_evaluable
```

- add result metadata:

```python
"execution_model": {
    "entry_label": cfg.get("entry_label") or "baseline_type_guard",
    "entry_mode": cfg.get("entry_mode") or "baseline_type_guard",
}
```

**Step 4: Run targeted tests**

```bash
python3 -m unittest tests.test_policy_experiment_metrics
```

Expected: OK.

## Task 2: Render Execution Model Metrics in Markdown

**Files:**

- Modify: `scripts/run_policy_experiments.py`
- Test: `tests/test_policy_experiment_runner_script.py`

**Step 1: Write failing tests**

Add tests that assert Markdown table includes:

- `Entry Model`
- `Entry Mode`
- `Not Evaluable`
- the configured entry label, for example `entry_next_open`

Suggested assertion:

```python
self.assertIn("Entry Model", text)
self.assertIn("entry_next_open", text)
self.assertIn("delay1_open", text)
```

**Step 2: Run failing test**

```bash
python3 -m unittest tests.test_policy_experiment_runner_script
```

Expected before implementation: FAIL because markdown has no execution-model columns.

**Step 3: Implement minimal renderer changes**

In `_table_row()`:

- read `execution_model = result.get("execution_model") or {}`
- read `coverage["policy_not_evaluable"]`
- add columns:
  - `Entry Model`
  - `Entry Mode`
  - `Not Evaluable`

Keep this backward compatible: old payloads without `execution_model` should render `-`.

**Step 4: Run targeted tests**

```bash
python3 -m unittest tests.test_policy_experiment_runner_script
```

Expected: OK.

## Task 3: Verification Matrix

**Files:**

- Verify only.

Run:

```bash
python3 -m unittest tests.test_policy_experiment_metrics tests.test_policy_experiment_runner_script
python3 -m py_compile chanlun/policy_experiment_metrics.py scripts/run_policy_experiments.py
git diff --check
python3 -m unittest tests.test_policy_experiment_metrics tests.test_policy_experiment_runner_script tests.test_historical_experiment_metrics tests.test_engine_experiment_runner_script tests.test_backtest_execution
python3 -m unittest discover -s tests
```

Expected:

- all tests pass
- no py_compile output
- no `git diff --check` output

## Task 4: Real Backtest

Run:

```bash
/usr/bin/time -p python3 scripts/run_policy_experiments.py \
  --policies delay1_v1_bottom_quality_market_known_guard,delay1_v1_bottom_quality_market_known_guard_entry_signal_close,delay1_v1_bottom_quality_market_known_guard_entry_next_open,delay1_v1_bottom_quality_market_known_guard_entry_confirm_close \
  --output-json /tmp/phase6_12_execution_model_metrics.json \
  --output-md /tmp/phase6_12_execution_model_metrics.md
```

Expected artifacts:

- `/tmp/phase6_12_execution_model_metrics.json`
- `/tmp/phase6_12_execution_model_metrics.md`

Expected interpretation:

- If `entry_signal_close` is much better than the two delayed entries, the strategy may be losing edge by waiting too long.
- If `entry_next_open` is worse than `entry_confirm_close`, opening gap risk may be harming the current execution model.
- If all three are close, signal quality is probably the larger bottleneck than execution price.

## Task 5: Result Document

**Files:**

- Create: `docs/plans/2026-06-27-chanlun-engine-phase6-12-execution-model-backtest-result.md`

Include:

- code changes
- test commands and exact results
- real backtest command and timing
- table comparing:
  - policy
  - entry label
  - entry mode
  - policy n
  - not evaluable
  - T+3
  - ΔT+3
  - win rate
  - loss<=5%
  - bigdrop>=5%
- recommendation for Phase 6.13

## Task 6: Commits and Push

Use two commits:

```bash
git add chanlun/policy_experiment_metrics.py scripts/run_policy_experiments.py tests/test_policy_experiment_metrics.py tests/test_policy_experiment_runner_script.py
git commit -m "feat: 添加执行模型回测对比"

git add -f docs/plans/2026-06-27-chanlun-engine-phase6-12-execution-model-backtest-result.md
git commit -m "docs: 添加执行模型回测结果"

git push origin main
git rev-list --left-right --count origin/main...HEAD
git status --short
```

Expected:

```text
0 0
```

`git status --short` may still show local `.codegraph/`; do not commit it.

## Acceptance Criteria

- Production `analyze()` remains unchanged.
- The three execution variant policies are available through `scripts/run_policy_experiments.py --policies`.
- Markdown output shows entry label/mode and not-evaluable counts.
- Existing Phase 6.11 breakdown output remains present.
- Full test suite passes.
- Real backtest output exists under `/tmp`.
- Result document is committed under `docs/plans`.
- Changes are pushed to `origin/main`.
