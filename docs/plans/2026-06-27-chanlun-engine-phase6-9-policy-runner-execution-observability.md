# ChanLun Engine Phase 6.9 Policy Runner Execution Observability Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add non-breaking execution observability to policy backtests so strategy metrics can be judged together with data/fetch/cache quality.

**Architecture:** Keep policy behavior unchanged. Extend the shared baseline context built by `run_policy_experiment_metrics()` with an `execution` block, then surface that block in JSON and Markdown output. The execution block is diagnostic-only and must not affect filtering, sample evaluation, deltas, or production `analyze()`.

**Tech Stack:** Python standard library, `unittest`, existing ChanLun policy backtest runner.

---

## Context

Phase 6.8 changed policy backtests from per-policy repeated scans to shared baseline samples and shared K-line cache.

That made multi-policy backtests faster, but the output still cannot explain execution quality:

- how many unique codes were considered,
- how many K-line fetch attempts were made,
- how many rows reused cached K-line data,
- how many rows had no K-line data,
- how many rows had invalid normalized K-line data,
- whether the runner is using the shared baseline path.

Without these counters, later strategy comparisons can mix strategy effects with data source noise.

## Non-Goals

- Do not add new strategy policies.
- Do not change `POLICY_EXPERIMENTS`.
- Do not change `should_filter_for_policy()`.
- Do not change `baseline_summary`, `policy_summary`, `coverage`, or `delta` semantics.
- Do not change production `analyze()`.
- Do not depend on wall-clock time in tests.

## Output Contract

Add a top-level `execution` object to `run_policy_experiment_metrics()` payload:

```json
{
  "execution": {
    "shared_baseline": true,
    "snapshot_rows": 2842,
    "unique_codes": 1234,
    "fetch_attempts": 1234,
    "cache_hits": 1608,
    "kline_missing": 0,
    "kline_invalid": 0,
    "baseline_rows": 1287
  }
}
```

Field rules:

- `shared_baseline`: always `true` for this runner after Phase 6.8.
- `snapshot_rows`: total rows from `_build_snapshot_rows()`.
- `unique_codes`: number of distinct non-empty codes seen in snapshot rows.
- `fetch_attempts`: number of first-time code lookups before cache reuse.
- `cache_hits`: number of rows whose code was already present in the shared K-line cache.
- `kline_missing`: number of rows skipped because fetched K-line was `None`.
- `kline_invalid`: number of rows skipped because `_normalize_kline()` returned falsey.
- `baseline_rows`: number of shared evaluated rows used by policies.

Keep existing top-level `snapshot_rows` for backward compatibility.

## Task 1: Add Execution Counters To Shared Baseline Context

**Files:**

- Modify: `chanlun/policy_experiment_metrics.py`
- Test: `tests/test_policy_experiment_metrics.py`

**Step 1: Write failing tests**

Add test coverage for execution fields.

Suggested tests:

```python
@patch("chanlun.policy_experiment_metrics._fetch_daily_kline_cached")
@patch("chanlun.policy_experiment_metrics._evaluate_pick_sample")
@patch("chanlun.policy_experiment_metrics.iter_snapshot_picks")
def test_execution_summary_reports_shared_cache_counters(...):
    ...
```

Use rows with duplicate codes:

```text
2026-01-05 code=000001
2026-01-06 code=000001
2026-01-07 code=000002
```

Expected:

```python
execution = payload["execution"]
self.assertTrue(execution["shared_baseline"])
self.assertEqual(execution["snapshot_rows"], 3)
self.assertEqual(execution["unique_codes"], 2)
self.assertEqual(execution["fetch_attempts"], 2)
self.assertEqual(execution["cache_hits"], 1)
self.assertEqual(execution["baseline_rows"], 3)
```

Add a second test for missing/invalid K-line rows:

```text
code=000001 -> None
code=000002 -> invalid normalized kline
code=000003 -> valid
```

Expected:

```python
self.assertEqual(execution["kline_missing"], 1)
self.assertEqual(execution["kline_invalid"], 1)
self.assertEqual(execution["baseline_rows"], 1)
```

If mocking `_normalize_kline()` is cleaner than building invalid arrays, use a focused patch and keep the test explicit.

**Step 2: Run failing tests**

```bash
python3 -m unittest tests.test_policy_experiment_metrics
```

Expected before implementation: failure because `execution` is missing.

**Step 3: Implement minimal counters**

