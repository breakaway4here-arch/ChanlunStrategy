# Auxiliary Decision Copilot Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rebuild the auxiliary decision area into an evidence-linked decision cockpit with reliable limit-up data, a persistent personal watchlist, grounded LLM analysis, real-position-only risk alerts, and attributable strategy reviews.

**Architecture:** Deterministic code owns market facts, data status, recommendation provenance, return calculations, and hard action gates. The LLM receives only structured facts with evidence IDs and returns validated event arbitration, direction clusters, watchlist relationships, and conditional explanations. The static report embeds an immutable analysis snapshot; the existing Cloudflare Worker later manages versioned watchlist configuration without mutating the current report snapshot.

**Tech Stack:** Python 3, `unittest`, plain JavaScript/CSS, existing report generator, JSON fixtures, Cloudflare Worker KV, Node test runner.

---

### Task 1: Fix limit-up parsing and introduce an auditable snapshot contract

**Files:**
- Create: `tests/fixtures/limit_up_pool_int_fbt.json`
- Create: `chanlun/auxiliary_decision.py`
- Modify: `chanlun/data_fetcher.py`
- Modify: `run.py`
- Modify: `daily_run.sh`
- Create: `scripts/finalize_recommendation_ledger.py`
- Modify: `chanlun/report_generator.py`
- Test: `tests/test_data_fetcher.py`
- Test: `tests/test_auxiliary_decision.py`
- Test: `tests/test_report_generator.py`

**Step 1: Write a failing parser test**

Add a captured minimal fixture whose `fbt` is the integer `92500`. Assert that `fetch_limit_up_pool()` preserves the row and formats `first_time` as `09:25`.

**Step 2: Run the parser test and verify RED**

Run: `python3 -m unittest tests.test_data_fetcher -v`

Expected: FAIL because `_fmt_btime()` calls `len()` on an integer and the item is silently dropped.

**Step 3: Implement the minimal parser fix**

Normalize the value to digits, left-pad to six characters, validate `HHmmss`, and return an empty value only for invalid input. Record per-row parse failures rather than dropping them without status.

**Step 4: Write failing snapshot-contract tests**

Cover:

- `verified_complete`
- `verified_empty`
- `partial`
- `missing`
- `error`
- `raw_total`, `parsed_count`, `parse_error_count`, `coverage`
- date mismatch
- total larger than fetched page

**Step 5: Run snapshot tests and verify RED**

Run: `python3 -m unittest tests.test_auxiliary_decision -v`

Expected: FAIL because `build_limit_up_snapshot()` does not exist.

**Step 6: Implement `build_limit_up_snapshot()`**

Keep it deterministic. Do not infer “zero涨停” from an empty item list unless total is verified zero. Preserve `as_of`, `generated_at`, source and error details.

**Step 7: Wire the snapshot into report data**

Keep legacy `limit_up_pool` temporarily for compatibility, but make `limit_up_snapshot` the authoritative auxiliary contract.

**Step 8: Verify GREEN**

Run:

```bash
python3 -m unittest tests.test_data_fetcher tests.test_auxiliary_decision tests.test_report_generator -v
python3 -m py_compile chanlun/data_fetcher.py chanlun/auxiliary_decision.py run.py chanlun/report_generator.py
```

Expected: PASS.

**Step 9: Commit**

```bash
git add chanlun/data_fetcher.py chanlun/auxiliary_decision.py run.py chanlun/report_generator.py tests/test_data_fetcher.py tests/test_auxiliary_decision.py tests/test_report_generator.py tests/fixtures/limit_up_pool_int_fbt.json
git commit -m "fix: 修复涨停池解析并增加状态合同"
```

### Task 2: Add the canonical personal watchlist and immutable daily facts

**Files:**
- Create: `config/decision_watchlist.json`
- Create: `chanlun/personal_watchlist.py`
- Modify: `run.py`
- Modify: `chanlun/report_generator.py`
- Test: `tests/test_personal_watchlist.py`
- Test: `tests/test_report_generator.py`

**Step 1: Write failing configuration tests**

Assert that the loader:

- validates five initial codes
- derives names from the local stock-name mapping
- sorts by priority
- rejects duplicate/invalid codes and unsupported roles
- exposes schema version and revision

**Step 2: Run and verify RED**

Run: `python3 -m unittest tests.test_personal_watchlist -v`

Expected: FAIL because the module and canonical config do not exist.

**Step 3: Implement the loader and canonical config**

