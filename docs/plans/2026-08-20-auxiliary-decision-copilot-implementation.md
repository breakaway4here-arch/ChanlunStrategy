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

## 2026-08-26 选股语义、记分牌与全页歧义修复记录

### 已实现

- 新增集中式池合同，保留“字段缺失 / 合同错误 / 合法空池 / 已停用 / 部分可用 / 数据可用”的差异；报告生成不得先用空数组抹平缺失池。
- `picks_pure` 固定为所有策略的共同上游全集；融合主推、强势启动、趋势延续、次日爆发、罗姐主题与 H4 的终局成员都受共同上游子集合同约束，但仍使用各自的门槛与排序。
- 每个页面 Tab 输出 `role / source_pool / action_semantics / availability`；页面分为“正式策略 / 研究观察 / 上游全集”，变量到 Tab 的映射见设计文档 12.2。
- 研究池统一显示“页面只能观察”，`picks_pure` 显示“仅作为策略上游”；正式输入事故日显示“正式动作已封闭”。原始策略判断只留在证据区，不能变成研究榜页面动作。
- 新增 `selection_input_health.schema_version=2`，按 `daily_fusion / h4_t3 / luojie_pool` 分别登记状态、阻断原因和受影响代码。15min/30min 输入必须核验交易日与终局状态；一个正式策略故障只封闭该策略，缺少或矛盾的健康证明一律 fail closed。
- 推荐账本与策略回看使用信号日收盘入场、T+1/T+3/T+5 收盘评估，并展示 MFE、MAE 与盘中触及 `+5%`。状态明确区分真实 0、等待到期、正常空选、今日未启用和数据不可用。
- 新增 `config/strategy_sample_exclusions.json` 事故登记与 `scripts/repair_strategy_scorecard_snapshot.py` 定向修复器；历史账本不改写，排除规则精确到日期、策略、代码和错误原因。
- 记分牌分为正式推荐、`picks_pure` 基线、独立研究策略、门控诊断；每张卡拆成“今日运行 / 账本累计 / 收益评测”三种口径，账本带起止日期，收益区分合同样本、可评、非收益样本、事故排除和去重回合。
- 移除跨角色“全部榜单平均收益”；跨页历史表现只比较正式主推与 H4，不把基础全集和研究池混入正式成绩。
- 今日方向摘要移到选股 Tab 前；风险原因、证据编号、确认条件与失效条件结构化展示；LLM 失败摘要和原始诊断分层显示。
- 移动端折叠市场头；候选支持当前池搜索、首次 20 条和继续加载；候选池原始数量不受限制。Tab 与候选使用可恢复焦点，候选行支持上下方向键 / Home / End 导航；搜索后首条结果自动成为可聚焦项。
- 方向摘要明确标注“规则生成 / 模型复核 / LLM 复核失败·已回退规则”；关注池的方向详情同步展示 `stock_links` 的代码、名称与角色。
- 跨日比较索引增加 H4 T+3，并使用同一事故登记排除受污染的正式样本；校验器会逐日对齐正式主推与 H4 的日报成员。
- 跨日比较额外逐日核验 `selection_input_health.schema_version=2` 与对应策略 `status=verified + formal_actions_allowed=true`；历史快照缺证明时正式列表清空，并记录 `formal_input_blocked_counts`，不再把旧主推误算成正式成绩。
- 历史工作区若含 `picks_pure` 全集外代码，修复器不改原始池、不删除后重排，而是按视图登记 `strategy_upstream_contract_mismatch` 并整体封闭。缺少策略级健康证明的旧归档由前端防线清空全部策略视图，只保留“基础候选”追溯。
- 修复器把日报、聚合 JSON、根页面、归档页面、JS/CSS 与比较索引放进同一个带 journal/回滚的原子发布事务，避免日报已更新但比较索引仍停在旧口径。

### 事故证据与受控修复边界

只读核验确认：2026-08-25 `300473`、2026-08-26 `300697` 的 30min 证据最后停在 2026-08-21 或未终局；罗姐策略 2026-08-24 至 2026-08-26 的 15min 输入过期或未终局。修复器只执行以下动作：

