# 独立右侧启动通道 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在不放宽经典 `picks_pure`、不改变 H4 语义和正式 fail-closed 合同的前提下，实现一个 formal/preclose 同源的独立右侧启动通道；先以 shadow 上线，经样本外和真实交易日门槛后才允许 active。

**Architecture:** 继续以 `chanlun.trend_continuation` 作为唯一右侧策略内核，从正式检索 `chan_results` 独立识别平台/中枢突破并做三层 30 分钟确认。`run.py` 与 `chanlun/preclose_pipeline.py` 只负责用相同纯函数编排 off/shadow/active；shadow 仅输出诊断，active 才将通过项送入现有评分、fusion admission 和 decision engine。经典强势启动仍受结构上游约束，H4 明确过滤右侧来源。预收盘由 launchd 在 14:45 自然启动，以 240 秒为总预算上限并保持 14:49 墙钟硬截止。

**Tech Stack:** Python 3、NumPy、SQLite 只读 URI、`unittest`、现有 ChanlunStrategy 决策/报告管线、Cloudflare preclose Worker 与 GitHub Pages 非回归验收。

---

## 执行规则

- 每个实现任务使用 `@superpowers:test-driven-development`：先写一个会因缺少目标行为而失败的测试，确认失败原因，再做最小实现。
- 遇到不符合预期的策略结果使用 `@superpowers:systematic-debugging`，不得通过放宽阈值或增加股票白名单让夹具通过。
- 每批提交前重新 `git fetch origin main`，确认 `origin/main` 是当前提交祖先；若主分支前进，只做必要适配并重新跑相关测试。
- 最终发布前使用 `@superpowers:verification-before-completion`；Cloudflare 验收按 `@cloudflare`、`@durable-objects`、`@wrangler` 的安全边界执行。
- 所有测试和回放不得写正式 `market_history.sqlite`、推荐账本、影子账本、日报、scorecard 或 comparison index。
- 实施阶段可保留小步本地提交；推送前压成一个干净功能提交，标题使用 `feat: 增加独立右侧启动通道`。

## Task 1：冻结策略合同与 2026-08-31 回归夹具

**Files:**

- Create: `tests/fixtures/right_side_startup/2026-08-31.json`
- Modify: `tests/test_trend_continuation.py`
- Test: `tests/test_market_data_guard.py`

**Step 1: 写失败测试**

在夹具中只保存经过脱敏且足以复算门控的日线、30 分钟和预期结论：

```json
{
  "trade_date": "2026-08-31",
  "cases": {
    "300709": {"expected": "candidate", "reference_price": 43.57},
    "002636": {"expected": "watch", "failure_gate": "daily_breakout"},
    "002952": {"expected": "watch", "failure_gate": "daily_breakout"}
  }
}
```

新增测试证明：夹具日期一致、30 分钟证据属于目标交易日、`300709` 通过严格右侧门、另外两只不通过；任何代码白名单都不参与判断。

**Step 2: 确认测试因合同尚未实现而失败**

Run:

```bash
python3 -m unittest tests.test_trend_continuation tests.test_market_data_guard
```

Expected: FAIL，失败点是缺少严格 `right_side_startup` 身份、日线 failure gate 或三层 30 分钟证据，而不是夹具解析错误。

**Step 3: 只补测试辅助构造器，不修改生产规则**

将 fixture loader 和 `SimpleNamespace` 构造器留在测试文件；生产模块不得读取该 fixture。

**Step 4: 重新确认失败是预期行为**

Run 同 Step 2；Expected: 仍 FAIL，且失败信息精确指向待实现规则。

**Step 5: Commit**

```bash
git add tests/fixtures/right_side_startup/2026-08-31.json tests/test_trend_continuation.py tests/test_market_data_guard.py
git commit -m "test: 冻结右侧启动回归样本"
```

## Task 2：收紧日线右侧事件并修复 Pivot 类型兼容

**Files:**

- Modify: `chanlun/trend_continuation.py`
- Modify: `tests/test_trend_continuation.py`
- Test: `tests/test_chan_engine_candidate_trend.py`

**Step 1: 增加失败单测**

