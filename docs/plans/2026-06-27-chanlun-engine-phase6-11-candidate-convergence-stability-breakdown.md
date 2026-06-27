# ChanLun Engine Phase 6.11 Candidate Convergence Stability Breakdown Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Converge Phase 6.10 to `delay1_v1_bottom_quality_market_known_guard` as the main candidate and add retained/filtered breakdowns so the improvement can be explained by market state, buy-point type, and confirmations.

**Architecture:** Keep policy behavior unchanged. Extend each policy result with a diagnostic `breakdown` object computed inside `_run_one_policy()`, then render a compact breakdown summary in Markdown. The breakdown is read-only evidence for promotion decisions and must not affect filtering, returns, deltas, or production `analyze()`.

**Tech Stack:** Python standard library, `unittest`, existing policy backtest runner.

---

## Context

Phase 6.10 tested three weak-trend variants:

```text
delay1_v1_bottom_quality_market_strong_guard
delay1_v1_bottom_quality_market_known_guard
delay1_v1_bottom_quality_market_or_ma_guard
```

All three produced identical metrics:

```text
policy n: 989
T+3: 0.41
T+3 win: 46.8
loss <=5: 17.7
big drop <=5: 36.2
retained: 76.85
```

Recommendation from Phase 6.10:

```text
delay1_v1_bottom_quality_market_known_guard
```

Reason:

- The extra 112 filtered samples are better described as `market_regime` unknown.
- `market_known_guard` is more conservative than treating unknown as weak/non-strong.
- It is easier to justify before any promotion gate.

## Non-Goals

- Do not remove the other two Phase 6.10 policies yet.
- Do not change policy filtering behavior.
- Do not change production `analyze()`.
- Do not add new data sources.
- Do not add promotion to production.
- Do not use wall-clock time in tests.

## Output Contract

Each policy result should include:

```json
{
  "breakdown": {
    "market_regime": {
      "strong": {
        "total": 10,
        "accepted": 8,
        "filtered": 2,
        "filter_reasons": {
          "bottom_quality_guard": 1,
          "bottom_market_unknown": 1
        }
      }
    },
    "best_buy_point_type": {
      "底背驰候选": {
        "total": 10,
        "accepted": 8,
        "filtered": 2,
        "filter_reasons": {}
      }
    },
    "confirmations": {
      "关键位不破 + 30min底分型": {
        "total": 6,
        "accepted": 4,
        "filtered": 2,
        "filter_reasons": {}
      }
    }
  }
}
```

Field rules:

- `total`: count of shared baseline rows in that bucket before policy filtering.
- `accepted`: count of rows retained by that policy.
- `filtered`: count of rows filtered by that policy.
- `filter_reasons`: reason counts for filtered rows only.

Bucket rules:

- `market_regime`: `str(pick.get("market_regime") or "").strip().lower()`, empty -> `unknown`.
- `best_buy_point_type`: `pick["best_buy_point"]["type"]` if present, otherwise `unknown`.
- `confirmations`: sorted confirmations joined by ` + `, empty -> `none`.

Existing fields must remain compatible:

- `coverage`
- `baseline_summary`
- `policy_summary`
- `delta`
- top-level `execution`

## Task 1: Add Breakdown Helpers And Policy Result Field

**Files:**

- Modify: `chanlun/policy_experiment_metrics.py`
- Test: `tests/test_policy_experiment_metrics.py`

**Step 1: Write failing tests**

Add a test that mocks three rows:

```text
row 1: market_regime=strong, type=底背驰候选, confirmations=["关键位不破", "30min底分型", "止跌结构"], should be accepted
row 2: market_regime="", type=底背驰候选, confirmations=["关键位不破", "30min底分型", "止跌结构"], should be filtered by market_known_guard
row 3: market_regime=strong, type=强势启动候选, confirmations=[], should be accepted
```

Run:

```bash
python3 -m unittest tests.test_policy_experiment_metrics
```

Expected before implementation: failure because `breakdown` is missing.

**Step 2: Add bucket helpers**

Add internal helpers:

```python
def _market_regime_bucket(pick: Optional[dict]) -> str:
    value = str((pick or {}).get("market_regime") or "").strip().lower()
    return value or "unknown"


def _best_buy_point_type_bucket(pick: Optional[dict]) -> str:
    bbp = (pick or {}).get("best_buy_point") or {}
    value = str(bbp.get("type") or "").strip()
    return value or "unknown"


def _confirmations_bucket(pick: Optional[dict]) -> str:
    bbp = (pick or {}).get("best_buy_point") or {}
    values = sorted(_as_str_list(bbp.get("confirmations")))
    return " + ".join(values) if values else "none"
```

Add:

```python
def _new_breakdown_bucket() -> dict:
    return {"total": 0, "accepted": 0, "filtered": 0, "filter_reasons": {}}
```

Add recording helper:

```python
def _record_breakdown(
    breakdown: Dict[str, Dict[str, dict]],
    pick: Optional[dict],
    accepted: bool,
    filter_reason: str = "",
) -> None:
    dimensions = {
        "market_regime": _market_regime_bucket(pick),
        "best_buy_point_type": _best_buy_point_type_bucket(pick),
        "confirmations": _confirmations_bucket(pick),
    }
    ...
```

