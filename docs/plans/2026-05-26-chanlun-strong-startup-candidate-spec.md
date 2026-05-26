# Chanlun Strong Startup Candidate Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 新增“强势启动候选”选股通道，把底部放量启动、突破中枢/平台、板块催化的股票纳入主推荐，避免当前结果过度集中在走势偏弱的 `底背驰候选`。

**Architecture:** 保留现有 `底背驰候选` 左侧低吸通道，但新增独立的右侧启动通道：`日线低位/底部区间 -> 放量长阳/平台突破/中枢上沿突破 -> 30min回踩确认或涨停观察 -> 强势启动候选/强势启动观察`。最终报告按层级展示：强势启动候选为主推荐，底背驰候选为低吸观察，不再把两者混成同一类。

**Tech Stack:** Python 3, `unittest`, existing `chanlun/*` modules, existing `run.py` batch pipeline, existing static HTML report under `docs/`.

---

## 1. 背景

### 1.1 当前问题

2026-05-26 当前结果：

```text
picks_pure = 77
picks_fusion = 76
pure type distribution = 76 底背驰候选 + 1 中枢低吸候选
formal_count = 0
```

这批票的共同特征是：

```text
日线低位参考
-> 30min 不破位 / EMA5收复 / 止跌结构
-> 底背驰候选
```

它们更像“跌不动了、可能修复”，不是“已经启动”。用户主观感受是走势平平、弱，原因符合当前策略设计。

### 1.2 招金黄金案例

以 `000506 招金黄金` 为例，本地缓存显示 2026-05-26：

```text
close = 15.40
涨幅 = 10.00%
量比近5日 = 1.70
日线信号 = swing底背驰参考 @ 13.54
```

当前系统排除原因：

1. `涨幅 >= LIMIT_UP_THRESHOLD(9.5)`，被基础涨停过滤排除。
2. 当前价距离 swing 参考价超过 12%，触发追高保护：

```text
当前价距离参考价过高
```

结论：按低吸通道排除是合理的，但它应该进入“强势启动观察池”，而不是完全消失。

### 1.3 目标转变

选股主目标应从：

```text
寻找低位修复候选
```

扩展为：

```text
优先寻找启动中的票，低位修复候选作为观察补充。
```

## 2. 非目标

1. 不删除现有 `底背驰候选` 通道。
2. 不放松正式 `一买/二买/三买` 定义。
3. 不把所有涨停股直接推荐买入。
4. 不恢复固定 TopN 补齐。
5. 不引入未来函数。
6. 不把强势启动规则混进 `底背驰候选` 判定里。

## 3. 新信号类型

### 3.1 新增类型

新增两类：

```python
STRONG_STARTUP_TYPES = {
    "强势启动候选",
    "强势启动观察",
}
```

语义：

1. `强势启动候选`：
   - 已经启动。
   - 日线满足低位启动 + 放量突破。
   - 30min 有可执行确认。
   - 可进入主推荐。

2. `强势启动观察`：
   - 已经明显启动或涨停。
   - 当天不建议追入。
   - 进入次日观察池，等待回踩不破或 30min 二买/三买确认。

### 3.2 推荐层级

最终展示层级：

```text
主推荐：
  强势启动候选
  三买 / 三买候选
  二买 / 二买候选

低吸观察：
  底背驰候选
  中枢低吸候选
  盘整低吸候选

启动观察：
  强势启动观察
```

排序原则：

```text
主推荐内：强势启动候选 > formal买点 > 其他candidate > 底背驰候选
观察池内：强势启动观察 > 其他观察项
```

注意：`强势启动观察` 不应和可买候选混在一起，必须标注“等待回踩确认”。

## 4. 强势启动候选定义

### 4.1 日线低位要求

不能是高位加速。至少满足以下任一：

```text
current_close <= recent_60_high * 0.88
current_close <= recent_120_high * 0.82
close_before_start <= recent_20_low * 1.12
存在最近日线中枢，启动前价格位于 ZD/ZG 附近或中枢内
```

