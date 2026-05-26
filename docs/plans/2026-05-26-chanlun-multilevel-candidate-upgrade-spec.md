# Chanlun Multi-Level Candidate Upgrade Spec

> **For implementers:** This is an execution-ready spec. Implement task-by-task and do not change the signal semantics without updating the QA rules in this document.

## Goal

The current pipeline can scan hundreds of stocks, detect many `buy_points`, and still output zero recommendations because the daily screener only accepts fully confirmed daily `一买/二买/三买`. This is too restrictive for Chanlun practice.

This refactor introduces a multi-level signal pipeline:

```text
daily structure signal
-> daily structure candidate pool
-> 30min sub-level confirmation
-> upgrade to recommendable candidate
-> score and display
```

The key change is that 30min confirmation must be able to upgrade daily unfinished or reference structures into candidate recommendations. 30min must not run only after daily formal picks have already filtered everything out.

## Non-Goals

- Do not weaken the definition of formal daily `一买/二买/三买`.
- Do not reintroduce `类二买` as a formal buy point.
- Do not allow `swing底背驰参考` alone to become a recommendation.
- Do not add fixed count padding such as `不足20只补齐`.
- Do not use score thresholds as the main admission rule.
- Do not optimize historical returns in this pass.

## Current Failure Mode

Observed 2026-05-26 run:

```text
342 stocks scanned
194 stocks had buy_points
pure daily pool = 0
fusion daily pool = 0
final recommendations = 0
```

Root cause:

```text
screen_daily_pure/screen_daily_fusion only accept formal daily signals:
一买 / 二买 / 三买

They exclude:
二买待确认
盘整背驰参考
中枢震荡低吸参考
swing底背驰参考
三买已错过

Then run.py only fetches 30min data for stocks already in the daily pools.
If daily pools are empty, 30min cannot upgrade anything.
```

This misses the Chanlun multi-level path where a lower-level completion can confirm a higher-level candidate before the higher-level segment is fully confirmed.

## Target Signal Tiers

Every buy point used by the screeners must have a signal tier.

```text
formal      Fully confirmed daily Chanlun buy point.
candidate   Daily structure candidate confirmed by 30min sub-level signal.
reference   Informational signal only; never recommended by itself.
blocked     Explicitly not recommendable.
```

### Formal Signals

These can be recommended without 30min upgrade, although 30min resonance can improve score:

```text
一买
二买
三买
```

Requirements:

- Must come from standard daily structure, not swing.
- Must satisfy the existing confirmed segment rules.
- Must pass existing forbidden-state QA.

### Candidate Signals

These can be recommended only after 30min confirmation:

```text
二买候选
盘整低吸候选
中枢低吸候选
三买候选
```

Candidate signals must record both:

```python
{
    "type": "二买候选",
    "tier": "candidate",
    "source_type": "二买待确认",
    "confirmed_by": "30min底背驰",
    ...
}
```

### Reference Signals

These can appear in chart/report details but cannot be `best_buy_point` and cannot enter recommendations directly:

```text
二买待确认
盘整背驰参考
中枢震荡低吸参考
swing底背驰参考
```

Reference signals may become candidates only through explicit upgrade rules below.

### Blocked Signals

These should never be recommended:

```text
三买已错过
类二买
```

`三买已错过` may remain visible in charts as a warning.

## Signal Type Mapping

| Daily source signal | Tier before 30min | Can upgrade? | Upgrade output |
| --- | --- | --- | --- |
| `一买` | formal | N/A | `一买` |
| `二买` | formal | N/A | `二买` |
| `三买` | formal | N/A | `三买` |
| `二买待确认` | reference | yes | `二买候选` |
| `盘整背驰参考` | reference | yes | `盘整低吸候选` |
| `中枢震荡低吸参考` | reference | yes | `中枢低吸候选` |
| Daily unfinished third-buy setup | reference/candidate seed | yes | `三买候选` |
| `swing底背驰参考` only | reference | no by itself | none |
| `三买已错过` | blocked | no | none |
| `类二买` | blocked | no | none |

## Architecture

### Existing Pipeline

