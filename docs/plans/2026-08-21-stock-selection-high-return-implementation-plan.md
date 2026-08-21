# Stock Selection High-Return Optimization Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在不统一各策略池内部逻辑的前提下，修复候选状态越权、研究收益口径和版本归因问题，并用可审计的 OOT 结果选择更高平均收盘收益的选股版本。

**Architecture:** `picks_pure` 只作为各独立策略确认结果合流后的“基础候选”共同上游；各来源策略继续独立发现、确认、失效和解释。融合层只能消费合格候选并决定“主推”，不能把来源池中的观察状态升级。公共层只统一股票身份、证据、版本、发布状态、研究入场价和收益评测格式；H4 T+3 v1 保持冻结隔离。

**Tech Stack:** Python 3、`unittest`、现有 JSON 报告合同、plain JavaScript/CSS、推荐账本、历史行情 SQLite、策略回看与 policy experiment 工具。

---

## 实施前提与不可变边界

- 本计划只优化选股研究，不接入券商委托、实际成交、持仓或实盘盈亏。
- 研究入场价固定为信号日收盘价，`entry_mode=immediate_close`。
- 每只主推必须具有已验证且唯一的 `intended_horizon`：`T+1`、`T+3` 或 `T+5`；无法确定时只能观察。
- 主推不设人工数量上限，所有过门股票展示，允许零只且不回填。
- 高收益版本以对应周期平均收盘收益为第一主指标；中位收盘收益与 `>=5%` 命中率负责识别异常值驱动；MFE 只展示和诊断。
- 生产替换的每个“来源池 + intended horizon + entry mode”切片至少有 100 个 primary 完整成熟 OOT 样本、20 个可形成 primary 完整样本的指标日期，并覆盖 2 个非重叠自然月；30–99 个样本或 10–19 个指标日期只做影子观察，更少则数据不足。
- 强势启动、趋势延续、原始缠论结构等来源逻辑不得收敛为一套评分。多来源同票只并列保留来源、原因、状态和周期，不增加共振分。
- `next_day_boom` 与 `luojie_pool` 在独立验证前保持观察；H4 T+3 v1 不改特征、不加主推分、不回填。
- 开始实施前先隔离用户现有改动，同步 `origin/main`，确认目标分支为当前分支祖先；每次提交只包含本计划文件。

## Task 1：冻结基础候选、主推与版本归因合同

**Files:**
- Modify: `run.py`
- Modify: `chanlun/recommendation_ledger.py`
- Modify: `chanlun/candidate_funnel.py`
- Test: `tests/test_recommendation_ledger.py`
- Test: `tests/test_candidate_funnel.py`

**Step 1: 写失败测试，锁定页面池与账本角色**

覆盖以下断言：

```python
def test_pure_pool_is_candidate_universe_not_published_recommendation(self):
    row = build_recommendation_row(pool="daily_pure", decision_code="recommend")
    self.assertEqual(row["publication_status"], "candidate")
    self.assertEqual(row["user_action"], "watch")

def test_fusion_only_publishes_recommend_decisions(self):
    self.assertTrue(is_published_fusion({"decision_code": "recommend"}))
    self.assertFalse(is_published_fusion({"decision_code": "observe"}))
```

同时要求 daily pure/fusion 的 `strategy_version` 非空，漏斗 retrieval 事件包含 `retrieval_pool`、`retrieval_sources` 和来源证据引用。

**Step 2: 运行测试，确认现状失败**

Run:

```bash
python3 -m unittest tests.test_recommendation_ledger tests.test_candidate_funnel -v
```

Expected: 新增的候选角色、非空版本或 retrieval 来源断言失败。

**Step 3: 最小实现公共外层合同**

