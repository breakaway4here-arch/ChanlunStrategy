# ChanLun Engine Phase 6.11 Candidate Convergence Stability Breakdown Result

## 结论

Phase 6.11 已完成：回测报告现在会按 `market_regime`、`best_buy_point_type`、`confirmations` 输出分组分解，用来判断候选策略收益是否集中在少数不稳定样本上。

本轮真实回测结论是：

- `delay1_v1` 单独延迟 1 根 K 线后，T+3 仍为 `0.03`，说明“延迟确认”本身不是足够强的收益来源。
- `delay1_v1_bottom_quality_market_known_guard` 保留 `76.85%` 样本，T+3 到 `0.41`，相对 baseline 提升 `+0.38`，但仍属于温和改善。
- 过滤全部集中在 `底背驰候选`，没有误伤 `强势启动候选` 和 `中枢低吸候选`，策略边界符合预期。
- 当前方向可以继续，但下一阶段应从“再加结构过滤”转向“真实交易执行质量”：入场价、止损、止盈、冷却和趋势/震荡分层。

## 代码变更

- `chanlun/policy_experiment_metrics.py`
  - 为每个 policy 记录 `breakdown`。
  - 分组维度：
    - `market_regime`
    - `best_buy_point_type`
    - `confirmations`
  - 每个 bucket 记录：
    - `total`
    - `accepted`
    - `filtered`
    - `filter_reasons`

- `scripts/run_policy_experiments.py`
  - Markdown 增加 `Breakdown Summary`。
  - `confirmations` 只展示样本数 Top 10，避免报告膨胀。

- `tests/test_policy_experiment_metrics.py`
  - 覆盖 metrics payload 中的 breakdown 结构。

- `tests/test_policy_experiment_runner_script.py`
  - 覆盖 Markdown breakdown 输出。
  - 覆盖 confirmations Top 10 截断逻辑。

## 验证命令

```bash
python3 -m unittest tests.test_policy_experiment_metrics tests.test_policy_experiment_runner_script
```

结果：

```text
Ran 26 tests in 0.017s
OK
```

```bash
python3 -m py_compile chanlun/policy_experiment_metrics.py scripts/run_policy_experiments.py
```

结果：通过，无输出。

```bash
git diff --check
```

结果：通过，无输出。

```bash
python3 -m unittest tests.test_policy_experiment_metrics tests.test_policy_experiment_runner_script tests.test_historical_experiment_metrics tests.test_engine_experiment_runner_script
```

结果：

```text
Ran 43 tests in 1.450s
OK
```

```bash
python3 -m unittest discover -s tests
```

结果：

```text
Ran 469 tests in 4.654s
OK
```

## 真实回测命令

```bash
/usr/bin/time -p python3 scripts/run_policy_experiments.py \
  --policies delay1_v1,delay1_v1_bottom_quality_guard,delay1_v1_bottom_quality_market_known_guard,delay1_v1_bottom_distance_gt6_guard,delay1_v1_bottom_missing_shape_guard \
  --output-json /tmp/phase6_11_candidate_convergence_stability_metrics.json \
  --output-md /tmp/phase6_11_candidate_convergence_stability_metrics.md
```

结果：

```text
real 44.35
user 6.40
sys 2.66
```

执行统计：

```text
snapshot_rows=2842
unique_codes=1103
fetch_attempts=1103
cache_hits=1739
kline_missing=1
kline_invalid=0
baseline_rows=1287
shared_baseline=True
```

## Policy 回测结果

| Policy | Policy n | Filtered | Retained % | T+3 | ΔT+3 | Win % | Loss<=5 % | BigDrop % |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| delay1_v1 | 1287 | 0 | 100.00 | 0.03 | 0.00 | 44.5 | 18.2 | 36.3 |
| delay1_v1_bottom_quality_guard | 1101 | 186 | 85.55 | 0.16 | 0.13 | 45.9 | 18.7 | 36.9 |
| delay1_v1_bottom_quality_market_known_guard | 989 | 298 | 76.85 | 0.41 | 0.38 | 46.8 | 17.7 | 36.2 |
| delay1_v1_bottom_distance_gt6_guard | 1242 | 45 | 96.50 | 0.07 | 0.04 | 44.8 | 18.0 | 36.2 |
| delay1_v1_bottom_missing_shape_guard | 1129 | 158 | 87.72 | 0.12 | 0.09 | 45.5 | 18.6 | 37.0 |

