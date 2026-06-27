# ChanLun Engine Phase 5.4 Experiment Report And Promotion Gates Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Produce repeatable experiment reports with promotion gates so candidate plugins can be judged by business metrics before production adoption.

**Architecture:** Add a batch runner that executes registered experiments, writes JSON and Markdown reports, and evaluates promotion gates. The runner is read-only against production strategy code.

**Tech Stack:** Python standard library, experiment registry, business metrics compare, Markdown output.

---

## Scope

Do:
- Add a batch experiment runner.
- Output JSON and Markdown.
- Add promotion gate evaluation.
- Keep reports deterministic where kline coverage is available.

Do not:
- Auto-promote experiments.
- Modify production `analyze()`.
- Push generated reports into `docs/` unless explicitly requested.

## Promotion Gates

Initial gates:
- `sample_count >= 100`
- `t3_mean_delta >= 0.5`
- `t3_win_rate_delta >= 3.0`
- `t3_loss_5pct_rate_delta <= -3.0`
- `big_drop_5pct_rate_delta <= -5.0`
- `coverage.evaluated > 0`

Gate result must be:
- `pass`
- `fail`
- `insufficient_data`

## Task 1: Add Gate Evaluator

**Files:**
- Create: `chanlun/experiment_gates.py`
- Test: `tests/test_experiment_gates.py`

**Required behavior:**
- Accept before/after metric dictionaries.
- Return gate-by-gate result and final decision.
- Treat missing metrics as `insufficient_data`.

**Validation:**

```bash
python3 -m unittest tests.test_experiment_gates -v
```

## Task 2: Add Batch Runner

**Files:**
- Create: `scripts/run_engine_experiments.py`
- Test: `tests/test_engine_experiment_runner_script.py`

**Required behavior:**
- Accept `--experiments signal_p0_distance_guard,signal_p0_p1_guard`.
- Accept `--output-json`.
- Accept `--output-md`.
- Include:
  - experiment metadata
  - structure diff summary
  - recommendation diff summary
  - return metrics
  - gate result

**Validation:**

```bash
python3 -m unittest tests.test_engine_experiment_runner_script -v
python3 scripts/run_engine_experiments.py --experiments signal_p0_distance_guard,signal_p0_p1_guard --output-json /tmp/engine_experiments.json --output-md /tmp/engine_experiments.md
```

Expected:
- script exits 0 when reports are produced.
- gate failures are reported in output, not treated as process errors.

## Task 3: Add Documentation

**Files:**
- Create: `docs/plans/2026-06-27-chanlun-engine-experiment-operations.md`

Document:
- How to add a new experiment.
- How to run compare for one experiment.
- How to run batch report.
- How to interpret promotion gates.
- Rule: production `analyze()` changes only after explicit human approval.

## Final Verification

```bash
python3 -m py_compile chanlun/experiment_gates.py scripts/run_engine_experiments.py
python3 -m unittest tests.test_experiment_gates tests.test_engine_experiment_runner_script -v
python3 -m unittest discover tests
```

## Commit

```bash
git add chanlun/experiment_gates.py scripts/run_engine_experiments.py tests/test_experiment_gates.py tests/test_engine_experiment_runner_script.py docs/plans/2026-06-27-chanlun-engine-experiment-operations.md
git commit -m "feat: add experiment reports and promotion gates"
```
