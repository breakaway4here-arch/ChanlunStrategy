# 2026-09-12 UI layout implementation record

## Scope

This isolated worktree implements the second M3 batch for U06, U07, U08, U09,
U10, and U12 in `chanlun/report_assets/report-v2.js` and
`chanlun/report_assets/report-v2.css`, with focused frontend contract tests.
The work is presentation-only: it does not change strategy inputs, formal
ranking, prices, Python code, report fixtures, or save behavior.

The page keeps the existing blue/white visual system and the existing chart
renderer. The public changes are the reading order and anchors, compact
candidate rows, the short judgment/evidence jump path, mobile chart/detail
layout, compact personal watchlist, and explicit sector-filter feedback.

## Interfaces reserved for the review batch

The shell exposes `#reportChanges` after the supporting factual cards. The
review batch may mount U11/U13/U15 content there without changing the
candidate, chart, or changes data model in this worktree.

## U-specific correction rounds

The earlier record called five workflow steps “rounds”. That was accounting
for implementation steps, not five substantive corrections to every problem.
The actual substantive correction count for this batch is:

| U | Substantive corrections | Current result |
|---|---:|---|
| U06 | 4 | Initial short-judgment/evidence path, frequency-mismatch labeling/evidence order review, then mobile order and chart-date locator correction |
| U07 | 2 | Initial summary/anchor implementation, then legacy capability and unknown-count correction |
| U08 | 2 | Compact three-line candidate row and identity mapping, then real viewport density and visible shared market-context correction |
| U09 | 2 | Mobile toolbar/status layout and overflow protection, then mobile detail order correction |
| U10 | 1 | Compact selected watchlist details and explicit missing-analysis state |
| U12 | 1 | Sector selection feedback and original/matched pool counts |
| U16 | 1 | Description-list semantics, status group role, and auxiliary text readability correction |

The earlier review turn was the second substantive U07 correction. The later
targeted corrections are recorded below; no U subproblem has reached the
five-correction limit. A browser-only issue that cannot be
reproduced from fixed local assets remains an explicit visual follow-up rather
than being hidden by weakening a contract.

The initial implementation and the first review were already committed in
`46766c10`; this follow-up must be a new commit and must not amend that commit.

Second-review verification: 247 focused frontend tests pass, including the
unknown legacy-capability count, same-stock main/H4 deduplication, and the
summary → full-market-evidence → candidate shell-order contract.

The deterministic Playwright runner was attempted against the fixed browser
fixture. The host Chrome process aborted before creating a page (`SIGABRT`/
`EPERM` while Playwright closed the process), so no browser screenshot claim is
made from this worktree. The source-level contracts and the existing 242-test
frontend regression remain the verified evidence; the parent process can rerun
the browser acceptance on its working host.

## Boundaries

This batch remains within B01-B10: no historical expansion, no formal strategy
or price changes, no production writes, no notification sends, and no server
startup. Original bootstrap bytes and generated assets remain outside the
change set.

## 2026-09-12 targeted browser acceptance corrections after 37bff86e

This follow-up is limited to the observed U06, U08, and U16 defects. It does
not change strategy inputs, ranking, prices, chart data, chart calculations,
rendering algorithms, save behavior, or generated `docs/assets` copies. It
does correct the evidence-jump event's date lookup.

- **U08 density root cause and result:** the real 1440/390 browser measurement
  in `/private/tmp/chanlun-ui-final-20260912/review-browser/review.json` showed
  187.656px desktop rows and 215.031–233.875px mobile rows. The extra
  `.candidate-row-statuses` block accounted for about 49px, while the mobile
  two-column market rule added a second market line. The row now has three
  reading lines, the common date/price-basis/non-real-time fact is visible once
  above the list, exceptions retain their own visible metadata, and all risk
  flags plus missing-evidence state remain readable. A real browser rerun on
  the fixed report measured 105.6875px for all ten checked rows at both 1440
  and 390 widths; long risk text remains allowed to grow naturally.
- **U06 locator root cause and result:** evidence jumps previously indexed
  `state.data.dates`, which is not the mounted candidate chart's date series.
  The locator now reads the mounted chart x-axis, dispatches only an exact
  date match, rejects stale detail roots, leaves missing/unmatched dates
  unlocated, and maps `historical-validation`/`simulation-tracking` to the
  existing history evidence ancestors. The browser click check located the
  dated `2026-09-11` signal and marked one evidence target; the negative
  stale-date case dispatched no action.
- **U16 result:** fact rows now keep legal `dl`/`dt`/`dd` structure with a
  button as the one-step evidence jump; the four-state detail summary uses a
  named `group`; missing evidence and ecology auxiliary text use readable
  colors and at least 12px text. Full axe scans of the current local report at
  1440 home, 390 home, and 390 detail reported no violations. The existing M4
  comparison implementation remains outside this correction.

Focused unit and Node contracts are required before this follow-up is
committed; the real-browser measurements above are the density acceptance
evidence rather than a CSS-only estimate.
