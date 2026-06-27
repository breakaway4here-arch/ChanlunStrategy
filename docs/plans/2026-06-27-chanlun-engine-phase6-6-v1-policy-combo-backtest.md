# ChanLun Engine Phase 6.6 V1 Policy Combo Backtest Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在 `signal_delay1_by_type_guard` v1 的基础上，回测“信号冷却 + 弱势/震荡代理过滤”的组合收益，找出是否有比 v1 更稳定的下一阶段 candidate。

**Architecture:** 新增一个纯回测 policy 层，读取历史 snapshot picks，先应用 v1 延迟确认逻辑，再叠加 cooldown / bottom-quality guard。它只输出 JSON/Markdown 指标，不改 `analyze()`、不改 provider registry、不改生产报告。

**Tech Stack:** Python standard library, `chanlun.historical_experiment_metrics`, `chanlun.backtest_execution`, `chanlun.backtest_metrics`, `scripts.backtest_recommendation_quality.iter_snapshot_picks`, `unittest`.

---

## Current Evidence

最新回测结论见：

- `docs/plans/2026-06-27-chanlun-engine-delay-confirmation-backtest-latest.md`

当前最优基线：

- `signal_delay1_by_type_guard`
- legacy T+3 均值：`-0.92%`
- v1 T+3 均值：`0.03%`
- legacy T+3 胜率：`35.9%`
- v1 T+3 胜率：`44.5%`
- legacy T+3 跌超 5%：`23.7%`
- v1 T+3 跌超 5%：`18.2%`

快照字段分布：

- total picks：`2842`
- `market_trend`: 空字符串 `2801`，`强趋势` `41`
- `signal_tier`: `candidate` `2751`，`None` `91`
- `best_buy_point.type`: `强势启动候选` `1411`，`底背驰候选` `1307`

因此 Phase 6.6 不直接依赖 `market_trend` 做弱趋势过滤；它先用 `type + confirmations + distance_from_reference_pct + 重复推荐间隔` 做可解释代理。

## Scope

Do:

- 新增 backtest-only policy experiment runner。
- 以 v1 为 baseline，输出 policy 与 v1 的收益对比。
- 支持多 policy 一次运行。
- 输出 JSON 和 Markdown。
- 增加单元测试和脚本测试。

Do not:

- 不改 `analyze()`。
- 不改生产推荐列表。
- 不把 policy 注册为正式 engine experiment。
- 不推广 v2。

## Policy Definitions

### baseline

`delay1_v1`

- 先用 `signal_delay1_by_type_guard` 的 drop 逻辑过滤。
- entry mode 复用 `entry_mode_for_pick("signal_delay1_by_type_guard", pick)`。
- 作为所有 policy 的直接对照基线。

### cooldown

`delay1_v1_cooldown3`

- 先应用 v1。
- 对同一个 `(code, best_buy_point.type)`，如果距离上一次 accepted snapshot 少于 3 个 snapshot days，则过滤。
- 同一天重复出现的 pure/fusion duplicate 视为冷却命中，过滤后出现项。

`delay1_v1_cooldown5`

- 同上，窗口改为 5 个 snapshot days。

### bottom quality guard

`delay1_v1_bottom_quality_guard`

仅作用于 `底背驰候选`：

- 缺少 `关键位不破`：过滤。
- `distance_from_reference_pct` 缺失：过滤。
- `distance_from_reference_pct > 6`：过滤。
- confirmations 同时缺少 `30min底分型` 和 `止跌结构`：过滤。

不作用于：

- `强势启动候选`
- `一买` / `二买` / `三买`
- `中枢低吸候选`

### combo

`delay1_v1_cooldown3_bottom_quality`

- 先应用 v1。
- 再应用 `bottom_quality_guard`。
- 最后应用 `cooldown3`。

## Required Metrics

每个 policy 输出：

- coverage
  - `snapshot_days`
  - `picks_seen`
  - `baseline_evaluated`
  - `policy_evaluated`
  - `baseline_filtered`
  - `policy_filtered`
  - `policy_filtered_by_reason`
  - `retained_ratio_pct`
- return metrics
  - `n`
  - `t1_mean`
  - `t3_mean`
  - `t3_win_rate`
  - `t3_loss_5pct_rate`
  - `max_dd_3d_mean`
  - `big_drop_5pct_rate`
  - `big_run_5pct_rate`
- delta vs `delay1_v1`
  - `t3_mean_delta`
  - `t3_win_rate_delta`
  - `t3_loss_5pct_rate_delta`
  - `big_drop_5pct_rate_delta`

## Files

Create:

- `chanlun/policy_experiment_metrics.py`
- `scripts/run_policy_experiments.py`
- `tests/test_policy_experiment_metrics.py`
- `tests/test_policy_experiment_runner_script.py`

Modify:

- No production module required.
- Only update existing files if imports or packaging require it.

## Task 1: Add Policy Experiment Metrics Module

**Files:**

- Create: `chanlun/policy_experiment_metrics.py`
- Test: `tests/test_policy_experiment_metrics.py`

**Step 1: Write failing tests**

Add tests for:

1. `list_policy_experiments()` includes:
   - `delay1_v1`
   - `delay1_v1_cooldown3`
   - `delay1_v1_cooldown5`
   - `delay1_v1_bottom_quality_guard`
   - `delay1_v1_cooldown3_bottom_quality`
2. bottom-quality guard filters:
   - missing `关键位不破`
   - missing distance
   - distance `> 6`
   - missing both `30min底分型` and `止跌结构`
3. bottom-quality guard keeps:
   - `底背驰候选` with `关键位不破`, distance `<= 6`, and `30min底分型`
   - `底背驰候选` with `关键位不破`, distance `<= 6`, and `止跌结构`
   - `强势启动候选`
