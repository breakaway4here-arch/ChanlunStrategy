# Chanlun Segment Refactor Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rebuild the standard Chanlun structure pipeline so buy signals are based on reliable `fractal -> stroke -> segment -> pivot` structures, while demoting swing/zigzag output to auxiliary display and scoring only.

**Architecture:** The standard Chanlun path becomes the only source of truth for pivots, trend type, divergence, and formal buy points. Swing tracking remains available, but is renamed and isolated as auxiliary wave detection; it must not create `一买`, `二买`, `三买`, or formal pivots. The refactor is staged behind tests and QA reports so signal quantity may decrease while structural correctness improves.

**Tech Stack:** Python 3, dataclasses, NumPy, existing `chanlun_strategy/chanlun` modules, local JSON/HTML report generation.

---

## Problem Statement

Current stock selection produces many inaccurate buy signals because upstream structure is unreliable:

- `build_segments()` groups every 3 strokes into a segment-like object. Chanlun segments should be confirmed by segment destruction, not fixed-size windows.
- `locate_buy_sell_points()` prefers `result.stroke_pivots` from swing tracking over standard `result.pivots`.
- `_detect_first_buy_from_swing()` can emit formal `一买` from zigzag-style strokes.
- `类二买` is triggered by current price distance to `ZD`, without confirming pullback structure.
- `三买` is triggered by `recent_low > ZG`, but uses current day price/index instead of the completed pullback low.

This causes invalid states such as `trend_type=无中枢` while a stock is marked as `三买`.

## Non-Goals

- Do not optimize returns in this phase.
- Do not tune thresholds to get more picks.
- Do not add new strategy filters before the structure pipeline is stable.
- Do not implement the full advanced feature-sequence version of lessons 67/71/78 in the first pass.
- Do not remove swing tracking entirely; isolate it.

## Target Principles

1. Formal buy signals must only come from the standard path.
2. A standard `三买` requires a standard pivot.
3. A standard `二买` must occur after `一买`.
4. A standard `一买` must not be created by swing-only structures.
5. Swing output can support visualization and scoring, not formal classification.
6. QA must include automated structure tests and manual chart review.

---

## Proposed Pipeline

### Standard Path

```text
raw klines
-> inclusion_process()
-> find_fractals()
-> build_strokes()
-> build_segments_by_break()
-> find_pivots()
-> classify_trend()
-> check_divergence()
-> locate_buy_sell_points()
```

### Auxiliary Swing Path

```text
raw klines
-> build_strokes_swing()      # existing function; output is renamed conceptually to swing_waves
-> prune_strokes()            # existing function; used only on swing_waves
-> optional display/scoring metadata
```

The swing path must not populate `result.stroke_pivots` as formal pivots. It should be exposed as `result.swing_waves` and optionally `result.swing_zones`.

---

## Data Model Changes

### Modify `Segment`

File: `chanlun_strategy/chanlun/chan_engine.py`

Add fields:

```python
@dataclass
class Segment:
    strokes: list
    start_idx: int
    end_idx: int
    direction: str
    high: float
    low: float
    destroyed_by_idx: Optional[int] = None
    confirmed: bool = True
```

Rationale:

- `destroyed_by_idx` records where the next opposite segment confirmed destruction.
- `confirmed=False` can be used for the latest unfinished segment, if kept for chart display.

### Modify `ChanResult`

Replace ambiguous swing fields:

```python
stroke_pivots: list = field(default_factory=list)
strokes_swing: list = field(default_factory=list)
```

with:

```python
swing_waves: list = field(default_factory=list)
swing_zones: list = field(default_factory=list)
```

Migration rule:

- Do not use `swing_zones` in `_get_pivot_info()`.
- Report/chart code may show them as auxiliary overlays with a different label.

---

## Segment Algorithm Spec

### Core Definition

Use a practical destruction-confirmed segment algorithm:

- A segment starts once at least three alternating strokes exist.
- An up segment starts from `up-down-up`; a down segment starts from `down-up-down`.
- The current segment continues to absorb subsequent strokes until it is destroyed.
- An up segment is destroyed only when a later down stroke breaks the segment's key low.
- A down segment is destroyed only when a later up stroke breaks the segment's key high.
- After destruction, close the old segment and start a new opposite segment from the destruction-related stroke window.