- `picks_pure` 去重合流时保留 `strategy_sources[]`、每个来源的池内状态、原因、证据与原始周期。
- daily pure 账本固定为 `publication_status=candidate`，不得产生可执行用户动作。
- daily fusion 只有 `decision_code=recommend` 才写入 published recommendation cohort；观察、拒绝和数据不足只写审计状态。
- 为 daily pure、daily fusion 和各独立池写入显式非空 `strategy_version`；版本变更只在合同或策略逻辑实际变化时发生。
- retrieval 漏斗先记录来源池，再记录 fusion admission 和最终 decision，保证可以定位在哪一门淘汰。

**Step 4: 重跑定向测试**

Run:

```bash
python3 -m unittest tests.test_recommendation_ledger tests.test_candidate_funnel -v
```

Expected: PASS，且新增合同测试全部通过。

**Step 5: 提交本任务**

```bash
git add run.py chanlun/recommendation_ledger.py chanlun/candidate_funnel.py tests/test_recommendation_ledger.py tests/test_candidate_funnel.py
git commit -m "fix: 修正基础候选与主推归因"
```

## Task 2：阻断观察状态越权并收紧强势启动资格

**Files:**
- Modify: `chanlun/strong_startup.py`
- Modify: `chanlun/fusion_admission.py`
- Modify: `chanlun/decision_engine.py`
- Modify: `chanlun/report_view_model.py`
- Test: `tests/test_strong_startup.py`
- Test: `tests/test_fusion_admission.py`
- Test: `tests/test_decision_engine.py`
- Test: `tests/test_report_view_model.py`

**Step 1: 写状态优先级失败测试**

建立矩阵测试：

```python
eligible = daily_grade == "strong" and confirm_30m in {"S", "A"}
```

- `strong + S/A` 只获得参加融合筛选的资格，不自动推荐。
- `weak`、`pullback`、B/C、涨停当日、缺少 30min 或确认不足全部保持观察。
- 公共评分不得把来源池 `observe/reject/insufficient` 升级为 `recommend`。
- highlights 在决策缺失或非推荐时不得展示“可上车/等回踩”等买入措辞。

**Step 2: 运行定向测试，确认失败**

Run:

```bash
python3 -m unittest tests.test_strong_startup tests.test_fusion_admission tests.test_decision_engine tests.test_report_view_model -v
```

Expected: 观察状态仍可能通过 admission 或页面动作未降级的断言失败。

**Step 3: 引入只降不升的状态边界**

实现来源池状态上限：

```python
if source_status != "candidate":
    return admission_result("observe", reason="source_pool_not_eligible")
```

fusion/decision 可以把候选降为观察或拒绝，不能把来源池观察升级。页面动作只消费最终 published recommendation 子集；未知/缺失决策按观察降级。

**Step 4: 重跑测试并核对等确认/观察 Top5**

Run:

```bash
python3 -m unittest tests.test_strong_startup tests.test_fusion_admission tests.test_decision_engine tests.test_report_view_model -v
```

Expected: PASS；近失项仍可见，但不进入主推动作统计。

**Step 5: 提交本任务**

```bash
git add chanlun/strong_startup.py chanlun/fusion_admission.py chanlun/decision_engine.py chanlun/report_view_model.py tests/test_strong_startup.py tests/test_fusion_admission.py tests/test_decision_engine.py tests/test_report_view_model.py
git commit -m "fix: 阻断观察信号越权推荐"
```

## Task 3：修正趋势延续语义并隔离 H4 v1

**Files:**
- Modify: `chanlun/trend_continuation.py`
- Modify: `chanlun/fusion_admission.py`
- Modify: `chanlun/decision_engine.py`
- Modify: `chanlun/h4_t3_pool.py`（只增加兼容保护，不改 v1 特征值）
- Test: `tests/test_trend_continuation.py`
- Test: `tests/test_decision_engine.py`
- Test: `tests/test_h4_t3_pool.py`
- Test: `tests/test_h4_production_boundary.py`

**Step 1: 为趋势池写独立语义测试**

断言趋势候选只按自己的合同评估：日线趋势结构、量能、追高风险、趋势参考位、延伸度、跳空、过热、失效条件和至少两项 30min 趋势确认。不得因为低位反转使用的分位位置规则而被直接重罚。

