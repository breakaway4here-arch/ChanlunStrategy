# Fusion Recommendation Score Phase 4 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add deterministic `recommendation_score` metadata for executable `fusion_strict_startup_rescue_v1` A-class signals without changing filtering or ordering behavior.

**Architecture:** Build on Phase 1 `quality_tier`, Phase 2 `expected_horizon`, and Phase 3 failure audit. Score is additive metadata on tagged A-class signals only. Policy experiment output should expose score summary and bucket distribution for audit. This phase must not sort recommendations, filter samples, or change selected candidate behavior.

**Tech Stack:** Python 3, `unittest`, `chanlun.signal_quality_classifier`, `chanlun.policy_experiment_metrics`, existing `scripts/run_policy_experiments.py`.

---

## Hard Constraints

- Do not modify `chanlun/chan_engine.py`.
- Do not modify `chanlun/engine_core.py`.
- Do not modify `chanlun/engine_signals.py`.
- Do not modify `analyze()`.
- Do not modify `analyze_dual()`.
- Do not change A/B/C execution semantics.
- Do not sort recommendations by score in this phase.
- Do not filter or downgrade by score in this phase.
- Do not add user-facing recommendation text in this phase.
- Do not commit or push from 小兵. Main thread will review, test, commit, and push.

## Score Rules for Phase 4

Only A-class signals can receive `recommendation_score`.

Base score by `quality_tier`:

| quality_tier | base |
|---|---:|
| `A+` | 92 |
| `A` | 78 |
| `A-` | 64 |

Adjustments:

| Condition | delta | reason |
|---|---:|---|
| `expected_horizon == "T+5"` | +3 | `longer_horizon_bonus` |
| `expected_horizon == "T+1"` | -3 | `short_horizon_penalty` |
| `market_env == "strong"` | -4 | `strong_market_audit_penalty` |
| `quality_tier_reasons` contains `startup_rescue` | -4 | `startup_rescue_penalty` |
| `quality_tier_reasons` contains `volatility_near_limit` | -6 | `volatility_near_limit_penalty` |

Clamp:

```python
score = max(0.0, min(100.0, round(score, 1)))
```

Expected examples:

- `A+` + `T+5` + strong market: `92 + 3 - 4 = 91`
- `A` + `T+3` + weak market: `78`
- `A-` + `T+1` + startup rescue: `64 - 3 - 4 = 57`

## Score Buckets

For policy experiment summary:

| Bucket | Range |
|---|---|
| `high` | `score >= 85` |
| `medium` | `70 <= score < 85` |
| `low` | `score < 70` |

## Task 1: Add Failing Unit Tests

**Files:**

- Modify: `tests/test_signal_quality_classifier.py`

**Step 1: Import new helpers**

Add imports:

```python
calculate_signal_recommendation_score,
explain_signal_recommendation_score,
```

**Step 2: Add score tests**

Add near Phase 2 horizon tests:

```python
def test_recommendation_score_for_a_plus(self):
    signal = {
        "type": "强势启动候选",
        "trend_strength": 3.0,
        "volatility": 0.05,
        "pivot": {"ZG": 12, "ZD": 10},
        "segment": {"high": 12, "low": 10},
        "market_env": "strong",
    }

    self.assertEqual(
        calculate_signal_recommendation_score(signal, profile="fusion_strict_startup_rescue_v1"),
        91.0,
    )
    self.assertEqual(
        explain_signal_recommendation_score(signal, profile="fusion_strict_startup_rescue_v1"),
        ["tier:A+", "longer_horizon_bonus", "strong_market_audit_penalty"],
    )
```

```python
def test_recommendation_score_for_standard_a(self):
    signal = {
        "type": "一买",
        "trend_strength": 2.0,
        "volatility": 0.07,
        "pivot": {"ZG": 12, "ZD": 10},
        "segment": {"high": 12, "low": 10},
        "market_env": "weak",
    }

    self.assertEqual(
        calculate_signal_recommendation_score(signal, profile="fusion_strict_startup_rescue_v1"),
        78.0,
    )
    self.assertEqual(
        explain_signal_recommendation_score(signal, profile="fusion_strict_startup_rescue_v1"),
        ["tier:A"],
    )
```

