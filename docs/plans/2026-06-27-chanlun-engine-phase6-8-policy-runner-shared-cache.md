# ChanLun Engine Phase 6.8 Policy Runner Shared Cache

## 背景

Phase 6.6 和 Phase 6.7 的真实回测都暴露了同一个问题：

```text
run_policy_experiment_metrics(policy_names)
```

当前会对每个 policy 独立执行一次完整扫描：

```text
policy A -> scan snapshots -> fetch/normalize kline -> evaluate baseline -> evaluate policy
policy B -> scan snapshots -> fetch/normalize kline -> evaluate baseline -> evaluate policy
...
```

这导致：

- 多 policy 回测耗时随 policy 数线性增长。
- 相同股票日线会被重复取数。
- 远端失败和 `[CACHE FALLBACK]` 日志被重复放大。
- Phase 6.7 只有 7 个 policy，但真实回测已经明显偏慢。

Phase 6.8 只做性能与可验证性优化，不改变策略逻辑。

## 目标

把多 policy 回测改成共享基础样本：

```text
scan snapshots once
fetch/normalize kline once per code
evaluate v1 baseline once per eligible pick
then apply each policy on shared evaluated samples
```

要求：

- 回测结果与当前实现一致。
- `policy_filtered`、`policy_filtered_by_reason`、`policy_filtered_detail_by_reason` 语义不变。
- `baseline_summary` 对所有 policy 仍然一致。
- 不改 production `analyze()`。

## 非目标

- 不新增策略规则。
- 不改变 `bottom_quality_guard` / reason-level policy 行为。
- 不改变历史收益评价函数。
- 不处理远端数据源稳定性，只减少重复调用。
- 不改变输出 JSON/Markdown 字段，除非新增非破坏性性能统计字段。

## 当前问题点

当前 `chanlun/policy_experiment_metrics.py` 里：

```python
return {
    "policies": [_run_one_policy(name, rows) for name in names],
    ...
}
```

`_run_one_policy()` 内部每次都创建：

```python
kline_cache = {}
baseline_samples = []
policy_samples = []
```

因此每个 policy 都会重复：

- fetch kline
- normalize kline
- v1 baseline filter
- baseline return sample evaluate

这在 policy 数增多时会非常慢。

## 设计方案

### Step 1: 新增 shared evaluated rows

新增内部结构，建议字段：

```python
{
    "snap_date": str,
    "version": str,
    "pick": dict,
    "baseline_sample": dict,
}
```

构建函数建议：

```python
def _build_baseline_evaluated_rows(rows):
    ...
```

负责：

- 统计 `picks_seen`
- 统计 `baseline_filtered`
- 共享 `kline_cache`
- normalize kline
- 执行 `should_drop_pick_for_experiment(_BASELINE_EXPERIMENT, pick)`
- 执行 baseline `_evaluate_pick_sample(...)`
- 返回：

```python
{
    "evaluated_rows": [...],
    "baseline_samples": [...],
    "coverage_base": {...},
}
```

### Step 2: policy 只消费 evaluated rows

把 `_run_one_policy(name, rows)` 改成：

```python
def _run_one_policy(name, evaluated_context):
    ...
```

每个 policy 只遍历已经有 `baseline_sample` 的 rows。

注意：

- cooldown 仍然需要按 snapshot 日期顺序维护独立 state。
- 每个 policy 的 cooldown state 不能共享。
- `policy_evaluated` 只统计该 policy 保留的样本。
- `baseline_summary` 使用 shared `baseline_samples`。

### Step 3: 输出保持兼容

每个 policy 仍输出：

```python
{
    "coverage": {
        "snapshot_days": ...,
        "picks_seen": ...,
        "baseline_evaluated": ...,
        "policy_evaluated": ...,
        "baseline_filtered": ...,
        "policy_filtered": ...,
        "policy_filtered_by_reason": ...,
        "policy_filtered_detail_by_reason": ...,
        "retained_ratio_pct": ...,
    },
    "baseline_summary": ...,
    "policy_summary": ...,
    "delta": ...
}
```

允许新增非破坏性字段：

```python
"execution": {
    "shared_baseline": True,
    "evaluated_rows": ...
}
```

但测试不能依赖 wall-clock 时间作为唯一证据。

## 验证策略

### 1. Golden parity 测试

在单元测试里用 mock 数据证明：

- 新实现对 `delay1_v1`
- `delay1_v1_bottom_quality_guard`
- `delay1_v1_bottom_distance_gt6_guard`
- `delay1_v1_bottom_missing_shape_guard`
- `delay1_v1_cooldown3`

输出和旧算法预期一致。

如果保留旧 helper 不方便，可以用现有 fixture 明确断言核心字段。

### 2. fetch 去重测试

新增测试证明：

同一批 rows 跑多个 policy 时：

```text
_fetch_daily_kline_cached
```

对同一 code 不会按 policy 重复调用。

示例断言：

```python
fetch_mock.call_count == unique_code_count
```

### 3. 真实回测结果一致

复跑 Phase 6.7 命令：

```bash
python3 scripts/run_policy_experiments.py \
  --policies delay1_v1,delay1_v1_bottom_quality_guard,delay1_v1_bottom_missing_key_guard,delay1_v1_bottom_missing_distance_guard,delay1_v1_bottom_invalid_distance_guard,delay1_v1_bottom_distance_gt6_guard,delay1_v1_bottom_missing_shape_guard \
  --output-json /tmp/phase6_8_policy_shared_cache_metrics.json \
  --output-md /tmp/phase6_8_policy_shared_cache_metrics.md
```

关键指标必须与 Phase 6.7 一致：

- baseline n `1287`
- baseline filtered `805`
- `delay1_v1_bottom_quality_guard`: n `1101`, filtered `186`, T+3 `0.16`
- `delay1_v1_bottom_distance_gt6_guard`: n `1242`, filtered `45`, T+3 `0.07`
- `delay1_v1_bottom_missing_shape_guard`: n `1129`, filtered `158`, T+3 `0.12`

### 4. 速度证据

不要求用测试断言耗时，但结果文档要记录：

- Phase 6.8 命令耗时。
- 和 Phase 6.7 观察到的慢速行为做定性比较。
- 日线 fallback 日志是否明显减少。

## 验证命令

```bash
python3 -m unittest tests.test_policy_experiment_metrics tests.test_policy_experiment_runner_script
python3 -m unittest tests.test_policy_experiment_metrics tests.test_policy_experiment_runner_script tests.test_historical_experiment_metrics tests.test_engine_experiment_runner_script
python3 -m unittest discover -s tests
python3 -m py_compile chanlun/policy_experiment_metrics.py scripts/run_policy_experiments.py
git diff --check
```

## 结果文档

落地完成后生成：

```text
docs/plans/2026-06-27-chanlun-engine-phase6-8-policy-runner-shared-cache-result.md
```

结果文档必须包含：

- 改动摘要。
- 测试命令和结果。
- Phase 6.8 真实回测命令。
- 与 Phase 6.7 关键指标一致性对照。
- 是否仍有数据源 fallback。
- 下一阶段建议。

## 晋级判断

Phase 6.8 不是策略晋级阶段。

只有满足以下条件才算完成：

- 多 policy 共享基础样本和 kline cache。
- 单元测试证明 fetch 不再按 policy 重复。
- 全量测试通过。
- Phase 6.7 关键回测指标保持一致。
- 代码已提交并 push。