4. cooldown filters same `(code, type)` within the configured snapshot-day window.
5. `run_policy_experiment_metrics(["delay1_v1_cooldown3"])` returns baseline and policy summaries.

Run:

```bash
python3 -m unittest tests.test_policy_experiment_metrics
```

Expected before implementation: fail because module is missing.

**Step 2: Implement module**

Implement:

```python
POLICY_EXPERIMENTS = {
    "delay1_v1": ...,
    "delay1_v1_cooldown3": ...,
    "delay1_v1_cooldown5": ...,
    "delay1_v1_bottom_quality_guard": ...,
    "delay1_v1_cooldown3_bottom_quality": ...,
}
```

Required public functions:

```python
def list_policy_experiments() -> list:
    ...

def supports_policy_experiment(name: str) -> bool:
    ...

def should_filter_for_policy(name: str, pick: dict, state: dict) -> tuple:
    """Return (filtered: bool, reason: str)."""
    ...

def run_policy_experiment_metrics(policy_names=None) -> dict:
    ...
```

Implementation details:

- Use `iter_snapshot_picks()` for data.
- Sort rows by `(snap_date, version, code)` before applying cooldown state.
- Use `should_drop_pick_for_experiment("signal_delay1_by_type_guard", pick)` to build the v1 baseline.
- Use `entry_mode_for_pick("signal_delay1_by_type_guard", pick)` for v1/policy entry modes.
- Use `_normalize_kline`, `_fetch_daily_kline_cached`, and `_evaluate_pick_sample` from `chanlun.historical_experiment_metrics` to keep behavior consistent.
- Use `summarize_return_samples` for return summaries.
- Keep exceptions local to each pick like existing historical metrics code: bad kline means skipped, not crash.
- Track policy reason counts with a plain dict or `collections.Counter`.

**Step 3: Run tests**

```bash
python3 -m unittest tests.test_policy_experiment_metrics
```

Expected: pass.

## Task 2: Add CLI Runner

**Files:**

- Create: `scripts/run_policy_experiments.py`
- Test: `tests/test_policy_experiment_runner_script.py`

**Step 1: Write failing script tests**

Test cases:

1. Unknown policy returns non-zero and prints `unknown policy`.
2. Valid policy writes JSON and Markdown.
3. `--policies delay1_v1_cooldown3,delay1_v1_bottom_quality_guard` runs both.

Run:

```bash
python3 -m unittest tests.test_policy_experiment_runner_script
```

Expected before implementation: fail because script is missing.

**Step 2: Implement script**

CLI:

```bash
python3 scripts/run_policy_experiments.py \
  --policies delay1_v1_cooldown3,delay1_v1_bottom_quality_guard,delay1_v1_cooldown3_bottom_quality \
  --output-json /tmp/phase6_6_policy_metrics.json \
  --output-md /tmp/phase6_6_policy_metrics.md
```

Markdown must include:

- generated time
- policy table
- baseline row
- policy row
- delta columns
- filtered-by-reason summary

**Step 3: Run tests**

```bash
python3 -m unittest tests.test_policy_experiment_runner_script
```

Expected: pass.

## Task 3: Run Full Verification

Run:

```bash
python3 -m py_compile \
  chanlun/policy_experiment_metrics.py \
  scripts/run_policy_experiments.py

python3 -m unittest \
  tests.test_policy_experiment_metrics \
  tests.test_policy_experiment_runner_script \
  tests.test_historical_experiment_metrics \
  tests.test_engine_experiment_runner_script

python3 -m unittest discover -s tests

git diff --check
```

Expected:

- targeted tests pass
- full suite passes
- diff check has no output

## Task 4: Run Historical Backtest

Run:

```bash
python3 scripts/run_policy_experiments.py \
  --policies delay1_v1,delay1_v1_cooldown3,delay1_v1_cooldown5,delay1_v1_bottom_quality_guard,delay1_v1_cooldown3_bottom_quality \
  --output-json /tmp/phase6_6_policy_metrics.json \
  --output-md /tmp/phase6_6_policy_metrics.md
```

Expected:

- command exits `0`
- JSON and Markdown exist
- each policy has baseline and policy metrics
- no policy should be promoted solely from this run if remote kline uses cache fallback heavily

## Task 5: Result Document

After backtest, create:

- `docs/plans/2026-06-27-chanlun-engine-phase6-6-v1-policy-combo-backtest-result.md`

It must include:

- commands run
- test result summary
- backtest table
- best policy if any
- explicit decision:
  - promote to next experiment
  - keep as backtest-only
  - reject
- data caveat about cache fallback if seen

## Acceptance Criteria

- `analyze()` behavior unchanged.
- No production report/ranking changes.
- New policy runner can compare v1 baseline with multiple policy variants.
- Unit tests cover policy filtering and cooldown state.
- Full test suite passes.
- Real historical backtest command completes.
- Result MD is written and committed.

## Commit Plan

Plan commit:

```bash
git add -f docs/plans/2026-06-27-chanlun-engine-phase6-6-v1-policy-combo-backtest.md
git commit -m "docs: 添加v1组合策略回测方案"
```

Implementation commit:

```bash
git add chanlun/policy_experiment_metrics.py scripts/run_policy_experiments.py tests/test_policy_experiment_metrics.py tests/test_policy_experiment_runner_script.py
git commit -m "feat: 添加v1组合策略回测"
```

Result commit:

```bash
git add -f docs/plans/2026-06-27-chanlun-engine-phase6-6-v1-policy-combo-backtest-result.md
git commit -m "docs: 添加v1组合策略回测结果"
```