This is a first-pass implementation of the "segment destruction" principle, not the full feature-sequence algorithm.

### Key Low / Key High

For an up segment:

- Track lows of all down strokes inside the segment.
- `key_low = min(down_stroke.end_price or low endpoint)` depending on stroke direction.
- If a later down stroke low `< key_low`, the up segment is destroyed.

For a down segment:

- Track highs of all up strokes inside the segment.
- `key_high = max(up_stroke.end_price or high endpoint)`.
- If a later up stroke high `> key_high`, the down segment is destroyed.

### Stroke Price Helpers

Create helper functions:

```python
def stroke_high(stroke: Stroke) -> float:
    return max(stroke.start_price, stroke.end_price)

def stroke_low(stroke: Stroke) -> float:
    return min(stroke.start_price, stroke.end_price)
```

### Segment Building Pseudocode

```python
def build_segments_by_break(strokes):
    if len(strokes) < 3:
        return []

    segments = []
    i = 0

    while i <= len(strokes) - 3:
        seed = find_next_alternating_three(strokes, i)
        if seed is None:
            break

        start = seed
        direction = strokes[start].direction
        current = strokes[start:start + 3]
        j = start + 3

        while j < len(strokes):
            current.append(strokes[j])

            if segment_destroyed(current, direction):
                old_strokes, new_start = split_at_destruction(current, direction)
                segments.append(make_segment(old_strokes, confirmed=True))
                i = new_start
                break

            j += 1
        else:
            segments.append(make_segment(current, confirmed=False))
            break

    return segments
```

The exact `split_at_destruction()` should be simple in phase 1:

- When an up segment is destroyed by a down stroke at index `k`, close old segment at the previous confirmed high stroke before `k`.
- Start the next segment from that high stroke.
- Reverse for down segments.

If this split is ambiguous, keep the old segment ending at the stroke before destruction and start the new segment at the destruction stroke's previous stroke. The important QA rule is that segments must not overlap as arbitrary 3-stroke windows.

---

## Buy Signal Rules After Refactor

### 一买

Formal `一买` requires:

- Standard `result.segments` exists.
- `result.divergence.type` contains `趋势底背驰`, or if `盘整底背驰`, it must not be labeled as formal `一买`; label it `盘整背驰参考`.
- Last segment direction is `down`.
- Buy price = last down segment low.
- Buy index = segment low's corresponding stroke endpoint index.

### 二买

Formal `二买` requires:

- A prior formal `一买`.
- A standard upward movement after `一买`.
- First standard pullback after that upward movement.
- Pullback low > first-buy low.
- Buy price = pullback low, not current close.
- Buy index > first-buy index.

### 三买

Formal `三买` requires:

- At least one standard pivot in `result.pivots`.
- A standard upward leave movement after the pivot.
- The first standard pullback after leaving the pivot is complete.
- Pullback low > pivot.ZG.
- Buy price = pullback low.
- Buy index = pullback low index.
- If current price is more than a configurable distance above buy price, mark as `三买已错过`, not selected.

Suggested missed threshold:

```python
THIRD_BUY_MAX_CHASE_PCT = 0.08
```

### 类二买

Phase 1:

- Disable from selection.
- If needed for visibility, emit `中枢震荡低吸参考`, not `类二买`.

Phase 2:

- Reintroduce only after standard segments are stable.
- It must require a completed pullback near `ZD`, not a static current-price distance.

---

## Implementation Tasks

### Task 1: Add Structure Fixture Tests

**Files:**

- Create: `chanlun_strategy/tests/test_segment_builder.py`
- Modify: none

**Step 1: Create deterministic stroke fixtures**

Use direct `Stroke` objects rather than K-line data, so the test isolates segment building.

```python
import unittest

from chanlun.chan_engine import Stroke, build_segments_by_break

def s(a, b, ap, bp, direction):
    return Stroke(
        start_idx=a,
        end_idx=b,
        start_price=ap,
        end_price=bp,
        direction=direction,
    )
```

**Step 2: Test that a simple up segment is not split into fixed 3-stroke windows**

