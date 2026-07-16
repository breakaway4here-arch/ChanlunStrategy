# Recommendation and Market Sentiment V2 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the report main view contain only genuine recommendations, repair evidence-driven ranking and position decisions, deduplicate sector flows, and add a reproducible 20-trading-day market sentiment chart.

**Architecture:** Keep decision and sentiment calculation in Python as the single source of truth. Build historical market evidence from the local market-history database, persist both raw evidence and derived scores in report JSON, and make the browser render-only. Preserve compatibility fields while removing the legacy frontend scoring path from formal conclusions.

**Tech Stack:** Python 3 standard library, existing SQLite market-history repository, unittest, existing report view-model/generator, vanilla JavaScript, ECharts.

---

### Task 1: Make report views decision-aware

**Files:**
- Modify: `chanlun/report_view_model.py`
- Test: `tests/test_report_view_model.py`

**Step 1: Write failing tests**

Add tests proving:

```python
def test_main_view_contains_all_recommendations_without_top_limit():
    rows = [make_pick(i, decision_code="recommend") for i in range(12)]
    rows += [make_pick(20, decision_code="observe")]
    workspace = build_report_workspace({"picks_fusion": rows})
    assert len(workspace["views"]["main"]) == 12
    assert all(row["decision_code"] == "recommend" for row in workspace["views"]["main"])


def test_highlights_excludes_reject_and_prioritizes_recommend():
    workspace = build_report_workspace(report_with_mixed_decisions())
    rows = workspace["views"]["highlights"]
    assert all(row["decision_code"] != "reject" for row in rows)
    assert decision_codes(rows) == sorted(decision_codes(rows), key=decision_priority)


def test_growth_quality_requires_evidence_coverage():
    workspace = build_report_workspace(report_with_complete_and_missing_quality())
    assert codes(workspace["views"]["growth_quality"]) == ["000001"]
```

**Step 2: Run tests and verify failure**

Run:

```bash
python3 -m unittest tests.test_report_view_model -v
```

Expected: FAIL because main currently exposes the entire fusion pool and quality ranking accepts missing evidence.

**Step 3: Implement minimal view rules**

- Filter `main` by `decision_code == "recommend"` with no slice limit.
- Set `default_view` to `main`.
- Filter `reject` from highlights and sort by decision priority before opportunity score.
- Add a quality-evidence predicate and exclude insufficient rows instead of assigning default zero scores.

**Step 4: Run tests**

Run:

```bash
python3 -m unittest tests.test_report_view_model -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add chanlun/report_view_model.py tests/test_report_view_model.py
git commit -m "fix: 修正日报推荐视图口径"
```

### Task 2: Generate trusted position evidence before decisions

**Files:**
- Modify: `chanlun/decision_engine.py`
- Modify: `chanlun/scoring_engine.py`
- Modify: `run.py`
- Test: `tests/test_decision_engine.py`
- Test: `tests/test_scoring_engine.py`

**Step 1: Write failing tests**

Cover:

```python
def test_decision_uses_only_verified_position_evidence():
    stock = {
        "position_distance_pct": 4.2,
        "position_reference_price": 10.0,
        "position_reference_type": "channel_reference",
        "position_data_status": "verified",
    }
    assert decide_stock(stock)["position"]["status"] == "safe"


def test_unverified_or_serialized_default_distance_is_not_consumed():
    stock = {
        "best_buy_point": {"distance_from_reference_pct": 0.0},
        "position_data_status": "missing",
    }
    assert decide_stock(stock)["decision"] == "暂不判断（位置信息不足）"
```

Add channel-specific evidence tests for low-position and trend candidates, including invalid reference prices, future evidence dates, `NaN`, and `Inf`.

**Step 2: Run tests and verify failure**

```bash
python3 -m unittest tests.test_decision_engine tests.test_scoring_engine -v
```

Expected: FAIL because the explicit position evidence contract does not exist.

