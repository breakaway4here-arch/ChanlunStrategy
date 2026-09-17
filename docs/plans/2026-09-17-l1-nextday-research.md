# L1 Next-Day Research Integration Plan

> **For Codex:** Implement in this isolated worktree with test-first changes. Parent independently reviews and accepts the diff.

**Goal:** Add a post-publish, research-only L1 shortlist and next-session outcome record without changing formal candidates, rankings, report validity, or notifications.

**Architecture:** Adapt only allowlisted system candidate pools from a successfully published report, validate the archived display workbench against that exact report for the B0 comparator, and pass normalized rows to the unchanged `L1_limit_sector` selector. Freeze each report date once; refresh older frozen outcomes from the canonical SQLite database in read-only mode and render JSON plus Markdown.

**Tech Stack:** Python 3.9 standard library, existing `chanlun.identity` and `chanlun.report_comparison._read_archived_workbench`, SQLite URI `mode=ro`, unittest.

---

## Scope and acceptance

- Candidate universe is the identity-deduplicated union of `picks_pure`, `picks_fusion`, `observation_watchlist`, `startup_watchlist`, `next_day_boom.candidates`, `luojie_pool.candidates`, `h4_t3_pool.candidates`, and existing `workspace.views`. Exclude holdings, personal watchlists, and market-wide hotspot lists.
- B0 uses the validated archived workbench's original highlights in `view_rank` order; raw workspace highlights are empty on the first live fixture. A missing or mismatched archived workbench is `not_evaluated`, never an empty-success comparator.
- L1 requires an explicit complete same-day limit-up snapshot. Industry counts deduplicate identities across the full snapshot; partial or conflicting snapshots are `not_evaluated/input_insufficient`.
- Keep the package's exact qualification and ranking semantics, five-item cap, no fillers. Preserve source-pool labels and any recorded risk or pending-condition fields on each candidate.
- Freeze selected identities and normalized inputs before outcome reads. An identical rerun is idempotent; a changed report/source hash writes a conflict record and cannot replace the frozen shortlist.
- Outcome refresh is limited to prior frozen report dates and the explicit completed report date passed by the caller. It reads the existing canonical market SQLite only; missing bars, immature horizons, unknown price basis, calendar gaps, and identity ambiguity remain separate statuses.
- The daily hook runs once after the shared successful publish path, has a 60-second bound, and cannot change the report's success/failure result.
- Impact: B02, B03, B04, B06, B07, B09, B10. B01/B05/B08 and formal selection behavior are not changed; G22 recall expansion and H4 adaptation remain out of scope.

## Files

- `chanlun/nextday_candidates.py`: unchanged vendor selector.
- `chanlun/nextday_research.py`: allowlisted normalization, snapshot validation, freeze/conflict persistence, report rendering, and outcome integration.
- `chanlun/nextday_outcomes.py`: independently implemented read-only horizon evaluator.
- `scripts/nextday_research.py`: explicit-date CLI.
- `scripts/nextday_research_hook.py`: bounded optional subprocess wrapper.
- `daily_run.sh`: one hook call after successful publish.
- `tests/test_nextday_research.py`, `tests/test_nextday_outcomes.py`, `tests/test_daily_run_script.py`: fixed-input parity, scope/identity/snapshot/freeze/outcome/hook checks.
- `research/nextday-strength-v0/`: source package, fixed historical fixtures, reproduction command, and ignored runtime `runs/` outputs.

## Work sequence

1. Preserve the study package and add failing tests for 25-day L1 identity/order parity, report pool union, B0 workbench rank order, full-snapshot industry counts, incomplete-input status, and frozen reruns.
2. Implement the report adapter and storage contract; run the focused tests on Python 3.9 and the repository test runner.
3. Add outcome status integration and a bounded optional hook; test outcome timing/price-basis separation and report-success isolation.
4. Run the original study reproducer on the checked-in fixtures, run focused and existing daily/report tests, inspect diffs, and record hashes and limits here before parent acceptance.

## Historical package

The input package is `nextday-strength-exploration-v0`; its 25 signal dates end on 2026-09-15. The 2026-09-17 shortlist is prospective and is not included in that historical performance. No fees, slippage, queue position, intraday fill, or realized-profit simulation is added. The package's favorable recent segment, weaker earlier segment, and opening-path caveats remain part of the saved study conclusion.

