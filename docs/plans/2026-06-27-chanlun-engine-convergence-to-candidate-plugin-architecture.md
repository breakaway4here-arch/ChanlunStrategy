# ChanLun Engine Convergence To Candidate Plugin Architecture

## 背景

用户指出：不要继续扩散做新一轮收益小实验，要把现有任务完善后，向最开始的实际方案收拢。

这份文档用于收敛当前工作流：

- Phase 6 系列到此关闭，定位为 `backtest-only experiment evaluation layer`。
- 后续不再继续添加新的 entry/exit/过滤小实验。
- 下一步进入 Phase 7，回到原始目标：candidate 插件架构。

## 原始目标

最开始的目标不是“不断调参回测”，而是：

```text
candidate = 插件系统，不是第二套缠论
```

核心规则：

- `analyze()` 永远保持 production legacy 行为。
- candidate 不能复制 full legacy engine。
- candidate 只能 override 单模块。
- candidate 必须 registry 化。
- `analyze_dual()` 只做 legacy/candidate 对比。
- 对比结果最终要服务业务指标，而不是只看结构 equal。

## 当前已完成的基础

当前代码已经具备一部分真实架构基础：

- `chanlun/engine_pipeline.py`
  - `EngineProviders`
  - `LEGACY_PROVIDERS`
  - `with_provider_overrides()`
  - `analyze_with_provider_bundle()`

- `chanlun/chan_engine.py`
  - `analyze()` 固定使用 `LEGACY_PROVIDERS`
  - `analyze_dual()` 是显式 opt-in，不影响 production

- `chanlun/engine_experiments.py`
  - 已有 `EXPERIMENT_REGISTRY`
  - 已有 `ExperimentDefinition`
  - 已有 `build_experiment_provider_bundle()`
  - 已有 signal guard 实验

- `chanlun/engine_candidate.py`
  - 已有单模块 candidate provider bundle
  - 已有 `candidate_provider_bundle()`
  - 已有 `all_candidate_provider_bundle()`
  - 但命名和职责仍偏 legacy compatibility，没有形成清晰的 `CANDIDATE_REGISTRY` 门面。

- `chanlun/policy_experiment_metrics.py`
  - Phase 6 系列新增了 backtest-only policy registry。
  - 这部分可以保留为评估层，但不应继续膨胀成主架构。

## 当前偏差

Phase 6 后半段开始偏向收益回测优化：

- execution model
- exit model
- stop/take-profit diagnostics

这些不是错，但已经偏离最初的架构目标。

因此后续停止继续扩散：

```text
不做 Phase 6.14 realized exit diagnostics
不再新增新的 policy 小实验
不再继续调入场/退出规则
```

## 收敛后的目标架构

目标架构应该是：

```text
analyze()
  -> LEGACY_PROVIDERS
  -> production ChanResult

CANDIDATE_REGISTRY
  signal_v1
  signal_delay1_by_type_guard
  pivot_v1
  segment_v1
  ...

build_candidate_provider_bundle(candidate_name)
  -> LEGACY_PROVIDERS + single module override

analyze_dual(candidate=...)
  -> legacy analyze()
  -> candidate provider bundle
  -> compare_chan_results()
  -> optional business metrics
```

## Phase 7 Scope

Phase 7 只做架构收拢，不做新策略优化。

### Phase 7.1 Candidate Registry 门面

目标：

- 新增明确的 `chanlun/engine_candidate_registry.py`。
- 暴露：
  - `CandidateDefinition`
  - `CANDIDATE_REGISTRY`
  - `get_candidate_definition(name)`
  - `list_candidate_definitions()`
  - `build_candidate_provider_bundle(name)`
  - `build_candidate_analyzer(name)`
- 复用现有 `engine_experiments.EXPERIMENT_REGISTRY` 和 `build_experiment_provider_bundle()`，不复制 provider 逻辑。
- 保留 `engine_candidate.candidate_provider_bundle()` 作为兼容 wrapper，但内部改为委托 registry。

验收：

- `analyze()` 不变。
- 单模块 candidate 仍只 override 一个 provider。
- `all` candidate 仍可用。
- unknown candidate 明确报错。
- 现有 candidate analyzer tests 继续通过。

### Phase 7.2 analyze_dual Candidate Name API

目标：

- 在不破坏现有 `candidate_analyzer` 参数的前提下，新增 candidate name 入口。
- 推荐 API：

```python
analyze_dual(..., candidate="signal_v1")
```

兼容：

```python
analyze_dual(..., candidate_analyzer=...)
```

约束：

- 如果同时传 `candidate` 和 `candidate_analyzer`，应明确拒绝。
- `analyze()` 不引入任何 candidate 参数。
- `run.py` 仍不得调用 `analyze_dual()`。

验收：

- `analyze_dual(candidate="signal")` 或兼容名能跑。
- `analyze_dual(candidate="signal_delay1_by_type_guard")` 能跑。
- `analyze_dual()` 默认仍等价 legacy vs legacy。

### Phase 7.3 Business Metrics 接入点

目标：

- 不再继续扩散 policy 小实验。
- 给 `analyze_dual()` 或 runner 增加可选 business metric summary 的结构位置。
- 只接入已有 Phase 6 backtest metrics，不新增新策略。

验收：

- dual compare report 可以区分：
  - structure diff
  - signal diff
  - backtest metric diff
- metric 缺失时不影响 structural compare。

## 立即下一步

下一步只做 Phase 7.1。

建议文件：

- Create: `chanlun/engine_candidate_registry.py`
- Modify: `chanlun/engine_candidate.py`
- Modify: `tests/test_chan_engine_provider_registry.py`
- Possibly Modify: `tests/test_engine_experiments.py`

明确不做：

- 不新增 entry/exit/stop/take-profit 策略。
- 不改 production `analyze()`。
- 不改回测结果口径。
- 不新增 Phase 6.14。

## 验证矩阵

Phase 7.1 完成后至少运行：

```bash
python3 -m unittest tests.test_chan_engine_provider_registry tests.test_engine_experiments tests.test_chan_engine_dual_guardrails tests.test_chan_engine_import_compat
python3 -m py_compile chanlun/engine_candidate_registry.py chanlun/engine_candidate.py chanlun/engine_experiments.py chanlun/chan_engine.py
git diff --check
python3 -m unittest discover -s tests
```

## Commit Strategy

先提交本文档：

```bash
git add -f docs/plans/2026-06-27-chanlun-engine-convergence-to-candidate-plugin-architecture.md
git commit -m "docs: 收拢候选插件架构方向"
git push origin main
```

然后按 Phase 7.1 新建具体实施 MD，再让小兵执行代码。
