# Report Quality, Visualization, Data Reliability Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在不硬过滤强势启动候选的前提下，提高报告的解释性、事件 Top10 可靠性、页面可读性、数据包效率和前端安全性，并修复 K 线展开图 MACD 不显示的问题。

**Architecture:** 保留现有选股主流程，新增“日线启动形态标注”和“30min 确认质量评级”作为解释/排序字段，不作为硬过滤条件。事件 Top10 改为规则评分优先、LLM 仅解释增强；报告 JSON 删除已不渲染的 30min K 线数组；前端统一 escape 外部文本；MACD 在数据生成侧计算真实值。

**Tech Stack:** Python 3, `unittest`, static HTML/JS, ECharts, existing `run.py`, `chanlun/strong_startup.py`, `chanlun/market_news.py`, `chanlun/report_generator.py`, `tests/`.

---

## 1. Scope

本次合并处理 8 个需求：

1. `强势启动候选` 允许负涨幅/小涨幅，不硬过滤，只在页面做风险/形态提示。
2. `30min确认` 不直接改紧，先做确认等级/影子评级，保留测试 demo 数据，避免筛到 0。
3. `A股影响力事件 Top10` 改成可解释的影响力评分筛查，不再泛泛按最新新闻或简单 stock/plate 数量排序。
4. LLM 失败后信息塌陷本轮不处理，保持现状。
5. 页面可视化从表格堆信息改成“摘要卡 + 标签 + 可展开细节”。
6. 删除报告 JSON 中已不用的 30min K 线冗余字段。
7. 前端统一 HTML escape 外部/动态文本。
8. 修复展开 K 线图 MACD 不展示的问题。

## 2. Non-Goals

1. 不删除负涨幅/小涨幅 `强势启动候选`。
2. 不把 30min 二买/三买作为硬门槛。
3. 不改变 `picks_pure/picks_fusion` 的主筛选入口和历史访问控制逻辑。
4. 不恢复 30min K 线/成交量图。
5. 不在本轮修复 LLM 调用失败、JSON 解析失败或重试策略。
6. 不让 LLM 决定事件排序；LLM 只补充解释。
7. 不做新的外部新闻源接入。

## 3. Evidence From Current Data

基于当前 `docs/data/2026-05-26.json` 和 `docs/data/2026-05-27.json` 的 demo：

```text
2026-05-26 fusion 强势启动：
  当前任意 30min 确认: 4
  严格要求 30min 二买/三买: 0
  要求 EMA5 + 回踩不破/二三买: 0
  要求日线硬启动 + 任意30min确认: 3
  要求正涨幅 + 任意30min确认: 4

2026-05-27 fusion 强势启动：
  当前任意 30min 确认: 11
  严格要求 30min 二买/三买: 0
  要求 EMA5 + 回踩不破/二三买: 0
  要求日线硬启动 + 任意30min确认: 5
  要求正涨幅 + 任意30min确认: 10
```

结论：

1. 不能直接把 `30min 二买/三买` 设成硬过滤，否则当前样本会筛到 0。
2. 可以先引入确认等级，用于排序/展示/复盘。
3. 未来如果复盘证明低等级效果差，再升级为过滤条件。

## 4. Data Model Changes

### 4.1 Strong Startup Labels

在强势启动候选的 `best_buy_point` 中新增字段：

```json
{
  "daily_startup_grade": "strong | weak | pullback",
  "daily_startup_label": "强启动 | 弱启动确认 | 回踩型启动观察",
  "daily_startup_warning": "当日收跌，属于观察型启动，不是追涨启动",
  "sublevel_confirm_grade": "S | A | B | C",
  "sublevel_confirm_label": "S级确认 | A级确认 | B级确认 | C级确认",
  "sublevel_confirm_reason": "30min EMA5维持；未出现二买/三买"
}
```

定义：

```text
daily_startup_grade:
  strong:
    change_pct >= 4
    OR startup_signals 包含 break_20d_high
    OR startup_reason 包含 突破20日平台/突破中枢

  weak:
    change_pct >= 0
    AND 不满足 strong

  pullback:
    change_pct < 0

sublevel_confirm_grade:
  S:
    confirmations 包含 30min 二买/三买

  A:
    daily_startup_grade == strong
    AND confirmations 包含 30min EMA5维持

  B:
    confirmations 非空
    AND 不满足 S/A

  C:
    confirmations 为空
```