### 4.2 放量要求

至少满足：

```text
today_volume >= avg_volume_5 * 1.5
```

或：

```text
today_amount >= avg_amount_5 * 1.5
```

### 4.3 价格启动要求

至少满足以下任二：

```text
today_change_pct >= 4.0
close > MA5
close > MA10
close > recent_20_high_prev
close > pivot_zg
实体阳线幅度 >= 3.0%
```

说明：

1. `recent_20_high_prev` 不包含当天，避免用当天自己突破自己。
2. `pivot_zg` 只有存在中枢时使用。
3. 强势启动可以来自没有原始 `buy_points` 的股票，不能要求先存在 `一买/二买/三买/底背驰参考`。

### 4.4 涨停处理

涨幅达到当前涨停过滤阈值：

```text
change_pct >= LIMIT_UP_THRESHOLD
```

不再直接丢弃，而是：

1. 如果满足低位 + 放量 + 启动条件，进入 `强势启动观察`。
2. 标注：

```text
已涨停/接近涨停，不建议当日追入，等待次日回踩不破或30min确认。
```

3. 次日若出现：

```text
缩量回踩不破突破位
30min回踩不破
30min二买/三买
EMA5/EMA10维持
```

可升级为 `强势启动候选`。

### 4.5 30min 确认要求

非涨停的强势启动，要进入 `强势启动候选`，需要至少一个 30min 确认：

```text
30min回踩不破突破位
30min回踩不破日线中枢ZG
30min EMA5/EMA10维持
30min出现二买/三买
30min放量后缩量回踩
```

如果只有日线启动，没有 30min 确认：

```text
强势启动观察
```

## 5. 诊断字段

每只强势启动相关股票必须记录：

```python
{
    "type": "强势启动候选",
    "tier": "candidate",
    "source_type": "日线强势启动",
    "startup_reason": "底部放量长阳突破20日平台",
    "startup_signals": [
        "低位",
        "放量1.7倍",
        "站上MA5/MA10",
        "突破20日平台",
        "突破中枢ZG"
    ],
    "confirmations": [
        "30min回踩不破突破位",
        "30min EMA5维持"
    ],
    "watch_reason": "",
    "avoid_chase": false,
    "next_day_conditions": []
}
```

`强势启动观察` 示例：

```python
{
    "type": "强势启动观察",
    "tier": "watch",
    "source_type": "日线强势启动",
    "startup_reason": "低位放量涨停",
    "avoid_chase": true,
    "watch_reason": "涨停当日不追，等待次日回踩确认",
    "next_day_conditions": [
        "回踩不破突破位",
        "30min二买/三买",
        "缩量回踩后再放量"
    ]
}
```

## 6. 架构改动

### 6.0 配置开关

新增配置：

```python
ENABLE_STRONG_STARTUP_CANDIDATES = True
STRONG_STARTUP_MIN_CHANGE_PCT = 4.0
STRONG_STARTUP_MIN_VOLUME_RATIO = 1.5
STRONG_STARTUP_LOW_POSITION_60D_RATIO = 0.88
STRONG_STARTUP_LOW_POSITION_120D_RATIO = 0.82
STRONG_STARTUP_PRE_START_LOW_RATIO = 1.12
```

要求：

1. 默认开启，但必须可回滚。
2. 关闭后，现有 `底背驰候选` 结果应保持和改动前一致。

### 6.1 新增模块

建议新增：

```text
chanlun/strong_startup.py
```

职责：

1. 检测日线强势启动。
2. 构建 `强势启动种子`。
3. 根据 30min 结果升级为 `强势启动候选` 或保留为 `强势启动观察`。

### 6.2 与现有结构池关系

当前结构池主要由：

```text
build_daily_structure_pool()
```

输出 formal / upgradeable / swing seed。

新增流程：

```text
daily analyze all stocks
-> build_daily_structure_pool()          # existing
-> build_strong_startup_pool()           # new
-> union target codes for 30min          # pure pool codes + non-limit startup seed codes
-> upgrade_daily_candidates_with_30min() # existing low吸 candidates
-> upgrade_strong_startup_with_30min()   # new startup candidates/watch
-> merge recommendations and watch list
-> score/rank/report
```

