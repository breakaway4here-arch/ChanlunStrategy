# ChanLun Engine Phase 7.2 Analyze Dual Candidate API Result

## 结论

Phase 7.2 已完成。

本阶段只完成 `analyze_dual(candidate=...)` 对 candidate registry name 的支持，没有扩散到策略调参、回测优化或 production 路径。

## 代码提交

```text
2b7929d feat: 支持dual候选注册名
```

## 实际修改文件

```text
chanlun/chan_engine.py
tests/test_chan_engine_dual_guardrails.py
tests/test_chan_engine_provider_registry.py
```

## 新 API

`analyze_dual()` 新增 keyword-only 参数：

```python
candidate=None
```

支持：

```python
analyze_dual(..., candidate="signal")
analyze_dual(..., candidate="signal_v1")
analyze_dual(..., candidate="signal_delay1_by_type_guard")
```

内部通过：

```python
engine_candidate_registry.build_candidate_analyzer(candidate)
```

构造 candidate analyzer。

## 旧 API 兼容

以下旧调用继续保留：

```python
analyze_dual(..., candidate_analyzer=callable)
```

不传 candidate 时，默认仍是：

```text
legacy analyze() vs legacy analyze()
```

## Guardrail

同时传 `candidate` 和 `candidate_analyzer` 时明确拒绝：

```text
ValueError: candidate and candidate_analyzer are mutually exclusive
```

未知 candidate name 透出明确错误：

```text
ValueError: unknown candidate: missing
```

## 行为边界

本阶段没有修改：

```text
analyze()
ChanResult contract
run.py
policy_experiment_metrics.py
backtest runner
Phase 6 文档或实验
```

`analyze()` 仍是 production legacy 路径，不接 candidate。

## 验证结果

局部测试：

```bash
python3 -m unittest tests.test_chan_engine_dual_guardrails tests.test_chan_engine_provider_registry tests.test_engine_experiments tests.test_chan_engine_import_compat
```

结果：

```text
Ran 36 tests in 0.028s
OK
```

编译检查：

```bash
python3 -m py_compile chanlun/chan_engine.py chanlun/engine_candidate_registry.py chanlun/engine_candidate.py
```

结果：通过。

空白检查：

```bash
git diff --check
```

结果：无输出。

全量测试：

```bash
python3 -m unittest discover -s tests
```

结果：

```text
Ran 491 tests in 4.525s
OK
```

## Review 结论

未发现阻断问题。

本阶段完成后，架构链路变为：

```text
CANDIDATE_REGISTRY
  -> build_candidate_analyzer(candidate_name)
  -> analyze_dual(candidate=...)
  -> compare_chan_results()
```

production 仍保持：

```text
analyze()
  -> LEGACY_PROVIDERS
```

## 下一阶段

可以进入 Phase 7.3。

Phase 7.3 只应做 business metrics 的结构接入点：

```text
dual compare report:
  - structure diff
  - signal diff
  - optional business metric diff
```

明确边界：

```text
不新增策略实验
不继续 Phase 6.14
不改 production analyze()
不改 run.py production 路径
```