```text
daily analyze all stocks
-> screen_daily_pure/fusion keep only formal daily picks
-> fetch 30min only for those picks
-> 30min confirmation
-> score/report
```

### Target Pipeline

```text
daily analyze all stocks
-> build_daily_structure_pool()
   includes formal + upgradeable reference structures
-> fetch 30min for structure pool
-> analyze 30min
-> upgrade_candidates_with_30min()
   formal stays formal
   upgradeable reference becomes candidate only if 30min confirms
-> screen/rank pure and fusion views
-> score/report
```

## Data Model

### Buy Point Fields

All buy point dictionaries should support these fields:

```python
{
    "type": "二买候选",
    "tier": "candidate",          # formal | candidate | reference | blocked
    "source_type": "二买待确认",   # original daily signal when upgraded
    "index": 88,
    "price": 12.34,
    "date": "2026-05-26",
    "reason": "...",
    "strength": "中",
    "confirmed_by": "30min底背驰",
    "confirmations": ["30min底背驰", "30min底分型", "MACD金叉"],
    "risk_flags": [],
}
```

Backward compatibility:

- Existing code that reads `type`, `index`, `price`, `date`, `reason`, `strength` must still work.
- If `tier` is missing, infer it through the mapping table.

### Stock Pick Fields

Every stock pick should include:

```python
{
    "signal_tier": "formal",       # formal | candidate
    "best_buy_point": {...},
    "buy_points": [...],           # recommendable points only
    "reference_buy_points": [...], # visible but not selected
    "blocked_buy_points": [...],   # visible warnings only, never selected
    "all_buy_points": [...],       # optional debug/report detail
    "resonance": {...},
}
```

Rules:

- `buy_points` must contain only formal or upgraded candidate points.
- `reference_buy_points` may contain `二买待确认`, `盘整背驰参考`, `中枢震荡低吸参考`, `swing底背驰参考`.
- `blocked_buy_points` may contain `三买已错过`, `类二买`, and other explicit warnings.
- `best_buy_point` must come from `buy_points`.

## Components To Add Or Change

### 1. Add signal tier helpers

Suggested file:

```text
chanlun/signal_policy.py
```

Required constants:

```python
FORMAL_TYPES = {"一买", "二买", "三买"}

UPGRADEABLE_REFERENCE_TYPES = {
    "二买待确认",
    "盘整背驰参考",
    "中枢震荡低吸参考",
}

REFERENCE_ONLY_TYPES = {
    "swing底背驰参考",
}

BLOCKED_TYPES = {
    "三买已错过",
    "类二买",
}

CANDIDATE_TYPES = {
    "二买候选",
    "盘整低吸候选",
    "中枢低吸候选",
    "三买候选",
}
```

Required functions:

```python
def infer_signal_tier(bp: dict) -> str:
    ...

def is_formal_buy(bp: dict) -> bool:
    ...

def is_upgradeable_reference(bp: dict) -> bool:
    ...

def is_recommendable_buy(bp: dict) -> bool:
    ...

def is_blocked_buy(bp: dict) -> bool:
    ...
```

Expected behavior:

```text
一买/二买/三买 -> formal
二买候选/盘整低吸候选/中枢低吸候选/三买候选 -> candidate
二买待确认/盘整背驰参考/中枢震荡低吸参考/swing底背驰参考 -> reference
三买已错过/类二买 -> blocked
unknown -> reference by default
```

### 2. Keep `locate_buy_sell_points()` conservative

File:

```text
chanlun/chan_engine.py
```

Do not weaken formal signal generation.

Required changes:

- Add `tier` to emitted buy points.
- `一买/二买/三买`: `tier="formal"`.
- `二买待确认`, `盘整背驰参考`, `中枢震荡低吸参考`, `swing底背驰参考`: `tier="reference"`.
- `三买已错过`: `tier="blocked"`.

Optional but recommended:

- Add a daily unfinished third-buy detector that emits `三买待确认` as reference.
- This is useful for later `三买候选` upgrade.

`三买待确认` seed condition:

```text
daily standard pivot exists
latest daily structure has left above ZG
current or latest unfinished pullback low > ZG
current price is not more than THIRD_BUY_MAX_CHASE_PCT above pullback low
```

