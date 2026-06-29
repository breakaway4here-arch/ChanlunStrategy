# Fusion Recommendation Optimization Roadmap Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build the next recommendation optimization path on top of `fusion_strict_startup_rescue_v1` without changing production engine internals.

**Architecture:** Keep the current A/B/C classifier and default candidate policy stable. Add downstream, additive metadata in five narrow phases: quality tier, expected holding horizon, failure downgrade rules, ranking score, and user-facing explanation. Each phase must land as its own MD, be implemented by 小兵, reviewed in the main thread, backtested, tested, then pushed before moving to the next phase.

**Tech Stack:** Python 3, `unittest`, existing `chanlun.signal_quality_classifier`, existing `chanlun.policy_experiment_metrics`, existing `scripts/run_policy_experiments.py`.

---

## Hard Constraints

- Do not modify `chanlun/chan_engine.py`.
- Do not modify `chanlun/engine_core.py`.
- Do not modify `chanlun/engine_signals.py`.
- Do not modify `analyze()`.
- Do not modify `analyze_dual()`.
- Do not remove or weaken `fusion_strict_startup_rescue_v1` strong-market guard.
- Do not change A/B/C execution semantics unless a later phase explicitly proves the change by backtest.
- Every phase must be separately documented under `docs/plans/`.
- Every code phase must pass:
  - targeted unit tests
  - `python3 -m unittest discover -s tests`
  - `python3 -m py_compile ...`
  - `git diff --check`
  - a policy backtest when behavior affects recommendation output

## Current Baseline

Current pushed default candidate:

- `fusion_strict_startup_rescue_v1`
- Default candidate behavior:
  - preserves all original `fusion_strict` A-class signals
  - rescues `trend_strength=1.0 + 强势启动候选` only outside `strong` market
  - blocks strong-market weak-startup rescue via `strong_market_rescue_guard`

Latest validated guard backtest:

| Strategy | samples_after | coverage | T+3 mean | T+3 win | drawdown |
|---|---:|---:|---:|---:|---:|
| fusion_strict | 88 | 20.28% | 1.31 | 51.1% | -4.42 |
| fusion_strict_startup_rescue_v1 | 123 | 28.34% | 2.28 | 55.3% | -4.23 |

## Phase Sequence

### Phase 1: A+/A/A- Quality Tier

Purpose:

- Split only existing A-class signals into `A+`, `A`, and `A-`.
- Keep `category == "A"` for all executable A-class signals.
- Do not filter or change execution yet.

Output:

```python
signal["category"] = "A"
signal["quality_tier"] = "A+" | "A" | "A-"
signal["quality_tier_reasons"] = [...]
```

Execution doc:

- `docs/plans/2026-06-29-fusion-quality-tier-phase1.md`

### Phase 2: Expected Horizon T+1 / T+3 / T+5

Purpose:

- Add a deterministic `expected_horizon` label for each A-class signal.
- Do not optimize exits yet; only tag expected holding cycle.

Expected direction:

- `A+` tends to `T+3/T+5`
- `A` tends to `T+3`
- `A-` tends to `T+1/T+3`

Validation:

- Compare realized T+1/T+3/T+5 by tier.
- Confirm tier-to-horizon mapping is not contradicted by backtest.

### Phase 3: Failure Sample Downgrade / Filter Rules

Purpose:

- Analyze failed A-class samples, especially `A-` and rescue samples.
- Convert proven weak conditions into tier downgrade or C filter.

Examples to test:

- high volatility near threshold
- missing structure proxy
- choppy / market mismatch
- concentrated drawdown buckets

Validation:

- T+3 mean and drawdown must improve or coverage loss must be explicitly justified.

### Phase 4: Recommendation Score

Purpose:

- Convert tier, horizon, structure quality, market guard, and failure-rule penalties into a stable sortable score.
- Score should rank recommendations, not replace A/B/C execution filtering.

Output:

```python
signal["recommendation_score"] = 0.0 - 100.0
```

Validation:

- Top-N buckets should show monotonic or near-monotonic improvement versus lower buckets.

### Phase 5: User-Facing Recommendation Reasons

Purpose:

- Convert machine tags into short user-readable reasons.
- Avoid vague text; reasons must cite actual facts such as trend strength, market environment, signal type, volatility bucket, and tier.

Output example:

```text
A-：弱市强势启动修复信号，已避开强市 rescue 风险，适合短线 T+1/T+3 观察。
```

Validation:

- Unit tests for reason strings.
- Snapshot/report smoke test if surfaced in UI/report output.

## Operating Flow Per Phase

1. Main thread writes executable MD.
2. 小兵 implements code from the MD using `gpt-5.3-codex-spark`.
3. Main thread reviews code and checks for scope drift.
4. Main thread runs targeted tests, full tests, py_compile, diff check, and backtest if applicable.
5. If clean, main thread commits and pushes.
6. Move to the next phase only after the previous phase is pushed.

## Do Not Do Yet

- Do not introduce score before Phase 4.
- Do not introduce user-facing explanation before Phase 5.
- Do not change report UI until the backend tags are verified.
- Do not use A+/A/A- to filter signals in Phase 1.
