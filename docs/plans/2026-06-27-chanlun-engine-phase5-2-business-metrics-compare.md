# ChanLun Engine Phase 5.2 Business Metrics Compare Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Extend dual compare from structure diff to recommendation and return metrics diff.

**Architecture:** Keep structural comparison in `engine_compare.py`. Add a separate metrics layer that can compare legacy and experiment outputs against historical snapshot recommendations and available kline data. Metrics are opt-in and never affect production `analyze()`.

**Tech Stack:** Python standard library, existing `scripts/backtest_recommendation_quality.py`, existing `docs/data/YYYY-MM-DD.json` snapshots.

---

## Scope

Do:
- Add business metric summarization for experiments.
- Reuse existing return metric definitions where possible.
- Make script output machine-readable JSON.
- Clearly report skipped samples and kline coverage.

Do not:
- Change recommendation generation.
- Hide missing market data.
- Treat unavailable kline as a failed strategy result.

## Task 1: Extract Shared Return Metric Helpers

**Files:**
- Modify: `scripts/backtest_recommendation_quality.py`
- Create: `chanlun/backtest_metrics.py`
- Test: `tests/test_backtest_metrics.py`

**Required behavior:**
- `summarize_return_samples(samples)` returns current keys:
  - `n`
  - `n_evaluable`
  - `t1_mean`
  - `t1_median`
  - `t3_mean`
  - `t3_median`
  - `t3_win_rate`
  - `t3_loss_5pct_rate`
  - `max_up_3d_mean`
  - `max_dd_3d_mean`
  - `big_drop_5pct_rate`
  - `big_run_5pct_rate`
- Existing script output remains compatible.

**Validation:**

```bash
python3 -m unittest tests.test_backtest_metrics -v
python3 scripts/backtest_recommendation_quality.py
```

Expected:
- tests pass
- script still runs
- if kline fetch fails, output still explains skipped coverage.

## Task 2: Add Recommendation Diff Metrics

**Files:**
- Create: `chanlun/experiment_metrics.py`
- Test: `tests/test_experiment_metrics.py`

**Required behavior:**

Compare two recommendation lists and report:
- `legacy_count`
- `experiment_count`
- `added_codes`
- `removed_codes`
- `kept_codes`
- `changed_best_buy_point_codes`

Compare by `code` and `best_buy_point`.

**Validation:**

```bash
python3 -m unittest tests.test_experiment_metrics -v
```

Expected: pass.

## Task 3: Add Business Metrics to Dual Compare Script

**Files:**
- Modify: `scripts/compare_chan_engine_dual.py`
- Test: `tests/test_chan_engine_experiment_script.py`

**Required behavior:**
- Add optional `--business-metrics`.
- When set, report summary includes:
  - `structure_equal`
  - `recommendation_diff`
  - `return_metrics`
  - `coverage`
- Do not fail the script solely because kline data is unavailable.
- Still exit non-zero when structural parity script is explicitly used for parity and differences exist.

**Validation:**

```bash
python3 -m unittest tests.test_experiment_metrics tests.test_chan_engine_experiment_script -v
python3 scripts/compare_chan_engine_dual.py --experiment signal_v1 --business-metrics --output /tmp/chan_engine_signal_v1_metrics.json
```

Expected:
- tests pass
- JSON includes business metrics section.

## Final Verification

```bash
python3 -m py_compile chanlun/backtest_metrics.py chanlun/experiment_metrics.py scripts/compare_chan_engine_dual.py
python3 -m unittest tests.test_backtest_metrics tests.test_experiment_metrics tests.test_chan_engine_experiment_script -v
python3 -m unittest discover tests
```

## Commit

```bash
git add chanlun/backtest_metrics.py chanlun/experiment_metrics.py scripts/backtest_recommendation_quality.py scripts/compare_chan_engine_dual.py tests/test_backtest_metrics.py tests/test_experiment_metrics.py tests/test_chan_engine_experiment_script.py
git commit -m "feat: add experiment business metrics"
```
