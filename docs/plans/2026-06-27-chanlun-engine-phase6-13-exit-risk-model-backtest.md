# ChanLun Engine Phase 6.13 Exit Risk Model Backtest Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add backtest-only exit/risk-model A/B metrics for the current best candidate so we can test whether fixed T+3 exit is the main reason returns remain weak.

**Architecture:** Keep production `analyze()` untouched. Add a small backtest execution helper that simulates simple 3-day exit rules from the same kline window, then wire it into policy experiment variants and Markdown output.

**Tech Stack:** Python 3, `unittest`, existing `chanlun.backtest_execution`, existing `chanlun.policy_experiment_metrics`, existing `scripts/run_policy_experiments.py`.

---

## Context

Phase 6.12 showed:

```text
entry_next_open:     T+3=0.41, ΔT+3=+0.38
entry_signal_close:  T+3=0.09, ΔT+3=+0.06
entry_confirm_close: T+3=-0.43, ΔT+3=-0.46
```

Interpretation:

- Further delaying entry is not useful.
- `entry_next_open` should be kept as the candidate execution baseline.
- Next question: does fixed T+3 exit hide too much downside/upside?

Phase 6.13 should answer this by testing simple exit rules on the same accepted samples.

## Non-Goals

- Do not modify production `analyze()`.
- Do not add live trading behavior.
- Do not add intraday data or minute-level fills.
- Do not implement portfolio sizing or position management.
- Do not remove existing T+3 metrics.
- Do not change the Phase 6.12 execution-model policies.

## Conservative Fill Rules

The exit simulator uses daily OHLC only, so intraday order is unknown.

Use these conservative assumptions:

- Entry model remains `delay1_open`.
- Evaluation window is the first 3 forward trading days after entry, aligned with existing T+3 metrics.
- `exit_t3`: exit at existing T+3 close.
- `exit_stop_loss_5pct`: if any forward low reaches `-5%`, return `-5.0`; otherwise exit at T+3 close.
- `exit_take_profit_8pct_or_t3`: if any forward high reaches `+8%`, return `8.0`; otherwise exit at T+3 close.
- `exit_stop5_take8_conservative`: scan days in order; if stop and take-profit both trigger on the same day, count stop first.

This is intentionally conservative. It avoids overstating the value of take-profit exits.

## Policy Variants

Add four backtest-only policy names:

```python
delay1_v1_bottom_quality_market_known_guard_entry_next_open_exit_t3
delay1_v1_bottom_quality_market_known_guard_entry_next_open_exit_stop_loss_5pct
delay1_v1_bottom_quality_market_known_guard_entry_next_open_exit_take_profit_8pct_or_t3
delay1_v1_bottom_quality_market_known_guard_entry_next_open_exit_stop5_take8_conservative
```

All four should use:

```python
bottom_quality_reasons = "all"
bottom_trend_reasons = ("market_unknown",)
entry_label = "entry_next_open"
entry_mode = "delay1_open"
```

Each policy differs only by `exit_model`.

## Task 1: Add Exit Simulator

**Files:**

- Modify: `chanlun/backtest_execution.py`
- Test: `tests/test_backtest_execution.py`

**Step 1: Write failing tests**

Add tests for:

1. `exit_t3` matches existing `evaluate_forward_returns(..., "delay1_open")["t3_close_pct"]`.
2. `exit_stop_loss_5pct` returns `-5.0` when forward low breaches stop.
3. `exit_take_profit_8pct_or_t3` returns `8.0` when forward high reaches target.
4. `exit_stop5_take8_conservative` returns `-5.0` when both stop and target occur on the same day.
5. Unknown exit model returns `None`.

Suggested API:

```python
from chanlun.backtest_execution import evaluate_exit_returns

sample = evaluate_exit_returns(kline, "2026-01-03", "delay1_open", "exit_stop_loss_5pct")
self.assertEqual(sample["exit_model"], "exit_stop_loss_5pct")
self.assertEqual(sample["exit_reason"], "stop_loss_5pct")
self.assertAlmostEqual(sample["t3_close_pct"], -5.0)
```

**Step 2: Run failing test**

