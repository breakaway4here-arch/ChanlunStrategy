# 影子评测运行时采集事故复盘

> 日期：2026-08-26
> 事故范围：H4 `picks_pure` 上游影子评测
> 影响等级：正式选股 P0 无影响；选股优化研究 P0 中断
> 历史缺口：2026-08-24、2026-08-25

## 1. 结论

上次发布验证了代码、2026-08-21 冻结快照、公开 JSON、Pages 资源和页面展示，但没有验证部署后的首个正式交易日能否从真实 `report_data` 持续冻结新 cohort。因此当时使用“影子评测已上线”表述过宽；准确说法应是“静态发布面已上线，动态采集待正式交易日验证”。

2026-08-24、2026-08-25 的失败不是因为没有 T+3 数据。链路在 H4 实验运行、行情回看和 pending staging 之前就失败了，错误为：

```text
production output contains an invalid NumPy array
```

两日没有 D 日冻结名单和信号日收盘价事实，不能在 2026-08-26 直接取“三天前数据”补成前瞻样本。它们保留为 `data_gap`；若未来具备可证明的 point-in-time 输入，只能建立独立的 `historical_shadow/replay`，不能并入 `oot_shadow`。

## 2. 时间线

| 日期 | 事件 | 当时结论 | 现在的校正 |
|---|---|---|---|
| 2026-08-21 | 冻结报告用于辅助决策与影子页面修复 | 可用于静态合同和页面验收 | 不能替代未来正式运行验收 |
| 2026-08-22 | `f5ae792` 发布影子评测与辅助决策 | 代码、受保护快照、Raw/Pages 和 DOM 通过 | 发布面完成；持续采集尚未证明 |
| 2026-08-24 | 首个后续正式日报发布 | 正式选股正常，影子显示 unavailable | 影子在实验前失败，本日为数据缺口 |
| 2026-08-25 | 第二个正式日报发布 | 同上 | 连续失败证明不是偶发 T+3 未到期 |
| 2026-08-26 | 运行时链路审计与修复 | 确认 raw/public 投影不一致 | 建立共享公开投影、H4 最小输入和三层状态 |

## 3. 直接原因

影子入口对除 `shadow_evaluations` 外的整份 raw `report_data` 做严格 `json_native_projection`，同时把这个结果用于：

1. 定义正式输出保护摘要；
2. 向 H4 builder 提供策略输入。

正式日报却通过 `report_generator.py` 的字段级公开投影、轻量聚合投影和 `NpEncoder` 发布。raw 对象含有公开报告并不发布的 NumPy/日期/瞬态结构，于是出现两套不一致的“正式输出定义”：日报可以成功序列化并发布，影子 guard 却在进入实验前失败。

原异常处理又把嵌套投影错误统一包装为 `invalid NumPy array`，丢失 JSON path，导致定位时只能看到类型，不能看到具体字段。

## 4. 系统性原因

### 4.1 验收对象选错

发布验收聚焦修复后的 2026-08-21 冻结快照。它证明页面和历史数据面一致，却没有证明 2026-08-24 的真实生产对象能经过影子入口。

### 4.2 测试 fixture 过于干净

既有测试使用手工构造的纯 Python/JSON 字段，没有覆盖生产态 `report_data` 中的 NumPy array/scalar、NaN、datetime/object array、bytes 和未发布瞬态对象。

### 4.3 writer 与 guard 各自定义公开边界

writer 有字段级投影，guard 则默认“raw 除 shadow 外全部是正式输出”。两者没有同源函数，也没有“projector 产物等于真实 writer 产物”的契约测试。

### 4.4 页面把不同状态压成一个文案

页面只区分 collecting/disabled/unavailable，导致“采集链路失败”“今天正常零候选”“T+3 尚未到期”“样本不足以比较”都可能被理解成同一种“暂不可用”。

### 4.5 发布门禁缺少动态 canary

