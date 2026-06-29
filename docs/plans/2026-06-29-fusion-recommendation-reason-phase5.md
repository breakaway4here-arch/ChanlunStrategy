# Fusion Recommendation Reason Phase 5 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add short, user-readable recommendation reason metadata for executable `fusion_strict_startup_rescue_v1` A-class signals.

**Architecture:** Build on Phase 1 `quality_tier`, Phase 2 `expected_horizon`, Phase 3 failure audit, and Phase 4 recommendation score. This phase only adds backend metadata fields: `recommendation_reason` and `recommendation_reason_tags`. It must not modify report UI, sorting, filtering, or execution behavior.

**Tech Stack:** Python 3, `unittest`, `chanlun.signal_quality_classifier`, `chanlun.policy_experiment_metrics`, existing `scripts/run_policy_experiments.py`.

---

## Hard Constraints

- Do not modify `chanlun/chan_engine.py`.
- Do not modify `chanlun/engine_core.py`.
- Do not modify `chanlun/engine_signals.py`.
- Do not modify `analyze()`.
- Do not modify `analyze_dual()`.
- Do not modify report UI in this phase.
- Do not change A/B/C execution semantics.
- Do not sort or filter by recommendation score.
- Do not commit or push from 小兵. Main thread will review, test, commit, and push.

## Output Fields

Only A-class signals receive:

```python
signal["recommendation_reason"] = "..."
signal["recommendation_reason_tags"] = [...]
```

Non-A signals must not retain stale reason fields.

## Reason Text Rules

Reason should be short, deterministic, and based on actual metadata:

### A+

```text
A+：高强度低波动结构，预期T+5持有，适合作为核心观察。
```

Tags:

```python
["高强度", "低波动", "完整结构", "T+5"]
```

### A

```text
A：标准A类结构，预期T+3观察，适合按计划跟踪。
```

Tags:

```python
["标准A类", "T+3"]
```

### A-

If `startup_rescue` is present:

```text
A-：弱市强势启动修复信号，预期T+1快进快出，需等待后续确认。
```

Tags:

```python
["启动修复", "T+1", "需确认"]
```

If `volatility_near_limit` is present:

```text
A-：波动接近上限，预期T+1观察，需控制回撤风险。
```

Tags:

```python
["波动偏高", "T+1", "控回撤"]
```

Fallback A-:

```text
A-：低位A类信号，预期T+1观察，仓位应更保守。
```

Tags:

```python
["低位A类", "T+1", "保守仓位"]
```

## Task 1: Add Failing Unit Tests

**Files:**

- Modify: `tests/test_signal_quality_classifier.py`

**Step 1: Import new helper**

Add import:

```python
build_signal_recommendation_reason
```

**Step 2: Add reason tests**

```python
def test_recommendation_reason_for_a_plus(self):
    signal = {
        "type": "强势启动候选",
        "trend_strength": 3.0,
        "volatility": 0.05,
        "pivot": {"ZG": 12, "ZD": 10},
        "segment": {"high": 12, "low": 10},
        "market_env": "strong",
    }

    reason = build_signal_recommendation_reason(
        signal,
        profile="fusion_strict_startup_rescue_v1",
    )

    self.assertEqual(
        reason,
        {
            "text": "A+：高强度低波动结构，预期T+5持有，适合作为核心观察。",
            "tags": ["高强度", "低波动", "完整结构", "T+5"],
        },
    )
```

```python
def test_recommendation_reason_for_standard_a(self):
    signal = {
        "type": "一买",
        "trend_strength": 2.0,
        "volatility": 0.07,
        "pivot": {"ZG": 12, "ZD": 10},
        "segment": {"high": 12, "low": 10},
        "market_env": "weak",
    }

    self.assertEqual(
        build_signal_recommendation_reason(
            signal,
            profile="fusion_strict_startup_rescue_v1",
        ),
        {
            "text": "A：标准A类结构，预期T+3观察，适合按计划跟踪。",
            "tags": ["标准A类", "T+3"],
        },
    )
```

