# 缠论候选覆盖率优化 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在不放松日线正式买点定义的前提下，让“日线结构参考 + 30min 次级别确认”真正产出可解释的候选股，避免 2026-05-26 这种有 63 个日线信号但最终 0 只入选的结果。

**Architecture:** 保持正式买点链路不变：`分型 -> 笔 -> 线段 -> 中枢 -> 背驰 -> 一买/二买/三买` 仍是唯一 formal 来源。本次只新增“参考信号进入候选池”的门控层：日线 swing/reference 先通过位置保护成为 candidate seed，再经过 30min 确认升级为 candidate，最终报告明确区分 formal、candidate、watch/reference。所有新增放宽必须有诊断和 QA 约束，不能把 raw reference 直接推荐。

**Tech Stack:** Python 3, `unittest`, existing `chanlun/*` modules, existing `run.py` batch pipeline, existing static report under `docs/`.

---

## 1. 当前问题与边界

### 1.1 现状证据

以 2026-05-26 最新 QA 为基准：

```text
daily_scan.total = 224
daily_scan.base_pass = 117
daily_scan.with_buy_points = 63
daily_scan.formal_count = 0
daily_scan.upgradeable_count = 2
daily_scan.reference_only_count = 61

sublevel_upgrade.requested_30min = 2
sublevel_upgrade.fetched_30min = 2
sublevel_upgrade.candidate_upgraded = 0
final pure = 0
final fusion = 0
```

结论：现在不是 `>75 分全保留，不足 20 补齐` 这类最终过滤导致 0，而是候选入口过窄。63 个日线信号里只有 2 个进入 30min 检查，61 个 reference-only 被提前挡掉，30min 根本没有机会做次级别进化。

### 1.2.1 规则预验证结果

在改正式代码前，已用临时脚本按本 spec 的核心规则对 2026-05-26 实时行情做离线模拟。注意：本次东方财富板块资金接口超时，程序走 fallback 板块，股票池与上一次正式报告的 224 只不完全一致；因此该验证用于判断规则机制是否有效，不作为最终收益或固定数量承诺。

模拟结果：

```text
日线股票池: 384
base_pass: 225
with_buy_points: 137
type_counts:
  swing底背驰参考: 137
  中枢震荡低吸参考: 3

existing_upgradeable_stocks: 3
swing_position_seeds: 95
30min targets: 96
30min fetched: 96

upgraded_count: 10
drops:
  no_confirm_无: 27
  no_confirm_弱: 58
  existing_no_confirm_弱: 3
```

通过 30min 确认的候选样例：

```text
605088 冠盛股份    底背驰候选 中  底分型+MACD金叉, 关键位不破
300695 兆丰股份    底背驰候选 中  底分型+MACD金叉, 关键位不破
603201 常润股份    底背驰候选 中  关键位不破, EMA5收复
605255 天普股份    底背驰候选 中  关键位不破, EMA5收复
603117 万林物流    底背驰候选 中  关键位不破, EMA5收复
002800 天顺股份    底背驰候选 中  底分型+MACD金叉, 关键位不破
002769 普路通      底背驰候选 中  底分型+MACD金叉, EMA5收复
002627 三峡旅游    底背驰候选 中  底分型+MACD金叉, 关键位不破, EMA5收复, 止跌结构
300269 联建光电    底背驰候选 中  底分型+MACD金叉, 关键位不破
002316 亚联发展    底背驰候选 中  关键位不破, EMA5收复, 止跌结构
```

验证结论：

1. 规则能有效扩大候选池：从原来的 2-3 只 30min target 扩大到约 96 只。
2. 规则不会全放水：95 个 swing seed 里只有 10 个通过 30min 中确认，58 个只有弱确认，27 个无确认。
3. 仍需要强 QA：候选数量不是硬目标，关键是每只必须有日线 seed 原因和 30min 确认原因。
4. 发现额外风险：仅 `ST` 过滤不够，模拟样例出现过名称含 `退市` 的股票，因此本 spec 增加退市/风险名称过滤。

### 1.3 本次要解决的问题

1. 扩大日线结构池：允许部分 `swing底背驰参考` 在满足“日线位置保护”时进入 30min 待确认池。
2. 放宽 30min 中等确认：除了“底分型 + MACD 金叉 + 关键位不破”，还应支持实盘常见的止跌确认组合。
3. 增强诊断：必须看清每类信号从日线到 30min 到最终推荐的流失原因。
4. 保持可解释：最终 HTML 不能把候选说成正式买点，必须明确 formal / candidate / watch。

### 1.4 非目标

1. 不修改正式 `一买/二买/三买` 判定标准。
2. 不把 `swing底背驰参考` 直接当推荐。
3. 不恢复固定 TopN 补齐。
4. 不用“为了选出股票”绕过 30min 确认。
5. 不引入未来函数，不使用当日之后的数据。

---

## 2. 目标行为

### 2.1 信号分层

保留现有分层，并新增 seed 层：

