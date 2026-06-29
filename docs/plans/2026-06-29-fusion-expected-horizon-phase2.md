# Fusion Expected Horizon Phase 2 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add deterministic expected holding horizon metadata (`T+1` / `T+3` / `T+5`) for executable `fusion_strict_startup_rescue_v1` A-class signals.

**Architecture:** Build on Phase 1 `quality_tier` metadata. Keep A/B/C execution semantics unchanged. Add `expected_horizon` and `expected_horizon_reasons` to A-class tagged signals only; B/C signals remain non-executable and should not receive an expected horizon. Add horizon distribution into policy experiment rows for audit/backtest visibility.

**Tech Stack:** Python 3, `unittest`, `chanlun.signal_quality_classifier`, `chanlun.policy_experiment_metrics`, existing `scripts/run_policy_experiments.py`.

---

## Hard Constraints

- Do not modify `chanlun/chan_engine.py`.
- Do not modify `chanlun/engine_core.py`.
- Do not modify `chanlun/engine_signals.py`.
- Do not modify `analyze()`.
- Do not modify `analyze_dual()`.
- Do not change `category` semantics.
- Do not change which signals are executable.
- Do not change `quality_tier` rules from Phase 1 unless a test reveals a direct bug.
- Do not implement failure downgrade/filter rules, recommendation score, or user-facing recommendation text in this phase.
- Do not commit or push from 小兵. Main thread will review, test, commit, and push.

## Horizon Rules for Phase 2

Only A-class signals can receive an expected horizon.

| quality_tier | expected_horizon | reasons |
|---|---|---|
| `A+` | `T+5` | `high_confidence_hold` |
| `A` | `T+3` | `standard_swing` |
| `A-` | `T+1` | `fast_confirm_or_exit` |

Fallback:

- If an A-class signal somehow lacks `quality_tier`, compute it using Phase 1 helper.
- If the tier is unknown, use `T+3` with reason `default_swing`.
- Non-A signals return `None` / no horizon metadata.

## Task 1: Add Failing Unit Tests

**Files:**

- Modify: `tests/test_signal_quality_classifier.py`

**Step 1: Import new helpers**

Add imports:

```python
classify_signal_expected_horizon,
explain_signal_expected_horizon,
```

**Step 2: Add horizon tests**

Add tests near Phase 1 tier tests:

```python
def test_expected_horizon_maps_a_plus_to_t5(self):
    signal = {
        "type": "强势启动候选",
        "trend_strength": 3.0,
        "volatility": 0.05,
        "pivot": {"ZG": 12, "ZD": 10},
        "segment": {"high": 12, "low": 10},
        "market_env": "strong",
    }

    self.assertEqual(
        classify_signal_expected_horizon(signal, profile="fusion_strict_startup_rescue_v1"),
        "T+5",
    )
    self.assertEqual(
        explain_signal_expected_horizon(signal, profile="fusion_strict_startup_rescue_v1"),
        ["high_confidence_hold"],
    )
```

```python
def test_expected_horizon_maps_standard_a_to_t3(self):
    signal = {
        "type": "一买",
        "trend_strength": 2.0,
        "volatility": 0.07,
        "pivot": {"ZG": 12, "ZD": 10},
        "segment": {"high": 12, "low": 10},
        "market_env": "weak",
    }

    self.assertEqual(
        classify_signal_expected_horizon(signal, profile="fusion_strict_startup_rescue_v1"),
        "T+3",
    )
    self.assertEqual(
        explain_signal_expected_horizon(signal, profile="fusion_strict_startup_rescue_v1"),
        ["standard_swing"],
    )
```

```python
def test_expected_horizon_maps_a_minus_to_t1(self):
    signal = {
        "type": "强势启动候选",
        "trend_strength": 1.0,
        "volatility": 0.05,
        "pivot": None,
        "segment": {"high": 12, "low": 10},
        "market_env": "weak",
    }

    self.assertEqual(
        classify_signal_expected_horizon(signal, profile="fusion_strict_startup_rescue_v1"),
        "T+1",
    )
    self.assertEqual(
        explain_signal_expected_horizon(signal, profile="fusion_strict_startup_rescue_v1"),
        ["fast_confirm_or_exit"],
    )
```

```python
def test_expected_horizon_ignores_non_a_signals(self):
    signal = {
        "type": "底背驰候选",
        "trend_strength": 1.0,
        "volatility": 0.08,
        "pivot": {"ZG": 12, "ZD": 10},
        "segment": {"high": 12, "low": 10},
    }

    self.assertIsNone(
        classify_signal_expected_horizon(signal, profile="fusion_strict_startup_rescue_v1"),
    )
    self.assertEqual(
        explain_signal_expected_horizon(signal, profile="fusion_strict_startup_rescue_v1"),
        [],
    )
```

**Step 3: Add tag metadata test**

Extend `test_tag_signal_quality_adds_quality_tier_for_a_only` or add a new test:

```python
def test_tag_signal_quality_adds_expected_horizon_for_a_only(self):
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

    tagged_a = tag_signal_quality(a_signal, profile="fusion_strict_startup_rescue_v1")
    tagged_b = tag_signal_quality(b_signal, profile="fusion_strict_startup_rescue_v1")

    self.assertEqual(tagged_a["expected_horizon"], "T+1")
    self.assertEqual(tagged_a["expected_horizon_reasons"], ["fast_confirm_or_exit"])
    self.assertNotIn("expected_horizon", tagged_b)
    self.assertNotIn("expected_horizon_reasons", tagged_b)
```

