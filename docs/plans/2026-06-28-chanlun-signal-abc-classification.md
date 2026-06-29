# ChanLun Signal ABC Classification Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a Signal Quality Classification Layer that labels existing buy signals as A/B/C and lets execution/backtest paths trade only A while keeping B/C observable.

**Architecture:** Keep the core ChanLun structure and signal generation untouched. Add a pure classifier module, then connect it only at downstream buy-point post-processing and backtest/report surfaces so `analyze()` and `analyze_dual()` remain stable.

**Tech Stack:** Python 3, `unittest`, existing `chanlun` modules and `scripts/backtest_recommendation_quality.py` historical snapshot flow.

---

## Hard Constraints

Do not modify:

- `chanlun/chan_engine.py`
- `chanlun/engine_core.py`
- `chanlun/engine_signals.py`
- `analyze()`
- `analyze_dual()`

Do not turn this into a new candidate/dual-engine refactor. This is only the Signal ABC layer.

Do not push immediately after implementation. Push is allowed only after:

1. unit tests pass;
2. backtest comparison is produced;
3. user confirms the backtest result is acceptable.

## Target Behavior

Existing flow:

```text
fractals -> strokes -> segments -> pivots -> signals
```

New downstream flow:

```text
signals -> signal_quality_classifier -> A/B/C -> execution/backtest
```

Classification:

- A = tradeable signal
- B = observe only
- C = filtered signal

Execution rule:

```python
def execute_signal(signal):
    category = classify_signal(signal)
    if category == "A":
        return place_order(signal)
    if category == "B":
        return log_only(signal)
    return ignore(signal)
```

In this repo, "place_order" maps to recommendation/backtest executable samples. No live broker/order code should be introduced.

## Rule Definition

Expected signal shape:

```python
signal = {
    "type": str,
    "index": int,
    "price": float,
    "context": {
        "trend_strength": float,
        "pivot": object,
        "segment": object,
        "volatility": float,
    },
}
```

Classification rules:

- A:
  - `trend_strength >= 2`
  - pivot exists
  - segment exists
  - volatility is low
- B:
  - `trend_strength == 1`
  - or structure is incomplete
  - or volatility is medium
- C:
  - `trend_strength <= 0`
  - or choppy/range signal
  - or high volatility plus weak/incomplete structure

Implementation detail:

- Missing context must not crash classification.
- Missing context defaults to B unless the signal is explicitly weak/blocked/choppy enough for C.
- Existing `tier` remains untouched. `category` is an additional field, not a replacement for `tier`.

## Files

Create:

- `chanlun/signal_quality_classifier.py`
- `tests/test_signal_quality_classifier.py`

Modify:

- `chanlun/daily_structure_pool.py`
- `chanlun/screener_pure.py`
- `chanlun/backtest_execution.py`
- `scripts/backtest_recommendation_quality.py`
- tests covering modified behavior as needed

Forbidden:

- `chanlun/chan_engine.py`
- `chanlun/engine_core.py`
- `chanlun/engine_signals.py`

## Task 1: Add Pure Signal Classifier

**Files:**

- Create: `chanlun/signal_quality_classifier.py`
- Create: `tests/test_signal_quality_classifier.py`

**Step 1: Write failing tests**

Add tests for:

- strong trend + pivot + segment + low volatility returns `"A"`;
- trend strength 1 returns `"B"`;
- missing pivot or missing segment returns `"B"`;
- trend strength 0 returns `"C"`;
- high volatility with weak/incomplete structure returns `"C"`;
- `tag_signal_quality(signal)` returns a copy and does not mutate input;
- `tag_signal_quality_in_place(signal)` sets `signal["category"]`;
- `filter_executable_signals(signals)` returns only category A.

Run:

```bash
python3 -m unittest tests.test_signal_quality_classifier
```

Expected: FAIL because module/functions do not exist.

**Step 2: Implement minimal classifier**

Expose:

```python
LOW_VOLATILITY_MAX = 0.10
HIGH_VOLATILITY_MIN = 0.18

def classify_signal(signal):
    ...

def tag_signal_quality(signal):
    ...

def tag_signal_quality_in_place(signal):
    ...

def tag_signal_quality_many(signals, in_place=False):
    ...

def filter_executable_signals(signals):
    ...
```

Keep the module dependency-free except standard Python helpers.

**Step 3: Verify**

Run:

```bash
python3 -m unittest tests.test_signal_quality_classifier
python3 -m py_compile chanlun/signal_quality_classifier.py
```

Expected: PASS.

## Task 2: Build Context and Tag Existing Buy Points Downstream

**Files:**

- Modify: `chanlun/daily_structure_pool.py`
- Modify: `chanlun/screener_pure.py`
- Test: `tests/test_daily_structure_pool.py`
- Test: add/update pure screener tests if present; otherwise keep coverage in classifier + daily pool.

**Step 1: Write failing tests**

Add tests proving:

- pool buy points get `category`;
- `best_buy_point` selected for executable recommendations is category A when A exists;
- B/C buy points stay in `buy_points` for observability;
- no forbidden engine files are imported or modified.