Implementation requirements:

- Increment `total` for each dimension bucket.
- Increment `accepted` if retained.
- Increment `filtered` if filtered.
- If filtered and `filter_reason` is non-empty, increment that bucket's `filter_reasons[filter_reason]`.

**Step 3: Wire into `_run_one_policy()`**

Initialize:

```python
policy_breakdown = {
    "market_regime": {},
    "best_buy_point_type": {},
    "confirmations": {},
}
```

When filtered:

```python
_record_breakdown(policy_breakdown, pick, accepted=False, filter_reason=reason)
```

When retained:

```python
_record_breakdown(policy_breakdown, pick, accepted=True)
```

Return:

```python
"breakdown": policy_breakdown
```

Important:

- A row must be counted exactly once per dimension.
- Breakdown counts must add up to `baseline_evaluated` per dimension.
- Breakdown must be computed after baseline filtering, because policies only consume shared baseline rows.

**Step 4: Add unit assertions**

Assert for `delay1_v1_bottom_quality_market_known_guard`:

```python
breakdown["market_regime"]["strong"]["accepted"] == 2
breakdown["market_regime"]["unknown"]["filtered"] == 1
breakdown["market_regime"]["unknown"]["filter_reasons"]["bottom_market_unknown"] == 1
breakdown["best_buy_point_type"]["底背驰候选"]["total"] == 2
breakdown["best_buy_point_type"]["强势启动候选"]["accepted"] == 1
```

Run:

```bash
python3 -m unittest tests.test_policy_experiment_metrics
```

Expected: OK.

## Task 2: Render Compact Breakdown Summary In Markdown

**Files:**

- Modify: `scripts/run_policy_experiments.py`
- Test: `tests/test_policy_experiment_runner_script.py`

**Step 1: Write failing Markdown test**

Extend fake payload with:

```python
"breakdown": {
    "market_regime": {
        "strong": {"total": 6, "accepted": 5, "filtered": 1, "filter_reasons": {"bottom_quality_guard": 1}},
        "unknown": {"total": 4, "accepted": 3, "filtered": 1, "filter_reasons": {"bottom_market_unknown": 1}},
    },
    "best_buy_point_type": {
        "底背驰候选": {"total": 8, "accepted": 6, "filtered": 2, "filter_reasons": {}},
    },
    "confirmations": {
        "关键位不破 + 30min底分型": {"total": 5, "accepted": 4, "filtered": 1, "filter_reasons": {}},
    },
}
```

Assert Markdown includes:

```text
Breakdown Summary
market_regime
unknown
bottom_market_unknown
best_buy_point_type
```

**Step 2: Add renderer helpers**

Add:

```python
def _format_reason_counts(reasons: Dict[str, Any]) -> str:
    ...
```

Add:

```python
def _render_breakdown_section(results: List[Dict[str, Any]]) -> List[str]:
    ...
```

Rendering rules:

- Omit section if no policy has `breakdown`.
- Include dimensions:
  - `market_regime`
  - `best_buy_point_type`
  - `confirmations`
- For `confirmations`, only render top 10 buckets by `total` descending to keep Markdown readable.
- Render lines like:

```markdown
## Breakdown Summary
### delay1_v1_bottom_quality_market_known_guard
#### market_regime
- unknown: total=112, accepted=0, filtered=112, reasons=bottom_market_unknown:112
```

Existing summary sections must remain unchanged.

**Step 3: Run script tests**

```bash
python3 -m unittest tests.test_policy_experiment_runner_script
```

Expected: OK.

## Task 3: Verification And Real Backtest

**Files:**

- Create: `docs/plans/2026-06-27-chanlun-engine-phase6-11-candidate-convergence-stability-breakdown-result.md`

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
  --policies delay1_v1,delay1_v1_bottom_quality_guard,delay1_v1_bottom_quality_market_known_guard,delay1_v1_bottom_distance_gt6_guard,delay1_v1_bottom_missing_shape_guard \
  --output-json /tmp/phase6_11_candidate_convergence_stability_metrics.json \
  --output-md /tmp/phase6_11_candidate_convergence_stability_metrics.md
```

Result doc must include:

- exact test results,
- real backtest command and timing,
- execution summary,
- policy metrics table,
- breakdown highlights for `market_regime`, `best_buy_point_type`, and confirmations,
- recommendation: keep/reject `delay1_v1_bottom_quality_market_known_guard` for promotion-gate planning.

## Acceptance Criteria

- Each policy result contains `breakdown`.
- Breakdown counts are deterministic and covered by tests.
- Markdown renders compact breakdown summary.
- Existing policy metrics remain unchanged.
- Full tests pass.
- Real backtest completes.
- Result MD is committed and pushed.

## Promotion-Gate Readiness

`delay1_v1_bottom_quality_market_known_guard` is ready for promotion-gate planning only if:

- It keeps Phase 6.10 improvements in the larger policy set.
- The breakdown confirms the extra filtering is concentrated in `market_regime=unknown`.
- No unexpected filtering appears in non-bottom candidate types.
- Retained ratio remains >= 70%.