要求：

1. 这些字段只作为解释、排序和页面提示，不作为硬过滤。
2. 负涨幅/小涨幅票仍可进入 `picks_pure/picks_fusion`。
3. 本轮不改变现有推荐集合和排序，只展示 `daily_startup_*` / `sublevel_confirm_*` 标签和摘要统计；如果后续要按 S/A/B/C 排序，必须单独确认。

### 4.2 Event Impact Fields

每条事件新增/稳定以下字段：

```json
{
  "impact_score": 0,
  "impact_level": "重大 | 较强 | 一般 | 微弱",
  "impact_reason": "政策催化+15；命中半导体资金流Top3+22",
  "affected_themes": ["半导体", "AI算力"],
  "matched_hot_sectors": ["半导体"],
  "market_validation": "半导体资金流Top3；关联主题涨停3只",
  "validation_details": {
    "sector_rank": 2,
    "sector_flow": 123456789,
    "limit_up_theme_count": 3,
    "limit_up_stock_count": 1
  },
  "event_category": "policy | industry | tech | earnings | order | mna | risk | commodity | overseas | company_reply | other",
  "tradability": "强 | 中 | 弱",
  "downgrade_reasons": ["公司称不会对业绩产生重大影响"]
}
```

### 4.3 JSON Field Removal

从 `picks_pure` 和 `picks_fusion` 的报告 JSON 中删除以下字段：

```text
has_30min
dates_30min
closes_30min
opens_30min
highs_30min
lows_30min
volumes_30min
```

保留：

```text
buy_points_30min
best_buy_point.confirmed_by
best_buy_point.confirmations
best_buy_point.confirm_date
best_buy_point.confirm_age_days
```

理由：

1. 页面已不渲染 30min K 线/成交量图。
2. 这些数组占用大量 JSON 体积。
3. 保留确认摘要即可解释 30min 作用。

## 5. Event Top10 Scoring Design

### 5.1 Candidate Pool

保持：

```python
fetch_cls_news(CLS_NEWS_COUNT)
```

配置应保持 `CLS_NEWS_COUNT = 100`。

### 5.2 Theme Classification

扩展 `THEME_SYNONYMS`，至少覆盖：

```python
{
    "半导体": ["半导体", "芯片", "存储", "长江存储", "长鑫存储", "晶圆", "先进封装", "光刻机", "靶材", "封测", "EMC"],
    "AI算力": ["AI", "人工智能", "大模型", "算力", "服务器", "数据中心", "GPU", "液冷"],
    "光模块": ["光模块", "CPO", "800G", "1.6T", "光通信"],
    "机器人": ["机器人", "人形机器人", "减速器", "执行器", "伺服"],
    "低空经济": ["低空经济", "eVTOL", "无人机", "通航", "飞行汽车"],
    "固态电池": ["固态电池", "电解质", "锂电", "动力电池"],
    "白酒": ["白酒", "酒企", "高端酒", "酱酒"],
    "电力": ["电力", "火电", "水电", "绿电", "电网", "虚拟电厂"],
    "煤炭": ["煤炭", "焦煤", "动力煤", "煤价"],
    "大消费": ["消费", "促消费", "社零", "食品饮料", "零售"]
}
```

### 5.3 Event Category

新增：

```python
classify_event_type(event) -> str
```

规则示例：

```text
policy:
  国务院、发改委、工信部、财政部、证监会、政策、规划、指导意见

industry:
  涨价、供需、订单潮、产能、景气度、库存、价格上行

tech:
  技术突破、量产、首发、国产替代、先进制程、新产品

earnings:
  业绩预增、利润增长、收入增长、财报

order:
  中标、订单、合同、供货、供应商

mna:
  并购、重组、收购、增资

risk:
  减持、解禁、监管处罚、立案、业绩下滑

commodity:
  期货、现货、商品价格，仅在映射到 A 股产业链时保留中等分

overseas:
  海外军事/政治/公司事件，无 A 股映射时降权

company_reply:
  互动平台、投资者关系回复，默认低权重，除非有明确订单/客户/产能
```