要求：

1. 不把强势启动逻辑塞进 `daily_structure_pool.py`。
2. 不改变 `底背驰候选` 的语义。
3. 新通道独立诊断，便于 QA。
4. `build_strong_startup_pool()` 必须从 `chan_results` 原始全集扫描，不能依赖 `build_daily_structure_pool()` 的输出，否则涨停票、无原始买点但已经启动的票会在原基础过滤里被提前吞掉。
5. `强势启动观察` 不进入 `picks_pure/picks_fusion` 主推荐数组，应进入单独字段 `startup_watchlist`。
6. 涨停/接近涨停的 `强势启动观察` 不需要为了当日主推荐去拉 30min；只有非涨停 startup seed 需要进入 30min 目标集合做确认升级。

### 6.3 run.py 合并规则

新增输出字段：

```python
report_data["startup_watchlist"] = startup_watchlist
```

主推荐合并：

```text
pure_confirmed = existing low吸/formal candidates + startup_candidates
fusion_confirmed = fusion_admission(pure_confirmed)
startup_watchlist = startup watch only
```

注意：

1. `强势启动候选` 进入 pure/fusion 主推荐。
2. `强势启动观察` 不进入 fusion admission，不参与主推荐计数。
3. `sublevel_upgrade_pure/fusion` 诊断不要把 startup watch 计入 `candidate_upgraded`。
4. 新增 `diagnostics.strong_startup` 记录启动通道自己的计数。
5. `fusion_admission` 必须显式支持 `强势启动候选`，不能因为类型未知被默认丢弃。
6. `强势启动观察` 不得传入 `fusion_admission`，也不得参与 pure/fusion 主推荐数量。

### 6.4 纯净版/融合版分层

纯净版：

```text
强势启动候选只要满足低位 + 放量 + 启动 + 30min确认，即可进入 pure 主推荐。
```

融合版：

```text
强势启动候选仍要经过融合版门控，保留 MA5 > MA10 > MA20 与大盘强弱判断。
```

建议门槛：

1. `MA5 > MA10 > MA20` 必须满足，否则融合版过滤。
2. 大盘强时，30min 确认强度为 `强/中/弱` 都可保留，但弱确认应降序。
3. 大盘弱时，只保留 30min 确认为 `强/中` 的强势启动候选。
4. fusion 过滤原因必须写入 `fusion_admission.reason`，例如 `强势启动候选要求MA多头`、`强势启动候选弱市要求30min确认强/中`。

## 7. 评分和排序

### 7.1 新增评分维度

强势启动候选评分应重视：

```text
启动强度
放量质量
低位程度
突破质量
30min确认质量
板块强度/消息催化
```

建议新增：

```python
score_strong_startup(stock)
```

初始权重：

```text
低位程度 20%
放量质量 20%
突破质量 25%
30min确认 20%
板块/消息 15%
```

如果消息面暂未稳定接入，第一版可以先把“板块/消息 15%”简化为：

```text
板块强度 15%
```

不要因为消息面不可用阻塞强势启动通道。

### 7.2 排序规则

主推荐排序：

```text
1. 强势启动候选
2. 三买 / 三买候选
3. 二买 / 二买候选
4. 中枢低吸候选
5. 底背驰候选
```

观察池排序：

```text
1. 强势启动观察
2. 底背驰候选中未充分确认但值得观察的票
```

## 8. 页面展示

### 8.1 顶部摘要

页面顶部必须区分：

```text
主推荐 X 只
强势启动候选 X 只
强势启动观察 X 只
低吸观察 X 只
底背驰候选 X 只
```

### 8.2 表格分区

选股结果不能再只是一张混合表。

建议分区：

```text
主推荐：已启动
启动观察：已涨停/大涨，等回踩确认
低吸观察：底背驰/中枢低吸
```

数据来源：

