# ChanLun Engine Phase 5.3 Signal Filter Experiments Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Convert the proven P0/P1 filters into opt-in signal experiments so strategy changes can be measured through the experiment registry.

**Architecture:** Add signal-provider variants that post-process buy points produced by the stable signal provider. Register each variant as an experiment. Keep production `analyze()` unchanged.

**Tech Stack:** Python standard library, existing `engine_signals.locate_buy_sell_points`, experiment registry from Phase 5.1, metrics from Phase 5.2.

---

## Scope

Do:
- Add explicit signal filter variants.
- Register each filter as an experiment.
- Add unit tests for filtering behavior.
- Add script-level comparison coverage.

Do not:
- Change `locate_buy_sell_points` production behavior.
- Apply filters to production reports.
- Promote any experiment automatically.

## Candidate Experiments

Register:
- `signal_p0_distance_guard`
  - Drops `底背驰候选` when `distance_from_reference_pct > 3`.
- `signal_p1_confirmation_guard`
  - Drops candidates confirmed only by `止跌结构 + EMA5收复` without `关键位不破` and without `30min底分型`.
- `signal_p0_p1_guard`
  - Applies both.

## Task 1: Add Signal Variant Module

**Files:**
- Create: `chanlun/engine_signal_experiments.py`
- Test: `tests/test_engine_signal_experiments.py`

**Required behavior:**
- `locate_buy_sell_points_p0_distance_guard(result)` delegates to stable signal provider then filters buy points.
- `locate_buy_sell_points_p1_confirmation_guard(result)` delegates then filters.
- `locate_buy_sell_points_p0_p1_guard(result)` applies both.
- Sell points are unchanged.

**Validation:**

```bash
python3 -m unittest tests.test_engine_signal_experiments -v
```

Expected: pass.

## Task 2: Register Signal Experiments

**Files:**
- Modify: `chanlun/engine_experiments.py`
- Test: `tests/test_engine_experiments.py`

**Required behavior:**
- `list_experiments()` includes the three signal guard experiments.
- `build_experiment_provider_bundle("signal_p0_p1_guard")` overrides only `signal_provider`.
- Metadata marks risk as `medium` because output recommendations can change.

**Validation:**

```bash
python3 -m unittest tests.test_engine_experiments tests.test_engine_signal_experiments -v
```

## Task 3: Run Business Compare for Signal Experiments

**Files:**
- No production code unless Phase 5.2 script needs small compatibility adjustment.

Run:

```bash
python3 scripts/compare_chan_engine_dual.py --experiment signal_p0_distance_guard --business-metrics --output /tmp/signal_p0_distance_guard.json
python3 scripts/compare_chan_engine_dual.py --experiment signal_p0_p1_guard --business-metrics --output /tmp/signal_p0_p1_guard.json
```

Expected:
- structural differences are limited to buy/sell signal fields.
- recommendation diff and return metrics are present.

## Final Verification

```bash
python3 -m py_compile chanlun/engine_signal_experiments.py chanlun/engine_experiments.py
python3 -m unittest tests.test_engine_signal_experiments tests.test_engine_experiments tests.test_chan_engine_experiment_script -v
python3 -m unittest discover tests
```

## Commit

```bash
git add chanlun/engine_signal_experiments.py chanlun/engine_experiments.py tests/test_engine_signal_experiments.py tests/test_engine_experiments.py
git commit -m "feat: add signal guard experiments"
```