**Step 4: Run tests and verify red**

Run:

```bash
python3 -m unittest tests.test_signal_quality_classifier
```

Expected:

- Fails because `classify_signal_expected_horizon` and `explain_signal_expected_horizon` do not exist yet.

## Task 2: Implement Horizon Helpers

**Files:**

- Modify: `chanlun/signal_quality_classifier.py`

**Step 1: Add `explain_signal_expected_horizon`**

Implementation shape:

```python
def explain_signal_expected_horizon(signal: Any, profile: str = _DEFAULT_FUSION_PROFILE) -> List[str]:
    if not isinstance(signal, Mapping):
        return []

    normalized_profile = _normalize_profile(profile)
    if classify_signal(signal, profile=normalized_profile) != "A":
        return []

    tier = signal.get("quality_tier")
    if tier not in {"A+", "A", "A-"}:
        tier = classify_signal_tier(signal, profile=normalized_profile)

    if tier == "A+":
        return ["high_confidence_hold"]
    if tier == "A-":
        return ["fast_confirm_or_exit"]
    if tier == "A":
        return ["standard_swing"]
    return ["default_swing"]
```

**Step 2: Add `classify_signal_expected_horizon`**

Implementation shape:

```python
def classify_signal_expected_horizon(signal: Any, profile: str = _DEFAULT_FUSION_PROFILE) -> Optional[str]:
    reasons = explain_signal_expected_horizon(signal, profile=profile)
    if not reasons:
        return None
    if "high_confidence_hold" in reasons:
        return "T+5"
    if "fast_confirm_or_exit" in reasons:
        return "T+1"
    return "T+3"
```

**Step 3: Attach metadata in tag helpers**

In `tag_signal_quality(...)`, after tier metadata is added for A signals:

```python
horizon = classify_signal_expected_horizon(out, profile=_normalize_profile(profile))
if horizon:
    out["expected_horizon"] = horizon
    out["expected_horizon_reasons"] = explain_signal_expected_horizon(
        out,
        profile=_normalize_profile(profile),
    )
```

For non-A signals, remove stale fields:

```python
out.pop("expected_horizon", None)
out.pop("expected_horizon_reasons", None)
```

Mirror the same behavior in `tag_signal_quality_in_place(...)`.

**Step 4: Run targeted tests**

Run:

```bash
python3 -m unittest tests.test_signal_quality_classifier
```

Expected:

- All tests pass.

## Task 3: Add Policy Experiment Horizon Distribution

**Files:**

- Modify: `chanlun/policy_experiment_metrics.py`
- Modify: `tests/test_policy_experiment_metrics.py`

**Step 1: Import helper**

In `chanlun/policy_experiment_metrics.py`, import:

```python
classify_signal_expected_horizon
```

**Step 2: Add horizon distribution**

Inside `_summarize_fusion_variant(...)`, when a pick is accepted as A:

```python
horizon = classify_signal_expected_horizon(signal, profile=variant_name) or "T+3"
horizon_counts[horizon] += 1
```

Include in returned row:

```python
"expected_horizon_distribution": dict(sorted(horizon_counts.items())),
```

Do not change ranking or selected candidate.

**Step 3: Update policy test**

In `test_run_policy_experiment_metrics_fusion_threshold_scan`, assert:

```python
self.assertEqual(
    rescue_profile["expected_horizon_distribution"],
    {"T+1": 1, "T+3": 1},
)
```

Adjust only if the fixture distribution differs after exact implementation.

**Step 4: Run policy tests**

Run:

```bash
python3 -m unittest tests.test_policy_experiment_metrics
```

Expected:

- All tests pass.

## Task 4: Backtest and Document Phase 2 Result

**Files:**

- Create: `docs/plans/2026-06-29-fusion-expected-horizon-phase2-result.md`

**Step 1: Run backtest**

Run:

```bash
python3 scripts/run_policy_experiments.py \
  --policies fusion_strict_startup_rescue_v1 \
  --business-metrics \
  --output-json /tmp/fusion_expected_horizon_phase2_report.json \
  --output-md /tmp/fusion_expected_horizon_phase2_report.md
```

Expected:

- Same sample count as guard/Phase 1 baseline: `123`.
- JSON includes `expected_horizon_distribution`.

**Step 2: Write result doc**

Create `docs/plans/2026-06-29-fusion-expected-horizon-phase2-result.md`:

```markdown
# 2026-06-29 Fusion Expected Horizon Phase 2 Result

## Goal

Add T+1/T+3/T+5 expected horizon metadata without changing A/B/C execution.

## Backtest Command

...

## Result

| Horizon | Count |
|---|---:|
| T+1 | ... |
| T+3 | ... |
| T+5 | ... |

## Conclusion

- Execution sample count unchanged.
- Horizon metadata is now available for Phase 3 failure analysis.
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
  - `docs/plans/2026-06-29-fusion-expected-horizon-phase2-result.md`

## Hand-Off Notes for 小兵

- Work directly from this plan.
- Do not implement Phase 3/4/5.
- Do not add failure downgrade rules.
- Do not add recommendation score.
- Do not add user-facing recommendation reasons.
- Do not commit.
- Do not push.
- Report:
  - files changed
  - red test failure summary
  - targeted test result
  - backtest command and horizon distribution
  - full verification result
