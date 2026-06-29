# Fusion Startup Rescue Market Guard Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enable `fusion_strict_startup_rescue_v1` as the default candidate profile, while disabling only its extra `trend_strength=1.0 + 强势启动候选` rescue branch in strong market environments.

**Architecture:** Keep `fusion_strict` as the stable baseline profile. `fusion_strict_startup_rescue_v1` must include all original `fusion_strict` A-class signals, but its extra weak-startup rescue is guarded by market environment: if `market_env == "strong"`, do not rescue the weak startup sample; otherwise allow it. This stays inside the downstream signal quality layer and policy experiment scan only.

**Tech Stack:** Python 3, `unittest`, existing `chanlun.signal_quality_classifier`, existing `chanlun.policy_experiment_metrics`, existing `scripts/run_policy_experiments.py`.

---

## Hard Constraints

- Do not modify `chanlun/chan_engine.py`.
- Do not modify `chanlun/engine_core.py`.
- Do not modify `chanlun/engine_signals.py`.
- Do not modify `analyze()`.
- Do not modify `analyze_dual()`.
- Do not change the behavior of explicit `profile="fusion_strict"`.
- Do not remove `fusion_strict`, `fusion_mid`, or `fusion_loose`.
- Do not commit or push in the implementation subagent. The main thread will review, test, commit, and push.

## Intended Behavior

Pseudocode:

```python
if profile == "fusion_strict_startup_rescue_v1":
    # Original strict A-class path still applies first and is not affected.
    if signal already passes fusion_strict A rules:
        return "A"

    # Only the extra rescue branch is guarded.
    if market_env == "strong":
        do not rescue trend_strength=1.0 startup
    else:
        allow rescue when trend_strength == 1.0 and signal_type == "强势启动候选"
```

Expected classifications:

| Profile | market_env | signal_type | trend_strength | Expected |
|---|---|---|---:|---|
| `fusion_strict` | any | `强势启动候选` | 1.0 | `B` |
| `fusion_strict_startup_rescue_v1` | `weak` | `强势启动候选` | 1.0 | `A` |
| `fusion_strict_startup_rescue_v1` | missing / unknown | `强势启动候选` | 1.0 | `A` |
| `fusion_strict_startup_rescue_v1` | `strong` | `强势启动候选` | 1.0 | `B` |
| `fusion_strict_startup_rescue_v1` | `strong` | original strict-qualified signal | >= 2.0 | `A` |
| `fusion_strict_startup_rescue_v1` | any | `底背驰候选` | 1.0 | `B` |
| `fusion_strict_startup_rescue_v1` | any | `中枢低吸候选` | 1.0 | `B` |

## Task 1: Add Market Guard Tests First

**Files:**

- Modify: `tests/test_signal_quality_classifier.py`
- Modify: `tests/test_policy_experiment_metrics.py`

**Step 1: Add failing classifier tests**

In `tests/test_signal_quality_classifier.py`, extend or add a test near `test_classify_signal_startup_rescue_only_rescues_weak_startup`.

Add these cases:

```python
def test_classify_signal_startup_rescue_has_strong_market_guard(self):
    weak_startup = {
        "type": "强势启动候选",
        "trend_strength": 1.0,
        "volatility": 0.15,
        "pivot": None,
        "segment": {"high": 12, "low": 10},
        "market_env": "weak",
    }
    strong_startup = dict(weak_startup)
    strong_startup["market_env"] = "strong"
    strict_original = {
        "type": "强势启动候选",
        "trend_strength": 2.0,
        "volatility": 0.08,
        "pivot": {"ZG": 12, "ZD": 10},
        "segment": {"high": 12, "low": 10},
        "market_env": "strong",
    }

    self.assertEqual(
        classify_signal(weak_startup, profile="fusion_strict_startup_rescue_v1"),
        "A",
    )
    self.assertEqual(
        classify_signal(strong_startup, profile="fusion_strict_startup_rescue_v1"),
        "B",
    )
    self.assertEqual(
        classify_signal(strict_original, profile="fusion_strict_startup_rescue_v1"),
        "A",
    )
    self.assertEqual(
        classify_signal(strong_startup, profile="fusion_strict"),
        "B",
    )
```

