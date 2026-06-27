# ChanLun Engine Phase 6.3 实验收益指标接入计划

日期: 2026-06-27

## 背景

Phase 6.1 已经能用历史推荐快照做真实收益回测:

- `immediate_close`
- `delay1_open`
- `delay1_close`

Phase 6.2 已经把延迟规则注册成 opt-in 实验:

```text
signal_delay1_by_type_guard
```

但当前实验报告 runner 仍只跑内存 `SCENARIOS`，没有真实市场收益数据，所以 gate 结果只能是:

```text
insufficient_data
```

这会限制后续优化，因为继续增加弱趋势过滤、冷却机制、趋势/震荡分层时，只能证明结构兼容，不能证明收益改善。

## 目标

把实验 registry 和历史推荐回测打通，让 `scripts/run_engine_experiments.py` 能为 signal 类实验输出真实 return metrics。

完成后应能回答:

- 实验保留/过滤了哪些历史推荐？
- 保留样本相对 legacy 的 T+1/T+3 表现是否改善？
- loss5、big_drop、max_dd 是否下降？
- promotion gate 能否从 `insufficient_data` 进入 `promote / reject / iterate` 判断。

## 范围

### Do

- 增加一个历史快照级别的 experiment metrics runner。
- 对 signal experiment 复用历史 `docs/data/YYYY-MM-DD.json` 推荐样本。
- 对 experiment 过滤后的样本计算真实收益 metrics。
- 让 `run_engine_experiments.py` 可选地接入该 metrics。
- 保持 production `analyze()` 和 report 默认输出不变。

### Do Not

- 不改变线上选股结果。
- 不把 `signal_delay1_by_type_guard` 自动晋升 production。
- 不把无行情样本静默当作失败样本。
- 不修改已有 Phase 6.1 回测结果口径。

## 设计

新增模块建议:

```text
chanlun/historical_experiment_metrics.py
```

职责:

1. 读取历史推荐快照。
2. 识别 `best_buy_point`。
3. 对 opt-in experiment 应用过滤/保留规则。
4. 复用 `chanlun.backtest_execution.evaluate_forward_returns()`。
5. 输出 legacy vs experiment 的 return metrics 和 coverage。

建议先只支持 signal guard 类实验:

```text
signal_delay1_by_type_guard
signal_p0_distance_guard
signal_p1_confirmation_guard
signal_p0_p1_guard
```

后续如果要支持 pivot/trend 等结构实验，再单独扩展。

## 核心口径

### Legacy

legacy 样本 = 历史快照中的原始推荐样本。

收益口径:

```text
entry_mode = immediate_close
```

### Experiment

experiment 样本 = 对 legacy 样本应用对应 signal guard 后保留的样本。

Phase 6.3 先做“过滤后收益评估”，不模拟真实重排后的新增样本。

收益口径:

```text
signal_delay1_by_type_guard:
  底背驰候选 -> delay1_close
  强势启动候选 -> delay1_open
  其他 -> immediate_close

其他 signal guard:
  immediate_close
```

## 输出字段

建议 JSON:

```json
{
  "experiment": "signal_delay1_by_type_guard",
  "coverage": {
    "snapshot_days": 24,
    "picks_seen": 2842,
    "legacy_evaluated": 1706,
    "experiment_evaluated": 1695,
    "filtered": 0,
    "skipped_no_kline": 1,
    "not_evaluable": 1146
  },
  "return_metrics": {
    "legacy": {
      "sample_count": 1706,
      "t3_mean": -0.91,
      "t3_win_rate": 35.9,
      "t3_loss_5pct_rate": 23.7,
      "big_drop_5pct_rate": 44.4
    },
    "experiment": {
      "sample_count": 1695,
      "t3_mean": -0.99,
      "t3_win_rate": 37.4,
      "t3_loss_5pct_rate": 24.8,
      "big_drop_5pct_rate": 44.6
    }
  }
}
```

具体数值以实现后实际跑出的结果为准。

## 任务拆解

### Task 1: 抽出历史推荐样本过滤器

文件:

- 新增: `chanlun/historical_experiment_metrics.py`
- 测试: `tests/test_historical_experiment_metrics.py`

要求:

- 支持按 experiment name 判断某个 pick 是否保留。
- `signal_delay1_by_type_guard` 应过滤刚形成的 `底背驰候选`。
- 缺 `best_buy_point.index`、缺 `closes` 时 no-op。
- 强势启动候选保留。

### Task 2: 接入收益计算

文件:

- 修改: `chanlun/historical_experiment_metrics.py`
- 测试: `tests/test_historical_experiment_metrics.py`

要求:

- 复用 `evaluate_forward_returns()`。
- 支持按 buy point type 选择 entry mode。
- 输出 legacy / experiment samples。
- 输出 coverage。

### Task 3: 接入 run_engine_experiments.py

文件:

- 修改: `scripts/run_engine_experiments.py`
- 测试: `tests/test_run_engine_experiments.py` 或新增对应脚本测试。

建议参数:

```bash
--historical-return-metrics
```

行为:

- 未传该参数时保持现状。
- 传入后，对支持的 signal experiment 附加真实 return metrics。
- gate 使用真实 metrics，不再返回 `coverage.evaluated=0`。

### Task 4: 生成 Phase 6.3 结果文档

文件:

```text
docs/plans/2026-06-27-chanlun-engine-phase6-3-experiment-return-metrics-result.md
```

内容:

- 命令
- coverage
- legacy vs experiment 指标
- gate 结论
- 是否进入 Phase 6.4 弱趋势/冷却

## 验证命令

```bash
python3 -m py_compile \
  chanlun/historical_experiment_metrics.py \
  scripts/run_engine_experiments.py

python3 -m unittest \
  tests.test_historical_experiment_metrics \
  tests.test_engine_signal_experiments \
  tests.test_engine_experiments \
  -v

python3 -m unittest discover tests

python3 scripts/run_engine_experiments.py \
  --experiments signal_delay1_by_type_guard \
  --historical-return-metrics \
  --output-json /tmp/phase6_3_delay_metrics.json \
  --output-md /tmp/phase6_3_delay_metrics.md
```

如果实现选择新增独立脚本，也必须保留 `run_engine_experiments.py` 的现有行为不变。

## 验收标准

- Full tests pass。
- `signal_delay1_by_type_guard` 生成真实 `return_metrics.legacy` 和 `return_metrics.experiment`。
- `coverage.evaluated > 0`。
- Gate 不再因为 `coverage.evaluated=0` 返回 `insufficient_data`。
- production `analyze()` 不变。

## 回滚

如果历史收益接入出现口径争议:

1. 保留 Phase 6.1 独立回测脚本。
2. 回退 `--historical-return-metrics` 参数接入。
3. 保留 signal experiment registry，不影响 production。

## 后续

Phase 6.4 再执行原计划中的:

- 弱趋势过滤
- 信号冷却机制
- 趋势/震荡分层

但这些规则必须基于 Phase 6.3 的真实收益 metrics 做 promotion gate，不能只看结构 diff。