```python
FORMAL_TYPES = {"一买", "二买", "三买"}

UPGRADEABLE_REFERENCE_TYPES = {
    "二买待确认",
    "盘整背驰参考",
    "中枢震荡低吸参考",
}

REFERENCE_ONLY_TYPES = {
    "swing底背驰参考",
}

CANDIDATE_SEED_TYPES = {
    "swing底背驰候选种子",
}

CANDIDATE_TYPES = {
    "二买候选",
    "三买候选",
    "盘整低吸候选",
    "中枢低吸候选",
    "底背驰候选",
}

BLOCKED_TYPES = {
    "三买已错过",
    "类二买",
}
```

规则：

1. `FORMAL_TYPES` 可直接推荐，但可附加 30min 共振信息。
2. `UPGRADEABLE_REFERENCE_TYPES` 仍需 30min 强/中确认后升级为候选。
3. `swing底背驰参考` 不能直接推荐。
4. `swing底背驰参考` 只有通过日线位置保护后，才能生成内部 seed：`swing底背驰候选种子`。
5. `swing底背驰候选种子` 不能出现在最终 `buy_points`，只能经 30min 强/中确认升级为 `底背驰候选`。
6. `BLOCKED_TYPES` 永远不能推荐，也不能升级。

### 2.2 推荐输出允许类型

最终 `stock["buy_points"]` 只允许：

```python
ALLOWED_RECOMMENDABLE_TYPES = {
    "一买", "二买", "三买",
    "二买候选", "三买候选", "盘整低吸候选", "中枢低吸候选", "底背驰候选",
}
```

最终 `stock["best_buy_point"]` 也只允许这些类型。

禁止出现在最终推荐里的类型：

```python
FORBIDDEN_RECOMMENDABLE_TYPES = {
    "二买待确认",
    "盘整背驰参考",
    "中枢震荡低吸参考",
    "swing底背驰参考",
    "swing底背驰候选种子",
    "三买已错过",
    "类二买",
}
```

---

## 3. 实现任务

### Task 1: 扩展信号策略层

**Files:**

- Modify: `chanlun/signal_policy.py`
- Test: `tests/test_signal_policy.py`

**Step 1: 写失败测试**

新增测试：

```python
from chanlun.signal_policy import (
    infer_signal_tier,
    is_candidate_seed,
    is_recommendable_buy,
    is_reference_only,
)


def test_swing_seed_is_seed_not_recommendable():
    bp = {"type": "swing底背驰候选种子"}
    assert infer_signal_tier(bp) == "seed"
    assert is_candidate_seed(bp)
    assert not is_recommendable_buy(bp)


def test_bottom_divergence_candidate_is_recommendable():
    bp = {"type": "底背驰候选", "tier": "candidate"}
    assert infer_signal_tier(bp) == "candidate"
    assert is_recommendable_buy(bp)


def test_raw_swing_reference_stays_reference_only():
    bp = {"type": "swing底背驰参考"}
    assert infer_signal_tier(bp) == "reference"
    assert is_reference_only(bp)
    assert not is_recommendable_buy(bp)
```

**Step 2: 运行测试确认失败**

Run:

```bash
python3 -m unittest tests.test_signal_policy -v
```

Expected: `is_candidate_seed` 或 `is_reference_only` 未定义，或 `swing底背驰候选种子` 分层错误。

**Step 3: 最小实现**

在 `chanlun/signal_policy.py` 增加：

```python
CANDIDATE_SEED_TYPES = {
    "swing底背驰候选种子",
}

CANDIDATE_TYPES = {
    "二买候选",
    "盘整低吸候选",
    "中枢低吸候选",
    "三买候选",
    "底背驰候选",
}

UPGRADE_OUTPUT_TYPE = {
    "二买待确认": "二买候选",
    "盘整背驰参考": "盘整低吸候选",
    "中枢震荡低吸参考": "中枢低吸候选",
    "三买待确认": "三买候选",
    "swing底背驰候选种子": "底背驰候选",
}
```

并更新：

```python
def infer_signal_tier(bp):
    if "tier" in bp:
        return bp["tier"]
    t = bp.get("type", "")
    if t in FORMAL_TYPES:
        return "formal"
    if t in CANDIDATE_TYPES:
        return "candidate"
    if t in CANDIDATE_SEED_TYPES:
        return "seed"
    if t in UPGRADEABLE_REFERENCE_TYPES or t in REFERENCE_ONLY_TYPES:
        return "reference"
    if t in BLOCKED_TYPES:
        return "blocked"
    return "reference"


def is_candidate_seed(bp):
    return infer_signal_tier(bp) == "seed"


def is_reference_only(bp):
    t = bp.get("type", "")
    return t in REFERENCE_ONLY_TYPES
```

**Step 4: 运行测试**

Run:

```bash
python3 -m unittest tests.test_signal_policy -v
```

Expected: PASS。

---

### Task 2: 新增日线位置保护和 swing seed 构造

**Files:**

- Modify: `chanlun/daily_structure_pool.py`
- Test: `tests/test_daily_structure_pool.py`

**Design:**

`swing底背驰参考` 只有满足日线位置保护时才进入结构池。位置保护不是买点本身，只是允许进入 30min 检查。