1. `主推荐：已启动` 来自 `picks_*` 中 `best_buy_point.type == "强势启动候选"`。
2. `启动观察` 来自 `REPORT_DATA.startup_watchlist`。
3. `低吸观察` 来自 `picks_*` 中 `底背驰候选/中枢低吸候选/盘整低吸候选`。

### 8.3 招金黄金类展示

类似 `000506 招金黄金` 这类：

```text
低位放量涨停
```

应显示在：

```text
启动观察
```

文案：

```text
已低位放量启动，但涨停当日不追。观察次日是否缩量回踩不破 14.xx，或30min出现二买/三买确认。
```

## 9. 诊断与 QA

### 9.1 新增 diagnostics

新增：

```python
"strong_startup": {
    "scanned": 0,
    "daily_startup_seed": 0,
    "startup_candidate": 0,
    "startup_watch": 0,
    "dropped_high_position": 0,
    "dropped_no_volume": 0,
    "dropped_no_breakout": 0,
    "dropped_no_30min_confirm": 0,
    "watch_due_to_limit_up": 0,
    "watch_due_to_no_30min_confirm": 0,
}
```

### 9.2 不变量

必须满足：

1. `强势启动候选` 必须有 `startup_reason`。
2. `强势启动候选` 必须有 30min confirmation。
3. `强势启动观察` 必须有 `watch_reason`。
4. 涨停票不能直接作为 `强势启动候选`，只能先进入 `强势启动观察`。
5. `底背驰候选` 仍保留原语义，不混入启动字段。
6. `startup_watchlist` 中的股票不能出现在 `buy_points` 主推荐里，除非另有独立 formal/candidate 买点。

## 10. 实现任务

### Task 1: 扩展信号策略

**Files:**
- Modify: `chanlun/signal_policy.py`
- Test: `tests/test_signal_policy.py`

**Step 1: 写失败测试**

新增：

```python
def test_strong_startup_candidate_in_candidate_types():
    bp = {"type": "强势启动候选"}
    assert infer_signal_tier(bp) == "candidate"


def test_strong_startup_candidate_is_recommendable():
    bp = {"type": "强势启动候选", "tier": "candidate"}
    assert is_recommendable_buy(bp)


def test_strong_startup_watch_infers_watch_tier():
    bp = {"type": "强势启动观察"}
    assert infer_signal_tier(bp) == "watch"


def test_strong_startup_watch_is_not_recommendable():
    bp = {"type": "强势启动观察", "tier": "watch"}
    assert not is_recommendable_buy(bp)
```

**Step 2: 运行测试确认失败**

Run:

```bash
python3 -m unittest tests.test_signal_policy -v
```

**Step 3: 最小实现**

新增类型常量，并支持 `watch` tier。

**Step 4: 跑测试**

Run:

```bash
python3 -m unittest tests.test_signal_policy -v
```

### Task 2: 新增强势启动检测模块

**Files:**
- Create: `chanlun/strong_startup.py`
- Test: `tests/test_strong_startup.py`

**Step 1: 写失败测试**

覆盖：

1. 低位 + 放量 + 突破 -> daily startup seed。
2. 高位放量大涨 -> dropped_high_position。
3. 无放量 -> dropped_no_volume。
4. 无突破 -> dropped_no_breakout。
5. 涨停 + 低位放量 -> `强势启动观察`，不是候选。
6. `000506` 类似数据：涨幅 10%、量比 1.7、启动前处于低位 -> `强势启动观察`。

**Step 2: 运行测试确认失败**

Run:

```bash
python3 -m unittest tests.test_strong_startup -v
```

**Step 3: 最小实现**

实现：

```python
build_strong_startup_pool(chan_results, sector_stocks=None)
```

输出：

```python
(startup_pool, startup_diag)
```

**Step 4: 跑测试**

Run:

```bash
python3 -m unittest tests.test_strong_startup -v
```

### Task 3: 30min 启动确认

**Files:**
- Modify: `chanlun/strong_startup.py`
- Test: `tests/test_strong_startup.py`