If this is too much for the first implementation, skip `三买候选` and implement only the three upgrade rules for existing references.

### 3. Replace daily screeners with structure pool builders

Current functions:

```text
screen_daily_pure()
screen_daily_fusion()
```

These currently discard all references before 30min. Change the flow.

Add:

```python
def build_daily_structure_pool(chan_results, sector_stocks=None, sectors=None, mode="pure", sh_closes=None):
    ...
```

Responsibilities:

- Apply base filters:
  - not ST
  - enough listed days
  - not limit up/down
  - enough liquidity
- Keep stocks with at least one:
  - formal buy point
  - upgradeable reference buy point
- Do not keep stocks whose only signal is:
  - `swing底背驰参考`
  - `三买已错过`
  - `类二买`
- Separate signals:
  - `formal_buy_points`
  - `upgradeable_buy_points`
  - `reference_buy_points`
  - `blocked_buy_points`

Return objects should include all data needed by later scoring/reporting.

Compatibility option:

- `screen_daily_pure()` and `screen_daily_fusion()` may call this new builder, then immediately return only formal picks if used outside `run.py`.
- In `run.py`, use the new builder directly so 30min can upgrade candidates.

### 4. Add 30min confirmation classifier

Suggested file:

```text
chanlun/sublevel_confirm.py
```

Required function:

```python
def classify_30min_confirmation(daily_stock: dict, source_bp: dict, min30_result) -> dict:
    ...
```

Return shape:

```python
{
    "confirmed": True,
    "level": "强",  # 强 | 中 | 弱 | 无
    "signals": ["30min底背驰", "30min底分型", "MACD金叉"],
    "reason": "30分钟底背驰 + 底分型确认",
}
```

Confirmation signals:

1. `30min底背驰`
   - `min30_result.divergence.is_divergence == True`
   - `divergence.type` contains `底背驰`

2. `30min formal/recommendable buy point`
   - `min30_result.buy_points` has a signal accepted by `signal_policy.is_recommendable_buy()`

3. `30min底分型 + MACD金叉`
   - recent bottom fractal exists
   - MACD golden cross occurs within recent 3 bars

4. `30min回拉不破日线关键位`
   - For `二买待确认`: recent 30min low > daily first-buy price.
   - For `中枢震荡低吸参考`: recent 30min low near or above daily `ZD`.
   - For `盘整背驰参考`: recent 30min low does not materially break daily signal price.
   - For `三买待确认`: recent 30min low > daily pivot `ZG`.

The classifier must receive `source_bp`, because the key level depends on the daily source signal. Do not infer one shared key level for every candidate on the same stock.

Recommended thresholds:

```python
NEAR_PRICE_PCT = 0.03
RECENT_30MIN_BARS = 8
```

Confirmation strength:

```text
强: 30min formal/recommendable buy point or 30min bottom divergence
中: bottom fractal + MACD golden cross + key level not broken
弱: key level not broken only
无: none
```

Upgrade should require `强` or `中`.

`30min formal/recommendable buy point` means `min30_result.buy_points` contains a signal allowed by `signal_policy.is_recommendable_buy()`. Reference-only 30min signals must not count as strong confirmation by themselves.

### 5. Add candidate upgrade function

Suggested location:

```text
chanlun/screener_pure.py
```

or new:

```text
chanlun/candidate_upgrade.py
```

Required function:

```python
def upgrade_daily_candidates_with_30min(daily_pool, chan_results_30min, mode="pure"):
    ...
```

Algorithm:

```text
for each stock in daily_pool:
    start with formal buy points
    if formal exists:
        keep formal as recommendable
        attach 30min resonance if available

    for each upgradeable reference buy point:
        classify 30min confirmation using (daily_stock, source_bp, min30_result)
        if confirmation level is 强 or 中:
            create candidate buy point
            append to recommendable buy_points

    if no recommendable buy_points:
        drop from recommendation output
        optionally keep in observation output if report supports it

    choose best_buy_point from recommendable points
```

Upgrade mapping:

```python
UPGRADE_OUTPUT_TYPE = {
    "二买待确认": "二买候选",
    "盘整背驰参考": "盘整低吸候选",
    "中枢震荡低吸参考": "中枢低吸候选",
    "三买待确认": "三买候选",
}
```