Also add a default-profile test:

```python
def test_classify_signal_default_profile_is_startup_rescue_v1(self):
    signal = {
        "type": "强势启动候选",
        "trend_strength": 1.0,
        "volatility": 0.15,
        "pivot": None,
        "segment": {"high": 12, "low": 10},
        "market_env": "weak",
    }

    self.assertEqual(classify_signal(signal), "A")
```

**Step 2: Add failing policy scan test coverage**

In `tests/test_policy_experiment_metrics.py`:

- Add optional `market_regime=None` to `_make_fusion_pick(...)`.
- Include `"market_regime": market_regime` in the returned pick when non-empty, or always include it.
- In `test_run_policy_experiment_metrics_fusion_threshold_scan`, make the existing weak-startup rescued sample `market_regime="weak"`.
- Add one more `picks_fusion` row with:
  - `best_type="强势启动候选"`
  - `trend_strength=1.0`
  - low volatility
  - usable pivot/segment
  - `market_regime="strong"`
  - unique code
- Add one more `evaluate_mock` return sample for that row.
- Update expectations:
  - baseline sample count increases by 1.
  - `fusion_strict_startup_rescue_v1` should not count the strong weak-startup sample as A.
  - `reject_reason_distribution` should include `strong_market_rescue_guard: 1`.

**Step 3: Verify tests fail before implementation**

Run:

```bash
python3 -m unittest tests.test_signal_quality_classifier tests.test_policy_experiment_metrics
```

Expected before implementation:

- At least one failure showing strong-market startup rescue is still classified as `A`, or default profile is still strict.

## Task 2: Implement Default Profile and Market Guard

**Files:**

- Modify: `chanlun/signal_quality_classifier.py`
- Modify: `chanlun/policy_experiment_metrics.py`

**Step 1: Make rescue profile the default candidate profile**

In `chanlun/signal_quality_classifier.py`:

- Add a default profile constant if useful:

```python
_DEFAULT_FUSION_PROFILE = _FUSION_PROFILE_STRICT_STARTUP_RESCUE_V1
```

- Change `_normalize_profile(None)` to return `_DEFAULT_FUSION_PROFILE`.
- Change public helper defaults from `_FUSION_PROFILE_STRICT` to `_DEFAULT_FUSION_PROFILE`:
  - `classify_signal`
  - `explain_signal_rejection`
  - `tag_signal_quality`
  - `tag_signal_quality_in_place`
  - `tag_signals`
  - `filter_executable_signals`
- Keep explicit `profile="fusion_strict"` behavior unchanged.

In `chanlun/policy_experiment_metrics.py`:

- Put `"fusion_strict_startup_rescue_v1"` before `"fusion_strict"` in `FUSION_PROFILES`.
- In `_run_fusion_threshold_scan`, if no profile is accepted, fallback selected candidate should be `"fusion_strict_startup_rescue_v1"` when it was part of the requested fusion profile list; otherwise use the first requested fusion profile, and only then fallback to `"fusion_strict"`.

**Step 2: Carry market environment into signal context**

In `build_signal_context(...)`, read market environment from both source and signal, preferring explicit signal fields:

```python
market_env = (
    signal_obj.get("market_env")
    or signal_obj.get("market_regime")
    or signal_obj.get("market_trend")
    or _get_from_obj(source, "market_env", None)
    or _get_from_obj(source, "market_regime", None)
    or _get_from_obj(source, "market_trend", None)
)
```

Add it to the returned context:

```python
"market_env": market_env,
```

In `classify_signal(...)`, pass `market_env` into `_is_profile_a_candidate(...)`.

**Step 3: Guard only the rescue branch**

In `_is_profile_a_candidate(...)`, keep the existing strict path checks intact.

Add a helper:

```python
def _is_strong_market_env(value: Any) -> bool:
    return str(value or "").strip().lower() == "strong"
```

