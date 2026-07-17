# Recommendation Risk Guard Repair Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Stop weak-market reports from mechanically promoting concentrated momentum candidates, repair position semantics, and make the growth-quality view an explicitly diversified observation list.

**Architecture:** Compute market sentiment before stock decisions and pass a normalized market-risk context into the pure decision engine. Separate signal-price distance from absolute low-position evidence, then make report ranking require real sector evidence and enforce concentration limits. Keep the shared `market_history.sqlite` as the only history store and validate with dated report replays.

**Tech Stack:** Python 3 standard library, SQLite market-history store, `unittest`, existing report generator/view model.

---

### Task 1: Market-risk gate before stock decisions

**Files:**
- Modify: `run.py`
- Modify: `chanlun/decision_engine.py`
- Test: `tests/test_decision_engine.py`
- Test: `tests/test_market_data_guard.py`

1. Add failing tests proving `weak` normalizes to a retreat/weak phase, sentiment below 40 or `turning_weaker` caps the result at `observe`, and strong/neutral regimes retain the current score path.
2. Run the focused tests and verify the expected failures.
3. Build market sentiment before decision injection and pass `market_sentiment` plus normalized phase in `market_context`.
4. Make the pure engine apply the risk cap after score calculation and emit an explicit market-risk reason.
5. Run focused tests and the complete decision/sentiment suites.

### Task 2: Separate signal distance from absolute position

**Files:**
- Modify: `run.py`
- Modify: `chanlun/decision_engine.py`
- Test: `tests/test_decision_engine.py`
- Test: `tests/test_market_data_guard.py`

1. Add failing tests proving same-day startup price equal to current price is not sufficient evidence for `低位启动区 +35`.
2. Preserve signal-distance evidence for display, but require an independent absolute-position field derived from the daily window, such as the 120-day close percentile.
3. Score verified low/mid/high percentiles continuously or by conservative bands; missing absolute evidence remains `observe`.
4. Run focused tests and verify old serialization defaults cannot become trusted position evidence.

### Task 3: Repair growth-quality semantics and concentration

**Files:**
- Modify: `chanlun/report_view_model.py`
- Modify: `chanlun/report_assets/report-v2.js`
- Test: `tests/test_report_view_model.py`
- Test: `tests/test_report_assets.py`

1. Add failing tests proving the view is observation-only, requires real sector attribution, does not treat stock change as sector quality, and caps one sector at two names.
2. Replace the broad 3%-45% momentum plateau with a continuous score that penalizes crowded high recent returns.
3. Rename the visible view to `高弹性观察 Top10` and state that it is not a formal recommendation.
4. Keep `workspace.views.main` as the only formal recommendation view.
5. Run focused view-model and frontend contract tests.

### Task 4: Replay and regression acceptance

**Files:**
- Modify or create only test fixtures/scripts needed for replay; do not create another market database.

1. Run the complete unit suite for decision, sentiment, report view-model, generator, and market-data guards.
2. Replay 2026-07-10, 2026-07-13, and 2026-07-16 from the shared database where evidence exists.
3. Verify 2026-07-16 no longer produces 22 mechanically identical recommendations and that weak-market recommendations are capped.
4. Compare recommendation counts, sector concentration, and next-day returns without tuning thresholds to 2026-07-17 alone.
5. Generate and validate the current report before any publish step.
