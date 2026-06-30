# Chanlun Data Contract Quality V1 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the daily report data contract explicit and trustworthy: no silent stale K-line use in official reports, no sector loss in startup picks, manifest separates trading dates, and workspace rows expose structured tags/badges.

**Architecture:** Keep Chanlun algorithm logic unchanged. Add data freshness and quality metadata at the data-fetch/report-contract layer, thread that metadata through `run.py`, then expose stable fields for the frontend/workspace and validation script.

**Tech Stack:** Python 3 stdlib + `unittest`, existing `chanlun` modules, generated static report JSON/HTML assets.

---

## Critical Context

- Current branch is `main`; base HEAD when this plan was written was `3a5247f`.
- Existing unrelated working tree state must be preserved and must not be staged or reverted:
  - `D docs/2026-06-20/index.html`
  - `?? .codegraph/`
  - `?? .playwright-mcp/`
  - `?? docs-preview/`
- User explicitly asked to distribute to subagents / 小兵 and review thoroughly.
- Default subagent model from memory: `gpt-5.3-codex-spark`.
- Relevant spec: `/Users/yangfan/Downloads/chanlun_data_optimization_spec.md`.
- Relevant historical lesson: do not silently accept stale/fallback market data for official reports; retry/mark/fail closed instead.

## Non-Goals

- Do not change Chanlun algorithm thresholds, buy-point logic, Luojie logic, or strong-startup strategy rules.
- Do not perform frontend visual redesign.
- Do not add a real trading-calendar service.
- Do not regenerate historical data broadly unless a test fixture requires a temp directory.

## Task 1: Data Fetcher Quality Contract

**Owner:** Worker 1

**Files:**
- Modify: `chanlun/data_fetcher.py`
- Test: `tests/test_market_data_guard.py`

**Requirements:**

1. Add `_kline_latest_date(kline)`:
   ```python
   def _kline_latest_date(kline):
       dates = (kline or {}).get("dates", [])
       return str(dates[-1]).split(" ")[0] if dates else ""
   ```

2. Add `build_kline_status(kline, required_date=None, source="unknown")`:
   - Missing kline returns:
     ```python
     {
       "daily": "missing",
       "latest_date": "",
       "source": source,
       "bars": 0,
       "stale": True,
     }
     ```
   - Existing kline returns `daily="verified"` when `required_date` is empty or latest date equals `required_date`.
   - Existing kline returns `daily="stale_cache"` when latest date does not equal `required_date`.
   - Include `bars = len(kline.get("closes", []))`.
   - Prefer `kline.get("source", source)` when available.

3. Change `batch_fetch_daily_klines(stocks, max_workers=10)` signature to:
   ```python
   def batch_fetch_daily_klines(stocks, max_workers=10, required_date=None, allow_stale=False):
   ```

4. In each returned stock row, preserve source metadata:
   ```python
   "sector": stock.get("sector", ""),
   "sector_tags": stock.get("sector_tags", []),
   "sector_rank": stock.get("sector_rank"),
   "sector_flow": stock.get("sector_flow"),
   "sector_strength_label": stock.get("sector_strength_label", ""),
   "change_pct": stock.get("change_pct", 0),
   "klines": klines,
   "data_status": status,
   ```

5. Official mode behavior:
   - If `status["daily"] != "verified"` and `allow_stale` is false, return `None` for that stock.
   - Print a clear `[STALE]` line containing code, name, latest date, and required date.
   - Missing/short K lines should also be represented in quality counters later, but this task only filters return rows.

6. In `collect_daily_data(required_date=None, allow_missing_index=False)`:
   - Replace `seen_codes/all_stocks` with `stock_map`.
   - First sector hit defines primary `sector`, `sector_rank`, `sector_flow`, `sector_strength_label`.
   - Later sector hits append to `sector_tags` without changing primary sector.
   - Keep fallback cache path, but mark fallback stock rows with source metadata enough for later `data_quality`.
   - Call:
     ```python
     stocks_with_kline = batch_fetch_daily_klines(
         all_stocks,
         required_date=required_date,
         allow_stale=allow_missing_index,
     )
     ```
   - Return top-level `data_quality`:
     ```python
     {
       "report_date": required_date or "",
       "is_trading_day": bool(sh_kline),
       "is_official": bool(sh_kline and stocks_with_kline and not allow_missing_index),
       "market_status": "verified" if sh_kline else "unverified",
       "stock_pool_source": "sector_components" or "kline_cache",
       "sector_source": "eastmoney" or "fallback_static" or "empty",
       "stale_stock_count": <number of returned stale rows plus filtered stale rows>,
       "missing_daily_count": <number of missing/filtered daily rows>,
       "missing_30min_count": 0,
       "fallback_used": <bool>,
       "warnings": [...],
     }
     ```
   - Keep `index_error` unchanged.