30min data failure behavior:

```text
If a stock has formal daily buy points:
    keep the formal buy points even when 30min data is missing.
    set resonance={"level": "弱", "reason": "30分钟数据缺失，未做次级别确认"}.

If a stock only has upgradeable references:
    do not upgrade without 30min data.
    drop from final recommendations.
    count it in diagnostics.dropped_no_30min.
```

Candidate creation:

```python
candidate = {
    **source_bp,
    "type": UPGRADE_OUTPUT_TYPE[source_bp["type"]],
    "tier": "candidate",
    "source_type": source_bp["type"],
    "confirmed_by": confirmation["reason"],
    "confirmations": confirmation["signals"],
    "strength": confirmation["level"],
    "reason": source_bp["reason"] + "；次级别确认：" + confirmation["reason"],
}
```

### 6. Update pure and fusion selection policy

Pure version:

- Admit formal daily buys.
- Admit upgraded candidates.
- Do not require MA bullish.
- Do not require market preferred type.
- Score and sort.

Fusion version:

- Admit formal and upgraded candidates.
- Keep MA and market logic as scoring/sorting preferences, not as hard exclusion except for severe risk.
- Recommended:
  - Do not hard-drop `二买候选` just because MA is not bullish.
  - For `三买` and `三买候选`, keep MA bullish as hard requirement only if the team explicitly wants trend-following behavior.

Initial fusion policy:

```text
一买 / 二买 / 二买候选 / 盘整低吸候选 / 中枢低吸候选:
    MA bullish affects score only.

三买 / 三买候选:
    require MA bullish OR 30min confirmation level == 强.
```

### 7. Update `run.py`

Replace:

```text
screen_daily_pure()
screen_daily_fusion()
fetch 30min only for those pools
screen_30min_pure()
screen_30min_fusion()
```

with:

```text
build_daily_structure_pool(mode="pure")
build_daily_structure_pool(mode="fusion")
fetch 30min for union of both structure pools
analyze 30min
upgrade_daily_candidates_with_30min(mode="pure")
upgrade_daily_candidates_with_30min(mode="fusion")
score
report
```

Important:

- Remove fixed count padding/filtering from the recommendation path.
- Do not add `adaptive_filter` back.
- If final output is 0, report diagnostics must show why:
  - daily structure pool count
  - formal count
  - upgradeable count
  - 30min confirmed candidate count
  - missing 30min count
  - final count

Required console output example:

```text
Phase 4: Daily structure pool
[pure] base_pass=342, with_signal=194, formal=0, upgradeable=71, reference_only=123, pool=71
[fusion] base_pass=342, with_signal=194, formal=0, upgradeable=71, reference_only=123, pool=71

Phase 5: 30min upgrade
30min fetched=71, analyzed=68
[pure] formal_kept=0, candidate_upgraded=12, dropped_no_confirm=56, dropped_no_30min=3
[fusion] formal_kept=0, candidate_upgraded=8, dropped_no_confirm=60, dropped_no_30min=3
```

### 8. Update scoring

File:

```text
chanlun/scorer.py
```

Add signal tier score component or incorporate it into existing scoring.

Suggested simple adjustment:

```python
SIGNAL_TIER_BASE = {
    "formal": 100,
    "candidate": 75,
    "reference": 30,
    "blocked": 0,
}
```

Do not score `reference` or `blocked` as recommendations.

Candidate type ordering:

```python
BUY_TYPE_PRIORITY = {
    "三买": 0,
    "二买": 1,
    "一买": 2,
    "三买候选": 3,
    "二买候选": 4,
    "盘整低吸候选": 5,
    "中枢低吸候选": 6,
}
```

Sorting should prefer:

```text
formal before candidate
then type priority
then score
```

Score should explain ranking, not admission.

### 9. Update report display

File:

```text
chanlun/report_generator.py
```

Display labels:

```text
正式买点: 一买 / 二买 / 三买
候选买点: 二买候选 / 三买候选 / 盘整低吸候选 / 中枢低吸候选
参考信号: 二买待确认 / 盘整背驰参考 / 中枢震荡低吸参考 / swing底背驰参考
风险/错过: 三买已错过
```

