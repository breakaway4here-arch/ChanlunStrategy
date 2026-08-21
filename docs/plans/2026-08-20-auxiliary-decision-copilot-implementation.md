# Auxiliary Decision Copilot Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rebuild the auxiliary decision area into an evidence-linked decision cockpit with reliable limit-up data, a persistent personal watchlist, grounded LLM analysis, real-position-only risk alerts, and attributable strategy reviews.

**Architecture:** Deterministic code owns market facts, data status, recommendation provenance, return calculations, and hard action gates. The LLM receives only structured facts with evidence IDs and returns validated event arbitration, direction clusters, watchlist relationships, and conditional explanations. The static report embeds an immutable analysis snapshot; the existing Cloudflare Worker fronts a single SQLite-backed Durable Object that transactionally stores current configuration, full revision snapshots and audit history without mutating the current report snapshot. Workers KV is not used for watchlist version locking because it has no atomic compare-and-swap contract.

**Tech Stack:** Python 3, `unittest`, plain JavaScript/CSS, existing report generator, JSON fixtures, Cloudflare Worker, SQLite-backed Durable Object, Node test runner.

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
- Modify: `chanlun/personal_watchlist.py`
- Modify: `run.py`
- Modify: `cloudflare/top10-worker/src/index.js`
- Modify: `cloudflare/top10-worker/test/top10-worker.test.js`
- Modify: `chanlun/report_assets/report-v2.js`
- Modify: `chanlun/report_assets/report-v2.css`
- Modify: `docs/plans/2026-08-20-auxiliary-decision-copilot-design.md`
- Test: `tests/test_personal_watchlist.py`
- Test: `tests/test_auxiliary_frontend.py`

**Step 1: Write failing Worker API tests**

Cover GET revision, authenticated PUT, invalid code/role, maximum size, CORS, missing/incorrect ETag, revision conflict and audit record creation.

**Step 2: Run and verify RED**

Run: `node --test cloudflare/top10-worker/test/top10-worker.test.js`

Expected: FAIL because watchlist routes do not exist.

**Step 3: Implement Worker-side configuration routes**

Keep write secrets server-side. Do not embed credentials in static JavaScript. Return revision/ETag and require optimistic locking for updates. Store current, complete immutable revision snapshots, and audits inside one Durable Object transaction so concurrent requests with the same ETag cannot both succeed.

**Step 4: Write failing management UI tests**

Cover add/remove/reorder/enable, revision conflict, save failure and “等待下次日报分析” state.

**Step 5: Implement the management UI**

Keep live configuration distinct from the embedded analysis snapshot. A save must not mutate or relabel the current analysis.

**Step 6: Verify GREEN**

Make the next report resolve the same Worker revision saved by the page. A valid remote version replaces the local bootstrap as a whole; a transport or schema failure must fall back with explicit `data_quality` diagnostics.

Run:

```bash
node --test cloudflare/top10-worker/test/top10-worker.test.js
node --check chanlun/report_assets/report-v2.js
python3 -m unittest tests.test_personal_watchlist tests.test_auxiliary_frontend -v
```

Expected: PASS.

**Deployment preflight and live acceptance**

Before deploying from `cloudflare/top10-worker`, configure the write secret with `npx wrangler secret put WATCHLIST_ADMIN_PASSWORD`; never store its value in the repository. The committed Durable Object migration in `wrangler.jsonc` must be applied by the Worker deployment.

After deployment, acceptance is not complete until a real page operation proves the full revision chain:

1. Page GET returns revision `R0` and ETag `R0`.
2. Authenticated page PUT with `If-Match: R0` returns revision `R1`.
3. Worker GET returns the exact full `R1` configuration.
4. The next non-debug report records `data_quality.personal_watchlist_config.revision=R1` and `personal_watchlist.config_revision=R1`.
5. A concurrent or stale PUT using `R0` returns 412 and does not create a second winner.

**Step 7: Commit**

