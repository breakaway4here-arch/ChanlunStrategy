# Fusion Quality Tier Phase 1 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add additive A+/A/A- quality tiers for `fusion_strict_startup_rescue_v1` A-class signals without changing A/B/C execution semantics.

**Architecture:** Keep `classify_signal()` returning the existing `A/B/C` category. Add a new tier helper that evaluates already-classified A signals and returns `A+`, `A`, or `A-` plus reason codes. `tag_signal_quality()` and related tagging helpers should attach `quality_tier` and `quality_tier_reasons` to A-class signals only; B/C signals should not become executable and should not receive an A-tier.

**Tech Stack:** Python 3, `unittest`, `chanlun.signal_quality_classifier`, `tests/test_signal_quality_classifier.py`.

---

## Hard Constraints

- Do not modify `chanlun/chan_engine.py`.
- Do not modify `chanlun/engine_core.py`.
- Do not modify `chanlun/engine_signals.py`.
- Do not modify `analyze()`.
- Do not modify `analyze_dual()`.
- Do not change `category` semantics.
- Do not change `filter_executable_signals()` eligibility except for adding tier metadata to returned A signals.
- Do not introduce `expected_horizon`, `recommendation_score`, or user-facing recommendation text in this phase.
- Do not commit or push from 小兵. Main thread will review, test, commit, and push.

## Tier Rules for Phase 1

Only signals with `category == "A"` can receive an A-tier.

### A+

Signal is A-class and all are true:

- `trend_strength >= 2.5`
- `volatility <= 0.08`
- `pivot` exists
- `segment` exists
- not choppy
- not a weak-startup rescue

Reason codes:

- `strong_trend`
- `low_volatility`
- `complete_structure`

### A

Signal is A-class but neither A+ nor A-.

Reason codes:

- `standard_a`

### A-

Signal is A-class and any are true:

- it entered A only through the `fusion_strict_startup_rescue_v1` rescue branch:
  - `trend_strength == 1.0`
  - `signal_type == "强势启动候选"`
  - market is not strong
  - not choppy
- OR volatility is near the high side of the allowed A range:
  - `0.08 < volatility <= LOW_VOLATILITY_MAX`

Reason codes:

- `startup_rescue` when it is the rescue branch
- `volatility_near_limit` when volatility is near the allowed upper bound

## Task 1: Add Failing Unit Tests

**Files:**

- Modify: `tests/test_signal_quality_classifier.py`

**Step 1: Import new helpers**

Add imports:

```python
from chanlun.signal_quality_classifier import (
    classify_signal_tier,
    explain_signal_tier,
)
```

Keep existing imports.

**Step 2: Add A+ test**

Add near existing fusion profile tests:

```python
def test_classify_signal_tier_marks_high_confidence_as_a_plus(self):
    signal = {
        "type": "强势启动候选",
        "trend_strength": 3.0,
        "volatility": 0.05,
        "pivot": {"ZG": 12, "ZD": 10},
        "segment": {"high": 12, "low": 10},
        "market_env": "strong",
    }

    self.assertEqual(
        classify_signal(signal, profile="fusion_strict_startup_rescue_v1"),
        "A",
    )
    self.assertEqual(
        classify_signal_tier(signal, profile="fusion_strict_startup_rescue_v1"),
        "A+",
    )
    self.assertEqual(
        explain_signal_tier(signal, profile="fusion_strict_startup_rescue_v1"),
        ["strong_trend", "low_volatility", "complete_structure"],
    )
```

**Step 3: Add A- rescue test**

```python
def test_classify_signal_tier_marks_rescue_as_a_minus(self):
    signal = {
        "type": "强势启动候选",
        "trend_strength": 1.0,
        "volatility": 0.05,
        "pivot": None,
        "segment": {"high": 12, "low": 10},
        "market_env": "weak",
    }

    self.assertEqual(
        classify_signal(signal, profile="fusion_strict_startup_rescue_v1"),
        "A",
    )
    self.assertEqual(
        classify_signal_tier(signal, profile="fusion_strict_startup_rescue_v1"),
        "A-",
    )
    self.assertEqual(
        explain_signal_tier(signal, profile="fusion_strict_startup_rescue_v1"),
        ["startup_rescue"],
    )
```

**Step 4: Add A standard test**

```python
def test_classify_signal_tier_marks_standard_a(self):
    signal = {
        "type": "一买",
        "trend_strength": 2.0,
        "volatility": 0.07,
        "pivot": {"ZG": 12, "ZD": 10},
        "segment": {"high": 12, "low": 10},
        "market_env": "weak",
    }

    self.assertEqual(
        classify_signal_tier(signal, profile="fusion_strict_startup_rescue_v1"),
        "A",
    )
    self.assertEqual(
        explain_signal_tier(signal, profile="fusion_strict_startup_rescue_v1"),
        ["standard_a"],
    )
```

