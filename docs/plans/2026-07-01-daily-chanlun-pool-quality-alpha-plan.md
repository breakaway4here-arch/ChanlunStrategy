# Daily Chanlun Pool Quality Alpha Plan

> For Codex: implement this plan conservatively. The goal is to improve the daily Chanlun stock-picking report with the highest-confidence lessons from the JoinQuant growth/liquidity experiment, without replacing the existing Chanlun discovery pipeline.

## Goal

在不改变现有日选股系统结构的前提下，把聚宽实验里最有把握的“池子质量”经验迁移到每天定时任务：

- 保留当前 `板块资金流 -> 板块成分股 -> 日线缠论扫描 -> 30min确认 -> scoring -> report` 主链路。
- 不新增正式股票池，不用聚宽池子替换东方财富板块池。
- 只在现有候选股上增加轻量质量因子，用于排序和诊断。
- 优先提升日报 Top10 / 主推 / 加速池的次日胜率和平均收益。

核心判断：这次聚宽回测变红，最可靠的贡献不是复杂 alpha 权重，而是“流动性合格 + 中小成长风格 + 强票保留”的方向。daily 日报没有持仓状态，所以先落地前两项，并把强票保留转化为次日验证闭环，而不是交易调仓逻辑。

## Current Pipeline

当前 daily 入口在 `run.py`：

1. `chanlun.data_fetcher.collect_daily_data()` 获取东方财富 TOP 板块资金流。
2. `fetch_sector_stocks()` 拉板块成分股并去重。
3. 批量获取日线 K 线。
4. 日线缠论扫描、结构池、融合池、加速池、罗姐池等继续筛选。
5. `chanlun.report_view_model` 调 `chanlun.scoring_engine.compute_opportunity_score()` 生成 `opportunity_score`。
6. 报告按 `opportunity_score` 排序展示。

因此，本次优化应接在候选股已有字段和 `scoring_engine` 上，而不是在最前面改成一个全新的股票池。

## Non Goals

本轮明确不做：

- 不新增新的股票池模块。
- 不新增 feature layer。
- 不新增 backtest framework。
- 不拆分 scoring pipeline。
- 不改变 `pool -> scoring -> ranking` 数据流。
- 不把聚宽实验脚本的交易/持仓逻辑搬进 daily 任务。
- 不硬性只选创业板/科创板。
- 不引入网络依赖到测试。

## Highest Confidence Optimization

### 1. Liquidity Quality

目标：降低低成交额、滑点大、实盘难买卖的候选股排名。

建议实现：

- 在日线 K 线数据中计算近 20 日平均成交活跃度。
- 当前腾讯日线字段主要有 `volumes`，若没有成交额字段，先用 `volume20` 作为保守代理。
- 如果后续能从东方财富成分股或行情接口稳定拿到成交额，再升级为 `money20`。

推荐字段：

```python
item["pool_quality"] = {
    "volume20": ...,
    "volume_ratio20": ...,
    "liquidity_score": 0..100,
}
```

排序影响：

- 流动性明显合格：小幅加分。
- 极低流动性：先降权，不建议第一版硬剔除。
- 加分上限要小，避免盖过缠论结构分。

### 2. Growth And Elasticity Bias

目标：把聚宽回测中有效的中小/成长风格变成软加分。

建议实现：

- 代码前缀识别：
  - `300` / `301`：创业板成长弹性加分。
  - `688` / `689`：科创板成长弹性加分，但权重低于创业板。
  - `002`：中小成长轻微加分。
- 不对 `60` / `000` / `001` 做负分，避免错杀主线大票。

推荐字段：

```python
item["pool_quality"]["growth_board_score"] = 0..100
item["pool_quality"]["growth_board_label"] = "创业板弹性" | "科创弹性" | "中小成长" | ""
```

排序影响：

- 只作为 `alpha_bonus`，不作为硬过滤。
- 第一版建议总贡献控制在 `+0..3` 分。

### 3. Sector Relative Strength

目标：daily 原本就依赖板块资金流，应该把“板块强 + 个股也强”排在更前面。

建议实现：

- 利用已有 `sector_rank`、`sector_flow`、`change_pct`。
- 候选股属于 TOP 板块且自身涨幅/量能不弱时加分。
- 如果只是板块强但个股明显弱，暂不加分。

推荐字段：

```python
item["pool_quality"]["sector_quality_score"] = 0..100
```

排序影响：

- 小幅补充现有 `sector_strength_factor`。
- 不改变板块池来源。

### 4. Next-Day Feedback Diagnostics

目标：让 daily 优化有真实闭环，持续观察“今天选出来，明天到底涨不涨”。

建议实现：

- 先不新增系统，只在已有回看/脚本中补充统计。
- 统计维度：
  - 昨日 `highlights Top10`
  - 昨日 `main`
  - 昨日 `acceleration`
  - 昨日 `luojie`
- 指标：
  - T+1 win rate
  - T+1 mean return
  - T+1 median return
  - worst return
  - switched-in 或排名上升样本的收益

这部分用于判断 pool quality alpha 是否真的有用，不直接影响当天选股。

## Recommended Implementation

### Task 1: Add Pool Quality Feature Extraction

Files:

- `chanlun/report_view_model.py`
- `tests/test_report_view_model.py`

Work:

- 增加内部 helper，例如 `_build_pool_quality_features(item)`。
- 从候选股已有字段里读取：
  - `code`
  - `volumes`
  - `change_pct`
  - `sector_rank`
  - `sector_flow`