同时冻结一个 H4 v1 输入样本，断言修改前后其 `decision_engine_v1` 特征向量、模型版本和生产边界完全一致。

**Step 2: 运行测试，确认趋势枚举与位置冲突**

Run:

```bash
python3 -m unittest tests.test_trend_continuation tests.test_decision_engine tests.test_h4_t3_pool tests.test_h4_production_boundary -v
```

Expected: 趋势枚举或通用位置先验断言失败；现有 H4 基线测试保持通过。

**Step 3: 分离事实归一化与池内解释**

- 统一事实枚举的读写兼容，但不把趋势池映射成低位反转分。
- 给 decision/fusion 输入显式 `strategy_source`，按来源调用对应 admission 规则。
- 趋势池仅在自身 `candidate` 后参加融合；近失、量能不足、涨停、跳空过大、远离参考位、缺数据或确认不足保持观察。
- H4 v1 继续读取冻结的 v1 特征适配器；新语义若需要进入模型，使用 v2 名称、重新训练并另行 OOT，不原地替换。

**Step 4: 重跑趋势与 H4 边界测试**

Run:

```bash
python3 -m unittest tests.test_trend_continuation tests.test_decision_engine tests.test_h4_t3_pool tests.test_h4_production_boundary -v
```

Expected: PASS；H4 v1 fixture 输出字节级等价或字段级完全一致。

**Step 5: 提交本任务**

```bash
git add chanlun/trend_continuation.py chanlun/fusion_admission.py chanlun/decision_engine.py chanlun/h4_t3_pool.py tests/test_trend_continuation.py tests/test_decision_engine.py tests/test_h4_t3_pool.py tests/test_h4_production_boundary.py
git commit -m "fix: 隔离趋势语义与H4旧模型"
```

## Task 4：去除市场状态重复作用并类型化确认事实

**Files:**
- Modify: `chanlun/fusion_admission.py`
- Modify: `chanlun/decision_engine.py`
- Modify: `chanlun/strong_startup.py`
- Modify: `chanlun/trend_continuation.py`
- Test: `tests/test_fusion_admission.py`
- Test: `tests/test_decision_engine.py`
- Test: `tests/test_strong_startup.py`
- Test: `tests/test_trend_continuation.py`

**Step 1: 写市场与确认归属测试**

- 同一个 `index_above_ema50` 事实可以被记录，但不能在 fusion admission 和通用总分中未经声明重复扣门。
- 强势启动的 S/A 确认与趋势延续的“两项 30min 确认”分别归各自池解释；任意非空确认文本不得等价为高质量确认。
- 每次市场影响输出 `owner_pool`、`stage`、`effect` 和 reason code，能说明它在哪个阶段产生一次什么影响。

**Step 2: 运行测试，确认重复门控和宽松布尔化失败**

Run:

```bash
python3 -m unittest tests.test_fusion_admission tests.test_decision_engine tests.test_strong_startup tests.test_trend_continuation -v
```

Expected: 市场状态重复作用或非空文本被当作确认的断言失败。

**Step 3: 最小重构事实与策略效果**

公共层只产生市场事实和结构化确认事实；各池在自己的 stage 将事实解释为 gate、penalty、annotation 或 ignored。删除通用层对未声明市场事实的第二次隐式影响，并保留兼容字段用于报告审计。

**Step 4: 重跑定向测试**

Run:

```bash
python3 -m unittest tests.test_fusion_admission tests.test_decision_engine tests.test_strong_startup tests.test_trend_continuation -v
```

Expected: PASS，且每项影响只出现一次、拥有明确 owner。

**Step 5: 提交本任务**

```bash
git add chanlun/fusion_admission.py chanlun/decision_engine.py chanlun/strong_startup.py chanlun/trend_continuation.py tests/test_fusion_admission.py tests/test_decision_engine.py tests/test_strong_startup.py tests/test_trend_continuation.py
git commit -m "refactor: 明确市场与确认规则归属"
```