Initial strong-watch codes: `300139`, `002281`, `300308`, `688041`, `688525`. Keep user thesis distinct from generated analysis.

**Step 4: Write failing fact-snapshot tests**

Test fresh, stale, missing and newly-added cases. The snapshot must not emit price levels when current evidence is stale or missing.

**Step 5: Implement watchlist fact snapshots**

Reuse existing daily K-line, sector, decision-engine and candidate data. Store evidence IDs, current/previous facts and candidate-pool intersections. Do not add LLM text yet.

**Step 6: Wire snapshot into report JSON**

Add `personal_watchlist` with `config_revision`, `analysis_revision`, `as_of`, `items` and status.

**Step 7: Verify GREEN**

Run:

```bash
python3 -m unittest tests.test_personal_watchlist tests.test_report_generator -v
python3 -m py_compile chanlun/personal_watchlist.py run.py chanlun/report_generator.py
```

Expected: PASS.

**Step 8: Commit**

```bash
git add config/decision_watchlist.json chanlun/personal_watchlist.py run.py chanlun/report_generator.py tests/test_personal_watchlist.py tests/test_report_generator.py
git commit -m "feat: 增加个人重点观察池快照"
```

### Task 3: Build grounded event arbitration and direction clusters

**Files:**
- Modify: `chanlun/auxiliary_decision.py`
- Modify: `chanlun/market_news.py`
- Modify: `run.py`
- Modify: `chanlun/report_generator.py`
- Test: `tests/test_auxiliary_decision.py`
- Test: `tests/test_market_news.py`
- Test: `tests/test_report_generator.py`

**Step 1: Write failing deterministic relationship tests**

Use frozen 2026-08-20 event fragments. Assert that:

- the overseas optical-communication event links to 中际旭创 via an evidence-backed `watchlist_intersection`
- a recap classified `no_impact` is not a top catalyst
- stock links include `link_type` and `evidence_ref`
- a risk direction can coexist with positive directions
- no direction is fabricated merely to reach three rows

**Step 2: Run and verify RED**

Run: `python3 -m unittest tests.test_auxiliary_decision -v`

Expected: FAIL because relationship and arbitration functions do not exist.

**Step 3: Implement deterministic facts and evidence registry**

Build stable evidence IDs for events, sector flows, limit-up groups, candidates and watchlist items. Compute allowed stock roles from facts rather than LLM labels.

**Step 4: Write failing LLM schema and arbitration tests**

Cover enum validation, missing evidence references, invalid stock names/codes, rule/LLM conflict, LLM failure and explicit fallback.

**Step 5: Implement provider-neutral LLM analysis**

Pass structured facts only. Persist `model`, `prompt_version`, `schema_version`, rule result, LLM result and arbitration reason. Never trust model-provided numeric values.

**Step 6: Wire `decision_brief` into report data**

The report must still contain deterministic direction clusters when the LLM is unavailable.

**Step 7: Verify GREEN**

Run:

```bash
python3 -m unittest tests.test_auxiliary_decision tests.test_market_news tests.test_report_generator -v
python3 -m py_compile chanlun/auxiliary_decision.py chanlun/market_news.py run.py chanlun/report_generator.py
```

Expected: PASS.

**Step 8: Commit**

```bash
git add chanlun/auxiliary_decision.py chanlun/market_news.py run.py chanlun/report_generator.py tests/test_auxiliary_decision.py tests/test_market_news.py tests/test_report_generator.py
git commit -m "feat: 增加事件仲裁与方向证据链"
```

### Task 4: Rebuild the auxiliary frontend around scan-first evidence chains

**Files:**
- Modify: `chanlun/report_assets/report-v2.js`
- Modify: `chanlun/report_assets/report-v2.css`
- Modify: `tests/test_report_generator.py`
- Create: `tests/test_auxiliary_frontend.py`

**Step 1: Write failing frontend contract tests**

Assert that the source contains renderers for:

- limit-up ecology status
- direction evidence tracks
- five-item personal watchlist
- conditional holding-risk section
- strategy scorecards

Also assert that the old global “卖出提醒” and unbounded recent-review mapping are no longer the primary render path.

**Step 2: Run and verify RED**

Run: `python3 -m unittest tests.test_auxiliary_frontend tests.test_report_generator -v`

Expected: FAIL because the new renderers do not exist.

**Step 3: Implement the Swiss visual system**

Use white/cold-grey surfaces, one blue accent, thin rules, left alignment and a visible evidence-chain track. Keep semantic red/green only for market outcomes; add text labels for risk and missing states.