日线位置保护通过任一组即可：

1. 近 20 日低位：`close <= rolling_20_low * 1.08`
2. 从近 20 日高点回撤充分：`close <= rolling_20_high * 0.92`
3. 如果有中枢 `ZD`：`close <= ZD * 1.05`
4. 如果 source bp 有 `price`：`close <= source_price * 1.08`

同时必须满足所有风险保护：

1. 非 ST、非退市/风险名称：`is_st_stock(name)` 已有逻辑必须保留，另需过滤名称包含 `退市`、`*ST`、`ST`、`退` 且明显退市整理的股票。
2. 非涨停、非跌停，沿用已有基础过滤。
3. 流动性，沿用已有基础过滤。
4. 不追高：`close <= source_price * 1.12`，如果没有 `source_price` 则使用 20 日高点规则。
5. 最近 3 日不能连续明显放量下跌：`close[-1] < close[-2] < close[-3]` 且最近 3 日均量大于前 10 日均量 1.5 倍时，不生成 seed。

**Step 1: 写失败测试**

Create `tests/test_daily_structure_pool.py`。

测试用例：

```python
def test_swing_reference_without_position_guard_is_excluded():
    result = make_result(
        code="000001",
        closes=[10, 10.5, 11, 11.2, 11.5] * 8,
        buy_points=[{"type": "swing底背驰参考", "price": 8.0}],
    )
    pool, diag = build_daily_structure_pool([result], sector_stocks={}, mode="pure")
    assert pool == []
    assert diag["swing_seed_count"] == 0
    assert diag["reference_only_count"] == 1


def test_swing_reference_with_position_guard_enters_pool_as_seed():
    result = make_result(
        code="000002",
        closes=[12, 11.5, 11, 10.5, 10.2, 10.1, 10.0, 10.1] * 5,
        buy_points=[{"type": "swing底背驰参考", "price": 10.0}],
    )
    pool, diag = build_daily_structure_pool([result], sector_stocks={}, mode="pure")
    assert len(pool) == 1
    seed = [bp for bp in pool[0]["buy_points"] if bp["type"] == "swing底背驰候选种子"][0]
    assert seed["tier"] == "seed"
    assert seed["source_type"] == "swing底背驰参考"
    assert seed["seed_reason"]
    assert diag["swing_seed_count"] == 1
```

测试辅助对象可以用 lightweight fake class，不要依赖真实行情接口。

**Step 2: 运行测试确认失败**

Run:

```bash
python3 -m unittest tests.test_daily_structure_pool -v
```

Expected: FAIL，当前没有 seed 构造和诊断字段。

**Step 3: 实现日线位置保护**

在 `chanlun/daily_structure_pool.py` 增加内部函数：

```python
def _build_swing_position_seed(bp, result, pivot_info):
    if bp.get("type") != "swing底背驰参考":
        return None
    ok, reason = _passes_daily_position_guard(bp, result, pivot_info)
    if not ok:
        return None
    return {
        **bp,
        "type": "swing底背驰候选种子",
        "tier": "seed",
        "source_type": "swing底背驰参考",
        "seed_reason": reason,
    }
```

实现：

```python
def _passes_daily_position_guard(bp, result, pivot_info):
    closes = result.closes
    volumes = result.volumes
    if closes is None or len(closes) < 20:
        return False, "日线数据不足20根"

    close = float(closes[-1])
    recent = closes[-20:]
    recent_low = float(np.min(recent))
    recent_high = float(np.max(recent))
    source_price = float(bp.get("price") or 0)
    zd = pivot_info.get("ZD") if pivot_info else None

    if source_price > 0 and close > source_price * 1.12:
        return False, "当前价距离参考价过高"
    if _is_three_day_volume_selloff(closes, volumes):
        return False, "最近3日放量连续下跌"

    reasons = []
    if close <= recent_low * 1.08:
        reasons.append("接近20日低点")
    if close <= recent_high * 0.92:
        reasons.append("相对20日高点回撤充分")
    if zd is not None and close <= float(zd) * 1.05:
        reasons.append("接近日线中枢ZD")
    if source_price > 0 and close <= source_price * 1.08:
        reasons.append("接近swing参考价")

    if not reasons:
        return False, "未处于日线低位或关键位附近"
    return True, "；".join(reasons)
```

实现：

```python
def _is_three_day_volume_selloff(closes, volumes):
    if closes is None or volumes is None or len(closes) < 13 or len(volumes) < 13:
        return False
    down_3 = closes[-1] < closes[-2] < closes[-3]
    recent_vol = float(np.mean(volumes[-3:]))
    base_vol = float(np.mean(volumes[-13:-3]))
    return down_3 and base_vol > 0 and recent_vol > base_vol * 1.5
```

**Step 4: 更新结构池逻辑**

分类时新增：

```python
swing_seeds = []
for bp in reference_bps:
    seed = _build_swing_position_seed(bp, result, pivot_info)
    if seed:
        swing_seeds.append(seed)

has_swing_seed = len(swing_seeds) > 0
```

