# 2026-06-29 Fusion-only 阈值扫描结果

## 1. 原 spec 可执行性结论

`/Users/yangfan/Downloads/chanlun_fusion_only_threshold_scan_spec.md` 的方向可执行，但不能原样执行。

原因：

- `compare_chan_engine_dual.py --business-metrics` 当前只跑内存结构场景，不能产出历史收益/覆盖率指标。
- 真实收益对比必须走历史推荐快照回测。
- `drawdown_mean` 是负数，数值越接近 0 表示回撤越小。原 spec 写 `drawdown_mean <= -4.60`，但示例把 `-4.55` 当作改善，因此本轮实际按 `drawdown_mean >= -4.60` 验收。

本轮落地后的真实回测命令：

```bash
python3 scripts/run_policy_experiments.py \
  --policies fusion_strict,fusion_mid,fusion_loose \
  --business-metrics \
  --output-json /tmp/fusion_pareto_report.json \
  --output-md /tmp/fusion_pareto_report.md
```

执行环境说明：

- 当前环境无外网访问腾讯行情，日志中出现 DNS 失败。
- 回测成功走本地 cache fallback。
- `baseline_rows=434`，与前一轮 ABC 回测的 `picks_fusion All=434` 口径对齐。

## 2. 回测基线

| 基线 | 样本 | T+3 mean | T+3 win rate | drawdown mean |
|---|---:|---:|---:|---:|
| picks_fusion All | 434 | -1.52 | 28.8% | -5.38 |

## 3. Profile 结果

| Candidate | Variant | samples_before | samples_after | coverage | T+3 mean | T+3 win rate | drawdown mean | 达标 |
|---|---|---:|---:|---:|---:|---:|---:|---|
| fusion_strict | fusion_strict | 434 | 88 | 20.28% | 1.31 | 51.1% | -4.42 | 否，coverage below 25% |
| fusion_mid | fusion_mid_trend | 434 | 88 | 20.28% | 1.31 | 51.1% | -4.42 | 否，coverage below 25% |
| fusion_loose | fusion_loose_trend | 434 | 369 | 85.02% | -2.15 | 24.9% | -5.46 | 否，coverage above 35%，收益/胜率/回撤均恶化 |

内部变体扫描结论：

| Public Candidate | Internal Variant | samples_after | coverage | T+3 mean | T+3 win rate | drawdown mean |
|---|---|---:|---:|---:|---:|---:|
| fusion_mid | fusion_mid_trend | 88 | 20.28% | 1.31 | 51.1% | -4.42 |
| fusion_mid | fusion_mid_volatility | 88 | 20.28% | 1.31 | 51.1% | -4.42 |
| fusion_mid | fusion_mid_structure | 88 | 20.28% | 1.31 | 51.1% | -4.42 |
| fusion_loose | fusion_loose_trend | 369 | 85.02% | -2.15 | 24.9% | -5.46 |
| fusion_loose | fusion_loose_volatility | 88 | 20.28% | 1.31 | 51.1% | -4.42 |

## 4. Pareto Frontier

按 `coverage` 与 `T+3 mean` 两个维度计算：

```text
pareto_frontier = ["fusion_strict", "fusion_mid", "fusion_loose"]
```

说明：

- `fusion_strict` 与 `fusion_mid` 坐标完全相同，因此二者互不支配。
- `fusion_loose` 覆盖率更高但收益更差，因此也未被 strict 支配。
- Pareto 有效不代表可上线，仍需通过验收门槛。

## 5. Reject Reason Distribution

本轮新增 `reject_reason_distribution` 输出，用来解释非 A 类样本真正卡在哪个条件。

### fusion_strict

| reason | count | rejected占比 |
|---|---:|---:|
| trend_strength_below_min | 346 | 100.00% |
| missing_pivot | 53 | 15.32% |
| choppy_trend | 12 | 3.47% |

样本拆解：

| trend_strength | count |
|---|---:|
| 1.0 | 346 |

| signal type | count |
|---|---:|
| 底背驰候选 | 290 |
| 强势启动候选 | 53 |
| 中枢低吸候选 | 3 |

### fusion_mid

`fusion_mid` 三个单项放宽变体结果一致，最终代表变体为 `fusion_mid_trend`。

| reason | count | rejected占比 |
|---|---:|---:|
| trend_strength_below_min | 346 | 100.00% |
| missing_pivot | 53 | 15.32% |
| choppy_trend | 12 | 3.47% |

内部变体：

| variant | A样本 | rejected | top reject reason |
|---|---:|---:|---|
| fusion_mid_trend | 88 | 346 | trend_strength_below_min |
| fusion_mid_volatility | 88 | 346 | trend_strength_below_min |
| fusion_mid_structure | 88 | 346 | trend_strength_below_min |

瓶颈判断：

- strict 的门槛是 `trend_strength >= 2.0`。
- mid_trend 放宽到 `trend_strength >= 1.5` 后，仍然没有增加 A 类样本。
- 所有 rejected 样本的 `trend_strength` 都是 `1.0`。
- 因此真正瓶颈不是波动率，也不是结构完整性，而是 `trend_strength=1.0` 这一大组信号。
- 这组信号主要来自 `底背驰候选`，直接放到 loose 后覆盖率会暴增但收益转负，所以不能简单把 trend_strength 放宽到 1.0。

## 6. 选择结论

```json
{
  "selected": "fusion_strict",
  "reason": "no profile met all target criteria",
  "rejected": {
    "fusion_mid": "coverage below 25%",
    "fusion_loose": "coverage above 35%, T+3 mean <= 0.80, T+3 win rate < 49%, drawdown worse than -4.60"
  }
}
```

结论：

- 本轮没有找到 `25%~35% coverage` 且收益/胜率/回撤同时达标的放宽版本。
- `fusion_mid` 没有带来额外覆盖，等价于 strict。
- `fusion_loose` 虽然覆盖率提升到 85.02%，但 T+3 mean 从 1.31 降到 -2.15，胜率从 51.1% 降到 24.9%，不可用。
- 因此保持当前 `fusion_strict`，不升级默认阈值。

## 7. 验证结果

已通过：

```bash
python3 -m unittest tests.test_signal_quality_classifier tests.test_policy_experiment_metrics tests.test_policy_experiment_runner_script
python3 -m py_compile chanlun/signal_quality_classifier.py chanlun/policy_experiment_metrics.py scripts/run_policy_experiments.py
python3 scripts/run_policy_experiments.py --policies fusion_strict,fusion_mid,fusion_loose --business-metrics --output-json /tmp/fusion_pareto_report.json --output-md /tmp/fusion_pareto_report.md
```

待最终提交前继续执行：

```bash
python3 -m unittest discover -s tests
git diff --check
```