```bash
python3 -m unittest tests.test_backtest_execution
```

Expected before implementation: FAIL because `evaluate_exit_returns` does not exist.

**Step 3: Implement helper**

Add:

```python
SUPPORTED_EXIT_MODELS = {
    "exit_t3",
    "exit_stop_loss_5pct",
    "exit_take_profit_8pct_or_t3",
    "exit_stop5_take8_conservative",
}
```

Implement:

```python
def evaluate_exit_returns(kline, snap_date, entry_mode, exit_model, horizon=5):
    ...
```

Implementation guidance:

- Reuse the same validation and entry-index rules as `evaluate_forward_returns`.
- Compute `ref` the same way as `evaluate_forward_returns`.
- Use the same first-three-day horizon for exit decisions.
- Start from the normal forward sample and copy its fields.
- Override:
  - `t3_close_pct`
  - `exit_model`
  - `exit_reason`
  - `exit_return_pct`
  - `exit_day_index`
- Keep `max_up_3d` and `max_dd_3d` from the original forward sample so risk columns remain comparable.

Expected return shape:

```python
{
    "t1_close_pct": ...,
    "t3_close_pct": adjusted_exit_return,
    "max_up_3d": ...,
    "max_dd_3d": ...,
    "n_forward_days": ...,
    "entry_mode": entry_mode,
    "entry_date": ...,
    "ref_date": ...,
    "exit_model": exit_model,
    "exit_reason": "t3_close" | "stop_loss_5pct" | "take_profit_8pct",
    "exit_return_pct": adjusted_exit_return,
    "exit_day_index": 1 | 2 | 3,
}
```

**Step 4: Run targeted test**

```bash
python3 -m unittest tests.test_backtest_execution
```

Expected: OK.

## Task 2: Wire Exit Models into Policy Metrics

**Files:**

- Modify: `chanlun/policy_experiment_metrics.py`
- Test: `tests/test_policy_experiment_metrics.py`

**Step 1: Write failing tests**

Add tests that assert:

1. The four new exit policy names are supported.
2. Exit policies use the same filter behavior as `delay1_v1_bottom_quality_market_known_guard_entry_next_open`.
3. An exit policy calls `evaluate_exit_returns` with:

```text
entry_mode=delay1_open
exit_model=exit_stop_loss_5pct
```

4. Result payload includes:

```python
result["execution_model"]["entry_label"] == "entry_next_open"
result["execution_model"]["entry_mode"] == "delay1_open"
result["execution_model"]["exit_model"] == "exit_stop_loss_5pct"
```

5. `coverage["policy_not_evaluable"]` increments if exit-model evaluation returns `None`.

**Step 2: Run failing test**

```bash
python3 -m unittest tests.test_policy_experiment_metrics
```

Expected before implementation: FAIL.

**Step 3: Implement policy wiring**

In `POLICY_EXPERIMENTS`, add the four policies listed above.

Import:

```python
from chanlun.backtest_execution import evaluate_exit_returns
```

In `_run_one_policy()`:

- read `exit_model = cfg.get("exit_model")`
- if `exit_model` exists, call:

```python
policy_sample = evaluate_exit_returns(
    item.get("normalized_kline"),
    snap_date,
    entry_mode,
    exit_model,
)
```

- otherwise keep Phase 6.12 behavior.
- add `exit_model` to `execution_model`, defaulting to `exit_t3` when no explicit exit model exists.

Keep behavior back-compatible:

- old policies without `entry_mode` keep using `baseline_sample`
- Phase 6.12 entry-only policies keep using `_evaluate_pick_sample`

**Step 4: Run targeted test**

```bash
python3 -m unittest tests.test_policy_experiment_metrics
```

Expected: OK.

## Task 3: Render Exit Model Metrics

**Files:**

- Modify: `scripts/run_policy_experiments.py`
- Test: `tests/test_policy_experiment_runner_script.py`

**Step 1: Write failing tests**

Add Markdown test assertions:

```python
self.assertIn("Exit Model", text)
self.assertIn("exit_stop_loss_5pct", text)
```

**Step 2: Run failing test**

