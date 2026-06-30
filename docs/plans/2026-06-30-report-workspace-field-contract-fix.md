# Report Workspace Field Contract Fix Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix the report data contract so stock pool rows, workspace rows, and the published page all show today's price change without relying on manual visual checks.

**Architecture:** Treat candidate price fields as a shared data contract. Backend serialization must derive `change_pct`, `current_price`, `reference_price`, and `distance_from_reference_pct` consistently; the v2 workspace must preserve those fields; the frontend must still have a raw-pool fallback for already-published JSON; the scheduled validation script must fail if the contract regresses.

**Tech Stack:** Python `unittest`, plain JavaScript in `chanlun/report_assets/report-v2.js`, shell script `daily_run.sh`, GitHub Pages static artifacts under `docs/`.

---

## Context

The 2026-06-30 report exposed a bug where the visible stock pool showed `--` for today's涨跌幅.

Already observed evidence:

- `docs/data/2026-06-30.json` raw `picks_fusion` / `picks_pure` rows have enough `closes` data to calculate the change, but most rows lack top-level `change_pct`.
- `chanlun/report_generator.py` was patched to add top-level `change_pct` to future serialized picks.
- The first frontend patch added `getCandidateChangePct(item)`, but the visible list renders `workspace.views.*` rows. Those workspace rows do not include `closes`, so the fallback still cannot fix already-published JSON.
- Current published JSON check before this plan:
  - `workspace.highlights`: 10/10 rows cannot resolve change using the current helper.
  - `workspace.main`: 21/24 rows cannot resolve change using the current helper.
  - `workspace.baseline`: 34/34 rows cannot resolve change using the current helper.
  - `workspace.luojie`: 30/30 rows have no change field; only require this view not to break, because LuoJie source rows may not include previous close.
- `scripts/validate_today_report.py` only validates market index values and will not catch UI contract regressions.
- `daily_run.sh` currently stages `docs/20*/`, which can accidentally include unrelated archive deletions.

Do not touch unrelated working tree state:

- `docs/2026-06-20/index.html` is already deleted in the working tree; do not restore, stage, or commit it.
- `.codegraph/`, `.playwright-mcp/`, and `docs-preview/` are untracked tool artifacts; leave them alone.

## Scope

Allowed files:

- `chanlun/report_view_model.py`
- `chanlun/report_assets/report-v2.js`
- `chanlun/report_generator.py`
- `scripts/validate_today_report.py`
- `daily_run.sh`
- `tests/test_report_view_model.py`
- `tests/test_report_generator.py`
- `tests/test_market_data_guard.py`
- `tests/test_requests_sessions.py`
- `docs/assets/report-v2.js`
- `docs/index.html`
- `docs/2026-06-30/index.html`

Only update `docs/data/2026-06-30.json` if a narrowly scoped JSON contract repair is unavoidable. Prefer fixing the current visible page through the frontend raw-pool fallback plus asset version bump.

## Task 1: Make Workspace Metrics Derive From Raw Candidate K-Line Data

**Files:**

- Modify: `chanlun/report_view_model.py`
- Test: `tests/test_report_view_model.py`

**Step 1: Write failing workspace tests**

Add tests that model the real failure: a main/baseline pick has `best_buy_point.current_price` and `closes`, but no top-level `change_pct` and no `best_buy_point.change_pct`.

Suggested test shape:

```python
def test_workspace_main_derives_change_pct_from_closes_when_pick_lacks_change_field(self):
    pick = _fusion_pick()
    pick.pop("change_pct", None)
    pick["best_buy_point"].pop("change_pct", None)
    pick["closes"] = [10.0, 10.5, 10.29]
    pick["best_buy_point"]["current_price"] = 10.29

    workspace = build_workspace(_report_data({"picks_fusion": [pick]}))

    main_item = workspace["views"]["main"][0]
    highlight_item = workspace["views"]["highlights"][0]
    self.assertEqual(main_item["change_pct"], -2.0)
    self.assertEqual(highlight_item["change_pct"], -2.0)
    self.assertEqual(main_item["current_price"], 10.29)
```

Add a baseline variant because baseline currently goes through the default metric branch:

```python
def test_workspace_baseline_uses_pick_metric_derivation(self):
    pick = _baseline_pick()
    pick.pop("change_pct", None)
    pick["best_buy_point"].pop("change_pct", None)
    pick["closes"] = [20.0, 21.0, 21.42]
    pick["best_buy_point"]["current_price"] = 21.42

    workspace = build_workspace(_report_data({"picks_pure": [pick]}))

    item = workspace["views"]["baseline"][0]
    self.assertEqual(item["change_pct"], 2.0)
    self.assertEqual(item["current_price"], 21.42)
```

