# 辅助决策驾驶舱设计

## 1. 背景与结论

当前“辅助决策中心”把市场情绪、板块资金、涨停情绪、事件驱动、卖出提醒、策略回看和诊断平铺成同权卡片，但用户真正需要的是一条可行动的判断链：

```text
今天发生了什么
→ 哪个方向得到盘面验证
→ 与我的重点观察股有什么关系
→ 下一步等什么条件
→ 什么情况说明判断失效
```

本次不继续扩充卡片数量，而是重构为“证据底座 + 决策摘要 + 重点观察池 + 持仓风控 + 策略验证”的决策驾驶舱。

## 2. 当前问题的证据

### 2.1 涨停情绪是解析失败，不是市场没有涨停

- `fetch_limit_up_pool()` 会把接口字段 `fbt` 交给 `_fmt_btime()`。
- 实际接口已可能返回整数，例如 `92500`；当前实现直接调用 `len(raw)` 和切片。
- 单条解析异常被循环中的 `except` 吞掉，因此接口有名单时仍可能返回空数组。
- 2026-08-20 已发布快照中，情绪证据保存了涨停总数，但 `limit_up_pool` 为空，页面误显示“暂无涨停池”。

### 2.2 事件 LLM 结果丰富，但页面只展示一句话

事件数据已有：

- `analysis`
- `positive_sectors` / `negative_sectors`
- `positive_stocks` / `negative_stocks`
- `impact_score`
- `market_validation`
- `tradability`

当前前端只渲染标题和 `impact.summary`，没有展示板块、个股、盘面证据，也没有与候选池或用户重点池做交叉关联。

### 2.3 卖出提醒没有持仓语义

当前 `sell_signals` 来自全市场缠论结果，只要出现卖点就进入列表，并未与用户真实持仓求交集。全市场风险样本被误命名为“卖出提醒”，会产生并不存在的操作指令。

### 2.4 策略回看无法归因

当前回看把近期信号按代码去重后全量展示，但历史记录缺少：

- 当时的 `decision_code`
- 推荐规则及贡献策略
- 推荐理由快照
- 策略/配置/代码版本
- 市场状态
- 可执行入场与退出口径

因此 observe/reject 也可能被前端标成“推荐日”，且无法回答“哪条策略导致推荐、该策略历史表现如何”。

## 3. 产品目标

1. 用户打开辅助区后，十秒内知道当天最重要的方向、证据强弱和下一确认条件。
2. 用户的五只重点观察股每天都被分析，不依赖它们是否进入选股池。
3. 观察股与真实持仓严格分离，不从观察池推断卖出动作。
4. LLM 参与事件仲裁、方向聚类、关联分析和条件推演，而不是只写摘要。
5. 所有 LLM 结论可追溯到结构化证据；失败时明确降级。
6. 策略回看先展示可解释的策略统计，再允许下钻到单次推荐。

## 4. 非目标

1. 不让 LLM 自由生成行情数字、收益率或无证据的“龙头”。
2. 不把事件催化直接等价为买入信号。
3. 不把历史观察、拒绝信号伪装成推荐样本。
4. 不使用旧的 `holdings/accounts.yaml` 示例作为真实持仓。
5. 不覆盖或混入主工作区现有的未提交改动。
6. 不修改核心选股算法来迎合辅助区展示。

## 5. 信息架构

### 5.1 市场证据底座

保留现有“市场情绪”和“板块资金”，新增可审计的涨停生态：

- 涨停总数、跌停总数
- 解析数量、覆盖率、数据状态和时间
- 最高连板、最早封板
- Top 题材及数量
- 龙头候选的事实角色
- 与重点观察池的交集

### 5.2 今日决策摘要

最多展示三个方向簇，允许少于三个，也允许明确显示“今日无有效主催化”。每个方向按以下证据链展示：

```text
事件/催化
→ 方向与板块
→ 资金/涨停验证
→ 被新闻点名、涨停领先或板块强势的股票
→ 候选池/重点观察池交集
→ 下一确认条件
→ 失效条件
```

至少保留一个负向或风险方向的展示能力，避免只呈现利好叙事。

### 5.3 我的重点观察池

初始配置：

