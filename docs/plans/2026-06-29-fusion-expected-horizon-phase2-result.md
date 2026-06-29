# 2026-06-29 Fusion Expected Horizon Phase 2 Result

## Goal

为 A 类信号补充 `expected_horizon` 元数据（`T+1`/`T+3`/`T+5`）并在 fusion policy experiment 输出里增加
`expected_horizon_distribution`，不改动执行/推荐/降级逻辑。

## Backtest Command

```bash
python3 scripts/run_policy_experiments.py \
  --policies fusion_strict_startup_rescue_v1 \
  --business-metrics \
  --output-json /tmp/fusion_expected_horizon_phase2_report.json \
  --output-md /tmp/fusion_expected_horizon_phase2_report.md
```

## Result

- `sample count`: 123
- `expected_horizon_distribution`:

| Horizon | Count |
|---|---:|
| T+1 | 35 |
| T+3 | 88 |
| T+5 | 0 |

## Conclusion

- 执行样本数与预期对齐（`123`）。
- A 类信号已带出固定仓位周期 metadata；执行和过滤语义保持不变。
- 该结果文件用于下一阶段的回归与告警复盘。
