# ChanLun Fusion-only 阈值扫描落地方案

> 来源：`/Users/yangfan/Downloads/chanlun_fusion_only_threshold_scan_spec.md`
>
> 结论：原 spec 方向可落地，但不能原样落地。需要把“收益/覆盖率扫描”收敛到历史快照回测入口，避免把 `compare_chan_engine_dual.py` 的结构场景对比误用成真实收益回测。

## 1. 可行性判断

### 可直接保留

- 只优化 `fusion-only`
- 不再引入 hybrid
- 不混入 pure fallback
- 不修改结构层、legacy signal、`analyze()`、`analyze_dual()`
- 扫描 `fusion_strict` / `fusion_mid` / `fusion_loose`
- 输出 coverage、T+3 mean、T+3 win rate、drawdown mean、Pareto frontier、selected candidate

### 需要改写

原 spec 要求通过：

```bash
python3 scripts/compare_chan_engine_dual.py --candidate fusion_mid --business-metrics
```

得到真实收益指标。当前仓库中 `compare_chan_engine_dual.py` 只跑 `tests.test_chan_engine_snapshot.SCENARIOS` 的内存结构用例，`--business-metrics` 只能输出推荐差异和 `no_market_data` 占位，不具备历史收益回测能力。

因此本轮真实收益指标必须从历史推荐快照回测产生：

```bash
python3 scripts/run_policy_experiments.py \
  --policies fusion_strict,fusion_mid,fusion_loose \
  --business-metrics \
  --output-json /tmp/fusion_pareto_report.json \
  --output-md /tmp/fusion_pareto_report.md
```

`compare_chan_engine_dual.py` 可保留候选注册兼容检查，但不得作为收益/覆盖率来源。

## 2. 本轮目标

在只使用 `picks_fusion` 的前提下，寻找比当前 strict A-only 覆盖率更高、收益仍为正的阈值点。

验收目标：

```text
25% <= coverage <= 35%
T+3 mean > 0.80
T+3 win rate >= 49%
drawdown_mean >= -4.60
```

说明：`drawdown_mean` 在当前回测中是负数，数值越接近 0 表示回撤越小。原 spec 写 `drawdown_mean <= -4.60`，但同时给出 `-4.55` 作为改善示例；因此实际验收按 `>= -4.60` 执行。

如果 `fusion_mid` / `fusion_loose` 都不满足，则保持：

```text
selected = fusion_strict
```

## 3. 禁止修改范围

禁止修改：

```text
run.py
chanlun/chan_engine.py
chanlun/engine_core.py
chanlun/engine_signals.py
analyze()
analyze_dual()
任何 legacy provider
分型 / 笔 / 线段 / 中枢 / 背驰 / legacy signal
```

不得重新引入：

```text
hybrid
pure fallback
fusion + pure 混合执行
```

## 4. 允许修改范围

优先只修改或新增：

```text
chanlun/signal_quality_classifier.py
chanlun/policy_experiment_metrics.py
scripts/run_policy_experiments.py
tests/test_signal_quality_classifier.py
tests/test_policy_experiment_metrics.py
docs/plans/*.md
```

如需让 `compare_chan_engine_dual.py --candidate fusion_*` 不报错，只能做轻量兼容注册，不得把真实收益逻辑塞进 dual compare。

## 5. 质量 profile 设计

新增 profile：

```text
fusion_strict
fusion_mid
fusion_loose
```

### fusion_strict

等价于当前 A-only：

```text
trend_strength >= 2
pivot exists
segment exists
volatility <= LOW_VOLATILITY_MAX
非震荡
```

目标：行为不变，作为基准。

### fusion_mid

只允许在 strict 基础上放宽一个条件，按以下顺序自动扫描，最终只保留表现最好的一个 mid profile：

1. `trend_strength >= 1.5`
2. `volatility <= LOW_VOLATILITY_MAX * 1.15`
3. `pivot exists OR strong trend segment exists`

选择规则：

- 优先满足验收目标
- 多个满足时按 `T+3 mean`、`coverage`、`drawdown_mean` 排序
- 如果都不满足，仍输出各方案结果，并将 `fusion_mid` 标记为未达标

### fusion_loose

在 `fusion_mid` 的最佳放宽项基础上再放宽一个条件，仅用于 Pareto frontier，不默认上线。

候选放宽：

```text
trend_strength >= 1
volatility <= LOW_VOLATILITY_MAX * 1.30
```

## 6. 推荐实现接口