```bash
python3 -m unittest tests.test_policy_experiment_runner_script
```

Expected before implementation: FAIL.

**Step 3: Implement renderer changes**

Add `Exit Model` column after `Entry Mode`.

Keep old payload compatibility:

```python
exit_model = execution_model.get("exit_model", "-")
```

Update table separator row to match the new column count.

**Step 4: Run targeted test**

```bash
python3 -m unittest tests.test_policy_experiment_runner_script
```

Expected: OK.

## Task 4: Verification Matrix

Run:

```bash
python3 -m unittest tests.test_backtest_execution tests.test_policy_experiment_metrics tests.test_policy_experiment_runner_script
python3 -m py_compile chanlun/backtest_execution.py chanlun/policy_experiment_metrics.py scripts/run_policy_experiments.py
git diff --check
python3 -m unittest tests.test_policy_experiment_metrics tests.test_policy_experiment_runner_script tests.test_historical_experiment_metrics tests.test_engine_experiment_runner_script tests.test_backtest_execution tests.test_backtest_metrics
python3 -m unittest discover -s tests
```

Expected:

- all tests pass
- no py_compile output
- no `git diff --check` output

## Task 5: Real Backtest

Run:

```bash
/usr/bin/time -p python3 scripts/run_policy_experiments.py \
  --policies delay1_v1_bottom_quality_market_known_guard_entry_next_open,delay1_v1_bottom_quality_market_known_guard_entry_next_open_exit_t3,delay1_v1_bottom_quality_market_known_guard_entry_next_open_exit_stop_loss_5pct,delay1_v1_bottom_quality_market_known_guard_entry_next_open_exit_take_profit_8pct_or_t3,delay1_v1_bottom_quality_market_known_guard_entry_next_open_exit_stop5_take8_conservative \
  --output-json /tmp/phase6_13_exit_risk_model_metrics.json \
  --output-md /tmp/phase6_13_exit_risk_model_metrics.md
```

Expected artifacts:

- `/tmp/phase6_13_exit_risk_model_metrics.json`
- `/tmp/phase6_13_exit_risk_model_metrics.md`

Interpretation:

- If stop loss reduces `loss<=5%` and `bigdrop>=5%` but hurts mean too much, it is a risk-control option, not a return option.
- If take-profit improves mean or win rate without increasing big drops, it is a promotion candidate.
- If combined stop/take is better than both, use it for the next promotion-gate phase.
- If all exits are worse than `exit_t3`, keep fixed T+3 and move back to signal quality.

## Task 6: Result Document

**Files:**

- Create: `docs/plans/2026-06-27-chanlun-engine-phase6-13-exit-risk-model-backtest-result.md`

Include:

- implementation summary
- code review notes
- test commands and exact results
- real backtest command and timing
- table comparing:
  - policy
  - entry model
  - entry mode
  - exit model
  - policy n
  - not evaluable
  - retained %
  - T+3 / adjusted exit return
  - ΔT+3
  - win rate
  - loss<=5%
  - bigdrop>=5%
- recommendation for Phase 6.14

## Task 7: Commits and Push

Use two commits:

```bash
git add chanlun/backtest_execution.py chanlun/policy_experiment_metrics.py scripts/run_policy_experiments.py tests/test_backtest_execution.py tests/test_policy_experiment_metrics.py tests/test_policy_experiment_runner_script.py
git commit -m "feat: 添加退出风控回测对比"

git add -f docs/plans/2026-06-27-chanlun-engine-phase6-13-exit-risk-model-backtest-result.md
git commit -m "docs: 添加退出风控回测结果"

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
- Four exit-model policy names are available through `scripts/run_policy_experiments.py --policies`.
- Exit-model policies reuse the Phase 6.12 best candidate filter and `entry_next_open`.
- Markdown output shows `Entry Model`, `Entry Mode`, `Exit Model`, and `Not Evaluable`.
- Existing Phase 6.11 breakdown output remains present.
- Full test suite passes.
- Real backtest output exists under `/tmp`.
- Result document is committed under `docs/plans`.
- Changes are pushed to `origin/main`.
