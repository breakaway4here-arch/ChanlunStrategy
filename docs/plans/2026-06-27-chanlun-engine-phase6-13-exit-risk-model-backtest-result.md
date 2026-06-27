# ChanLun Engine Phase 6.13 Exit Risk Model Backtest Result

## 结论

Phase 6.13 已完成：在 backtest-only 层新增退出/风控模型对比，生产 `analyze()` 未改动。

真实回测结论：

- `exit_t3` 仍是本轮最优，T+3 为 `0.41`。
- `exit_stop_loss_5pct` 把均值压到 `0.11`，没有带来收益改善。
- `exit_take_profit_8pct_or_t3` 胜率提高到 `48.3%`，但均值降到 `0.30`，不如 T+3。
- `exit_stop5_take8_conservative` 均值接近 0，组合规则没有优势。

因此，Phase 6.13 不建议推广简单止损/止盈退出模型。下一步更适合做 realized exit diagnostics：把“退出规则后的真实亏损/回撤”和“持有窗口内最大下探”分开统计，否则 stop-loss 的风险控制效果会被现有 `bigdrop` 指标掩盖。

## 代码变更

- `chanlun/backtest_execution.py`
  - 新增 `SUPPORTED_EXIT_MODELS`。
  - 新增 `evaluate_exit_returns()`。
  - 支持：
    - `exit_t3`
    - `exit_stop_loss_5pct`
    - `exit_take_profit_8pct_or_t3`
    - `exit_stop5_take8_conservative`
  - 同日止损/止盈同时触发时，组合模型按保守规则优先止损。

- `chanlun/policy_experiment_metrics.py`
  - 新增四条 exit policy。
  - exit policy 复用：
    - `entry_label=entry_next_open`
    - `entry_mode=delay1_open`
    - `bottom_quality_reasons=all`
    - `bottom_trend_reasons=(market_unknown,)`
  - `execution_model` 增加 `exit_model`。

- `scripts/run_policy_experiments.py`
  - Markdown 主表新增 `Exit Model` 列。

- Tests
  - `tests/test_backtest_execution.py`
  - `tests/test_policy_experiment_metrics.py`
  - `tests/test_policy_experiment_runner_script.py`

## Code Review

Review 结论：

- 修改范围符合 Phase 6.13 MD。
- 未触碰生产 `analyze()`。
- 未修改 candidate provider/registry 架构。
- exit policy 与 Phase 6.12 的 `entry_next_open` 样本保持同一过滤口径。
- Markdown 仍保留 Phase 6.11 的 `Breakdown Summary`。

注意：

- 当前 `bigdrop>=5%` 仍来自原始 3 日窗口内最大下探，不是 exit model 后的 realized drawdown。
- `exit_stop_loss_5pct` 的 `t3_close_pct` 被替换为 `-5.0`，因此 `loss<=5%` 会统计止损触发样本。这是本阶段按计划实现的保守口径，但不适合作为“止损后风险是否下降”的唯一指标。

## 测试命令

```bash
python3 -m unittest tests.test_backtest_execution tests.test_policy_experiment_metrics tests.test_policy_experiment_runner_script
```

结果：

```text
Ran 43 tests in 0.020s
OK
```

```bash
python3 -m py_compile chanlun/backtest_execution.py chanlun/policy_experiment_metrics.py scripts/run_policy_experiments.py
```

结果：通过，无输出。

```bash
git diff --check
```

结果：通过，无输出。

```bash
python3 -m unittest tests.test_policy_experiment_metrics tests.test_policy_experiment_runner_script tests.test_historical_experiment_metrics tests.test_engine_experiment_runner_script tests.test_backtest_execution tests.test_backtest_metrics
```

结果：

```text
Ran 62 tests in 1.445s
OK
```

```bash
python3 -m unittest discover -s tests
```

结果：

```text
Ran 481 tests in 4.632s
OK
```

## 真实回测命令

