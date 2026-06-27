# ChanLun Engine Phase 6.5 Delay Guard V2 救回规则结果

日期: 2026-06-27

## 结论

`signal_delay1_by_type_guard_v2` 已实现并通过测试，但不建议替代 v1。

v2 的目标是救回一部分 v1 误杀样本。它确实多保留了样本，但整体收益和风险指标都略弱于 v1。

当前判断:

```text
最佳 candidate 仍是 signal_delay1_by_type_guard v1。
v2 可以保留为实验，不 promotion，不作为下一阶段主线。
```

## 实现

新增 opt-in 实验:

```text
signal_delay1_by_type_guard_v2
```

v2 规则:

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

保持不变:

- 不修改 production `analyze()`。
- 不替换 v1。
- 不改变 report 默认行为。
- 仍通过 experiment registry opt-in 启用。

## 修改文件

- `chanlun/engine_signal_experiments.py`
- `chanlun/engine_experiments.py`
- `chanlun/historical_experiment_metrics.py`
- `tests/test_engine_signal_experiments.py`
- `tests/test_engine_experiments.py`
- `tests/test_historical_experiment_metrics.py`

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
  --experiments signal_delay1_by_type_guard,signal_delay1_by_type_guard_v2 \
  --historical-return-metrics \
  --output-json /tmp/phase6_5_v1_v2_metrics.json \
  --output-md /tmp/phase6_5_v1_v2_metrics.md

python3 scripts/audit_filtered_samples.py \
  --experiment signal_delay1_by_type_guard_v2 \
  --output-json /tmp/phase6_5_v2_filtered_audit.json \
  --output-md /tmp/phase6_5_v2_filtered_audit.md
```

## 验证结果

- py_compile: pass
- targeted tests: `Ran 37 tests ... OK`
- full tests: `Ran 443 tests ... OK`
- v1/v2 historical metrics: exit code `0`
- v2 filtered audit: exit code `0`

## v1 vs v2 Historical Metrics

### Coverage

| Experiment | Legacy Evaluated | Experiment Evaluated | Filtered | Gate |
|---|---:|---:|---:|---|
| v1 | 1706 | 1287 | 805 | pass |
| v2 | 1706 | 1373 | 614 | pass |

说明:

- v2 多保留 `86` 个可评估样本。
- v2 总过滤数少于 v1，说明救回规则生效。

### Return Metrics

| Metric | Legacy | v1 | v2 |
|---|---:|---:|---:|
| n | 1706 | 1287 | 1373 |
| T+1 mean | -0.28 | 0.58 | 0.56 |
| T+3 mean | -0.92 | 0.03 | -0.12 |
| T+3 win rate | 35.9% | 44.5% | 43.2% |
| T+3 <= -5% | 23.7% | 18.2% | 19.0% |
| max dd 3d mean | -5.03 | -4.46 | -4.49 |
| big drop 5% rate | 44.4% | 36.3% | 37.0% |
| big run 5% rate | 30.7% | 38.0% | 37.4% |

判断:

- v2 仍显著优于 legacy。
- v2 通过 gate。
- 但 v2 相比 v1，收益和风险指标均略差。

## v2 Filtered Audit

v2 被过滤样本:

```json
{
  "filtered": 331,
  "t1_mean": -1.5,
  "t3_mean": -2.81,
  "t3_win_rate": 21.5,
  "t3_loss_5pct_rate": 30.2,
  "max_dd_3d_mean": -5.7,
  "big_drop_5pct_rate": 51.1,
  "big_run_5pct_rate": 19.9
}
```

对比 v1 filtered audit:

| Metric | v1 Filtered | v2 Filtered |
|---|---:|---:|
| filtered | 417 | 331 |
| T+3 mean | -2.49 | -2.81 |
| T+3 win rate | 23.3% | 21.5% |
| T+3 <= -5% | 26.9% | 30.2% |
| big drop 5% rate | 47.2% | 51.1% |
| big run 5% rate | 20.9% | 19.9% |

判断:

- v2 剩下继续过滤的样本更差，说明救回规则确实拿走了一部分相对不差的样本。
- 但救回后的整体 experiment metrics 仍弱于 v1，说明救回样本没有带来足够收益，反而拉低了整体质量。

## v2 Top Winners 仍有误伤

v2 filtered audit top winners 仍包括:

| Date | Version | Code | Name | T+3 | Distance | Confirmations |
|---|---|---|---|---:|---:|---|
| 2026-06-02 | picks_pure | 300322 | 硕贝德 | 17.88% | 4.30 | 30min底分型, 关键位不破 |
| 2026-05-28 | picks_pure | 300913 | 兆龙互连 | 16.77% | 6.10 | 30min底分型, 关键位不破, EMA5收复 |
| 2026-05-28 | picks_fusion | 300913 | 兆龙互连 | 16.77% | 6.10 | 30min底分型, 关键位不破, EMA5收复 |
| 2026-05-27 | picks_pure | 600792 | 云煤能源 | 13.16% | 1.88 | 30min底分型, 关键位不破, 止跌结构 |
| 2026-06-09 | picks_pure | 600567 | 山鹰国际 | 12.50% | 1.57 | 关键位不破, EMA5收复 |

这些样本没有被当前 v2 救回，因为缺少 `止跌结构` 或 distance 超出 `<=3`。

但从分组看，进一步扩大救回范围风险很高:

- `EMA5收复+关键位不破`: T+3 mean `-3.12`
- `30min底分型+关键位不破`: T+3 mean `-2.50`
- `30min底分型+EMA5收复+关键位不破`: T+3 mean `-1.47`，big drop `60.7%`

因此不建议继续按 confirmation 简单扩救回。

## 最终判断

```text
v1: pass，当前最佳 candidate
v2: pass，但弱于 v1，保留实验，不进入 promotion 主线
```

Phase 6.5 的价值是证明:

- “救回少数 top winners”这个方向并不天然优于 v1。
- 继续救回会引入更多风险。
- 下一阶段应回到 v1 作为基线，探索弱趋势/冷却等外层过滤，而不是继续放宽底背驰救回。

## 下一步

Phase 6.6 建议:

```text
以 signal_delay1_by_type_guard v1 为基线，做弱趋势过滤 / 信号冷却组合实验。
```

要求:

- 每个组合都必须跑 `--historical-return-metrics`。
- 每个组合都必须跑 filtered audit。
- 不直接 promotion。