**Step 2: Run tests and confirm they fail**

Run:

```bash
python3 -m unittest tests.test_report_view_model.TestReportViewModel.test_workspace_main_derives_change_pct_from_closes_when_pick_lacks_change_field tests.test_report_view_model.TestReportViewModel.test_workspace_baseline_uses_pick_metric_derivation
```

Expected before implementation: FAIL because `change_pct` is `None`.

**Step 3: Implement shared metric helpers**

In `chanlun/report_view_model.py`, add small local helpers. Do not import from `chanlun.report_generator`, because `report_generator.py` already imports `build_workspace`.

Required behavior:

- `change_pct` priority:
  1. `item.change_pct`
  2. `item.best_buy_point.change_pct`
  3. `(closes[-1] - closes[-2]) / closes[-2] * 100`, rounded to 2 decimals
- `current_price` priority:
  1. `item.current_price`
  2. `item.best_buy_point.current_price`
  3. `item.close`
  4. `closes[-1]`
- `reference_price` priority:
  1. `item.reference_price`
  2. `item.best_buy_point.reference_price`
  3. `item.best_buy_point.source_price`
  4. `item.best_buy_point.price`
  5. source-specific fields such as LuoJie `life_line` / `reduce_line`
- `distance_from_reference_pct` priority:
  1. existing distance fields
  2. derived from current and reference price when both are valid and reference is non-zero

Use these helpers in:

- `_extract_main_metrics`
- `_extract_luojie_metrics` where applicable
- `_extract_confirming_metrics` where applicable
- default branch in `_primary_metric_bundle`
- `_extract_risk_flags`, so overheat risk is not missed when `change_pct` only exists in `closes`
- `_extract_score` for confirming rows if using change as weak sort proxy

**Step 4: Run focused tests**

Run:

```bash
python3 -m unittest tests.test_report_view_model
```

Expected: all tests pass.

## Task 2: Make Frontend Current-Page Fallback Use Raw Pools

**Files:**

- Modify: `chanlun/report_assets/report-v2.js`
- Modify after source change: `docs/assets/report-v2.js`
- Modify after source change: `docs/index.html`
- Modify after source change: `docs/2026-06-30/index.html`
- Test: `tests/test_report_generator.py`

**Step 1: Write failing asset test**

Extend `TestReportV2AuxiliaryHeader` in `tests/test_report_generator.py`.

Assert that `getCandidateChangePct` can look up raw candidate data via `findRawCandidate(item.ref || {})`.

Suggested assertions:

```python
def test_candidate_rows_use_raw_candidate_fallback_for_workspace_change_pct(self):
    self.assertIn("findRawCandidate(rec.ref || {})", self.asset_js)
    self.assertIn("return getCandidateChangePct(raw);", self.asset_js)
```

Adjust exact strings to match the implementation, but the test must enforce the behavior, not just the function name.

**Step 2: Run the test and confirm it fails**

Run:

```bash
python3 -m unittest tests.test_report_generator.TestReportV2AuxiliaryHeader.test_candidate_rows_use_raw_candidate_fallback_for_workspace_change_pct
```

Expected before implementation: FAIL.

**Step 3: Implement frontend fallback**

Update `getCandidateChangePct(item)`:

- Keep direct `item.change_pct`.
- Keep `item.best_buy_point.change_pct`.
- Keep direct `item.closes` calculation.
- If still null and `item.ref` exists, call `findRawCandidate(item.ref || {})` and calculate from that raw object.
- Avoid infinite recursion: either pass a second boolean parameter like `allowRawFallback`, or factor out a pure `getCandidateChangePctFromRecord(record)`.

Expected implementation pattern:

```javascript
function getCandidateChangePctFromRecord(rec) {
  // direct / bp / closes only
}

function getCandidateChangePct(item) {
  var rec = item || {};
  var direct = getCandidateChangePctFromRecord(rec);
  if (direct !== null) return direct;
  var raw = findRawCandidate(rec.ref || {});
  if (raw && raw !== rec) return getCandidateChangePctFromRecord(raw);
  return null;
}
```

**Step 4: Sync docs asset and bump asset hash**

After `chanlun/report_assets/report-v2.js` changes:

```bash
cp chanlun/report_assets/report-v2.js docs/assets/report-v2.js
python3 -c "from chanlun.report_generator import _report_asset_version; print(_report_asset_version())"
```

Use the printed hash to update only asset query strings in:

- `docs/index.html`
- `docs/2026-06-30/index.html`

Do not regenerate `docs/data/2026-06-30.json` by feeding serialized JSON back into `generate_report()`. That previously caused chart arrays to be sliced again.

**Step 5: Run JS and report tests**

Run:

```bash
node --check chanlun/report_assets/report-v2.js
python3 -m unittest tests.test_report_generator.TestReportV2AuxiliaryHeader tests.test_report_generator.TestReportGenerator
```

Expected: pass.

## Task 3: Add Published Report Contract Validation

**Files:**

- Modify: `scripts/validate_today_report.py`
- Test: `tests/test_market_data_guard.py`

**Step 1: Write failing pure validation tests**

Add pure tests for a new helper, for example `validate_report_contract(report)`.

Required tests:

1. A report whose `workspace.views.main` row has null `change_pct` but whose raw `picks_fusion` ref has usable `closes` should pass.
2. A report whose workspace row and raw ref both cannot resolve change should return an error.
3. A report with non-empty `picks_fusion` but empty/missing `workspace.views.main` should return an error.

Suggested test call:

```python
from scripts.validate_today_report import validate_report_contract

errors = validate_report_contract(report)
self.assertEqual(errors, [])
```

**Step 2: Run the tests and confirm they fail**

Run:

```bash
python3 -m unittest tests.test_market_data_guard.TestReportContractGuard
```

Expected before implementation: FAIL because the helper/class does not exist.

**Step 3: Implement contract validation**

In `scripts/validate_today_report.py`, add pure helpers:

- `_safe_float`
- `_resolve_raw_candidate(report, ref)`
- `_resolve_change_pct(row, raw=None)`
- `validate_report_contract(report)`

Contract rules:

- For `workspace.views.highlights`, `workspace.views.main`, and `workspace.views.baseline`, every row with a stock code must resolve a displayable `change_pct` from either the workspace row or raw ref.
- For `workspace.views.main`, if `picks_fusion` is non-empty, `main` should be non-empty.
- For `workspace.views.baseline`, if `picks_pure` is non-empty, `baseline` should be non-empty.
- For rows with `current_price` missing, allow raw fallback if raw has `current_price`, `close`, or latest `closes`.
- Do not require LuoJie rows to have `change_pct` unless raw data actually has enough price history. LuoJie rows may only have `close`.

Integrate with `main()`:

- Keep market index validation.
- Run `contract_errors = validate_report_contract(report)`.
- If errors exist, print `report contract mismatch:` and return `1`.

**Step 4: Run validation tests**

Run:

```bash
python3 -m unittest tests.test_market_data_guard
```

Expected: pass.

## Task 4: Narrow Daily Run Staging Scope

**Files:**

- Modify: `daily_run.sh`
- Test: `tests/test_market_data_guard.py` or `tests/test_requests_sessions.py`

**Step 1: Write failing script guard test**

Add assertions to `TestDailyRunScriptGuard`:

```python
self.assertNotIn("docs/20*/", script)
self.assertIn('"docs/${TODAY}/index.html"', script)
self.assertIn('"docs/data/${TODAY}.json"', script)
```

**Step 2: Run the test and confirm it fails**

Run:

```bash
python3 -m unittest tests.test_market_data_guard.TestDailyRunScriptGuard
```

Expected before implementation: FAIL because `docs/20*/` is present.

**Step 3: Update staging command**

Replace broad staging:

```bash
git add docs/index.html docs/data.json docs/data/ docs/20*/
```

with explicit current-day paths:

```bash
git add \
  docs/index.html \
  docs/data.json \
  docs/data/index.json \
  "docs/data/${TODAY}.json" \
  "docs/${TODAY}/index.html" \
  docs/assets/report-v2.css \
  docs/assets/report-v2.js
```

Keep quoting for paths with `${TODAY}`.

**Step 4: Run shell syntax and script tests**

Run:

```bash
zsh -n daily_run.sh
python3 -m unittest tests.test_market_data_guard.TestDailyRunScriptGuard tests.test_requests_sessions
```

Expected: pass.

## Task 5: Verify Current 2026-06-30 Page Is Actually Fixed

**Files:**

- No new source files unless needed.