```bash
/usr/bin/time -p python3 scripts/run_policy_experiments.py \
  --policies delay1_v1_bottom_quality_market_known_guard_entry_next_open,delay1_v1_bottom_quality_market_known_guard_entry_next_open_exit_t3,delay1_v1_bottom_quality_market_known_guard_entry_next_open_exit_stop_loss_5pct,delay1_v1_bottom_quality_market_known_guard_entry_next_open_exit_take_profit_8pct_or_t3,delay1_v1_bottom_quality_market_known_guard_entry_next_open_exit_stop5_take8_conservative \
  --output-json /tmp/phase6_13_exit_risk_model_metrics.json \
  --output-md /tmp/phase6_13_exit_risk_model_metrics.md
```

结果：

```text
real 54.94
user 6.82
sys 2.85
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

回测过程中仍有远端行情接口 JSON 解析失败，但已有 cache fallback 接管；这与 Phase 6.10/6.11/6.12 一致。

## 回测结果

| Policy | Entry Model | Entry Mode | Exit Model | Policy n | Not Evaluable | Retained % | T+3 / Exit Return | ΔT+3 | Win % | Loss<=5 % | BigDrop % | BigRun % |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| delay1_v1_bottom_quality_market_known_guard_entry_next_open | entry_next_open | delay1_open | exit_t3 | 989 | 0 | 76.85 | 0.41 | 0.38 | 46.3 | 17.7 | 36.3 | 41.4 |
| delay1_v1_bottom_quality_market_known_guard_entry_next_open_exit_t3 | entry_next_open | delay1_open | exit_t3 | 989 | 0 | 76.85 | 0.41 | 0.38 | 46.3 | 17.7 | 36.3 | 41.4 |
| delay1_v1_bottom_quality_market_known_guard_entry_next_open_exit_stop_loss_5pct | entry_next_open | delay1_open | exit_stop_loss_5pct | 989 | 0 | 76.85 | 0.11 | 0.08 | 40.4 | 36.3 | 36.3 | 41.4 |
| delay1_v1_bottom_quality_market_known_guard_entry_next_open_exit_take_profit_8pct_or_t3 | entry_next_open | delay1_open | exit_take_profit_8pct_or_t3 | 989 | 0 | 76.85 | 0.30 | 0.27 | 48.3 | 17.7 | 36.3 | 41.4 |
| delay1_v1_bottom_quality_market_known_guard_entry_next_open_exit_stop5_take8_conservative | entry_next_open | delay1_open | exit_stop5_take8_conservative | 989 | 0 | 76.85 | 0.01 | -0.02 | 42.5 | 35.6 | 36.3 | 41.4 |

## 解读

### exit_t3

```text
T+3=0.41
Win=46.3
Loss<=5=17.7
BigDrop=36.3
```

当前固定 T+3 退出仍是本轮最好结果。它不完美，但简单退出规则没有超过它。

### exit_stop_loss_5pct

```text
T+3=0.11
Win=40.4
Loss<=5=36.3
```

止损规则没有提升收益。`loss<=5%` 上升是因为止损样本按 `-5.0` 计入，这说明当前样本里 5% 下探触发较多，机械止损会显著截断后续反弹。

### exit_take_profit_8pct_or_t3

```text
T+3=0.30
Win=48.3
Loss<=5=17.7
```

止盈提高了胜率，但均值低于 T+3。说明部分大波动样本在 T+3 前触发 +8% 后，继续持有到 T+3 反而平均更好，简单止盈会截断收益。

### exit_stop5_take8_conservative

```text
T+3=0.01
Win=42.5
Loss<=5=35.6
```

组合模型最弱。保守规则下，同日同时触发时先算止损，导致它继承止损模型的劣势。

## 下一阶段建议

Phase 6.14 建议做 `Realized Exit Diagnostics`，目标不是立刻新增策略，而是先补足指标口径：

- 统计 exit reason 分布：
  - `t3_close`
  - `stop_loss_5pct`
  - `take_profit_8pct`
- 增加 realized-risk 指标：
  - `exit_return_mean`
  - `exit_loss_5pct_rate`
  - `exit_win_rate`
  - `pre_exit_max_dd_mean`
- 保留原始 window risk：
  - `max_dd_3d_mean`
  - `bigdrop>=5%`

这样才能区分：

- “窗口里曾经下探很深”
- “退出规则实际亏了多少”

当前不建议进入 promotion gate；需要先把 exit diagnostics 补完整。