```bash
git add chanlun/personal_watchlist.py run.py cloudflare/top10-worker/src/index.js cloudflare/top10-worker/test/top10-worker.test.js chanlun/report_assets/report-v2.js chanlun/report_assets/report-v2.css docs/plans/2026-08-20-auxiliary-decision-copilot-design.md docs/plans/2026-08-20-auxiliary-decision-copilot-implementation.md tests/test_personal_watchlist.py tests/test_auxiliary_frontend.py
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

## 2026-08-21 本地验收记录

本轮只生成 `output_debug/` 预览，不覆盖或提交正式日报快照。完整 `--debug` 主流程（非正式全 A 日报）运行退出码为 0，并完成以下用户可见验收：

- 涨停生态为 `verified_complete`，原始 45 条、成功解析 45 条、覆盖率 100%。
- 重点观察池版本为 `watchlist-20260820-01`；晓程科技、光迅科技、中际旭创、海光信息、佰维存储 5/5 均有当日事实。
- 事件 LLM 10 条全部成功；终局方向为 `status=ok`、模型 `deepseek-v4-pro`、提示词 `decision-brief-v3`。
- 终局方向输出光伏风险、半导体偏多、消费电子偏多三条证据链；半导体方向明确关联晓程科技和佰维存储，并同时展示下一确认与失效条件。
- 未配置已确认持仓时，`holding_risks=0`，页面不生成卖出动作。
- 报告合同与运行切换校验均为 0 错误；根页面、当日 JSON、归档页面均返回 HTTP 200。
- 桌面 DOM 可读性检查通过；390px 移动端根页面无横向溢出，五只观察股和三条方向均可访问，浏览器控制台无错误。
- Python 全量测试 1083 项通过；Worker 测试、前端 JavaScript 语法、Python 编译与 `git diff --check` 均通过。

完整 debug 运行还暴露并修复了两项稳定性问题：推荐账本处理 NumPy 向量时先调用 `item()` 导致崩溃；推理模型在完成预算不足时可能返回空正文或非空但截断的 JSON。现在账本先转换数组，事件与终局分析分别获得受控预算，终局 LLM 只接收实际方向引用的证据；空正文和截断 JSON 都会重试并记录 `finish_reason` 与正文长度等诊断。

线上验收仍保留为独立发布门槛：本轮未部署 Worker、未配置线上写入 secret，也未执行 `R0 -> PUT R1 -> GET R1 -> 下一份正式日报读取 R1` 的完整链路，因此不得把本地管理页面验收描述成线上已生效。

## 2026-08-21 高收益选股优化与本地验收

### 已落地范围

- `picks_pure` 固定为“基础候选”共同上游全集；候选合并保留 `strategy_sources`，不再用最后一次写入覆盖策略归因。
- `picks_fusion` 只有最终 `decision_code=recommend` 才进入“主推”；允许空池、不限数量、不回填。
- 强势启动、趋势延续、H4 T+3、加速和罗姐池保持各自门控。加速、罗姐池、等确认、基础候选及跨池看点均被页面动作上限收紧为“观察/仅观察”，同时保留原始决策字段供审计。
- `next_day_boom` 和 `luojie_pool` 同时在候选状态、运行时策略输入和推荐账本三层固定为 `observe/internal/watch`；即使通用决策意外给出 `recommend`，也不能进入正式推荐 cohort。
- 多来源不再产生共振加分或绕过门控；各来源候选先分别执行自己的 fusion admission，再按股票代码聚合，结果不再依赖输入顺序。
- 新高收益周期合同固定处于 `shadow`：缺失或冲突的 `intended_horizon` 不能成为高收益主推，但在没有 OOT 胜者前不会清空现网旧主推；页面明确标为“现网旧口径（周期未验）”。本版本拒绝 `active` 启动，避免行内自填周期绕过运行时 OOT cutover proof。
- 推荐账本和策略回看按信号日收盘入场，计算 T+1/T+3/T+5 未来收盘收益以及各周期 D+1 到 D+N 的 MFE/MAE。
- 增加高收益版本 scorecard 和晋级器：同切片比较、均值主排序、中位数/5% 命中率防极端样本、生产/影子样本门槛、无 Top K 数量上限。
- 风险方向增加独立、可溯源的 `risk_reasons(reason, impact, evidence_refs)`，页面单独展示；风险成立但没有具体原因时降级。

### 历史证据与发布判定

本轮在 63 个历史快照日上运行现有策略回放，共看到 7940 条候选。对可评估的 6134 条基线样本，T+3 平均收益为 -0.80%、中位数 -1.32%、胜率 39.8%；改成“信号日收盘价立即入场”并应用当前质量门后有 5708 条，T+3 平均收益 -1.34%、中位数 -1.86%、胜率 36.1%，平均收益下降 0.54 个百分点，胜率下降 3.7 个百分点。因此该口径是研究合同修正，不是收益已提升的证据。

融合阈值扫描也没有胜出的生产候选：

| 候选 | 样本 | T+3 平均收益 | 胜率 | 平均回撤 | 结论 |
| --- | ---: | ---: | ---: | ---: | --- |
| strict | 1036 | -1.65% | 32.1% | -5.53% | 未通过 |
| strict + startup rescue | 1481 | -1.62% | 32.7% | -5.38% | 未通过，仅位于当前 Pareto 前沿 |
| mid | 1036 | -1.65% | 32.1% | -5.53% | 未通过 |
| loose | 1357 | -2.08% | 29.1% | -5.66% | 未通过 |

当前 `docs/data` 的 68 份 JSON 中有 65 个非空选股日，日期覆盖 2026-05-23 至 2026-08-21；`picks_pure` 5262 条、`picks_fusion` 2718 条全部缺少 `intended_horizon`。这些旧快照不能被改写成周期已验证样本，也不能用于选出正式的高收益版本。

结论：本轮代码可以进入候选/影子阶段，但没有生产高收益胜者，现有生产版本保持不变。只有新账本积累到同来源池、同周期、同入场口径下至少 100 个成熟样本、20 个有效日期和 2 个不重叠月份，并完成 OOT 锁定后，才允许重新评选和切换。

### 本地验收

- 完整 Python 回归：1135 项通过，0 失败。
- 本地 `run.py --debug`：退出码 0，生成 `output_debug/index.html`；随机调试样本得到主推 0、基础候选 0，验证空池时没有回填。运行期间外部东方财富接口多次连接失败，因此此报告只证明主流程和降级可运行，不作为收益证据。
- 合成的界面验收夹具仅用于检查展示合同，不是历史收益样本：桌面端主推详情可见信号日收盘价、T+1/T+3/T+5 收盘收益、期间最高/最低；结构化风险原因独立可见；390px 手机端无横向溢出。
- 浏览器逐页检查“加速”“罗姐池”“基础候选”均无“推荐、可上车、买入、立即执行”字样；主推页保留“推荐/可上车”；控制台 0 错误。

界面验收截图：

- 桌面：`/Users/yangfan/.codex/visualizations/2026/08/21/01a02396-28f1-7110-bc8d-3ae284959f29/stock-selection-desktop.png`
- 手机：`/Users/yangfan/.codex/visualizations/2026/08/21/01a02396-28f1-7110-bc8d-3ae284959f29/stock-selection-mobile.png`

本轮没有生成、覆盖或提交正式 `docs/index.html` 与当日线上日报，也没有部署 Worker；正式发布仍需单独确认。

## 2026-08-21 核心选股原始问题登记（实施前）

本实施计划完成的是辅助决策驾驶舱，不授权为了页面统一而修改各选股池的策略定义。后续复核发现的弱/回踩启动仍可推荐、趋势枚举不一致、市场状态重复作用、漏斗与策略版本归因缺失、T+1 标签混名、H4 v1 特征兼容和 highlights 动作降级问题，集中记录在 [辅助决策驾驶舱设计第 13 节](2026-08-20-auxiliary-decision-copilot-design.md#13-核心选股池语义边界与优化问题记录)。

后续设计必须遵守：公共层可以统一真实数据、证据、版本、标签和评测协议；`picks_pure`、`picks_fusion`、强势启动、趋势延续、观察池、次日大涨、罗姐池和 H4 T+3 的候选、确认、排序、门槛、周期和失效逻辑分别定义、分别验收。设计口径已经确认并转成 [高收益选股优化实施计划](2026-08-21-stock-selection-high-return-implementation-plan.md)；后续已获授权并在隔离分支实施，尚未正式发布。

已确认 `picks_pure` 为各独立策略确认结果合流后的基础候选全集：原始缠论结构、强势启动、趋势延续等策略继续独立发现、确认、观察和失效，成立候选携带来源策略、池内等级、原因和证据汇入该全集，再供融合池及其他后续策略使用。共同上游不等于统一策略逻辑，`picks_pure` 也不是最终推荐池，不直接产生用户可执行动作；后续实施不得把 `daily_pure` 全池按 published recommendation cohort 记账。

已确认页面“主推” Tab 为最终对外可执行推荐池，对应 `picks_fusion` 中最终决策为 `recommend` 的股票。主推不设人工每日数量上限，所有过门股票全部展示，允许零只、不回填；“少而精”由质量门槛自然形成，不通过 Top3/Top5 截断。`picks_fusion` 原始载荷中保留的观察、拒绝或数据不足项只能用于审计，不得进入最终推荐数量、推荐账本或用户动作统计。后台变量与页面 Tab/卡片的完整对照记录在设计文档第 13.3.1 节；后续讨论必须使用“页面名称（后台变量）”格式。

用户已授权其余非个人交易偏好项目按推荐方案收口：强势启动仅“日线 strong + 30min S/A”取得融合筛选资格，其余只观察；趋势延续使用自己的趋势位置、过热与失效合同；加速和罗姐池在独立验收前只观察；H4 T+3 v1 冻结、独立、允许空池且不回填；多池同票只并列展示来源，不自动加分或升级。详细合同见设计文档第 13.3.2 节。该阶段完成文档设计；后续隔离分支已按已确认的持有周期、研究入场价、主推数量和高收益评价口径实施。

已确认主推股票允许使用不同的主要持有周期，但必须在主推卡片、详情和研究归因账本逐只标注 `T+1`、`T+3` 或 `T+5`，并保留来源策略与周期依据。只有对应策略已经验收的周期才能成为 `intended_horizon`；周期缺失、存在未解决冲突或未经验证时只能观察，不得进入主推。版本采用高收益优先，以对应周期平均收盘收益为第一主指标。

已确认本项目只评价和优化选股，不考虑实际交易。主推统一使用 `entry_mode=immediate_close`（页面标签“信号日收盘价”），以信号日正式收盘价为研究入场价，`T+1`、`T+3`、`T+5` 分别以对应未来交易日收盘价作为主收益，并补充从 D+1 开始到对应周期为止的期间最高收益与期间最低收益。页面使用“收盘收益／期间最高／期间最低”中文标签；例如收盘 `+5%`、窗口最高 `+10%` 必须同时展示。切换入场模式时不得把信号日盘中高低价计入入场后 MAE/MFE。券商委托、是否成交、真实成交价、止损止盈、持仓和实盘盈亏均不进入本轮范围。当前 `delay1_open` 归因必须修正。主推不设人工数量上限，Top-K 只做研究诊断。

已确认版本选择采用高收益优先，不以尾部风险最低作为第一目标。每只股票按其 `intended_horizon` 计算收盘收益，版本比较以平均收盘收益为第一主指标；中位收盘收益和 `>=5%` 命中率作为稳健性支持。若均值更高但这两项相对基线同时变差，则标记为“异常值驱动”，不得直接替换生产版本。期间最高收益只展示和诊断，不作为第一优化目标。大跌率、worst、期间最低收益和时序稳定性继续完整展示，但不自动否决收益明显更高的非支配版本；真实数据、防泄漏、成熟标签和 OOT 等研究硬门保持不变。

生产替换的 OOT 硬门固定为：同一来源池、同一 `intended_horizon`、同一 `entry_mode` 下至少 100 个 primary 完整成熟样本、20 个可形成 primary 完整样本的指标日期，并覆盖 2 个非重叠自然月；30–99 个成熟样本或 10–19 个指标日期只做影子观察，低于该范围为数据不足。OOT 必须按时间顺序锁定，不能在看过结果后继续调参，也不能跨池、跨周期拼样本达到门槛。

已确认风险方向需要独立 `risk_reasons` 字段。页面显示“风险成立”时必须逐条列出风险事实、可能影响与证据引用；摘要、证据链、下一确认和失效条件不能替代具体原因。该字段用于解释和验收，未经单独回看验证不得直接成为选股硬门。

## 2026-08-21 完成审计补记

| 实施任务 | 权威证据 | 审计结论 |
| --- | --- | --- |
| 基础候选、主推与版本归因 | `candidate_funnel`、`recommendation_ledger`、页面 workspace 合同测试 | `picks_pure` 使用独立 `candidate` 终态；漏斗主推只取页面实际发布的 recommend 集合，不再把实验候选全部记为主推 |
| 状态越权、强势启动与趋势延续 | 强势启动、趋势延续、fusion admission、decision engine 矩阵测试 | 来源状态只降不升；启动须日线 strong + 30min S/A；趋势须至少两项独立 30min 确认并使用趋势位置语义 |
| 加速与罗姐池观察边界 | 候选字段、运行时策略输入、推荐账本三层回归 | 均为 `observe/internal/watch`，不能进入正式推荐 cohort；完成审计时补齐了此前仅页面降级而账本仍可能越权的缺口 |
| H4 T+3 v1 隔离 | 冻结 legacy 决策向量、真实空池、无上限/无回填、无主推加分测试 | v1 继续独立 fail-close；页面从冻结池合同显示 T+3；模型异常只关闭 H4 池，不中断整份日报 |
| 收盘价分周期研究 | 固定 OHLC 与交易日 fixture | 入场为信号日收盘；T+1/T+3/T+5 用未来交易日收盘；MFE/MAE 只含 D+1..D+N |
| 高收益版本晋级 | scorecard、同切片、异常值、样本与 OOT 门测试 | 均值主排序；中位数和 5% 命中率防异常值；无 Top K 生产截断 |
| 页面和风险原因 | 视图模型、生成器、浏览器桌面/390px 验收 | Tab、来源、周期、收益标签一致；页面优先消费 workspace 决策，原始 recommend 不能绕过观察封顶；风险原因独立且有证据引用 |

审计边界：代码、研究合同和本地展示已完成；历史回放没有产生可替换生产的高收益胜者，因此“正式生产版本胜出、正式日报生成、远端发布”均保持未完成状态，不能由本地测试代替。

高收益晋级链补充审计：scorecard 内四个研究布尔值不再具有晋级效力。影子评测可另行提供只读 OOT attestation manifest，由脚本读取实际 OOT 数据文件并校验 SHA-256，同时逐版本绑定来源池、策略版本、主要周期、`immediate_close` 入场、cutoff 和当前完整代码提交 SHA，并从 artifact 样本重算样本数、活跃日/月、平均/中位收盘收益和 `>=5%` 命中率；合同、文件哈希、代码状态或重算指标任一不一致均 fail-close。但调用方仍能同时伪造 artifact 与哈希，当前 `source_record_hash` 也没有反查受控账本或行情库，所以所有已验证 artifact 仍固定为 `shadow / trusted_oot_provenance_unavailable`，`selected_version` 必须为空。正式生产晋级须后续接入 recommendation ledger + `market_history.sqlite` 反查，或受信 CI 公钥签名。该边界不改变当前“没有生产高收益胜者”的结论。

独立代码复审还发现并补齐：同票多来源在合并前分别过门；观察 Tab 的 workspace 决策优先于原始池数据；旧 `delay1_open` 页面记录不再被静默改写为收盘价；新日报候选显式写入 `immediate_close`；未来窗口零成交量会以 `suspended_or_non_trading_bar` 解释样本不足；聚合 `data.json` 补齐观察池与 H4 池，旧消费者也能还原新增 Tab。

最终复审补齐同票多来源全链路：信号时效、fusion admission、来源评分、GF-DMA、位置证据与 decision engine 均先逐来源执行，再按 code 聚合；一个过期来源不再删掉同票的有效来源。聚合决策采用“任一 recommend 优先，否则 observe 优先于 reject”，不允许某个策略自身的 reject 否掉另一独立策略的 recommend，也不叠加分数；页面显示“排名代表来源”，账本保留该来源的理由和分数。H4 展开合格的趋势 variant 后独立评估，全部 H4 门槛通过即进入自身 T+3 研究 cohort；输出重建 H4 来源与推荐快照，上游来源/决策只作审计。漏斗对基础候选的融合淘汰记全局失败，但同票并行观察近失只记 `source_failures`，不再污染主推/基础候选的 `first_failure_counts`。

OOT 实施边界不变：本地 artifact 与 SHA-256 可被同一调用方同时伪造，且现有实现无法证明训练结束时点、OOT 开始时点和参数锁定先后关系。因此所有 attestation 仍强制 `shadow / trusted_oot_provenance_unavailable`，不产生 `selected_version`；只有接入受控 recommendation ledger + `market_history.sqlite` 反查，或受信 CI 公钥签名并证明时间锁后，才能另行设计生产 cutover。