### 5.4 Score Formula

在 `score_market_impact(event, sector_flow, limit_up_pool=None)` 中按以下方式累计：

```text
财联社 level:
  A/3: +24
  B/2: +16
  C/1: +8

A股映射强度:
  明确主题 +8
  明确个股 +5
  明确板块 +6

事件类型:
  policy +18
  industry +15
  tech +15
  earnings +12
  order +12
  mna +10
  company_reply +3
  commodity +5
  overseas +2
  risk +8

热门板块验证:
  主题/板块命中资金流 Top3 +22
  命中 Top10 +12
  命中但资金流非正 +3

涨停验证:
  新闻自带个股在涨停池 +10/只，上限20
  主题映射到涨停池主题/名称 +6/只，上限18

可交易性:
  有主题 + 有板块验证 +8
  有主题 + 有涨停验证 +8
  只有单个公司公告 +0

降权:
  出现“不构成重大影响/不会对业绩产生重大影响/投资规模较小” -15
  纯海外且无 A 股主题 -12
  纯商品期货且无 A 股主题 -8
  重复标题/同主题重复弱新闻 -5
```

等级：

```text
impact_score >= 55: 重大
impact_score >= 35: 较强
impact_score >= 18: 一般
else: 微弱
```

可交易性：

```text
强:
  impact_score >= 45
  AND (有热门板块验证 OR 有涨停验证)

中:
  impact_score >= 25
  AND 有 A 股主题

弱:
  其他
```

### 5.5 Ranking Rules

```python
rank_market_impact_events(events, sector_flow, limit_up_pool=None, top_n=10)
```

排序：

```text
1. impact_score desc
2. tradability 强 > 中 > 弱
3. 财联社 level desc
4. ctime desc
```

去重：

1. 标题完全相同只保留一条。
2. 同一 `affected_themes[0] + event_category` 超过 3 条时，后续重复降权但不强删。

## 6. UI Design

### 6.1 Top Summary Cards

在页面顶部现有市场指数下方新增一行摘要卡：

```text
今日推荐：fusion 11 / pure 80
主信号：强势启动 11，只保留启动类
市场状态：弱市，MA过滤 87 只
风险提示：B级确认 6 只，回踩型 1 只
```

数据来源：

```text
REPORT_DATA.picks_pure
REPORT_DATA.picks_fusion
REPORT_DATA.diagnostics.fusion_admission
best_buy_point.daily_startup_grade
best_buy_point.sublevel_confirm_grade
```

### 6.2 Pick Table

主表新增/调整字段：

```text
代码
名称
信号类型
启动形态
30min确认
信号年龄
参考价
现价
距参考价
评分
一句话原因
```

融合版额外保留：

```text
融合版
止损
```

展示规则：

```text
daily_startup_label:
  强启动 -> 红色/高亮
  弱启动确认 -> 橙色
  回踩型启动观察 -> 蓝灰色 + 提示

sublevel_confirm_label:
  S级确认 -> 红色
  A级确认 -> 橙色
  B级确认 -> 黄色
  C级确认 -> 灰色
```

如果不是 `强势启动候选`，对应列显示 `-`。

### 6.3 Expanded K-Line Detail

展开区域必须显示：

```text
日线K线 + 日线MACD
信号发生日
参考价/现价/距离
启动形态与解释
30min确认等级与解释
完整原因
融合版约束
风险提示
```

边界：

1. 不显示 30min K 线/成交量子图。
2. 不改变主 K 线 tooltip 模式，保持 `trigger: 'axis'`。
3. K 线 X 轴不能出现价格值，例如 `3.68/4.08`。

### 6.4 Event Cards

`A股影响力事件 Top10` 每条显示：

```text
排名
impact_score + impact_level
tradability
event_category 中文名
标题
影响理由 impact_reason
主题 affected_themes
盘面验证 market_validation
降权原因 downgrade_reasons
LLM headline/analysis（如果存在）
查看原文
```

页面文案：

```text
A股影响力事件 Top10
按事件重要性、主题映射、资金流、涨停验证综合排序；不是最新新闻列表。
```

## 7. HTML Escape

### 7.1 Helper

在前端 JS 中新增：