**Tests to Add:**

1. `test_build_kline_status_marks_verified_and_stale`
   - Use two simple kline dicts.
   - Assert verified for `2026-06-30`, stale for required `2026-06-30` when latest is `2026-06-29`.

2. `test_batch_fetch_daily_klines_filters_stale_in_official_mode`
   - Patch `fetch_daily_kline` to return stale kline.
   - Assert returned list is empty when `allow_stale=False`.

3. `test_batch_fetch_daily_klines_keeps_stale_with_status_in_preview_mode`
   - Same stale kline.
   - Assert row exists and `row["data_status"]["daily"] == "stale_cache"`.

4. `test_collect_daily_data_preserves_sector_tags_and_quality`
   - Patch `fetch_sector_flow`, `fetch_sector_stocks`, `batch_fetch_daily_klines`, `fetch_shanghai_index`.
   - Two sectors contain same stock.
   - Assert returned stock has `sector_tags` with both sectors.
   - Assert `data_quality` exists and `stock_pool_source == "sector_components"`.

**Verification:**

Run:
```bash
python3 -m unittest tests.test_market_data_guard -v
```

Expected: all tests in that file pass.

## Task 2: Report Generator Manifest And Recent Review Contract

**Owner:** Worker 2

**Files:**
- Modify: `chanlun/report_generator.py`
- Test: `tests/test_report_generator.py`

**Requirements:**

1. In `_generate_report_v2()`, include top-level data quality:
   ```python
   "data_quality": report_data.get("data_quality", {}),
   ```
   and keep `diagnostics` unchanged.

2. Before writing manifest, derive:
   ```python
   dq = daily_data.get("data_quality", {})
   write_data_manifest(
       date_str,
       data_dir,
       is_trading_day=dq.get("is_trading_day", True),
       is_official=dq.get("is_official", True),
   )
   ```

3. Change `write_data_manifest(date_str, data_dir)` signature:
   ```python
   def write_data_manifest(date_str, data_dir, is_trading_day=True, is_official=True):
   ```

4. Manifest schema:
   ```json
   {
     "dates": [],
     "trading_dates": [],
     "latest": "YYYY-MM-DD",
     "latest_trading_date": "YYYY-MM-DD",
     "date_meta": {
       "YYYY-MM-DD": {"is_trading_day": true, "is_official": true}
     }
   }
   ```
   Compatibility:
   - Preserve old `dates`.
   - If reading old manifest, set `trading_dates` from old `dates` only when missing.
   - Never add non-trading dates to `trading_dates`.
   - Always set `latest = date_str`.
   - Only update `latest_trading_date` when `is_trading_day` is true.

5. Change `build_recent_reviews()`:
   - Use `manifest.get("trading_dates") or manifest.get("dates", [])`.
   - Add to each enriched row:
     ```python
     "current_date": dates[-1] if dates else "",
     "data_status": "verified" if dates and dates[-1] == date_str else "stale_cache",
     ```
   - When no kline/current price is available, include `current_date: ""` and `data_status: "missing"`.

6. In `update_data_json()`, include `"data_quality": report_data.get("data_quality", {})` in `day_entry`.

**Tests to Add:**

1. `test_manifest_keeps_trading_dates_separate_from_dates`
   - Write `2026-06-20` with `is_trading_day=False, is_official=False`.
   - Write `2026-06-30` with `is_trading_day=True, is_official=True`.
   - Assert 06-20 appears in `dates`, not `trading_dates`.
   - Assert `latest_trading_date == "2026-06-30"`.

2. `test_generate_report_writes_data_quality_to_daily_json_and_manifest`
   - Use temp output dir and minimal report data containing `data_quality`.
   - Assert `data/YYYY-MM-DD.json` has top-level `data_quality`.
   - Assert `data/index.json.date_meta[date]` matches.