```python
def test_recommendation_score_for_startup_rescue(self):
    signal = {
        "type": "强势启动候选",
        "trend_strength": 1.0,
        "volatility": 0.05,
        "pivot": None,
        "segment": {"high": 12, "low": 10},
        "market_env": "weak",
    }

    self.assertEqual(
        calculate_signal_recommendation_score(signal, profile="fusion_strict_startup_rescue_v1"),
        57.0,
    )
    self.assertEqual(
        explain_signal_recommendation_score(signal, profile="fusion_strict_startup_rescue_v1"),
        ["tier:A-", "short_horizon_penalty", "startup_rescue_penalty"],
    )
```

```python
def test_recommendation_score_ignores_non_a(self):
    signal = {
        "type": "底背驰候选",
        "trend_strength": 1.0,
        "volatility": 0.08,
        "pivot": {"ZG": 12, "ZD": 10},
        "segment": {"high": 12, "low": 10},
    }

    self.assertIsNone(
        calculate_signal_recommendation_score(signal, profile="fusion_strict_startup_rescue_v1"),
    )
    self.assertEqual(
        explain_signal_recommendation_score(signal, profile="fusion_strict_startup_rescue_v1"),
        [],
    )
```

**Step 3: Add tag metadata assertions**

Extend the existing tag metadata test:

```python
self.assertEqual(tagged_a["recommendation_score"], 57.0)
self.assertEqual(
    tagged_a["recommendation_score_reasons"],
    ["tier:A-", "short_horizon_penalty", "startup_rescue_penalty"],
)
self.assertNotIn("recommendation_score", tagged_b)
self.assertNotIn("recommendation_score_reasons", tagged_b)
```

**Step 4: Run tests and verify red**

Run:

```bash
python3 -m unittest tests.test_signal_quality_classifier
```

Expected:

- Fails because score helpers do not exist.

## Task 2: Implement Score Helpers

**Files:**

- Modify: `chanlun/signal_quality_classifier.py`

**Step 1: Add `explain_signal_recommendation_score`**

Implementation outline:

```python
def explain_signal_recommendation_score(signal: Any, profile: str = _DEFAULT_FUSION_PROFILE) -> List[str]:
    if not isinstance(signal, Mapping):
        return []

    normalized_profile = _normalize_profile(profile)
    if classify_signal(signal, profile=normalized_profile) != "A":
        return []

    tier = signal.get("quality_tier")
    if tier not in {"A+", "A", "A-"}:
        tier = classify_signal_tier(signal, profile=normalized_profile)
    if tier not in {"A+", "A", "A-"}:
        return []

    horizon = signal.get("expected_horizon")
    if horizon not in {"T+1", "T+3", "T+5"}:
        horizon = classify_signal_expected_horizon(signal, profile=normalized_profile)

    tier_reasons = signal.get("quality_tier_reasons")
    if not isinstance(tier_reasons, list):
        tier_reasons = explain_signal_tier(signal, profile=normalized_profile)

    _, context = _context_for_signal(signal)
    market_env = (
        context.get("market_env")
        or signal.get("market_env")
        or signal.get("market_regime")
        or signal.get("market_trend")
    )

    reasons = [f"tier:{tier}"]
    if horizon == "T+5":
        reasons.append("longer_horizon_bonus")
    if horizon == "T+1":
        reasons.append("short_horizon_penalty")
    if _is_strong_market_env(market_env):
        reasons.append("strong_market_audit_penalty")
    if "startup_rescue" in tier_reasons:
        reasons.append("startup_rescue_penalty")
    if "volatility_near_limit" in tier_reasons:
        reasons.append("volatility_near_limit_penalty")
    return reasons
```

**Step 2: Add `calculate_signal_recommendation_score`**

Implementation outline:

```python
def calculate_signal_recommendation_score(signal: Any, profile: str = _DEFAULT_FUSION_PROFILE) -> Optional[float]:
    reasons = explain_signal_recommendation_score(signal, profile=profile)
    if not reasons:
        return None

    tier_reason = reasons[0]
    if tier_reason == "tier:A+":
        score = 92.0
    elif tier_reason == "tier:A-":
        score = 64.0
    else:
        score = 78.0

    deltas = {
        "longer_horizon_bonus": 3.0,
        "short_horizon_penalty": -3.0,
        "strong_market_audit_penalty": -4.0,
        "startup_rescue_penalty": -4.0,
        "volatility_near_limit_penalty": -6.0,
    }
    for reason in reasons[1:]:
        score += deltas.get(reason, 0.0)
    return max(0.0, min(100.0, round(score, 1)))
```

**Step 3: Attach score metadata**

In `tag_signal_quality(...)`, after expected horizon metadata for A signals:

```python
score = calculate_signal_recommendation_score(out, profile=_normalize_profile(profile))
if score is not None:
    out["recommendation_score"] = score
    out["recommendation_score_reasons"] = explain_signal_recommendation_score(...)
```

For non-A signals, remove stale:

```python
out.pop("recommendation_score", None)
out.pop("recommendation_score_reasons", None)
```

Mirror in `tag_signal_quality_in_place(...)`.

**Step 4: Run targeted tests**

Run:

```bash
python3 -m unittest tests.test_signal_quality_classifier
```

Expected:

- All tests pass.

## Task 3: Add Policy Experiment Score Summary

**Files:**

- Modify: `chanlun/policy_experiment_metrics.py`
- Modify: `tests/test_policy_experiment_metrics.py`

**Step 1: Import helper**

```python
calculate_signal_recommendation_score
```

**Step 2: Add score summary helpers**

Add:

```python
def _score_bucket(score: Optional[float]) -> str:
    if score is None:
        return "unknown"
    if score >= 85:
        return "high"
    if score >= 70:
        return "medium"
    return "low"
```

Add:

```python
def _build_score_summary(scores: Sequence[float]) -> dict:
    values = [float(x) for x in scores if x is not None]
    if not values:
        return {"count": 0, "mean": None, "min": None, "max": None}
    return {
        "count": len(values),
        "mean": round(sum(values) / len(values), 2),
        "min": round(min(values), 2),
        "max": round(max(values), 2),
    }
```

**Step 3: Include in fusion row**

Inside `_summarize_fusion_variant(...)`, when accepted:

```python
score = calculate_signal_recommendation_score(signal, profile=variant_name)
if score is not None:
    scores.append(score)
    score_bucket_counts[_score_bucket(score)] += 1
```

Return:

```python
"recommendation_score_summary": _build_score_summary(scores),
"recommendation_score_bucket_distribution": dict(sorted(score_bucket_counts.items())),
```

Do not use score in ranking.

**Step 4: Update policy test**

For the mocked rescue profile:

- standard A score should be `78.0` -> medium
- startup rescue score should be `57.0` -> low

Assert:

```python
self.assertEqual(
    rescue_profile["recommendation_score_bucket_distribution"],
    {"low": 1, "medium": 1},
)
self.assertEqual(rescue_profile["recommendation_score_summary"]["count"], 2)
self.assertEqual(rescue_profile["recommendation_score_summary"]["min"], 57.0)
self.assertEqual(rescue_profile["recommendation_score_summary"]["max"], 78.0)
self.assertEqual(rescue_profile["recommendation_score_summary"]["mean"], 67.5)
```

**Step 5: Run policy tests**

Run:

```bash
python3 -m unittest tests.test_policy_experiment_metrics
```

Expected:

- All tests pass.

## Task 4: Backtest and Document Phase 4 Result

**Files:**

- Create: `docs/plans/2026-06-29-fusion-recommendation-score-phase4-result.md`

**Step 1: Run backtest**

Run:

```bash
python3 scripts/run_policy_experiments.py \
  --policies fusion_strict_startup_rescue_v1 \
  --business-metrics \
  --output-json /tmp/fusion_recommendation_score_phase4_report.json \
  --output-md /tmp/fusion_recommendation_score_phase4_report.md
```

Expected:

- Sample count remains `123`.
- JSON includes score summary and bucket distribution.

**Step 2: Write result doc**

Create result doc:

```markdown
# 2026-06-29 Fusion Recommendation Score Phase 4 Result

## Goal

Add recommendation score metadata without changing execution or sorting.

## Result

| Metric | Value |
|---|---:|
| samples | ... |
| score mean | ... |
| score min | ... |
| score max | ... |

## Score Buckets

| Bucket | Count |
|---|---:|
| high | ... |
| medium | ... |
| low | ... |

## Conclusion

- Execution sample count unchanged.
- Score is ready for a later sorting experiment, but not active yet.
```

## Task 5: Final Verification

Run:

```bash
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
  - `chanlun/signal_quality_classifier.py`
  - `chanlun/policy_experiment_metrics.py`
  - `tests/test_signal_quality_classifier.py`
  - `tests/test_policy_experiment_metrics.py`
  - `docs/plans/2026-06-29-fusion-recommendation-score-phase4-result.md`

## Hand-Off Notes for 小兵

- Work directly from this plan.
- Do not activate sorting.
- Do not filter by score.
- Do not add user-facing recommendation reasons.
- Do not commit.
- Do not push.
- Report:
  - files changed
  - red test failure summary
  - targeted test result
  - backtest command and score summary
  - full verification result