覆盖：

1. `engine_types.Pivot` 对象与 mapping 的 `ZG` 读取结果一致。
2. `close >= MA5 >= MA10` 但未突破平台/ZG 时只能 watch，参考类型不得回退到 `ma10`。
3. 平台突破与中枢突破至少一个成立，才有 seed。
4. 涨停、跌停、跳空、过度延伸维持观察/过滤语义。

**Step 2: 运行并确认失败**

```bash
python3 -m unittest tests.test_trend_continuation tests.test_chan_engine_candidate_trend
```

Expected: FAIL 于对象 Pivot 被忽略和 MA10 回退仍可生成近失观察的旧行为。

**Step 3: 最小实现**

在 `chanlun/trend_continuation.py`：

- 增加统一的 `_field_value(value, *keys)`，同时支持 Mapping 和属性对象。
- 删除 `ma10` 作为右侧事件参考位的候选路径。
- 保留 MA 排列为状态证据，只在平台/ZG 突破成立后形成 `strong_structure`。
- 将来源标准化为 `source_channel="right_side_startup"`、`source_type="日线右侧启动"`，保留旧函数名以减少调用面。
- 诊断写入 `reference_type`、`reference_price`、`distance_from_reference_pct`、`failure_gate`、`actual_value` 和阈值。

**Step 4: 运行聚焦测试**

Run 同 Step 2；Expected: PASS。

**Step 5: Commit**

```bash
git add chanlun/trend_continuation.py tests/test_trend_continuation.py tests/test_chan_engine_candidate_trend.py
git commit -m "feat: 收紧右侧启动日线门"
```

## Task 3：把 30 分钟确认改为 mandatory / structure / quality 三层门

**Files:**

- Modify: `chanlun/trend_continuation.py`
- Modify: `tests/test_trend_continuation.py`
- Test: `tests/test_market_data_guard.py`

**Step 1: 增加失败单测**

分别构造并断言：

- 只有 `EMA5 >= EMA10`：watch。
- 突破位不破 + EMA 状态，无新鲜结构：watch。
- 突破位不破 + 新鲜结构，无质量确认：watch。
- mandatory + structure + quality 全部成立：candidate。
- 日期错配、stale、盘后 `is_final=false`：watch。
- 盘中 `bar_state=intraday` 且 `is_final=false` 只有显式 preclose 上下文才可作为预跑证据。

**Step 2: 确认旧的“任意两项”规则失败**

```bash
python3 -m unittest tests.test_trend_continuation tests.test_market_data_guard
```

Expected: FAIL，证明旧 `_confirm_30min()` 会错误升级 EMA 状态票。

**Step 3: 最小实现**

将 `_confirm_30min` 改为结构化证据：

```python
{
    "mandatory": {"reference_hold": True},
    "structure": {"fresh_event": True, "labels": [...]},
    "quality": {"independent_confirm": True, "labels": [...]},
    "risk": {"macd_weakening": False},
    "passed": True,
}
```

复用仓库已有 30 分钟形态/买点输出，不复制一套不同 K 线定义。`EMA5 > EMA10` 只能进入状态字段；EMA 收复或持续上行必须有斜率/穿越证据。MACD 减弱进入 risk，不单独凑 quality。

**Step 4: 运行聚焦测试**

Run 同 Step 2；Expected: PASS。

**Step 5: Commit**

```bash
git add chanlun/trend_continuation.py tests/test_trend_continuation.py tests/test_market_data_guard.py
git commit -m "feat: 增加右侧启动三层确认"
```

## Task 4：增加 off / shadow / active 纯模式合同

**Files:**

- Modify: `config.py`
- Create: `chanlun/right_side_startup.py`
- Create: `tests/test_right_side_startup.py`

**Step 1: 写模式失败测试**

断言：

- 默认 `CHANLUN_RIGHT_SIDE_STARTUP_MODE=shadow`。
- 非 `off|shadow|active` 值启动即报错。
- off 不扫描；shadow 返回候选和诊断但 `published=[]`；active 最多发布 Top3。
- active 排序只使用现有统一分数，不引入独立“资金加分”或样例优先级。
- 任一模式都不删除或覆盖已有经典候选。

