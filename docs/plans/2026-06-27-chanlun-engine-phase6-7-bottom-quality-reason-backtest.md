# ChanLun Engine Phase 6.7 Bottom Quality Reason Backtest

## 背景

Phase 6.6 的回测结论是：

- `delay1_v1_bottom_quality_guard` 是当前唯一有继续研究价值的方向。
- 它把 T+3 均值从 `0.03` 提升到 `0.16`，胜率从 `44.5%` 提升到 `45.9%`。
- 但它没有降低尾部风险，`T+3 <= -5%` 和 `big_drop_5pct_rate` 都变差。
- `cooldown3` / `cooldown5` 当前定义不成立，暂时不继续扩大。

因此 Phase 6.7 不再增加 cooldown，而是拆解 `bottom_quality_guard` 的内部原因，判断到底是哪条底背驰质量规则有用。

## 目标

把复合规则：

```text
bottom_quality_guard
```

拆成可独立回测的 reason-level policy：

```text
missing_key_protection
missing_distance
invalid_distance
distance_gt_6
missing_bottom_shape_or_stop_drop
```

每条规则单独跑一遍，与 `signal_delay1_by_type_guard` v1 baseline 对比。

## 非目标

- 不改 production `analyze()`。
- 不改 legacy provider。
- 不把任何新 policy 接入线上信号。
- 不继续扩展 cooldown。
- 不做收益曲线可视化，先只做指标和样本拆解。

## 设计原则

### 1. 只在实验层拆分

改动集中在：

- `chanlun/policy_experiment_metrics.py`
- `scripts/run_policy_experiments.py`
- 对应 tests

### 2. 保持 v1 baseline 不变

所有新 policy 仍然以：

```python
_BASELINE_EXPERIMENT = "signal_delay1_by_type_guard"
```

作为对照。

baseline 只统计 v1 真正保留的样本。

### 3. 单 reason 独立过滤

新增 policy 只过滤对应 reason 命中的底背驰候选。

建议 policy 名：

```text
delay1_v1_bottom_missing_key_guard
delay1_v1_bottom_missing_distance_guard
delay1_v1_bottom_invalid_distance_guard
delay1_v1_bottom_distance_gt6_guard
delay1_v1_bottom_missing_shape_guard
```

保留现有复合 policy：

```text
delay1_v1_bottom_quality_guard
```

用于和单 reason 结果对照。

## 规则定义

### missing_key_protection

底背驰候选缺少：

```text
关键位不破
```

### missing_distance

底背驰候选没有：

```text
distance_from_reference_pct
```

### invalid_distance

底背驰候选存在 `distance_from_reference_pct`，但无法转成数值。

### distance_gt_6

底背驰候选：

```text
distance_from_reference_pct > 6
```

### missing_bottom_shape_or_stop_drop

底背驰候选同时缺少：

```text
30min底分型
止跌结构
```

## 实施步骤

### Step 1: reason helper

新增 helper：

```python
def bottom_quality_guard_reasons(pick: Optional[dict]) -> List[str]:
    ...
```

要求：

- 非底背驰候选返回 `[]`。
- 一个样本可以返回多个 reason。
- 复合 `bottom_quality_guard` 使用 `bool(reasons)`。

### Step 2: 注册 reason-level policies

扩展 `POLICY_EXPERIMENTS`：

```python
"delay1_v1_bottom_missing_key_guard": {
    "cooldown_days": None,
    "bottom_quality_reasons": {"missing_key_protection"},
},
...
```

原来的：

```python
"bottom_quality_guard": True
```

可以保留，也可以迁移成：

```python
"bottom_quality_reasons": "all"
```

但必须保证现有 policy 名和行为不变。

### Step 3: filter reason 输出

`should_filter_for_policy()` 返回更细 reason：

```text
bottom_missing_key_protection
bottom_missing_distance
bottom_invalid_distance
bottom_distance_gt_6
bottom_missing_shape_or_stop_drop
```

复合 policy 可以返回第一个命中的细 reason，也可以在 coverage 里增加 reason counter。优先选择“覆盖信息更强、旧表兼容”的实现。

### Step 4: runner 复用现有输出

`scripts/run_policy_experiments.py` 不需要大改，只要：

- 支持新 policy 名。
- Markdown 表里的 `Filtered By Reason` 能显示细 reason。
- JSON 输出保留完整 `policy_filtered_by_reason`。

### Step 5: 测试

新增或扩展：

- `tests/test_policy_experiment_metrics.py`
- `tests/test_policy_experiment_runner_script.py`

必须覆盖：

- 每个 reason helper 的判断。
- 单 reason policy 只过滤对应 reason。
- 复合 policy 与旧行为一致。
- baseline 仍然排除 v1 过滤样本。
- unknown policy 仍然失败。

## 回测命令

```bash
python3 scripts/run_policy_experiments.py \
  --policies delay1_v1,delay1_v1_bottom_quality_guard,delay1_v1_bottom_missing_key_guard,delay1_v1_bottom_missing_distance_guard,delay1_v1_bottom_invalid_distance_guard,delay1_v1_bottom_distance_gt6_guard,delay1_v1_bottom_missing_shape_guard \
  --output-json /tmp/phase6_7_bottom_quality_reason_metrics.json \
  --output-md /tmp/phase6_7_bottom_quality_reason_metrics.md
```

## 验证命令

```bash
python3 -m unittest tests.test_policy_experiment_metrics tests.test_policy_experiment_runner_script
python3 -m unittest tests.test_policy_experiment_metrics tests.test_policy_experiment_runner_script tests.test_historical_experiment_metrics tests.test_engine_experiment_runner_script
python3 -m unittest discover -s tests
python3 -m py_compile chanlun/policy_experiment_metrics.py scripts/run_policy_experiments.py
git diff --check
```

## 晋级判断

单 reason policy 只有同时满足以下条件，才进入下一阶段组合测试：

- T+3 均值提升为正。
- T+3 胜率提升为正。
- `T+3 <= -5%` 不恶化，或恶化幅度小于 `0.3`。
- `big_drop_5pct_rate` 不恶化，或恶化幅度小于 `0.3`。
- 保留率不低于 `80%`，除非收益提升非常显著。

## 预期输出

落地完成后生成：

```text
docs/plans/2026-06-27-chanlun-engine-phase6-7-bottom-quality-reason-backtest-result.md
```

结果文档必须包含：

- 测试命令和结果。
- 真实回测命令。
- policy 对比表。
- 每个 reason 的结论：保留 / 放弃 / 需要组合验证。
- 下一阶段建议。