```python
class SegmentBuilderTests(unittest.TestCase):
    def test_up_segment_extends_until_destroyed(self):
        strokes = [
            s(0, 1, 10, 15, "up"),
            s(1, 2, 15, 12, "down"),
            s(2, 3, 12, 18, "up"),
            s(3, 4, 18, 14, "down"),
            s(4, 5, 14, 20, "up"),
            s(5, 6, 20, 11, "down"),  # destroys prior key low 12
            s(6, 7, 11, 16, "up"),
            s(7, 8, 16, 9, "down"),
        ]

        segments = build_segments_by_break(strokes)

        self.assertGreaterEqual(len(segments), 1)
        self.assertGreater(len(segments[0].strokes), 3)
        self.assertEqual(segments[0].direction, "up")
        self.assertEqual(segments[0].start_idx, 0)
```

**Step 3: Test no arbitrary overlap**

```python
    def test_segments_are_not_arbitrary_three_stroke_windows(self):
        strokes = [
            s(0, 1, 10, 15, "up"),
            s(1, 2, 15, 12, "down"),
            s(2, 3, 12, 18, "up"),
            s(3, 4, 18, 14, "down"),
            s(4, 5, 14, 20, "up"),
        ]

        segments = build_segments_by_break(strokes)

        self.assertEqual(len(segments), 1)
        self.assertEqual([st.start_idx for st in segments[0].strokes], [0, 1, 2, 3, 4])


if __name__ == "__main__":
    unittest.main()
```

**Step 4: Run test and verify it fails before implementation**

Run:

```bash
cd chanlun_strategy
python3 -m unittest discover -s tests -p 'test_*.py'
```

Expected:

- Import or attribute failure because `build_segments_by_break` does not exist.

---

### Task 2: Implement `build_segments_by_break`

**Files:**

- Modify: `chanlun_strategy/chanlun/chan_engine.py`
- Test: `chanlun_strategy/tests/test_segment_builder.py`

**Step 1: Add helper functions**

```python
def stroke_high(stroke):
    return max(stroke.start_price, stroke.end_price)

def stroke_low(stroke):
    return min(stroke.start_price, stroke.end_price)
```

**Step 2: Add segment helpers**

```python
def _is_alternating(strokes):
    return all(strokes[i].direction != strokes[i + 1].direction for i in range(len(strokes) - 1))

def _make_segment(strokes, confirmed=True, destroyed_by_idx=None):
    return Segment(
        strokes=strokes[:],
        start_idx=strokes[0].start_idx,
        end_idx=strokes[-1].end_idx,
        direction=strokes[0].direction,
        high=max(stroke_high(s) for s in strokes),
        low=min(stroke_low(s) for s in strokes),
        confirmed=confirmed,
        destroyed_by_idx=destroyed_by_idx,
    )
```

**Step 3: Implement minimal destruction logic**

```python
def _segment_destroyed(candidate, direction):
    if len(candidate) < 4:
        return False

    last = candidate[-1]
    prior = candidate[:-1]

    if direction == "up" and last.direction == "down":
        prior_down_lows = [stroke_low(s) for s in prior if s.direction == "down"]
        return bool(prior_down_lows) and stroke_low(last) < min(prior_down_lows)

    if direction == "down" and last.direction == "up":
        prior_up_highs = [stroke_high(s) for s in prior if s.direction == "up"]
        return bool(prior_up_highs) and stroke_high(last) > max(prior_up_highs)

    return False
```

**Step 4: Implement `build_segments_by_break`**

```python
def build_segments_by_break(strokes):
    if len(strokes) < 3:
        return []

    segments = []
    i = 0
    n = len(strokes)

    while i <= n - 3:
        while i <= n - 3 and not _is_alternating(strokes[i:i + 3]):
            i += 1
        if i > n - 3:
            break

        current = strokes[i:i + 3]
        j = i + 3
        closed = False

        while j < n:
            current.append(strokes[j])
            if not _is_alternating(current[-3:]):
                j += 1
                continue

            if _segment_destroyed(current, current[0].direction):
                old = current[:-1]
                segments.append(_make_segment(old, confirmed=True, destroyed_by_idx=strokes[j].end_idx))
                i = max(j - 2, i + 1)
                closed = True
                break

            j += 1

        if not closed:
            segments.append(_make_segment(current, confirmed=False))
            break

    return segments
```