**Step 3: Implement position evidence builder**

Create one backend helper that runs before decision injection and emits:

```python
{
    "position_distance_pct": value_or_none,
    "position_reference_price": value_or_none,
    "position_reference_type": "channel_reference" | "buy_point" | "none",
    "position_data_status": "verified" | "missing" | "invalid",
    "position_evidence_date": "YYYY-MM-DD",
}
```

Rules:

- Reject invalid numeric values and non-positive reference prices.
- Do not read `best_buy_point.distance_from_reference_pct` unless its reference semantics are explicitly verified.
- Keep `ENABLE_DISTANCE_DECISION` disabled.
- Decision engine consumes only top-level verified position evidence.

**Step 4: Run tests**

```bash
python3 -m unittest tests.test_decision_engine tests.test_scoring_engine -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add chanlun/decision_engine.py chanlun/scoring_engine.py run.py tests/test_decision_engine.py tests/test_scoring_engine.py
git commit -m "fix: 补齐可信位置决策证据"
```

### Task 3: Preserve growth-quality inputs through the pipeline

**Files:**
- Modify: `chanlun/scoring_engine.py`
- Modify: `chanlun/report_view_model.py`
- Test: `tests/test_scoring_engine.py`
- Test: `tests/test_report_view_model.py`

**Step 1: Write failing tests**

Verify that available `market_cap`, `circulating_market_cap`, `money20`, and quality-tier fields survive scoring and report normalization. Verify that missing values remain `None`, not zero.

**Step 2: Run tests and verify failure**

```bash
python3 -m unittest tests.test_scoring_engine tests.test_report_view_model -v
```

Expected: FAIL where fields are currently dropped or normalized to false defaults.

**Step 3: Implement propagation**

- Preserve canonical quality fields from universe rows through scored rows.
- Use one evidence-coverage helper shared by growth-quality ranking and diagnostics.
- Add a view diagnostic with eligible and excluded counts.

**Step 4: Run tests**

```bash
python3 -m unittest tests.test_scoring_engine tests.test_report_view_model -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add chanlun/scoring_engine.py chanlun/report_view_model.py tests/test_scoring_engine.py tests/test_report_view_model.py
git commit -m "fix: 修复成长质量数据传递"
```

### Task 4: Deduplicate hierarchical sector-flow rows

**Files:**
- Modify: `chanlun/data_fetcher.py`
- Modify: `run.py`
- Test: `tests/test_data_fetcher.py`

**Step 1: Write failing tests**

Use fixtures representing:

- `电子 -> 半导体 -> 数字芯片设计`
- `通信 -> 通信设备`
- `IT服务II -> IT服务III`

Assert that high-overlap parent/child candidates do not coexist in the final inflow or outflow list and that deduplicated rows are not summed.

**Step 2: Run tests and verify failure**

```bash
python3 -m unittest tests.test_data_fetcher -v
```

Expected: FAIL because current fetchers simply slice the raw ranking.

**Step 3: Implement evidence-based deduplication**

- Fetch a wider candidate window than the display count.
- Obtain component-code sets for candidates where available.
- Treat subset or high-overlap component sets as one hierarchy chain.
- Keep the strongest representative by absolute flow and evidence coverage.
- Attach `hierarchy_dedup_status` and `component_coverage`.
- Never calculate a mixed-level total.

If component evidence is unavailable, retain the raw item but mark it `unverified`; do not silently claim deduplication.

**Step 4: Run tests**

```bash
python3 -m unittest tests.test_data_fetcher -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add chanlun/data_fetcher.py run.py tests/test_data_fetcher.py
git commit -m "fix: 去重板块资金层级"
```

### Task 5: Build reproducible market-evidence snapshots

**Files:**
- Create: `chanlun/market_sentiment.py`
- Modify: `chanlun/market_history_repository.py`
- Test: `tests/test_market_sentiment.py`
- Test: `tests/test_market_history_repository.py`