## Task 5：实现信号日收盘价与分周期研究结果

**Files:**
- Modify: `run.py`
- Modify: `chanlun/recommendation_ledger.py`
- Modify: `chanlun/strategy_review.py`
- Test: `tests/test_recommendation_ledger.py`
- Test: `tests/test_strategy_review.py`

**Step 1: 写无未来泄漏的价格窗口测试**

使用固定 OHLC fixture 验证：

```python
entry = close[D]
t1_close = close[D + 1] / entry - 1
t3_mfe = max(high[D + 1:D + 4]) / entry - 1
t3_mae = min(low[D + 1:D + 4]) / entry - 1
```

必须额外断言：信号日盘中 high/low 不进入任何入场后 MFE/MAE；停牌或交易日不足时保持 `pending/insufficient`，不使用自然日补齐。

**Step 2: 运行测试，确认 `delay1_open` 与窗口语义失败**

Run:

```bash
python3 -m unittest tests.test_recommendation_ledger tests.test_strategy_review -v
```

Expected: immediate close、T+N 收盘或 D+1 窗口断言失败。

**Step 3: 增加研究结果合同**

账本和回看统一写入：

```python
{
    "entry_mode": "immediate_close",
    "entry_price": close_d,
    "intended_horizon": "T+3",
    "close_return": t3_close_return,
    "mfe": t3_mfe,
    "mae": t3_mae,
}
```

- 同时保留 `T+1/T+3/T+5` 的研究结果，主评分只读取 `intended_horizon` 对应的 `close_return`。
- 多来源同票保留各来源周期，最终主推另有唯一 `intended_horizon`；冲突未解决则降为观察。
- 旧 `delay1_open` 样本不静默改写；按版本/entry mode 分组，必要时用显式迁移脚本重算。

**Step 4: 重跑价格和成熟度测试**

Run:

```bash
python3 -m unittest tests.test_recommendation_ledger tests.test_strategy_review -v
```

Expected: PASS；fixture 中 T+1 收盘 `+5%`、期间最高 `+10%` 可同时得到。

**Step 5: 提交本任务**

```bash
git add run.py chanlun/recommendation_ledger.py chanlun/strategy_review.py tests/test_recommendation_ledger.py tests/test_strategy_review.py
git commit -m "feat: 增加收盘价分周期选股回看"
```

## Task 6：建立高收益版本选择与异常值支持规则

**Files:**
- Modify: `chanlun/strategy_review.py`
- Modify: `chanlun/policy_experiment_metrics.py`
- Modify: `scripts/run_policy_experiments.py`
- Test: `tests/test_strategy_review.py`
- Test: `tests/test_policy_experiment_metrics.py`
- Test: `tests/test_policy_experiment_runner_script.py`

**Step 1: 写版本比较失败测试**

每个版本按 `intended_horizon` 聚合并输出：样本数、活跃日、日均数量、平均/中位收盘收益、上涨率、`>=5%`、`<=-5%`、worst、MAE/MFE、时序稳定性与 Top-K 诊断。

锁定选择规则：

```python
outlier_driven = (
    candidate.mean_close_return > baseline.mean_close_return
    and candidate.median_close_return < baseline.median_close_return
    and candidate.hit_rate_ge_5 < baseline.hit_rate_ge_5
)
```

均值是第一排序；`outlier_driven=True` 的版本不能直接晋级。MFE 不参与第一排序，尾部指标披露但不自动否决非支配高收益版本。

**Step 2: 运行指标测试，确认失败**

Run:

```bash
python3 -m unittest tests.test_strategy_review tests.test_policy_experiment_metrics tests.test_policy_experiment_runner_script -v
```

Expected: 缺少分周期均值、稳健性支持或异常值标记的断言失败。

**Step 3: 实现分层 OOT 记分卡**

