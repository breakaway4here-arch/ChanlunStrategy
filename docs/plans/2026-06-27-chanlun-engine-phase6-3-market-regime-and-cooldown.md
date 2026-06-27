# ChanLun Engine Phase 6.3 Market Regime And Cooldown Experiment Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Test weak-trend filtering and signal cooldown after delayed-entry backtesting is available.

**Architecture:** Add opt-in experiment variants and backtests for market-regime filters and cooldown windows. Keep production unchanged until gate evidence and human approval.

**Tech Stack:** Python standard library, experiment registry, delayed-entry backtest from Phase 6.1, existing market/report data.

---

## Scope

Do:
- Add backtest-only filters for weak-trend and cooldown rules.
- Compare them against Phase 6.1 delayed-entry baselines.
- Produce JSON/Markdown reports.

Do not:
- Change production ranking or report output.
- Auto-promote experiments.

## Candidate Rules

1. Weak trend filter:
   - Drop bottom-fishing signals when market state is weak and signal lacks strong confirmation.
2. Cooldown:
   - Do not emit a new recommendation for the same code/type within N trading days.
3. Trend/range layering:
   - Use different confirmation requirements for trend market vs range market.

## Required Metrics

Compare:
- sample count
- T+1/T+3/T+5 mean
- T+3 win rate
- T+3 <= -5% rate
- 3-day max drawdown
- big-run rate
- retained ratio

## Implementation Sequence

1. Add pure backtest filters and tests.
2. Run delayed-entry + filter combinations.
3. Add the best candidate as opt-in experiment only if evidence is positive.
4. Update promotion gates if T+5 is added.

## Commit

Use separate commits for each experiment family:

```bash
git commit -m "feat: 添加弱趋势过滤回测"
git commit -m "feat: 添加信号冷却回测"
```
