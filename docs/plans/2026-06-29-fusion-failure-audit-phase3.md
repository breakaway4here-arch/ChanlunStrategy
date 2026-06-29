# Fusion Failure Audit Phase 3 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Analyze failed `fusion_strict_startup_rescue_v1` A-class samples and output candidate downgrade/filter conditions without changing execution behavior.

**Architecture:** Build on Phase 1 `quality_tier` and Phase 2 `expected_horizon`. For accepted A-class samples in fusion policy experiment scans, classify failed samples using realized backtest metrics and bucket them by tier, horizon, signal type, and market environment. This phase only emits audit metadata such as `failure_sample_audit`; it must not filter, downgrade, rerank, or alter selected candidate behavior.

**Tech Stack:** Python 3, `unittest`, `chanlun.policy_experiment_metrics`, `chanlun.signal_quality_classifier`, existing `scripts/run_policy_experiments.py`.

---

## Hard Constraints

- Do not modify `chanlun/chan_engine.py`.
- Do not modify `chanlun/engine_core.py`.
- Do not modify `chanlun/engine_signals.py`.
- Do not modify `analyze()`.
- Do not modify `analyze_dual()`.
- Do not change A/B/C execution semantics.
- Do not change `quality_tier` or `expected_horizon` semantics.
- Do not add recommendation score.
- Do not add user-facing recommendation reasons.
- Do not actually downgrade or filter samples in this phase.
- Do not commit or push from 小兵. Main thread will review, test, commit, and push.

## Failure Definition

For Phase 3 audit only:

- failed sample: `t3_close_pct <= 0`
- severe drawdown marker: `max_dd_3d <= -5.0`

Rationale:

- T+3 is the current primary backtest metric.
- Drawdown marker is separately counted so later phases can decide whether to downgrade even if T+3 is positive.

## Audit Output Shape

Each fusion profile row should include:

```python
"failure_sample_audit": {
    "samples": 123,
    "failed_samples": 55,
    "failure_rate_pct": 44.72,
    "severe_drawdown_samples": 10,
    "severe_drawdown_rate_pct": 8.13,
    "bucket_distribution": {
        "quality_tier:A-": 20,
        "expected_horizon:T+1": 20,
        "signal_type:强势启动候选": 20,
        "market_env:weak": 18
    },
    "candidate_conditions": [
        {"condition": "quality_tier=A-", "failed_samples": 20, "failure_rate_pct": 57.14},
        {"condition": "expected_horizon=T+1", "failed_samples": 20, "failure_rate_pct": 57.14}
    ]
}
```

Exact counts above are examples. Tests should use fixture-specific counts.

## Candidate Condition Rule

For each dimension bucket, compute:

- total accepted samples in bucket
- failed samples in bucket
- failure rate

Include a bucket in `candidate_conditions` when:

- bucket total >= 1 in tests, and
- bucket failure rate is greater than overall failure rate

For real data, this is only an audit signal, not an automatic rule.

Dimensions:

- `quality_tier`
- `expected_horizon`
- `signal_type`
- `market_env`

## Task 1: Add Failing Unit Test

**Files:**

- Modify: `tests/test_policy_experiment_metrics.py`

**Step 1: Extend fusion threshold scan test**

In `test_run_policy_experiment_metrics_fusion_threshold_scan`, use the existing mocked accepted rescue profile samples:

- strict original accepted sample: positive `t3_close_pct`
- weak startup rescue accepted sample: negative `t3_close_pct`

Add assertions:

```python
audit = rescue_profile["failure_sample_audit"]
self.assertEqual(audit["samples"], 2)
self.assertEqual(audit["failed_samples"], 1)
self.assertEqual(audit["failure_rate_pct"], 50.0)
self.assertEqual(audit["bucket_distribution"]["quality_tier:A-"], 1)
self.assertEqual(audit["bucket_distribution"]["expected_horizon:T+1"], 1)
self.assertEqual(audit["bucket_distribution"]["signal_type:强势启动候选"], 1)
self.assertEqual(audit["bucket_distribution"]["market_env:weak"], 1)
self.assertIn(
    {"condition": "quality_tier=A-", "failed_samples": 1, "failure_rate_pct": 100.0},
    audit["candidate_conditions"],
)
```

If exact `candidate_conditions` ordering differs, assert by building a set of condition names and checking metrics for the specific condition.

**Step 2: Run test and verify red**

Run:

```bash
python3 -m unittest tests.test_policy_experiment_metrics.PolicyExperimentMetricsTests.test_run_policy_experiment_metrics_fusion_threshold_scan
```

Expected:

- Fails because `failure_sample_audit` does not exist yet.

## Task 2: Implement Failure Audit Helpers

**Files:**

- Modify: `chanlun/policy_experiment_metrics.py`

**Step 1: Add small helpers near fusion scan helpers**

Add:

```python
def _sample_failed(sample: Optional[dict]) -> bool:
    try:
        value = sample.get("t3_close_pct")
    except AttributeError:
        return False
    return value is not None and float(value) <= 0.0
```

Add:

```python
def _sample_severe_drawdown(sample: Optional[dict]) -> bool:
    try:
        value = sample.get("max_dd_3d")
    except AttributeError:
        return False
    return value is not None and float(value) <= -5.0
```

Add a percent helper reuse existing `_to_pct(failed, total)`.

**Step 2: Add accepted sample metadata**