**Step 2: 运行并确认模块不存在**

```bash
python3 -m unittest tests.test_right_side_startup
```

Expected: ERROR/FAIL，缺少模式模块和配置。

**Step 3: 最小实现纯编排器**

`chanlun/right_side_startup.py` 只负责：模式校验、运行现有 trend 函数、标准化诊断、shadow/public 分流和 Top3 限制。不得访问网络、数据库、文件系统或环境以外的运行时状态。

诊断至少包含：`mode`、`policy_version`、`input_count`、`daily_seed_count`、`min30_requested`、`min30_verified`、`candidate_count`、`watch_count`、`rejected_count`、`items`。

**Step 4: 运行测试**

```bash
python3 -m unittest tests.test_right_side_startup tests.test_trend_continuation
```

Expected: PASS。

**Step 5: Commit**

```bash
git add config.py chanlun/right_side_startup.py tests/test_right_side_startup.py
git commit -m "feat: 增加右侧启动影子模式"
```

## Task 5：盘后正式接入独立通道并隔离 H4

**Files:**

- Modify: `run.py`
- Modify: `chanlun/h4_t3_pool.py`
- Modify: `tests/test_pipeline_invariants.py`
- Modify: `tests/test_h4_production_boundary.py`
- Modify: `tests/test_right_side_startup.py`

**Step 1: 写失败集成测试**

冻结以下不变量：

1. 经典 strong-startup 输入仍是 `_extend_upstream_for_limit_up_observation(chan_results, pure_pool)`。
2. right-side 输入是正式检索 `chan_results`，不是 `pure_pool`。
3. shadow 下 `picks_pure`、`picks_fusion`、H4 和正式 hash 与 off 完全一致。
4. active 下只有右侧候选经现有评分/fusion/decision engine 后可追加；旧候选内容和顺序不变。
5. `build_h4_t3_pool` 明确拒绝 `source_channel == "right_side_startup"`。

**Step 2: 运行确认 formal 尚未具备独立模式**

```bash
python3 -m unittest tests.test_pipeline_invariants tests.test_h4_production_boundary tests.test_right_side_startup
```

Expected: FAIL。

**Step 3: 最小接入**

在 `run.py`：

- Phase 4.5 保留 classic startup 共同上游。
- 单独对 `chan_results` 建右侧 daily seeds，仅请求这些 seed 的 30 分钟数据。
- shadow 只进入 `report_data["right_side_startup"]` 诊断，不进入 `pure_confirmed`。
- shadow 的 30 分钟数据只从正式 SQLite 只读加载，不进入 ongoing 补数目标；公开写入器默认剥离 `right_side_startup` 影子诊断，off/shadow 的正式日报、Pages 与聚合投影保持字节等价。
- active 才在去重后追加到 `pure_confirmed`，继续走 `apply_scores`、fusion admission 和 `_inject_decision_engine`；不得绕过正式市场情绪或决策门控。
- 不把右侧候选写成伪买点类型。

在 `chanlun/h4_t3_pool.py` 的正式输入边界先过滤右侧来源，并在 diagnostics 记录数量。

**Step 4: 运行聚焦回归**

Run 同 Step 2；Expected: PASS。

**Step 5: Commit**

```bash
git add run.py chanlun/h4_t3_pool.py tests/test_pipeline_invariants.py tests/test_h4_production_boundary.py tests/test_right_side_startup.py
git commit -m "feat: 接入盘后右侧启动通道"
```

## Task 6：让 14:45 与正式复用同一通道语义并扩展安全预算

**Files:**

- Modify: `chanlun/preclose_pipeline.py`
- Modify: `chanlun/preclose_data.py`
- Modify: `preclose_run.py`
- Modify: `launchd/com.breakaway4here.chanlun-preclose.plist`
- Modify: `tests/test_preclose_pipeline.py`
- Modify: `tests/test_preclose_data.py`
- Modify: `tests/test_preclose_runtime.py`
- Modify: `tests/test_preclose_launchd.py`
- Modify: `tests/test_preclose_formal_isolation.py`

**Step 1: 写失败测试**