- 只比较相同池、相同 intended horizon、相同 entry mode 和明确版本边界。
- 数据真实性、防泄漏、成熟标签、最小样本和 OOT 是先决硬门；未过硬门不得进入收益排序。
- 晋级脚本不得把 scorecard 调用方提供的 `truth_verified`、`leakage_free`、`maturity_verified`、`oot_locked` 布尔值直接当作证据。影子评测另附只读 OOT attestation manifest；每个 baseline/candidate 条目同时绑定 `source_pool`、`strategy_version`、`intended_horizon`、`entry_mode`、`cutoff`、OOT 数据文件 SHA-256 和完整代码提交 SHA。脚本从 artifact 样本重算样本数、活跃日/月、平均/中位收盘收益和 `>=5%` 命中率，并要求数据文件内部合同、manifest 与 scorecard 三方一致；代码工作区有已跟踪未提交改动、代码 SHA 不一致、文件哈希不一致或任一合同字段/指标不一致时 fail-close。
- 当前 manifest 与数据文件仍可由调用方同时伪造并重新计算哈希，`source_record_hash` 也尚未反查受控账本或行情库，因此它只支持影子诊断，所有版本固定附加 `trusted_oot_provenance_unavailable`，不得产生 `selected_version`。正式晋级必须后续接入 recommendation ledger + `market_history.sqlite` 的只读反查，或由受信 CI 使用公钥可验证签名生成不可由调用方自签的证明。
- attestation manifest 通过 `--high-return-oot-attestation-json` 单独传入；只提供 `--high-return-scorecards-json` 时仍可生成诊断报告，但所有版本保持 `hard_gate_failed / oot_attestation_verified`，同样不得晋级。
- OOT 按时间顺序锁定，禁止随机打散或看过结果后继续调参；生产级切片至少 100 个 primary 完整成熟样本、20 个可形成 primary 完整样本的指标日期，并覆盖 2 个非重叠自然月，影子级为 30–99 个成熟样本或 10–19 个指标日期。
- 输出全量候选结果，不设生产 Top-K；Top-K 曲线仅用于观察排序边际质量。
- 分别显示整体、月份/滚动窗口、市场状态和来源池切片，避免一个短窗口的均值掩盖时序失效。

**Step 4: 重跑指标与脚本测试**

Run:

```bash
python3 -m unittest tests.test_strategy_review tests.test_policy_experiment_metrics tests.test_policy_experiment_runner_script -v
```

Expected: PASS；人工构造的极端单票高收益版本被标记为异常值驱动。

**Step 5: 提交本任务**

```bash
git add chanlun/strategy_review.py chanlun/policy_experiment_metrics.py scripts/run_policy_experiments.py tests/test_strategy_review.py tests/test_policy_experiment_metrics.py tests/test_policy_experiment_runner_script.py
git commit -m "feat: 增加高收益选股版本记分卡"
```

## Task 7：让页面名称、来源、周期和研究收益与合同一致

**Files:**
- Modify: `chanlun/report_view_model.py`
- Modify: `chanlun/report_assets/report-v2.js`
- Modify: `chanlun/report_assets/report-v2.css`
- Test: `tests/test_report_view_model.py`
- Test: `tests/test_report_generator.py`
- Test: `tests/test_report_comparison_frontend.py`

**Step 1: 写用户可见合同测试**

锁定以下页面语义：

- “基准”改为“基础候选”；后台仍为 `picks_pure`。
- “主推”只渲染 `picks_fusion` 的最终 `recommend` 子集。
- 候选卡展示来源策略；多来源同票并列展示各来源原因、状态和周期，不写“共振加分”。
- 主推卡、详情和回看显示唯一的 T+1/T+3/T+5 标签。
- 收益文案使用“信号日收盘价”“收盘收益”“期间最高”“期间最低”。
- 加速、罗姐、等确认、观察 Top5、看点 Top10、高弹性观察不得使用正式买入措辞。

**Step 2: 运行前后端合同测试，确认失败**

Run:

```bash
python3 -m unittest tests.test_report_view_model tests.test_report_generator tests.test_report_comparison_frontend -v
```

Expected: Tab 名称、来源、周期或收益标签断言失败。

**Step 3: 最小修改 view model 与渲染**

先在 view model 形成稳定字段，再由 JavaScript 纯展示；不要在前端重新推断来源状态、推荐资格或 intended horizon。缺少关键字段时显示“数据不足/周期未确认”，并从主推动作区移除。

**Step 4: 运行合同测试与 JavaScript 语法检查**

Run:

```bash
python3 -m unittest tests.test_report_view_model tests.test_report_generator tests.test_report_comparison_frontend -v
node --check chanlun/report_assets/report-v2.js
```

Expected: 全部 PASS，JavaScript 无语法错误。

**Step 5: 提交本任务**

```bash
git add chanlun/report_view_model.py chanlun/report_assets/report-v2.js chanlun/report_assets/report-v2.css tests/test_report_view_model.py tests/test_report_generator.py tests/test_report_comparison_frontend.py
git commit -m "feat: 对齐选股池页面与收益标签"
```

## Task 8：端到端回放、版本选择和用户可见验收

**Files:**
- Modify: `docs/plans/2026-08-20-auxiliary-decision-copilot-design.md`
- Modify: `docs/plans/2026-08-20-auxiliary-decision-copilot-implementation.md`
- Modify only if a regression is found: files owned by Tasks 1-7

**Step 1: 跑核心选股回归集**

Run:

```bash
python3 -m unittest tests.test_candidate_funnel tests.test_recommendation_ledger tests.test_strong_startup tests.test_trend_continuation tests.test_fusion_admission tests.test_decision_engine tests.test_h4_t3_pool tests.test_h4_production_boundary tests.test_strategy_review tests.test_policy_experiment_metrics tests.test_report_view_model tests.test_report_generator tests.test_report_comparison_frontend -v
```

Expected: 全部 PASS。

**Step 2: 跑全量测试和静态校验**

