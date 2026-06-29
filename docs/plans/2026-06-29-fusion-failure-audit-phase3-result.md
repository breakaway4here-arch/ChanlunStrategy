# 2026-06-29 Fusion Failure Audit Phase 3 Result

## Goal

Analyze failed A-class samples for the `fusion_strict_startup_rescue_v1` fusion profile and output candidate downgrade/filter conditions for phase 4 design.

## Backtest Command

```bash
python3 scripts/run_policy_experiments.py \
  --policies fusion_strict_startup_rescue_v1 \
  --business-metrics \
  --output-json /tmp/fusion_failure_audit_phase3_report.json \
  --output-md /tmp/fusion_failure_audit_phase3_report.md
```

## Result

| Metric | Value |
|---|---:|
| samples | 123 |
| failed_samples | 55 |
| failure_rate_pct | 44.72 |
| severe_drawdown_samples | 42 |
| severe_drawdown_rate_pct | 34.15 |
| candidate | fusion_strict_startup_rescue_v1 |
| accepted | True |
| baseline_samples | 434 |

## Top Failure Buckets

| Bucket | Failed Samples |
|---|---:|
| expected_horizon:T+3 | 43 |
| quality_tier:A | 43 |
| market_env:weak | 31 |
| market_env:strong | 24 |
| expected_horizon:T+1 | 12 |
| quality_tier:A- | 12 |
| signal_type:强势启动候选 | 55 |

## Candidate Conditions

| Condition | Failed Samples | Failure Rate |
|---|---:|---:|
| expected_horizon=T+3 | 43 | 48.86 |
| market_env=strong | 24 | 50.00 |
| quality_tier=A | 43 | 48.86 |

## Conclusion

- No execution semantics changed in this phase.
- Candidate conditions are audit signals only and should be used for phase 4 experimentation only.
- `signal_type=强势启动候选` was not retained as a candidate condition because its failure rate equals the overall failure rate; it describes the current accepted sample universe rather than a differentiating weakness.
