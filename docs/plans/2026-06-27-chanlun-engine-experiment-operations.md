# ChanLun Engine Phase 5.4 实验报表与晋升门控操作手册

本文件给出实验新增、单测对比、批量报告与 promotion gate 的标准操作。

## 如何新增一个 experiment

1. 在 `chanlun/engine_experiments.py` 的 `EXPERIMENT_REGISTRY` 中新增一条 `ExperimentDefinition(...)`。
2. `name` 与 `module` 需唯一且可追踪。
3. 如有风险评估，设置 `risk`（默认 `low`）。
4. 在 `overrides` 中放入本实验替换的 provider（例如 `signal_provider`）。
5. 加入相应单测覆盖（至少 `tests/test_engine_experiments.py` 的 registry 校验）。

## 如何跑单个对比

当前推荐入口：

```bash
python3 scripts/compare_chan_engine_dual.py \
  --candidate <registry_name> \
  --business-metrics \
  --output /tmp/candidate_<registry_name>.json
```

示例：

```bash
python3 scripts/compare_chan_engine_dual.py --candidate signal_v1 --business-metrics --output /tmp/signal_v1.json
python3 scripts/compare_chan_engine_dual.py --candidate signal_delay1_by_type_guard --business-metrics --output /tmp/signal_delay1_by_type_guard.json
```

`--experiment <实验名>` 仍保留为兼容入口（旧文档/旧脚本调用），新流程建议统一使用 `--candidate`。

## 如何跑单个实验 compare（兼容入口）

该入口仍可用于旧脚本/旧批量报告兼容；新流程优先使用上一节的 `--candidate <registry_name>`。

```bash
python3 scripts/compare_chan_engine_dual.py \
  --experiment <实验名> \
  --business-metrics \
  --output /tmp/experiment_<实验名>.json
```

输出文件会包含：
- `summary`（含 `structure_equal`、`recommendation_diff`、`return_metrics`、`coverage`）
- `scenarios`（逐场景结构对比）

当前脚本仍使用 `SCENARIOS` 做快照输入，`coverage.evaluated` 可能为 0（无实时行情）。

## 如何跑 batch report

```bash
python3 scripts/run_engine_experiments.py \
  --experiments signal_p0_distance_guard,signal_p0_p1_guard \
  --output-json /tmp/engine_experiments.json \
  --output-md /tmp/engine_experiments.md
```

该脚本会按实验名逐个调用：
`scripts/compare_chan_engine_dual.py --experiment <实验名> --business-metrics`

并把每个实验汇总为一个 JSON 条目，输出字段包含：
- `experiment`
- `risk`
- `summary.structure_equal`
- `recommendation_diff`
- `return_metrics`
- `coverage`
- `gate_result`

Markdown 报表会输出实验名、风险等级、结构一致性、coverage、门禁决策。

## 如何解读 promotion gates

初始门槛：
- `sample_count >= 100`
- `t3_mean_delta >= 0.5`
- `t3_win_rate_delta >= 3.0`
- `t3_loss_5pct_rate_delta <= -3.0`
- `big_drop_5pct_rate_delta <= -5.0`
- `coverage.evaluated > 0`

`evaluate_promotion_gates(before_metrics, after_metrics, coverage)` 行为：
- 任何关键指标缺失，或 `coverage.evaluated <= 0` -> `final_decision = "insufficient_data"`
- 有完整数据时逐项 pass/fail
- 仅当全部门禁 pass 时 `final_decision = "pass"`，否则 `fail`

注意：当前 compare 产出的 `coverage.evaluated` 仍是占位（Phase 5.2 快照场景），所以通常会先得到 `insufficient_data`，这是预期结果。

## 上线约束

`chanlun.analyze()`（生产入口）不得在本阶段自动修改。
只有在门禁通过、且经过人工确认后，才允许进入生产改造流程。