**Step 1: Run targeted test matrix**

Run:

```bash
node --check chanlun/report_assets/report-v2.js
python3 -m unittest tests.test_report_view_model tests.test_report_generator tests.test_market_data_guard tests.test_requests_sessions
python3 -m py_compile scripts/validate_today_report.py chanlun/report_view_model.py chanlun/report_generator.py
git diff --check
```

Expected: all pass.

**Step 2: Run current JSON symptom check**

Use a short local script to emulate display resolution for the current published JSON:

```bash
python3 - <<'PY'
import json
from pathlib import Path

report = json.loads(Path("docs/data/2026-06-30.json").read_text())

def safe(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None

def raw_by_pool(pool):
    if pool == "picks_fusion":
        rows = report.get("picks_fusion") or []
    elif pool == "picks_pure":
        rows = report.get("picks_pure") or []
    elif pool == "startup_watchlist":
        rows = report.get("startup_watchlist") or []
    else:
        rows = []
    return {str(r.get("code")): r for r in rows}

raw_maps = {pool: raw_by_pool(pool) for pool in ("picks_fusion", "picks_pure", "startup_watchlist")}

def calc(row):
    direct = safe(row.get("change_pct"))
    if direct is not None:
        return direct
    bp = row.get("best_buy_point") or {}
    bp_change = safe(bp.get("change_pct"))
    if bp_change is not None:
        return bp_change
    closes = row.get("closes") or []
    if len(closes) >= 2:
        prev = safe(closes[-2])
        latest = safe(closes[-1])
        if prev not in (None, 0) and latest is not None:
            return (latest - prev) / prev * 100
    ref = row.get("ref") or {}
    raw = raw_maps.get(ref.get("pool"), {}).get(str(ref.get("code")))
    if raw:
        return calc(raw)
    return None

for view in ("highlights", "main", "baseline", "confirming"):
    rows = report.get("workspace", {}).get("views", {}).get(view, [])
    missing = [r.get("code") for r in rows if calc(r) is None]
    print(view, len(rows), "missing_display_change", len(missing), missing[:5])
    if missing and view in {"highlights", "main", "baseline"}:
        raise SystemExit(1)
PY
```

Expected: `missing_display_change 0` for `highlights`, `main`, and `baseline`.

**Step 3: Confirm docs data was not accidentally reserialized**

Run:

```bash
git diff -- docs/data/2026-06-30.json
```

Expected: empty diff unless Task 2 explicitly chose a narrow JSON contract repair. If there is a diff, explain why and verify chart array lengths did not shrink.

**Step 4: Review staged files**

Run:

```bash
git status --short
git diff --name-status
git diff --cached --name-status
```

Expected:

- Do not stage `docs/2026-06-20/index.html`.
- Do not stage `.codegraph/`, `.playwright-mcp/`, or `docs-preview/`.
- Expected changed files are limited to the allowed scope above.

## Task 6: Commit and Push Only After Review Approval

This task is for the controller/reviewer, not the implementation subagent, unless explicitly delegated later.

Expected commit title:

```bash
git commit -m "fix: 修复日报工作区行情字段契约"
```

Push with the existing fallback-aware environment. If pushing manually, use:

```bash
git -c http.https://github.com.proxy=127.0.0.1:7897 \
    -c https.https://github.com.proxy=127.0.0.1:7897 \
    push
```

After push, verify:

```bash
git log --oneline -3
curl -ksS -x http://127.0.0.1:7897 https://raw.githubusercontent.com/breakaway4here-arch/ChanlunStrategy/main/docs/assets/report-v2.js -o /private/tmp/chanlun_remote_report_v2.js
rg -n "findRawCandidate| getCandidateChangePct|function getCandidateChangePct" /private/tmp/chanlun_remote_report_v2.js
curl -ksS -x http://127.0.0.1:7897 "https://breakaway4here-arch.github.io/ChanlunStrategy/?t=20260630-workspace-contract" -o /private/tmp/chanlun_pages_index.html
rg -n "report-v2\\.(css|js)\\?v=" /private/tmp/chanlun_pages_index.html
```

## Implementation Handoff Rules

- Use TDD: failing test first, then minimal code.
- Keep changes small and scoped.
- Do not regenerate the whole report from `docs/data/2026-06-30.json`.
- Do not use `git reset --hard` or restore unrelated files.
- Do not stage/commit unrelated working tree state.
- Report changed file paths and exact verification output.
