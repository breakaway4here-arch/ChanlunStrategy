# Chanlun Daily UI v2 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Upgrade the daily report from a long stacked page to a compact white-background trading workspace with backend-generated `workspace` data and external v2 assets.

**Architecture:** Add a Python view-model layer that merges existing pools into a lightweight `workspace`, keep raw pools unchanged for chart/detail lookup, and replace the inline HTML/CSS/JS report with a small HTML shell that loads shared `report-v2.css` and `report-v2.js`. The frontend renders only the precomputed workspace and uses `ref` to find original chart objects.

**Tech Stack:** Python report generation, static HTML, vanilla JavaScript, ECharts 5.4.3, CSS in `chanlun/report_assets/`, unittest.

---

## Source Spec

- `/Users/yangfan/Downloads/chanlun_daily_ui_v2_spec.md`

## Non-Negotiable Boundaries

- Do not change selection algorithms, data collection, or Chanlun engine logic.
- Do not name Top10 as buy/recommendation Top10; use `看点 Top10`.
- Do not let frontend JS sort, merge, dedupe, rank, generate action, generate resonance, or generate Top10.
- Do not duplicate chart arrays in `workspace`; use `ref` to raw data.
- Do not keep an old/new toggle in the page.
- Keep root and archive pages loading JSON/assets correctly.
- Preserve access-control behavior and HTML escaping protections covered by `tests/test_report_generator.py`.

## Parallel Work Split

### Task 1: Workspace View Model

**Plan:** `docs/plans/2026-06-29-chanlun-daily-ui-v2-task1-view-model.md`

**Owner:** Worker 1

**Write Scope:**
- Create: `chanlun/report_view_model.py`
- Create: `tests/test_report_view_model.py`

**Forbidden Scope:**
- Do not edit `chanlun/report_generator.py`.
- Do not edit frontend assets.

### Task 2: Generator Shell And Asset Pipeline

**Plan:** `docs/plans/2026-06-29-chanlun-daily-ui-v2-task2-generator-shell.md`

**Owner:** Worker 2

**Write Scope:**
- Modify: `chanlun/report_generator.py`
- Modify as needed: `tests/test_report_generator.py`

**Forbidden Scope:**
- Do not edit `chanlun/report_view_model.py`.
- Do not edit `chanlun/report_assets/report-v2.css`.
- Do not edit `chanlun/report_assets/report-v2.js`.

### Task 3: Frontend Assets, Mobile UX, Auxiliary Center

**Plan:** `docs/plans/2026-06-29-chanlun-daily-ui-v2-task3-frontend-assets.md`

**Owner:** Worker 3

**Write Scope:**
- Create: `chanlun/report_assets/report-v2.css`
- Create: `chanlun/report_assets/report-v2.js`
- Modify only if a test needs static string checks: `tests/test_report_generator.py`

**Forbidden Scope:**
- Do not edit `chanlun/report_view_model.py`.
- Do not edit `chanlun/report_generator.py` except for a small test fixture expectation if absolutely necessary; prefer not touching it.

## Integration Owner Checklist

1. Review worker diffs for write-scope violations.
2. Resolve integration issues in `chanlun/report_generator.py` only after all workers report back.
3. Regenerate `docs/index.html`, `docs/2026-06-29/index.html`, `docs/data/2026-06-29.json`, `docs/data/index.json`, and shared `docs/assets/`.
4. Verify `docs/index.html` uses `assets/report-v2.css` and archive pages use `../assets/report-v2.css`.
5. Run targeted tests:
   - `python3 -m unittest tests.test_report_view_model tests.test_report_generator -v`
   - `python3 -m py_compile chanlun/report_view_model.py chanlun/report_generator.py`
   - `git diff --check`
6. Run broader report-safe regression:
   - `python3 -m unittest tests.test_report_generator tests.test_requests_sessions tests.test_market_data_guard -v`
7. If practical, serve `docs/` locally and inspect desktop/mobile screenshots.
8. Commit with title format: `feat: 升级日报 UI v2 #<redmine_issue_id>` if a Redmine ID is provided; otherwise omit the issue suffix.
9. Push branch `taste-ui-design-system`.