```javascript
function escapeHtml(value) {
    if (value === null || value === undefined) return '';
    return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}
```

### 7.2 Must Escape

以下所有动态文本必须 escape：

```text
股票代码/名称
信号原因
启动原因
观察理由
确认原因
事件标题
事件原文
LLM headline
LLM analysis
LLM sector/stock/reason
板块名称
风险提示
历史日期按钮文本
```

### 7.3 Do Not Escape

只允许不 escape 的内容：

1. 代码内部固定 HTML 标签。
2. 代码内部固定 class/style。
3. 数值格式化结果。

## 8. MACD Bug Fix

### 8.1 Root Cause

强势启动候选在 `run.py` 中构造 pick 时写死：

```python
"macd_hist": np.zeros(len(sc.get("closes", [])))
```

因此当 fusion 结果全是强势启动候选时，展开图 MACD 数据全为 0，页面看起来就是没有 MACD。

### 8.2 Required Fix

在 `run.py` 构造强势启动 pick 时：

```python
from chanlun.chan_engine import calc_macd

closes = sc.get("closes", [])
_, _, macd_hist = calc_macd(closes)
```

写入：

```python
"macd_hist": macd_hist
```

注意：

1. 必须用完整 `closes` 计算 MACD，再由 `report_generator._serialize_picks()` 切片。
2. 不要用切片后的 28-50 根重新计算，否则 EMA warmup 可能得到全 `NaN`。
3. `_safe_list()` 应把 `NaN` 转成 `0.0` 或 `None`，但不能把已有真实非零 hist 覆盖成全 0。

### 8.3 Serialization Fallback

在 `_serialize_picks()` 中：

```text
如果 p["macd_hist"] 缺失、长度不匹配、或全 0 且 closes 足够长：
  使用完整 closes 重新 calc_macd
  再切片
```

但 fallback 不能掩盖上游错误，建议同时在 diagnostics 或测试中覆盖。

## 9. Implementation Tasks

### Task 1: Add Strong Startup Label Helpers

**Files:**
- Modify: `chanlun/strong_startup.py`
- Modify: `run.py`
- Test: `tests/test_strong_startup.py` or create `tests/test_startup_labels.py`

**Step 1: Write failing tests**

Create tests for:

```python
def test_daily_startup_grade_pullback_for_negative_change():
    bp = annotate_startup_quality({
        "change_pct": -3.65,
        "startup_signals": ["close_above_ma5"],
        "confirmations": ["30min回踩不破突破位"],
    })
    assert bp["daily_startup_grade"] == "pullback"
    assert bp["daily_startup_label"] == "回踩型启动观察"

def test_daily_startup_grade_strong_for_breakout_even_small_gain():
    bp = annotate_startup_quality({
        "change_pct": 2.58,
        "startup_signals": ["break_20d_high"],
        "confirmations": ["30min EMA5维持"],
    })
    assert bp["daily_startup_grade"] == "strong"

def test_sublevel_grade_b_for_ema_only_confirmation():
    bp = annotate_startup_quality({
        "change_pct": 2.58,
        "startup_signals": [],
        "confirmations": ["30min EMA5维持"],
    })
    assert bp["sublevel_confirm_grade"] == "B"
```

**Step 2: Implement helper**

Suggested helper:

```python
def annotate_startup_quality(signal):
    ...
    return signal
```

Call it before putting data into `best_buy_point` and `buy_points`.

**Step 3: Verify**

Run:

```bash
python3 -m unittest tests.test_startup_labels -v
python3 -m unittest discover -s tests -p 'test_*.py'
```

Expected:

```text
OK
```

### Task 2: Add 30min Shadow QA Demo

**Files:**
- Create: `scripts/qa_startup_confirm_grades.py`
- Test: optional `tests/test_startup_confirm_qa.py`

**Script behavior:**

```bash
python3 scripts/qa_startup_confirm_grades.py docs/data/2026-05-27.json
```

Output:

```text
fusion startup total: 11
S: 0
A: 5
B: 6
C: 0
would_keep_if_require_buy23: 0
would_keep_if_require_daily_hard_plus_any_confirm: 5
```

Purpose:

1. 给用户确认“改紧之后会不会选不到票”。
2. 后续如果要把等级变硬过滤，有历史数据对比。

