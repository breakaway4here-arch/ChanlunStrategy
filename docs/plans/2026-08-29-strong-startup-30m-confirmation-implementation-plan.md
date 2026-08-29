# Strong Startup 30-Minute Confirmation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Stop a lagging `EMA5 > EMA10` state from independently upgrading strong-startup seeds or producing an A-grade confirmation, while preserving explicit fresh 二买/三买 and latest two-yang structure confirmations. Keep the tested recovery bundle as shadow evidence only.

**Architecture:** Add one pure 30-minute evidence builder in `chanlun/sublevel_confirm.py`; make only the strong-startup pipeline consume it in this release. Keep state evidence separate from decision confirmations, evaluate the recovery bundle through a read-only historical replay, retain it as shadow evidence after the replay failed promotion gates, and make UI/report copy derive from structured fields rather than the legacy EMA string.

**Tech Stack:** Python 3, NumPy, SQLite read-only URI, `unittest`, existing Chanlun report generator and vanilla JavaScript frontend tests.

---

**Execution dependency note:** Implement the factual portion of Task 3 before
Task 2 so the replay harness consumes the same evidence calculations as
production. Run Task 2 next to evaluate the recovery bundle, then finish the
`recovery_bundle_match` shadow field in Task 3. This avoids creating a temporary second
indicator implementation in the replay script.

### Task 1: Establish a clean baseline and preserve the source checkout

**Files:**
- Inspect: `AGENTS.md`
- Inspect: `chanlun/strong_startup.py`
- Inspect: `chanlun/sublevel_confirm.py`
- Inspect: `tests/test_strong_startup.py`
- Inspect: `tests/test_sublevel_confirm.py`
- Inspect: `tests/test_startup_labels.py`

**Step 1: Verify branch ancestry and isolation**

Run:

```bash
git rev-parse HEAD
git rev-parse origin/main
git merge-base --is-ancestor origin/main HEAD
git status --short --untracked-files=all
```

Expected: worktree clean, `HEAD == origin/main`, ancestry exit code 0.

**Step 2: Verify the source checkout fingerprint**

Run from `/Users/yangfan/yf_source/ChanlunStrategy`:

```bash
git status --short --untracked-files=all \
  | grep -vE '^(.. )?(\.codegraph|\.idea)/' \
  | shasum -a 256
```

Expected: 24 paths and fingerprint `ddf0b5df6b2e73ce39cc1a2e778dc2ac3befcedd306daf60455b2fcbbdad59ee`.

**Step 3: Run baseline tests**

Run:

```bash
python3 -m unittest \
  tests.test_strong_startup \
  tests.test_sublevel_confirm \
  tests.test_startup_labels
```

Expected: PASS before changes.

### Task 2: Add a reproducible read-only comparison harness

**Files:**
- Create: `scripts/replay_strong_startup_30m_confirmation.py`
- Create: `tests/test_replay_strong_startup_30m_confirmation.py`
- Reuse: `scripts/qa_startup_confirm_grades.py`
- Read-only input: `/Users/yangfan/yf_source/ChanlunStrategy/.cache/chanlun/market_history.sqlite`
- Read-only input: `docs/data/*.json`

**Step 1: Write failing tests for data isolation and metric semantics**

Add tests that require the replay module to:

```python
self.assertTrue(result["database_read_only"])
self.assertIn("missing_forward_returns", result)
self.assertIn("t1", result["outcomes"])
self.assertIn("t3", result["outcomes"])
self.assertIn("t5", result["outcomes"])
self.assertNotIn("unknown", result["outcomes"]["t1"]["wins"])
```

Also assert that displayed rows, unique events and evaluable forward-return samples are separate counts.

**Step 2: Run the new test and confirm RED**

Run:

```bash
python3 -m unittest tests.test_replay_strong_startup_30m_confirmation -v
```

Expected: FAIL because the module does not exist.

**Step 3: Implement the minimal replay module**

Implement pure helpers plus a CLI that:

