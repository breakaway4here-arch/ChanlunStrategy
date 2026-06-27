# ChanLun Engine Phase 7.2 Analyze Dual Candidate API

## 背景

Phase 7.1 已完成 candidate registry facade：

```text
chanlun/engine_candidate_registry.py
```

当前已有能力：

- `CANDIDATE_REGISTRY`
- `get_candidate_definition(name)`
- `list_candidate_definitions()`
- `build_candidate_provider_bundle(name)`
- `build_candidate_analyzer(name)`

Phase 7.2 只做一件事：让 `analyze_dual()` 可以直接使用 candidate registry name。

## 方向纠偏

本阶段必须向实际插件架构收拢，不再扩散。

允许的短暂修复：

- 为了让 `analyze_dual(candidate=...)` 正常运行而补测试或修兼容小问题。
- 为了避免旧 API 破坏而增加 guardrail。

不允许的偏离：

- 不新增 entry/exit/stop/take-profit 策略。
- 不新增回测优化。
- 不继续 Phase 6.14。
- 不修改 production `analyze()` 逻辑。
- 不修改 `ChanResult` contract。
- 不把 `run.py` 接到 candidate 或 dual 路径。
- 不把本阶段扩大成业务指标系统；那是 Phase 7.3。

一句话边界：

```text
Phase 7.2 = analyze_dual 识别 candidate registry name，不是新策略实验。
```

## 当前问题

当前 `analyze_dual()` 只支持：

```python
analyze_dual(..., candidate_analyzer=callable)
```

这对测试可用，但对候选插件系统不够直接。调用方必须先知道具体 analyzer function，而不是使用 registry name。

目标调用方式应该是：

```python
analyze_dual(..., candidate="signal_v1")
analyze_dual(..., candidate="signal")
analyze_dual(..., candidate="signal_delay1_by_type_guard")
```

## 本阶段目标

修改：

```text
chanlun/chan_engine.py
```

补充测试：

```text
tests/test_chan_engine_dual_guardrails.py
tests/test_chan_engine_provider_registry.py
```

必要时可新增测试文件，但优先复用现有 dual/provider registry 测试。

## API 设计

### 保留旧 API

旧调用继续可用：

```python
analyze_dual(
    code,
    name,
    dates,
    opens,
    highs,
    lows,
    closes,
    volumes,
    candidate_analyzer=analyze_with_candidate_signal,
)
```

### 新增 candidate name API

新增 keyword-only 参数：

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
):
    ...
```

新调用：

```python
analyze_dual(..., candidate="signal_v1")
```

### 默认行为不变

不传 candidate 时：

```python
analyze_dual(...)
```

仍然等价于：

```text
legacy analyze() vs legacy analyze()
```

### 参数互斥

不能同时传：

```python
analyze_dual(..., candidate="signal", candidate_analyzer=callable)
```

应明确报错：

```python
ValueError("candidate and candidate_analyzer are mutually exclusive")
```

### unknown candidate

未知 candidate name 应透出明确错误：

```python
ValueError("unknown candidate: xxx")
```

错误来源可以来自 `engine_candidate_registry.get_candidate_definition()` 或 `build_candidate_analyzer()`。

## 推荐实现

在 `chanlun/chan_engine.py` 中按需导入 registry builder，避免 production analyze 路径加载额外 candidate 逻辑：

```python
if candidate is not None and candidate_analyzer is not None:
    raise ValueError("candidate and candidate_analyzer are mutually exclusive")

if candidate is not None:
    from .engine_candidate_registry import build_candidate_analyzer

    analyzer = build_candidate_analyzer(candidate)
else:
    analyzer = candidate_analyzer or analyze
```

保持：

```python
legacy = analyze(**kwargs)
candidate_result = analyzer(**kwargs)
comparison = compare_chan_results(legacy, candidate_result)
```

## 测试要求

### 1. 默认行为

`analyze_dual()` 不传参数时仍 legacy vs legacy：

```text
comparison["equal"] is True
```

### 2. 旧 API 兼容

`candidate_analyzer=...` 仍可用。

### 3. 新 API 支持 legacy alias

```python
analyze_dual(..., candidate="signal")
```

能返回：

```text
legacy
candidate
comparison
```

### 4. 新 API 支持 canonical name

```python
analyze_dual(..., candidate="signal_v1")
analyze_dual(..., candidate="signal_delay1_by_type_guard")
```

均能运行。

### 5. 参数互斥

```python
analyze_dual(..., candidate="signal", candidate_analyzer=analyze)
```

应抛 `ValueError`。

### 6. unknown candidate

```python
analyze_dual(..., candidate="missing")
```

应抛 `ValueError`。

### 7. production analyze 不变

继续保留现有断言：

```text
analyze() uses LEGACY_PROVIDERS
run.py does not call analyze_dual()
```

如果当前测试里已有类似 guardrail，补强即可，不重复造大测试。

## 验证命令

局部验证：

```bash
python3 -m unittest tests.test_chan_engine_dual_guardrails tests.test_chan_engine_provider_registry tests.test_engine_experiments tests.test_chan_engine_import_compat
python3 -m py_compile chanlun/chan_engine.py chanlun/engine_candidate_registry.py chanlun/engine_candidate.py
git diff --check
```

全量验证：

```bash
python3 -m unittest discover -s tests
```

验收标准：

- 局部测试全绿。
- 全量测试全绿。
- `git diff --check` 无输出。
- `git status --short` 只允许本阶段相关文件和既有 `.codegraph/` 未跟踪目录。

## 小兵执行边界

小兵只允许做：

```text
chanlun/chan_engine.py
tests/test_chan_engine_dual_guardrails.py
tests/test_chan_engine_provider_registry.py
```

如确需新增测试文件，必须在最终说明中解释原因。

小兵禁止做：

```text
修改 run.py
修改 policy_experiment_metrics.py
修改任何 backtest runner
新增策略实验
新增 Phase 6 文档
删除旧 candidate_analyzer API
```

## 完成文档

代码完成并验证后，补充：

```text
docs/plans/2026-06-27-chanlun-engine-phase7-2-analyze-dual-candidate-api-result.md
```

结果文档必须包含：

- 实际修改文件。
- 新旧 API 行为说明。
- 测试命令和结果。
- 是否修改 production `analyze()`。
- 是否可以进入 Phase 7.3。

## Commit Strategy

方案文档：

```bash
git add -f docs/plans/2026-06-27-chanlun-engine-phase7-2-analyze-dual-candidate-api.md
git commit -m "docs: 添加dual候选API实施方案"
git push origin main
```

代码：

```bash
git add chanlun/chan_engine.py tests/test_chan_engine_dual_guardrails.py tests/test_chan_engine_provider_registry.py
git commit -m "feat: 支持dual候选注册名"
git push origin main
```

结果文档：

```bash
git add -f docs/plans/2026-06-27-chanlun-engine-phase7-2-analyze-dual-candidate-api-result.md
git commit -m "docs: 添加dual候选API结果"
git push origin main
```