## 分组稳定性

推荐候选：

```text
delay1_v1_bottom_quality_market_known_guard
```

### market_regime

```text
strong:  total=194,  accepted=125, filtered=69,  reasons=bottom_quality_guard:69
unknown: total=1017, accepted=788, filtered=229, reasons=bottom_market_unknown:112, bottom_quality_guard:117
weak:    total=76,   accepted=76,  filtered=0,   reasons=-
```

判断：

- `bottom_market_unknown` 只在 `unknown` 桶触发，行为正确。
- 仍有大量 accepted 来自 `unknown`，原因是 market_known_guard 当前只针对底背驰候选，不处理强势启动候选。
- 下一阶段若要继续提升稳定性，不应直接全局过滤 unknown，否则会误伤大量强势启动样本。

### best_buy_point_type

```text
中枢低吸候选: total=19,  accepted=19,  filtered=0,   reasons=-
底背驰候选:   total=355, accepted=57,  filtered=298, reasons=bottom_market_unknown:112, bottom_quality_guard:186
强势启动候选: total=913, accepted=913, filtered=0,   reasons=-
```

判断：

- 过滤全部集中在 `底背驰候选`。
- 这证明 Phase 6.10 的候选策略边界是可控的，没有扩大到其他买点类型。
- 但也说明收益改善空间受限：当前策略只优化底背驰，主样本仍来自强势启动候选。

### confirmations Top Buckets

```text
30min EMA5维持:
  total=793, accepted=793, filtered=0

EMA5收复 + 关键位不破:
  total=169, accepted=11, filtered=158, reasons=bottom_quality_guard:158

EMA5收复 + 关键位不破 + 止跌结构:
  total=111, accepted=34, filtered=77, reasons=bottom_market_unknown:51, bottom_quality_guard:26

30min EMA5维持 + 30min回踩不破突破位:
  total=64, accepted=64, filtered=0

30min回踩不破突破位:
  total=56, accepted=56, filtered=0
```

判断：

- 大样本桶 `30min EMA5维持` 没有被当前底背驰过滤影响。
- 当前候选策略主要清理的是底背驰里的弱形态确认组合。
- 单靠底背驰质量过滤，无法明显改变强势启动样本的收益结构。

## 对“信号延迟 1 根 K 线确认”的判断

用户给出的优化方向是对的，但当前回测显示：

```text
delay1_v1: T+3=0.03, ΔT+3=0.00
```

也就是说，在现有样本和执行模型里，“延迟 1 根 K 线确认”已经作为 baseline 存在，但单独收益不明显。

更准确的结论是：

- 延迟确认是必要的防噪声机制。
- 但当前收益瓶颈不只在信号触发过早。
- 下一步要把延迟确认和交易执行规则一起评估：
  - 入场价：信号日收盘、次日开盘、确认 K 收盘三者差异。
  - 退出：固定 T+3 不足以反映真实策略。
  - 风控：底部信号需要止损，强势启动需要冷却和追高限制。
  - 分层：底背驰、强势启动、中枢低吸不能共用同一执行模型。

## 下一阶段建议

Phase 6.12 建议做 `Execution Model Backtest`：

- 固化当前最优候选：
  - `delay1_v1_bottom_quality_market_known_guard`
- 增加执行模型 A/B：
  - `entry_signal_close`
  - `entry_next_open`
  - `entry_confirm_close`
- 增加基础退出模型：
  - `exit_t3`
  - `exit_stop_loss_5pct`
  - `exit_take_profit_8pct_or_t3`
- 输出收益分解：
  - 平均收益
  - 胜率
  - `loss<=5%`
  - `bigdrop>=5%`
  - max drawdown
  - 交易次数

目的：

- 判断当前回测提升不大的原因到底是信号质量问题，还是执行模型太粗。
- 把优化从“结构 diff”推进到“交易收益 diff”。
