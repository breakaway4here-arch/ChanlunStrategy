# ChanLun Engine Phase 6.8 Policy Runner Shared Cache Result

## 结论

Phase 6.8 已完成并通过验证。

这一步不是策略收益优化，而是回测执行器优化：多 policy 回测现在共享同一批 baseline 样本和同一份日线缓存，避免每个 policy 重复扫描、重复取数、重复计算 baseline。

真实回测结果与 Phase 6.7 关键指标保持一致，说明本次改动没有改变策略行为。

## 改动摘要

修改文件：

- `chanlun/policy_experiment_metrics.py`
- `tests/test_policy_experiment_metrics.py`

核心变化：

- 新增共享 baseline context 构建逻辑。
- `run_policy_experiment_metrics()` 只构建一次 snapshot rows、snapshot day index、baseline samples。
- 每个 policy 只消费已经评估过的 baseline rows。
- 每个 policy 仍保留独立 cooldown state，避免策略之间互相污染。
- 新增测试覆盖：
  - 多 policy 共享同一批 K 线 fetch。
  - 多 policy 下 cooldown state 仍独立。

## 验证命令

### 1. Policy runner 定向测试

```bash
python3 -m unittest tests.test_policy_experiment_metrics tests.test_policy_experiment_runner_script
```

结果：

```text
Ran 16 tests in 0.012s

OK
```

### 2. 回测相关扩展测试

```bash
python3 -m unittest tests.test_policy_experiment_metrics tests.test_policy_experiment_runner_script tests.test_historical_experiment_metrics tests.test_engine_experiment_runner_script
```

结果：

```text
Ran 33 tests in 1.512s

OK
```

### 3. 全量测试

```bash
python3 -m unittest discover -s tests
```

结果：

```text
Ran 459 tests in 4.493s

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
  --policies delay1_v1,delay1_v1_bottom_quality_guard,delay1_v1_bottom_missing_key_guard,delay1_v1_bottom_missing_distance_guard,delay1_v1_bottom_invalid_distance_guard,delay1_v1_bottom_distance_gt6_guard,delay1_v1_bottom_missing_shape_guard \
  --output-json /tmp/phase6_8_policy_shared_cache_metrics.json \
  --output-md /tmp/phase6_8_policy_shared_cache_metrics.md
```

结果：

```text
real 55.84
user 6.24
sys 2.81
```

输出文件：

- `/tmp/phase6_8_policy_shared_cache_metrics.json`
- `/tmp/phase6_8_policy_shared_cache_metrics.md`

## 回测结果

生成时间：

```text
2026-06-27T20:46:48.016050
```

| Policy | Baseline n | Baseline T+3 | Policy n | Policy T+3 | Delta T+3 | T+3 Win | Loss <=5 | Big Drop <=5 | Filtered | Retained | Reason |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `delay1_v1` | 1287 | 0.03 | 1287 | 0.03 | 0.00 | 44.5 | 18.2 | 36.3 | 0 | 100.00 | - |
| `delay1_v1_bottom_quality_guard` | 1287 | 0.03 | 1101 | 0.16 | 0.13 | 45.9 | 18.7 | 36.9 | 186 | 85.55 | `bottom_quality_guard:186` |
| `delay1_v1_bottom_missing_key_guard` | 1287 | 0.03 | 1287 | 0.03 | 0.00 | 44.5 | 18.2 | 36.3 | 0 | 100.00 | - |
| `delay1_v1_bottom_missing_distance_guard` | 1287 | 0.03 | 1287 | 0.03 | 0.00 | 44.5 | 18.2 | 36.3 | 0 | 100.00 | - |
| `delay1_v1_bottom_invalid_distance_guard` | 1287 | 0.03 | 1287 | 0.03 | 0.00 | 44.5 | 18.2 | 36.3 | 0 | 100.00 | - |
| `delay1_v1_bottom_distance_gt6_guard` | 1287 | 0.03 | 1242 | 0.07 | 0.04 | 44.8 | 18.0 | 36.2 | 45 | 96.50 | `bottom_distance_gt_6:45` |
| `delay1_v1_bottom_missing_shape_guard` | 1287 | 0.03 | 1129 | 0.12 | 0.09 | 45.5 | 18.6 | 37.0 | 158 | 87.72 | `bottom_missing_shape_or_stop_drop:158` |

## 与 Phase 6.7 的一致性

Phase 6.7 关键指标：

- baseline n `1287`
- baseline filtered `805`
- `delay1_v1_bottom_quality_guard`: n `1101`, filtered `186`, T+3 `0.16`
- `delay1_v1_bottom_distance_gt6_guard`: n `1242`, filtered `45`, T+3 `0.07`
- `delay1_v1_bottom_missing_shape_guard`: n `1129`, filtered `158`, T+3 `0.12`

Phase 6.8 关键指标：

- baseline n `1287`
- baseline filtered `805`
- `delay1_v1_bottom_quality_guard`: n `1101`, filtered `186`, T+3 `0.16`
- `delay1_v1_bottom_distance_gt6_guard`: n `1242`, filtered `45`, T+3 `0.07`
- `delay1_v1_bottom_missing_shape_guard`: n `1129`, filtered `158`, T+3 `0.12`

结论：策略行为一致。

## 数据源 fallback

本次真实回测仍有 `[CACHE FALLBACK]` 日志，说明远端/缓存数据源稳定性问题仍然存在。

但 Phase 6.8 已经减少了按 policy 重复放大的问题：同一批 policy 不再各自重复拉取同一批股票日线。

## 下一阶段建议

Phase 6.9 建议优先做回测观测指标，而不是马上继续加策略规则：

- 在 payload 增加非破坏性 `execution` 字段。
- 记录 `shared_baseline: true`。
- 记录 `unique_codes`、`fetch_attempts`、`cache_hits`、`fallback_count`。
- 让后续每次策略优化都能同时看到收益指标和数据质量/执行质量。

做完 Phase 6.9 后，再进入策略侧优化：

- 弱趋势过滤。
- 信号冷却机制细分。
- 震荡/趋势分层。
