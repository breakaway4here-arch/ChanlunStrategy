# ChanLun Engine Phase 6.1 延迟入场回测结果

日期: 2026-06-27

## 结论

信号延迟 1 根 K 线有统计价值，但不能作为全局无脑规则。

- `picks_pure`: `delay1_open` 优于即时收盘入场，收益、胜率、回撤和大跌率都有改善。
- `picks_fusion`: `delay1_close` 风险改善最明显，但 T+3 均值仍为负。
- `底背驰候选`: 延迟能明显降噪，但整体仍偏弱，后续应优先结合 P0 过滤或趋势分层。
- `强势启动候选`: `delay1_open` 略优，`delay1_close` 会损失启动收益，不宜全局套用。

因此 Phase 6.2 不应直接把延迟写入 production `analyze()`，而应做 candidate 插件实验:

1. 对 `底背驰候选` 优先试 `delay1_close` 确认。
2. 对 `强势启动候选` 最多试 `delay1_open`，避免等到收盘。
3. 继续用 dual/business metrics 评估，不影响 production。

## 回测命令

```bash
python3 scripts/backtest_delayed_entry.py \
  --output-json /tmp/chanlun_delayed_entry_backtest_20260627.json
```

## 样本覆盖

```json
{
  "snapshot_days": 24,
  "picks_seen": 2842,
  "evaluated_by_mode": {
    "immediate_close": 1706,
    "delay1_open": 1706,
    "delay1_close": 1695
  },
  "skipped": 1,
  "skipped_no_code": 0,
  "skipped_no_kline": 1,
  "not_evaluable_by_mode": {
    "immediate_close": 1135,
    "delay1_open": 1135,
    "delay1_close": 1146
  }
}
```

说明:

- `skipped` 是 pick 级别缺数据。
- `not_evaluable_by_mode` 是有 K 线但对应入场模式无法评估，常见原因是快照日不是交易日或 forward bars 不足。

## Overall 指标

### picks_pure

| mode | n | T+1 mean | T+3 mean | T+3 win | T+3 loss5 | max dd 3d | big drop | big run |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| immediate_close | 1272 | -0.12 | -0.71 | 38.3% | 22.8% | -4.91 | 42.7% | 31.8% |
| delay1_open | 1272 | 0.25 | -0.35 | 40.9% | 19.6% | -4.56 | 37.5% | 34.8% |
| delay1_close | 1263 | -0.19 | -1.01 | 37.5% | 25.9% | -5.09 | 45.1% | 32.4% |

判断: pure 路径优先考虑 `delay1_open`，不建议 `delay1_close`。

### picks_fusion

| mode | n | T+1 mean | T+3 mean | T+3 win | T+3 loss5 | max dd 3d | big drop | big run |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| immediate_close | 434 | -0.75 | -1.52 | 28.8% | 26.3% | -5.38 | 49.3% | 27.4% |
| delay1_open | 434 | -0.53 | -1.31 | 30.0% | 23.7% | -5.17 | 44.7% | 29.7% |
| delay1_close | 432 | 0.02 | -0.95 | 33.3% | 21.5% | -4.90 | 43.1% | 30.6% |

判断: fusion 路径延迟确认有效，但整体仍未转正，需要和弱信号过滤组合。

## Fusion 分类型

### 底背驰候选

| mode | n | T+1 mean | T+3 mean | T+3 win | T+3 loss5 | max dd 3d |
|---|---:|---:|---:|---:|---:|---:|
| immediate_close | 290 | -1.69 | -3.27 | 16.6% | 31.7% | -5.81 |
| delay1_open | 290 | -1.40 | -2.99 | 17.2% | 29.0% | -5.54 |
| delay1_close | 289 | 0.04 | -2.12 | 25.3% | 23.5% | -4.84 |

判断: `delay1_close` 能显著降噪，但底背驰候选单独仍不够，应叠加 P0 距离过滤和趋势分层。

### 强势启动候选

| mode | n | T+1 mean | T+3 mean | T+3 win | T+3 loss5 | max dd 3d |
|---|---:|---:|---:|---:|---:|---:|
| immediate_close | 141 | 1.18 | 2.16 | 54.6% | 14.9% | -4.47 |
| delay1_open | 141 | 1.26 | 2.20 | 56.7% | 12.8% | -4.39 |
| delay1_close | 140 | -0.03 | 1.43 | 49.3% | 17.1% | -4.97 |

判断: 强势启动可试 `delay1_open`，但不应等到次日收盘。

## Phase 6.1 代码验收

本阶段只新增离线回测能力，不改变 production `analyze()`。

新增/调整:

- `chanlun/backtest_execution.py`: 统一 forward-return 计算，支持 `immediate_close` / `delay1_open` / `delay1_close`。
- `scripts/backtest_recommendation_quality.py`: 复用统一计算器，保持 legacy 即时收盘口径。
- `scripts/backtest_delayed_entry.py`: 输出三种入场模式对比 JSON，内置 per-code K 线缓存。
- `tests/test_backtest_execution.py`: 覆盖三种入场模式。
- `tests/test_backtest_delayed_entry_script.py`: 覆盖 JSON 输出、numpy K 线、缓存和 skipped 口径。

验证:

```bash
python3 -m py_compile chanlun/backtest_execution.py scripts/backtest_delayed_entry.py scripts/backtest_recommendation_quality.py
python3 -m unittest tests.test_backtest_execution tests.test_backtest_delayed_entry_script -v
python3 -m unittest discover tests
python3 scripts/backtest_delayed_entry.py --output-json /tmp/chanlun_delayed_entry_backtest_20260627.json
```

结果:

- targeted tests: `Ran 9 tests ... OK`
- full tests: `Ran 413 tests ... OK`
- full delayed-entry backtest: exit code `0`

## 下一阶段建议

Phase 6.2 做 candidate 插件，不动 production:

```text
delayed_entry_candidate_v1:
  底背驰候选 -> delay1_close confirmation
  强势启动候选 -> delay1_open confirmation
  其他信号 -> immediate_close baseline
```

验收门槛:

- Fusion T+3 mean 继续改善。
- Fusion T+3 win rate 不低于 Phase 6.1 `delay1_close`。
- Fusion loss5 和 big_drop 继续下降。
- 强势启动候选不得被 `delay1_close` 误伤。
