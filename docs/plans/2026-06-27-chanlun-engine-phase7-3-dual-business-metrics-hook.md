# ChanLun Engine Phase 7.3 Dual Business Metrics Hook

## 背景

Phase 7 已完成两步架构收拢：

```text
Phase 7.1: candidate registry facade
Phase 7.2: analyze_dual(candidate=...) registry name API
```

当前主链路已经是：

```text
CANDIDATE_REGISTRY
  -> build_candidate_analyzer(candidate_name)
  -> analyze_dual(candidate=...)
  -> compare_chan_results()
```

Phase 7.3 只补最后一个结构位置：让 dual compare payload 可以携带可选 business metrics。

## 方向纠偏

本阶段必须继续向实际 candidate 插件架构收拢，不再扩散。

允许：

- 给 `analyze_dual()` 增加可选 business metrics hook。
- 复用已有 `chanlun.experiment_metrics.compare_recommendations()` 做推荐差异摘要。
- 在脚本层复用已有 `--business-metrics` 输出结构。
- metrics 缺失时保留 structural compare，不影响 dual compare。

禁止：

- 不新增 entry/exit/stop/take-profit 策略。
- 不新增 Phase 6.14。
- 不新增新的回测 runner。
- 不在 `analyze_dual()` 里拉真实行情。
- 不在 `analyze_dual()` 里计算 forward returns。
- 不修改 production `analyze()`。
- 不修改 `run.py` production 路径。
- 不修改 `ChanResult` contract。

一句话边界：

```text
Phase 7.3 = dual payload 的 business_metrics 接入点，不是收益优化。
```

## 当前问题

当前 `analyze_dual()` 返回：

```python
{
    "legacy": legacy,
    "candidate": candidate_result,
    "comparison": compare_chan_results(legacy, candidate_result),
}
```

结构 diff 已经清楚，但没有标准位置挂业务指标。

脚本 `scripts/compare_chan_engine_dual.py` 已有 `--business-metrics`，但 metrics 字段散在 report summary 中：

```text
structure_equal
recommendation_diff
return_metrics
coverage
```

Phase 7.3 的目标不是新增算法，而是统一结构接入点。

## 本阶段目标

新增一个可选 hook：

```python
analyze_dual(..., business_metrics=...)
```

当不传 `business_metrics` 时，返回结构完全保持：

```text
legacy
candidate
comparison
```

当传入时，返回增加：

```text
business_metrics
```

## API 设计

### analyze_dual 新参数

新增 keyword-only 参数：

```python
business_metrics=None
```

完整形态：

```python
def analyze_dual(
    code,
    name,
    dates,
    opens,
    highs,
    lows,
    closes,
    volumes,
    *,
    candidate=None,
    candidate_analyzer=None,
    business_metrics=None,
):
    ...
```

### business_metrics 支持 dict

如果传入 dict，直接挂载：

```python
payload = analyze_dual(..., business_metrics={"return_metrics": existing_metrics})
payload["business_metrics"] == {"return_metrics": existing_metrics}
```

### business_metrics 支持 callable

如果传入 callable，应在 legacy/candidate/comparison 都完成后调用：

```python
metrics = business_metrics(
    legacy=legacy,
    candidate=candidate_result,
    comparison=comparison,
)
```

然后挂载：

```python
payload["business_metrics"] = metrics
```

### callable 返回 None

如果 callable 返回 `None`，仍挂载一个明确状态：

```python
{
    "status": "not_provided"
}
```

这样 metrics 缺失不会影响 structural compare。

### callable 报错

本阶段建议不要吞异常。

原因：metrics hook 是显式 opt-in，调用方应看到 collector 失败。默认不传 hook 时，dual compare 不受影响。

## Helper 设计

新增轻量 helper，避免脚本各自拼字段：

```text
chanlun/engine_dual_metrics.py
```

建议提供：

```python
def result_to_recommendations(result):
    ...

def build_dual_business_metrics(
    legacy,
    candidate,
    comparison,
    *,
    return_metrics=None,
    coverage=None,
):
    ...
```

返回结构：

```python
{
    "structure": comparison["summary"],
    "recommendation_diff": compare_recommendations(...),
    "return_metrics": return_metrics or {
        "status": "not_provided",
        "legacy": None,
        "candidate": None,
    },
    "coverage": coverage or {
        "status": "not_provided",
    },
}
```

注意：

- `build_dual_business_metrics()` 不计算真实收益。
- `return_metrics` 只接收外部已有结果。
- `coverage` 只接收外部已有覆盖信息。
- 不访问网络。
- 不读取行情。

## 脚本收敛

`scripts/compare_chan_engine_dual.py` 当前有本地 `_to_recommendations()` 和 `_calculate_business_metrics()`。

本阶段可以把它收敛为：

```python
from chanlun.engine_dual_metrics import build_dual_business_metrics
```

当 `--business-metrics` 开启时：

