# Chanlun UI Visual Direction 3 Task 2: CSS Visual System

## Ownership

You are the CSS worker. Use model `gpt-5.3-codex-spark`.

You are not alone in the codebase. Another worker may edit JS/tests only. Do not revert or overwrite unrelated edits. Your write scope is limited to:

- `chanlun/report_assets/report-v2.css`

Do not edit JavaScript, tests, generated `docs/assets`, or backend Python algorithms.

## Goal

Apply the visual direction 3 CSS system: white fintech dashboard, light blue/purple atmosphere, glassy white cards, strong hierarchy, rank badges, unified tags, risk colors, and responsive single-column mobile behavior.

## Requirements

1. Use the token family from `/Users/yangfan/Downloads/chanlun_ui_visual_direction_3_style_config.md`, adjusted only where needed for the existing UI.
2. Keep cards readable and utilitarian. Avoid a one-note purple page.
3. Preserve A-share colors: up red, down green, risk orange.
4. Keep text fitting inside candidate rows, tabs, cards, and mobile drawer.
5. Do not import fonts, dependencies, images, or icons.

## Implementation Tasks

1. Replace `:root` tokens with:
   - `--bg`, `--card`, `--card-soft`, `--card-glass`
   - `--text-main`, `--text-sub`, `--text-muted`
   - `--border`, `--border-soft`
   - `--primary`, `--primary-strong`, `--primary-soft`, `--primary-glow`
   - `--purple`, `--purple-soft`, `--cyan`, `--cyan-soft`
   - `--up-red`, `--up-red-soft`, `--down-green`, `--down-green-soft`
   - `--risk-orange`, `--risk-orange-soft`, `--warn-yellow`, `--warn-yellow-soft`
   - `--neutral-gray`, `--neutral-soft`
   - `--shadow-card`, `--shadow-float`, `--shadow-primary`
   - radius tokens
2. Restyle `body`, `.report-shell`, `.report-header`, `.market-*`, `.workspace`, `.workspace-tabs`, `.workspace-tab`.
3. Add/adjust candidate styles:
   - `.candidate-row` grid layout
   - `.rank-badge.rank-01`, `.rank-02`, `.rank-03`, `.rank-normal`
   - `.candidate-identity`, `.candidate-price`, `.candidate-tags`
   - `.tag`, `.tag-main`, `.tag-acceleration`, `.tag-luojie`, `.tag-confirming`, `.tag-baseline`, `.tag-resonance`, `.tag-action-*`, `.tag-risk`
4. Restyle `.detail-panel`, `.detail-price-grid`, `.price-cell`, `.chart-panel`.
5. Restyle auxiliary cards:
   - `.decision-grid`
   - `.decision-card`
   - `.decision-icon`
   - `.market-temp-gauge`
   - metric/flow/review/diagnostic rows
6. Add responsive rules:
   - at `max-width: 1180px`: header stacks, index 3 columns, workspace 1 column, decision grid 3 columns
   - at `max-width: 760px`: index 2 columns, summary cards 1 column, candidate rows compact, decision grid 1 column, mobile drawer remains readable

## Verification

Run if useful:

```bash
git diff -- chanlun/report_assets/report-v2.css
```

Return:

- Files changed
- Notes on responsive behavior
- Any class names you expect the JS worker to provide