**Step 5: Add non-A test**

```python
def test_classify_signal_tier_ignores_non_a_signals(self):
    signal = {
        "type": "底背驰候选",
        "trend_strength": 1.0,
        "volatility": 0.08,
        "pivot": {"ZG": 12, "ZD": 10},
        "segment": {"high": 12, "low": 10},
    }

    self.assertEqual(
        classify_signal(signal, profile="fusion_strict_startup_rescue_v1"),
        "B",
    )
    self.assertIsNone(
        classify_signal_tier(signal, profile="fusion_strict_startup_rescue_v1"),
    )
    self.assertEqual(
        explain_signal_tier(signal, profile="fusion_strict_startup_rescue_v1"),
        [],
    )
```

**Step 6: Add tag metadata test**

```python
def test_tag_signal_quality_adds_quality_tier_for_a_only(self):
    a_signal = {
        "type": "强势启动候选",
        "trend_strength": 1.0,
        "volatility": 0.05,
        "pivot": None,
        "segment": {"high": 12, "low": 10},
        "market_env": "weak",
    }
    b_signal = {
        "type": "底背驰候选",
        "trend_strength": 1.0,
        "volatility": 0.08,
        "pivot": {"ZG": 12, "ZD": 10},
        "segment": {"high": 12, "low": 10},
    }

    tagged_a = tag_signal_quality(
        a_signal,
        profile="fusion_strict_startup_rescue_v1",
    )
    tagged_b = tag_signal_quality(
        b_signal,
        profile="fusion_strict_startup_rescue_v1",
    )

    self.assertEqual(tagged_a["category"], "A")
    self.assertEqual(tagged_a["quality_tier"], "A-")
    self.assertEqual(tagged_a["quality_tier_reasons"], ["startup_rescue"])
    self.assertEqual(tagged_b["category"], "B")
    self.assertNotIn("quality_tier", tagged_b)
    self.assertNotIn("quality_tier_reasons", tagged_b)
```

**Step 7: Run tests and verify red**

Run:

```bash
python3 -m unittest tests.test_signal_quality_classifier
```

Expected:

- Fails because `classify_signal_tier` and `explain_signal_tier` do not exist yet.

## Task 2: Implement Tier Helpers

**Files:**

- Modify: `chanlun/signal_quality_classifier.py`

**Step 1: Add internal context helper**

Add a helper to avoid duplicating context extraction:

```python
def _context_for_signal(signal: Any) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    if not isinstance(signal, Mapping):
        return {}, {}
    context = signal.get("context")
    if not isinstance(context, Mapping):
        context = build_signal_context(signal, signal)
    return signal, context
```

Use it only where it keeps the patch simple. Do not refactor unrelated code.

**Step 2: Add rescue detection helper**

```python
def _is_startup_rescue_candidate(context: Mapping[str, Any], signal: Mapping[str, Any], profile: str) -> bool:
    signal_type = str(signal.get("type", context.get("type", "")))
    market_env = (
        context.get("market_env")
        or signal.get("market_env")
        or signal.get("market_regime")
        or signal.get("market_trend")
    )
    trend_strength = _to_float(context.get("trend_strength"))
    trend_type = context.get("trend_type")
    return (
        profile == _FUSION_PROFILE_STRICT_STARTUP_RESCUE_V1
        and trend_strength == 1.0
        and signal_type == "强势启动候选"
        and not _is_strong_market_env(market_env)
        and not _to_bool_choppy(trend_type)
    )
```

**Step 3: Add `explain_signal_tier`**

```python
def explain_signal_tier(signal: Any, profile: str = _DEFAULT_FUSION_PROFILE) -> list[str]:
    if not isinstance(signal, Mapping):
        return []

    normalized_profile = _normalize_profile(profile)
    if classify_signal(signal, profile=normalized_profile) != "A":
        return []

    signal_obj, context = _context_for_signal(signal)
    trend_strength = _to_float(context.get("trend_strength"))
    volatility = _to_float(context.get("volatility"))
    pivot = context.get("pivot")
    segment = context.get("segment")

    reasons = []
    if _is_startup_rescue_candidate(context, signal_obj, normalized_profile):
        reasons.append("startup_rescue")

    if volatility is not None and _LOW_VOLATILITY_MAX >= volatility > 0.08:
        reasons.append("volatility_near_limit")

    if reasons:
        return reasons

    if (
        trend_strength is not None
        and trend_strength >= 2.5
        and volatility is not None
        and volatility <= 0.08
        and bool(pivot)
        and bool(segment)
    ):
        return ["strong_trend", "low_volatility", "complete_structure"]

    return ["standard_a"]
```

