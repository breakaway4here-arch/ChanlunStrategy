# 影子评测运行时修复设计

> 日期：2026-08-26
> 状态：已确认，授权实施
> 作用域：只修复 H4 影子评测采集、状态与发布保护；不修改正式选股结果，不扩展到其他独立策略池。

## 1. 事故与严重性

2026-08-24、2026-08-25 的正式日报均成功发布，但 `shadow_evaluations` 在实验构建和账本 staging 之前返回 `unavailable`：

```text
production output contains an invalid NumPy array
```

因此两日没有冻结影子 cohort、没有实验行、没有 pending 批次，也没有可在 T+1/T+3/T+5 成熟的影子样本。

- 正式选股与日报：未受影响，既有 fail-closed 隔离生效。
- 选股优化研究：P0。继续运行不会积累任何可比较证据。
- 这不是缺少 T+3 行情；失败发生在读取历史行情和计算成熟度之前。

## 2. 根因边界

影子入口在公开报告生成之前，对除 `shadow_evaluations` 外的整份 raw `report_data` 调用严格 `json_native_projection`。该投影会把 NumPy 数组转为列表后递归验证，但把所有嵌套异常统一包装成 `invalid NumPy array`，既丢失字段路径，也把未发布的运行时瞬态对象纳入正式保护范围。

正式日报走另一条路径：字段级公开投影、K 线数组切片、`_safe_list`、`NpEncoder`，再写 full daily 与 aggregate light JSON。于是形成两套不一致的“正式输出定义”：公开报告可以发布，而 raw 保护投影先失败。

根因不是“少兼容一种 NumPy 类型”，而是把三个职责混在了一个 raw 投影中：

1. 定义实际公开的正式输出；
2. 证明影子运行前后正式输出未变；
3. 为 H4 影子策略准备模型输入。

## 3. 决策

采用双层隔离方案：

### 3.1 权威正式输出保护

在 `report_generator.py` 抽出两个纯投影：

- full daily：每日 JSON、首页 inline data、归档页共同使用；
- aggregate light：`data.json` 使用。

writer 与 shadow guard 必须调用同一组 projector。guard 对排除 `shadow_evaluations` 后的组合 envelope 计算 canonical SHA-256：

```json
{
  "daily": "<full daily formal projection>",
  "aggregate": "<aggregate light formal projection>"
}
```

未被任何公开 projector 发布的 raw 瞬态字段不进入正式摘要；新增正式字段只有进入共享 projector 才能发布，因此一旦发布就自动受 guard 保护。共享 projector 失败、before/after 不一致、writer 与 projector 不一致时均 fail closed。

### 3.2 H4 最小影子输入

H4 影子策略不再接收整份 raw `report_data`，也不直接接收公开展示裁剪后的 picks。输入只保留：

- 报告日期；
- `picks_pure` 中 H4 固定特征真正读取的字段；
- code/name 与信号日正式收盘证明；
- H4 pool attestation、模型版本与策略身份；
- 影子候选公开展示所需字段。

最小输入严格投影并深拷贝；模型输入 before/after 另做内部完整性检查。正式输出 SHA 是权威 `production_guard`。

`picks_pure` 仍只是所有策略共同上游全集。H4 保持自己的特征、模型和门槛；本次不改变次日爆发、罗姐池等策略逻辑。

### 3.3 三层状态合同

页面与数据合同不再用一个 badge 混合系统健康和样本成熟：

1. `collection_health`
   - `ok | partial | collection_failed | disabled`
   - 记录 `failure_stage`、`error_code`、`candidate_count`、`staged_count`。
   - 成功但零候选显示“采集成功，今日 0 只”，不是不可用。
2. `outcome_maturity`
   - T+1/T+3/T+5 分别统计 `mature | right_censored | unavailable`。
   - 单个 T+3 到期只表示“已有到期样本”，不等于策略成熟。
3. `comparison_readiness`
   - `insufficient | maturing | ready_for_manual_review`。
   - 同一 strategy/version/upstream/source/intended_horizon/entry_mode 达到 100 个成熟样本、20 个有效日期、2 个自然月后才可人工验收。
   - `promotion_eligible` 始终为 `false`，绝不自动替换正式策略。

旧 `status=collecting|partial|unavailable|disabled` 暂时保留兼容，前端以三层状态为权威，并为历史 payload 提供保守映射。

## 4. 历史日期与未来函数

2026-08-24、2026-08-25 记录为 `data_gap`。两日没有在当时冻结的影子 cohort，不能用今天的代码倒推名单并冒充前瞻 OOT。

未来收益补齐不属于未来函数：只要 D 日名单和信号日正式收盘价已经冻结，后续使用 D+1/D+3/D+5 final qfq 行情评价即可。修复后的第一批真实 cohort 会自动按交易日历推进，无需人工“取三天前的数据”。

历史回放属于独立后续需求。只有当日 point-in-time 输入、commit/config/model SHA、截至 D 的行情和 final close 均可证明时才允许生成，并必须标记 `research_tier=historical_shadow/replay`；永远不覆盖原 gap，也不并入 `oot_shadow` 晋级门槛。

## 5. 失败处理

- 任一阶段失败：不 staging，不 finalize，不展示研究指标。
- 错误必须包含 `failure_stage` 与 JSON path，但不输出原始敏感值。
- 正式摘要不一致：`production_guard_failed`，正式报告继续按既有 fail-closed 边界发布。
- 影子候选为零：生成合法空批次及 digest，证明采集链路运行成功。

## 6. 验收合同

1. production-like NumPy/NaN/日期数组/bytes 不再因无关 raw 字段阻断影子。
2. 公开 projector 与实际 full daily、inline/archive、aggregate light 一致。
3. off/shadow 两次运行的所有正式公开字段语义摘要完全一致。
4. H4 builder 只能看到最小输入，且不能修改正式报告。
5. 失败不写账本；成功零候选形成合法 staged empty batch。
6. T+1/T+3/T+5 使用交易日收盘；MFE/MAE 仅统计 D+1 至目标日。
7. 页面明确区分采集失败、正常空池、周期到期和人工比较资格。
8. 全量测试通过；远端 SHA、Pages workflow、Raw/Pages JSON、桌面与移动端一致。
9. 首个正式 cohort 的 staging/finalize 成功；随后继续验证首个 T+1、T+3 状态推进。