入池条件改为：

```python
if not has_formal and not has_upgradeable and not has_swing_seed:
    ...
    continue
```

`pool_bps` 改为：

```python
pool_bps = formal_bps + upgradeable_bps + swing_seeds
all_bps = formal_bps + upgradeable_bps + swing_seeds + reference_bps + blocked_bps
```

注意：`best_buy_point` 初始选择不能把 seed 当最终推荐。可以保留为 `None` 或只从 `formal_bps + upgradeable_bps` 中选。建议：

```python
best_bp = _pick_best_buy_point(formal_bps + upgradeable_bps) if (formal_bps or upgradeable_bps) else None
```

seed 只用于 30min 升级，不参与最终推荐排序。

**Step 5: 更新诊断**

`diag` 增加：

```python
"swing_seed_count": 0,
"buy_point_type_counts": {},
"structure_pool_reasons": {
    "formal": 0,
    "upgradeable_reference": 0,
    "swing_position_seed": 0,
},
"excluded_reference_type_counts": {},
```

每看到一个 bp 都统计 `buy_point_type_counts[type] += 1`。

被排除的 reference-only 统计：

```python
diag["excluded_reference_type_counts"][bp_type] += 1
```

入池原因统计：

```python
if has_formal:
    diag["structure_pool_reasons"]["formal"] += 1
if has_upgradeable:
    diag["structure_pool_reasons"]["upgradeable_reference"] += 1
if has_swing_seed:
    diag["structure_pool_reasons"]["swing_position_seed"] += 1
    diag["swing_seed_count"] += len(swing_seeds)
```

**Step 6: 运行测试**

Run:

```bash
python3 -m unittest tests.test_daily_structure_pool -v
```

Expected: PASS。

---

### Task 3: 扩展 30min 确认分类

**Files:**

- Modify: `chanlun/sublevel_confirm.py`
- Test: `tests/test_sublevel_confirm.py`

**Design:**

当前中等确认过窄：`底分型 + MACD 金叉 + 关键位不破` 同时满足才升级。实盘里次级别止跌经常先表现为均线收复或连续止跌结构。因此新增：

强确认：

1. 30min 底背驰。
2. 30min formal/candidate buy。

中确认，任一成立：

1. `底分型 + MACD 金叉`
2. `关键位不破 + 收盘重新站上 EMA5`
3. `止跌K线结构 + 收盘重新站上 EMA5`

弱确认：

1. 只有关键位不破。
2. 只有 EMA5 收复。

只有强/中能升级。弱只能进入 watch/reference，不推荐。

**Step 1: 写失败测试**

Create `tests/test_sublevel_confirm.py`。

测试：

```python
def test_key_level_and_ema5_reclaim_is_medium_confirmation():
    daily_stock = make_daily_stock_with_swing_seed(source_price=10.0)
    bp = {"type": "swing底背驰候选种子", "price": 10.0}
    min30 = make_min30_result(
        lows=[10.2, 10.1, 10.0, 10.05, 10.08, 10.12, 10.2, 10.3],
        closes=[10.25, 10.15, 10.08, 10.1, 10.12, 10.18, 10.26, 10.35],
    )
    confirmation = classify_30min_confirmation(daily_stock, bp, min30)
    assert confirmation["confirmed"]
    assert confirmation["level"] == "中"
    assert "EMA5收复" in confirmation["signals"]
```

```python
def test_key_level_only_is_weak_not_confirmed():
    daily_stock = make_daily_stock_with_swing_seed(source_price=10.0)
    bp = {"type": "swing底背驰候选种子", "price": 10.0}
    min30 = make_min30_result(
        lows=[10.2, 10.1, 10.0, 10.05, 10.02, 10.01, 10.03, 10.04],
        closes=[10.2, 10.15, 10.1, 10.08, 10.05, 10.03, 10.02, 10.01],
    )
    confirmation = classify_30min_confirmation(daily_stock, bp, min30)
    assert not confirmation["confirmed"]
    assert confirmation["level"] == "弱"
```

```python
def test_stop_fall_bars_and_ema5_reclaim_is_medium_confirmation():
    daily_stock = make_daily_stock_with_swing_seed(source_price=10.0)
    bp = {"type": "swing底背驰候选种子", "price": 10.0}
    min30 = make_min30_result(
        lows=[10.4, 10.2, 10.0, 10.02, 10.05, 10.08, 10.12, 10.16],
        closes=[10.3, 10.1, 10.05, 10.08, 10.12, 10.18, 10.22, 10.28],
    )
    confirmation = classify_30min_confirmation(daily_stock, bp, min30)
    assert confirmation["confirmed"]
    assert confirmation["level"] == "中"
    assert "止跌结构" in confirmation["signals"]
```

**Step 2: 运行测试确认失败**

Run:

```bash
python3 -m unittest tests.test_sublevel_confirm -v
```

Expected: FAIL，当前没有 EMA5 收复/止跌结构，也不识别 swing seed 的关键位。

**Step 3: 实现 EMA5 收复**

在 `chanlun/sublevel_confirm.py` 增加：