**Step 5: Run tests**

Run:

```bash
cd chanlun_strategy
python3 -m unittest discover -s tests -p 'test_*.py'
```

Expected:

- New tests pass.

---

### Task 3: Swap Standard Pipeline to New Segment Builder

**Files:**

- Modify: `chanlun_strategy/config.py`
- Modify: `chanlun_strategy/chanlun/chan_engine.py`
- Test: `chanlun_strategy/tests/test_pipeline_invariants.py`

**Step 1: Add feature flag**

In `chanlun_strategy/config.py`:

```python
USE_SEGMENT_BREAK_BUILDER = True
```

This gives the rollback plan a concrete switch.

**Step 2: Add pipeline invariant tests**

Create `chanlun_strategy/tests/test_pipeline_invariants.py`.

```python
import unittest
import numpy as np
from chanlun.chan_engine import analyze

class PipelineInvariantTests(unittest.TestCase):
    def test_no_third_buy_without_standard_pivot(self):
        dates = list(range(60))
        closes = np.array([10 + i * 0.1 for i in range(60)], dtype=float)
        highs = closes + 0.2
        lows = closes - 0.2
        opens = closes
        volumes = np.ones(60) * 10000

        result = analyze("TEST", "TEST", dates, opens, highs, lows, closes, volumes)

        if not result.pivots:
            self.assertFalse(any(bp["type"] == "三买" for bp in result.buy_points))


if __name__ == "__main__":
    unittest.main()
```

**Step 3: Change analyze**

Replace:

```python
segments = build_segments(strokes)
```

with:

```python
from config import USE_SEGMENT_BREAK_BUILDER

segments = build_segments_by_break(strokes) if USE_SEGMENT_BREAK_BUILDER else build_segments_fixed_window(strokes)
```

Keep old `build_segments()` temporarily as `build_segments_fixed_window()` if needed for comparison.

**Step 4: Run tests**

Run:

```bash
cd chanlun_strategy
python3 -m unittest discover -s tests -p 'test_*.py'
```

Expected:

- Invariant test passes.

---

### Task 4: Isolate Swing From Formal Buy Signals

**Files:**

- Modify: `chanlun_strategy/chanlun/chan_engine.py`
- Modify: `chanlun_strategy/chanlun/screener_pure.py`
- Modify: `chanlun_strategy/chanlun/screener_fusion.py`
- Modify: `chanlun_strategy/chanlun/report_generator.py`
- Test: `chanlun_strategy/tests/test_pipeline_invariants.py`

**Step 1: Rename fields**

In `ChanResult`, replace:

```python
stroke_pivots
strokes_swing
```

with:

```python
swing_waves
swing_zones
```

**Step 2: Update analyze**

Replace:

```python
sw_strokes_raw = build_strokes_swing(...)
sw_strokes = prune_strokes(...)
stroke_pivots = build_stroke_pivots(sw_strokes)
```

with:

```python
swing_waves_raw = build_strokes_swing(...)
swing_waves = prune_strokes(swing_waves_raw, min_pct=0.06)
swing_zones = build_stroke_pivots(swing_waves)
```

Do not use `swing_zones` for `result.pivots`.

**Step 3: Update pivot extraction**

In `_get_pivot_info()`, remove fallback to swing pivots:

```python
sp = result.pivots
```

**Step 4: Disable swing formal first buy**

Remove or disable:

```python
_detect_first_buy_from_swing(result, buy_points)
```

If retained, it must append:

```python
{"type": "swing底背驰参考", ...}
```

and screeners must not select it.

**Step 5: Add invariant test**

```python
def test_swing_does_not_create_formal_buy_points(self):
    # Use an upward-only dataset likely to create swing waves but no standard pivot.
    # The exact data can be adjusted after first run.
    ...
    if not result.pivots:
        self.assertFalse(any(bp["type"] in {"一买", "二买", "三买"} for bp in result.buy_points))
```

**Step 6: Run tests**

Run:

```bash
cd chanlun_strategy
python3 -m unittest discover -s tests -p 'test_*.py'
```

Expected:

- No formal buy point is emitted solely from swing data.