**Step 4: Implement scan-first rendering**

Render at most three direction summaries and all enabled watchlist items. Allow one expanded detail at a time. On mobile, transform the horizontal evidence track into vertical steps without page overflow.

**Step 5: Implement honest empty/error states**

Differentiate verified empty, partial, missing, LLM failure, stale watch data and no configured positions.

**Step 6: Verify GREEN**

Run:

```bash
node --check chanlun/report_assets/report-v2.js
python3 -m unittest tests.test_auxiliary_frontend tests.test_report_generator -v
```

Expected: PASS.

**Step 7: Commit**

```bash
git add chanlun/report_assets/report-v2.js chanlun/report_assets/report-v2.css tests/test_auxiliary_frontend.py tests/test_report_generator.py
git commit -m "feat: 重构辅助决策驾驶舱界面"
```

### Task 5: Restrict holding-risk actions to fresh confirmed positions

**Files:**
- Create: `chanlun/position_book.py`
- Modify: `run.py`
- Modify: `chanlun/report_generator.py`
- Modify: `chanlun/report_assets/report-v2.js`
- Test: `tests/test_position_book.py`
- Test: `tests/test_report_generator.py`

**Step 1: Write failing position freshness tests**

Cover no positions, stale positions, unconfirmed positions, fresh confirmed positions and a non-held global sell signal.

**Step 2: Run and verify RED**

Run: `python3 -m unittest tests.test_position_book -v`

Expected: FAIL because no position contract/intersection exists.

**Step 3: Implement the position book and intersection**

Require source, as-of, confirmation and stale-after metadata. Preserve global sell signals for research/diagnostics, but emit `holding_risks` only for the valid intersection.

**Step 4: Hide user-facing actions when no confirmed position exists**

Do not render a placeholder sell card. Show configuration state only in the management/diagnostic area.

**Step 5: Verify GREEN**

Run:

```bash
python3 -m unittest tests.test_position_book tests.test_report_generator -v
node --check chanlun/report_assets/report-v2.js
```

Expected: PASS.

**Step 6: Commit**

```bash
git add chanlun/position_book.py run.py chanlun/report_generator.py chanlun/report_assets/report-v2.js tests/test_position_book.py tests/test_report_generator.py
git commit -m "fix: 卖出提醒仅关联确认持仓"
```

### Task 6: Add the immutable recommendation ledger and strategy scorecards

**Files:**
- Create: `chanlun/recommendation_ledger.py`
- Create: `chanlun/strategy_review.py`
- Modify: `run.py`
- Modify: `chanlun/report_generator.py`
- Modify: `chanlun/report_assets/report-v2.js`
- Test: `tests/test_recommendation_ledger.py`
- Test: `tests/test_strategy_review.py`
- Test: `tests/test_report_generator.py`

**Step 1: Write failing recommendation-ledger tests**

Assert stable recommendation IDs, multiple strategy contributions, immutable reason snapshots, policy/config/code versions, and legacy unknown handling.

**Step 2: Run and verify RED**

Run: `python3 -m unittest tests.test_recommendation_ledger -v`

Expected: FAIL because the ledger does not exist.

**Step 3: Implement ledger creation and persistence**

Build a provisional batch at report generation time, but only for official non-preview runs. Finalize it into immutable history after `validate_today_report.py` succeeds; debug, preview and failed validation must never claim the day's stable IDs. Do not infer precise strategy versions, entry modes or intended horizons; mark them `unknown`.

**Step 4: Lock return-experiment semantics in failing tests**

Cover adjusted prices, explicit finality, an authoritative trading calendar, executable entry, per-horizon maturity, suspended/limit-up-locked states, benchmark-date alignment, right censoring, episode dedupe and cross-strategy attribution. A missing stock bar must not shift D+1 forward.

**Step 5: Implement deterministic scorecards**

Expose only actually published user recommendations as the performance cohort. Internal observation gates and published watch/none actions remain separate from returns even if an internal decision is `recommend`. Show T+1/T+3/T+5 together unless a strategy declares its intended horizon, and include mean, median, win rate, excess return, MAE/MFE and an explicit low-sample state.

**Step 6: Replace unbounded recent reviews in the UI**

Default to strategy scorecards and allow drill-down to recommendation entries and representative samples.

**Step 7: Verify GREEN**

Run:

```bash
python3 -m unittest tests.test_recommendation_ledger tests.test_strategy_review tests.test_report_generator -v
python3 -m py_compile chanlun/recommendation_ledger.py chanlun/strategy_review.py run.py chanlun/report_generator.py
node --check chanlun/report_assets/report-v2.js
```