1. 写入输入健康与事故登记投影。
2. 封闭正式页面动作并从 scorecard 可评样本中排除事故贡献。
3. 保持 `picks_pure`、`picks_fusion`、各研究池、账本和正式输出保护 SHA 不变。
4. 只允许报告校验器对“登记完整、正式视图为空、错误码匹配”的事故修复使用受控例外；其他正式输入错误继续 fail closed。

H4 在 2026-08-26 的快照使用了 `picks_fusion` 上游，已独立登记为 `strategy_upstream_contract_mismatch`。该状态与融合策略 `300697` 的 30min 事故分开展示和评分，不再用全局正式健康状态混合归因。

### 本地回归与真实页面验收

- 本轮 Python 全量回归 1335 项通过；JavaScript 语法、Shell 语法与 Python 编译同步通过。该计数已覆盖策略级健康、共同上游、比较索引和三分母页面合同。
- 定向修复演练使用真实 2026-08-26 报告副本、真实推荐账本和市场历史库；日报 JSON、聚合 JSON、根页面和归档页面四个受保护原始池哈希均未改变，正式输出保护 before/after SHA 一致。
- 第二轮真实副本演练处理 878 条已终结账本，2026-08-26 当日 318/318 条全部可追溯，行情库 632/632 代码解析成功。四个公开平面的受保护选股哈希前后一致；日报校验与正式主推 / H4 比较成员对齐通过。该演练仅修改 `/private/tmp` 中的副本，未改动正式 `docs`。
- 1280×800 与 390×844 实际浏览器验收均无整页横向溢出；移动端市场头已折叠，方向摘要位于 Tab 前。
- 旧快照合同复核发现：看点 9/10、观察 4/5、罗姐 24/30、等确认 66/66 不在 `picks_pure`。修复后这四个视图均显示“数据不可用 (0)”；高弹性观察保留 10 只且 10/10 都属于 `picks_pure`，基础候选保持 136 只，原始池哈希不变。
- 基础候选首次显示 20/136；搜索 `301031` 后唯一结果同时成为 selected 与 `tabindex=0`，清空搜索后 ArrowDown 会把选中项和焦点同步移动到 `601388`，证明渐进展示和键盘路径不限制池数量。
- 记分牌可展开看到事故编号、原因、排除数量和逐周期“数据不可用”；事故复盘行不再把旧评分展示成有效成绩，事故图表中的图钉与参考线也统一标为“事故前·仅追溯”。
- 比较索引 26 日窗口内正式主推与 H4 的样本总数均为 0；12 个缺少逐策略健康证明的历史交易日记录了 `formal_input_blocked_counts`，没有继续进入正式表现统计。

### 发布结果、事故复盘与未完成项

2026-08-26 修复版已经完成独立整页复核、同步最新 `origin/main` 后的 1335 项回归、真实正式快照修复、提交、推送和 Pages 实值验收。发布提交为 `805de5bc77aab609545e1e2455878b31eff20ec5`；远端 main 与线上首页、JS、CSS、当日日报 JSON、比较索引逐文件 SHA 一致。三位整页审查 agent 均给出 `Ready: yes`，无剩余 P0/P1。

上一次“任务与 Pages 均成功，但页面记分牌不可用”的完整因果链、逃逸分析和每次发布必须执行的“五证验收”，见 [2026-08-26 选股与记分牌不可用版本发布事故复盘](2026-08-26-strategy-scorecard-release-incident-retrospective.md)。核心根因是 finalizer 固化账本后没有重建页面回看投影，旧校验又未覆盖逐策略健康、共同上游、记分牌分母和最终线上业务字段；不是因为已经到期的 T+3 历史行情无法读取。

当前明确未完成项是页面载荷分片：候选 DOM 已渐进渲染，但 HTML/JSON 仍携带完整个股详情。后续应把日报摘要与个股详情拆为静态分片并按需加载；此项不得通过限制 `picks_pure` 数量来规避。
