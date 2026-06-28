# ChanLun Engine Phase 7 Final Audit

## 结论

Phase 7 主线已闭环。

本轮目标是把 candidate 从“复制 legacy 的第二套缠论”收拢为可插拔实验系统，并保持 production `analyze()` 不变。

当前实现已经满足：

```text
candidate = 插件系统，不是第二套缠论
```

## 审计范围

本次审计覆盖：

```text
Phase 7.1 Candidate Registry Facade
Phase 7.2 Analyze Dual Candidate API
Phase 7.3 Dual Business Metrics Hook
```

对应文档：

```text
docs/plans/2026-06-27-chanlun-engine-phase7-1-candidate-registry-facade.md
docs/plans/2026-06-27-chanlun-engine-phase7-1-candidate-registry-facade-result.md
docs/plans/2026-06-27-chanlun-engine-phase7-2-analyze-dual-candidate-api.md
docs/plans/2026-06-27-chanlun-engine-phase7-2-analyze-dual-candidate-api-result.md
docs/plans/2026-06-27-chanlun-engine-phase7-3-dual-business-metrics-hook.md
docs/plans/2026-06-27-chanlun-engine-phase7-3-dual-business-metrics-hook-result.md
```

## 已完成提交

```text
79418a6 docs: 添加候选注册门面实施方案
ac92e4e feat: 添加候选注册门面
8ebf35f docs: 添加候选注册门面结果
c73d087 docs: 添加dual候选API实施方案
2b7929d feat: 支持dual候选注册名
9bbc7fd docs: 添加dual候选API结果
4aff310 docs: 添加dual业务指标hook方案
a8b0b8b feat: 添加dual业务指标hook
d44f1f0 docs: 添加dual业务指标hook结果
```

## Requirement Audit

### 1. analyze() 永远不变

状态：通过。

当前 `chanlun/chan_engine.py::analyze()` 仍固定：

```python
analyze_with_provider_bundle(..., providers=LEGACY_PROVIDERS)
```

测试覆盖：

```text
tests/test_chan_engine_provider_registry.py::test_public_analyze_uses_legacy_provider_bundle
tests/test_chan_engine_provider_registry.py::test_legacy_provider_bundle_matches_public_analyze
```

### 2. candidate 不能复制 legacy

状态：通过。

当前 candidate provider bundle 通过：

```text
engine_experiments.EXPERIMENT_REGISTRY
build_experiment_provider_bundle()
with_provider_overrides()
```

实现为单模块 override 或 `all_v1` provider bundle，不复制 full engine。

测试覆盖：

```text
tests/test_chan_engine_provider_registry.py::test_single_candidate_provider_bundles_override_only_their_component
tests/test_chan_engine_provider_registry.py::test_build_candidate_provider_bundle_matches_registry
```

### 3. candidate registry 化

状态：通过。

新增：

```text
chanlun/engine_candidate_registry.py
```

提供：

```python
CandidateDefinition
CANDIDATE_REGISTRY
get_candidate_definition(name)
list_candidate_definitions()
build_candidate_provider_bundle(name)
build_candidate_analyzer(name)
```

支持 legacy alias：

```text
macd
inclusion
fractal
stroke
segment
pivot
trend
divergence
signal
all
```

支持 canonical experiment name：

```text
signal_v1
signal_delay1_by_type_guard
all_v1
...
```

### 4. analyze_dual 只做对比

状态：通过。

`analyze_dual()` 当前职责：

```text
legacy analyze()
candidate analyzer
compare_chan_results()
optional business_metrics hook
```

不访问行情，不计算真实收益，不接 production `run.py`。

测试覆盖：

```text
tests/test_chan_engine_dual_guardrails.py::test_run_py_does_not_reference_analyze_dual
tests/test_chan_engine_dual_guardrails.py::test_analyze_dual_default_candidate_matches_legacy
```

### 5. analyze_dual 支持 candidate registry name

状态：通过。

支持：

```python
analyze_dual(..., candidate="signal")
analyze_dual(..., candidate="signal_v1")
analyze_dual(..., candidate="signal_delay1_by_type_guard")
```

同时保留：

```python
analyze_dual(..., candidate_analyzer=callable)
```

并对二者同时传入做互斥保护。

测试覆盖：

```text
tests/test_chan_engine_dual_guardrails.py::test_analyze_dual_accepts_candidate_registry_names
tests/test_chan_engine_dual_guardrails.py::test_analyze_dual_rejects_mutually_exclusive_inputs
tests/test_chan_engine_dual_guardrails.py::test_analyze_dual_unknown_candidate_is_rejected
```

### 6. 支持 business metrics 接入点

状态：通过。

`analyze_dual()` 支持：

```python
business_metrics=dict
business_metrics=callable
```

默认不传时不改变返回结构。

新增：

```text
chanlun/engine_dual_metrics.py
```

提供：

```python
result_to_recommendations()
build_dual_business_metrics()
build_aggregate_dual_business_metrics()
```

该 helper 只做结构整理和推荐差异比较，不新增收益计算。

测试覆盖：

```text
tests/test_chan_engine_dual_guardrails.py::test_analyze_dual_default_has_no_business_metrics
tests/test_chan_engine_dual_guardrails.py::test_analyze_dual_business_metrics_accepts_dict
tests/test_chan_engine_dual_guardrails.py::test_analyze_dual_business_metrics_accepts_callable
tests/test_engine_dual_metrics.py
```

### 7. 每阶段落盘 MD

状态：通过。

Phase 7.1、7.2、7.3 均已包含：

```text
实施方案 MD
结果 MD
```

并均已提交推送。

### 8. 小兵实施，主线程 review/test/push

状态：通过。

执行方式：

```text
每阶段先落盘 MD
小兵按 MD 实施代码
主线程 review diff
主线程运行局部测试、py_compile、git diff --check、全量 unittest
主线程 commit/push
主线程补结果文档并 push
```

## Verification Evidence

Phase 7.1：

```text
Ran 487 tests
OK
```

Phase 7.2：

```text
Ran 491 tests
OK
```

Phase 7.3：

```text
Ran 499 tests
OK
```

最终远端同步：

```text
git rev-list --left-right --count origin/main...HEAD
0 0
```

## Remaining Local State

当前仅剩本地未跟踪工具目录：

```text
.codegraph/
```

该目录是本地 CodeGraph 工具状态，不属于业务代码或 Phase 7 交付物。

## Final Architecture

当前架构：

```text
analyze()
  -> LEGACY_PROVIDERS
  -> production ChanResult

CANDIDATE_REGISTRY
  -> CandidateDefinition
  -> build_candidate_provider_bundle(name)
  -> build_candidate_analyzer(name)

analyze_dual(candidate=...)
  -> legacy analyze()
  -> candidate analyzer
  -> compare_chan_results()
  -> optional business_metrics
```

## 收口建议

Phase 7 不再继续新增阶段。

后续如果要继续优化，应另起明确新目标，并先判断是否属于：

```text
架构增强
策略实验
回测评估
production 接入
```

不能再把短期修复自然扩散成新的策略调参线。

