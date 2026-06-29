# Task 2: Header + Decision Center CSS

## Scope

Modify only:

- `chanlun/report_assets/report-v2.css`

Do not modify:

- `chanlun/report_assets/report-v2.js`
- `tests/*`
- `docs/assets/*`
- `docs/index.html`
- `docs/data/*`

## Goal

Style the optimized market header and auxiliary decision center while preserving the existing light trading-workspace direction.

## Visual Direction

Keep the current restrained light trading terminal:

- white / light gray surfaces
- blue primary accent
- A-share red for up
- green for down
- orange for risk
- 8px radius max for cards/tools
- no decorative blobs, gradients, or unrelated illustrations

The source landing plan gives CSS sketches, but you can tune spacing and density if it improves readability.

## Required Styles

Add or update styles for:

- `.market-header`
- `.market-regime-row`
- `.market-regime-card`
- `.market-label`
- `.market-value`
- `.market-note`
- `.market-index-grid`
- `.market-index-card`
- `.market-index-name`
- `.market-index-close`
- `.market-index-change`
- `.decision-center`
- `.decision-grid`
- `.decision-card`
- `.decision-card-head`
- `.status-badge`
- `.flow-chip`
- `.tag-chip`
- `.metric-pair-grid`
- `.metric-pair`
- `.decision-note`
- `.flow-columns`
- `.mini-section-title`
- `.flow-row`
- `.stock-signal-row`
- `.event-row`
- `.review-row`
- `.diagnostic-row`

## Responsive Requirements

- Under `980px`:
  - market regime cards stack or fit without overflow
  - market index cards become 3 columns
  - decision cards become 1 column
  - flow columns become 1 column
- Under `760px`:
  - market index cards become 2 columns
  - header text remains readable
  - workspace tabs remain horizontally scrollable
  - mobile detail drawer remains unaffected

## Verification

Run:

```bash
node --check chanlun/report_assets/report-v2.js
```

Return:

- Changed files.
- Notes on responsive choices.
- Any selectors that intentionally replace old `.metric-chip` behavior.
