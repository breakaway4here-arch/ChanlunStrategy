# ChanLun Engine Phase 6.6 v1 Policy Combo Backtest Result

## 结论

Phase 6.6 已完成实现、测试和真实历史回测。

本轮结论是：这些策略都只能继续留在 backtest-only 实验层，暂不建议升入 production `analyze()`。

最值得继续挖的是 `delay1_v1_bottom_quality_guard`，它在当前样本上让 T+3 均值从 `0.03` 提升到 `0.16`，胜率从 `44.5%` 提升到 `45.9%`。但它同时让 `T+3 <= -5%` 比例从 `18.2%` 升到 `18.7%`，`big_drop_5pct_rate` 从 `36.3%` 升到 `36.9%`，尾部风险没有改善，所以不能直接上线。

`cooldown3` / `cooldown5` 当前定义不成立：交易数下降约 28% 到 29%，但 T+3 均值和尾部风险都变差。组合策略虽然胜率最高，但过滤过重且尾部风险继续变差。

## 本轮代码范围

- 新增 `chanlun/policy_experiment_metrics.py`
  - 在 `signal_delay1_by_type_guard` v1 基线之上运行 policy-only 实验。
  - 支持 cooldown 和底背驰质量过滤。
  - 保证 baseline 只统计 v1 真正保留的样本。
- 新增 `scripts/run_policy_experiments.py`
  - 支持多 policy 批量回测。
  - 输出 JSON 和 Markdown。
- 新增测试：
  - `tests/test_policy_experiment_metrics.py`
  - `tests/test_policy_experiment_runner_script.py`

## 关键修正

小兵初版实现里有一个重要问题：baseline 会把 v1 本应过滤的样本也计入，导致 policy delta 参考基线不纯。

已修正为：

- 先执行 `signal_delay1_by_type_guard` v1 过滤。
- `baseline_filtered` 记录 v1 本身过滤的样本数。
- `policy_filtered` 只记录当前 policy 相对 v1 的额外过滤。
- 新增回归测试覆盖该行为。

## 测试结果

```bash
python3 -m unittest tests.test_policy_experiment_metrics tests.test_policy_experiment_runner_script
```

结果：`Ran 9 tests in 0.006s OK`

```bash
python3 -m py_compile chanlun/policy_experiment_metrics.py scripts/run_policy_experiments.py
```

结果：通过。

```bash
python3 -m unittest tests.test_policy_experiment_metrics tests.test_policy_experiment_runner_script tests.test_historical_experiment_metrics tests.test_engine_experiment_runner_script
```

结果：`Ran 26 tests in 1.427s OK`

```bash
python3 -m unittest discover -s tests
```

结果：`Ran 452 tests in 4.584s OK`

## 真实回测命令

```bash
python3 scripts/run_policy_experiments.py \
  --policies delay1_v1,delay1_v1_cooldown3,delay1_v1_cooldown5,delay1_v1_bottom_quality_guard,delay1_v1_cooldown3_bottom_quality \
  --output-json /tmp/phase6_6_policy_metrics.json \
  --output-md /tmp/phase6_6_policy_metrics.md
```

结果文件：

- `/tmp/phase6_6_policy_metrics.json`
- `/tmp/phase6_6_policy_metrics.md`

注意：执行过程中存在多只股票远端日线获取失败并回退本地缓存的日志，形如 `[CACHE FALLBACK] day <code> remote failed, using cache`。因此这次回测可用于策略方向判断，但后续若要决定 production 晋级，需要在数据源稳定或缓存版本固定后复跑。

## 回测样本

- `generated_at`: `2026-06-27T20:21:25.358146`
- `snapshot_rows`: `2842`
- `baseline_policy`: `signal_delay1_by_type_guard`
- `baseline_evaluated`: `1287`
- `baseline_filtered`: `805`
- baseline 指标：
  - `t1_mean`: `0.58`
  - `t3_mean`: `0.03`
  - `t3_win_rate`: `44.5`
  - `t3_loss_5pct_rate`: `18.2`
  - `max_dd_3d_mean`: `-4.46`
  - `big_drop_5pct_rate`: `36.3`
  - `big_run_5pct_rate`: `38.0`

## Policy 对比

| Policy | n | Filtered | Retained % | T+1 | T+3 | ΔT+3 | T+3 Win | ΔWin | Loss <= -5% | ΔLoss5 | Big Drop | ΔBigDrop | Filter Reason |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| delay1_v1 | 1287 | 0 | 100.00 | 0.58 | 0.03 | 0.00 | 44.5 | 0.0 | 18.2 | 0.0 | 36.3 | 0.0 | - |
| delay1_v1_cooldown3 | 929 | 358 | 72.18 | 0.52 | -0.07 | -0.10 | 45.4 | +0.9 | 19.9 | +1.7 | 37.1 | +0.8 | cooldown:358 |
| delay1_v1_cooldown5 | 911 | 376 | 70.78 | 0.53 | -0.05 | -0.08 | 45.8 | +1.3 | 19.9 | +1.7 | 37.1 | +0.8 | cooldown:376 |
| delay1_v1_bottom_quality_guard | 1101 | 186 | 85.55 | 0.66 | 0.16 | +0.13 | 45.9 | +1.4 | 18.7 | +0.5 | 36.9 | +0.6 | bottom_quality_guard:186 |
| delay1_v1_cooldown3_bottom_quality | 819 | 468 | 63.64 | 0.56 | 0.03 | 0.00 | 46.8 | +2.3 | 20.3 | +2.1 | 37.7 | +1.4 | bottom_quality_guard:186, cooldown:282 |

## 策略判断

### delay1_v1

这是 v1 baseline，对照组，无额外过滤。

### delay1_v1_cooldown3

不建议继续当前定义：

- 样本减少到 `72.18%`
- T+3 均值下降 `0.10`
- `T+3 <= -5%` 增加 `1.7`
- `big_drop_5pct_rate` 增加 `0.8`

### delay1_v1_cooldown5

不建议继续当前定义：

- 样本减少到 `70.78%`
- T+3 均值下降 `0.08`
- `T+3 <= -5%` 增加 `1.7`
- `big_drop_5pct_rate` 增加 `0.8`

### delay1_v1_bottom_quality_guard

建议保留为下一轮优化主线，但暂不上线：

- T+3 均值提升 `0.13`
- T+3 胜率提升 `1.4`
- 保留率 `85.55%`，过滤力度可接受
- 但尾部风险没有下降，说明过滤条件更像是提升均值，而不是控制亏损

### delay1_v1_cooldown3_bottom_quality

不建议继续当前组合：

- 保留率只有 `63.64%`
- T+3 均值没有改善
- 胜率提升来自过滤过重，不是质量显著改善
- `T+3 <= -5%` 和 `big_drop_5pct_rate` 都明显变差

## 下一步建议

Phase 6.7 不应继续扩大 cooldown，而应围绕底背驰质量过滤做原因拆解：

1. 导出 `bottom_quality_guard` 被过滤样本和保留样本的收益分布。
2. 对比被过滤样本里到底过滤掉了多少亏损、多少盈利。
3. 把底背驰过滤拆成可独立开关：
   - `missing_key_protection`
   - `missing_distance`
   - `distance_gt_6`
   - `missing_bottom_shape_or_stop_drop`
4. 用 reason-level 回测决定哪些子规则保留。

当前 cooldown 方向需要重新定义后再测，例如只过滤同一代码同一信号的低质量重复，而不是简单 N 日窗口过滤。