```python
def _check_ema5_reclaim(min30_result):
    closes = min30_result.closes
    if closes is None or len(closes) < 6:
        return False
    recent = np.asarray(closes[-5:], dtype=float)
    ema5 = float(np.mean(recent))
    latest_close = float(closes[-1])
    prev_close = float(closes[-2])
    return latest_close > ema5 and latest_close >= prev_close
```

说明：这里先用 5 根均价近似 EMA5，避免引入新依赖。若项目已有 EMA 工具函数，可复用项目函数。

**Step 4: 实现止跌 K 线结构**

```python
def _check_stop_fall_bars(min30_result):
    lows = min30_result.lows
    closes = min30_result.closes
    opens = min30_result.opens
    if lows is None or closes is None or opens is None:
        return False
    if len(lows) < 4 or len(closes) < 4 or len(opens) < 4:
        return False

    higher_lows = lows[-1] >= lows[-2] >= min(lows[-4:-2])
    two_repair_closes = closes[-1] >= opens[-1] and closes[-2] >= opens[-2]
    close_repair = closes[-1] > closes[-3]
    return bool(higher_lows and two_repair_closes and close_repair)
```

**Step 5: 扩展关键位识别**

`_check_key_level()` 增加：

```python
elif src_type == "swing底背驰候选种子":
    bp_price = source_bp.get("price", 0)
    if bp_price <= 0:
        return False
    return recent_low >= bp_price * (1 - NEAR_PRICE_PCT)
```

**Step 6: 更新强/中/弱判定**

在 `classify_30min_confirmation()` 中增加：

```python
ema5_reclaim = _check_ema5_reclaim(min30_result)
if ema5_reclaim:
    signals.append("EMA5收复")
    reasons.append("30分钟收盘重新站上EMA5")

stop_fall_bars = _check_stop_fall_bars(min30_result)
if stop_fall_bars:
    signals.append("止跌结构")
    reasons.append("30分钟出现止跌K线结构")
```

判定改为：

```python
if "30min底背驰" in signals or has_30min_buy:
    level = "强"
    confirmed = True
elif has_fractal_macd or (key_level_ok and ema5_reclaim) or (stop_fall_bars and ema5_reclaim):
    level = "中"
    confirmed = True
elif key_level_ok or ema5_reclaim:
    level = "弱"
    confirmed = False
else:
    level = "无"
    confirmed = False
```

注意：`has_fractal_macd` 不再要求同时 `key_level_ok`，因为底分型和 MACD 金叉本身就是次级别确认组合。但如果后续 QA 发现误报，可以再加“不能跌破 source_price 3%”的风险阀。

**Step 7: 运行测试**

Run:

```bash
python3 -m unittest tests.test_sublevel_confirm -v
```

Expected: PASS。

---

### Task 4: 升级逻辑支持 swing seed -> 底背驰候选

**Files:**

- Modify: `chanlun/candidate_upgrade.py`
- Test: `tests/test_candidate_upgrade.py`

**Step 1: 写失败测试**

Create `tests/test_candidate_upgrade.py`。

测试：

```python
def test_swing_seed_upgrades_to_bottom_divergence_candidate_with_medium_confirmation():
    daily_pool = [make_stock(
        code="000001",
        buy_points=[
            {
                "type": "swing底背驰候选种子",
                "tier": "seed",
                "source_type": "swing底背驰参考",
                "price": 10.0,
                "seed_reason": "接近20日低点",
            },
            {"type": "swing底背驰参考", "price": 10.0},
        ],
    )]
    min30_results = [make_min30_result(code="000001", medium_confirm=True)]
    recommended, diag = upgrade_daily_candidates_with_30min(daily_pool, min30_results, mode="pure")

    assert len(recommended) == 1
    bp = recommended[0]["best_buy_point"]
    assert bp["type"] == "底背驰候选"
    assert bp["tier"] == "candidate"
    assert bp["source_type"] == "swing底背驰参考"
    assert bp["seed_type"] == "swing底背驰候选种子"
    assert bp["seed_reason"] == "接近20日低点"
    assert diag["candidate_upgraded"] == 1
```

```python
def test_swing_seed_without_30min_confirmation_is_not_recommended():
    daily_pool = [make_stock(
        code="000002",
        buy_points=[{"type": "swing底背驰候选种子", "tier": "seed", "source_type": "swing底背驰参考", "price": 10.0}],
    )]
    min30_results = [make_min30_result(code="000002", medium_confirm=False)]
    recommended, diag = upgrade_daily_candidates_with_30min(daily_pool, min30_results, mode="pure")

    assert recommended == []
    assert diag["dropped_no_confirm"] == 1
```

**Step 2: 运行测试确认失败**

Run:

```bash
python3 -m unittest tests.test_candidate_upgrade -v
```

Expected: FAIL，当前只处理 `is_upgradeable_reference()`，不处理 seed。

**Step 3: 实现 seed 分类**

在 `candidate_upgrade.py` 引入：