### Task 3: Rewrite Market Impact Scoring

**Files:**
- Modify: `chanlun/market_news.py`
- Modify: `tests/test_market_news.py`

**Step 1: Tests**

Add tests:

```python
def test_policy_with_hot_sector_ranks_above_company_reply():
    ...

def test_company_reply_with_no_major_impact_is_downgraded():
    ...

def test_theme_limit_up_validation_scores_even_without_stock_list():
    ...

def test_pure_overseas_without_a_share_mapping_is_downgraded():
    ...

def test_rank_market_impact_events_uses_score_then_tradability_then_level():
    ...
```

**Step 2: Implement**

Add:

```python
classify_event_type(event)
score_market_validation(event, sector_flow, limit_up_pool, themes)
dedupe_or_downgrade_events(events)
```

Update `score_market_impact()`.

**Step 3: Verify**

Run:

```bash
python3 -m unittest tests.test_market_news -v
```

Expected:

```text
OK
```

### Task 4: Fix MACD For Strong Startup Picks

**Files:**
- Modify: `run.py`
- Modify: `chanlun/report_generator.py`
- Test: `tests/test_report_generator.py`

**Step 1: Tests**

Add test:

```python
def test_serialize_strong_startup_recomputes_macd_when_zero_placeholder():
    pick = make_pick(bp_type="强势启动候选", with_30min=False)
    pick["closes"] = np.linspace(10, 20, 80)
    pick["macd_hist"] = np.zeros(80)
    serialized = _serialize_picks([pick])
    assert any(abs(v) > 0 for v in serialized[0]["macd_hist"])
```

**Step 2: Implement**

1. Replace `np.zeros(...)` in `run.py`.
2. Add safe fallback in `_serialize_picks()`.

**Step 3: Verify**

Run:

```bash
python3 -m unittest tests.test_report_generator -v
```

Expected:

```text
OK
```

### Task 5: Remove 30min Chart Arrays From Report JSON

**Files:**
- Modify: `chanlun/report_generator.py`
- Modify: `tests/test_report_generator.py`

**Step 1: Update tests**

Replace old tests expecting 30min arrays:

```python
def test_serialize_picks_omits_30min_chart_arrays():
    pick = make_pick(with_30min=True)
    s = _serialize_picks([pick])[0]
    assert "dates_30min" not in s
    assert "opens_30min" not in s
    assert "highs_30min" not in s
    assert "lows_30min" not in s
    assert "closes_30min" not in s
    assert "volumes_30min" not in s
    assert "has_30min" not in s
```

Keep tests for:

```text
buy_points_30min
best_buy_point.confirmations
```

**Step 2: Implement**

Remove the fields from `_serialize_picks()`.

**Step 3: Verify generated data**

Run:

```bash
rg -n 'dates_30min|closes_30min|opens_30min|highs_30min|lows_30min|volumes_30min|has_30min' docs/data/2026-05-27.json
```

Expected after regeneration:

```text
no matches
```

### Task 6: Add Frontend Escape Helper

**Files:**
- Modify: `chanlun/report_generator.py`
- Test: `tests/test_report_generator.py`

**Step 1: Tests**

Generate report with malicious text:

```python
report_data["events"] = [{
    "title": "<img src=x onerror=alert(1)>",
    "impact": {"headline": "<script>alert(1)</script>", "analysis": ["<b>x</b>"]},
    ...
}]
```

Assert:

```python
self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
self.assertNotIn("<script>alert(1)</script>", html)
self.assertNotIn("onerror=alert", html)
```

**Step 2: Implement**

Add `escapeHtml()` in generated JS and use it everywhere dynamic text enters `innerHTML`.

**Step 3: Verify**

Run:

```bash
python3 -m unittest tests.test_report_generator -v
```

### Task 7: Improve Report Visualization

**Files:**
- Modify: `chanlun/report_generator.py`
- Test: `tests/test_report_generator.py`

**Step 1: Summary Cards**

Add:

```javascript
renderSelectionSummaryCards()
```

Call from `renderAll()` after market/structure render and before pick table.

**Step 2: Pick Table Labels**

Show:

```text
启动形态
30min确认
```