---

### Task 5: Rewrite Third Buy

**Files:**

- Modify: `chanlun_strategy/chanlun/chan_engine.py`
- Test: `chanlun_strategy/tests/test_buy_points.py`

**Step 1: Create tests**

```python
def test_third_buy_requires_standard_pivot():
    result = make_result_with_no_pivots_but_price_above_fake_zone()
    buy_points, _ = locate_buy_sell_points(result)
    self.assertFalse(any(bp["type"] == "三买" for bp in buy_points))

def test_third_buy_uses_pullback_low_not_current_close():
    result = make_result_with_pivot_leave_and_pullback()
    buy_points, _ = locate_buy_sell_points(result)
    third = next(bp for bp in buy_points if bp["type"] == "三买")
    self.assertEqual(third["price"], expected_pullback_low)
    self.assertEqual(third["index"], expected_pullback_low_idx)
```

Use direct `ChanResult`, `Pivot`, `Segment`, and `Stroke` objects for this test rather than full K-line data. Implement these tests inside a `unittest.TestCase` class, consistent with the project test command.

**Step 2: Rewrite logic**

Implement a dedicated function:

```python
def _find_third_buy_point(result, buy_points):
    if not result.pivots or len(result.segments) < 2:
        return

    pivot = result.pivots[-1]
    post = [s for s in result.segments if s.start_idx >= pivot.end_idx]
    if len(post) < 2:
        return

    leave = post[-2]
    pullback = post[-1]

    if leave.direction != "up" or pullback.direction != "down":
        return
    if pullback.low <= pivot.ZG:
        return

    current_price = float(result.closes[-1])
    if (current_price - pullback.low) / pullback.low > THIRD_BUY_MAX_CHASE_PCT:
        buy_type = "三买已错过"
    else:
        buy_type = "三买"

    buy_points.append({...})
```

**Step 3: Screeners ignore missed signals**

Update both screeners so `三买已错过` is displayed but not selected.

**Step 4: Run tests**

Run:

```bash
cd chanlun_strategy
python3 -m unittest discover -s tests -p 'test_*.py'
```

Expected:

- Third-buy tests pass.

---

### Task 6: Rewrite Second Buy

**Files:**

- Modify: `chanlun_strategy/chanlun/chan_engine.py`
- Test: `chanlun_strategy/tests/test_buy_points.py`

**Step 1: Test second buy must be after first buy**

```python
def test_second_buy_must_be_after_first_buy():
    result = make_result_with_first_buy_and_later_pullback()
    buy_points, _ = locate_buy_sell_points(result)
    first = next(bp for bp in buy_points if bp["type"] == "一买")
    second = next(bp for bp in buy_points if bp["type"] == "二买")

    self.assertGreater(second["index"], first["index"])
    self.assertGreater(second["price"], first["price"])
```

**Step 2: Test no same-index second buy**

```python
def test_second_buy_cannot_share_first_buy_index():
    result = make_result_with_only_first_buy()
    buy_points, _ = locate_buy_sell_points(result)
    self.assertFalse(any(bp["type"] == "二买" for bp in buy_points))
```

Implement these tests inside a `unittest.TestCase` class.

**Step 3: Implement `_find_second_buy_point`**

```python
def _find_second_buy_point(result, buy_points):
    first_buys = [bp for bp in buy_points if bp["type"] == "一买"]
    if not first_buys:
        return

    first = max(first_buys, key=lambda x: x["index"])
    first_idx = first["index"]
    first_price = first["price"]

    post_segments = [s for s in result.segments if s.start_idx > first_idx]
    if len(post_segments) < 2:
        return

    # Need upward movement then first pullback.
    saw_up = False
    for seg in post_segments:
        if not saw_up:
            if seg.direction == "up":
                saw_up = True
            continue

        if seg.direction == "down":
            if seg.low > first_price:
                buy_points.append({
                    "type": "二买",
                    "index": seg.end_idx,
                    "price": round(seg.low, 2),
                    ...
                })
            return
```

**Step 4: Call it after first-buy detection**

In `locate_buy_sell_points()`, call:

```python
_find_second_buy_point(result, buy_points)
```

before third-buy detection.

**Step 5: Run tests**

Expected:

- No `二买` with `index <= 一买.index`.

---

### Task 7: Disable Class-2 Buy Selection

**Files:**

- Modify: `chanlun_strategy/chanlun/chan_engine.py`
- Modify: `chanlun_strategy/chanlun/screener_pure.py`
- Modify: `chanlun_strategy/chanlun/screener_fusion.py`
- Modify: `chanlun_strategy/chanlun/report_generator.py`

**Step 1: Remove formal `类二买` append**

In `_find_pivot_buy_points()`, remove current static-distance class-2 logic.

Optional display-only replacement:

```python
buy_points.append({
    "type": "中枢震荡低吸参考",
    ...
})
```

Screeners must not select this type.

**Step 2: Update priorities**

Pure:

```python
bp_order = {"三买": 0, "二买": 1, "一买": 2}
```

Fusion:

```python
bp_order = {"三买": 0, "二买": 1, "一买": 2}
```

Remove `类二买` from `FUSION_BUY_POINTS_TREND` in `config.py` for phase 1:

```python
FUSION_BUY_POINTS_TREND = ["三买"]
```

**Step 3: Run sample report**

Run:

```bash
cd chanlun_strategy
python3 run.py --debug
```

Expected:

- Picks decrease.
- No selected `类二买`.

---

## QA Plan

### QA Layer 1: Unit Tests

Run:

```bash
cd chanlun_strategy
python3 -m unittest discover -s tests -p 'test_*.py'
```

Must pass:

- Segment builder tests.
- Buy point invariants.
- No third buy without standard pivot.
- No second buy at same index as first buy.
- Swing does not create formal buy points.

### QA Layer 2: Static Signal Invariants

Create script:

`chanlun_strategy/scripts/qa_signal_invariants.py`

Checks on generated JSON:

```python
def load_report(payload):
    # Supports both docs/data/YYYY-MM-DD.json and aggregate docs/data.json.
    if "reports" not in payload:
        return payload
    latest = payload["dates"][-1]
    return payload["reports"][latest]

def selected_buy_points(report):
    for key in ("picks_pure", "picks_fusion"):
        for pick in report.get(key, []):
            yield pick, pick["best_buy_point"]
            for bp in pick.get("buy_points", []):
                yield pick, bp

for pick, bp in selected_buy_points(report):
    assert not (pick["trend_type"] == "无中枢" and bp["type"] == "三买")
    assert bp["type"] != "类二买"
    assert not (bp["type"] == "三买" and "已涨" in bp.get("reason", ""))

for pick in report.get("picks_pure", []) + report.get("picks_fusion", []):
    firsts = [bp for bp in pick.get("buy_points", []) if bp["type"] == "一买"]
    seconds = [bp for bp in pick.get("buy_points", []) if bp["type"] == "二买"]
    for first in firsts:
        for second in seconds:
            assert second["index"] > first["index"]
```

Run:

```bash
cd chanlun_strategy
python3 scripts/qa_signal_invariants.py docs/data/2026-05-24.json
```

Expected:

- `PASS: all signal invariants satisfied`

### QA Layer 3: Debug Report Run

Run:

```bash
cd chanlun_strategy
python3 run.py --debug
```

Expected:

- No crash.
- Output JSON generated under `output_debug`.
- Number of picks is lower than before or equal, not materially higher.
- No selected `类二买`.
- No formal `三买` with `trend_type=无中枢`.

### QA Layer 4: Historical JSON Regression

Run invariant script on existing reports:

```bash
cd chanlun_strategy
python3 scripts/qa_signal_invariants.py docs/data/2026-05-23.json
python3 scripts/qa_signal_invariants.py docs/data/2026-05-24.json
python3 scripts/qa_signal_invariants.py docs/data/2026-05-24_v3.json
```

Expected after regenerating reports:

- No invalid formal signal remains.

If using old JSON before regeneration:

- The script should fail and list known historical problems. This confirms QA catches the original bug.

### QA Layer 5: Manual Chart Review

Review at least 20 stocks across categories:

- 5 previous false `三买` examples:
  - `002833`
  - `003019`
  - `300632`
  - `300838`
  - `603773`
- 5 previous `类二买` examples:
  - `300578`
  - `603331`
  - `002827`
  - `605060`
  - `300269`