```python
def test_recommendation_reason_for_startup_rescue(self):
    signal = {
        "type": "强势启动候选",
        "trend_strength": 1.0,
        "volatility": 0.05,
        "pivot": None,
        "segment": {"high": 12, "low": 10},
        "market_env": "weak",
    }

    self.assertEqual(
        build_signal_recommendation_reason(
            signal,
            profile="fusion_strict_startup_rescue_v1",
        ),
        {
            "text": "A-：弱市强势启动修复信号，预期T+1快进快出，需等待后续确认。",
            "tags": ["启动修复", "T+1", "需确认"],
        },
    )
```

```python
def test_recommendation_reason_ignores_non_a(self):
    signal = {
        "type": "底背驰候选",
        "trend_strength": 1.0,
        "volatility": 0.08,
        "pivot": {"ZG": 12, "ZD": 10},
        "segment": {"high": 12, "low": 10},
    }

    self.assertIsNone(
        build_signal_recommendation_reason(
            signal,
            profile="fusion_strict_startup_rescue_v1",
        ),
    )
```

**Step 3: Add tag metadata assertions**

Extend tag metadata test:

```python
self.assertEqual(
    tagged_a["recommendation_reason"],
    "A-：弱市强势启动修复信号，预期T+1快进快出，需等待后续确认。",
)
self.assertEqual(tagged_a["recommendation_reason_tags"], ["启动修复", "T+1", "需确认"])
self.assertNotIn("recommendation_reason", tagged_b)
self.assertNotIn("recommendation_reason_tags", tagged_b)
```

**Step 4: Run tests and verify red**

Run:

```bash
python3 -m unittest tests.test_signal_quality_classifier
```

Expected:

- Fails because `build_signal_recommendation_reason` does not exist.

## Task 2: Implement Reason Helper

**Files:**

- Modify: `chanlun/signal_quality_classifier.py`

**Step 1: Add `build_signal_recommendation_reason`**

Implementation outline:

```python
def build_signal_recommendation_reason(
    signal: Any,
    profile: str = _DEFAULT_FUSION_PROFILE,
) -> Optional[dict]:
    if not isinstance(signal, Mapping):
        return None

    normalized_profile = _normalize_profile(profile)
    if classify_signal(signal, profile=normalized_profile) != "A":
        return None

    tier = signal.get("quality_tier")
    if tier not in {"A+", "A", "A-"}:
        tier = classify_signal_tier(signal, profile=normalized_profile)

    horizon = signal.get("expected_horizon")
    if horizon not in {"T+1", "T+3", "T+5"}:
        horizon = classify_signal_expected_horizon(signal, profile=normalized_profile)

    tier_reasons = signal.get("quality_tier_reasons")
    if not isinstance(tier_reasons, list):
        tier_reasons = explain_signal_tier(signal, profile=normalized_profile)

    if tier == "A+":
        return {
            "text": "A+：高强度低波动结构，预期T+5持有，适合作为核心观察。",
            "tags": ["高强度", "低波动", "完整结构", "T+5"],
        }
    if tier == "A-":
        if "startup_rescue" in tier_reasons:
            return {
                "text": "A-：弱市强势启动修复信号，预期T+1快进快出，需等待后续确认。",
                "tags": ["启动修复", "T+1", "需确认"],
            }
        if "volatility_near_limit" in tier_reasons:
            return {
                "text": "A-：波动接近上限，预期T+1观察，需控制回撤风险。",
                "tags": ["波动偏高", "T+1", "控回撤"],
            }
        return {
            "text": "A-：低位A类信号，预期T+1观察，仓位应更保守。",
            "tags": ["低位A类", "T+1", "保守仓位"],
        }
    return {
        "text": "A：标准A类结构，预期T+3观察，适合按计划跟踪。",
        "tags": ["标准A类", "T+3"],
    }
```

