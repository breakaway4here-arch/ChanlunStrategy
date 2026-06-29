# 2026-06-29 fusion_strict_startup_rescue_v1 回测结果

## 1. 实验目标

新增 `fusion_strict_startup_rescue_v1`：

- 保留 `fusion_strict` 原 A 类。
- 额外 rescue `trend_strength=1.0` 且 `signal_type=强势启动候选` 的样本。
- 继续过滤 `trend_strength=1.0` 的 `底背驰候选` 和 `中枢低吸候选`。

## 2. 回测命令

```bash
python3 scripts/run_policy_experiments.py \
  --policies fusion_strict,fusion_strict_startup_rescue_v1 \
  --business-metrics \
  --output-json /tmp/fusion_startup_rescue_v1_report.json \
  --output-md /tmp/fusion_startup_rescue_v1_report.md
```

说明：

- 当前环境无外网访问腾讯行情，回测走本地 cache fallback。
- 基线口径仍为 `picks_fusion All`，`baseline_rows=434`。

## 3. 与 fusion_strict 对比

| Strategy | samples_after | coverage | T+3 mean | T+3 win rate | drawdown mean | accepted |
|---|---:|---:|---:|---:|---:|---|
| fusion_strict | 88 | 20.28% | 1.31 | 51.1% | -4.42 | false |
| fusion_strict_startup_rescue_v1 | 141 | 32.49% | 2.16 | 54.6% | -4.47 | true |

增量：

| Metric | Delta |
|---|---:|
| samples_after | +53 |
| coverage | +12.21 pct |
| T+3 mean | +0.85 |
| T+3 win rate | +3.5 pct |
| drawdown mean | -0.05 |

## 4. Reject Reason Distribution

### fusion_strict

| reason | count |
|---|---:|
| trend_strength_below_min | 346 |
| missing_pivot | 53 |
| choppy_trend | 12 |

### fusion_strict_startup_rescue_v1

| reason | count |
|---|---:|
| trend_strength_below_min | 293 |
| choppy_trend | 12 |

说明：

- `missing_pivot=53` 在 rescue 版本中消失，对应被救回的 `强势启动候选`。
- 仍被过滤的 `293` 个主要是弱趋势 `底背驰候选` 和 `中枢低吸候选`，不应整体放开。

## 5. 选择结论

```json
{
  "selected": "fusion_strict_startup_rescue_v1",
  "reason": "meets target criteria",
  "rejected": {
    "fusion_strict": "coverage below 25%"
  },
  "pareto_frontier": ["fusion_strict_startup_rescue_v1"]
}
```

结论：

- `fusion_strict_startup_rescue_v1` 满足覆盖率 25%~35%、T+3 mean > 0.80、T+3 win rate >= 49%、drawdown mean >= -4.60。
- 该版本不是粗暴放宽弱趋势，而是只 rescue 已被分桶验证有效的 `强势启动候选`。
- 可以作为下一步默认候选策略，继续做独立稳定性验证。

## 6. 稳定性拆分验证

补充验证口径：

- `T+1/T+3/T+5` 使用同一批 `picks_fusion` snapshot 与本地 kline cache。
- `T+3/T+5` 只统计具备完整 forward horizon 的样本，因此样本数可能略低于主回测表。
- `incremental_rescued` 表示 `fusion_strict_startup_rescue_v1` 相比 `fusion_strict` 新增救回的样本。

### 6.1 整体 T+1 / T+3 / T+5

| Strategy | n | T+1 mean | T+1 win | T+3 mean | T+3 win | T+5 mean | T+5 win | DD3 mean |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| fusion_strict | 88 | 1.01 | 59.09% | 1.49 | 52.33% | 1.67 | 47.06% | -4.32 |
| fusion_strict_startup_rescue_v1 | 141 | 1.18 | 60.99% | 2.28 | 55.47% | 1.91 | 45.59% | -4.43 |
| incremental_rescued | 53 | 1.47 | 64.15% | 3.61 | 60.78% | 2.32 | 43.14% | -4.62 |

判断：

- 均值维度上，`rescue_v1` 的 T+1、T+3、T+5 都比 `fusion_strict` 更好。
- 胜率维度上，T+1/T+3 改善，T+5 win rate 下降，说明新增样本更偏短线弹性，持有到 T+5 的稳定胜率不足。
- 回撤维度上，`incremental_rescued` DD3 为 `-4.62`，略差于目标线，后续不应继续无差别放宽。

### 6.2 按月份拆分

| Month | Strategy | n | T+1 mean | T+3 mean | T+5 mean | T+3 win | T+5 win | DD3 mean |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 2026-05 | fusion_strict | 23 | -0.12 | 0.67 | -2.83 | 52.17% | 30.43% | -4.50 |
| 2026-05 | rescue_v1 | 45 | 0.41 | 1.52 | -2.17 | 62.22% | 28.89% | -4.25 |
| 2026-05 | incremental | 22 | 0.98 | 2.41 | -1.49 | 72.73% | 27.27% | -3.99 |
| 2026-06 | fusion_strict | 65 | 1.40 | 1.79 | 3.34 | 52.38% | 53.23% | -4.26 |
| 2026-06 | rescue_v1 | 96 | 1.54 | 2.65 | 3.93 | 52.17% | 53.85% | -4.52 |
| 2026-06 | incremental | 31 | 1.82 | 4.52 | 5.20 | 51.72% | 55.17% | -5.09 |