断言：

- `PreclosePipelineComponents` 注入同一 right-side 纯编排器。
- classic startup 只扫描 `pure_pool` 对应上游，不再直接扫全部日线结果。
- right-side 从全部合格 `daily_results` 独立扫描。
- 30 分钟 `target_codes` 是 classic structure、classic startup、right-side seeds 的并集并去重。
- shadow 的 success/failure/timeout/not-run 四态均不改变正式文件 hash。
- launchd 周一至周五均为 14:45，不再保留 14:47 条目。
- 允许窗口为 `[14:45, 14:49)`；总预算上限从 120 秒增至 240 秒，但始终取墙钟剩余时间、交付预留和总预算的最小值。
- 14:49 到达前若预算耗尽仍 fail-closed；14:49 之后绝不启动 pipeline 或新增动作。
- executed stages 仍只有既有允许阶段。

**Step 2: 运行确认现有 preclose 上游不一致**

```bash
python3 -m unittest tests.test_preclose_pipeline tests.test_preclose_data tests.test_preclose_formal_isolation
```

Expected: FAIL，至少命中 classic startup 仍扫描 `daily_results`。

**Step 3: 最小实现**

- `_build_daily_state` 同时产出 classic 与 right-side 状态。
- `_finish_main_state` 按模式分流；shadow 候选只在 diagnostics，active 才进入统一候选和 decision engine。
- 预跑右侧 30 分钟证据显式携带 `trade_date/as_of/bar_state=intraday/is_final=false`，由同一验证函数识别合法上下文。
- 将调度窗口和最大预算提取为命名常量，避免 launchd、runtime 和 pipeline 各自保留不一致的 14:47/120 秒魔法值。
- 不增加新闻、公告/研报、LLM、iWencai、15 分钟、罗姐、报告或 Git 阶段。

**Step 4: 运行聚焦回归**

Run 同 Step 2；Expected: PASS。

**Step 5: Commit**

```bash
git add chanlun/preclose_pipeline.py chanlun/preclose_data.py preclose_run.py launchd/com.breakaway4here.chanlun-preclose.plist tests/test_preclose_pipeline.py tests/test_preclose_data.py tests/test_preclose_runtime.py tests/test_preclose_launchd.py tests/test_preclose_formal_isolation.py
git commit -m "feat: 提前预收盘启动并对齐策略"
```

## Task 7：决策、账本和展示合同保持单一正式动作

**Files:**

- Modify: `chanlun/report_generator.py`
- Modify: `chanlun/report_view_model.py`
- Modify: `chanlun/preclose_notify.py`
- Modify: `chanlun/report_assets/report-v2.js`
- Modify: `tests/test_report_generator.py`
- Modify: `tests/test_report_view_model.py`
- Modify: `tests/test_auxiliary_decision.py`
- Modify: `tests/test_preclose_notify.py`
- Modify: `tests/test_preclose_frontend.py`

**Step 1: 写失败测试**

断言：

- 用户可见 main 仍只取 `decision_engine_v1.decision_code == "recommend"`。
- `decision_score` 仍只来自 `decision_engine_v1.total_score`，右侧通道不新增第二个正式分数。
- 同一股票只有一个正式动作；右侧来源只作为证据标签。
- shadow 只出现在研究验证诊断，不进入 main/H4/推送。
- 观察文案为“为何进入 / 还差什么 / 什么情况失效”，不平铺内部 `xxx未提供`。
- 网页、微信和盘后复核面向用户的时间标签统一为“14:45预跑”；旧 `preclose-1447-v1` 版本标识升级，避免新旧调度证据混淆。

**Step 2: 运行并确认序列化尚无 right-side 合同**

```bash
python3 -m unittest tests.test_report_generator tests.test_report_view_model tests.test_auxiliary_decision
```

Expected: FAIL。

**Step 3: 最小实现**

序列化 `right_side_startup` 的简洁摘要与完整底层诊断；页面主卡只显示来源、参考位和关键确认，不展示内部校验术语。不得改变正式市场情绪、PSY12、唯一动作和分数来源合同。

**Step 4: 运行聚焦测试**