- Opens SQLite with `file:<path>?mode=ro` and `uri=True`.
- Reads report JSON without rewriting it.
- Reconstructs evidence only for report-listed strong-startup events.
- Separates total report rows, unique `(trade_date, code)` events, events with 30-minute data, and events with T+1/T+3/T+5 outcomes.
- Emits deterministic JSON to stdout or a caller-provided output path outside tracked report artifacts.
- Compares `legacy_ema_only`, `structure_only`, and candidate recovery bundles.

Do not call the daily report generator or any function that writes `MarketHistoryStore`.

**Step 4: Run the test and confirm GREEN**

Run:

```bash
python3 -m unittest tests.test_replay_strong_startup_30m_confirmation -v
```

Expected: PASS.

**Step 5: Run the real read-only replay**

Run:

```bash
python3 scripts/replay_strong_startup_30m_confirmation.py \
  --reports docs/data \
  --market-db /Users/yangfan/yf_source/ChanlunStrategy/.cache/chanlun/market_history.sqlite \
  --as-of 2026-08-28 \
  --output /private/tmp/strong-startup-30m-replay.json
```

Expected: exit 0, production DB SHA and mtime unchanged, JSON contains counts/outcomes for every candidate rule and a 301629 evidence row.

**Step 6: Lock the formal rule and shadow recovery field**

Use the replay result to lock the smallest formal rule that satisfies all design gates:

- Never accepts `ema_bullish_alignment` alone.
- Rejects the 301629 pullback shape.
- Keeps explicit 30-minute buy points and fresh two-yang structures.
- The recovery bundle must include price repair and MACD improvement; missing indicators fail closed, and the result remains shadow-only because its historical outcomes did not pass promotion gates.
- Do not add code/name/date exceptions and do not optimize for a target pool size.

Record the selected rule and the replay counts in the design document before implementation.

### Task 3: Build the shared evidence object with TDD

**Files:**
- Modify: `chanlun/sublevel_confirm.py`
- Modify: `tests/test_sublevel_confirm.py`

**Step 1: Add failing evidence tests**

Add tests for `build_30min_confirmation_evidence(min30_result)` covering:

```python
self.assertTrue(evidence["ema_bullish_alignment"])
self.assertEqual(evidence["macd_hist_direction"], "weakening")
self.assertGreater(evidence["recent_peak_drawdown_pct"], 4.0)
self.assertFalse(evidence["recovery_bundle_match"])
```

Use the fixed 301629-shaped closes and MACD values. Add healthy-recovery, buy-point, fresh-pattern, insufficient-bars and missing-MACD cases.

**Step 2: Run the tests and confirm RED**

Run:

```bash
python3 -m unittest tests.test_sublevel_confirm -v
```

Expected: FAIL for the missing evidence builder.

**Step 3: Implement the pure evidence builder**

Implement:

```python
def build_30min_confirmation_evidence(min30_result):
    return {
        "schema_version": 1,
        "ema_bullish_alignment": ...,
        "close_above_ema5": ...,
        "ema5_rising_bars": ...,
        "recent_peak_drawdown_pct": ...,
        "macd_hist_direction": ...,
        "ema5_reclaim": ...,
        "stop_fall": ...,
        "buy_point": ...,
        "fresh_yang_pattern": ...,
        "recovery_bundle_match": ...,
    }
```

Keep it deterministic, JSON-safe and fail-closed. Reuse the real `ema()` implementation from `chanlun.chan_engine`. Move or share existing private helpers rather than duplicating calculations.

**Step 4: Preserve current generic classifier behavior**

Reuse safe shared helpers where the evidence builder needs them. Do not force the generic classifier onto the strong-startup policy: existing tests and its external `confirmed/level/signals/reason` contract must remain unchanged in this release.

**Step 5: Run tests and confirm GREEN**

Run:

```bash
python3 -m unittest tests.test_sublevel_confirm -v
```

Expected: PASS.

