# Chanlun Daily UI v2 Task 1 View Model Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build the backend `workspace` contract used by the v2 daily report UI.

**Architecture:** `build_workspace(report_data)` receives already-serialized daily report data and returns lightweight view data: view metadata, counts, Top10 highlights, deduped candidates, action labels, resonance labels, risk flags, and `ref` pointers into raw pools. It must not copy large chart arrays.

**Tech Stack:** Python, unittest.

---

## Files

- Create: `chanlun/report_view_model.py`
- Create: `tests/test_report_view_model.py`

Do not edit `chanlun/report_generator.py` in this task.

## Required Workspace Shape

```python
workspace = {
    "default_view": "highlights",
    "view_order": ["highlights", "main", "acceleration", "luojie", "confirming", "baseline"],
    "view_meta": {...},
    "views": {
        "highlights": [...],
        "main": [...],
        "acceleration": [...],
        "luojie": [...],
        "confirming": [...],
        "baseline": [...],
    },
    "counts": {...},
    "diagnostics": {...},
}
```

## Behavior Requirements

- Sources:
  - `main` from `picks_fusion`
  - `baseline` from `picks_pure`
  - `acceleration` from `next_day_boom.candidates` only when `next_day_boom.mode == "enabled"`
  - `luojie` from `luojie_pool.candidates`
  - `confirming` from `startup_watchlist`
- `highlights` can include `main`, `acceleration`, `luojie`, and `confirming`.
- `baseline` must not enter `highlights`.
- Deduplicate by `code` across highlight-eligible pools.
- `sources` should use internal ids; `source_labels` should use Chinese labels.
- Single-source chips remain neutral by data; multi-source items get `resonance_label`.
- Action labels must be one of: `可上车`, `盯盘`, `慎追`, `等回踩`, `仅观察`.
- `可上车` is allowed only when `main` is present.
- Workspace item must contain `ref = {"pool": "...", "code": "..."}`.
- Workspace item must not contain large fields: `dates`, `opens`, `highs`, `lows`, `closes`, `volumes`, `macd_hist`, `chart_annotations`, `buy_points`, `reference_buy_points`, `blocked_buy_points`.
- Include `rank_trace`, `watch_score`, `action_reason`, `primary_reason`, and `risk_flags`.

## Suggested Implementation Steps

1. Write tests for shape, view order, and metadata.
2. Write tests that baseline names do not enter highlights.
3. Write tests for deduping the same code across `picks_fusion` and `next_day_boom`.
4. Write tests for action boundary: acceleration-only cannot become `可上车`.
5. Write tests that chart arrays do not appear in workspace items.
6. Implement source normalization helpers.
7. Implement resonance label helper:
   - `主推 + 加速` -> `共振·进攻`
   - `主推 + 罗姐池` -> `共振·主线`
   - any 3+ sources -> `强共振`
   - combinations involving `等确认` -> `共振·启动`
8. Implement risk/action heuristics conservatively from available fields:
   - high distance or high change -> `慎追`/risk
   - startup/confirming without main -> `等回踩` or `仅观察`
   - luojie-only -> at most `盯盘`
   - acceleration-only -> at most `盯盘`
9. Run:
   - `python3 -m unittest tests.test_report_view_model -v`
   - `python3 -m py_compile chanlun/report_view_model.py`

## Expected Worker Output

- Changed file list.
- Test commands and exact pass/fail output.
- Any intentional heuristic trade-offs.
