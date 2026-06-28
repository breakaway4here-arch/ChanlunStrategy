# ChanLun Engine Docs Registry CLI Sync Result

## 结论

本批次已完成。

当前操作口径已同步为：

```bash
python3 scripts/compare_chan_engine_dual.py \
  --candidate <registry_name> \
  --business-metrics \
  --output /tmp/candidate_<registry_name>.json
```

`--experiment <name>` 仍保留为兼容入口，但不再作为主推入口。

## 实际修改文件

```text
docs/plans/2026-06-28-chanlun-engine-docs-registry-cli-sync.md
docs/plans/2026-06-27-chanlun-engine-experiment-operations.md
scripts/compare_chan_engine_dual.py
tests/test_chan_engine_experiment_script.py
docs/plans/2026-06-28-chanlun-engine-docs-registry-cli-sync-result.md
```

## 同步内容

### 操作手册

更新：

```text
docs/plans/2026-06-27-chanlun-engine-experiment-operations.md
```

新增当前推荐入口：

```bash
python3 scripts/compare_chan_engine_dual.py --candidate signal_v1 --business-metrics --output /tmp/signal_v1.json
python3 scripts/compare_chan_engine_dual.py --candidate signal_delay1_by_type_guard --business-metrics --output /tmp/signal_delay1_by_type_guard.json
```

旧入口标题调整为：

```text
如何跑单个实验 compare（兼容入口）
```

并明确 `--experiment <实验名>` 用于旧文档/旧脚本兼容。

### 脚本 Help

更新：

```text
scripts/compare_chan_engine_dual.py
```

`--candidate` help 说明 candidate registry name：

```text
candidate registry name (e.g. signal, signal_v1, signal_delay1_by_type_guard)
```

`--experiment` help 说明兼容用途：

```text
compatibility alias for experiment registry names
```

### 测试

更新：

```text
tests/test_chan_engine_experiment_script.py
```

新增 `--help` 测试，确认 help 输出包含：

```text
candidate registry
--candidate
--experiment
```

## 边界确认

本批次没有修改：

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

没有新增策略、没有新增回测 runner、没有访问真实行情。

## 验证结果

局部测试：

```bash
python3 -m unittest tests.test_chan_engine_experiment_script
```

结果：

```text
Ran 8 tests in 1.792s
OK
```

编译检查：

```bash
python3 -m py_compile scripts/compare_chan_engine_dual.py
```

结果：通过。

空白检查：

```bash
git diff --check
```

结果：无输出。

组尾全量测试：

```bash
python3 -m unittest discover -s tests
```

结果：

```text
Ran 502 tests in 5.915s
OK
```

## 后续

候选插件架构的主线已经完成：

```text
registry -> analyze_dual(candidate=...) -> CLI --candidate <registry_name> -> docs/help synced
```

后续除非有明确新需求，不建议继续拆架构小阶段。