3. `test_recent_reviews_uses_trading_dates_not_all_dates`
   - Build temp `data/index.json` where `dates` includes a weekend/preview file and `trading_dates` excludes it.
   - Create JSON files for both, patch `fetch_daily_kline`.
   - Assert recent reviews do not include recommendation from the excluded weekend date.

4. `test_recent_reviews_marks_stale_current_data`
   - Patch `fetch_daily_kline` to return latest date before current report date.
   - Assert `data_status == "stale_cache"` and `current_date` is the stale latest date.

**Verification:**

Run:
```bash
python3 -m unittest tests.test_report_generator -v
```

Expected: all tests in that file pass.

## Task 3: Workspace Structured Tags And Data Badges

**Owner:** Worker 3

**Files:**
- Modify: `chanlun/report_view_model.py`
- Test: `tests/test_report_view_model.py`

**Requirements:**

1. Add `_build_info_tags(raw, source, risk_flags)`:
   - Add sector tag from `raw["sector"]`.
   - Add up to two extra sector tags from `raw["sector_tags"]` if they differ from primary sector. Use type `sector`.
   - Add source tag from `SOURCE_LABELS`.
   - Add signal tag from `best_buy_point.type`, `raw.type`, or `raw.source_type`.
   - Add confirm tag from `best_buy_point.sublevel_confirm_label`, `raw.sublevel_confirm_label`, or `best_buy_point.confirmed_by` if concise enough. Label should begin with `30min ` for sublevel labels.
   - Add at most two risk tags from `risk_flags`.
   - De-duplicate by `(type, label)`.

2. Add `_build_data_badges(raw, data_quality=None)`:
   - If row `data_status.daily == "verified"` add `{"type": "quality", "label": "数据已校验"}`.
   - If stale cache add `{"type": "quality", "label": "缓存兜底"}` and optionally `{"type": "risk", "label": "数据非最新"}`.
   - If missing add `{"type": "quality", "label": "日线缺失"}`.
   - If no row-level status but report `data_quality.fallback_used` is true add `{"type": "quality", "label": "含兜底数据"}`.
   - Otherwise default to `{"type": "quality", "label": "数据已校验"}` only if market status is verified or absent; avoid claiming verified if `market_status` is unverified/missing.

3. Thread report-level `data_quality` into `_build_item()`:
   - Accept optional `data_quality` parameter.
   - `_build_view_items()` and `_build_highlights()` should pass it through from `build_workspace()`.

4. `_build_item()` must include:
   ```python
   "info_tags": _build_info_tags(preferred_raw, preferred, all_risk_flags),
   "data_badges": _build_data_badges(preferred_raw, data_quality),
   ```

5. Keep `primary_reason` and all existing fields unchanged.

**Tests to Add:**

1. `test_workspace_item_has_info_tags`
   - Fusion pick with sector and best buy type.
   - Assert info tags include sector, source, signal.

2. `test_workspace_info_tags_include_extra_sector_tags`
   - Pick has `sector="电子"` and `sector_tags=["电子", "半导体"]`.
   - Assert both sector labels exist once.

3. `test_workspace_data_badges_reflect_stale_status`
   - Pick has `data_status.daily="stale_cache"`.
   - Assert data badges include `缓存兜底`.

4. `test_workspace_does_not_claim_verified_when_market_unverified`
   - No row-level data status, report `data_quality.market_status="unverified"`.
   - Assert there is no `数据已校验` badge.

**Verification:**

Run:
```bash
python3 -m unittest tests.test_report_view_model -v
```

Expected: all tests in that file pass.

## Task 4: Run.py Integration For Startup Sector And Quality Propagation

**Owner:** Worker 4

**Files:**
- Modify: `run.py`
- Test: `tests/test_market_data_guard.py` or a new focused unittest if needed

**Requirements:**

1. After `daily_data = collect_daily_data(...)`, set:
   ```python
   data_quality = daily_data.get("data_quality", {})
   ```

2. Strong-startup normalized pick must preserve sector metadata:
   ```python
   sector_meta = sector_stocks.get(sc["code"], {})
   "sector": sc.get("sector") or sector_meta.get("sector", ""),
   "sector_tags": sc.get("sector_tags") or sector_meta.get("sector_tags", []),
   "sector_rank": sector_meta.get("sector_rank"),
   "sector_flow": sector_meta.get("sector_flow"),
   "sector_strength_label": sector_meta.get("sector_strength_label", ""),
   ```