## Delivery record

Implementation agents work only in the isolated tree; the parent owns independent acceptance, commits, and deployment. This batch never rewrites production reports or the market database and never sends notifications.

### Confirmed execution scope

- User confirmed `gpt-5.6-sol / xhigh` for implementation; parent retains the current model and reasoning configuration. These settings apply to this task only.
- Actual baseline: `48ef940a4f64ba1ab21bbdd9c0460677ce6ebad8`, completed report `2026-09-17`, funnel run `20260917-aa5eaa7b7a0d`.
- Parent independently derived the 36-security universe, 47-row complete limit snapshot, 13-security intersection, and five-item L1 order before implementation. Actual published B0 has only three entries and remains three; nothing is filled to five.
- A same-day insufficient-input attempt can advance to its first valid freeze. An evaluated empty result or nonempty shortlist stays immutable; subsequent source changes create conflict evidence.
- Cross-date `qfq` labels alone do not prove a common price basis. Unverified cross-date paths stay unavailable; within-bar open-to-close remains independently calculable. All paths exclude execution/fee/slippage simulation.
- H4 is not repaired by this batch. Its independent read-only adapter review found missing right-side health enrichment and an unseen source/category distribution in the frozen model; no source renaming, model prediction/training, threshold change, or production activation is included.

### Parent acceptance before release

- The parent ran 79 tests across the adapter, read-only outcomes, post-publish hook, existing daily script, report comparison, and formal publish guard: all passed. Shell syntax and whitespace checks passed.
- The checked-in original package reproduced all 25 signal dates, 2,504 rows, and 10 methods; all three principal output files match the package results. The vendored selector matches the original script byte for byte. This is historical reproduction, not a new independent effect estimate.
- The actual 2026-09-17 CLI produced L1 in order: SH600609 金杯汽车 (8/1/10:58), SH603960 克来机电 (8/1/14:17), SZ003026 中晶科技 (2/3/09:25), SH603248 锡华科技 (2/3/14:02), SZ000504 南华生物 (2/1/10:02). The tuple is industry limit-up count / consecutive boards / first seal time. All retain their original observation risks and confirmation conditions.
- B0 retains the published order: SZ301075 多瑞医药, SH603960 克来机电, SH688521 芯原股份. Archived B0 entries cannot add identities to the L1 report-pool universe. The sole overlap is SH603960.
- A second actual CLI run kept the frozen selection bytes unchanged. The read-only evaluator returned five valid/pending L1 rows and three valid/pending B0 rows, zero missing prices, and no observed future return. Target dates are 2026-09-18, 2026-09-21, and 2026-09-22.
- Negative checks cover identity alias conflicts and valid partial identity fields, missing/partial/wrong-date snapshots, duplicate snapshot coverage, genuine empty input, immutable selection, initially insufficient input becoming valid, nonfinal/missing prices, calendar boundaries, and optional hook failures/timeouts.
- Eleven protected runtime files (including current report JSON/HTML, strategy, H4 model and frontend assets) remain byte-identical. The canonical SQLite inode/size/mtime are unchanged. Existing runtime changes to `docs/2026-09-08/index.html` and `docs/compare/index.html` are outside this release and must be preserved.

### Runtime handoff

`daily_run.sh` invokes the optional wrapper once after a successful publish, including its already-generated-report path. The wrapper enforces 60 seconds, preserves normal publish exit status, and records its own status separately. Actual runtime `.cache/chanlun` resolves to the shared repository cache, so default output is the existing repository's `research/nextday-strength-v0/runs/`, outside the runtime checkout. A `runs/` ignore rule also protects a direct-checkout deployment from dirty runtime outputs.

Per-date `selection.json` is the immutable signal record; `outcomes.json` and `shortlist.md` refresh after it. `summary.json` indexes saved dates rather than mixing prospective dates into the explored historical sample. Run failures use `last_hook_status.json` and never change formal recommendations, database contents, or notifications.

Deploy only these code/docs/fixture files by fast-forwarding the runtime checkout after source validation. Invoke the research wrapper directly for the existing completed report; do not invoke `daily_run.sh`, `run.py`, report regeneration, or notifications for acceptance. A future natural scheduled invocation is distinct from this direct wrapper acceptance.