判断：

- 5 月和 6 月的 T+1/T+3 均值都同步改善。
- 5 月 T+5 仍为负，只是亏损幅度收窄，说明该阶段不适合用 T+5 作为主要退出目标。
- 6 月新增样本 T+5 均值显著改善，但 DD3 变差，属于高弹性高波动收益。

### 6.3 按市场环境拆分

| Market | Strategy | n | T+1 mean | T+3 mean | T+5 mean | T+3 win | T+5 win | DD3 mean |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| strong | fusion_strict | 48 | 1.55 | 1.35 | 2.45 | 52.17% | 53.33% | -4.53 |
| strong | rescue_v1 | 66 | 1.21 | 1.31 | 1.60 | 51.61% | 50.82% | -5.04 |
| strong | incremental | 18 | 0.32 | 1.19 | -0.78 | 50.00% | 43.75% | -6.49 |
| weak | fusion_strict | 40 | 0.36 | 1.64 | 0.79 | 52.50% | 40.00% | -4.08 |
| weak | rescue_v1 | 75 | 1.15 | 3.07 | 2.16 | 58.67% | 41.33% | -3.93 |
| weak | incremental | 35 | 2.06 | 4.71 | 3.73 | 65.71% | 42.86% | -3.76 |

判断：

- 新增 rescue 样本的主要收益来自 `weak` 环境，T+1/T+3/T+5 均值与 DD3 都改善。
- `strong` 环境下新增 rescue 样本拖累 T+5，DD3 恶化到 `-6.49`，不适合作为继续放宽方向。
- 下一步如果继续优化，方向应收敛到 `trend_strength=1.0 + 强势启动候选 + weak market`，而不是继续扩大 rescue 范围。

### 6.4 收益集中度

| Strategy | samples | unique_codes | top1 count share | top5 count share | top5 positive contribution share |
|---|---:|---:|---:|---:|---:|
| fusion_strict | 88 | 84 | 2.27% | 10.23% | 34.85% |
| fusion_strict_startup_rescue_v1 | 141 | 130 | 1.42% | 7.09% | 24.78% |
| incremental_rescued | 53 | 52 | 3.77% | 11.32% | 43.12% |

`rescue_v1` 总体并没有集中在少数几只票：

- `141` 个样本覆盖 `130` 只股票。
- Top1 出现频率只有 `1.42%`，Top5 出现频率 `7.09%`。
- Top5 正收益贡献占比从 `fusion_strict` 的 `34.85%` 降到 `24.78%`。

但新增的 `incremental_rescued` 样本中，Top5 正收益贡献占比为 `43.12%`，说明救回样本内部收益更依赖少数高弹性票，后续需要继续观察样本扩张后的稳定性。

### 6.5 最终判断

`fusion_strict_startup_rescue_v1` 可以保留为当前默认候选：

- 覆盖率从 `20.28%` 提升到 `32.49%`。
- 主回测 T+3 mean 从 `1.31` 提升到 `2.16`。
- 补充验证中 T+1/T+3/T+5 均值同步改善。
- 总体收益不集中在少数几只股票。

限制条件：

- 新增 rescue 样本的 T+5 胜率没有同步改善。
- `strong` 市场环境下新增 rescue 样本拖累回撤，不应继续沿“粗放 rescue”方向扩展。
- 后续优化应只做更细分的 `weak market + 强势启动候选` 约束实验。

## 7. Strong Market Rescue Guard 上线修正

### 7.1 上线策略

- 默认候选：`fusion_strict_startup_rescue_v1`
- 保留：全部原 `fusion_strict` A 类
- 禁用：`market_env == "strong"` 下新增的 `trend_strength=1.0 + 强势启动候选` rescue
- 允许：非 `strong` 环境下的 `trend_strength=1.0 + 强势启动候选` rescue

### 7.2 回测结果

```bash
python3 scripts/run_policy_experiments.py \
  --policies fusion_strict,fusion_strict_startup_rescue_v1 \
  --business-metrics \
  --output-json /tmp/fusion_startup_rescue_market_guard_report.json \
  --output-md /tmp/fusion_startup_rescue_market_guard_report.md
```

基线口径：`picks_fusion`，`baseline_rows=434`。

| Strategy | samples_after | coverage | T+3 mean | T+3 win | drawdown |
|---|---:|---:|---:|---:|---:|
| fusion_strict | 88 | 20.28% | 1.31 | 51.1% | -4.42 |
| fusion_strict_startup_rescue_v1 | 123 | 28.34% | 2.28 | 55.3% | -4.23 |

增量：

| Metric | Delta |
|---|---:|
| samples_after | +35 |
| coverage | +8.06 pct |
| T+3 mean | +0.97 |
| T+3 win | +4.2pct |
| drawdown mean | +0.19 |

Reject reason 中新增 `strong_market_rescue_guard: 18`（对应 `strong` 市场下被拦截的 rescue 样本）。

### 7.3 结论

- `fusion_strict_startup_rescue_v1` 在完整回测中仍优于 `fusion_strict`。
- `strong` 市场过滤成功拦截 `18` 个低质量 rescue 样本，`strong_market_rescue_guard` 生效。
- guard 上线后覆盖率、T+3 平均收益、T+3 胜率与回撤均较基线版本更优；`strong` 市场风险明显可控。