In `_build_shared_baseline_context()`:

- initialize:

```python
unique_codes = set()
fetch_attempts = 0
cache_hits = 0
kline_missing = 0
kline_invalid = 0
```

- before calling `_fetch_daily_kline_cached()`:

```python
code_str = str(code)
if code_str in kline_cache:
    cache_hits += 1
else:
    fetch_attempts += 1
unique_codes.add(code_str)
```

- increment `kline_missing` when fetched kline is `None`.
- increment `kline_invalid` when normalized kline is falsey.
- include `baseline_rows` after evaluated rows are built.
- return `execution` from `_build_shared_baseline_context()`.

In `run_policy_experiment_metrics()`:

- cast/read `execution` from baseline context.
- return it as top-level `execution`.
- keep top-level `snapshot_rows`.

**Step 4: Run tests**

```bash
python3 -m unittest tests.test_policy_experiment_metrics
```

Expected: OK.

## Task 2: Surface Execution Summary In Runner Markdown

**Files:**

- Modify: `scripts/run_policy_experiments.py`
- Test: `tests/test_policy_experiment_runner_script.py`

**Step 1: Write failing runner test**

Update fake payload to include:

```python
"execution": {
    "shared_baseline": True,
    "snapshot_rows": 10,
    "unique_codes": 6,
    "fetch_attempts": 6,
    "cache_hits": 4,
    "kline_missing": 1,
    "kline_invalid": 0,
    "baseline_rows": 9,
}
```

Assert Markdown contains an execution section:

```python
self.assertIn("Execution Summary", text)
self.assertIn("shared_baseline: True", text)
self.assertIn("fetch_attempts: 6", text)
self.assertIn("cache_hits: 4", text)
```

**Step 2: Update renderer signature**

Change:

```python
def _render_markdown(results: List[Dict[str, Any]]) -> str:
```

to:

```python
def _render_markdown(payload: Dict[str, Any]) -> str:
```

Inside it:

```python
results = payload.get("policies", [])
execution = payload.get("execution") or {}
```

Keep the existing table and reason summaries.

Append:

```markdown
## Execution Summary
- shared_baseline: True
- snapshot_rows: 2842
- unique_codes: ...
- fetch_attempts: ...
- cache_hits: ...
- kline_missing: ...
- kline_invalid: ...
- baseline_rows: ...
```

If `execution` is missing, either omit the section or write `none`; prefer omitting the section for backward compatibility.

Update `_write_outputs()` to call `_render_markdown(payload)`.

**Step 3: Run tests**

```bash
python3 -m unittest tests.test_policy_experiment_runner_script
```

Expected: OK.

## Task 3: Verification And Real Backtest

**Files:**

- Create: `docs/plans/2026-06-27-chanlun-engine-phase6-9-policy-runner-execution-observability-result.md`

**Step 1: Run full verification**

```bash
python3 -m unittest tests.test_policy_experiment_metrics tests.test_policy_experiment_runner_script
python3 -m unittest tests.test_policy_experiment_metrics tests.test_policy_experiment_runner_script tests.test_historical_experiment_metrics tests.test_engine_experiment_runner_script
python3 -m unittest discover -s tests
python3 -m py_compile chanlun/policy_experiment_metrics.py scripts/run_policy_experiments.py
git diff --check
```

**Step 2: Run real policy backtest**

```bash
/usr/bin/time -p python3 scripts/run_policy_experiments.py \
  --policies delay1_v1,delay1_v1_bottom_quality_guard,delay1_v1_bottom_distance_gt6_guard,delay1_v1_bottom_missing_shape_guard \
  --output-json /tmp/phase6_9_policy_execution_observability_metrics.json \
  --output-md /tmp/phase6_9_policy_execution_observability_metrics.md
```

**Step 3: Result document must include**

- implementation summary,
- test commands and exact results,
- real backtest command,
- execution summary from output JSON,
- policy metrics table,
- whether policy metrics stayed consistent with Phase 6.8 for the included policies,
- next strategy-side recommendation.

## Acceptance Criteria

- `run_policy_experiment_metrics()` returns top-level `execution`.
- Existing policy metric fields remain compatible.
- Markdown output includes execution summary when available.
- Unit tests cover cache/fetch/missing/invalid counters.
- Full tests pass.
- Real backtest output contains execution summary.
- Result MD is committed.
- Code and docs are pushed.