### Task 4: Switch strong-startup promotion to structured evidence

**Files:**
- Modify: `chanlun/strong_startup.py`
- Modify: `tests/test_strong_startup.py`

**Step 1: Replace the permissive test with failing regression cases**

Remove the assertion that a monotonic series upgrades merely because `EMA5 > EMA10`. Add:

- 301629-shaped pullback: candidate count 0, watch count 1.
- Pure EMA alignment without an independent event: watch.
- Latest recommendable 二买/三买: candidate.
- Fresh two-yang structure: candidate.
- Verified recovery bundle selected by Task 2: watch, with `recovery_bundle_match=true` retained for shadow audit only.
- Missing MACD for a recovery-only case: watch.

Assert `confirmation_evidence` is present on both the candidate and watch audit objects.

**Step 2: Run tests and confirm RED**

Run:

```bash
python3 -m unittest tests.test_strong_startup -v
```

Expected: regression tests fail under the legacy EMA rule.

**Step 3: Implement the strong-startup switch**

Change `_check_30min_confirmations()` to consume the shared evidence object. Return only decision-grade confirmation strings; never append a string for `ema_bullish_alignment` alone.

Store the structured evidence separately:

```python
seed["confirmation_evidence"] = evidence
seed["confirmations"] = decision_confirmations
```

When building a watch item, preserve `confirmation_evidence` and use a reason code that distinguishes “均线多头排列但未独立确认” from missing 30-minute data.

**Step 4: Run tests and confirm GREEN**

Run:

```bash
python3 -m unittest tests.test_strong_startup -v
```

Expected: PASS.

### Task 5: Fix confirmation grading and user-facing semantics

**Files:**
- Modify: `chanlun/strong_startup.py`
- Modify: `chanlun/report_generator.py`
- Modify: `scripts/repair_sublevel_selection_snapshot.py`
- Inspect: `chanlun/report_assets/report-v2.js`
- Inspect: `docs/assets/report-v2.js`
- Modify: `tests/test_startup_labels.py`
- Modify: `tests/test_report_generator.py`
- Modify: `tests/test_auxiliary_frontend.py`
- Modify: `tests/test_repair_sublevel_selection_snapshot.py`

**Step 1: Write failing grade and copy tests**

Add assertions that:

```python
self.assertNotEqual(alignment_only["sublevel_confirm_grade"], "A")
self.assertIn("均线仍为多头排列", alignment_only["sublevel_confirm_reason"])
self.assertIn("未形成独立确认", alignment_only["sublevel_confirm_reason"])
```

Add frontend contract tests that reject `30min EMA5维持` as an independent displayed confirmation and render structured evidence without exposing internal keys.

**Step 2: Run the affected tests and confirm RED**

Run:

```bash
python3 -m unittest \
  tests.test_startup_labels \
  tests.test_report_generator \
  tests.test_auxiliary_frontend -v
```

Expected: the new semantic assertions fail.

**Step 3: Implement grade and copy changes**

- Grade from structured confirmation types, not substring matching for `EMA5`.
- Give A only to the latest two-yang structure class; give S to a whitelisted 二买/三买 confirmation. Never grade the recovery shadow field by itself.
- Keep alignment-only items in observation and describe the exact state.
- Serialize `confirmation_evidence` through report generation.
- If the current data-bound renderer already displays the corrected serialized reason, leave assets unchanged; otherwise update source and published asset copies together.

**Step 4: Run affected tests and confirm GREEN**

Run the command from Step 2.

Expected: PASS.

### Task 6: Re-run replay, regression and full suite

**Files:**
- Verify: all changed files
- Evidence output: `/private/tmp/strong-startup-30m-replay-final.json`

**Step 1: Run the final real replay**

Run:

```bash
python3 scripts/replay_strong_startup_30m_confirmation.py \
  --reports docs/data \
  --market-db /Users/yangfan/yf_source/ChanlunStrategy/.cache/chanlun/market_history.sqlite \
  --as-of 2026-08-28 \
  --output /private/tmp/strong-startup-30m-replay-final.json
```

