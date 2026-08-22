# 选股影子评测上线设计

## 1. 目标

在不改变现网“主推”结果、不降低正式提示收益边界的前提下，把独立策略候选以影子方式持续记录、按信号日收盘价回看，并在正式日报中展示真实样本进度、收益和未晋级原因。

本阶段只让影子评测真正上线，不授权任何影子版本接管正式主推。各策略池继续拥有自己的候选、周期、门槛和失效逻辑；`picks_pure` 只作为共同上游全集，不统一各池算法。

## 2. 方案选择

### 方案 A：直接合并现有高收益 PR，再补页面卡片

不采用。现有 PR 的 `shadow` 只阻止周期切换，却仍无条件改变逐来源 admission、时效过滤、决策聚合、强势启动质量门和 H4 输入，可能直接改变正式 `picks_fusion`。

### 方案 B：在现有大提交中逐个增加运行开关

不采用。正式链和研究链已经交织在多个阶段，逐点加开关容易遗漏共享对象、H4、推荐账本或漏斗等下游消费者，无法形成可证明的生产不变性。

### 方案 C：从最新生产 `main` 增加独立影子通道

采用。正式链维持现状；影子模块只接收正式结果或独立池结果的深拷贝，写入独立账本、独立评测合同和独立页面卡片。影子异常时正式日报继续发布。

## 3. 架构与数据流

```text
picks_pure 共同上游全集
├─ 现网原路径 → picks_fusion → 主推/H4/正式推荐账本
└─ 独立影子注册表
   ├─ next_day_boom · T+1
   ├─ H4 T+3 · T+3
   └─ 后续各池自己的 shadow builder
       → 深拷贝 → 影子候选 → 影子账本 → 收盘价回看
                                      → shadow_evaluations
```

第一期只登记具有明确来源池、版本、`intended_horizon` 和 `entry_mode=immediate_close` 的实验。没有明确周期的池子不生成假卡片，也不跨池、跨周期拼样本。

正式输出在影子执行前后计算规范化 SHA-256。规范化内容至少包含主推股票代码和顺序、最终决策、原因、页面动作及研究价字段。摘要不一致时丢弃影子结果并标记 `production_guard_failed`；正式日报仍使用影子执行前的数据。

## 4. 顶层合同

正式日报新增独立字段 `shadow_evaluations`：

```json
{
  "schema_version": 1,
  "mode": "shadow",
  "affects_production": false,
  "status": "collecting",
  "started_at": "2026-08-22",
  "production_guard": {
    "unchanged": true,
    "before_sha256": "...",
    "after_sha256": "..."
  },
  "production_reference": {
    "pool": "picks_fusion",
    "today_count": 4,
    "intended_horizon": null,
    "comparison_eligible": false,
    "reason": "现网主推未声明统一主周期，只作数量与隔离参考"
  },
  "experiments": []
}
```

每个 `experiments[]` 记录：

- `experiment_id`、`display_name`、`strategy_version`；
- `upstream_pool`、`source_pool`、`intended_horizon`、`entry_mode`；
- `today.candidates[]`，逐票标注“影子研究，不是推荐”；
- `sample_size`、`active_dates`、`active_months`；
- `mean_close_return`、`median_close_return`、`up_rate`、`hit_rate_ge_5`；
- `mean_mfe`、`mean_mae`、`worst_close_return`；
- `research_tier`、`comparison_status`、`promotion_eligible=false`；
- `hard_gate_reasons[]` 和 `representative_samples[]`。

影子账本与正式推荐账本分离。影子条目固定包含 `evaluation_role=shadow_candidate`、`publication_effect=false`、`evaluation_eligible=true/false`、来源池、版本、周期、信号日收盘价及原因快照。影子条目永远不能进入正式推荐 ID、主推数量、H4 输入或正式漏斗。

## 5. 收益口径

- 入场：信号日正式收盘价。
- T+1/T+3/T+5：对应未来交易日收盘价。
- 期间最高/最低：只使用 D+1 到 D+N，排除信号日盘中高低价。
- 未成熟、停牌、缺行情和非最终 K 线：显示不可评估，不按 0 处理。
- 主指标：对应 `intended_horizon` 的平均收盘收益。
- 稳健支持：中位收盘收益和 `>=5%` 命中率；二者相对参照同时下降时标记“异常值驱动”。
- 没有同池、同周期、同入场口径基线时只展示结果，不产生晋级比较。
- 生产晋级仍要求至少 100 个成熟样本、20 个有效日期、2 个非重叠月份，以及可信 OOT 来源；本阶段所有实验固定 `promotion_eligible=false`。

## 6. 页面位置与字段映射

页面位置固定为：**辅助决策驾驶舱 → 策略记分牌之后 → 数据诊断之前 →「影子评测」**。

| 后台字段 | 页面中文位置 |
| --- | --- |
| `mode` | 卡片徽标“影子评测中” |
| `affects_production=false` | 保护条“不影响正式主推” |
| `production_guard.unchanged` | “正式主推校验通过/失败” |
| `production_reference.today_count` | “现网主推 N 只” |
| `display_name + intended_horizon` | 实验标题，如“H4 T+3 · T+3” |
| `today.candidates` | “今日影子研究名单（不是推荐）” |
| `sample_size/active_dates/active_months` | “样本进度 N/100 · N/20日 · N/2月” |
| `mean_close_return` | “平均收盘收益” |
| `median_close_return` | “中位收盘收益” |
| `hit_rate_ge_5` | “≥5%命中率” |
| `up_rate` | “上涨率” |
| `mean_mfe/mean_mae` | “期间最高／期间最低” |
| `comparison_status` | “当前结论” |
| `hard_gate_reasons` | “尚未晋级原因” |
| `representative_samples` | “逐票回看” |

页面不截断影子候选，不用 Top-K 改变生产数量。视觉沿用现有日报的冷白信息面板，以蓝色状态、细分隔线和左右指标网格突出“正式保护轨道”，不添加虚构数据或装饰文案。

## 7. 错误处理

- 影子构建器收到深拷贝；修改共享对象视为测试失败。
- 单个实验异常只将该实验标为 `unavailable`，其他实验继续。
- 整体影子模块异常时输出真实错误状态和空实验，正式日报继续生成。
- 正式摘要变化时 fail-close，影子结果不落账、不展示为有效。
- 影子账本先写 pending；只有正式日报校验通过后才固化。
- 周末或尚无首个收盘日时显示“已启用，等待首个收盘样本”，不回填已经看过的历史日期冒充 OOT。

## 8. 上线验收

必须同时证明：

1. 全量测试、Python/JavaScript 语法和差异检查通过。
2. 固定输入下影子开关前后的正式主推摘要完全一致。
3. 影子异常不影响正式日报生成。
4. 当日或最新公开 JSON 存在 `shadow_evaluations`，且 `affects_production=false`、`production_guard.unchanged=true`。
5. Git 远端 `main` 包含上线提交，日报发布任务退出码为 0。
6. GitHub raw JSON 与 Pages 页面均能看到“影子评测”和“不影响正式主推”。
7. 桌面端与 390px 移动端可见样本进度、收益、未晋级原因和真实空状态。
8. 页面数值可从影子账本和 `market_history.sqlite` 重算；影子代码未进入主推、H4、正式账本或正式漏斗。

上线完成后再对辅助模块做独立审查，按“会误导决策/数据不可用/展示可改进”分级；任何会改变选股池或正式主推的建议继续先进入影子，不直接切生产。