Only for `强势启动候选`; otherwise `-`.

**Step 3: Expanded Details**

Add detail rows for:

```text
启动形态
30min确认等级
确认解释
```

**Step 4: Event Cards**

Add subtitle and display:

```text
event_category
validation_details
downgrade_reasons
```

**Step 5: Test**

Assert generated HTML contains:

```text
function renderSelectionSummaryCards
启动形态
30min确认
A股影响力事件 Top10
按事件重要性、主题映射、资金流、涨停验证综合排序
```

### Task 8: Regenerate Report And QA

**Files:**
- Generated: `docs/index.html`
- Generated: `docs/data/2026-05-27.json`
- Generated: `docs/data.json`

Run:

```bash
python3 run.py --date 2026-05-27
```

If the project does not support `--date`, use the current documented command for single-day regeneration.

Then run:

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
python3 scripts/qa_signal_invariants.py docs/data/2026-05-27.json
python3 scripts/qa_startup_confirm_grades.py docs/data/2026-05-27.json
du -h docs/data/2026-05-27.json docs/data.json docs/index.html
rg -n 'dates_30min|closes_30min|opens_30min|highs_30min|lows_30min|volumes_30min|has_30min' docs/data/2026-05-27.json
```

Expected:

```text
unittest: OK
signal invariants: PASS
startup confirm grades: prints S/A/B/C distribution
rg 30min arrays: no matches
data file smaller than before, target < 1.6M for 2026-05-27
```

Manual browser QA:

1. Open `docs/index.html` or GitHub Pages URL.
2. Confirm fusion tab loads 2026-05-27.
3. Expand first fusion row.
4. Confirm K line X axis shows dates, not prices.
5. Confirm MACD panel has visible non-zero bars when data is non-zero.
6. Confirm no 30min K line/volume subplot appears.
7. Confirm `启动形态` and `30min确认` labels are visible.
8. Confirm event Top10 card shows score, reason, theme, validation.
9. Confirm malicious text test is escaped in generated HTML.

## 10. Acceptance Criteria

### Functional

1. Negative/small-gain `强势启动候选` remain selectable.
2. Every `强势启动候选` has `daily_startup_*` and `sublevel_confirm_*` fields.
3. 30min stricter criteria are reported by QA/demo script, not used as hard filter.
4. Event Top10 uses impact score with theme/market validation.
5. LLM failure handling remains unchanged.
6. Expanded K line MACD is no longer all zero for strong startup picks with enough closes.
7. Report JSON no longer contains 30min K line arrays.
8. Generated HTML escapes dynamic text.

### QA

1. `python3 -m unittest discover -s tests -p 'test_*.py'` passes.
2. `python3 scripts/qa_signal_invariants.py docs/data/2026-05-27.json` passes.
3. `python3 scripts/qa_startup_confirm_grades.py docs/data/2026-05-27.json` prints non-empty grade distribution.
4. Browser manual QA confirms K line/MACD/tooltip behavior.

### No Regressions

1. Do not reintroduce `trigger: 'item'` for candlestick tooltip.
2. Do not reintroduce 30min chart subplot.
3. Do not hide all B/C startup candidates.
4. Do not remove access control.
5. Do not make event ranking depend on LLM success.

## 11. Self-Review

Review results before handoff:

1. Confirmed requirement 1 and 2 are not conflicting: `daily_startup_grade` describes 日线形态, `sublevel_confirm_grade` describes 30min 确认质量.
2. Confirmed spec does not hard-filter negative/small-gain startup candidates.
3. Confirmed 30min stricter logic is only shadow QA/demo, because current data would produce 0 if requiring 30min 二买/三买.
4. Confirmed event Top10 has concrete score formula, theme matching, market validation, downgrade rules, and sorting order.
5. Confirmed LLM failure is explicitly non-goal/pass.
6. Confirmed MACD root cause is addressed at source (`run.py`) and with serialization fallback.
7. Confirmed 30min chart arrays are removed from JSON, while text confirmations are preserved.
8. Confirmed HTML escape applies to external data and LLM/news text.
9. Confirmed tooltip boundary is explicit: no unrequested change to candlestick tooltip mode.
10. Confirmed generated docs/data/html QA is included, not only unit tests.
