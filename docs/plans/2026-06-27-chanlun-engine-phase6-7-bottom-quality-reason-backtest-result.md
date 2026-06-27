# ChanLun Engine Phase 6.7 Bottom Quality Reason Backtest Result

## 结论

Phase 6.7 已完成实现、测试和真实历史回测。

本轮结论是：`bottom_quality_guard` 的有效贡献主要来自两个 reason：

- `bottom_distance_gt_6`
- `bottom_missing_shape_or_stop_drop`

其中 `bottom_distance_gt_6` 最值得继续保留和组合验证。它过滤样本少，保留率 `96.50%`，但 T+3 均值、胜率和尾部风险都略有改善。

`bottom_missing_shape_or_stop_drop` 能提升均值和胜率，但尾部风险变差，不适合单独晋级。

`bottom_missing_key_protection`、`bottom_missing_distance`、`bottom_invalid_distance` 在当前 v1 baseline 样本里没有命中，暂时没有继续单独优化价值。

## 本轮代码范围

- 更新 `chanlun/policy_experiment_metrics.py`
  - 新增 `bottom_quality_guard_reasons(pick)`。
  - 新增 reason-level policy。
  - 复合 `bottom_quality_guard` 行为保持不变。
  - `policy_filtered_by_reason` 保持互斥计数。
  - 新增 `policy_filtered_detail_by_reason` 承载复合 policy 的细分原因。
- 更新 `scripts/run_policy_experiments.py`
  - 保持原输出格式。
  - 新增 `Filter Detail Reason Summary`，展示复合 policy 的细分原因。
- 更新测试：
  - `tests/test_policy_experiment_metrics.py`
  - `tests/test_policy_experiment_runner_script.py`

## 测试结果

```bash
python3 -m unittest tests.test_policy_experiment_metrics tests.test_policy_experiment_runner_script
```

结果：`Ran 14 tests in 0.350s OK`

```bash
python3 -m unittest tests.test_policy_experiment_metrics tests.test_policy_experiment_runner_script tests.test_historical_experiment_metrics tests.test_engine_experiment_runner_script
```

结果：`Ran 31 tests in 1.771s OK`

```bash
python3 -m unittest discover -s tests
```

结果：`Ran 457 tests in 4.803s OK`

```bash
python3 -m py_compile chanlun/policy_experiment_metrics.py scripts/run_policy_experiments.py
```

结果：通过。

```bash
git diff --check
```

结果：通过。

## 真实回测命令

```bash
python3 scripts/run_policy_experiments.py \
  --policies delay1_v1,delay1_v1_bottom_quality_guard,delay1_v1_bottom_missing_key_guard,delay1_v1_bottom_missing_distance_guard,delay1_v1_bottom_invalid_distance_guard,delay1_v1_bottom_distance_gt6_guard,delay1_v1_bottom_missing_shape_guard \
  --output-json /tmp/phase6_7_bottom_quality_reason_metrics.json \
  --output-md /tmp/phase6_7_bottom_quality_reason_metrics.md
```

结果文件：

- `/tmp/phase6_7_bottom_quality_reason_metrics.json`
- `/tmp/phase6_7_bottom_quality_reason_metrics.md`

注意：执行过程中仍有大量远端日线获取失败，并使用项目缓存兜底，形如 `[CACHE FALLBACK] day <code> remote failed, using cache`。这次结果可用于策略方向判断；如要做上线晋级，应固定缓存版本或改善数据源稳定性后复跑。

## 回测样本

- `generated_at`: `2026-06-27T20:34:02.405221`
- `snapshot_rows`: `2842`
- `baseline_policy`: `signal_delay1_by_type_guard`
- `baseline_evaluated`: `1287`
- `baseline_filtered`: `805`
- baseline 指标：
  - `t1_mean`: `0.58`
  - `t3_mean`: `0.03`
  - `t3_win_rate`: `44.5`
  - `t3_loss_5pct_rate`: `18.2`
  - `max_dd_3d_mean`: `-4.46`
  - `big_drop_5pct_rate`: `36.3`
  - `big_run_5pct_rate`: `38.0`

## Policy 对比

