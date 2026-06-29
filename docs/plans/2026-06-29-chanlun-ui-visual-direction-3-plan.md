# Chanlun UI Visual Direction 3 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Apply the light fintech dashboard visual system from `/Users/yangfan/Downloads/chanlun_ui_visual_direction_3_style_config.md` to the existing report v2 frontend without changing recommendation algorithms.

**Architecture:** Keep the existing static-report architecture: `chanlun/report_assets/report-v2.js` owns semantic markup and fallback calculations, while `chanlun/report_assets/report-v2.css` owns visual tokens, layout, tags, badges, and responsive behavior. After source asset edits, regenerate or copy into `docs/assets` so runtime docs stay in sync.

**Tech Stack:** Plain JavaScript, CSS, Python unittest, static HTML assets.

---

## Requirements

1. Preserve the existing `taste-ui-design-system` branch and report v2 data contract.
2. Do not modify recommendation ranking, `build_workspace()`, candidate pool construction, scoring, or backend selection algorithms.
3. Do not introduce new dependencies.
4. Keep A-share color semantics: up/positive is red, down/negative is green, risk is orange, primary actions are blue, resonance is purple.
5. Keep tab counts and the existing view order.
6. Do not reintroduce duplicated candidate pool count chips in the header.
7. Keep `chanlun/report_assets` and `docs/assets` synchronized before final verification.

## Task Split

### Task 1: JS Structure, Class Mapping, And Market Temperature

**Owner:** JS worker (`gpt-5.3-codex-spark`)

**Files:**
- Modify: `chanlun/report_assets/report-v2.js`
- Modify: `tests/test_report_generator.py`

**Scope:**
- Add class mapping helpers:
  - `getActionClass(action)`
  - `getRiskClass(risk)`
  - `getSourceClass(label)`
  - `getRankClass(rank)`
  - `getResonanceClass(label)`
- Update candidate row markup so each row has:
  - rank badge
  - identity block
  - price/change block
  - source/resonance/action/risk tag group
  - star/priority marker only if backed by existing real candidate state; otherwise omit rather than fabricate.
- Add market temperature fallback calculation based on existing report fields:
  - index breadth from market indices
  - average index change
  - report-level limit-up pool length
  - neutral volume fallback
  - sector inflow/outflow counts
  - sell signal count and hot-risk count
- Add label/tone helpers:
  - `buildMarketTemperature(data)`
  - `getMarketTemperatureLabel(score)`
  - `getMarketTemperatureTone(score)`
  - `getMarketTemperatureSummary(score)`
- Update market temperature card to show score, label, component rows, and nonblank fallback copy.
- Extend tests to assert helper names, seven auxiliary cards, market temperature fallback, tab counts, no old header metric chips, and class mapping presence.

**Out of scope:**
- Do not edit CSS.
- Do not change generated `docs/assets` directly.
- Do not change backend Python report algorithms.

**Verification:**
- `node --check chanlun/report_assets/report-v2.js`
- `python3 -m unittest tests.test_report_generator -v`

### Task 2: CSS Visual System And Responsive Polish

**Owner:** CSS worker (`gpt-5.3-codex-spark`)

**Files:**
- Modify: `chanlun/report_assets/report-v2.css`

**Scope:**
- Replace tokens with the light fintech dashboard system:
  - light blue/purple gradient background
  - glassy white cards
  - tokenized borders, shadows, radii, primary/purple/cyan/up/down/risk colors
- Restyle header market cards, index cards, tabs, candidate rows, rank badges, tag system, detail panel, and auxiliary decision cards.
- Add or refine styles for:
  - `.market-hero-row`
  - `.market-summary-strip`
  - `.market-summary-card`
  - `.summary-icon`
  - `.rank-badge`
  - `.candidate-identity`
  - `.candidate-price`
  - `.candidate-tags`
  - `.tag-*`
  - `.decision-icon`
  - `.market-temp-gauge`
  - responsive breakpoints at approximately 1180px and 760px
- Keep mobile detail drawer usable and keep candidate rows compact on mobile.

**Out of scope:**
- Do not edit JavaScript or tests.
- Do not touch `docs/assets` directly.
- Do not add decorative one-note purple domination; the page should read as white fintech dashboard with restrained blue/purple atmosphere.

**Verification:**
- CSS should keep all visible text fitting inside mobile and desktop containers.
- No new dependency, image, or font import.

## Main-Agent Integration

1. Review both worker diffs for spec compliance and code quality.
2. Resolve any class-name mismatch between JS and CSS.
3. Regenerate docs assets and report pages from current sample data if needed.
4. Run:
   - `node --check chanlun/report_assets/report-v2.js`
   - `python3 -m unittest tests.test_report_generator -v`
   - `python3 -m unittest tests.test_report_view_model tests.test_report_generator tests.test_requests_sessions tests.test_market_data_guard -v`
   - `python3 -m py_compile chanlun/report_generator.py chanlun/report_view_model.py`
   - `git diff --check`
5. Browser verify:
   - desktop: header, tabs, candidates, detail panel, auxiliary center
   - mobile: header stacks, tabs scroll, candidate tap opens drawer, auxiliary cards single-column
6. Commit with AGENTS format, no scope:
   - `feat: 优化日报视觉系统`
7. Push `taste-ui-design-system`.