Inside `_summarize_fusion_variant(...)`, when a pick is accepted:

- compute existing `tier`
- compute existing `horizon`
- compute:

```python
signal_type = _best_buy_point_type_bucket(pick)
market_env = _market_regime_bucket(pick)
accepted_audit_rows.append({
    "sample": item["baseline_sample"],
    "quality_tier": tier,
    "expected_horizon": horizon,
    "signal_type": signal_type,
    "market_env": market_env,
})
```

**Step 3: Build audit object**

Add helper:

```python
def _build_failure_sample_audit(rows: Sequence[dict]) -> dict:
    total = len(rows)
    failed_rows = [row for row in rows if _sample_failed(row.get("sample"))]
    severe_rows = [row for row in rows if _sample_severe_drawdown(row.get("sample"))]

    total_by_condition = Counter()
    failed_by_condition = Counter()
    for row in rows:
        conditions = [
            f"quality_tier:{row.get('quality_tier') or 'unknown'}",
            f"expected_horizon:{row.get('expected_horizon') or 'unknown'}",
            f"signal_type:{row.get('signal_type') or 'unknown'}",
            f"market_env:{row.get('market_env') or 'unknown'}",
        ]
        for condition in conditions:
            total_by_condition[condition] += 1
            if _sample_failed(row.get("sample")):
                failed_by_condition[condition] += 1

    overall_failure_rate = (len(failed_rows) / total * 100.0) if total else 0.0
    candidate_conditions = []
    for condition, failed_count in sorted(failed_by_condition.items()):
        condition_total = total_by_condition.get(condition, 0)
        if condition_total <= 0:
            continue
        failure_rate = round(failed_count / condition_total * 100.0, 2)
        if failure_rate > overall_failure_rate:
            candidate_conditions.append({
                "condition": condition.replace(":", "="),
                "failed_samples": failed_count,
                "failure_rate_pct": failure_rate,
            })

    return {
        "samples": total,
        "failed_samples": len(failed_rows),
        "failure_rate_pct": _to_pct(len(failed_rows), total),
        "severe_drawdown_samples": len(severe_rows),
        "severe_drawdown_rate_pct": _to_pct(len(severe_rows), total),
        "bucket_distribution": dict(sorted(failed_by_condition.items())),
        "candidate_conditions": candidate_conditions,
    }
```

**Step 4: Include in fusion row**

In `_summarize_fusion_variant(...)` returned row:

```python
"failure_sample_audit": _build_failure_sample_audit(accepted_audit_rows),
```

Do not use audit output in ranking.

## Task 3: Run Targeted Tests

Run:

```bash
python3 -m unittest tests.test_policy_experiment_metrics
python3 -m unittest tests.test_signal_quality_classifier tests.test_policy_experiment_metrics
```

Expected:

- All tests pass.

## Task 4: Backtest and Document Phase 3 Result

**Files:**

- Create: `docs/plans/2026-06-29-fusion-failure-audit-phase3-result.md`

**Step 1: Run backtest**

Run:

```bash
python3 scripts/run_policy_experiments.py \
  --policies fusion_strict_startup_rescue_v1 \
  --business-metrics \
  --output-json /tmp/fusion_failure_audit_phase3_report.json \
  --output-md /tmp/fusion_failure_audit_phase3_report.md
```

Expected:

- Same sample count as guard/Phase 1/Phase 2 baseline: `123`.
- JSON includes `failure_sample_audit`.

**Step 2: Write result doc**

Create `docs/plans/2026-06-29-fusion-failure-audit-phase3-result.md`:

```markdown
# 2026-06-29 Fusion Failure Audit Phase 3 Result

## Goal

Analyze failed A-class samples and output downgrade/filter candidate conditions without changing execution.

## Backtest Command

...

## Result

| Metric | Value |
|---|---:|
| samples | ... |
| failed_samples | ... |
| failure_rate_pct | ... |
| severe_drawdown_samples | ... |

## Top Failure Buckets

| Bucket | Failed Samples |
|---|---:|
| ... | ... |

## Candidate Conditions

| Condition | Failed Samples | Failure Rate |
|---|---:|---:|
| ... | ... | ... |

## Conclusion

- No execution sample count changed.
- List which buckets should be considered in Phase 4/next filter experiment.
```

## Task 5: Final Verification

Run:

```bash
python3 -m unittest tests.test_policy_experiment_metrics
python3 -m unittest tests.test_signal_quality_classifier tests.test_policy_experiment_metrics
python3 -m unittest discover -s tests
python3 -m py_compile chanlun/signal_quality_classifier.py chanlun/policy_experiment_metrics.py scripts/run_policy_experiments.py
git diff --check
git status --short
```

Expected:

- Targeted tests pass.
- Full suite passes.
- py_compile passes.
- `git diff --check` has no output.
- Only intended files are modified:
  - `chanlun/policy_experiment_metrics.py`
  - `tests/test_policy_experiment_metrics.py`
  - `docs/plans/2026-06-29-fusion-failure-audit-phase3-result.md`

## Hand-Off Notes for 小兵

- Work directly from this plan.
- Do not implement actual downgrade/filter behavior.
- Do not add recommendation score.
- Do not add user-facing recommendation reasons.
- Do not commit.
- Do not push.
- Report:
  - files changed
  - red test failure summary
  - targeted test result
  - backtest command and failure audit summary
  - full verification result