| 优先级 | 代码 | 名称 | 角色 |
| --- | --- | --- | --- |
| 1 | 300139 | 晓程科技 | strong_watch |
| 2 | 002281 | 光迅科技 | strong_watch |
| 3 | 300308 | 中际旭创 | strong_watch |
| 4 | 688041 | 海光信息 | strong_watch |
| 5 | 688525 | 佰维存储 | strong_watch |

每只股票固定展示：

- `as_of` 与数据状态
- 相对上一交易日的事实变化；新加入时显示“新增关注”
- 关联方向、事件和板块证据
- 当前结构摘要
- 状态：`可计划 / 等确认 / 回避 / 数据不足`
- 下一确认条件与失效条件
- 用户 thesis 与 LLM 判断分栏

“可计划”必须通过确定性硬门控；LLM 只能解释，不能单独升级状态。

### 5.4 持仓风控

只有 `fresh + confirmed` 的真实持仓才参与卖出提醒。持仓合同至少包含：

- `source`
- `as_of`
- `confirmed_at`
- `stale_after`
- `code`
- 可选成本、数量和仓位

页面只展示真实持仓与全市场 `sell_signals` 的交集。未配置或已过期时，不显示任何个股卖出动作。

### 5.5 策略验证

默认 cohort 同时要求当时 `decision_code=recommend`、`publication_status=published`、`user_action=recommendation`；内部观察池即使门控为 recommend 也不计入策略收益。observe/reject 与 watch/none 分开作为门控和发布效果展示。主屏按策略展示：

- 成熟样本数与样本不足状态
- T+1 / T+3 / T+5 胜率
- 中位收益、均值、相对基准超额
- MAE / MFE
- 代表性正负样本

每次推荐写入不可变推荐账本：

```json
{
  "recommendation_id": "...",
  "signal_id": "...",
  "decision_code": "recommend",
  "reason_snapshot": [],
  "strategy_contributions": [
    {"strategy_id": "...", "role": "primary", "version": "..."}
  ],
  "policy_version": "...",
  "config_hash": "...",
  "code_commit": "...",
  "market_regime": "...",
  "entry_rule": "...",
  "entry_price": null
}
```

收益统计必须先锁定可执行口径：前复权、权威交易日历、入场时点、显式 horizon、推荐/入场/目标日终局性、停牌/涨停不可成交、成熟样本、逐期限基准日期对齐、右删失、重复 episode 和跨策略归因。个股缺 K 线不得把下一根 K 线顺延成目标交易日；日报验收通过前只能形成 provisional batch，不能进入永久账本。

## 6. 数据合同

### 6.1 `limit_up_snapshot`

```json
{
  "date": "2026-08-20",
  "as_of": "2026-08-20T15:10:00+08:00",
  "generated_at": "...",
  "source": "eastmoney_limit_pools",
  "status": "verified_complete",
  "raw_total": 79,
  "limit_down_total": 12,
  "parsed_count": 79,
  "parse_error_count": 0,
  "coverage": 1.0,
  "items": [],
  "theme_groups": [],
  "leaders": [],
  "error": ""
}
```

状态枚举：

- `verified_complete`
- `verified_empty`
- `partial`
- `missing`
- `error`

只有 `raw_total=0 + verified_empty` 才表示确实没有涨停。空 `items` 不能单独解释为零。接口总量超过单页上限时必须分页或标记 partial。

旧的 2026-08-20 报告只用于证明“总量非零但名单为空”的矛盾。当前重新抓取的名单属于历史重建，必须标记 `historical_reconstruction`，不得覆盖或冒充原始快照。

### 6.2 `decision_brief`

```json
{
  "status": "ok",
  "model": "...",
  "prompt_version": "...",
  "schema_version": "1",
  "generated_at": "...",
  "theses": [
    {
      "thesis_id": "...",
      "direction": "positive",
      "stage": "confirmed",
      "confidence": "medium",
      "evidence_refs": [],
      "sector_links": [],
      "stock_links": [],
      "watchlist_impacts": [],
      "next_trigger": [],
      "invalidation": []
    }
  ],
  "arbitration": []
}
```

每条事件仲裁记录保留：

- `rule_score`
- `rule_result`
- `llm_result`
- `arbitration_result`
- `arbitration_reason`
- `model`
- `prompt_version`
- `schema_version`