Change the rescue branch to:

```python
if (
    profile == _FUSION_PROFILE_STRICT_STARTUP_RESCUE_V1
    and trend_strength == 1.0
    and signal_type == "强势启动候选"
):
    return not _is_strong_market_env(context.get("market_env"))
```

Important: This guard must only apply to this rescue branch. A signal that already satisfies the strict A-class rules must still return `A` even when `market_env == "strong"`.

**Step 4: Add explicit reject reason**

In `explain_signal_rejection(...)`, add:

```python
if (
    normalized_profile == _FUSION_PROFILE_STRICT_STARTUP_RESCUE_V1
    and trend_strength == 1.0
    and signal_type == "强势启动候选"
    and _is_strong_market_env(context.get("market_env"))
):
    reasons.append("strong_market_rescue_guard")
```

Make sure `signal_type` is defined in `explain_signal_rejection(...)` the same way as in `classify_signal(...)`.

**Step 5: Run targeted tests**

Run:

```bash
python3 -m unittest tests.test_signal_quality_classifier tests.test_policy_experiment_metrics
```

Expected:

- All tests pass.

## Task 3: Backtest and Update Result Doc

**Files:**

- Modify: `docs/plans/2026-06-29-fusion-strict-startup-rescue-v1-result.md`

**Step 1: Run backtest**

Run:

```bash
python3 scripts/run_policy_experiments.py \
  --policies fusion_strict,fusion_strict_startup_rescue_v1 \
  --business-metrics \
  --output-json /tmp/fusion_startup_rescue_market_guard_report.json \
  --output-md /tmp/fusion_startup_rescue_market_guard_report.md
```

Expected:

- `fusion_strict_startup_rescue_v1` should retain the original strict A-class samples.
- Strong-market `trend_strength=1.0 + 强势启动候选` rescue samples should be removed from rescue.
- Compared with pre-guard rescue, coverage should decrease from `141` samples toward about `123` samples based on the prior validation split.
- Compared with `fusion_strict`, coverage should still be higher than `88` samples.

**Step 2: Update result doc**

Append a new section to `docs/plans/2026-06-29-fusion-strict-startup-rescue-v1-result.md`:

```markdown
## 7. Strong Market Rescue Guard 上线修正

### 7.1 上线策略

- 默认候选：`fusion_strict_startup_rescue_v1`
- 保留：全部原 `fusion_strict` A 类
- 禁用：`market_env == "strong"` 下新增的 `trend_strength=1.0 + 强势启动候选` rescue
- 允许：非 strong 环境下的 `trend_strength=1.0 + 强势启动候选` rescue

### 7.2 回测结果

粘贴 `fusion_strict` 与 guard 后 `fusion_strict_startup_rescue_v1` 的 samples、coverage、T+3 mean、T+3 win、drawdown、reject reason distribution。

### 7.3 结论

写明是否仍优于 `fusion_strict`，以及 strong-market guard 是否降低回撤风险。
```

## Task 4: Final Verification

**Files:** no code changes unless tests fail.

Run:

```bash
python3 -m unittest discover -s tests
python3 -m py_compile chanlun/signal_quality_classifier.py chanlun/policy_experiment_metrics.py scripts/run_policy_experiments.py
git diff --check
git status --short
```

Expected:

- Full unittest suite passes.
- `py_compile` passes.
- `git diff --check` has no output.
- Only intended files are modified:
  - `chanlun/signal_quality_classifier.py`
  - `chanlun/policy_experiment_metrics.py`
  - `tests/test_signal_quality_classifier.py`
  - `tests/test_policy_experiment_metrics.py`
  - `docs/plans/2026-06-29-fusion-strict-startup-rescue-v1-result.md`
  - `docs/plans/2026-06-29-fusion-startup-rescue-market-guard.md`

## Hand-off Notes for 小兵

- Work directly from this plan.
- Do not change engine internals.
- Do not commit.
- Do not push.
- Report:
  - Files changed.
  - Targeted test result.
  - Backtest command and key metrics.
  - Full verification command results.
