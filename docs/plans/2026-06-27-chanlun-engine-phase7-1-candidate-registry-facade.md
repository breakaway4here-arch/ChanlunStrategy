# ChanLun Engine Phase 7.1 Candidate Registry Facade

## 背景

Phase 6 已关闭为回测评估层。后续不再继续扩散 entry/exit/stop/take-profit 小实验，本阶段回到原始目标：

```text
candidate = 插件系统，不是第二套缠论
```

Phase 7.1 只做一个实际架构收拢点：给 candidate 增加明确的 registry facade，让后续 `analyze_dual(candidate=...)` 和 A/B 对比有稳定入口。

## 当前基础

现有代码已经有可复用基础：

- `chanlun/engine_pipeline.py`
  - `EngineProviders`
  - `LEGACY_PROVIDERS`
  - `with_provider_overrides()`
  - `analyze_with_provider_bundle()`

- `chanlun/engine_experiments.py`
  - `ExperimentDefinition`
  - `EXPERIMENT_REGISTRY`
  - `get_experiment()`
  - `list_experiments()`
  - `build_experiment_provider_bundle()`

- `chanlun/engine_candidate.py`
  - legacy candidate analyzer functions
  - `candidate_provider_bundle()`
  - `all_candidate_provider_bundle()`
  - `CANDIDATE_ANALYZERS`

问题是：candidate 的对外入口仍散在 legacy compatibility 文件里，没有一个清晰的 `CANDIDATE_REGISTRY`。

## 本阶段目标

新增：

```text
chanlun/engine_candidate_registry.py
```

暴露：

```python
CandidateDefinition
CANDIDATE_REGISTRY
get_candidate_definition(name)
list_candidate_definitions()
build_candidate_provider_bundle(name)
build_candidate_analyzer(name)
```

核心约束：

- 不修改 `analyze()` 行为。
- 不改 `ChanResult` contract。
- 不复制 legacy engine。
- 不复制 provider 逻辑。
- 不新增交易策略。
- 不新增回测口径。
- `engine_candidate.py` 只保留兼容入口，并委托 registry。

## 设计

### CandidateDefinition

建议结构：

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class CandidateDefinition:
    name: str
    module: str
    experiment: str
    description: str = ""
    risk: str = "low"
    alias_of: str | None = None
```

注意项目当前需要兼容 Python 3.9/3.10 时，不要使用运行环境不支持的类型语法；如有风险，使用 `Optional[str]`。

### Registry 内容

`CANDIDATE_REGISTRY` 应包含两类名字：

1. legacy alias，保持旧调用可用：

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

2. canonical experiment name，来自 `EXPERIMENT_REGISTRY` 的非 `legacy` 项：

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

legacy alias 应映射到 canonical experiment：

```python
_LEGACY_ALIASES = {
    "macd": "macd_v1",
    "inclusion": "inclusion_v1",
    "fractal": "fractal_v1",
    "stroke": "stroke_v1",
    "segment": "segment_v1",
    "pivot": "pivot_v1",
    "trend": "trend_v1",
    "divergence": "divergence_v1",
    "signal": "signal_v1",
    "all": "all_v1",
}
```

### Provider Bundle

`build_candidate_provider_bundle(name)` 只做：

1. 查 `CandidateDefinition`。
2. 取 `definition.experiment`。
3. 调 `build_experiment_provider_bundle(experiment)`。

未知 candidate 抛出明确错误：

```python
raise ValueError(f"unknown candidate: {name}")
```

### Analyzer Builder

`build_candidate_analyzer(name)` 返回 callable，用同一个 provider bundle 跑 candidate pipeline。

建议实现：

```python
def build_candidate_analyzer(candidate_name):
    providers = build_candidate_provider_bundle(candidate_name)

    def analyze_candidate(code, name, dates, highs, lows, closes, volumes=None, amounts=None):
        return analyze_with_provider_bundle(
            code,
            name,
            dates,
            highs,
            lows,
            closes,
            volumes=volumes,
            amounts=amounts,
            providers=providers,
        )

    analyze_candidate.__name__ = f"analyze_with_candidate_{candidate_name}"
    return analyze_candidate