Run:

```bash
python3 -m unittest tests.test_daily_structure_pool tests.test_signal_quality_classifier
```

Expected: FAIL because buy points are not tagged yet.

**Step 2: Implement downstream tagging**

Add usage of the classifier only after `buy_points` exist:

```python
from .signal_quality_classifier import build_signal_context, tag_signal_quality_many, filter_executable_signals

for bp in buy_points:
    bp["context"] = build_signal_context(result, bp)
    bp["category"] = classify_signal(bp)
```

Expected integration shape:

- keep all tagged points in `buy_points`;
- use only A points for execution/recommendation choice when any A exists;
- if no A exists, keep existing stock visibility only where the existing pipeline already kept it, but do not mark B/C as executable.

Do not change signal generation logic.

**Step 3: Verify**

Run:

```bash
python3 -m unittest tests.test_daily_structure_pool tests.test_signal_quality_classifier
```

Expected: PASS.

## Task 3: Add ABC-A Backtest Comparison

**Files:**

- Modify: `chanlun/backtest_execution.py`
- Modify: `scripts/backtest_recommendation_quality.py`
- Test: `tests/test_backtest_execution.py`

**Step 1: Write failing tests**

Add tests proving:

- `execute_signal(signal)` returns an action/value for A/B/C without live side effects;
- backtest grouping can classify historical snapshot picks by `best_buy_point.category`;
- executable backtest samples can be filtered to A only.

Run:

```bash
python3 -m unittest tests.test_backtest_execution tests.test_signal_quality_classifier
```

Expected: FAIL until execution helper and script grouping exist.

**Step 2: Implement execution helper**

In `chanlun/backtest_execution.py`, add a side-effect-free execution decision helper:

```python
def execute_signal(signal):
    category = classify_signal(signal)
    if category == "A":
        return {"action": "place_order", "category": "A", "execute": True}
    if category == "B":
        return {"action": "log_only", "category": "B", "execute": False}
    return {"action": "ignore", "category": "C", "execute": False}
```

This is a model of execution intent only. Do not add real order placement.

**Step 3: Add script comparison output**

Update `scripts/backtest_recommendation_quality.py` to print both:

- baseline overall historical recommendation metrics;
- ABC-A-only metrics where `best_buy_point.category == "A"` after classification/tagging.

Required comparison fields:

- total evaluated baseline samples;
- evaluated A samples;
- A sample reduction percentage;
- T+3 win rate baseline vs A;
- T+3 mean return baseline vs A;
- max drawdown mean baseline vs A.

**Step 4: Verify**

Run:

```bash
python3 -m unittest tests.test_backtest_execution tests.test_signal_quality_classifier
python3 scripts/backtest_recommendation_quality.py
```

Expected: tests PASS, script prints baseline and ABC-A comparison.

## Task 4: Full Verification and Backtest Gate

**Files:**

- All changed files.

**Step 1: Guard forbidden files**

Run:

```bash
git diff -- chanlun/chan_engine.py chanlun/engine_core.py chanlun/engine_signals.py
```

Expected: empty diff.

**Step 2: Run focused tests**

Run:

```bash
python3 -m unittest \
  tests.test_signal_quality_classifier \
  tests.test_daily_structure_pool \
  tests.test_backtest_execution
```

Expected: PASS.

**Step 3: Run project verification subset**

Run:

```bash
python3 -m unittest \
  tests.test_chan_engine_core \
  tests.test_chan_engine_snapshot \
  tests.test_chan_engine_import_compat \
  tests.test_signal_policy \
  tests.test_daily_structure_pool \
  tests.test_candidate_upgrade \
  tests.test_backtest_execution \
  tests.test_signal_quality_classifier
```

Expected: PASS.

**Step 4: Compile and hygiene**

Run:

```bash
python3 -m py_compile \
  chanlun/signal_quality_classifier.py \
  chanlun/daily_structure_pool.py \
  chanlun/screener_pure.py \
  chanlun/backtest_execution.py \
  scripts/backtest_recommendation_quality.py

git diff --check
```

Expected: PASS / clean.

**Step 5: Backtest comparison before push**

Run:

```bash
python3 scripts/backtest_recommendation_quality.py
```

Capture and report:

- baseline evaluated samples;
- ABC-A evaluated samples;
- A reduction percentage;
- baseline vs A T+3 win rate;
- baseline vs A T+3 mean return;
- baseline vs A max drawdown mean.

Acceptance target:

- A sample count drops 30%-70% versus baseline, or explain why the available historical sample does not hit the target;
- A T+3 win rate improves versus baseline, or do not push without user confirmation;
- A max drawdown mean improves versus baseline, or do not push without user confirmation.

**Step 6: Stop for user confirmation**

Do not commit/push until the user sees the backtest comparison and confirms.

## Review Checklist

- `analyze()` unchanged.
- `analyze_dual()` unchanged.
- No edits in forbidden files.
- Signal generation remains intact.
- `tier` stays backward-compatible.
- `category` is additive.
- B/C remain visible for diagnostics.
- A-only filtering affects execution/backtest intent, not core structure.

