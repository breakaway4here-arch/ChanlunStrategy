# Minute K-line Retry and Historical Repair Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make minute-level selection inputs retry safely and fail closed, then reconstruct the affected 2026-08-26 candidate from verified historical bars without contaminating the publication ledger or scorecard.

**Architecture:** `KLineRepository` passes report context to production fetchers while remaining compatible with existing two-argument test fetchers. The minute fetcher performs one provider request per attempt, validates the payload before returning it to the repository, and alternates providers for a maximum of four requests. Candidate upgrade channels propagate acquisition evidence. A dedicated historical repair command stages and verifies bars, recomputes only the affected sublevel decision from the frozen report, and atomically rebuilds public report planes with a reconstruction receipt.

**Tech Stack:** Python 3, `unittest`, SQLite market-history store, existing report workspace projection, static HTML/JSON publication, GitHub Pages.

---

### Task 1: Add contextual minute retry tests

**Files:**
- Modify: `tests/test_kline_repository.py`
- Modify: `tests/test_strong_startup.py`
- Modify: `tests/test_trend_continuation.py`

**Steps:**

1. Add a failing test that records provider calls and asserts `eastmoney, sina, eastmoney, sina` after four invalid responses.
2. Assert that stale Eastmoney data triggers Sina and that fresh Sina data stops further calls.
3. Assert that four failures return no remote payload and never replace an existing stale database tail.
4. Assert that a first-attempt success makes exactly one HTTP call.
5. Assert that `required_date` and `as_of` reach a contextual production fetcher while old two-argument fetchers still work.
6. Add failing tests requiring strong-startup and trend-continuation candidates to preserve verified `strategy_input_evidence`.
7. Run the three test modules and confirm RED for missing retry/evidence behavior.

### Task 2: Implement retry and pre-write freshness validation

**Files:**
- Modify: `chanlun/data_fetcher.py`
- Modify: `chanlun/kline_repository.py`

**Steps:**

1. Add a pure minute-payload validator covering equal arrays, finite OHLCV, legal price ranges, minimum bars, exact report date and final bar time.
2. Replace concurrent first-nonempty minute fetching with a bounded sequential attempt loop: initial + three retries, provider alternation, 0.5/1/2 second backoff.
3. Add fetch diagnostics for attempts, provider order and final failure reason without storing response bodies.
4. Extend repository fetch invocation to pass `required_date` and `as_of` only when the fetcher signature accepts them; do not catch an internal `TypeError` as a compatibility signal.
5. Ensure rejected payloads are not prepared or written.
6. Run Task 1 tests and confirm GREEN.

### Task 3: Propagate verified strategy input evidence

**Files:**
- Modify: `chanlun/strong_startup.py`
- Modify: `chanlun/trend_continuation.py`
- Test: `tests/test_strong_startup.py`
- Test: `tests/test_trend_continuation.py`

**Steps:**

1. Copy `strategy_input_evidence` from the analyzed 30-minute result only when it is a mapping.
2. Preserve it through trend candidate normalization and strong-startup report serialization.
3. Do not synthesize evidence when the result lacks it.
4. Run the candidate upgrade and market-data guard tests.

### Task 4: Add a safe 2026-08-26 historical reconstruction

**Files:**
- Create: `scripts/repair_sublevel_selection_snapshot.py`
- Modify: `chanlun/report_view_model.py`
- Create: `tests/test_repair_sublevel_selection_snapshot.py`
- Modify: `tests/test_report_view_model.py`

**Steps:**

1. Add failing tests for the repair command: wrong date rejected, source report must be official/closed, exact-date final bars required, future bars truncated by `as_of`, no confirmation produces no reconstructed candidate, and recommendation ledger remains byte-identical.
2. Recreate the daily strong-startup seed for `300697` only from the frozen 2026-08-26 report row.
3. Load verified 30-minute bars from canonical SQLite at `as_of=2026-08-26 15:00:00`, rerun Chan analysis and the original strong-startup confirmation.
4. When it passes, update only its sublevel evidence and confirmation fields; set `publication_status=historical_reconstruction` and `scorecard_eligible=false`.
5. Rebuild `selection_input_health` so `daily_fusion` is verified while unrelated H4/15-minute incidents remain unavailable.
6. Rebuild workspace views and render the row as `历史重建候选`, with `is_formal_recommendation=false`.
7. Add an atomic reconstruction receipt with before/after hashes and verified source metadata.
8. Write all report planes to a staging directory, validate them, then atomically publish.

### Task 5: Collect and merge real historical minute bars

**Files:**
- Reuse: `scripts/backfill_market_history.py`
- Reuse: `.cache/chanlun/market_history.sqlite`

**Steps:**

1. Fetch `300697` 30-minute history into an isolated staging database using the new bounded retry semantics.
2. Verify the staging database contains a final `2026-08-26 15:00:00` row and enough bars as of that timestamp.
3. Record provider and ingest manifest evidence.
4. Atomically merge the completed staging shard into canonical SQLite.
5. Run the repair command against a staged copy of `docs` and verify the reconstruction receipt and scorecard exclusion.

### Task 6: Regression and review

**Files:**
- All modified files above

**Steps:**

1. Run targeted unit tests for repository, data fetcher, candidate upgrades, market guards, report model and repair publisher.
2. Run `python3 -m py_compile` on every modified Python file.
3. Run the complete Python test suite.
4. Request an independent code review focused on retry cardinality, stale-data leakage and historical look-ahead.
5. Resolve findings and rerun affected tests.

### Task 7: Commit, deploy and verify production

**Files:**
- Code, tests, plans and rebuilt 2026-08-26 report assets/data

**Steps:**

1. Fetch `origin/main`, prove it is an ancestor, and rebase/merge safely if needed.
2. Commit implementation with the repository title convention.
3. Push the branch to `origin/main` as explicitly requested by the user.
4. Safely fast-forward the LaunchAgent working copy while preserving all pre-existing uncommitted files.
5. Run report validators and rebuild comparison/scorecard projections in the required finalizer order.
6. Push the repaired report commit.
7. Read back remote `main` SHA, Pages assets, `docs/data/2026-08-26.json`, archive HTML and comparison index.
8. Confirm the online main tab shows the reconstructed candidate and its historical marker, while the scorecard sample count does not increase.