**Step 1: 写失败测试**

覆盖：

1. 30min回踩不破突破位 -> `强势启动候选`
2. 30min EMA5/EMA10维持 -> `强势启动候选`
3. 无30min确认 -> `强势启动观察`
4. 涨停启动 -> `强势启动观察`

**Step 2: 运行测试确认失败**

Run:

```bash
python3 -m unittest tests.test_strong_startup -v
```

**Step 3: 最小实现**

实现：

```python
upgrade_strong_startup_with_30min(startup_pool, chan_results_30min)
```

**Step 4: 跑测试**

Run:

```bash
python3 -m unittest tests.test_strong_startup -v
```

### Task 4: 接入 run.py

**Files:**
- Modify: `run.py`
- Test: `tests/test_strong_startup_pipeline.py`

**Step 1: 写失败测试**

覆盖：

1. 30min 拉取目标包含 startup pool。
   - 只包含非涨停 startup seed。
   - 涨停 startup watch 不应为了当日主推荐触发 30min 拉取。
2. final picks 包含 `强势启动候选`。
3. watch list 包含 `强势启动观察`。
4. diagnostics 包含 `strong_startup`。
5. `ENABLE_STRONG_STARTUP_CANDIDATES=False` 时，不改变原有 pure/fusion 结果。

**Step 2: 运行测试确认失败**

Run:

```bash
python3 -m unittest tests.test_strong_startup_pipeline -v
```

**Step 3: 最小实现**

接入流程：

```text
pure_pool
startup_pool
all_target_codes = pure_pool codes ∪ non_limit_startup_seed codes
pure_confirmed = existing upgrade
startup_confirmed, startup_watch = new upgrade
pure_confirmed = pure_confirmed + startup_confirmed
startup_watchlist = startup_watch
```

**Step 4: 跑测试**

Run:

```bash
python3 -m unittest tests.test_strong_startup_pipeline -v
```

### Task 5: 评分和排序

**Files:**
- Modify: `chanlun/scorer.py`
- Modify: `chanlun/fusion_admission.py`
- Test: `tests/test_scorer.py`
- Test: `tests/test_fusion_admission.py`

**Step 1: 写失败测试**

覆盖：

1. `强势启动候选` 排在 `底背驰候选` 前。
2. `强势启动观察` 不进入主推荐排序。
3. 放量质量影响 startup score。
4. 纯净版可保留满足确认的 `强势启动候选`。
5. 融合版对 `强势启动候选` 保留 MA 多头和大盘强弱门槛。
6. 未知类型不能因为新增规则被误放行。

**Step 2: 运行测试确认失败**

Run:

```bash
python3 -m unittest tests.test_scorer -v
```

**Step 3: 最小实现**

新增 startup score、排序优先级，以及 `fusion_admission._admit()` 对 `强势启动候选` 的显式门控。

**Step 4: 跑测试**

Run:

```bash
python3 -m unittest tests.test_scorer -v
```

### Task 6: 页面分区展示

**Files:**
- Modify: `chanlun/report_generator.py`
- Test: `tests/test_report_generator.py`

**Step 1: 写失败测试**

覆盖：

1. HTML 有“主推荐：已启动”区。
2. HTML 有“启动观察”区。
3. HTML 有“低吸观察”区。
4. 顶部摘要包含 startup counts。
5. `强势启动观察` 显示 `next_day_conditions`。
6. `startup_watchlist` 不为空时，即使主推荐为空也要展示启动观察区。

**Step 2: 运行测试确认失败**

Run:

```bash
python3 -m unittest tests.test_report_generator -v
```

**Step 3: 最小实现**

重构 pick table 渲染为分区。

**Step 4: 跑测试**

Run:

```bash
python3 -m unittest tests.test_report_generator -v
```

### Task 7: QA 脚本增强

**Files:**
- Modify: `scripts/qa_signal_invariants.py`
- Test: `tests/test_signal_invariants.py`

**Step 1: 写失败测试**

覆盖强势启动不变量：