原门禁检查了 Git、测试、受保护快照、Pages asset、Raw JSON 和 DOM，却没有要求部署后首个正式交易日必须出现 available experiment 与 staged pending batch。

## 5. 哪些保护实际生效

- 影子顶层异常 fail closed，正式选股、正式推荐账本和日报发布没有被影子错误阻断。
- `affects_production=false` 与正式摘要保护边界阻止影子结果自动进入正式主推。
- 公开页面没有展示未经验证的研究收益。
- 正式日报连续可用，使故障被限定在研究证据采集，不是正式选股事故。

## 6. 哪些保护没有生效

- 没有成功冻结 2026-08-24、2026-08-25 的影子候选。
- 没有 pending 批次可供 finalizer 归档。
- 没有路径化错误，首次只看到笼统 NumPy 报错。
- 页面没有明确告诉用户“本日形成数据缺口”，也没有说明它与 T+3 尚未成熟无关。
- 上线结论没有区分“静态发布完成”和“动态采集已验证”。

## 7. 修复方案及自动化证据

| 修复 | 防止的问题 | 自动化证据 |
|---|---|---|
| full daily / aggregate light 共享公开 projector | writer 与 guard 漂移 | projector 与实际 writer 产物相等测试 |
| guard 只摘要实际公开正式输出 | 未发布 raw 瞬态值阻断影子 | 未发布 NumPy/对象字段不改变正式摘要测试 |
| H4 builder 使用显式最小输入 | 任意 raw 字段污染模型入口 | production-like fixture 与未使用脏字段测试 |
| 路径化 `ShadowInputProjectionError` | 错误只有类型没有位置 | 必需字段非法时包含 `$.picks_pure[i].field` 测试 |
| `collection_health` | 采集失败与正常空池混淆 | 零候选仍 staged empty batch；失败不 staging 测试 |
| `outcome_maturity` | T+3 未到期被当系统失败 | T+1/T+3/T+5 mature/right-censored/unavailable 统计测试 |
| `comparison_readiness` | 首个到期样本被称为策略成熟 | 100 样本/20 日/2 月门槛与永不自动晋级测试 |
| finalizer 严格校验 schema、隔离声明、正式双摘要、采集健康、`data_gap` 和批次摘要 | 旧/损坏/失败批次被误归档 | schema、隔离、guard、data gap 与摘要反例全部拒绝测试 |
| 页面三层展示 | 用户只能看到“暂不可用” | 采集成功 0 只、数据缺口、T+3 到期与人工验收状态测试 |
| Pages asset SHA 审批 | 未审查前端进入修复发布 | approved asset hash 门禁测试 |

本轮最终全量回归：1222 项测试通过。

## 8. 新的上线完成定义

影子评测以后分四个验收层级，必须逐层记录：

1. **代码完成**：相关测试与全量测试通过。
2. **发布面完成**：远端 SHA、workflow、Raw/Pages JSON、JS/CSS 和桌面/移动 DOM 一致。
3. **动态采集完成**：部署后的首个正式交易日满足 `collection_health=ok|partial`、experiment available、正式摘要 before/after 相同、pending staged，零候选允许。
4. **收益推进完成**：首个 T+1、T+3 按交易日收盘推进；这只证明数据成熟，不代表策略已达到人工比较门槛。

任何结论都只能使用已经通过的层级，禁止用第 2 层替代第 3 层。

## 9. 后续责任清单

- [x] 统一 writer 与 guard 的公开投影。
- [x] 建立 H4 最小输入和路径化错误。
- [x] 增加采集健康、收益成熟度、比较准备度。
- [x] 收紧 finalizer 授权。
- [x] 更新页面解释与生产态 fixture。
- [x] 全量测试通过。
- [ ] 合并并发布到远端 `main`。
- [ ] 验证 Raw/Pages 与桌面/390px 移动页面。
- [ ] 15:00 后验证首个正式 cohort staging/finalize。
- [ ] 后续验证首个 T+1 与 T+3 状态推进。