```python
from .signal_policy import (
    is_formal_buy,
    is_upgradeable_reference,
    is_candidate_seed,
    UPGRADE_OUTPUT_TYPE,
)
```

分类改为：

```python
seed_bps = [bp for bp in all_bp if is_candidate_seed(bp)]
upgradeable_bps = [bp for bp in all_bp if is_upgradeable_reference(bp) or is_candidate_seed(bp)]
```

`other_bps` 排除 seed：

```python
other_bps = [
    bp for bp in all_bp
    if not is_formal_buy(bp)
    and not is_upgradeable_reference(bp)
    and not is_candidate_seed(bp)
]
```

**Step 4: 实现升级输出**

升级时：

```python
src_type = bp.get("type", "")
out_type = UPGRADE_OUTPUT_TYPE.get(src_type)
if not out_type:
    reference_buy_points.append(bp)
    continue
```

candidate 构造：

```python
candidate = {
    **bp,
    "type": out_type,
    "tier": "candidate",
    "source_type": bp.get("source_type", src_type),
    "seed_type": src_type if is_candidate_seed(bp) else None,
    "confirmed_by": confirmation["reason"],
    "confirmations": confirmation["signals"],
    "strength": confirmation["level"],
    "reason": bp.get("reason", "") + "；次级别确认：" + confirmation["reason"],
}
```

如果 `seed_type is None`，可以删除该 key，避免旧候选输出多余字段：

```python
if candidate["seed_type"] is None:
    del candidate["seed_type"]
```

**Step 5: 加追高和破位风险阀**

在升级成功前调用：

```python
if not _passes_upgrade_risk_guard(stock, bp, min30_result):
    reference_buy_points.append(bp)
    diag["dropped_risk_guard"] += 1
    continue
```

新增诊断字段：

```python
"dropped_risk_guard": 0,
```

实现：

```python
def _passes_upgrade_risk_guard(stock, source_bp, min30_result):
    closes = stock.get("closes")
    if closes is None or len(closes) == 0:
        return False
    latest_daily_close = float(closes[-1])
    source_price = float(source_bp.get("price") or 0)
    if source_price > 0 and latest_daily_close > source_price * 1.12:
        return False

    lows_30 = min30_result.lows
    if source_price > 0 and lows_30 is not None and len(lows_30) >= 8:
        recent_low = float(np.min(lows_30[-8:]))
        if recent_low < source_price * 0.97:
            return False

    return True
```

需要 `import numpy as np`。

**Step 6: 更新最佳买点排序**

`_pick_best_from_recommendable()` 增加：

```python
"底背驰候选": 7,
```

排序原则仍是 formal 优先于 candidate。candidate 内部优先级：

```text
三买候选 > 二买候选 > 盘整低吸候选 > 中枢低吸候选 > 底背驰候选
```

原因：`底背驰候选` 来自 swing reference，结构确定性弱于中枢类候选。

**Step 7: 运行测试**

Run:

```bash
python3 -m unittest tests.test_candidate_upgrade -v
```

Expected: PASS。

---

### Task 5: 加强 QA 脚本，禁止未知类型混入推荐

**Files:**

- Modify: `scripts/qa_signal_invariants.py`
- Test: `tests/test_pipeline_invariants.py` 或新建 `tests/test_qa_signal_invariants.py`

**Current Gap:**

现有 QA 注释说 `buy_points` 每一项都必须 allowed，但代码只检查 forbidden，没有检查 unknown type。并且 candidate 元数据校验主要看 `best_buy_point`，不保证每个 candidate 都有 `source_type/confirmed_by/confirmations/strength`。

**Step 1: 写失败测试**

新增测试：

```python
import json
import subprocess
import tempfile
from pathlib import Path


def _run_qa(path):
    return subprocess.run(
        ["python3", "scripts/qa_signal_invariants.py", str(path)],
        capture_output=True,
        text=True,
    )


def test_qa_rejects_unknown_buy_point_type():
    payload = {
        "pure": [{
            "code": "000001",
            "name": "TEST",
            "best_buy_point": {"type": "未知候选", "tier": "candidate"},
            "buy_points": [{"type": "未知候选", "tier": "candidate"}],
        }],
        "fusion": [],
        "diagnostics": {"daily_scan": {"buy_point_type_counts": {}}},
    }
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "data.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        result = _run_qa(path)
        assert result.returncode != 0
```

```python
def test_qa_rejects_candidate_missing_metadata():
    payload = {
        "pure": [{
            "code": "000001",
            "name": "TEST",
            "best_buy_point": {"type": "底背驰候选", "tier": "candidate"},
            "buy_points": [{"type": "底背驰候选", "tier": "candidate"}],
        }],
        "fusion": [],
        "diagnostics": {"daily_scan": {"buy_point_type_counts": {}}},
    }
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "data.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        result = _run_qa(path)
        assert result.returncode != 0
```

如果现有测试框架不方便直接 import 脚本，可用 `subprocess.run(["python3", "scripts/qa_signal_invariants.py", path])`。

**Step 2: 运行测试确认失败**

Run:

```bash
python3 -m unittest tests.test_pipeline_invariants -v
```