1. `强势启动候选` 有 startup fields。
2. `强势启动候选` 有 30min confirmation。
3. `强势启动观察` 不在 `buy_points` 主推荐里。
4. `startup_watchlist` 中每项都有 `watch_reason` 和 `next_day_conditions`。
5. 同一股票如果同时有 formal/candidate 买点和 `强势启动观察`，主推荐里的 `buy_points` 不能包含 `强势启动观察` 这个 buy point；页面可在观察区另行展示同 code。

**Step 2: 运行测试确认失败**

Run:

```bash
python3 -m unittest tests.test_signal_invariants -v
```

**Step 3: 最小实现**

更新 QA 脚本。

**Step 4: 跑测试**

Run:

```bash
python3 -m unittest tests.test_signal_invariants -v
```

## 11. 回归 QA

### 11.1 单测

必须通过：

```bash
python3 -m unittest tests.test_signal_policy -v
python3 -m unittest tests.test_strong_startup -v
python3 -m unittest tests.test_strong_startup_pipeline -v
python3 -m unittest tests.test_scorer -v
python3 -m unittest tests.test_report_generator -v
python3 -m unittest tests.test_signal_invariants -v
python3 -m unittest discover -s tests -p 'test_*.py'
```

### 11.2 2026-05-26 回归

Run:

```bash
python3 run.py --date 2026-05-26 --debug
python3 scripts/qa_signal_invariants.py docs/data/2026-05-26.json
```

检查：

1. `strong_startup.daily_startup_seed > 0`
2. `强势启动候选` 或 `强势启动观察` 有输出
3. `000506 招金黄金` 应进入 `startup_watchlist`，如果在股票池内
4. `600547 山东黄金` 可继续作为 `底背驰候选` 或 startup，取决于是否满足突破条件
5. 页面分区显示正确
6. `ENABLE_STRONG_STARTUP_CANDIDATES=False` 后，原 2026-05-26 pure/fusion 数量和类型分布不应变化。
7. fusion 版中 `强势启动候选` 应体现 MA 多头和大盘强弱过滤，不能和 pure 无差异。

### 11.3 人工图形验收

抽查：

1. 招金黄金类涨停启动票：
   - 显示在启动观察
   - 不进入当日主推荐买入
   - 有次日确认条件

2. 非涨停放量突破票：
   - 若有 30min 确认，进入强势启动候选

3. 普通底背驰票：
   - 仍显示在低吸观察
   - 不混入主推荐

## 12. 风险与控制

### 12.1 风险

1. 强势启动规则过松，变成追涨榜。
2. 强势启动规则过严，仍选不出启动票。
3. 涨停票被误放进主推荐，诱导追高。
4. 与底背驰候选混在一起，页面仍然看不清。

### 12.2 控制

1. 涨停票只进观察，不进主推荐。
2. 强势启动必须有低位约束。
3. 主推荐必须有 30min 确认。
4. 页面分区强制区分“已启动可跟踪”和“低吸观察”。
5. diagnostics 必须展示每层流失原因。

## 13. 自 Review 清单

这份 spec 已自 review，确认如下：

1. 没有删除现有底背驰候选通道。
2. 没有把涨停票直接作为可买主推荐。
3. 强势启动候选有低位、放量、突破、30min 确认四层约束。
4. 招金黄金这类低位放量涨停会进入启动观察，而不是被静默排除。
5. 页面要求主推荐、启动观察、低吸观察分区，避免用户误读。
6. QA 明确要求 2026-05-26 回归和招金黄金案例验证。
7. 已明确强势启动扫描必须基于原始 `chan_results`，避免涨停票被现有结构池基础过滤提前排除。
8. 已明确 `强势启动观察` 单独进入 `startup_watchlist`，不污染主推荐。
9. 已加配置开关，支持关闭后回归旧结果。
10. 已明确 pure/fusion 对强势启动的差异，避免新增通道让两个版本再次选股完全一样。
11. 已明确涨停观察不触发当日 30min 拉取，避免无意义变慢。
