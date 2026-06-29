# Chanlun Daily UI v2 Task 3 Frontend Assets Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement the v2 daily report UI assets: compact white trading workspace, desktop split view, mobile two-line market table, detail drawer, charts, and auxiliary center.

**Architecture:** `report-v2.js` reads bootstrap/data loaded by the generator, renders `REPORT_DATA.workspace`, and uses each item `ref` to find raw pool objects for detail and chart rendering. `report-v2.css` owns all visual layout and responsive behavior.

**Tech Stack:** Vanilla JavaScript, ECharts, CSS.

---

## Files

- Create: `chanlun/report_assets/report-v2.css`
- Create: `chanlun/report_assets/report-v2.js`

Avoid editing `chanlun/report_generator.py`.
Avoid editing `chanlun/report_view_model.py`.

## Design Direction

Use the spec's confirmed visual system, not a new creative theme:

- Background `#F7F8FB`
- Cards `#FFFFFF`
- Text `#111827`, `#4B5563`, `#9CA3AF`
- Border `#E5E7EB`
- Primary `#5167F6`
- A-share up red `#EF4444`
- A-share down green `#10B981`
- Risk orange `#F59E0B`
- Resonance gold `#D97706`
- System font stack with tabular numerics

## Required JS Functions

- `initReportV2()`
- `renderHeader()`
- `renderWorkspaceTabs()`
- `renderViewDescription()`
- `renderCandidateList()`
- `renderCandidateDetail()`
- `openMobileDetailDrawer()`
- `closeMobileDetailDrawer()`
- `findRawCandidate(ref)`
- `renderChart(rawCandidate, workspaceItem)`
- `renderAuxiliaryCenter()`

## Required UI Behavior

- Default view is `workspace.default_view`, expected `highlights`.
- Tabs: `看点 Top10`, `主推`, `加速`, `罗姐池`, `等确认`, `基准`, with counts.
- View description visible under tabs.
- Desktop: left candidate list, right sticky/detail panel.
- Mobile:
  - header no more than two lines in normal width
  - horizontally scrollable tabs
  - each candidate is two compact rows by default
  - risk third row appears only when `risk_flags` exist
  - tap opens bottom detail drawer
- Detail order: conclusion, price, chart, reason, risk, details.
- Chart must show K-line plus MACD when data exists.
- Empty chart state text:
  - `暂无图表数据，但保留推荐原因和来源。请检查原始池子数据或 K 线数据。`
- Auxiliary center is below workspace and collapsed by default.
- Auxiliary order: market, sector, limit-up, events, sell, reviews, diagnostics.
- Use `escapeHtml` for dynamic strings.
- Do not use emoji icons or fabricated labels.
- Do not perform sort/dedupe/action/resonance generation in JS.

## Required CSS Modules

- `.report-shell`
- `.report-header`
- `.workspace`
- `.workspace-tabs`
- `.view-description`
- `.candidate-list`
- `.candidate-row`
- `.source-chip`
- `.resonance-chip`
- `.action-pill`
- `.detail-panel`
- `.detail-price-grid`
- `.chart-panel`
- `.mobile-drawer`
- `.aux-center`

## Suggested Implementation Steps

1. Create CSS variables from the spec.
2. Build desktop layout and stable dimensions first.
3. Build candidate rows with tabular numerics and no layout shift.
4. Build detail panel and chart container.
5. Build mobile media query at `max-width: 760px`.
6. Build drawer interactions and chart resize on open.
7. Build auxiliary center as a `<details>` section.
8. Add defensive empty states for no workspace, no candidates, no raw chart.
9. Run a local syntax smoke check:
   - `node --check chanlun/report_assets/report-v2.js` if node exists.

## Expected Worker Output

- Changed file list.
- Syntax check output.
- Notes on any generator contract assumptions.