Expected: FAIL。

**Step 3: 修改 QA 规则**

`ALLOWED_BEST_TYPES` 增加：

```python
"底背驰候选",
```

对每个 stock：

```python
for bp in stock.get("buy_points", []):
    bp_type = bp.get("type")
    if bp_type not in ALLOWED_BEST_TYPES:
        errors.append(f"{code} buy_points contains non-recommendable type: {bp_type}")
```

对每个 candidate：

```python
if bp.get("tier") == "candidate" or bp.get("type", "").endswith("候选"):
    required = ["source_type", "confirmed_by", "confirmations", "strength"]
    for key in required:
        if not bp.get(key):
            errors.append(f"{code} candidate {bp.get('type')} missing {key}")
```

对 `底背驰候选` 额外要求：

```python
if bp.get("type") == "底背驰候选":
    if bp.get("source_type") != "swing底背驰参考":
        errors.append(f"{code} 底背驰候选 source_type must be swing底背驰参考")
    if bp.get("seed_type") != "swing底背驰候选种子":
        errors.append(f"{code} 底背驰候选 seed_type must be swing底背驰候选种子")
    if not bp.get("seed_reason"):
        errors.append(f"{code} 底背驰候选 missing seed_reason")
```

**Step 4: 运行测试**

Run:

```bash
python3 -m unittest tests.test_pipeline_invariants -v
```

Expected: PASS。

---

### Task 6: 报告和 diagnostics 输出

**Files:**

- Modify: `run.py`
- Modify: `chanlun/report_generator.py`
- Possibly modify: `docs/index.html` only if it is generated output

**Required diagnostics:**

`docs/data/YYYY-MM-DD.json` 和 `docs/data.json` 必须包含：

```json
{
  "diagnostics": {
    "daily_scan": {
      "total": 224,
      "base_pass": 117,
      "with_buy_points": 63,
      "formal_count": 0,
      "upgradeable_count": 2,
      "swing_seed_count": 0,
      "reference_only_count": 61,
      "blocked_only_count": 0,
      "buy_point_type_counts": {
        "swing底背驰参考": 61
      },
      "structure_pool_reasons": {
        "formal": 0,
        "upgradeable_reference": 2,
        "swing_position_seed": 0
      },
      "excluded_reference_type_counts": {
        "swing底背驰参考": 61
      }
    },
    "sublevel_upgrade_pure": {
      "requested_30min": 0,
      "fetched_30min": 0,
      "formal_kept": 0,
      "candidate_upgraded": 0,
      "dropped_no_confirm": 0,
      "dropped_no_30min": 0,
      "dropped_risk_guard": 0
    }
  }
}
```

实际数值按运行结果生成，不允许硬编码。

**Report requirements:**

HTML 必须把推荐分为：

1. `正式买点`：`一买/二买/三买`
2. `候选买点`：`三买候选/二买候选/盘整低吸候选/中枢低吸候选/底背驰候选`
3. `观察信号`：reference/watch，只能在详情里展示，不能进入推荐列表排序

每个 `底背驰候选` 展示：

```text
来源：swing底背驰参考
日线种子原因：接近20日低点 / 回撤充分 / 接近ZD / 接近参考价
30min确认：EMA5收复 / 止跌结构 / 底分型+MACD金叉 / 30min底背驰
强度：强/中
```

如果最终仍为 0，HTML 必须展示诊断摘要：

```text
日线信号 63 个，其中可进入30min确认 2 个，swing位置种子 0 个；
30min确认通过 0 个，风险保护剔除 0 个。
```

这比单纯“0只”更可解释。

---

### Task 7: 配置开关和回滚

**Files:**

- Modify: `config.py`
- Modify: `run.py`

新增配置：

```python
ENABLE_SWING_POSITION_SEEDS = True
ENABLE_RELAXED_30MIN_CONFIRM = True
ENABLE_SIGNAL_DISTRIBUTION_DIAGNOSTICS = True
```

使用方式：

1. `ENABLE_SWING_POSITION_SEEDS=False` 时，不生成 `swing底背驰候选种子`。
2. `ENABLE_RELAXED_30MIN_CONFIRM=False` 时，30min 中确认恢复旧规则：`底分型 + MACD金叉 + 关键位不破`。
3. `ENABLE_SIGNAL_DISTRIBUTION_DIAGNOSTICS=False` 时仍保留核心计数，但可跳过详细 type distribution。建议默认 True。

QA 要求：默认配置必须打开三项；回滚只用于线上紧急隔离，不作为长期方案。

---

## 4. 全量 QA 流程

### 4.1 单元测试

Run:

```bash
python3 -m unittest tests.test_signal_policy -v
python3 -m unittest tests.test_daily_structure_pool -v
python3 -m unittest tests.test_sublevel_confirm -v
python3 -m unittest tests.test_candidate_upgrade -v
python3 -m unittest tests.test_pipeline_invariants -v
python3 -m unittest discover -s tests -p 'test_*.py'
```

Expected:

```text
OK
```

不得通过删除或跳过旧测试来过关。

