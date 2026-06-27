# ChanLun Engine Phase 6.2 延迟信号实验结果

日期: 2026-06-27

## 结论

Phase 6.2 已把 Phase 6.1 的延迟入场结论转成 opt-in candidate 实验:

```text
signal_delay1_by_type_guard
```

该实验只作用于 signal provider，不改变 production `analyze()`。

当前实现策略:

- `底背驰候选`: 如果信号刚在最新 K 线形成，则延迟/过滤，等待至少 1 根后续 K 线确认。
- `强势启动候选`: 不被该 close guard 过滤，避免误伤 Phase 6.1 中表现较好的启动类信号。
- 缺少 `index`、缺少 `result.closes`、类型不匹配时 no-op。

## 实现范围

修改文件:

- `chanlun/engine_signal_experiments.py`
- `chanlun/engine_experiments.py`
- `tests/test_engine_signal_experiments.py`
- `tests/test_engine_experiments.py`

新增能力:

- `_is_signal_newly_formed(point, closes, required_bars=1)`
- `locate_buy_sell_points_delay1_by_type_guard(result)`
- 实验注册 `signal_delay1_by_type_guard`

## 行为约束

该阶段保持以下边界:

- 不修改 `analyze()` 默认行为。
- 不修改报告默认选股结果。
- 不修改 legacy provider bundle。
- 只通过 `build_experiment_provider_bundle("signal_delay1_by_type_guard")` 显式启用。

## 验证命令

```bash
python3 -m py_compile chanlun/engine_signal_experiments.py chanlun/engine_experiments.py

python3 -m unittest \
  tests.test_engine_signal_experiments \
  tests.test_engine_experiments \
  tests.test_chan_engine_experiment_script \
  -v

python3 -m unittest discover tests

python3 scripts/compare_chan_engine_dual.py \
  --experiment signal_delay1_by_type_guard \
  --business-metrics \
  --output /tmp/delay_experiment.json

python3 scripts/run_engine_experiments.py \
  --experiments signal_delay1_by_type_guard \
  --output-json /tmp/delay_experiment_report.json \
  --output-md /tmp/delay_experiment_report.md
```

## 验证结果

- py_compile: pass
- targeted tests: `Ran 25 tests ... OK`
- full tests: `Ran 419 tests ... OK`
- dual compare: exit code `0`
- experiment report: exit code `0`

Dual compare summary:

```json
{
  "all_equal": true,
  "scenario_count": 5,
  "candidate": "legacy",
  "structure_equal": true,
  "recommendation_diff": {
    "legacy_count": 0,
    "experiment_count": 0,
    "added_codes": [],
    "removed_codes": [],
    "kept_codes": [],
    "changed_best_buy_point_codes": []
  },
  "return_metrics": {
    "status": "no_market_data",
    "legacy": null,
    "experiment": null
  },
  "coverage": {
    "evaluated": 0,
    "skipped_no_market_data": 5,
    "reason": "Phase 5.2 runs on in-memory SCENARIOS only; no market fetch"
  },
  "experiment": "signal_delay1_by_type_guard"
}
```

Experiment gate:

```text
signal_delay1_by_type_guard | medium | structure pass | coverage 0 | insufficient_data
```

`insufficient_data` 是预期结果: 当前 `run_engine_experiments.py` 使用内存场景验证结构兼容，还没有接入真实收益回测。

## 下一阶段

Phase 6.3 应把 Phase 6.1 的真实收益回测和 Phase 6.2 的实验 registry 接起来:

1. 让实验报告 runner 可读取历史推荐/行情回测结果。
2. 对 `signal_delay1_by_type_guard` 输出真实 return metrics。
3. 把 promotion gate 从 `insufficient_data` 推进到可判断 `promote / reject / iterate`。

建议优先级高于继续新增过滤规则，因为没有真实收益 metrics 时，新实验只能证明结构兼容，不能证明收益改善。