Recommended table columns:

```text
股票
信号
层级
价格
评分
30min确认
共振
理由
```

Visual rule:

- Formal: strongest badge.
- Candidate: distinct badge, not visually identical to formal.
- Reference: only inside detail/chart, not main recommendation table.

### 10. Update QA script

File:

```text
scripts/qa_signal_invariants.py
```

Allowed best buy point types:

```python
ALLOWED_BEST_TYPES = {
    "一买",
    "二买",
    "三买",
    "二买候选",
    "盘整低吸候选",
    "中枢低吸候选",
    "三买候选",
}
```

Forbidden best types:

```python
FORBIDDEN_BEST_TYPES = {
    "类二买",
    "二买待确认",
    "swing底背驰参考",
    "中枢震荡低吸参考",
    "盘整背驰参考",
    "三买已错过",
}
```

New QA invariants:

1. `best_buy_point.type` must be in `ALLOWED_BEST_TYPES`.
2. `best_buy_point.type` must not be in `FORBIDDEN_BEST_TYPES`.
3. Every item in `buy_points` must be in `ALLOWED_BEST_TYPES`.
4. No item in `buy_points` may be in `FORBIDDEN_BEST_TYPES`.
5. Candidate best points must have:
   - `tier == "candidate"`
   - `source_type`
   - `confirmed_by`
   - non-empty `confirmations`
6. `二买候选.source_type` must be `二买待确认`.
7. `盘整低吸候选.source_type` must be `盘整背驰参考`.
8. `中枢低吸候选.source_type` must be `中枢震荡低吸参考`.
9. `三买候选` must have a valid daily pivot `ZG`.
10. `swing底背驰参考` alone must never become best.
11. `三买` and `三买候选` must not appear when daily pivot count is zero.
12. `二买.index > 一买.index` when both exist.
13. If `candidate_upgraded > 0`, diagnostics must include `requested_30min`, `fetched_30min`, and `dropped_no_confirm`.

### 11. Add diagnostics QA

Add a debug JSON section:

```python
"diagnostics": {
    "daily_scan": {
        "total": 342,
        "base_pass": 342,
        "with_buy_points": 194,
        "formal_count": 0,
        "upgradeable_count": 71,
        "reference_only_count": 123,
        "blocked_only_count": 0
    },
    "sublevel_upgrade": {
        "requested_30min": 71,
        "fetched_30min": 68,
        "formal_kept": 0,
        "candidate_upgraded": 12,
        "dropped_no_confirm": 56,
        "dropped_no_30min": 3
    }
}
```

This is mandatory. Without diagnostics, future "0 picks" cannot be explained.

## Implementation Plan

### Step 1: Add signal policy module

Create:

```text
chanlun/signal_policy.py
```

Implement constants and helper functions.

Tests:

```text
tests/test_signal_policy.py
```

Cover:

- formal types.
- candidate types.
- reference types.
- blocked types.
- unknown defaults to reference.

### Step 2: Add `tier` to buy point emission

Modify:

```text
chanlun/chan_engine.py
```

For every `buy_points.append`, add appropriate `tier`.

Tests:

- Existing buy point tests should assert tier.
- `二买待确认` must be reference.
- `三买已错过` must be blocked.

### Step 3: Build daily structure pool

Modify:

```text
chanlun/screener_pure.py
chanlun/screener_fusion.py
```

or create:

```text
chanlun/daily_structure_pool.py
```

Implementation requirements:

- Base filters stay.
- Formal and upgradeable reference signals enter pool.
- Reference-only swing signals do not enter pool.
- Blocked-only signals do not enter pool.
- Return diagnostics counters.

Tests:

- Stock with only `swing底背驰参考` is excluded.
- Stock with `二买待确认` is included in structure pool but not final recommendations yet.
- Stock with formal `二买` is included as formal.
- Stock with `三买已错过` only is excluded.

### Step 4: Add 30min confirmation classifier

Create:

```text
chanlun/sublevel_confirm.py
```

Tests:

- 30min bottom divergence returns strong confirmation.
- 30min formal buy returns strong confirmation.
- Bottom fractal + MACD golden cross returns medium confirmation.
- Key level not broken only returns weak confirmation.
- No signal returns no confirmation.

### Step 5: Add candidate upgrade function

Create:

```text
chanlun/candidate_upgrade.py
```

Tests:

- `二买待确认` + strong 30min confirmation -> `二买候选`.
- `二买待确认` + no 30min confirmation -> no recommendation.
- `盘整背驰参考` + medium 30min confirmation -> `盘整低吸候选`.
- `中枢震荡低吸参考` + medium 30min confirmation -> `中枢低吸候选`.
- `swing底背驰参考` + strong 30min confirmation -> no recommendation unless another upgradeable daily structure exists.
- Formal `二买` remains `二买`.

### Step 6: Rewrite `run.py` pipeline

Modify:

```text
run.py
```

Required flow:

```text
daily analysis
daily structure pool
30min fetch for structure pool union
30min analysis
candidate upgrade
score
report
```

Remove or bypass old behavior:

- Do not fetch 30min only for formal daily picks.
- Do not use `adaptive_filter`.
- Do not require fixed output count.

### Step 7: Update scoring and sorting

Modify:

```text
chanlun/scorer.py
```

Requirements:

- Formal ranks above candidate.
- Candidate is still scoreable.
- Reference and blocked never appear in scored recommendations.

### Step 8: Update report generator

Modify:

```text
chanlun/report_generator.py
```

Requirements:

- Render candidate badges separately from formal badges.
- Show `confirmed_by`.
- Preserve `reference_buy_points` in detail view if available.
- Include diagnostics section or hidden JSON field.

### Step 9: Update QA

Modify:

```text
scripts/qa_signal_invariants.py
```

Add candidate invariants and diagnostics checks.

### Step 10: Run full verification

Commands:

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
python3 run.py --debug
python3 scripts/qa_signal_invariants.py output_debug/data/$(date +%F).json
python3 run.py
python3 scripts/qa_signal_invariants.py docs/data/$(date +%F).json
python3 scripts/qa_signal_invariants.py docs/data.json
```

## Acceptance Criteria

### Functional

- Daily structure pool is not empty when there are upgradeable daily structures.
- 30min is fetched for structure pool, not only formal daily picks.
- Formal daily signals continue to be recommendable.
- Upgradeable reference signals can become candidate recommendations only after 30min confirmation.
- Reference-only swing signals cannot become recommendations by themselves.
- Blocked signals cannot become recommendations.

### Quality

- If final recommendations are zero, report diagnostics explain the exact drop-off.
- No fixed `top_n=20` padding or score threshold gating remains in the recommendation path.
- `best_buy_point` is always formal or candidate.
- Candidate recommendations always include `source_type` and 30min confirmation metadata.

### QA

- Unit tests pass.
- Debug run QA passes.
- Formal run QA passes.
- Manual chart review includes at least:
  - 3 upgraded `二买候选` examples, if present.
  - 3 upgraded `盘整低吸候选` or `中枢低吸候选` examples, if present.
  - Any `三买候选`, if present.

## Rollback Plan

Add config gates:

```python
ENABLE_DAILY_STRUCTURE_POOL = True
ENABLE_30MIN_CANDIDATE_UPGRADE = True
```

Rollback options:

```text
ENABLE_30MIN_CANDIDATE_UPGRADE=False
    Keeps formal daily recommendations only.

ENABLE_DAILY_STRUCTURE_POOL=False
    Restores old daily screener path.
```

Both flags should default to `True` after QA passes.

## Review Checklist

Before merge, reviewer should verify:

- `screen_daily_*` no longer discards upgradeable references before 30min.
- `run.py` fetches 30min for the daily structure pool.
- `二买待确认` cannot directly become best; it must become `二买候选`.
- `盘整背驰参考` cannot directly become best; it must become `盘整低吸候选`.
- `中枢震荡低吸参考` cannot directly become best; it must become `中枢低吸候选`.
- `swing底背驰参考` cannot become best.
- QA script rejects forbidden best types.
- Report clearly distinguishes formal and candidate signals.
