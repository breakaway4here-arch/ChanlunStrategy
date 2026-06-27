# ChanLun 延迟确认回测结果 - latest

生成时间：2026-06-27

## 结论

这次回测验证了用户提出的核心判断：当前更有效的优化点不是继续复制 candidate 架构，而是让信号晚一根 K 线确认后再执行。

最新结果显示：

- `signal_delay1_by_type_guard` 是当前最优版本。
- legacy 的 T+3 平均收益为 `-0.92%`，v1 提升到 `0.03%`。
- T+3 胜率从 `35.9%` 提升到 `44.5%`。
- T+3 跌幅超过 5% 的比例从 `23.7%` 降到 `18.2%`。
- 3 日内最大回撤均值从 `-5.03%` 收敛到 `-4.46%`。
- v2 虽然也通过 gate，但弱于 v1，不建议替代 v1。

## 验证命令

```bash
python3 -m py_compile \
  chanlun/historical_experiment_metrics.py \
  chanlun/filtered_sample_audit.py \
  scripts/run_engine_experiments.py \
  scripts/audit_filtered_samples.py

python3 -m unittest discover -s tests

python3 scripts/run_engine_experiments.py \
  --experiments signal_delay1_by_type_guard,signal_delay1_by_type_guard_v2 \
  --historical-return-metrics \
  --output-json /tmp/chanlun_delay_guard_metrics_latest.json \
  --output-md /tmp/chanlun_delay_guard_metrics_latest.md

python3 scripts/backtest_delayed_entry.py \
  --output-json /tmp/chanlun_delayed_entry_latest.json

python3 scripts/audit_filtered_samples.py \
  --experiment signal_delay1_by_type_guard \
  --output-json /tmp/chanlun_v1_filtered_audit_latest.json \
  --output-md /tmp/chanlun_v1_filtered_audit_latest.md
```

## 验证结果

- 单测：`Ran 443 tests in 4.548s - OK`
- 语法编译：通过
- 历史回测：通过，输出文件已生成
- 过滤样本审计：通过，输出文件已生成

回测过程中远端日线接口多次返回空/异常，脚本使用本地日线缓存兜底：

```text
[CACHE FALLBACK] day <code> remote failed, using cache
```

因此本轮结果可用于策略相对比较，但后续正式 promotion 前建议补一轮“数据源健康”验证。

## 延迟入场模式对比

样本范围：

- snapshot days：`24`
- picks seen：`2842`
- immediate/delay1_open 可评估样本：`1706`
- delay1_close 可评估样本：`1695`
- skipped no kline：`1`

### picks_pure

| 模式 | n | T+1均值 | T+3均值 | T+3胜率 | T+3跌超5% | 最大回撤均值 | 3日大跌率 | 3日大涨率 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| immediate_close | 1272 | -0.12% | -0.71% | 38.3% | 22.8% | -4.91% | 42.7% | 31.8% |
| delay1_open | 1272 | 0.25% | -0.35% | 40.9% | 19.6% | -4.56% | 37.5% | 34.8% |
| delay1_close | 1263 | -0.19% | -1.01% | 37.5% | 25.9% | -5.09% | 45.1% | 32.4% |

结论：`picks_pure` 里 `delay1_open` 最好。

### picks_fusion

| 模式 | n | T+1均值 | T+3均值 | T+3胜率 | T+3跌超5% | 最大回撤均值 | 3日大跌率 | 3日大涨率 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| immediate_close | 434 | -0.75% | -1.52% | 28.8% | 26.3% | -5.38% | 49.3% | 27.4% |
| delay1_open | 434 | -0.53% | -1.31% | 30.0% | 23.7% | -5.17% | 44.7% | 29.7% |
| delay1_close | 432 | 0.02% | -0.95% | 33.3% | 21.5% | -4.90% | 43.1% | 30.6% |

结论：`picks_fusion` 里 `delay1_close` 最好。

## 实验版本对比