- 5 previous `一买` examples:
  - `000751`
  - `605288`
  - `300241`
  - `000506`
  - `300120`
- 5 random current selected picks.

Manual acceptance checklist per chart:

- Are fractals visually reasonable after inclusion?
- Are strokes alternating and anchored at meaningful top/bottom fractals?
- Do segments extend until meaningful destruction rather than splitting every 3 strokes?
- Does each pivot have at least 3 completed standard segments?
- If marked `三买`, is there a visible pivot, upward leave, and first pullback not returning to `ZG`?
- If marked `二买`, is it after `一买` and after a real upward movement?
- If marked `一买`, is it a standard trend divergence rather than only swing divergence?

Record results in:

`chanlun_strategy/docs/qa/2026-05-25-segment-refactor-review.md`

Create the directory first:

```bash
mkdir -p chanlun_strategy/docs/qa
```

### QA Layer 6: Pick Quality Metrics

After a full run, compare before/after:

Metrics:

- Total picks.
- Count by best buy point type.
- Count of `trend_type=无中枢`.
- Count of selected `三买` with `trend_type=无中枢`.
- Count of selected `类二买`.
- Count of `二买.index <= 一买.index`.
- Median distance from signal price to current close.
- Percentage of selected picks with 30min weak/no confirmation.

Expected direction:

- Total picks decreases.
- Invalid signal counts become zero.
- Median chase distance decreases.
- Weak/no 30min confirmation ratio decreases.

### QA Layer 7: Performance

Run debug and one full run timing:

```bash
cd chanlun_strategy
time python3 run.py --debug
```

Expected:

- New segment builder should not increase runtime by more than 30% on debug sample.
- If full run is available, runtime should remain operationally acceptable.

---

## Acceptance Criteria

Implementation is acceptable only if all are true:

1. Unit tests pass.
2. No selected `三买` exists without a standard pivot.
3. No selected `类二买` in phase 1.
4. No `二买` shares or precedes its related `一买` index.
5. Swing output does not create formal buy points.
6. Manual chart review passes at least 16/20 cases.
7. Report generation still works.
8. Invalid historical patterns are caught by QA scripts.

---

## Rollback Plan

Keep old logic under explicit names for one release:

- `build_segments_fixed_window()`
- `build_stroke_pivots()` retained only for swing display.

Feature flag:

```python
USE_SEGMENT_BREAK_BUILDER = True
```

If output becomes unusable:

1. Set `USE_SEGMENT_BREAK_BUILDER = False`.
2. Regenerate debug report.
3. Keep QA scripts and tests; do not remove them.
4. Compare failed charts and adjust segment split logic.

---

## Commit Plan

Commit 1:

```bash
cd chanlun_strategy
git add tests/test_segment_builder.py
git commit -m "test: add chanlun segment builder fixtures"
```

Commit 2:

```bash
cd chanlun_strategy
git add chanlun/chan_engine.py
git commit -m "feat: build segments by destruction confirmation"
```

Commit 3:

```bash
cd chanlun_strategy
git add tests/test_pipeline_invariants.py chanlun/chan_engine.py config.py
git commit -m "refactor: isolate swing waves from formal chanlun signals"
```

Commit 4:

```bash
cd chanlun_strategy
git add tests/test_buy_points.py chanlun/chan_engine.py chanlun/screener_pure.py chanlun/screener_fusion.py config.py
git commit -m "fix: require standard structures for buy points"
```

Commit 5:

```bash
cd chanlun_strategy
git add scripts/qa_signal_invariants.py docs/qa
git commit -m "test: add signal invariant qa checks"
```

---

## Open Decisions

1. Whether latest unfinished segment should be included in pivot detection.
   Recommendation: no. Use `confirmed=True` segments only for pivots and buy points.

2. Whether `盘整底背驰` can be selected.
   Recommendation: not as `一买`; display as reference only until signal quality improves.

3. Whether to keep `类二买`.
   Recommendation: disable for phase 1, reintroduce only after standard structures pass QA.

4. Whether to implement full feature-sequence segment rules.
   Recommendation: not in phase 1. First stabilize destruction-confirmed segments and inspect charts.
