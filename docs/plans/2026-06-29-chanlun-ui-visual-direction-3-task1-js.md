# Chanlun UI Visual Direction 3 Task 1: JS Structure

## Ownership

You are the JS worker. Use model `gpt-5.3-codex-spark`.

You are not alone in the codebase. Another worker may edit CSS only. Do not revert or overwrite unrelated edits. Your write scope is limited to:

- `chanlun/report_assets/report-v2.js`
- `tests/test_report_generator.py`

Do not edit `chanlun/report_assets/report-v2.css`, generated `docs/assets`, or backend Python algorithms.

## Goal

Update report v2 JavaScript so the light fintech dashboard visual system has the semantic hooks it needs: unified tag classes, rank badges, richer candidate row structure, and a market temperature card with fallback calculation.

## Requirements

1. Keep the existing app shell, access-control behavior, chart lifecycle, tab counts, and mobile drawer behavior.
2. Do not modify recommendation sorting, scoring, workspace building, or backend candidate construction.
3. Keep all dynamic strings escaped with `escapeHtml`.
4. Do not fabricate fake data. If a value is absent, show real fallback copy such as `暂无...` or `--`.
5. Preserve A-share semantics: positive/up is red, negative/down is green.

## Implementation Tasks

1. Add mapping helpers near existing formatting helpers:
   - `clamp(value, min, max)`
   - `getActionClass(action)`
   - `getRiskClass(risk)`
   - `getSourceClass(label)`
   - `getRankClass(rank)`
   - `getResonanceClass(label)`
2. Update `renderCandidateList()` markup to include:
   - `<span class="rank-badge ...">01</span>`
   - `<div class="candidate-identity">...`
   - `<div class="candidate-price">...`
   - `<div class="candidate-tags">...`
   - action and risk tags using the mapping helpers
3. Add market temperature helpers:
   - `buildMarketTemperature(data)`
   - `getMarketTemperatureLabel(score)`
   - `getMarketTemperatureTone(score)`
   - `getMarketTemperatureSummary(score)`
4. Update `renderMarketTemperatureCard(data)` so it uses `buildMarketTemperature(data)` and renders:
   - score `/ 100`
   - label badge
   - component rows
   - summary fallback text
5. Extend `tests/test_report_generator.py` in the existing report-v2 auxiliary/header test area:
   - assert helper names exist in `report-v2.js`
   - assert market temperature card references score, label, and components
   - assert class mapping helper names exist
   - assert old `metric-chip` header pool count pattern remains absent
   - assert tab counts remain present

## Verification

Run:

```bash
node --check chanlun/report_assets/report-v2.js
python3 -m unittest tests.test_report_generator -v
```

Return:

- Files changed
- Verification commands and results
- Any assumptions or skipped items