**Step 1: Write failing tests**

Create deterministic daily-bar fixtures covering:

- Main board 10% limit.
- ChiNext/STAR 20% limit.
- Beijing exchange limit.
- ST limit.
- One-price limit.
- New/unlimited stock exclusion.
- Suspended and invalid rows.
- Advance/decline/flat counts.
- Median return and large-rise/large-fall breadth.
- Total turnover, MA5, and MA20.
- Trend-above-MA ratios.

Assert that limit-up and limit-down counts are produced from the same dated snapshot.

**Step 2: Run tests and verify failure**

```bash
python3 -m unittest tests.test_market_sentiment tests.test_market_history_repository -v
```

Expected: FAIL because the evidence builder and historical cross-section query do not exist.

**Step 3: Implement repository query and evidence builder**

Add a read-only repository method returning all eligible A-share daily bars for a requested date plus required lookback data. Build:

```python
{
    "date": report_date,
    "breadth": {...},
    "limits": {...},
    "turnover": {...},
    "trend": {...},
    "sources": {...},
    "coverage": {...},
}
```

Do not treat missing records as unchanged or zero. Record excluded counts by reason.

**Step 4: Run tests**

```bash
python3 -m unittest tests.test_market_sentiment tests.test_market_history_repository -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add chanlun/market_sentiment.py chanlun/market_history_repository.py tests/test_market_sentiment.py tests/test_market_history_repository.py
git commit -m "feat: 构建可复算市场情绪证据"
```

### Task 6: Score sentiment V2 and detect turns

**Files:**
- Modify: `chanlun/market_sentiment.py`
- Modify: `run.py`
- Test: `tests/test_market_sentiment.py`
- Test: `tests/test_market_temperature.py`

**Step 1: Write failing tests**

Test:

- Five component weights sum to 100%.
- Smoothed ratio `(up + 1) / (down + 1)`.
- Log-ratio percentile normalization.
- No future dates are used in historical percentiles.
- Partial evidence reweights valid components and emits coverage.
- Low coverage yields `status == "insufficient"`.
- Fewer than five valid days produce no turning signal.
- Synthetic sequences detect ice rebound, strengthening, weakening, and hot reversal.

**Step 2: Run tests and verify failure**

```bash
python3 -m unittest tests.test_market_sentiment tests.test_market_temperature -v
```

Expected: FAIL because V2 scoring and turning detection do not exist.

**Step 3: Implement scoring**

Use:

```python
WEIGHTS = {
    "breadth": 0.30,
    "limit_ecology": 0.30,
    "index_strength": 0.15,
    "turnover_activity": 0.15,
    "trend_structure": 0.10,
}
```

Return score, label, status, coverage, component scores, raw evidence, MA3, deltas, and optional turning signal. Map the result into legacy `market_temperature` only for compatibility.

**Step 4: Run tests**

```bash
python3 -m unittest tests.test_market_sentiment tests.test_market_temperature -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add chanlun/market_sentiment.py run.py tests/test_market_sentiment.py tests/test_market_temperature.py
git commit -m "feat: 升级市场情绪评分与转折"
```

### Task 7: Recalculate and persist 20 trading days

**Files:**
- Modify: `run.py`
- Modify: `chanlun/report_generator.py`
- Test: `tests/test_report_generator.py`
- Test: `tests/test_market_sentiment.py`

**Step 1: Write failing tests**

Assert:

- At most 20 valid trading dates are emitted in chronological order.
- Each history point was calculated with evidence dated no later than itself.
- `market_sentiment` and `market_sentiment_history` survive JSON serialization.
- Existing empty or wrong `market_temperature` snapshots are not reused.

**Step 2: Run tests and verify failure**

```bash
python3 -m unittest tests.test_market_sentiment tests.test_report_generator -v
```

Expected: FAIL because sentiment history is not currently serialized.

**Step 3: Implement history and persistence**

