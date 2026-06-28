# ChanLun Engine Registry Usage Surface Convergence

## 背景

Phase 7 已完成：

```text
candidate registry facade
analyze_dual(candidate=...) registry name API
dual business_metrics hook
```

当前剩余不够收敛的地方在使用面：

```text
scripts/compare_chan_engine_dual.py
  --candidate 仍走 CANDIDATE_ANALYZERS legacy keys
  --experiment 仍走 engine_experiments provider bundle
```

这会让使用者看到两套入口：

```text
candidate alias
experiment name
```

而 Phase 7 后的目标入口应该是：

```text
candidate registry name
```

本批次只做使用面收敛，不新增策略。

## 新执行节奏

本批次采用更快流程：

```text
总 MD 落盘
小兵实现一个代码批次
主线程 review + 局部测试
组尾全量测试
结果 MD
统一提交 push
```

不再对每个小点做：

```text
方案 commit
代码 commit
结果 commit
```

除非触及 production 或数据口径风险。

## 目标

把 dual compare 脚本收敛到 candidate registry：

```bash
python3 scripts/compare_chan_engine_dual.py --candidate signal
python3 scripts/compare_chan_engine_dual.py --candidate signal_v1
python3 scripts/compare_chan_engine_dual.py --candidate signal_delay1_by_type_guard
```

旧入口保持兼容：

```bash
python3 scripts/compare_chan_engine_dual.py --experiment signal_v1
```

但内部应复用：

```python
analyze_dual(candidate=...)
engine_candidate_registry
```

而不是脚本自己拼 provider bundle。

## 边界纠偏

允许：

- 修改 dual compare 脚本入口，让 `--candidate` 支持 registry name。
- 保留 `--experiment` 作为兼容 alias。
- 更新脚本测试。
- 更新相关 import 和 summary 字段。

禁止：

- 不改 production `analyze()`。
- 不改 `run.py`。
- 不新增策略实验。
- 不新增回测 runner。
- 不访问真实行情。
- 不改 `policy_experiment_metrics.py`。
- 不改 Phase 6 文档。

一句话边界：

```text
本批次 = CLI/usage surface 收敛到 candidate registry，不是策略优化。
```

## 推荐实现

### 1. compare script 使用 registry

在 `scripts/compare_chan_engine_dual.py` 中：

```python
from chanlun.engine_candidate_registry import list_candidate_definitions
```

`--candidate` choices 改为：

```python
("legacy", *list_candidate_definitions())
```

`--experiment` 保留兼容，choices 可继续使用 existing experiment list，或收敛为 canonical candidate names。

内部逻辑建议：

```python
candidate_name = args.candidate
experiment_name = args.experiment

if candidate_name is None and experiment_name is None:
    candidate_name = "legacy"

dual_candidate = None
if experiment_name is not None:
    dual_candidate = experiment_name if experiment_name != "legacy" else None
    candidate_name = "legacy"
elif candidate_name != "legacy":
    dual_candidate = candidate_name

payload = analyze_dual(..., candidate=dual_candidate)
```

这样：

- `--candidate signal` 走 registry alias。
- `--candidate signal_v1` 走 canonical registry name。
- `--candidate signal_delay1_by_type_guard` 走 signal guard candidate。
- `--experiment signal_v1` 兼容旧测试，但内部也走 `analyze_dual(candidate="signal_v1")`。

### 2. 移除脚本重复 provider 拼装

如果不再需要，可以删除：

```python
_analyze_with_experiment_bundle()
build_experiment_provider_bundle
analyze_with_provider_bundle
CANDIDATE_ANALYZERS
```

但注意 `--candidate` choices 需要 registry，不再依赖 `CANDIDATE_ANALYZERS`。

### 3. summary 字段兼容

保持旧输出：

```text
summary["candidate"]
summary["experiment"]  # 仅 --experiment 时出现
summary["all_equal"]
summary["scenario_count"]
```

新增或修正可选字段：

```text
summary["candidate_registry_name"]
```

用于明确实际运行的 registry name。该字段可选，但建议加，方便审计。

## 测试要求

更新 `tests/test_chan_engine_experiment_script.py` 或新增脚本测试，覆盖：

### candidate legacy alias

```bash
scripts/compare_chan_engine_dual.py --candidate signal
```

应通过，summary candidate 为 `signal`。

### candidate canonical name

```bash
scripts/compare_chan_engine_dual.py --candidate signal_v1
```

应通过，summary candidate 为 `signal_v1`。

### candidate guard name

```bash
scripts/compare_chan_engine_dual.py --candidate signal_delay1_by_type_guard
```

应能运行。由于 guard 可能造成 diff，测试不要强制 `check=True`，但必须确认：

```text
output JSON 写出
summary.candidate == signal_delay1_by_type_guard
```

### experiment compatibility

```bash
scripts/compare_chan_engine_dual.py --experiment signal_v1
```

继续通过，summary experiment 为 `signal_v1`。

### business metrics compatibility

```bash
scripts/compare_chan_engine_dual.py --candidate signal_v1 --business-metrics
```

继续包含：

```text
structure_equal
recommendation_diff
return_metrics
coverage
```

### mutual exclusion

`--candidate` 和 `--experiment` 同时传仍由 argparse 拒绝。

## 局部验证

```bash
python3 -m unittest tests.test_chan_engine_experiment_script tests.test_chan_engine_dual_guardrails tests.test_chan_engine_provider_registry
python3 -m py_compile scripts/compare_chan_engine_dual.py chanlun/chan_engine.py chanlun/engine_candidate_registry.py
git diff --check
```

## 组尾验证

```bash
python3 -m unittest discover -s tests
```

## 完成文档

组尾补：

```text
docs/plans/2026-06-28-chanlun-engine-registry-usage-surface-convergence-result.md
```

结果文档包含：

- 实际修改文件。
- CLI 支持的 candidate registry name。
- 兼容性说明。
- 测试结果。
- 是否还有下一步。

## 统一提交策略

本批次完成后统一提交：

```bash
git add -f docs/plans/2026-06-28-chanlun-engine-registry-usage-surface-convergence.md
git add scripts/compare_chan_engine_dual.py tests/test_chan_engine_experiment_script.py
git add -f docs/plans/2026-06-28-chanlun-engine-registry-usage-surface-convergence-result.md
git commit -m "refactor: 收敛dual脚本候选注册入口"
git push origin main
```