| Policy | n | Filtered | Retained % | T+1 | T+3 | ΔT+3 | T+3 Win | ΔWin | Loss <= -5% | ΔLoss5 | Big Drop | ΔBigDrop | Filter Reason |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| delay1_v1 | 1287 | 0 | 100.00 | 0.58 | 0.03 | 0.00 | 44.5 | 0.0 | 18.2 | 0.0 | 36.3 | 0.0 | - |
| delay1_v1_bottom_quality_guard | 1101 | 186 | 85.55 | 0.66 | 0.16 | +0.13 | 45.9 | +1.4 | 18.7 | +0.5 | 36.9 | +0.6 | bottom_quality_guard:186 |
| delay1_v1_bottom_missing_key_guard | 1287 | 0 | 100.00 | 0.58 | 0.03 | 0.00 | 44.5 | 0.0 | 18.2 | 0.0 | 36.3 | 0.0 | - |
| delay1_v1_bottom_missing_distance_guard | 1287 | 0 | 100.00 | 0.58 | 0.03 | 0.00 | 44.5 | 0.0 | 18.2 | 0.0 | 36.3 | 0.0 | - |
| delay1_v1_bottom_invalid_distance_guard | 1287 | 0 | 100.00 | 0.58 | 0.03 | 0.00 | 44.5 | 0.0 | 18.2 | 0.0 | 36.3 | 0.0 | - |
| delay1_v1_bottom_distance_gt6_guard | 1242 | 45 | 96.50 | 0.60 | 0.07 | +0.04 | 44.8 | +0.3 | 18.0 | -0.2 | 36.2 | -0.1 | bottom_distance_gt_6:45 |
| delay1_v1_bottom_missing_shape_guard | 1129 | 158 | 87.72 | 0.63 | 0.12 | +0.09 | 45.5 | +1.0 | 18.6 | +0.4 | 37.0 | +0.7 | bottom_missing_shape_or_stop_drop:158 |

## 复合规则拆解

`delay1_v1_bottom_quality_guard` 共过滤 `186` 个样本，细分 reason 为：

| Detail Reason | Count |
| --- | ---: |
| bottom_distance_gt_6 | 45 |
| bottom_missing_shape_or_stop_drop | 158 |

两个细分计数相加超过 `186`，说明存在重叠样本。代码里已把互斥主计数和细分 detail 计数拆开，避免后续把 detail count 误认为过滤样本总数。

## 单 Reason 判断

### bottom_distance_gt_6

建议进入下一阶段组合验证：

- 过滤 `45` 个样本，保留率 `96.50%`。
- T+3 均值提升 `0.04`。
- 胜率提升 `0.3`。
- `T+3 <= -5%` 下降 `0.2`。
- `big_drop_5pct_rate` 下降 `0.1`。

它不是强收益提升，但方向比较干净：收益和尾部风险同时小幅改善。

### bottom_missing_shape_or_stop_drop

不建议单独晋级：

- 过滤 `158` 个样本，保留率 `87.72%`。
- T+3 均值提升 `0.09`。
- 胜率提升 `1.0`。
- 但 `T+3 <= -5%` 增加 `0.4`。
- `big_drop_5pct_rate` 增加 `0.7`。

它贡献了复合规则的大部分均值提升，但也带来了尾部风险恶化。

### bottom_missing_key_protection

当前样本命中 `0`，暂不继续。

### bottom_missing_distance

当前样本命中 `0`，暂不继续。

### bottom_invalid_distance

当前样本命中 `0`，暂不继续。

## 下一步建议

Phase 6.8 建议做性能和评估质量优化，而不是继续加交易规则：

1. 重构 `run_policy_experiment_metrics()`，让多 policy 共享 snapshot rows、kline cache 和 baseline samples。
2. 保持输出指标不变，用测试锁定与当前实现一致。
3. 再复跑 Phase 6.7 回测，确认结果一致但耗时明显下降。

如果继续策略方向，则只把 `bottom_distance_gt_6` 作为候选，与后续 market regime 或趋势过滤组合测试；不要把完整 `bottom_quality_guard` 直接升入 production。
