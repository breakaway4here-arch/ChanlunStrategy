# ChanLun Engine Phase 7.1 Candidate Registry Facade Result

## 结论

Phase 7.1 已完成。

本阶段按 `docs/plans/2026-06-27-chanlun-engine-phase7-1-candidate-registry-facade.md` 收敛到实际 candidate 插件架构，不继续扩散 Phase 6 的交易参数和回测小实验。

## 代码提交

```text
ac92e4e feat: 添加候选注册门面
```

## 实际修改文件

```text
chanlun/engine_candidate_registry.py
chanlun/engine_candidate.py
tests/test_chan_engine_provider_registry.py
```

## 完成内容

### 1. 新增 Candidate Registry Facade

新增 `chanlun/engine_candidate_registry.py`，提供：

```python
CandidateDefinition
CANDIDATE_REGISTRY
get_candidate_definition(name)
list_candidate_definitions()
build_candidate_provider_bundle(name)
build_candidate_analyzer(name)
```

该 facade 复用：

```python
engine_experiments.EXPERIMENT_REGISTRY
engine_experiments.build_experiment_provider_bundle()
engine_pipeline.analyze_with_provider_bundle()
```

没有复制 legacy engine，也没有复制 provider 逻辑。

### 2. Candidate 名称支持

`CANDIDATE_REGISTRY` 支持 legacy alias：

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

同时支持 canonical experiment name：

```text
macd_v1
inclusion_v1
fractal_v1
stroke_v1
segment_v1
pivot_v1
trend_v1
divergence_v1
signal_v1
signal_p0_distance_guard
signal_p1_confirmation_guard
signal_p0_p1_guard
signal_delay1_by_type_guard
signal_delay1_by_type_guard_v2
all_v1
```

### 3. 保留兼容入口

`chanlun/engine_candidate.py` 中的 `candidate_provider_bundle()` 已改为薄 wrapper：

```python
def candidate_provider_bundle(candidate_name):
    from .engine_candidate_registry import build_candidate_provider_bundle

    return build_candidate_provider_bundle(candidate_name)
```

保留了现有：

```text
CANDIDATE_ANALYZERS
analyze_with_candidate_*()
analyze_with_all_candidate_components()
all_candidate_provider_bundle()
```

因此旧测试和旧调用面继续可用。

## 行为边界

本阶段没有修改：

```text
chanlun/chan_engine.py::analyze()
ChanResult contract
run.py production 调用路径
policy runner 回测口径
entry/exit/stop/take-profit 策略
```

`analyze()` 仍固定走 legacy provider bundle。candidate registry 仍是 opt-in 能力。

## 验证结果

局部测试：

```bash
python3 -m unittest tests.test_chan_engine_provider_registry tests.test_engine_experiments tests.test_chan_engine_dual_guardrails tests.test_chan_engine_import_compat
```

结果：

```text
Ran 32 tests in 0.016s
OK
```

编译检查：

```bash
python3 -m py_compile chanlun/engine_candidate_registry.py chanlun/engine_candidate.py chanlun/engine_experiments.py chanlun/chan_engine.py
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
Ran 487 tests in 4.482s
OK
```

## Review 结论

未发现阻断问题。

当前结构已经从：

```text
engine_candidate.py compatibility entry
```

收敛为：

```text
engine_candidate_registry.py explicit candidate facade
engine_candidate.py compatibility wrapper
engine_experiments.py provider experiment source
```

## 下一阶段

可以进入 Phase 7.2。

Phase 7.2 只做：

```text
analyze_dual(candidate="signal_v1")
```

并保留现有：

```text
analyze_dual(candidate_analyzer=...)
```

明确不做：

```text
不改 analyze()
不新增策略实验
不新增回测优化方向
不继续 Phase 6.14
```

