# Task 1: Header + Decision Center JS

## Scope

Modify only:

- `chanlun/report_assets/report-v2.js`
- `tests/test_report_generator.py`

Do not modify:

- `chanlun/report_assets/report-v2.css`
- `chanlun/report_view_model.py`
- `chanlun/report_generator.py`
- `docs/assets/*`
- `docs/index.html`
- `docs/data/*`

## Goal

Move header content from duplicated pool counts to market overview, and rebuild auxiliary information as structured decision cards.

## Required Behavior

- Header no longer renders `看点 / 主推 / 加速 / 罗姐池 / 等确认 / 基准` metric chips.
- Workspace tabs still render labels and counts.
- Header renders:
  - market status
  - operation pace
  - market breadth
  - average index change
  - index cards from `data.market`
- Auxiliary center renders these seven cards:
  - `市场温度`
  - `板块资金`
  - `涨停情绪`
  - `事件驱动`
  - `卖出提醒`
  - `策略回看`
  - `数据诊断`
- All dynamic text must pass through `escapeHtml`.
- Empty data must show friendly fallback text.

## Implementation Notes

Add helpers near the existing header/auxiliary functions:

- `getMarketItems(market)`
- `buildMarketSummary(market)`
- `buildMarketStyleHint(best)`
- `renderMarketRegime(summary)`
- `renderMarketIndexCards(items)`
- `renderDecisionCard(config)`
- `renderStatusBadge(badge)`
- `renderMarketTemperatureCard(data)`
- `renderSectorFlowCard(data)`
- `renderLimitUpCard(data)`
- `renderEventsCard(data)`
- `renderSellSignalsCard(data)`
- `renderRecentReviewsCard(data)`
- `renderDiagnosticsCard(data)`

Keep JS style consistent with the current file: use `var`, string concatenation, and existing helpers (`safeNumber`, `formatPct`, `formatNumber`, `normalizeString`, `asArray`, `escapeHtml`).

## Tests To Add Or Update

In `tests/test_report_generator.py`, add lightweight assertions against copied `asset_js`:

- `buildMarketSummary`
- `renderMarketTemperatureCard`
- `renderDecisionCard`
- `辅助决策中心`
- no old top header string `metric-chip">看点`
- `workspace-tab-count` still exists

## Verification

Run:

```bash
node --check chanlun/report_assets/report-v2.js
python3 -m unittest tests.test_report_generator -v
```

Return:

- Changed files.
- Test output summary.
- Any assumptions or edge cases.
