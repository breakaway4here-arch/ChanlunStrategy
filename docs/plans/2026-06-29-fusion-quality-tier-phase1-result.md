# 2026-06-29 Fusion Quality Tier Phase 1 Result

## Goal

Add A+/A/A- tier metadata for `fusion_strict_startup_rescue_v1` without changing A/B/C execution semantics.

## Backtest Command

```bash
python3 scripts/run_policy_experiments.py \
  --policies fusion_strict_startup_rescue_v1 \
  --business-metrics \
  --output-json /tmp/fusion_quality_tier_phase1_report.json \
  --output-md /tmp/fusion_quality_tier_phase1_report.md
```

## Result

- Baseline samples: `434`
- `fusion_strict_startup_rescue_v1` post-filter samples: `123`
- Coverage: `0.2834` (`28.34%`)
- T+3 mean: `2.28`
- T+3 win rate: `55.3`
- Max 3D drawdown mean: `-4.23`

| Tier | Count |
| --- | ---: |
| A+ | 0 |
| A | 88 |
| A- | 35 |

## Conclusion

- No execution policy branch changed; only A-class signals carry extra `quality_tier` and `quality_tier_reasons` fields.
- Existing behavior for sample counts/ranking remains unchanged for `fusion_strict_startup_rescue_v1` in this phase.
- `A+` count is currently `0`, which means the live snapshot set has no A-class sample satisfying the stricter `trend_strength >= 2.5 + low volatility + complete structure` rule. This is acceptable for Phase 1 because the tiering layer is additive and will be calibrated by later horizon/failure analysis.
