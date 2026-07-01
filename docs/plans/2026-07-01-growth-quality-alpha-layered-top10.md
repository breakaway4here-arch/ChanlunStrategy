# Growth Quality Alpha Layered Top10 Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Turn pool quality from broad positive scoring into a selective growth-quality alpha, enrich daily candidates with real turnover/capitalization fields when available, and expose a non-destructive growth-quality Top10 view.

**Architecture:** Keep the existing `pool -> scoring -> ranking -> report` flow intact. Daily data enrichment adds fields onto existing candidate rows; `report_view_model` derives quality features and a new view from those fields; `scoring_engine` only consumes the same `alpha_features.pool_quality` payload and applies bounded layered bonus.

**Tech Stack:** Python stdlib, existing EastMoney/Tencent/Sina data fetchers, `unittest`, existing offline `docs/data` snapshots and `scripts/backtest_scoring_alpha_impact.py`.

---

## Global Constraints

- Do not replace existing stock pools or change the main `highlights` Top10 behavior.
- Do not add a new framework, feature layer, or split the scoring pipeline.
- Do not make `market_cap` up when it is not available. Use `None` plus a source/status field.
- Keep all new growth-quality behavior observable and bounded.
- Keep `scripts/joinquant_alpha_weight_experiment.py` untouched.
- Use `gpt-5.3-codex-spark` for implementation subagents.

## Task A: Layer Pool Quality Bonus In Scoring

**Owner:** Worker A  
**Files:**
- Modify: `chanlun/scoring_engine.py`
- Test: `tests/test_scoring_engine.py`

**Implementation steps:**

1. Replace the current additive `_score_pool_quality_bonus()` behavior with layered tiers.
2. Require all three legs for a clearly visible bonus:
   - high liquidity: prefer `money20`/成交额-derived score; fallback to current volume proxy.
   - growth style: `300/301`, `688/689`, or `002`.
   - strong sector: high `sector_quality_score`.
3. Suggested tiers:
   - `elite`: liquidity >= 70, growth >= 55, sector >= 70 -> up to `+3.0`.
   - `strong`: liquidity >= 55, growth >= 55, sector >= 55 -> up to `+1.8`.
   - `partial`: two of three legs pass -> max `+0.7`.
   - otherwise -> `0`.
4. Continue clamping total alpha by `ALPHA_BONUS_LIMIT`.
5. Add trace diagnostics:
   - `pool_quality_bonus`
   - `pool_quality_score`
   - `pool_quality_tier`
   - `pool_quality_tags`
   - `pool_quality_components` if helpful.

**Acceptance tests:**

- Ordinary liquidity-only or growth-only rows add `0` or tiny partial bonus, not broad bonus.
- Elite rows get a clear but capped bonus.
- Missing `pool_quality` remains unchanged.
- Extreme values still clamp.
- Existing alpha-disabled test remains unchanged.

## Task B: Enrich Daily Rows With Real Money And Market Cap Fields

**Owner:** Worker B  
**Files:**
- Modify: `chanlun/data_fetcher.py`
- Modify: `run.py`
- Test: `tests/test_market_data_guard.py` and/or targeted existing tests

**Implementation steps:**

1. Preserve daily K-line amount/money arrays when providers expose them:
   - EastMoney `fields2` includes amount in the historical kline string; parse it into `amounts`.
   - Tencent/Sina may lack amount; leave `amounts` absent or empty instead of inventing it.
2. In `batch_fetch_daily_klines()`, pass through existing stock metadata:
   - `market_cap`
   - `float_market_cap`
   - `amount`
   - any provider/source marker.
3. Extend `fetch_sector_stocks()` to request useful EastMoney fields for capitalization if available. Keep failures non-fatal.
4. In `run.py`, attach candidate-level liquidity fields onto existing rows:
   - `money20`
   - `amounts` when present and serializable downstream
   - `market_cap`
   - `float_market_cap`
   - `liquidity_source` with values like `amounts`, `volume_price_proxy`, `missing`.
5. For rows generated from startup/luojie/acceleration paths, preserve these fields when source stock metadata exists.

**Acceptance tests:**

- EastMoney kline parser preserves `amounts`.
- `batch_fetch_daily_klines()` carries market cap metadata.
- Candidate rows can expose `money20` when `amounts` exist.
- Missing provider fields do not break report generation and do not fabricate market cap.

## Task C: Add Non-Destructive Growth Quality Top10 View

**Owner:** Worker C, after A and B land  
**Files:**
- Modify: `chanlun/report_view_model.py`
- Test: `tests/test_report_view_model.py`
- Optional smoke: `scripts/backtest_scoring_alpha_impact.py`

**Implementation steps:**

1. Extend `_build_pool_quality_features()` to prefer:
   - `money20` for liquidity score when available.
   - `circulating_market_cap` first, then `market_cap`, internally normalized to `亿元`.
   - `ret20` from explicit field or last 20 trading days of closes.
   - `market_cap`/`circulating_market_cap` as growth-elasticity scoring inputs, not hard filters.
2. Add `pool_quality_tier` / component diagnostics into workspace item `pool_quality`.
3. Add a new view key, for example `growth_quality`, to `VIEW_ORDER` and `VIEW_META`.
4. Build `growth_quality` from existing non-baseline candidates only:
   - same merged universe as `highlights`.
   - sort by tier first, then `pool_quality_score`, then `opportunity_score`, then code.
   - limit to Top10.
5. Keep `default_view` as `highlights`.
6. Add workspace diagnostics comparing:
   - original `highlights` codes.
   - `growth_quality` codes.
   - overlap count.

**Acceptance tests:**

- `workspace["views"]["growth_quality"]` exists but `default_view` remains `highlights`.
- Existing `highlights` ranking is unchanged when growth-quality view is added.
- Growth quality view promotes elite growth/liquidity/sector rows over ordinary rows.
- Baseline pool still does not enter `highlights` or `growth_quality`.
- `view_meta` and counts include the new view.

## Task D: Backtest And Review

**Owner:** Main agent

**Verification commands:**

```bash
python3 -m unittest tests.test_scoring_engine tests.test_report_view_model tests.test_market_data_guard -v
python3 -m unittest tests.test_report_generator tests.test_daily_structure_pool tests.test_candidate_upgrade tests.test_fusion_admission tests.test_signal_recency tests.test_strong_startup tests.test_startup_labels -v
python3 -m py_compile chanlun/scoring_engine.py chanlun/report_view_model.py chanlun/data_fetcher.py run.py scripts/backtest_scoring_alpha_impact.py
git diff --check
python3 scripts/backtest_scoring_alpha_impact.py --min-forward-days 1 --horizon 1 --top-k 10 --metric t1_close_pct
python3 scripts/backtest_scoring_alpha_impact.py --min-forward-days 3 --horizon 5 --top-k 10 --metric t3_close_pct
```

**Review checklist:**

- No new pool replaces the original pools.
- Growth quality view is opt-in/non-default.
- Broad pool-quality bonus is gone; obvious score movement requires real turnover, growth style/cap fit, and strong sector.
- `money20` is stored in yuan; `<5000万` does not earn liquidity alpha, `>=1亿` becomes meaningful liquidity, and `>=2亿` is high liquidity.
- Market-cap fields are stored in `亿元`; `circulating_market_cap` is preferred over `market_cap`.
- Growth elasticity favors `30亿 <= market_cap <= 800亿` or the analogous circulating-cap bands, plus `300/301/688/689/002` style and sane `ret20`.
- Real money fields are used when present; market cap remains `None` when absent.
- Backtest conclusion separates ranking/view changes from scoring changes.