### 4.2 2026-05-26 数据回归

Run:

```bash
python3 run.py --date 2026-05-26
```

如果当前 `run.py` 不支持 `--date`，则先按现有项目方式跑默认交易日，并确认输出文件为 `docs/data/2026-05-26.json`。不要为本 spec 强行重构 CLI。

然后运行：

```bash
python3 scripts/qa_signal_invariants.py docs/data/2026-05-26.json
python3 scripts/qa_signal_invariants.py docs/data.json
```

Expected:

```text
QA passed
```

### 4.3 结果验收标准

在同一批 2026-05-26 数据上，期望看到：

1. `daily_scan.with_buy_points` 仍接近原来的 63，不应大幅下降。
2. `daily_scan.swing_seed_count > 0`，除非诊断明确说明全部 swing reference 不在日线低位或触发风险保护。
3. `sublevel_upgrade.requested_30min > 2`，因为 swing seed 应扩大进入 30min 的池子。
4. `candidate_upgraded` 理想上应大于 0；如果仍为 0，必须能从 `dropped_no_confirm/dropped_risk_guard/type_counts` 看出原因，而不是黑盒 0。
5. 最终推荐不强制固定数量，但不能靠 padding 补齐。
6. 任何最终推荐里的 `底背驰候选` 都必须有 `source_type/seed_type/seed_reason/confirmed_by/confirmations/strength`。
7. `swing底背驰参考` 和 `swing底背驰候选种子` 不得出现在最终推荐 `buy_points` 或 `best_buy_point`。

### 4.4 人工图形验收

如果最终有候选：

1. 至少人工打开 3 只 `底背驰候选` 的日线图。
2. 检查是否确实处于低位、回撤充分或接近中枢下沿。
3. 再看 30min 图，确认不是一路下跌中仅靠“没破参考价”误升级。
4. 如果 3 只里有 2 只明显追高或破位，应收紧 `daily_position_guard` 或 `risk_guard`，不要继续扩大池子。

---

## 5. Commit 建议

按小步提交：

```bash
git add chanlun/signal_policy.py tests/test_signal_policy.py
git commit -m "feat: add candidate seed signal policy"

git add chanlun/daily_structure_pool.py tests/test_daily_structure_pool.py
git commit -m "feat: build swing position seeds"

git add chanlun/sublevel_confirm.py tests/test_sublevel_confirm.py
git commit -m "feat: relax 30min confirmation with stop-fall signals"

git add chanlun/candidate_upgrade.py tests/test_candidate_upgrade.py
git commit -m "feat: upgrade swing seeds into bottom divergence candidates"

git add scripts/qa_signal_invariants.py tests/test_pipeline_invariants.py
git commit -m "test: enforce recommendable signal invariants"

git add config.py run.py chanlun/report_generator.py
git commit -m "feat: expose candidate diagnostics in report"
```

---

## 6. 自 Review

### 6.1 已检查的关键风险

1. 没有放松 formal：`一买/二买/三买` 的来源不变。
2. 没有把 swing 直接推荐：raw `swing底背驰参考` 必须先变 seed，再经 30min 确认升级。
3. 没有恢复 TopN padding：最终数量由信号产生，不靠补齐。
4. 候选可解释：`底背驰候选` 必须带 `source_type/seed_type/seed_reason/confirmed_by/confirmations/strength`。
5. QA 能防止污染：未知类型、reference、seed、blocked 都不能进入最终推荐。
6. 仍保留风险阀：追高、破位、连续放量下跌不能升级。
7. 结果为 0 时也能定位原因：必须输出 type distribution 和 drop reasons。
8. 已做 2026-05-26 离线预验证：规则能把 30min target 从 2-3 只扩大到约 96 只，并模拟产出 10 只 `底背驰候选`。
9. 预验证发现退市名称过滤缺口，已补入基础风险过滤要求。

### 6.2 本 spec 的刻意取舍

1. `底背驰候选` 排在候选优先级最后，因为它来自 swing reference，确定性弱于标准中枢结构候选。
2. `底分型 + MACD金叉` 可单独作为中确认，这是一次有边界的放宽；如果 QA 发现误报，再加 source_price 破位阀，而不是回退整个机制。
3. EMA5 先用近 5 根均价近似，避免引入新依赖；如果项目已有 EMA 实现，应优先复用。
4. 日线位置保护使用 OR 条件扩大覆盖，但风险保护使用 AND 条件兜底，避免把追高 swing 也放进池子。

### 6.3 执行前检查清单

执行同事开始改代码前，先确认：

1. `tests/test_daily_structure_pool.py`、`tests/test_sublevel_confirm.py`、`tests/test_candidate_upgrade.py` 必须新增，不要只改集成测试。
2. `scripts/qa_signal_invariants.py` 必须检查每一个 `buy_points`，不是只看 `best_buy_point`。
3. `run.py` 不能把 30min fetched 的股票数写死，必须来自结构池 union。
4. HTML 报告不能把 candidate 文案写成“正式买点”。
5. 如果最终还是 0，先看 diagnostics，不要再加固定数量补齐。