**Step 4: Add `classify_signal_tier`**

```python
def classify_signal_tier(signal: Any, profile: str = _DEFAULT_FUSION_PROFILE) -> Optional[str]:
    reasons = explain_signal_tier(signal, profile=profile)
    if not reasons:
        return None
    if "startup_rescue" in reasons or "volatility_near_limit" in reasons:
        return "A-"
    if reasons == ["strong_trend", "low_volatility", "complete_structure"]:
        return "A+"
    return "A"
```

**Step 5: Attach tier metadata in tag helpers**

In `tag_signal_quality(...)`:

- after setting `out["category"]`, if it is A:

```python
tier = classify_signal_tier(out, profile=_normalize_profile(profile))
if tier:
    out["quality_tier"] = tier
    out["quality_tier_reasons"] = explain_signal_tier(out, profile=_normalize_profile(profile))
```

- if category is not A, ensure the copied output does not retain stale tier fields:

```python
out.pop("quality_tier", None)
out.pop("quality_tier_reasons", None)
```

In `tag_signal_quality_in_place(...)`:

- mirror the same behavior for dict mutation.

**Step 6: Run targeted tests**

Run:

```bash
python3 -m unittest tests.test_signal_quality_classifier
```

Expected:

- All tests pass.

## Task 3: Add Policy Experiment Tier Audit Summary

**Files:**

- Modify: `chanlun/policy_experiment_metrics.py`
- Modify: `tests/test_policy_experiment_metrics.py`

**Step 1: Import tier helper**

In `chanlun/policy_experiment_metrics.py`, import:

```python
classify_signal_tier
```

**Step 2: Add tier distribution to fusion profile rows**

Inside `_summarize_fusion_variant(...)`, when a pick is accepted as A:

- Build signal via existing `_build_fusion_pick_signal(pick)`.
- Compute tier:

```python
tier = classify_signal_tier(signal, profile=variant_name) or "A"
tier_counts[tier] += 1
```

- Include this in the returned row:

```python
"quality_tier_distribution": dict(sorted(tier_counts.items())),
```

Do not change ranking or selected candidate in Phase 1.

**Step 3: Update policy metrics test**

In `test_run_policy_experiment_metrics_fusion_threshold_scan`, assert that `rescue_profile` has a tier distribution, for example:

```python
self.assertEqual(
    rescue_profile["quality_tier_distribution"],
    {"A": 1, "A-": 1},
)
```

Adjust expected distribution to match the fixture exactly after implementation.

**Step 4: Run policy tests**

Run:

```bash
python3 -m unittest tests.test_policy_experiment_metrics
```

Expected:

- All tests pass.

## Task 4: Backtest and Document Phase 1 Result

**Files:**

- Modify or create: `docs/plans/2026-06-29-fusion-quality-tier-phase1-result.md`

**Step 1: Run backtest**

Run:

```bash
python3 scripts/run_policy_experiments.py \
  --policies fusion_strict_startup_rescue_v1 \
  --business-metrics \
  --output-json /tmp/fusion_quality_tier_phase1_report.json \
  --output-md /tmp/fusion_quality_tier_phase1_report.md
```

Expected:

- Same selected candidate behavior as current default.
- JSON includes `quality_tier_distribution` for `fusion_strict_startup_rescue_v1`.

**Step 2: Write result doc**

Create or update `docs/plans/2026-06-29-fusion-quality-tier-phase1-result.md` with:

```markdown
# 2026-06-29 Fusion Quality Tier Phase 1 Result

## Goal

Add A+/A/A- tier metadata without changing A/B/C execution.

## Backtest Command

...

## Result

| Tier | Count |
|---|---:|
| A+ | ... |
| A | ... |
| A- | ... |

## Conclusion

- Whether execution sample count changed. It should not change compared with guard baseline.
- Whether tier distribution is usable for Phase 2 horizon analysis.
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
  - `docs/plans/2026-06-29-fusion-quality-tier-phase1-result.md`

## Hand-Off Notes for 小兵

- Work directly from this plan.
- Do not implement Phase 2/3/4/5.
- Do not add score or recommendation text.
- Do not commit.
- Do not push.
- Report:
  - files changed
  - red test failure summary
  - targeted test result
  - backtest command and tier distribution
  - full verification result