Expected: PASS.

**Step 8: Commit**

```bash
git add chanlun/recommendation_ledger.py chanlun/strategy_review.py run.py chanlun/report_generator.py chanlun/report_assets/report-v2.js tests/test_recommendation_ledger.py tests/test_strategy_review.py tests/test_report_generator.py
git commit -m "feat: 增加推荐账本与策略归因回看"
```

### Task 7: Add versioned watchlist management to the existing Worker

**Files:**
- Modify: `cloudflare/top10-worker/src/index.js`
- Modify: `cloudflare/top10-worker/test/top10-worker.test.js`
- Modify: `chanlun/report_assets/report-v2.js`
- Modify: `chanlun/report_assets/report-v2.css`
- Test: `tests/test_auxiliary_frontend.py`

**Step 1: Write failing Worker API tests**

Cover GET revision, authenticated PUT, invalid code/role, maximum size, CORS, missing/incorrect ETag, revision conflict and audit record creation.

**Step 2: Run and verify RED**

Run: `node --test cloudflare/top10-worker/test/top10-worker.test.js`

Expected: FAIL because watchlist routes do not exist.

**Step 3: Implement Worker-side configuration routes**

Keep write secrets server-side. Do not embed credentials in static JavaScript. Return revision/ETag and require optimistic locking for updates.

**Step 4: Write failing management UI tests**

Cover add/remove/reorder/enable, revision conflict, save failure and “等待下次日报分析” state.

**Step 5: Implement the management UI**

Keep live configuration distinct from the embedded analysis snapshot. A save must not mutate or relabel the current analysis.

**Step 6: Verify GREEN**

Run:

```bash
node --test cloudflare/top10-worker/test/top10-worker.test.js
node --check chanlun/report_assets/report-v2.js
python3 -m unittest tests.test_auxiliary_frontend -v
```

Expected: PASS.

**Step 7: Commit**

```bash
git add cloudflare/top10-worker/src/index.js cloudflare/top10-worker/test/top10-worker.test.js chanlun/report_assets/report-v2.js chanlun/report_assets/report-v2.css tests/test_auxiliary_frontend.py
git commit -m "feat: 增加重点观察池页面管理"
```

### Task 8: Generate and visually verify the real report

**Files:**
- Modify via generator: `docs/assets/report-v2.js`
- Modify via generator: `docs/assets/report-v2.css`
- Modify via generator: `docs/index.html`
- Modify via generator: `docs/data/<current-date>.json`
- Modify via generator: `docs/<current-date>/index.html`

**Step 1: Run the complete targeted regression suite**

Run:

```bash
python3 -m unittest tests.test_data_fetcher tests.test_auxiliary_decision tests.test_personal_watchlist tests.test_position_book tests.test_recommendation_ledger tests.test_strategy_review tests.test_market_news tests.test_report_generator tests.test_report_view_model -v
node --test cloudflare/top10-worker/test/top10-worker.test.js
node --check chanlun/report_assets/report-v2.js
git diff --check
```

Expected: PASS with zero failures.

**Step 2: Generate the current report**

Use the repository's official daily generation command and keep generated dates/status truthful. Do not overwrite the frozen 2026-08-20 snapshot with a reconstruction.

**Step 3: Run contract validation**

Run the existing report validator against the generated report. Confirm root and archive resource paths separately.

**Step 4: Perform desktop visual QA**

Verify:

- evidence chain readability
- at most three direction summaries
- all five watchlist stocks
- honest limit-up status
- no false sell actions
- strategy scorecard and drill-down

**Step 5: Perform mobile visual QA**

Verify 390px width, no page overflow, one detail expanded at a time, long-text wrapping and usable management controls.

**Step 6: Capture failure-state screenshots**

Capture partial limit-up data, LLM failure, stale watchlist facts and no-position states.

**Step 7: Final review with the independent reviewer**

Provide the reviewer with the final diff, tests and screenshots. Resolve all must-fix findings before release.

**Step 8: Synchronize target branch and rerun tests before final commit**

Fetch and merge the latest `origin/main`, confirm it is an ancestor, then rerun the full verification matrix. Do not mix unrelated changes.

**Step 9: Commit generated artifacts only after validation**

```bash
git add docs/assets/report-v2.js docs/assets/report-v2.css docs/index.html docs/data/<current-date>.json docs/<current-date>/index.html
git commit -m "chore: 更新辅助决策驾驶舱日报"
```
