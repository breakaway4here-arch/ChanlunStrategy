# ChanLun Engine Phase 6.10 Weak Trend Filter Backtest Result

## 结论

Phase 6.10 已完成并通过验证。

本阶段新增 3 个 backtest-only 弱趋势过滤 policy，不改 production `analyze()`，不新增数据源。

真实回测显示：三个新 policy 在当前样本上的结果完全一致，都比 `delay1_v1_bottom_quality_guard` 更好，并且通过本阶段晋级门槛。

推荐下一阶段收敛为一个语义最清楚的候选：

```text
delay1_v1_bottom_quality_market_known_guard
```

原因：本轮额外过滤的 112 条样本本质上来自 `market_regime` 缺失/未知。用 `market_known_guard` 表达最准确，不会过早把“未知”解释为“弱市”。

## 改动摘要

修改文件：

- `chanlun/policy_experiment_metrics.py`
- `tests/test_policy_experiment_metrics.py`
- `tests/test_policy_experiment_runner_script.py`

新增 policy：

- `delay1_v1_bottom_quality_market_strong_guard`
- `delay1_v1_bottom_quality_market_known_guard`
- `delay1_v1_bottom_quality_market_or_ma_guard`

新增 helper：

- `bottom_trend_guard_reasons()`
- `_bottom_trend_reason_label()`

过滤顺序：

```text
bottom quality guard -> bottom trend guard -> cooldown
```

主进程 review 后补充：

- 增加空 `market_regime` 且 `ma_bullish=False` 时，`market_or_ma_guard` 过滤的 policy 级测试。

## 验证命令

### 1. Policy runner 定向测试

```bash
python3 -m unittest tests.test_policy_experiment_metrics tests.test_policy_experiment_runner_script
```

结果：

```text
Ran 23 tests in 0.012s

OK
```

### 2. 回测相关扩展测试

```bash
python3 -m unittest tests.test_policy_experiment_metrics tests.test_policy_experiment_runner_script tests.test_historical_experiment_metrics tests.test_engine_experiment_runner_script
```

结果：

```text
Ran 40 tests in 1.455s

OK
```

### 3. 全量测试

```bash
python3 -m unittest discover -s tests
```

结果：

```text
Ran 466 tests in 4.667s

OK
```

### 4. 编译检查

```bash
python3 -m py_compile chanlun/policy_experiment_metrics.py scripts/run_policy_experiments.py
```

结果：通过。

### 5. Diff 空白检查

```bash
git diff --check
```

结果：通过。

## 真实回测命令

```bash
/usr/bin/time -p python3 scripts/run_policy_experiments.py \
  --policies delay1_v1_bottom_quality_guard,delay1_v1_bottom_quality_market_strong_guard,delay1_v1_bottom_quality_market_known_guard,delay1_v1_bottom_quality_market_or_ma_guard \
  --output-json /tmp/phase6_10_weak_trend_filter_metrics.json \
  --output-md /tmp/phase6_10_weak_trend_filter_metrics.md
```

结果：

```text
real 42.36
user 6.26
sys 2.78
```

输出文件：

- `/tmp/phase6_10_weak_trend_filter_metrics.json`
- `/tmp/phase6_10_weak_trend_filter_metrics.md`

## Execution Summary

```text
shared_baseline: True
snapshot_rows: 2842
unique_codes: 1103
fetch_attempts: 1103
cache_hits: 1739
kline_missing: 1
kline_invalid: 0
baseline_rows: 1287
```

## 回测指标

| Policy | Baseline n | Baseline Filtered | Policy n | Policy T+3 | Delta T+3 | T+3 Win | Loss <=5 | Big Drop <=5 | Max DD | Filtered | Retained | Decision |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `delay1_v1_bottom_quality_guard` | 1287 | 805 | 1101 | 0.16 | 0.13 | 45.9 | 18.7 | 36.9 | -4.49 | 186 | 85.55 | baseline |
| `delay1_v1_bottom_quality_market_strong_guard` | 1287 | 805 | 989 | 0.41 | 0.38 | 46.8 | 17.7 | 36.2 | -4.43 | 298 | 76.85 | pass |
| `delay1_v1_bottom_quality_market_known_guard` | 1287 | 805 | 989 | 0.41 | 0.38 | 46.8 | 17.7 | 36.2 | -4.43 | 298 | 76.85 | pass |
| `delay1_v1_bottom_quality_market_or_ma_guard` | 1287 | 805 | 989 | 0.41 | 0.38 | 46.8 | 17.7 | 36.2 | -4.43 | 298 | 76.85 | pass |

## Filter Reasons

```text
delay1_v1_bottom_quality_guard:
  bottom_quality_guard: 186

delay1_v1_bottom_quality_market_strong_guard:
  bottom_quality_guard: 186
  bottom_market_not_strong: 112

delay1_v1_bottom_quality_market_known_guard:
  bottom_quality_guard: 186
  bottom_market_unknown: 112

delay1_v1_bottom_quality_market_or_ma_guard:
  bottom_quality_guard: 186
  bottom_market_not_strong_no_ma: 112
```

质量过滤 detail：

```text
bottom_distance_gt_6: 45
bottom_missing_shape_or_stop_drop: 158
```

## 晋级门槛检查

对比基准：

```text
delay1_v1_bottom_quality_guard
```

门槛：

- T+3 mean >= baseline
- T+3 win rate >= baseline
- `t3_loss_5pct_rate` <= baseline
- `big_drop_5pct_rate` <= baseline
- retained ratio >= 70%

三个新 policy 结果：

```text
T+3 mean: 0.41 >= 0.16
T+3 win rate: 46.8 >= 45.9
t3 loss <=5: 17.7 <= 18.7
big drop <=5: 36.2 <= 36.9
retained ratio: 76.85 >= 70
```

结论：三者都通过。

## 为什么三个结果完全一样

在当前样本中，额外过滤的 112 条样本同时满足三个 policy 的过滤条件：

- 对 `market_strong_guard` 来说，它们不是 `market_regime=strong`。
- 对 `market_known_guard` 来说，它们是 `market_regime` 缺失/未知。
- 对 `market_or_ma_guard` 来说，它们同时不是强市且没有 `ma_bullish=True`。

因此三者指标一致。

## 推荐选择

推荐优先保留：

```text
delay1_v1_bottom_quality_market_known_guard
```

理由：

- 本轮额外过滤的核心事实是 `market_regime` 未知。
- `market_known_guard` 的语义最保守：只剔除市场状态未知，不把未知直接等同于弱市。
- 对后续晋级生产更容易解释。

暂不推荐直接推广：

- `market_strong_guard`：语义更激进，可能把未知市场状态解释成非强市。
- `market_or_ma_guard`：当前结果一致，但规则解释更绕，样本没有体现出它相对 `market_known_guard` 的独立收益。

## 下一阶段建议

Phase 6.11 建议做“候选收敛与稳定性复核”：

- 只保留 `delay1_v1_bottom_quality_market_known_guard` 作为主候选。
- 用更完整 policy 集合复跑：
  - `delay1_v1`
  - `delay1_v1_bottom_quality_guard`
  - `delay1_v1_bottom_quality_market_known_guard`
  - `delay1_v1_bottom_distance_gt6_guard`
  - `delay1_v1_bottom_missing_shape_guard`
- 增加按 `market_regime` / `best_buy_point.type` / `confirmations` 的 retained vs filtered breakdown。
- 如果稳定通过，再考虑进入 promotion gate 文档，而不是马上改 production。