Expected: 301629 is alignment-only/watch, positive fixtures remain, DB SHA/mtime unchanged.

**Step 2: Run directed regression**

Run:

```bash
python3 -m unittest \
  tests.test_sublevel_confirm \
  tests.test_strong_startup \
  tests.test_startup_labels \
  tests.test_scoring_engine \
  tests.test_fusion_admission \
  tests.test_report_generator \
  tests.test_auxiliary_frontend \
  tests.test_replay_strong_startup_30m_confirmation
```

Expected: PASS, exit 0.

**Step 3: Run the complete Python suite**

Run:

```bash
python3 -m unittest discover -s tests
```

Expected: PASS, exit 0; record total test count.

**Step 4: Verify generated assets are synchronized**

Run:

```bash
cmp chanlun/report_assets/report-v2.js docs/assets/report-v2.js
```

Expected: exit 0.

### Task 7: Review, sync, create one final commit and publish

**Files:**
- Stage only the two plan documents and implementation/test files from Tasks 2-5.
- Do not stage `.cache/`, generated reports, screenshots, `.codegraph/` or `.idea/`.

**Step 1: Review the exact diff**

Run:

```bash
git status --short --untracked-files=all
git diff --check
git diff --stat
git diff -- chanlun tests scripts docs/assets
```

Expected: only scoped files, no whitespace errors.

**Step 2: Request code review and address findings**

Use `superpowers:requesting-code-review`. Re-run directed tests after every material correction.

**Step 3: Fetch and integrate the latest target main**

Run:

```bash
git fetch origin main
git rebase origin/main
git merge-base --is-ancestor origin/main HEAD
```

Expected: ancestry exit 0. If main changes strategy semantics, stop and report instead of silently adapting.

**Step 4: Re-run Task 6 after synchronization**

Expected: replay, directed tests, full suite and asset comparison all pass again.

**Step 5: Stage only scoped files**

Because Markdown plans are ignored, force-add exactly these two files:

```bash
git add -f \
  docs/plans/2026-08-29-strong-startup-30m-confirmation-design.md \
  docs/plans/2026-08-29-strong-startup-30m-confirmation-implementation-plan.md
git add \
  chanlun/sublevel_confirm.py \
  chanlun/strong_startup.py \
  chanlun/report_generator.py \
  chanlun/report_assets/report-v2.js \
  docs/assets/report-v2.js \
  scripts/replay_strong_startup_30m_confirmation.py \
  scripts/repair_sublevel_selection_snapshot.py \
  tests/test_replay_strong_startup_30m_confirmation.py \
  tests/test_sublevel_confirm.py \
  tests/test_strong_startup.py \
  tests/test_startup_labels.py \
  tests/test_report_generator.py \
  tests/test_auxiliary_frontend.py \
  tests/test_repair_sublevel_selection_snapshot.py
```

Inspect `git diff --cached --name-status` before committing.

**Step 6: Create one clean commit**

Run:

```bash
git commit -m "fix: 收紧强势启动30分钟确认"
```

Expected: one commit based on latest `origin/main`, title follows `AGENTS.md`.

**Step 7: Push, merge through the repository workflow, and publish affected formal output**

Push the `codex/` branch, create/merge the PR using the repository's existing safe flow, and verify remote `main` contains the commit. If the rule changes the current formal report, run the existing formal daily publishing path rather than editing generated JSON/HTML by hand.

**Step 8: Production acceptance**

Verify:

- Live Pages JSON/HTML/JS/CSS contain the new structured semantics.
- A real screenshot shows no misleading “EMA5维持” confirmation.
- The same stock has only one formal action and the formal pool is not backfilled.
- Source checkout fingerprint remains the original 24-path value.
- Add the new result to the parent P0-P4 launch evidence; do not mark the parent goal complete until all 25 gates have fresh evidence.