- Query the latest 20 available trading dates ending at report date.
- Calculate each date from the local database.
- Persist V2 current and history objects.
- Preserve explicit diagnostics for unavailable historical dates.

**Step 4: Run tests**

```bash
python3 -m unittest tests.test_market_sentiment tests.test_report_generator -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add run.py chanlun/report_generator.py tests/test_market_sentiment.py tests/test_report_generator.py
git commit -m "feat: 沉淀二十日市场情绪"
```

### Task 8: Render the sentiment chart without frontend rescoring

**Files:**
- Modify: `chanlun/report_assets/report-v2.js`
- Modify: `chanlun/report_assets/report-v2.css`
- Modify: `chanlun/report_generator.py`
- Test: `tests/test_report_generator.py`

**Step 1: Write failing static-contract tests**

Assert that the generated report:

- References `market_sentiment_history`.
- Creates a dedicated ECharts instance for sentiment.
- Renders raw score and MA3 series.
- Includes background zones and turn markers.
- Displays limit-up, limit-down, and ratio in tooltip.
- Does not use the legacy browser formula when backend V2 evidence is absent; it displays insufficient data instead.

**Step 2: Run tests and verify failure**

```bash
python3 -m unittest tests.test_report_generator -v
```

Expected: FAIL because no sentiment chart exists and frontend still contains formal fallback scoring.

**Step 3: Implement rendering**

- Add a responsive chart mount inside the market sentiment card.
- Use separate `sentimentChartInstance`.
- Plot 20-day score and MA3.
- Add mark areas for temperature zones and mark points for verified turns.
- Resize and dispose safely.
- Render evidence coverage and “样本不足/数据不足” states explicitly.

**Step 4: Run tests**

```bash
python3 -m unittest tests.test_report_generator -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add chanlun/report_assets/report-v2.js chanlun/report_assets/report-v2.css chanlun/report_generator.py tests/test_report_generator.py
git commit -m "feat: 增加市场情绪二十日曲线"
```

### Task 9: Full regression, report regeneration, and release verification

**Files:**
- Regenerate: `docs/data/2026-07-16.json`
- Regenerate: `docs/2026-07-16/index.html`
- Regenerate: report index files as required by the existing publish workflow

**Step 1: Run focused suites**

```bash
python3 -m unittest \
  tests.test_report_view_model \
  tests.test_decision_engine \
  tests.test_scoring_engine \
  tests.test_data_fetcher \
  tests.test_market_history_repository \
  tests.test_market_sentiment \
  tests.test_market_temperature \
  tests.test_report_generator -v
```

Expected: PASS.

**Step 2: Run repository regression suite**

```bash
python3 -m unittest discover -v
```

Expected: PASS, or report any pre-existing unrelated failure separately with exact evidence.

**Step 3: Regenerate 2026-07-16 report**

Use the repository’s normal official daily-run command and require database-first market history. Do not use preview output as production evidence.

**Step 4: Validate generated JSON**

Check:

- Main contains only recommend decisions.
- Main has no fixed Top10 truncation.
- Decision distribution and position-evidence status counts are reported.
- Growth-quality eligible/excluded counts are present.
- Sector flow has hierarchy diagnostics.
- Sentiment has 20 or fewer valid chronological points, raw evidence, scores, coverage, and no future data.

**Step 5: Validate rendered page**

Open the generated official report and verify:

- Default view and counts.
- Main/highlights/growth-quality semantics.
- Sector-flow labels.
- Sentiment line, MA3, zones, tooltip, and insufficient-data states.

**Step 6: Commit generated artifacts**

```bash
git add docs/data/2026-07-16.json docs/2026-07-16/index.html docs/index.html
git commit -m "chore: 更新七月十六日日报"
```

**Step 7: Push and verify online**

Push the current branch, merge to `main` through the existing release workflow, and verify that the online JSON and page match the committed revision before reporting completion.
