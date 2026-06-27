# ChanLun Engine Phase 7.3 Dual Business Metrics Hook Result

## 结论

Phase 7.3 已完成。

本阶段只新增 dual payload 的可选 `business_metrics` hook，并把脚本层已有 business metrics 输出收敛到 helper。没有新增收益策略、没有访问真实行情、没有修改 production `analyze()`。

## 代码提交

```text
a8b0b8b feat: 添加dual业务指标hook
```

## 实际修改文件

```text
chanlun/chan_engine.py
chanlun/engine_dual_metrics.py
scripts/compare_chan_engine_dual.py
tests/test_chan_engine_dual_guardrails.py
tests/test_engine_dual_metrics.py
```

## Core Hook

`analyze_dual()` 新增 keyword-only 参数：

```python
business_metrics=None
```

默认不传时，返回结构保持不变：

```text
legacy
candidate
comparison
```

传入 dict 时原样挂载：

```python
analyze_dual(..., business_metrics={"status": "dict_input"})
```

传入 callable 时，在 structural compare 完成后调用：

```python
business_metrics(
    legacy=legacy,
    candidate=candidate_result,
    comparison=comparison,
)
```

callable 返回 `None` 时挂载：

```python
{"status": "not_provided"}
```

## Helper

新增：

```text
chanlun/engine_dual_metrics.py
```

提供：

```python
result_to_recommendations(result)
build_dual_business_metrics(...)
build_aggregate_dual_business_metrics(...)
```

helper 只做：

```text
ChanResult buy_points -> recommendation records
compare_recommendations(...)
return_metrics/coverage 字段归一
```

helper 不做：

```text
不拉行情
不计算 forward returns
不新增策略
不跑回测
```

## Script Compatibility

`scripts/compare_chan_engine_dual.py --business-metrics` 继续保留旧输出 key：

```text
structure_equal
recommendation_diff
return_metrics
coverage
```

其中 `return_metrics` 的旧字段仍保留：

```text
legacy
experiment
```

避免破坏已有 JSON 消费方。

## 行为边界

本阶段没有修改：

```text
analyze()
ChanResult contract
run.py
policy_experiment_metrics.py
backtest_execution.py
backtest_metrics.py
scripts/run_policy_experiments.py
任何 Phase 6 文档或实验
```

production 仍保持：

```text
analyze() -> LEGACY_PROVIDERS
```

## 验证结果

局部测试：

```bash
python3 -m unittest tests.test_chan_engine_dual_guardrails tests.test_engine_dual_metrics tests.test_chan_engine_experiment_script tests.test_chan_engine_provider_registry
```

结果：

```text
Ran 34 tests in 1.123s
OK
```

编译检查：

```bash
python3 -m py_compile chanlun/chan_engine.py chanlun/engine_dual_metrics.py scripts/compare_chan_engine_dual.py
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
Ran 499 tests in 5.545s
OK
```

## Review 结论

未发现阻断问题。

Phase 7.3 完成后，dual compare 已具备三层结构：

```text
structure diff
signal/recommendation diff
optional business metrics hook
```

这满足原始方向：

```text
candidate = 插件系统，不是第二套缠论
analyze_dual() = legacy/candidate compare + optional business metrics
```

## 后续建议

Phase 7 主线已基本闭环。

后续不建议继续新增 Phase 7.4，除非有明确新需求。下一步更适合做一次收尾复核：

```text
Phase 7 Final Audit
```

复核内容：

- `analyze()` production 路径未变。
- candidate registry name 可列举、可构造 provider bundle、可构造 analyzer。
- `analyze_dual(candidate=...)` 可跑。
- `business_metrics` hook 可选且默认不影响 structural compare。
- scripts/tests/docs 三者一致。

