# ChanLun Signal ABC Classification Backtest Result

## Scope

Plan:

- `docs/plans/2026-06-28-chanlun-signal-abc-classification.md`

Implemented scope:

- Added downstream Signal ABC classification.
- Kept `tier` backward-compatible.
- Added `category` as an additive field.
- Added A-only execution intent without live order placement.
- Kept B/C visible for diagnostics and observation.

Forbidden files checked:

- `chanlun/chan_engine.py`
- `chanlun/engine_core.py`
- `chanlun/engine_signals.py`

Result: no diff in forbidden files.

## Backtest Command

```bash
python3 scripts/backtest_recommendation_quality.py > /private/tmp/chanlun_abc_backtest.txt 2>&1
```

Data scope:

- 25 historical snapshot days from `docs/data/YYYY-MM-DD.json`
- Total picks scanned: 2842
- Total evaluated: 1706
- Skipped no kline cover: 1136

Note:

- Network fetch failed in this sandboxed run and fell back to local cache.
- The script exited successfully.

## ABC-A Execution Intent Comparison

| Version | Baseline N | A-only N | Reduction | Baseline T+3 Win | A T+3 Win | Baseline T+3 Mean | A T+3 Mean | Baseline DD Mean | A DD Mean |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| picks_pure | 1272 | 413 | 67.53% | 38.3% | 47.2% | -0.71 | 0.53 | -4.91 | -4.67 |
| picks_fusion | 434 | 88 | 79.72% | 28.8% | 51.1% | -1.52 | 1.31 | -5.38 | -4.42 |

## Readout

`picks_pure`:

- Meets the 30%-70% reduction target.
- Win rate improves by +8.9 percentage points.
- T+3 mean return improves from negative to positive.
- Drawdown mean improves slightly.

`picks_fusion`:

- Win rate, T+3 mean return, and drawdown all improve materially.
- Reduction is 79.72%, above the target upper bound of 70%.
- This is good for a conservative A layer, but stricter than the written MVP target.

## Decision Gate

Do not push until user confirms one of these:

1. Accept this stricter A-only result and push.
2. Tune the fusion-side threshold so reduction falls closer to 30%-70%, then rerun tests and backtest.