### v1：signal_delay1_by_type_guard

规则：

- 新形成的 `底背驰候选` 延迟确认。
- `强势启动候选` 不过滤。
- 底背驰候选使用 delay1 close 入场，强势启动使用 delay1 open 入场。

覆盖：

- legacy evaluated：`1706`
- experiment evaluated：`1287`
- filtered：`805`
- skipped no kline：`1`

收益：

| 指标 | legacy | v1 |
| --- | ---: | ---: |
| n | 1706 | 1287 |
| T+1均值 | -0.28% | 0.58% |
| T+3均值 | -0.92% | 0.03% |
| T+3胜率 | 35.9% | 44.5% |
| T+3跌超5% | 23.7% | 18.2% |
| 最大回撤均值 | -5.03% | -4.46% |
| 3日大跌率 | 44.4% | 36.3% |
| 3日大涨率 | 30.7% | 38.0% |

Gate：`pass`

### v2：signal_delay1_by_type_guard_v2

规则：

- 在 v1 基础上，尝试救回部分有强确认的底背驰候选。

覆盖：

- legacy evaluated：`1706`
- experiment evaluated：`1373`
- filtered：`614`
- skipped no kline：`1`

收益：

| 指标 | legacy | v2 |
| --- | ---: | ---: |
| n | 1706 | 1373 |
| T+1均值 | -0.28% | 0.56% |
| T+3均值 | -0.92% | -0.12% |
| T+3胜率 | 35.9% | 43.2% |
| T+3跌超5% | 23.7% | 19.0% |
| 最大回撤均值 | -5.03% | -4.49% |
| 3日大跌率 | 44.4% | 37.0% |
| 3日大涨率 | 30.7% | 37.4% |

Gate：`pass`

但 v2 在 T+3 均值、胜率、回撤、大跌率、大涨率上都弱于 v1，所以保留为实验，不建议晋升。

## 被过滤样本审计

v1 被过滤样本：

- n：`417`
- T+1均值：`-1.18%`
- T+3均值：`-2.49%`
- T+3胜率：`23.3%`
- T+3跌超5%：`26.9%`
- 最大回撤均值：`-5.41%`
- 3日大跌率：`47.2%`
- 3日大涨率：`20.9%`

这说明 v1 过滤掉的样本整体质量明显偏弱，方向成立。

但被过滤样本里仍有少量大赢家：

| 日期 | 版本 | 代码 | 名称 | T+3 | confirmations | distance |
| --- | --- | --- | --- | ---: | --- | ---: |
| 2026-06-02 | picks_pure | 300322 | 硕贝德 | 17.88% | 30min底分型, 关键位不破 | 4.30 |
| 2026-05-28 | picks_pure | 300913 | 兆龙互连 | 16.77% | 30min底分型, 关键位不破, EMA5收复 | 6.10 |
| 2026-05-28 | picks_fusion | 300913 | 兆龙互连 | 16.77% | 30min底分型, 关键位不破, EMA5收复 | 6.10 |
| 2026-05-27 | picks_pure | 300265 | 通光线缆 | 15.96% | 关键位不破, EMA5收复, 止跌结构 | 2.76 |
| 2026-06-18 | picks_pure | 688338 | 赛科希德 | 14.18% | 30min底分型, 关键位不破, EMA5收复, 止跌结构 | 2.04 |

解释：

- v1 的收益提升主要来自过滤掉大量低质量早信号。
- 代价是会错过少量强反弹样本。
- v2 试图救回这些样本，但整体收益反而变弱，因此当前不应救得太宽。

## 最终判断

用户提出的“信号延迟 1 根 K 线确认”是当前最有效方向之一，且已经被最新回测验证。

建议：

1. 当前最优候选：`signal_delay1_by_type_guard`
2. 暂不推广 v2
3. 下一阶段继续围绕 v1 做组合优化：
   - 弱趋势过滤
   - 信号冷却机制
   - 震荡/趋势分层
