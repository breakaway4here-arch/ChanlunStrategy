# ChanLun Engine Phase 6.5 Delay Guard V2 救回规则计划

日期: 2026-06-27

## 背景

Phase 6.3 证明 `signal_delay1_by_type_guard` 能显著改善历史收益:

```text
T+3 mean: -0.92 -> 0.03
T+3 win: 35.9% -> 44.5%
T+3 <= -5%: 23.7% -> 18.2%
big drop: 44.4% -> 36.3%
gate: pass
```

Phase 6.4 证明被过滤样本整体较差:

```text
filtered n=417
T+3 mean=-2.49
T+3 win=23.3%
big drop=47.2%
```

但 top winners 里存在少数明显误伤:

- 300322 硕贝德: T+3 `17.88%`
- 300913 兆龙互连: T+3 `16.77%`
- 300265 通光线缆: T+3 `15.96%`
- 688338 赛科希德: T+3 `14.18%`

这些误伤样本多带:

- `关键位不破`
- `EMA5收复`
- `30min底分型`
- `止跌结构`

但分组统计显示，大样本 confirmation 组合整体仍为负，因此不能简单全量救回。

## 目标

新增 opt-in candidate:

```text
signal_delay1_by_type_guard_v2
```

目标不是 promotion，而是测试一个更精细的规则:

```text
在 v1 过滤底背驰候选的基础上，只救回少数高确认度样本。
```

## 范围

### Do

- 增加 v2 signal experiment。
- 增加历史收益 metrics 支持。
- 增加 filtered audit 支持。
- 跑真实 historical gate 和 filtered audit。

### Do Not

- 不修改 production `analyze()`。
- 不替换 v1。
- 不直接 promotion。
- 不做弱趋势/冷却规则。

## 候选救回规则

从 Phase 6.4 top winners 和分组看，较合理的低风险 v2 是:

```text
底背驰候选刚形成时:
  默认过滤

  但如果 confirmations 同时包含:
    - 关键位不破
    - EMA5收复
    - 止跌结构
  且 distance_from_reference_pct <= 3
  则救回
```

理由:

- `0-3%` 距离桶风险明显低于 `3-6%`。
- `EMA5收复+关键位不破+止跌结构` 组合在大样本中虽然仍为负，但是相对较不差的一组。
- 该规则比救回全部 `关键位不破+EMA5` 更保守。

不要救回:

- `3-6%` 距离桶，Phase 6.4 显示极差: T+3 mean `-5.23`，big drop `91.2%`。
- 仅 `关键位不破+EMA5收复`，大样本 T+3 mean `-3.12`。
- 仅 `30min底分型+关键位不破`，T+3 mean `-2.50`。

## 实现建议

### Signal provider

文件:

- `chanlun/engine_signal_experiments.py`
- `chanlun/engine_experiments.py`

新增:

```python
locate_buy_sell_points_delay1_by_type_guard_v2(result)
```

逻辑:

1. 调用 production `locate_buy_sell_points(result)`。
2. 对 buy_points 应用 v2 drop predicate。
3. sell_points 原样返回。
4. 缺字段 no-op 或按保守路径处理，不能抛异常。

### Historical metrics

文件:

- `chanlun/historical_experiment_metrics.py`

新增支持:

```text
signal_delay1_by_type_guard_v2
```

entry mode:

```text
底背驰候选 -> delay1_close
强势启动候选 -> delay1_open
其他 -> immediate_close
```

drop predicate 必须与 provider v2 一致。

### Filtered audit

无需新增脚本。`scripts/audit_filtered_samples.py` 应能直接支持 v2，只要 `supports_historical_return_metrics()` 包含 v2。

## 测试

新增/更新:

- `tests/test_engine_signal_experiments.py`
- `tests/test_engine_experiments.py`
- `tests/test_historical_experiment_metrics.py`
- `tests/test_filtered_sample_audit.py` 如有必要

必须覆盖:

- v2 过滤普通刚形成底背驰候选。
- v2 救回 `关键位不破 + EMA5收复 + 止跌结构 + distance<=3`。
- v2 不救回 `distance>3`。
- v2 不救回缺 confirmation 的样本。
- registry 只覆盖 `signal_provider`。
- historical metrics 支持 v2。

## 验证命令

```bash
python3 -m py_compile \
  chanlun/engine_signal_experiments.py \
  chanlun/engine_experiments.py \
  chanlun/historical_experiment_metrics.py

python3 -m unittest \
  tests.test_engine_signal_experiments \
  tests.test_engine_experiments \
  tests.test_historical_experiment_metrics \
  -v

python3 -m unittest discover tests

python3 scripts/run_engine_experiments.py \
  --experiments signal_delay1_by_type_guard_v2 \
  --historical-return-metrics \
  --output-json /tmp/phase6_5_v2_metrics.json \
  --output-md /tmp/phase6_5_v2_metrics.md

python3 scripts/audit_filtered_samples.py \
  --experiment signal_delay1_by_type_guard_v2 \
  --output-json /tmp/phase6_5_v2_filtered_audit.json \
  --output-md /tmp/phase6_5_v2_filtered_audit.md
```

## 验收标准

v2 必须同时满足:

- historical gate 仍为 pass，或至少不明显弱于 v1。
- T+3 mean 不低于 v1 太多。
- T+3 win rate 不低于 v1 太多。
- big drop 不明显高于 v1。
- filtered audit 中 top winners 误伤减少。

对比基线:

```text
v1:
  n=1287
  T+3 mean=0.03
  T+3 win=44.5%
  T+3 loss5=18.2%
  big drop=36.3%
```

如果 v2 为了救回少数 winner 导致风险显著回升，则 reject v2，保留 v1。

## 结果文档

完成后落盘:

```text
docs/plans/2026-06-27-chanlun-engine-phase6-5-delay-guard-v2-rescue-result.md
```

内容:

- v1 vs v2 historical metrics。
- v1 vs v2 filtered audit。
- 救回样本数量。
- 是否值得继续迭代。

## 后续

如果 v2 优于 v1:

1. Phase 6.6 做 promotion-ready pipeline validation。
2. 再进入弱趋势/冷却组合。

如果 v2 弱于 v1:

1. reject v2。
2. 保留 v1 为当前最佳 candidate。
3. 再做弱趋势/冷却，但不要混入救回规则。
