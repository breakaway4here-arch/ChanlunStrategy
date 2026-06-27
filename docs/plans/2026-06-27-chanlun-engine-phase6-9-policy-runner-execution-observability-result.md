# ChanLun Engine Phase 6.9 Policy Runner Execution Observability Result

## 结论

Phase 6.9 已完成并通过验证。

这一步不改变策略收益逻辑，只给 policy backtest 增加执行观测指标。后续看策略优化结果时，可以同时看到样本规模、K 线 fetch 去重、缓存复用、缺失 K 线和无效 K 线情况，避免把数据源噪音误判成策略效果。

## 改动摘要

修改文件：

- `chanlun/policy_experiment_metrics.py`
- `scripts/run_policy_experiments.py`
- `tests/test_policy_experiment_metrics.py`
- `tests/test_policy_experiment_runner_script.py`

核心变化：

- `run_policy_experiment_metrics()` 新增 top-level `execution`。
- `execution` 包含：
  - `shared_baseline`
  - `snapshot_rows`
  - `unique_codes`
  - `fetch_attempts`
  - `cache_hits`
  - `kline_missing`
  - `kline_invalid`
  - `baseline_rows`
- 保留原 top-level `snapshot_rows`，兼容既有消费者。
- Markdown 输出在存在 `execution` 时新增 `Execution Summary`。
- 单元测试覆盖：
  - 多 policy 共享缓存计数。
  - missing/invalid K 线计数。
  - runner Markdown execution summary。

## 主进程 Review 修正

小兵实现后，主进程 review 额外修了一处细节：

```python
if not normalized_kline:
    kline_invalid += 1
    continue
```

原因：计划要求 `_normalize_kline()` 返回 falsey 时都算 invalid。当前实现主要返回 `None`，但用 falsey 判断更贴合观测字段语义，也避免未来返回 `{}` 时漏计。

对应测试已把 invalid mock 改成 `{}`，确保覆盖真实语义。

## 验证命令

### 1. Policy runner 定向测试

```bash
python3 -m unittest tests.test_policy_experiment_metrics tests.test_policy_experiment_runner_script
```

结果：

```text
Ran 18 tests in 0.011s

OK
```

### 2. 回测相关扩展测试

```bash
python3 -m unittest tests.test_policy_experiment_metrics tests.test_policy_experiment_runner_script tests.test_historical_experiment_metrics tests.test_engine_experiment_runner_script
```

结果：

```text
Ran 35 tests in 1.451s

OK
```

### 3. 全量测试

```bash
python3 -m unittest discover -s tests
```

结果：

```text
Ran 461 tests in 4.613s

OK
```

### 4. 编译检查

```bash
python3 -m py_compile chanlun/policy_experiment_metrics.py scripts/run_policy_experiments.py
```

结果：通过。

### 5. Diff 空白检查

```bash
git diff --check
```

结果：通过。

## 真实回测命令

```bash
/usr/bin/time -p python3 scripts/run_policy_experiments.py \
  --policies delay1_v1,delay1_v1_bottom_quality_guard,delay1_v1_bottom_distance_gt6_guard,delay1_v1_bottom_missing_shape_guard \
  --output-json /tmp/phase6_9_policy_execution_observability_metrics.json \
  --output-md /tmp/phase6_9_policy_execution_observability_metrics.md
```

结果：

```text
real 45.67
user 6.41
sys 2.81
```

输出文件：

- `/tmp/phase6_9_policy_execution_observability_metrics.json`
- `/tmp/phase6_9_policy_execution_observability_metrics.md`

## Execution Summary

```text
shared_baseline: True
snapshot_rows: 2842
unique_codes: 1103
fetch_attempts: 1103
cache_hits: 1739
kline_missing: 1
kline_invalid: 0
baseline_rows: 1287
```

解释：

- `snapshot_rows=2842`：原始快照 picks 行数。
- `unique_codes=1103`：本次回测涉及 1103 个唯一股票代码。
- `fetch_attempts=1103`：每个唯一代码只触发一次共享 K 线 lookup。
- `cache_hits=1739`：重复代码命中共享缓存，不再按 policy 重复取数。
- `kline_missing=1`：有 1 行因为最终没有 K 线数据被跳过。
- `kline_invalid=0`：没有归一化失败的 K 线。
- `baseline_rows=1287`：最终进入 policy 对比的共享 baseline 样本数。

## 回测指标

| Policy | Baseline n | Baseline Filtered | Policy n | Policy T+3 | Delta T+3 | T+3 Win | Loss <=5 | Big Drop <=5 | Filtered | Retained | Reason |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `delay1_v1` | 1287 | 805 | 1287 | 0.03 | 0.00 | 44.5 | 18.2 | 36.3 | 0 | 100.00 | - |
| `delay1_v1_bottom_quality_guard` | 1287 | 805 | 1101 | 0.16 | 0.13 | 45.9 | 18.7 | 36.9 | 186 | 85.55 | `bottom_quality_guard:186` |
| `delay1_v1_bottom_distance_gt6_guard` | 1287 | 805 | 1242 | 0.07 | 0.04 | 44.8 | 18.0 | 36.2 | 45 | 96.50 | `bottom_distance_gt_6:45` |
| `delay1_v1_bottom_missing_shape_guard` | 1287 | 805 | 1129 | 0.12 | 0.09 | 45.5 | 18.6 | 37.0 | 158 | 87.72 | `bottom_missing_shape_or_stop_drop:158` |

## 与 Phase 6.8 的一致性

本次包含的 4 个 policy 与 Phase 6.8 关键指标一致：

- baseline n `1287`
- baseline filtered `805`
- `delay1_v1_bottom_quality_guard`: n `1101`, filtered `186`, T+3 `0.16`
- `delay1_v1_bottom_distance_gt6_guard`: n `1242`, filtered `45`, T+3 `0.07`
- `delay1_v1_bottom_missing_shape_guard`: n `1129`, filtered `158`, T+3 `0.12`

结论：Phase 6.9 只增加观测字段，没有改变策略行为。

## 数据源状态

真实回测日志仍出现大量远端日线失败并 fallback 到 cache：

```text
[CACHE FALLBACK] day <code> remote failed, using cache
```

这说明外部数据源稳定性问题仍然存在。本阶段新增的 execution 字段能看到最终结构化影响：

- `fetch_attempts=1103`
- `cache_hits=1739`
- `kline_missing=1`
- `kline_invalid=0`

下一步如果要进一步拆数据源质量，需要在 fetch 层增加 remote failure/fallback success 的结构化计数。当前 Phase 6.9 只统计 policy runner 视角。

## 下一阶段建议

Phase 6.10 建议回到策略收益侧，做“弱趋势过滤”：

- 只对 `delay1_v1_bottom_quality_guard` 的保留样本再加趋势过滤。
- 先用已有 pick/结构字段做最小实验，避免再引入远端数据依赖。
- 指标重点：
  - T+3 mean 是否继续提升。
  - `t3_loss_5pct_rate` 和 `big_drop_5pct_rate` 是否下降。
  - 交易数不要低于 baseline 的 70%，避免过度过滤。

可选实验：

```text
delay1_v1_bottom_quality_trend_guard
```

晋级门槛建议：

- T+3 mean >= `bottom_quality_guard`
- T+3 win rate >= `bottom_quality_guard`
- t3 loss <=5% rate 不高于 `bottom_quality_guard`
- big drop <=5% rate 不高于 `bottom_quality_guard`