Run:

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile run.py chanlun/candidate_funnel.py chanlun/recommendation_ledger.py chanlun/strong_startup.py chanlun/trend_continuation.py chanlun/fusion_admission.py chanlun/decision_engine.py chanlun/h4_t3_pool.py chanlun/strategy_review.py chanlun/policy_experiment_metrics.py chanlun/report_view_model.py
node --check chanlun/report_assets/report-v2.js
git diff --check
```

Expected: 全部退出码为 0。

**Step 3: 运行历史回放与 policy experiments**

按冻结数据窗口生成基线与候选版本结果，至少输出：

- 分来源池、分 T+1/T+3/T+5、分版本的 mature 样本数和活跃日。
- 平均/中位收盘收益、`>=5%` 命中率、上涨率、`<=-5%`、worst、MAE/MFE、时序切片。
- 异常值驱动标记、研究硬门结果和非支配比较。
- 每日实际过门数量分布与 Top-K 诊断，但不得据此截断主推。

Expected: 只有通过真实性、防泄漏、成熟标签和 OOT 硬门的版本进入最终比较；高收益版本必须通过稳健性支持规则。

**Step 4: 生成本地 debug 报告并做桌面/移动端验收**

用户可见验收清单：

- “基础候选”能看到来源标签，且不会被写成正式推荐。
- “主推”只包含最终 recommend，允许当天为空且无回填。
- 每只主推显示 T+1/T+3/T+5 之一，以及信号日收盘价。
- 成熟样本同时显示收盘收益、期间最高、期间最低；例如 `+5% / +10%` 不再互相覆盖。
- 观察池、加速和罗姐池没有买入措辞；多来源同票没有自动共振升级。
- H4 T+3 v1 输出与冻结基线一致。

**Step 5: 更新本地验收记录并提交**

只记录实际运行得到的测试数量、回放窗口、样本数、收益结果和截图路径，不预写通过结论。

```bash
git add docs/plans/2026-08-20-auxiliary-decision-copilot-design.md docs/plans/2026-08-20-auxiliary-decision-copilot-implementation.md
git commit -m "docs: 记录高收益选股优化验收"
```

## Task 9：补齐风险原因独立字段与页面展示

**Files:**
- Modify: `chanlun/auxiliary_decision.py`
- Modify: `chanlun/market_news.py`
- Modify: `chanlun/report_view_model.py`
- Modify: `chanlun/report_assets/report-v2.js`
- Test: `tests/test_auxiliary_decision.py`
- Test: `tests/test_market_news.py`
- Test: `tests/test_report_view_model.py`

**Step 1: 写风险原因合同失败测试**

断言负向方向或页面显示“风险成立”时，`risk_reasons` 至少有一条；每条包含非空 `reason`、`impact` 和 `evidence_refs`。摘要、`next_trigger`、`invalidation` 或通用风险标签即使非空，也不能替代该字段。

**Step 2: 运行测试，确认当前字段缺失**

Run:

```bash
python3 -m unittest tests.test_auxiliary_decision tests.test_market_news tests.test_report_view_model -v
```

Expected: 风险方向缺少独立原因列表，新增断言失败。

**Step 3: 最小扩展 LLM、规则回退和 view model 合同**

统一输出：

```python
"risk_reasons": [
    {
        "reason": "具体风险事实",
        "impact": "对方向或关联股票的可能影响",
        "evidence_refs": ["evidence-id"],
    }
]
```

- LLM prompt、解析器、规则回退和报告 view model 都保留该字段。
- 风险方向没有合格原因时降为 `partial/insufficient`，页面不得只显示“风险成立”。
- 该字段仅用于解释和审计；不得在本任务中新增选股扣分或硬门。

**Step 4: 重跑测试和 JavaScript 检查**

Run:

```bash
python3 -m unittest tests.test_auxiliary_decision tests.test_market_news tests.test_report_view_model -v
node --check chanlun/report_assets/report-v2.js
```

Expected: PASS；页面可逐条显示原因、影响和证据。

**Step 5: 提交本任务**

```bash
git add chanlun/auxiliary_decision.py chanlun/market_news.py chanlun/report_view_model.py chanlun/report_assets/report-v2.js tests/test_auxiliary_decision.py tests/test_market_news.py tests/test_report_view_model.py
git commit -m "feat: 增加风险原因独立展示"
```

## 最终上线门槛

满足以下条件后，候选版本才可以替换当前生产选股版本：

1. 所有研究硬门通过，且没有信号日 high/low 泄漏进 D+1 之后的路径指标。
2. `picks_pure`、主推和观察的账本归因与页面数量完全一致。
3. 候选版本在锁定 OOT 窗口逐 `intended_horizon` 的平均收盘收益优于基线，且中位数与 `>=5%` 命中率不同时劣于基线；每个生产级比较切片至少 100 个 primary 完整成熟样本、20 个可形成 primary 完整样本的指标日期，并覆盖 2 个非重叠自然月。
4. 结果按 intended horizon 和来源池可重算、可解释、可回滚；不跨周期混算均值。
5. H4 v1 冻结回归通过；加速与罗姐池仍保持观察身份。
6. 用户确认本地报告的页面语义和收益展示后，再单独授权正式日报生成、提交或发布。
7. 每条负向方向都能独立展示具体风险原因、可能影响与证据，不再用“风险成立”代替解释。

本文件记录实施任务与验收门。Tasks 1-9 已在隔离分支 `codex/stock-selection-high-return` 实现；独立复审后追加了生产/影子周期边界、逐来源时效/admission/评分/位置/决策、明确的聚合代表来源、页面观察封顶、来源级漏斗失败、H4 趋势 variant 与异常隔离、旧入场口径兼容和 OOT attestation 修复。历史证据仍未产生通过 OOT 生产门的高收益胜者，默认只运行影子审计，且尚未生成或发布正式日报。
