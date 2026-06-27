# ChanLun Engine Phase 6.12 Execution Model Backtest Result

## 结论

Phase 6.12 已完成：policy backtest runner 现在可以在同一过滤样本集上对比不同入场模型。

本轮真实回测结论：

- `entry_next_open` 与当前 `baseline_type_guard` 几乎一致，是当前最稳的执行模型。
- `entry_signal_close` 收益更低、风险更高，说明信号日收盘直接买并没有改善效果。
- `entry_confirm_close` 明显变差，T+3 转负，说明再等到确认 K 收盘会损失边际收益。
- 这一步证明当前收益瓶颈不主要是“入场太早”，而是后续退出/风控模型太粗。

## 代码变更

- `chanlun/policy_experiment_metrics.py`
  - 新增三条 execution variant policy：
    - `delay1_v1_bottom_quality_market_known_guard_entry_signal_close`
    - `delay1_v1_bottom_quality_market_known_guard_entry_next_open`
    - `delay1_v1_bottom_quality_market_known_guard_entry_confirm_close`
  - `evaluated_rows` 增加 `normalized_kline`，用于同一 accepted sample 的 entry mode 复算。
  - policy result 增加：
    - `execution_model.entry_label`
    - `execution_model.entry_mode`
    - `coverage.policy_not_evaluable`

- `scripts/run_policy_experiments.py`
  - Markdown 主表新增：
    - `Entry Model`
    - `Entry Mode`
    - `Not Evaluable`
  - 保留 Phase 6.11 的 `Breakdown Summary`。

- `tests/test_policy_experiment_metrics.py`
  - 覆盖新增 policy 注册。
  - 覆盖三条 execution variant 与 base guard 的过滤一致性。
  - 覆盖显式 entry mode 复算。
  - 覆盖 `policy_not_evaluable`。

- `tests/test_policy_experiment_runner_script.py`
  - 覆盖 Markdown 新增 execution model 列。

## Code Review

Review 后只做了一个小修：

- `scripts/run_policy_experiments.py` 的 Markdown 表格分隔行补齐一列，使表头、分隔行、数据行列数一致。

未发现需要阻断的问题：

- 只修改了 Phase 6.12 允许的四个文件。
- 未修改生产 `analyze()`。
- 未修改 candidate provider/registry 架构。
- execution variant 复用同一过滤规则，没有变成新的信号策略。

## 测试命令

```bash
python3 -m unittest tests.test_policy_experiment_metrics tests.test_policy_experiment_runner_script
```

结果：

```text
Ran 30 tests in 0.025s
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
python3 -m unittest tests.test_policy_experiment_metrics tests.test_policy_experiment_runner_script tests.test_historical_experiment_metrics tests.test_engine_experiment_runner_script tests.test_backtest_execution
```

结果：

```text
Ran 52 tests in 1.460s
OK
```

```bash
python3 -m unittest discover -s tests
```

结果：

```text
Ran 473 tests in 4.647s
OK
```

## 真实回测命令

```bash
/usr/bin/time -p python3 scripts/run_policy_experiments.py \
  --policies delay1_v1_bottom_quality_market_known_guard,delay1_v1_bottom_quality_market_known_guard_entry_signal_close,delay1_v1_bottom_quality_market_known_guard_entry_next_open,delay1_v1_bottom_quality_market_known_guard_entry_confirm_close \
  --output-json /tmp/phase6_12_execution_model_metrics.json \
  --output-md /tmp/phase6_12_execution_model_metrics.md
```

结果：

```text
real 45.34
user 6.32
sys 2.75
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

回测过程中仍有远端行情接口 JSON 解析失败，但均走了已有 cache fallback；这与 Phase 6.10/6.11 现象一致。

## 回测结果

| Policy | Entry Model | Entry Mode | Policy n | Not Evaluable | Filtered | Retained % | T+3 | ΔT+3 | Win % | Loss<=5 % | BigDrop % |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| delay1_v1_bottom_quality_market_known_guard | baseline_type_guard | baseline_type_guard | 989 | 0 | 298 | 76.85 | 0.41 | 0.38 | 46.8 | 17.7 | 36.2 |
| delay1_v1_bottom_quality_market_known_guard_entry_signal_close | entry_signal_close | immediate_close | 989 | 0 | 298 | 76.85 | 0.09 | 0.06 | 43.6 | 20.7 | 41.2 |
| delay1_v1_bottom_quality_market_known_guard_entry_next_open | entry_next_open | delay1_open | 989 | 0 | 298 | 76.85 | 0.41 | 0.38 | 46.3 | 17.7 | 36.3 |
| delay1_v1_bottom_quality_market_known_guard_entry_confirm_close | entry_confirm_close | delay1_close | 980 | 9 | 298 | 76.15 | -0.43 | -0.46 | 40.6 | 25.6 | 46.5 |

## 解读

### entry_signal_close

```text
T+3=0.09
Win=43.6
Loss<=5=20.7
BigDrop=41.2
```

信号日收盘买入比当前模型差。它没有带来“更早拿到利润”的优势，反而增加了亏损和大跌样本。

### entry_next_open

```text
T+3=0.41
Win=46.3
Loss<=5=17.7
BigDrop=36.3
```

次日开盘买入与当前 baseline_type_guard 基本一致，是当前可保留的执行模型。它没有明显扩大收益，但也没有引入额外风险。

### entry_confirm_close

```text
T+3=-0.43
Win=40.6
Loss<=5=25.6
BigDrop=46.5
```

确认 K 收盘买入明显变差，说明“再等确认”在当前样本里会牺牲太多位置优势。后续不建议继续沿着更慢入场优化。

## 对用户问题的回答

用户提出“信号延迟 1 根 K 线确认”作为优先优化方向。当前结论是：

- 延迟确认已经是当前 baseline 的一部分。
- 一味继续延迟入场不会提升收益。
- 真实改进点更可能在退出和风控，而不是入场再推迟。

## Phase 6.13 建议

下一阶段建议做 `Exit Risk Model Backtest`：

- 固定候选：
  - `delay1_v1_bottom_quality_market_known_guard_entry_next_open`
- 增加退出模型：
  - `exit_t3`
  - `exit_stop_loss_5pct`
  - `exit_take_profit_8pct_or_t3`
  - `exit_trailing_stop_after_5pct`
- 输出指标：
  - 平均收益
  - 胜率
  - `loss<=5%`
  - `bigdrop>=5%`
  - not evaluable
  - retained %

目标：

- 判断当前收益不大的主因是否是固定 T+3 退出过粗。
- 降低 `loss<=5%` 和 `bigdrop>=5%`，而不是继续追求入场点更晚。