- 计算：
  - `liquidity_score`
  - `growth_board_score`
  - `sector_quality_score`
  - `pool_quality_score`
  - `pool_quality_tags`
- 将结果放入 `compute_opportunity_score()` 的 context：

```python
{
    "alpha_features": {
        "pool_quality": {...}
    }
}
```

Acceptance:

- 不改变 `compute_opportunity_score()` 的函数签名。
- 不改变 raw candidate 结构要求；缺字段时返回中性分。
- 老数据、缓存数据、缺少 volume 的样本不报错。

### Task 2: Add Bounded Pool Quality Bonus

Files:

- `chanlun/scoring_engine.py`
- `tests/test_scoring_engine.py`

Work:

- 在 `_score_alpha_bonus()` 中增加 pool quality bonus。
- 新增 helper，例如 `_score_pool_quality_bonus(pool_quality)`。
- bonus 只加分，不扣分。
- 总加分仍受 `ALPHA_BONUS_LIMIT` 约束。

Recommended first-version weights:

```text
liquidity_score       max +1.2
growth_board_score    max +1.0
sector_quality_score  max +0.8
total pool bonus      max +3.0
```

Acceptance:

- `alpha_enabled=False` 时结果完全不变。
- 无 `pool_quality` 时结果完全不变。
- 有 `pool_quality` 时只产生小幅正向变化。
- 任何单项异常值都被 clamp。

### Task 3: Expose Diagnostics In Report Data

Files:

- `chanlun/report_view_model.py`
- `tests/test_report_view_model.py`

Work:

- 在 workspace item 中加入：

```python
"pool_quality": {...}
```

- `rank_trace` 中保留：
  - `pool_quality_bonus`
  - `pool_quality_score`
  - `pool_quality_tags`

Acceptance:

- UI 不改也能正常渲染。
- JSON 中能看到为什么某只票被加分。
- 不影响已有 `opportunity_score` 排序字段。

### Task 4: Add Lightweight Next-Day Evaluation

Files:

- 优先复用已有回测/回看脚本。
- 如必须新增输出，优先放在现有脚本参数内，不新增框架。

Work:

- 对历史 `docs/data/*.json` 做 T+1 统计。
- 输出 baseline score vs pool-quality alpha score 的排名变化。
- 聚焦 Top10 和各池前排，而不是模拟完整交易系统。

Metrics:

- mean T+1 return
- win rate
- median T+1 return
- worst T+1 return
- top-ranked sample count

Acceptance:

- 不依赖网络。
- 对缺少次日数据的日期跳过并计数。
- 输出能明确回答：pool quality alpha 是否提升 Top10 次日表现。

## Suggested Task Split For Subagents

### Worker A: Feature Extraction

Model: `gpt-5.3-codex-spark`

Files:

- `chanlun/report_view_model.py`
- `tests/test_report_view_model.py`

Deliverable:

- `pool_quality` 特征构造和 context 透传。
- 不改 `scoring_engine.py`。

### Worker B: Scoring Bonus

Model: `gpt-5.3-codex-spark`

Files:

- `chanlun/scoring_engine.py`
- `tests/test_scoring_engine.py`

Deliverable:

- bounded pool quality alpha bonus。
- 覆盖缺字段、异常值、alpha off、cap 生效。

### Worker C: Evaluation

Model: `gpt-5.3-codex-spark`

Files:

- existing backtest/review script only

Deliverable:

- T+1 评估输出。
- 不新增 framework。

Main agent review:

- 合并三个 worker 的结果。
- 检查是否有隐性硬过滤或结构重写。
- 跑测试和回测。
- 决定是否提交。

## Verification

Targeted tests:

```bash
python3 -m unittest tests.test_report_view_model tests.test_scoring_engine -v
```

Compatibility tests:

```bash
python3 -m unittest tests.test_daily_structure_pool tests.test_candidate_upgrade tests.test_fusion_admission tests.test_signal_recency tests.test_strong_startup tests.test_startup_labels -v
```

Static checks:

```bash
python3 -m py_compile chanlun/report_view_model.py chanlun/scoring_engine.py
git diff --check
```

Evaluation:

```bash
python3 scripts/backtest_scoring_alpha_impact.py --min-forward-days 1
python3 scripts/backtest_scoring_alpha_impact.py --min-forward-days 3
```

If a dedicated T+1 script already exists after implementation, run that script as the final decision gate.

## Success Criteria

本轮只有在以下条件同时满足时，才认为值得保留：

- Top10 或主推池 T+1 win rate 提升。
- mean T+1 return 不下降，最好提升。
- worst T+1 return 不明显恶化。
- 排名前移样本里，流动性/成长/板块质量标签能解释多数变化。
- 代码没有引入新的数据源强依赖。
- 日报在缺字段、缓存兜底、非交易日数据下仍能生成。

## Rollback Criteria

出现以下任一情况，应回退或压低权重：

- Top10 胜率下降。
- alpha 只把高波动票推前，worst return 明显恶化。
- 主推池被成长板标签过度支配，缠论结构分失去主导。
- 缺少 volume 的历史样本大量变成异常排序。
- 需要新增框架或大规模重构才能解释收益。

## First Version Recommendation

最有把握的第一版：

1. 只做 `pool_quality` 软加分。
2. 总加分上限控制在 `+3`，并继续受 `ALPHA_BONUS_LIMIT` 限制。
3. 不做硬过滤。
4. 不改入池逻辑。
5. 用 T+1 真实收益评估 Top10 和主推池。

如果第一版验证有效，再考虑把极低流动性做硬过滤；如果第一版无效，不继续扩大权重。