Run 同 Step 2；Expected: PASS。

**Step 5: Commit**

```bash
git add chanlun/report_generator.py chanlun/report_view_model.py chanlun/preclose_notify.py chanlun/report_assets/report-v2.js tests/test_report_generator.py tests/test_report_view_model.py tests/test_auxiliary_decision.py tests/test_preclose_notify.py tests/test_preclose_frontend.py
git commit -m "feat: 展示右侧启动决策证据"
```

## Task 8：增加只读样本外回放和激活门报告

**Files:**

- Create: `scripts/replay_right_side_startup.py`
- Create: `tests/test_replay_right_side_startup.py`
- Modify: `docs/runbooks/preclose-production.md`

**Step 1: 写失败测试**

用临时 SQLite 数据库验证：

- URI 必须包含 `mode=ro`，禁止网络回补。
- 时间分块和 embargo 不得使用未来数据。
- 输出 T+1/T+3/T+5、P10、最差收益、最大回撤、`<=-5%` 尾部率、每日数与 P95。
- 报告同时包含 right-side 与当前正式主推基线。
- gate 只有在 T+3 中位数不劣于基线且尾部增量 `<=2pp` 时通过。

**Step 2: 确认脚本不存在**

```bash
python3 -m unittest tests.test_replay_right_side_startup
```

Expected: ERROR/FAIL。

**Step 3: 最小实现**

参考 `scripts/replay_strong_startup_30m_confirmation.py` 和 `scripts/run_recall_walkforward.py`，但调用新的同源纯函数。所有输出写入用户明确指定的 evidence 目录；默认只打印聚合统计，不改仓库生成产物。

**Step 4: 运行只读回放单测**

```bash
python3 -m unittest tests.test_replay_right_side_startup
python3 -m py_compile scripts/replay_right_side_startup.py
```

Expected: PASS，exit 0。

**Step 5: Commit**

```bash
git add scripts/replay_right_side_startup.py tests/test_replay_right_side_startup.py docs/runbooks/preclose-production.md
git commit -m "test: 增加右侧启动样本外回放"
```

## Task 9：完成 formal/preclose 冻结语义和策略非回归

**Files:**

- Modify: `tests/test_right_side_startup.py`
- Modify: `tests/test_preclose_e2e.py`
- Modify: `tests/test_pipeline_invariants.py`
- Modify: `tests/test_h4_t3_pool.py`

**Step 1: 增加端到端夹具断言**

用同一份 2026-08-31 fixture 分别运行 formal adapter 和 preclose adapter，断言：

- daily/30m 同值时三只股票结论一致。
- 14:45 与收盘真实行情变化可以改变结论，但 failure gate 必须可解释。
- `300709` 是 candidate，`002636/002952` 是 watch。
- shadow 正式 hash 与 off 一致。
- H4 不含 right-side；active public source 每日最多 3 只。

**Step 2: 运行端到端测试**

```bash
python3 -m unittest tests.test_right_side_startup tests.test_preclose_e2e tests.test_pipeline_invariants tests.test_h4_t3_pool
```

Expected: PASS。

**Step 3: 运行策略聚焦审查集**

```bash
python3 -m unittest \
  tests.test_trend_continuation \
  tests.test_market_data_guard \
  tests.test_decision_engine \
  tests.test_fusion_admission \
  tests.test_h4_production_boundary \
  tests.test_preclose_pipeline \
  tests.test_preclose_formal_isolation \
  tests.test_report_view_model \
  tests.test_report_generator
```

Expected: PASS，exit 0。

**Step 4: Commit**

```bash
git add tests/test_right_side_startup.py tests/test_preclose_e2e.py tests/test_pipeline_invariants.py tests/test_h4_t3_pool.py
git commit -m "test: 验证右侧启动双链路一致性"
```

## Task 10：全量验证、发布准备与单提交整理

**Files:**

- Verify only: repository-wide

**Step 1: 同步最新 main**

```bash
git fetch origin main
git rebase origin/main
git merge-base --is-ancestor origin/main HEAD
```

Expected: rebase 成功，ancestor check exit 0。

**Step 2: 全量 Python 与静态检查**