```python
payload = analyze_dual(
    ...,
    candidate=...,
    business_metrics=lambda legacy, candidate, comparison: build_dual_business_metrics(
        legacy,
        candidate,
        comparison,
        return_metrics={
            "status": "no_market_data",
            "legacy": None,
            "candidate": None,
        },
        coverage={
            "evaluated": 0,
            "skipped_no_market_data": scenario_count,
            "reason": "SCENARIOS only; no market fetch",
        },
    ),
)
```

但需要注意：脚本当前是聚合所有 scenario 后再计算 recommendation diff。若直接按 scenario 调 hook，会改变输出口径。

因此 Phase 7.3 推荐最小实现：

1. core `analyze_dual()` 增加 hook 支持。
2. 新增 `engine_dual_metrics.py` helper。
3. 脚本保留聚合口径，但复用 helper 的 `result_to_recommendations()` 或新增 `build_aggregate_dual_business_metrics()`。

推荐 helper：

```python
def build_aggregate_dual_business_metrics(
    legacy_recommendations,
    candidate_recommendations,
    *,
    return_metrics=None,
    coverage=None,
):
    ...
```

这样脚本输出不变，只减少散落逻辑。

## 测试要求

### Core analyze_dual

补充 `tests/test_chan_engine_dual_guardrails.py`：

- 不传 `business_metrics` 时不包含 `business_metrics` key。
- 传 dict 时原样挂载。
- 传 callable 时收到 `legacy`、`candidate`、`comparison`，并挂载返回值。
- callable 返回 None 时挂载 `{"status": "not_provided"}`。
- 默认 structural compare 不受 metrics 缺失影响。

### Helper

新增或补充测试：

```text
tests/test_engine_dual_metrics.py
```

覆盖：

- `result_to_recommendations(None) == []`
- `result_to_recommendations(result)` 只提取 dict buy_points。
- `build_aggregate_dual_business_metrics()` 包含：
  - `structure`
  - `recommendation_diff`
  - `return_metrics`
  - `coverage`
- 未传 return_metrics/coverage 时返回 `not_provided`。

### Script

补充 `tests/test_chan_engine_experiment_script.py` 或现有脚本测试：

- `--business-metrics` 输出 key 不变：
  - `structure_equal`
  - `recommendation_diff`
  - `return_metrics`
  - `coverage`
- 不要求真实收益。
- 不访问真实行情。

## 小兵执行边界

允许写入：

```text
chanlun/chan_engine.py
chanlun/engine_dual_metrics.py
scripts/compare_chan_engine_dual.py
tests/test_chan_engine_dual_guardrails.py
tests/test_engine_dual_metrics.py
tests/test_chan_engine_experiment_script.py
```

禁止写入：

```text
run.py
chanlun/policy_experiment_metrics.py
chanlun/backtest_execution.py
chanlun/backtest_metrics.py
scripts/run_policy_experiments.py
任何 Phase 6 文档
任何新增策略或回测 runner
```

## 验证命令

局部验证：

```bash
python3 -m unittest tests.test_chan_engine_dual_guardrails tests.test_engine_dual_metrics tests.test_chan_engine_experiment_script tests.test_chan_engine_provider_registry
python3 -m py_compile chanlun/chan_engine.py chanlun/engine_dual_metrics.py scripts/compare_chan_engine_dual.py
git diff --check
```

全量验证：

```bash
python3 -m unittest discover -s tests
```

验收标准：

- 局部测试全绿。
- 全量测试全绿。
- `--business-metrics` 旧输出 key 不破坏。
- `analyze_dual()` 默认返回不新增 `business_metrics`。
- 不访问网络。
- 不改 production `analyze()`。

## 完成文档

代码完成并验证后，补充：

```text
docs/plans/2026-06-27-chanlun-engine-phase7-3-dual-business-metrics-hook-result.md
```

结果文档必须包含：

- 实际修改文件。
- hook 行为说明。
- 脚本输出兼容性说明。
- 测试命令和结果。
- 是否修改 production `analyze()`。
- 是否可以进入 Phase 7.4 或收尾。

## Commit Strategy

方案文档：

```bash
git add -f docs/plans/2026-06-27-chanlun-engine-phase7-3-dual-business-metrics-hook.md
git commit -m "docs: 添加dual业务指标hook方案"
git push origin main
```

代码：

```bash
git add chanlun/chan_engine.py chanlun/engine_dual_metrics.py scripts/compare_chan_engine_dual.py tests/test_chan_engine_dual_guardrails.py tests/test_engine_dual_metrics.py tests/test_chan_engine_experiment_script.py
git commit -m "feat: 添加dual业务指标hook"
git push origin main
```

结果文档：

```bash
git add -f docs/plans/2026-06-27-chanlun-engine-phase7-3-dual-business-metrics-hook-result.md
git commit -m "docs: 添加dual业务指标hook结果"
git push origin main
```

