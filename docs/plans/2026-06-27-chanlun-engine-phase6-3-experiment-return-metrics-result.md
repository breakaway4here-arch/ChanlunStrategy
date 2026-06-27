# ChanLun Engine Phase 6.3 实验收益指标接入结果

日期: 2026-06-27

## 结论

Phase 6.3 已把实验报告 runner 接入真实历史收益 metrics。

核心变化:

- `scripts/run_engine_experiments.py` 新增 `--historical-return-metrics`。
- 默认不传参数时行为不变，仍使用原内存 SCENARIOS 占位收益。
- 传入参数后，支持的 signal 实验会读取历史推荐快照和行情缓存，生成真实 return metrics。
- `signal_delay1_by_type_guard` 的 gate 已从 `insufficient_data` 变成真实 `pass`。

## 实现范围

新增:

- `chanlun/historical_experiment_metrics.py`
- `tests/test_historical_experiment_metrics.py`

修改:

- `scripts/run_engine_experiments.py`
- `tests/test_engine_experiment_runner_script.py`

## 支持的历史收益实验

```text
signal_delay1_by_type_guard
signal_p0_distance_guard
signal_p1_confirmation_guard
signal_p0_p1_guard
```

当前重点验证:

```text
signal_delay1_by_type_guard
```

## 口径

Legacy:

```text
历史快照原始推荐样本
entry_mode = immediate_close
```

Experiment:

```text
signal_delay1_by_type_guard:
  底背驰候选 -> delay1_close
  强势启动候选 -> delay1_open
  其他 -> immediate_close
```

过滤逻辑:

- `底背驰候选` 若刚形成，则过滤/延迟。
- 缺 `index` 或缺 `closes` 时 no-op。
- P0/P1 系列实验也接入对应历史过滤逻辑，避免“声明支持但实际等同 legacy”。

## 验证命令

```bash
python3 -m py_compile \
  chanlun/historical_experiment_metrics.py \
  scripts/run_engine_experiments.py

python3 -m unittest tests.test_historical_experiment_metrics -v

python3 -m unittest \
  tests.test_engine_signal_experiments \
  tests.test_engine_experiments \
  tests.test_engine_experiment_runner_script \
  -v

python3 -m unittest discover tests

python3 scripts/run_engine_experiments.py \
  --experiments signal_delay1_by_type_guard \
  --historical-return-metrics \
  --output-json /tmp/phase6_3_delay_metrics.json \
  --output-md /tmp/phase6_3_delay_metrics.md
```

## 验证结果

- py_compile: pass
- historical metrics tests: `Ran 8 tests ... OK`
- related runner/experiment tests: `Ran 25 tests ... OK`
- full tests: `Ran 428 tests ... OK`
- historical experiment report: exit code `0`

## 历史收益结果

Coverage:

```json
{
  "snapshot_days": 24,
  "picks_seen": 2842,
  "legacy_evaluated": 1706,
  "experiment_evaluated": 1287,
  "filtered": 805,
  "skipped_no_code": 0,
  "skipped_no_kline": 1,
  "not_evaluable": 1884,
  "not_evaluable_legacy": 1135,
  "not_evaluable_experiment": 749,
  "evaluated": 1287
}
```

Legacy metrics:

```json
{
  "n": 1706,
  "n_evaluable": 1706,
  "t1_mean": -0.28,
  "t1_median": -0.37,
  "t3_mean": -0.92,
  "t3_median": -2.0,
  "t3_win_rate": 35.9,
  "t3_loss_5pct_rate": 23.7,
  "max_up_3d_mean": 4.46,
  "max_dd_3d_mean": -5.03,
  "big_drop_5pct_rate": 44.4,
  "big_run_5pct_rate": 30.7
}
```

Experiment metrics:

```json
{
  "n": 1287,
  "n_evaluable": 1287,
  "t1_mean": 0.58,
  "t1_median": 0.3,
  "t3_mean": 0.03,
  "t3_median": -0.82,
  "t3_win_rate": 44.5,
  "t3_loss_5pct_rate": 18.2,
  "max_up_3d_mean": 5.24,
  "max_dd_3d_mean": -4.46,
  "big_drop_5pct_rate": 36.3,
  "big_run_5pct_rate": 38.0
}
```

Delta:

| Metric | Legacy | Experiment | Delta |
|---|---:|---:|---:|
| sample count | 1706 | 1287 | -419 |
| T+1 mean | -0.28 | 0.58 | +0.86 |
| T+3 mean | -0.92 | 0.03 | +0.95 |
| T+3 win rate | 35.9% | 44.5% | +8.6pp |
| T+3 <= -5% | 23.7% | 18.2% | -5.5pp |
| max drawdown 3d mean | -5.03 | -4.46 | +0.57 |
| big drop 5% rate | 44.4% | 36.3% | -8.1pp |
| big run 5% rate | 30.7% | 38.0% | +7.3pp |

## Gate 结果

```text
signal_delay1_by_type_guard | medium | structure pass | coverage 1287 | pass | all gates pass
```

详细 gate:

- coverage_evaluated: pass
- sample_count: pass
- t3_mean_delta: pass
- t3_win_rate_delta: pass
- t3_loss_5pct_rate_delta: pass
- big_drop_5pct_rate_delta: pass

最终:

```text
final_decision = pass
```

## 判断

`signal_delay1_by_type_guard` 是目前最值得继续推进的实验:

- 样本减少约 24.6%，但保留 1287 个可评估样本，样本量仍足够。
- 收益均值从负转接近持平。
- 胜率和风险指标同步改善。
- 大跌率下降明显，符合“延迟确认降低噪音”的原始假设。

暂不建议直接 promotion 到 production，因为:

- 当前是历史推荐快照级别评估，还不是线上重跑全 pipeline 后的推荐组合。
- `filtered=805` 较高，需要确认被过滤样本中是否存在少数大牛股被误伤。
- 后续还要和弱趋势过滤/冷却机制做组合对比。

## 下一步

进入 Phase 6.4:

1. 先对 `signal_delay1_by_type_guard` 做 filtered 样本误伤分析。
2. 再做弱趋势过滤和信号冷却，不直接改 production。
3. 每个新增规则都必须通过 `--historical-return-metrics` 输出真实 gate。
