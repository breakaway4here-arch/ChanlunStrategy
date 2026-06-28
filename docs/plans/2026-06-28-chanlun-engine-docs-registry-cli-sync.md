# ChanLun Engine Docs Registry CLI Sync

## 背景

当前代码已经收敛为：

```text
candidate registry
  -> analyze_dual(candidate=...)
  -> scripts/compare_chan_engine_dual.py --candidate <registry_name>
```

但部分操作文档仍把 `--experiment <实验名>` 描述成主要入口。

本批次只做轻量文档/帮助信息同步，不改策略、不改回测、不改 production。

## 新执行节奏

继续采用快流程：

```text
总 MD 落盘
小兵改文档/脚本 help/必要测试
主线程 review + 局部验证
组尾全量测试
结果 MD
统一提交 push
```

## 目标

把当前操作口径统一为：

```bash
python3 scripts/compare_chan_engine_dual.py \
  --candidate <registry_name> \
  --business-metrics \
  --output /tmp/candidate_<registry_name>.json
```

示例：

```bash
python3 scripts/compare_chan_engine_dual.py --candidate signal_v1 --business-metrics --output /tmp/signal_v1.json
python3 scripts/compare_chan_engine_dual.py --candidate signal_delay1_by_type_guard --business-metrics --output /tmp/signal_delay1.json
```

`--experiment <name>` 保留为兼容旧实验脚本/旧文档的入口，但不再作为主推入口。

## 允许修改

```text
docs/plans/2026-06-27-chanlun-engine-experiment-operations.md
scripts/compare_chan_engine_dual.py
tests/test_chan_engine_experiment_script.py
docs/plans/2026-06-28-chanlun-engine-docs-registry-cli-sync-result.md
```

必要时可以增加一个极小测试，确认 help 文案包含 registry candidate 提示。

## 禁止修改

```text
run.py
chanlun/chan_engine.py
chanlun/engine_candidate_registry.py
chanlun/policy_experiment_metrics.py
chanlun/backtest_execution.py
chanlun/backtest_metrics.py
scripts/run_policy_experiments.py
任何 Phase 6 文档
```

## 具体任务

### 1. 更新操作手册

更新：

```text
docs/plans/2026-06-27-chanlun-engine-experiment-operations.md
```

要求：

- 增加“当前推荐入口”说明：`--candidate <registry_name>`。
- 明确 `--experiment` 是兼容入口。
- 示例使用 `--candidate signal_v1` 和 `--candidate signal_delay1_by_type_guard`。
- 保留 batch report 中 `scripts/run_engine_experiments.py --experiments ...` 的描述，因为该脚本仍是 experiment batch runner。
- 不改历史指标门槛和 gate 说明。

### 2. 更新脚本 help

在 `scripts/compare_chan_engine_dual.py` 的 argparse help 中说明：

```text
--candidate: candidate registry name, e.g. signal, signal_v1, signal_delay1_by_type_guard
--experiment: compatibility alias for experiment registry names
```

不改变 CLI 行为。

### 3. 补测试

如果脚本 help 有可测性，补一个小测试：

```bash
python3 scripts/compare_chan_engine_dual.py --help
```

断言输出包含：

```text
candidate registry
--candidate
--experiment
```

或者在现有脚本测试中覆盖即可。

## 局部验证

```bash
python3 -m unittest tests.test_chan_engine_experiment_script
python3 -m py_compile scripts/compare_chan_engine_dual.py
git diff --check
```

## 组尾验证

```bash
python3 -m unittest discover -s tests
```

## 完成文档

新增：

```text
docs/plans/2026-06-28-chanlun-engine-docs-registry-cli-sync-result.md
```

包含：

- 实际修改文件。
- 新旧 CLI 口径。
- 测试结果。
- 是否还有必要继续。

## 统一提交策略

本批次组尾统一提交：

```bash
git add -f docs/plans/2026-06-28-chanlun-engine-docs-registry-cli-sync.md
git add -f docs/plans/2026-06-28-chanlun-engine-docs-registry-cli-sync-result.md
git add docs/plans/2026-06-27-chanlun-engine-experiment-operations.md scripts/compare_chan_engine_dual.py tests/test_chan_engine_experiment_script.py
git commit -m "docs: 同步候选注册CLI操作口径"
git push origin main
```