`stock_links` 必须带 `link_type` 和 `evidence_ref`。允许的事实角色包括：新闻点名、涨停领先、板块强势、重点池交集、候选池交集。仅通过代码名称校验不能称为龙头。

### 6.3 重点池配置与分析快照

配置态与分析态分离：

- canonical 配置保存用户想关注什么。
- 日报快照保存本次生成时真正分析了哪个 revision。

配置至少包含：

- `schema_version`
- `revision` / `etag`
- `updated_at` / `updated_by`
- `enabled`
- `added_at`
- `code`
- `role`
- `priority`
- `tags`
- `note` / `thesis`

股票名称由代码映射生成，不信任任意输入名称。

## 7. LLM 工作边界

### 7.1 LLM 负责

- 新增催化与盘面复盘的语义区分
- no-impact 复核与可审计仲裁
- 多事件语义去重和方向聚类
- 事件、板块、候选池、重点池的关联解释
- 确认/失效条件的自然语言组织
- 基于确定性聚合数据生成策略复盘摘要

### 7.2 规则和代码负责

- 行情、涨跌幅、收益和统计计算
- 股票代码/名称校验
- evidence ref 存在性校验
- 事实角色和龙头资格计算
- “可计划”硬门控
- 持仓 freshness 和交集
- LLM 输出 schema、枚举和降级

### 7.3 降级

LLM 失败时展示规则聚类和事实证据，并明确标记“LLM 分析不可用”。不得使用规则文本伪装成 AI 结论，也不得清空可用事实。

## 8. 动态维护

### 8.1 第一阶段

仓库内版本化配置作为 canonical truth，日报嵌入本次分析快照。这能先保证五只股票每日稳定进入分析。

### 8.2 页面管理

最后阶段扩展现有 Cloudflare Worker：

- GET 返回配置 revision。
- PUT 通过 Worker 端秘密或短时会话鉴权。
- 使用 ETag/乐观锁避免覆盖他人更新。
- 校验代码、角色、最大数量、schema 和 CORS。
- 保留审计与回滚所需的 revision。
- 静态页面不保存可写凭据。

保存后的新配置只显示“等待下次日报分析”，不能混入当天快照并伪装已分析。

## 9. 视觉与交互

采用 Swiss 方向：白/冷灰底、单一蓝色强调、细网格和左对齐信息层级。核心差异化是横向“证据链轨道”，不是装饰。

交互遵循 scan-first：

- 默认只展开最多三个方向和五只重点股摘要。
- 一次只展开一个详情。
- 桌面端展示证据链，手机端改为纵向步骤。
- 风险、partial、LLM 失败和数据不足使用不同语义状态，不仅依赖颜色。

## 10. 分期与验收门

### P0：涨停解析与状态合同

- 整数 `92500` 解析为 `09:25`。
- 接口名单、总数、日期和覆盖率可核对。
- 解析失败不再展示“暂无涨停”。

### P1：重点池 canonical 配置和事实快照

- 五只股票不论是否入选都出现。
- 新加入股票显示“新增关注”。
- 无新鲜数据时不输出具体价位和强动作。

### P2：方向簇、LLM 仲裁与证据链

- 2026-08-20 冻结事件中，“海外光通信”可关联中际旭创。
- `no_impact=true` 的收评不进入主催化前三。
- LLM 失败、冲突和引用错误均可见且可降级。

### P3：推荐账本与策略 scorecard

- 默认 cohort 全部是 `decision_code=recommend`。
- observe/reject/unknown 分栏。
- 每个成熟样本能追到推荐账本、贡献策略和收益口径。
- 旧数据只标 `legacy_inferred/unknown`，不伪造版本。

### P4：页面关注池管理

- 新增、删除、排序、启停可持久化。
- revision 冲突不会静默覆盖。
- 保存后明确显示何时生效。
- P4 失败不影响 P0-P3 已发布能力。

## 11. 发布验证

1. Python 单元测试与数据合同测试。
2. Worker API 测试。
3. JavaScript 语法检查。
4. 冻结 fixture 回放。
5. 当日真实报告生成。
6. 桌面和手机截图验收。
7. 数据不足、partial、LLM 失败三类异常截图。
8. 根页面与归档页面都能加载正确资源。