3. Preserve row-level `data_status` when available:
   ```python
   "data_status": sc.get("data_status") or sector_meta.get("data_status", {}),
   ```

4. Add `data_quality` to `diagnostics`:
   ```python
   "data_quality": data_quality,
   ```

5. Add top-level `data_quality` to `report_data`.

6. Debug mode should also create a minimal `data_quality` to keep report contract stable:
   ```python
   "data_quality": {
      "report_date": today,
      "is_trading_day": bool(sh_kline),
      "is_official": False,
      "market_status": "verified" if sh_kline else "unverified",
      "stock_pool_source": "manual_debug",
      "sector_source": "eastmoney" if sectors else "empty",
      "stale_stock_count": 0,
      "missing_daily_count": 0,
      "missing_30min_count": 0,
      "fallback_used": False,
      "warnings": ["debug mode"],
   }
   ```

**Tests to Add:**

1. Prefer testing helper extraction if adding a small local helper is cleaner.
2. Minimum required assertion: startup normalized pick no longer contains hardcoded `"sector": ""`; tests may inspect `run.py` source only if extracting helper would expand risk too much.
3. Assert generated `report_data` path can carry `data_quality` through `generate_report` using tests from Task 2.

**Verification:**

Run:
```bash
python3 -m py_compile run.py
python3 -m unittest tests.test_market_data_guard tests.test_report_generator tests.test_report_view_model -v
```

Expected: all targeted tests pass.

## Task 5: Validation Script Guardrails

**Owner:** Worker 5

**Files:**
- Modify: `scripts/validate_today_report.py`
- Test: `tests/test_market_data_guard.py`

**Requirements:**

1. Extend `validate_report_contract(report)` to validate `data_quality` when present:
   - `data_quality` must be a dict.
   - If `data_quality.is_official is True`, then:
     - `market_status == "verified"`.
     - `fallback_used is False`.
     - `stale_stock_count == 0`.
     - `missing_daily_count == 0`.
   - If any workspace row or raw candidate has `data_status.daily == "stale_cache"` and report is official, return an error.

2. Keep existing workspace display-field checks from the previous bugfix.

3. Add tests:
   - `test_validate_report_contract_rejects_official_stale_data_quality`
   - `test_validate_report_contract_rejects_official_stale_candidate_status`
   - `test_validate_report_contract_allows_preview_stale_status_when_not_official`

**Verification:**

Run:
```bash
python3 -m unittest tests.test_market_data_guard -v
python3 -m py_compile scripts/validate_today_report.py
```

Expected: all tests pass and script compiles.

## Final Integration Review

After all worker tasks are complete, controller must run:

```bash
python3 -m unittest tests.test_market_data_guard tests.test_report_generator tests.test_report_view_model tests.test_requests_sessions -v
python3 -m py_compile run.py chanlun/data_fetcher.py chanlun/report_generator.py chanlun/report_view_model.py scripts/validate_today_report.py
zsh -n daily_run.sh
git diff --check
```

Optional generated-report contract check if local data is safe to regenerate:

```bash
python3 main.py run
python3 scripts/validate_today_report.py
```

Do not run live generation if network/cache state would make it noisy unless the controller explicitly decides it is needed.

## Review Checklist

- `docs/data/YYYY-MM-DD.json` has top-level `data_quality`.
- `diagnostics.data_quality` exists.
- `docs/data/index.json` has `dates`, `trading_dates`, `latest`, `latest_trading_date`, `date_meta`.
- Non-trading/preview dates can enter `dates` but not `trading_dates`.
- `build_recent_reviews()` only uses `trading_dates` when present.
- Strong-startup normalized picks preserve `sector` and `sector_tags`.
- Multi-sector stocks preserve all sector tags while primary sector remains first/highest-rank.
- Official mode does not include stale daily K-line rows.
- Preview mode may include stale rows but they carry `data_status.daily="stale_cache"`.
- Workspace rows include `info_tags` and `data_badges`.
- Existing fields remain backward compatible.
- Unrelated working tree entries are not staged.