在 `chanlun/signal_quality_classifier.py` 中新增纯函数接口：

```python
classify_signal(signal, profile="fusion_strict")
tag_signal_quality(signal, profile="fusion_strict")
filter_executable_signals(signals, profile="fusion_strict")
list_quality_profiles()
```

兼容要求：

- 不传 `profile` 时行为必须保持当前 strict A-only 不变
- 已有调用方不需要改参数
- profile 只影响 A/B/C 分类，不影响原始 signal 生成

## 7. 回测实现

在 `chanlun/policy_experiment_metrics.py` 中支持 policy：

```text
fusion_strict
fusion_mid
fusion_loose
```

回测口径：

- 只读取 `picks_fusion`
- baseline 为 `picks_fusion` All
- policy 为对应 profile 下 category=A 的样本
- coverage = `samples_after / samples_before`
- `drawdown_mean` 使用 `max_dd_3d_mean`
- 输出字段同时保留百分比展示和 0-1 ratio，避免二义性

每个 policy 输出必须包含：

```json
{
  "candidate": "fusion_mid",
  "samples_before": 434,
  "samples_after": 123,
  "coverage": 0.283,
  "coverage_pct": 28.3,
  "t3_mean_before": -1.52,
  "t3_mean_after": 0.92,
  "t3_win_rate_before": 28.8,
  "t3_win_rate_after": 49.7,
  "drawdown_mean_before": -5.38,
  "drawdown_mean_after": -4.55,
  "accepted": true
}
```

## 8. CLI 要求

扩展 `scripts/run_policy_experiments.py`：

```bash
python3 scripts/run_policy_experiments.py \
  --policies fusion_strict,fusion_mid,fusion_loose \
  --business-metrics \
  --output-json /tmp/fusion_pareto_report.json \
  --output-md /tmp/fusion_pareto_report.md
```

要求：

- `--business-metrics` 可选兼容旧命令；本轮可以作为 no-op flag
- JSON 输出包含 `fusion_threshold_scan`
- Markdown 输出包含三组结果、Pareto frontier、selected candidate、rejected reason

`compare_chan_engine_dual.py` 只需保证现有候选不受影响；若注册 `fusion_*`，输出要明确 `return_metrics.status = "no_market_data"`。

## 9. Pareto 与选择规则

Pareto 点：

```text
x = coverage
y = t3_mean_after
```

若存在 B：

```text
B.coverage >= A.coverage
B.t3_mean_after >= A.t3_mean_after
且至少一项严格更好
```

则 A 被支配。

默认选择：

1. 仅从满足验收目标的 Pareto 点中选
2. 优先 `T+3 mean` 更高
3. 其次 `coverage` 更高
4. 再其次 `drawdown_mean` 更优（更接近 0）
5. 无达标点则 `selected = fusion_strict`

## 10. 测试要求

新增/更新测试覆盖：

- strict 默认行为不变
- mid 单条件放宽，不混合多条件
- loose 不作为默认 selected，除非满足全部验收
- unknown profile 报错
- `run_policy_experiments.py --business-metrics` 能接受 fusion 三策略并产出 JSON/MD
- policy metrics 只使用 `picks_fusion`，不混入 `picks_pure`

## 11. 验收命令

必须通过：

```bash
python3 -m unittest tests.test_signal_quality_classifier tests.test_policy_experiment_metrics
python3 -m unittest discover -s tests
python3 -m py_compile scripts/run_policy_experiments.py chanlun/signal_quality_classifier.py chanlun/policy_experiment_metrics.py
git diff --check
```

必须执行真实回测：

```bash
python3 scripts/run_policy_experiments.py \
  --policies fusion_strict,fusion_mid,fusion_loose \
  --business-metrics \
  --output-json /tmp/fusion_pareto_report.json \
  --output-md /tmp/fusion_pareto_report.md
```

## 12. 结果文档

完成后新增：

```text
docs/plans/2026-06-29-fusion-only-threshold-scan-result.md
```

内容必须包含：

1. 原 spec 是否原样可执行的结论
2. `fusion_strict` / `fusion_mid` / `fusion_loose` 三组回测结果
3. Pareto frontier
4. selected candidate
5. rejected candidates reason
6. 全量测试结果

## 13. 交付边界

本轮只交付 fusion-only 阈值扫描和回测结论。

不做：

- hybrid
- pure fallback
- 新交易执行系统
- 改结构层提升信号生成
- 把回测结论直接接入生产默认交易
