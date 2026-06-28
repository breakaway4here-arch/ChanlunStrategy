# ChanLun Engine Registry Usage Surface Convergence Result

## 结论

本批次已完成。

`scripts/compare_chan_engine_dual.py` 的使用面已收敛到 candidate registry name：

```bash
python3 scripts/compare_chan_engine_dual.py --candidate signal
python3 scripts/compare_chan_engine_dual.py --candidate signal_v1
python3 scripts/compare_chan_engine_dual.py --candidate signal_delay1_by_type_guard
```

旧的 `--experiment signal_v1` 仍兼容，但内部不再自己拼 experiment provider bundle，而是复用：

```python
analyze_dual(candidate=...)
engine_candidate_registry
```

## 实际修改文件

```text
docs/plans/2026-06-28-chanlun-engine-registry-usage-surface-convergence.md
scripts/compare_chan_engine_dual.py
tests/test_chan_engine_experiment_script.py
docs/plans/2026-06-28-chanlun-engine-registry-usage-surface-convergence-result.md
```

## 行为变化

### --candidate 支持 registry name

`--candidate` choices 从 legacy `CANDIDATE_ANALYZERS.keys()` 改为：

```python
("legacy", *list_candidate_definitions())
```

因此支持：

```text
signal
signal_v1
signal_delay1_by_type_guard
all_v1
...
```

### --experiment 保持兼容

`--experiment` 仍保留，兼容现有测试和调用：

```bash
python3 scripts/compare_chan_engine_dual.py --experiment signal_v1
```

但内部改为：

```python
analyze_dual(candidate="signal_v1")
```

### Summary 字段

保留旧字段：

```text
summary.candidate
summary.experiment
summary.all_equal
summary.scenario_count
```

新增审计字段：

```text
summary.candidate_registry_name
```

仅实际使用 registry candidate 时出现。

### business metrics 兼容

`--business-metrics` 旧输出 key 保持：

```text
structure_equal
recommendation_diff
return_metrics
coverage
```

## 边界确认

本批次没有修改：

```text
run.py
production analyze()
policy_experiment_metrics.py
backtest_execution.py
backtest_metrics.py
任何 Phase 6 文档
```

没有新增策略、没有新增回测 runner、没有访问真实行情。

## 验证结果

局部测试：

```bash
python3 -m unittest tests.test_chan_engine_experiment_script tests.test_chan_engine_dual_guardrails tests.test_chan_engine_provider_registry
```

结果：

```text
Ran 32 tests in 1.444s
OK
```

编译检查：

```bash
python3 -m py_compile scripts/compare_chan_engine_dual.py chanlun/chan_engine.py chanlun/engine_candidate_registry.py
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
Ran 501 tests in 5.749s
OK
```

## 后续

这个批次已经把 CLI 使用面收敛到 registry。

下一步不建议继续拆新的架构小阶段；更适合进入：

```text
轻量清理 + 文档同步
```

只处理：

- README 或开发文档中仍指向旧 `--experiment` 主入口的描述。
- 脚本示例是否统一使用 `--candidate <registry_name>`。

仍不进入策略优化或回测调参。