```

这里不应导入 `engine_candidate.py` 中的具体 analyzer，避免 registry 与 compatibility 文件互相强依赖。

### engine_candidate.py 兼容改造

`engine_candidate.candidate_provider_bundle()` 改为薄 wrapper：

```python
def candidate_provider_bundle(candidate_name):
    from .engine_candidate_registry import build_candidate_provider_bundle

    return build_candidate_provider_bundle(candidate_name)
```

保留：

- `CANDIDATE_ANALYZERS`
- `analyze_with_candidate_signal()`
- `analyze_with_candidate_pivot()`
- 其他现有 legacy analyzer function

本阶段不要删除这些 API，避免破坏旧测试和外部调用。

## 测试要求

新增或补充 `tests/test_chan_engine_provider_registry.py`：

### Registry 基础

- `CANDIDATE_REGISTRY` 包含 legacy alias：
  - `signal`
  - `pivot`
  - `all`
- `CANDIDATE_REGISTRY` 包含 canonical candidate：
  - `signal_v1`
  - `signal_delay1_by_type_guard`
  - `all_v1`
- `get_candidate_definition("signal").experiment == "signal_v1"`
- `get_candidate_definition("signal_v1").module == "signal"`
- `get_candidate_definition("unknown")` 抛 `ValueError`。

### Provider Bundle 行为

- `build_candidate_provider_bundle("signal")` 只 override `signal_provider`。
- `build_candidate_provider_bundle("signal_delay1_by_type_guard")` 只 override `signal_provider`。
- `build_candidate_provider_bundle("all")` 复用 `all_v1`，不是复制 full engine。
- `engine_candidate.candidate_provider_bundle("signal")` 与 registry 行为一致。

### Analyzer Builder

- `build_candidate_analyzer("signal")` 返回 callable。
- callable 在最小 K 线样本上返回 `ChanResult`。
- `build_candidate_analyzer("unknown")` 抛 `ValueError`。

## 不做事项

本阶段明确不做：

- 不改 `chanlun/chan_engine.py` 的 `analyze()`。
- 不新增 `analyze_dual(candidate=...)`，这是 Phase 7.2。
- 不新增回测策略。
- 不新增 Phase 6.14。
- 不改 policy runner 的收益计算。
- 不删除 legacy candidate analyzer API。

## 验证命令

先跑局部：

```bash
python3 -m unittest tests.test_chan_engine_provider_registry tests.test_engine_experiments tests.test_chan_engine_dual_guardrails tests.test_chan_engine_import_compat
python3 -m py_compile chanlun/engine_candidate_registry.py chanlun/engine_candidate.py chanlun/engine_experiments.py chanlun/chan_engine.py
git diff --check
```

再跑全量：

```bash
python3 -m unittest discover -s tests
```

验收标准：

- 局部测试全绿。
- 全量测试全绿。
- `git diff --check` 无输出。
- `git status --short` 中不应包含无关业务改动。

## 完成文档

代码完成并验证后，补充结果文档：

```text
docs/plans/2026-06-27-chanlun-engine-phase7-1-candidate-registry-facade-result.md
```

结果文档必须包含：

- 实际修改文件。
- registry 支持的 candidate 名称。
- 测试命令和结果。
- 是否有行为变更。
- 下一阶段 Phase 7.2 是否可以继续。

## Commit Strategy

方案文档：

```bash
git add -f docs/plans/2026-06-27-chanlun-engine-phase7-1-candidate-registry-facade.md
git commit -m "docs: 添加候选注册门面实施方案"
git push origin main
```

代码：

```bash
git add chanlun/engine_candidate_registry.py chanlun/engine_candidate.py tests/test_chan_engine_provider_registry.py
git commit -m "feat: 添加候选注册门面"
git push origin main
```

结果文档：

```bash
git add -f docs/plans/2026-06-27-chanlun-engine-phase7-1-candidate-registry-facade-result.md
git commit -m "docs: 添加候选注册门面结果"
git push origin main
```

