# Chanlun Daily UI v2 Task 2 Generator Shell Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make `report_generator.py` emit v2 daily data, copy shared assets, and generate a small HTML shell instead of a giant inline UI.

**Architecture:** Keep existing serialization helpers and JSON writing behavior, call `build_workspace(daily_data)` before JSON serialization, and generate root/archive HTML with correct relative asset paths. HTML should preserve access control, date resolution, inline fallback, and JSON fetch behavior.

**Tech Stack:** Python, static HTML shell, unittest.

---

## Files

- Modify: `chanlun/report_generator.py`
- Modify: `tests/test_report_generator.py`

Do not edit `chanlun/report_view_model.py`.
Do not edit `chanlun/report_assets/report-v2.css` or `chanlun/report_assets/report-v2.js`.

## Required Changes

- Import `build_workspace` from `chanlun.report_view_model`.
- Add `daily_data["workspace"] = build_workspace(daily_data)` after raw pools are serialized.
- Add an asset copy helper that copies `chanlun/report_assets/report-v2.css` and `chanlun/report_assets/report-v2.js` into `output_dir/assets/`.
- Use content-stable copy behavior: only rewrite output asset when bytes differ.
- Generate root `index.html` using:
  - `assets/report-v2.css`
  - `assets/report-v2.js`
- Generate archive `date/index.html` using:
  - `../assets/report-v2.css`
  - `../assets/report-v2.js`
- Keep ECharts CDN.
- Keep access control variables and helpers needed by the v2 JS:
  - access enabled flag
  - access hash and salt
  - `PAGE_DATE`
  - escaped inline bootstrap report data
- Preserve local `file://` fallback behavior.
- Preserve JSON loading prefix behavior for archive pages.

## HTML Shell Expectations

The shell should include:

```html
<div id="app"></div>
<script>
  window.CHANLUN_BOOTSTRAP = {
    pageDate: "...",
    inlineReportData: ...,
    accessControlEnabled: true,
    accessKeyHash: "...",
    accessKeySalt: "..."
  };
</script>
```

The exact object name can differ if `report-v2.js` uses the same name.

## Tests To Update Or Add

- HTML contains `assets/report-v2.css` for root output.
- Archive HTML contains `../assets/report-v2.css`.
- HTML contains `window.CHANLUN_BOOTSTRAP`.
- HTML still does not contain plaintext `FULL_ACCESS_KEY`.
- Daily JSON contains `workspace`.
- `workspace` contains `default_view: highlights`.
- Asset files are copied into output `assets/`.
- Existing access-control and escape tests must still pass; update static string expectations only if equivalent v2 behavior replaced old function names.

## Suggested Implementation Steps

1. Add failing tests for workspace and asset references.
2. Add failing tests for copied assets.
3. Add helper `copy_if_changed(src, dst)`.
4. Add helper `copy_report_assets(output_dir)`.
5. Split HTML generation into root/archive path-aware helper, or pass `asset_prefix`.
6. Replace giant inline template with shell.
7. Run:
   - `python3 -m unittest tests.test_report_generator -v`
   - `python3 -m py_compile chanlun/report_generator.py`

## Expected Worker Output

- Changed file list.
- Tests run and exact result.
- Any access-control behavior that needed test adaptation.