```bash
python3 -m unittest discover -s tests
python3 -m py_compile run.py chanlun/trend_continuation.py chanlun/right_side_startup.py chanlun/preclose_pipeline.py scripts/replay_right_side_startup.py
```

Expected: 全部 PASS，exit 0；测试数量不得少于基线 1800。

**Step 3: Worker 与现有 Top10 非回归**

```bash
npm test --prefix cloudflare/preclose-worker
npm test --prefix cloudflare/top10-worker
```

Expected: 两组全部 PASS，exit 0；Top10 源码、binding、路由和 migration 无 diff。

**Step 4: 生成 shadow dry-run 并验证零写入**

在临时目录和只读正式 DB 上分别跑 off/shadow，比较：

```bash
shasum -a 256 data/market_history.sqlite data/recommendation_ledger.jsonl docs/data.json docs/data/comparison-index.json
```

Expected: 前后 SHA 完全一致；shadow 诊断包含候选，但正式池不变。

**Step 5: 整理一个功能提交**

在确认所有本地小提交均只属于本方案后，将它们整理为一个最终功能提交；保留设计与实施计划文档，只强制加入这两份被忽略的 Markdown，不加入任何其他忽略或生成文件。

Expected final title:

```text
feat: 增加独立右侧启动通道
```

## Task 11：Shadow 发布与真实交易日激活门

**Files:**

- Modify only if evidence requires: `docs/runbooks/preclose-production.md`
- Runtime config: `~/.config/chanlun-strategy/preclose.env`，权限 `0600`，不得打印值

**Step 1: 以 shadow 发布，不直接 active**

通过仓库现有安全合入流程推送单提交到 main，更新 production-runtime；确认 main、runtime 和 release SHA 一致且 clean。`CHANLUN_RIGHT_SIDE_STARTUP_MODE=shadow`。

**Step 2: Cloudflare/Pages 非回归**

若 Worker 源码无变更，不重新引入新 binding；仍执行 wrangler dry-run 和线上 GET/CORS/no-store/expired 回读。Top10 线上 body SHA 与发布前一致。Pages 回读 JSON/HTML/JS/CSS，并用真实数据页面截图验收来源标签、唯一正式动作和零横向溢出。

**Step 3: 自然交易日 shadow 验收**

只观察 launchd 自然触发：

- 14:45 启动、14:49 前完成；launchctl 回读必须证明新 plist 已 load 且绝对路径指向 production-runtime。
- 14:56:30 Worker 与页面同步失效。
- snapshot identity/content hash 一致。
- 盘后正式与只读复核完成。
- right-side shadow 有诊断，正式 DB/ledger/日报/Pages/comparison hash 不变。

任一项失败即保持 shadow，记录 failure gate，不得事后手工补跑冒充。

**Step 4: 历史激活门审查**

运行只读样本外回放。只有 T+3 中位数不劣于正式基线、尾部增量 `<=2pp`、候选数受控且真实 shadow 日全部通过，才允许把模式从 shadow 改为 active。

回放必须使用 `gate_events` 的当日完整正式检索全集，缺失即 fail-closed；至少覆盖 20 个样本外交易日，右侧与基线各至少 20 个可评估 T+3 样本，原始确认候选每日 P95 `<=20`，并继续强制公开 Top3。

**Step 5: Active 首日生产验收**

下一真实交易日自然触发后验证：

- 右侧来源最多 Top3。
- 只有 decision engine recommend 进入 main。
- H4 不含 right-side。
- 微信、网页和盘后复核同一 snapshot identity/content hash。
- 相同 formal hash + channel 不重复推送。
- 手机实际到达；缺少手机确认不得标记完全上线。

**Step 6: 回退验证**

通过向前把模式切回 `shadow` 或 `off` 验证关闭路径；不得删除账本、DO 或历史审计，也不承诺 DO 生命周期变化后旧版本简单 rollback 安全。

**Step 7: 完成判定**

只有本计划门槛与原 P0-P4 25 项上线门槛均有新鲜证据后，才可调用 `update_goal(status="complete")`；否则 goal 保持进行中/blocked，并明确下一真实交易日缺口。
