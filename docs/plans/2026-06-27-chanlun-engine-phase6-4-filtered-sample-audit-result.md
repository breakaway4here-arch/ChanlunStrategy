# ChanLun Engine Phase 6.4 被过滤样本误伤审计结果

日期: 2026-06-27

## 结论

`signal_delay1_by_type_guard` 过滤掉的样本整体质量较差，过滤方向成立。

但 top winners 中存在少数明显误伤，因此当前不建议直接 promotion 到 production。下一步应做 candidate v2: 在保持整体过滤收益的前提下，尝试救回少数高确认度的大涨样本。

## 审计命令

```bash
python3 scripts/audit_filtered_samples.py \
  --experiment signal_delay1_by_type_guard \
  --output-json /tmp/phase6_4_filtered_audit.json \
  --output-md /tmp/phase6_4_filtered_audit.md
```

## 验证结果

```bash
python3 -m py_compile chanlun/filtered_sample_audit.py scripts/audit_filtered_samples.py
python3 -m unittest tests.test_filtered_sample_audit tests.test_audit_filtered_samples_script -v
python3 -m unittest discover tests
```

结果:

- py_compile: pass
- targeted tests: `Ran 6 tests ... OK`
- full tests: `Ran 434 tests ... OK`
- real audit: exit code `0`

## Summary

```json
{
  "filtered": 417,
  "n": 417,
  "t1_mean": -1.18,
  "t1_median": -0.77,
  "t3_mean": -2.49,
  "t3_median": -2.72,
  "t3_win_rate": 23.3,
  "t3_loss_5pct_rate": 26.9,
  "max_up_3d_mean": -5.41,
  "big_drop_5pct_rate": 47.2,
  "big_run_5pct_rate": 20.9
}
```

解释:

- 被过滤样本 T+3 均值显著为负。
- 胜率只有 `23.3%`。
- 近一半样本 3 日内出现过 `<= -5%` 的大回撤。
- 说明该 guard 主要挡掉的是高噪音/高风险样本。

## Top Winners

| Date | Version | Code | Name | T+3 | Distance | Confirmations |
|---|---|---|---|---:|---:|---|
| 2026-06-02 | picks_pure | 300322 | 硕贝德 | 17.88% | 4.30 | 30min底分型, 关键位不破 |
| 2026-05-28 | picks_pure | 300913 | 兆龙互连 | 16.77% | 6.10 | 30min底分型, 关键位不破, EMA5收复 |
| 2026-05-28 | picks_fusion | 300913 | 兆龙互连 | 16.77% | 6.10 | 30min底分型, 关键位不破, EMA5收复 |
| 2026-05-27 | picks_pure | 300265 | 通光线缆 | 15.96% | 2.76 | 关键位不破, EMA5收复, 止跌结构 |
| 2026-06-18 | picks_pure | 688338 | 赛科希德 | 14.18% | 2.04 | 30min底分型, 关键位不破, EMA5收复, 止跌结构 |
| 2026-06-18 | picks_fusion | 688338 | 赛科希德 | 14.18% | 2.04 | 30min底分型, 关键位不破, EMA5收复, 止跌结构 |
| 2026-05-27 | picks_pure | 600792 | 云煤能源 | 13.16% | 1.88 | 30min底分型, 关键位不破, 止跌结构 |
| 2026-06-09 | picks_pure | 600567 | 山鹰国际 | 12.50% | 1.57 | 关键位不破, EMA5收复 |
| 2026-05-27 | picks_pure | 001896 | 豫能控股 | 12.13% | 4.93 | 关键位不破, EMA5收复 |
| 2026-05-27 | picks_pure | 605499 | 东鹏饮料 | 9.49% | 1.02 | 关键位不破, EMA5收复 |

判断:

- 误伤确实存在，最高 T+3 接近 `18%`。
- 误伤样本多带 `关键位不破`、`EMA5收复`、`30min底分型` 等确认。
- 但这些 confirmation 组合整体并不都强，不能因为 top winners 就全量放回。

## By Type

| Type | N | T+3 Mean | T+3 Win | Big Run | Big Drop |
|---|---:|---:|---:|---:|---:|
| 底背驰候选 | 417 | -2.49% | 23.3% | 20.9% | 47.2% |

## By Signal Tier

| Signal Tier | N | T+3 Mean | T+3 Win | Big Run | Big Drop |
|---|---:|---:|---:|---:|---:|
| candidate | 417 | -2.49% | 23.3% | 20.9% | 47.2% |

## By Confirmations

| Confirmations | N | T+3 Mean | T+3 Win | Big Run | Big Drop |
|---|---:|---:|---:|---:|---:|
| EMA5收复+关键位不破 | 143 | -3.12% | 19.6% | 18.2% | 49.0% |
| 30min底分型+关键位不破 | 103 | -2.50% | 20.4% | 20.4% | 40.8% |
| EMA5收复+关键位不破+止跌结构 | 79 | -1.95% | 29.1% | 26.6% | 39.2% |
| 30min底分型+EMA5收复+关键位不破 | 61 | -1.47% | 29.5% | 24.6% | 60.7% |
| 30min底分型+EMA5收复+关键位不破+止跌结构 | 30 | -3.47% | 20.0% | 10.0% | 56.7% |
| 30min底分型+关键位不破+止跌结构 | 1 | 13.16% | 100.0% | 100.0% | 0.0% |

判断:

- 没有一个大样本 confirmation 组合能证明“应该整体救回”。
- `EMA5收复+关键位不破+止跌结构` 相对没那么差，但 T+3 均值仍为负。
- 单样本高收益组合不能作为规则依据。

## By Distance Bucket

| Distance | N | T+3 Mean | T+3 Win | Big Run | Big Drop |
|---|---:|---:|---:|---:|---:|
| 0-3% | 317 | -1.92% | 24.6% | 22.1% | 35.6% |
| 3-6% | 80 | -5.23% | 13.8% | 11.2% | 91.2% |
| 6-10% | 19 | -0.45% | 42.1% | 36.8% | 57.9% |
| >10% | 1 | -1.01% | 0.0% | 100.0% | 0.0% |

判断:

- `3-6%` 距离桶极差，是优先过滤区间。
- `0-3%` 样本最多，整体仍负，但 big drop 明显低于其他桶。
- `6-10%` 样本少且波动大，既有 big run，也有高 big drop，不适合简单放回。

## 是否存在不可接受误伤

结论: 有误伤，但不是不可接受。

理由:

- Top winners 说明 v1 会错过少数大涨样本。
- 但被过滤整体 T+3 均值 `-2.49%`，胜率 `23.3%`，big drop `47.2%`。
- 过滤贡献大于误伤成本。

因此:

```text
signal_delay1_by_type_guard v1 可以继续推进，但不直接 promotion。
```

## 下一步建议

Phase 6.5 做 candidate v2，不改 production:

1. 保留 v1 的底背驰延迟/过滤主逻辑。
2. 对 top-winner 特征做“救回规则”实验，例如:
   - `30min底分型 + 关键位不破`
   - `关键位不破 + EMA5收复 + 止跌结构`
   - 距离 `0-3%` 且多 confirmation
3. 用 `--historical-return-metrics` 重新跑 gate。
4. 同时输出 filtered audit，确认救回没有把风险重新放大。

不要直接进入 production promotion。
