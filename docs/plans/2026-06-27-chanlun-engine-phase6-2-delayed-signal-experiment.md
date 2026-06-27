# ChanLun Engine Phase 6.2 Delayed Signal Experiment Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Convert the best delayed-entry rule from Phase 6.1 into an opt-in experiment, without changing production `analyze()`.

**Architecture:** Register delayed signal variants in `engine_experiments.py`. The experiment may mark or filter signal buy points based on signal age, but production signal generation remains unchanged until a later human-approved promotion.

**Tech Stack:** Python standard library, `chanlun.engine_signal_experiments`, experiment registry, `unittest`.

---

## Preconditions

Do not start this phase until Phase 6.1 has produced a backtest result showing which delayed mode is preferable.

## Scope

Do:
- Add opt-in experiment(s) for delayed signal handling.
- Preserve production `analyze()`.
- Add tests proving newly formed signals can be deferred while older confirmed signals remain.

Do not:
- Promote the delay to production.
- Change report generation defaults.
- Hide candidate counts without diagnostics.

## Candidate Experiments

Names to choose after Phase 6.1:
- `signal_delay1_open_guard`
- `signal_delay1_close_guard`
- `signal_delay1_by_type_guard`

## Task 1: Add Signal Age Predicate

**Files:**
- Modify: `chanlun/engine_signal_experiments.py`
- Test: `tests/test_engine_signal_experiments.py`

**Required behavior:**
- A helper can identify newly formed signals using `result.closes` length and `bp["index"]`.
- Missing `index` or missing `closes` must no-op.
- Only opt-in experiment uses the helper.

## Task 2: Register Delay Experiment

**Files:**
- Modify: `chanlun/engine_experiments.py`
- Test: `tests/test_engine_experiments.py`

**Required behavior:**
- Register delayed signal experiment with `module="signal"` and `risk="medium"`.
- `build_experiment_provider_bundle()` overrides only `signal_provider`.

## Task 3: Compare With Business Metrics

Run:

```bash
python3 scripts/compare_chan_engine_dual.py --experiment <delay_experiment> --business-metrics --output /tmp/delay_experiment.json
python3 scripts/run_engine_experiments.py --experiments <delay_experiment> --output-json /tmp/delay_experiment_report.json --output-md /tmp/delay_experiment_report.md
```

Expected:
- Script runs.
- Gate remains `insufficient_data` until real return metrics are wired into the runner.

## Final Verification

```bash
python3 -m py_compile chanlun/engine_signal_experiments.py chanlun/engine_experiments.py
python3 -m unittest tests.test_engine_signal_experiments tests.test_engine_experiments tests.test_chan_engine_experiment_script -v
python3 -m unittest discover tests
```

## Commit

```bash
git add chanlun/engine_signal_experiments.py chanlun/engine_experiments.py tests/test_engine_signal_experiments.py tests/test_engine_experiments.py
git commit -m "feat: 添加延迟信号实验"
```