**Step 2: Attach reason metadata**

In `tag_signal_quality(...)`, after score metadata:

```python
reason = build_signal_recommendation_reason(out, profile=normalized_profile)
if reason:
    out["recommendation_reason"] = reason["text"]
    out["recommendation_reason_tags"] = reason["tags"]
else:
    out.pop("recommendation_reason", None)
    out.pop("recommendation_reason_tags", None)
```

For non-A signals, remove stale:

```python
out.pop("recommendation_reason", None)
out.pop("recommendation_reason_tags", None)
```

Mirror in `tag_signal_quality_in_place(...)`.

**Step 3: Run targeted tests**

Run:

```bash
python3 -m unittest tests.test_signal_quality_classifier
```

Expected:

- All tests pass.

## Task 3: Add Policy Experiment Reason Tag Distribution

**Files:**

- Modify: `chanlun/policy_experiment_metrics.py`
- Modify: `tests/test_policy_experiment_metrics.py`

**Step 1: Import helper**

```python
build_signal_recommendation_reason
```

**Step 2: Count reason tags**

Inside `_summarize_fusion_variant(...)`, when accepted:

```python
reason = build_signal_recommendation_reason(signal, profile=variant_name)
if reason:
    for tag in reason.get("tags", []):
        reason_tag_counts[str(tag)] += 1
```

Return:

```python
"recommendation_reason_tag_distribution": dict(sorted(reason_tag_counts.items())),
```

Do not use reason tags in ranking/filtering.

**Step 3: Update policy test**

For the mocked rescue profile:

- standard A contributes `标准A类`, `T+3`
- startup rescue contributes `启动修复`, `T+1`, `需确认`

Assert at least:

```python
self.assertEqual(
    rescue_profile["recommendation_reason_tag_distribution"]["标准A类"],
    1,
)
self.assertEqual(
    rescue_profile["recommendation_reason_tag_distribution"]["启动修复"],
    1,
)
self.assertEqual(
    rescue_profile["recommendation_reason_tag_distribution"]["T+1"],
    1,
)
self.assertEqual(
    rescue_profile["recommendation_reason_tag_distribution"]["T+3"],
    1,
)
```

**Step 4: Run policy tests**

Run:

```bash
python3 -m unittest tests.test_policy_experiment_metrics
```

Expected:

- All tests pass.

## Task 4: Backtest and Document Phase 5 Result

**Files:**

- Create: `docs/plans/2026-06-29-fusion-recommendation-reason-phase5-result.md`

**Step 1: Run backtest**

Run:

```bash
python3 scripts/run_policy_experiments.py \
  --policies fusion_strict_startup_rescue_v1 \
  --business-metrics \
  --output-json /tmp/fusion_recommendation_reason_phase5_report.json \
  --output-md /tmp/fusion_recommendation_reason_phase5_report.md
```

Expected:

- Sample count remains `123`.
- JSON includes reason tag distribution.

**Step 2: Write result doc**

Create result doc:

```markdown
# 2026-06-29 Fusion Recommendation Reason Phase 5 Result

## Goal

Add user-readable recommendation reason metadata without changing execution or UI.

## Result

| Metric | Value |
|---|---:|
| samples | ... |

## Reason Tags

| Tag | Count |
|---|---:|
| ... | ... |

## Conclusion

- Execution sample count unchanged.
- Reason text metadata is ready for report/UI integration in a separate step.
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
  - `docs/plans/2026-06-29-fusion-recommendation-reason-phase5-result.md`

## Hand-Off Notes for 小兵

- Work directly from this plan.
- Do not modify report UI.
- Do not activate sorting or filtering.
- Do not commit.
- Do not push.
- Report:
  - files changed
  - red test failure summary
  - targeted test result
  - backtest command and reason tag distribution
  - full verification result
