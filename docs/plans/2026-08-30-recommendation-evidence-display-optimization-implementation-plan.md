# 推荐票证据展示综合优化 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在不改变正式选股、池成员、排序、评分、动作、市场情绪和 14:47 链路的前提下，为日报增加推荐票横向比较、八模块证据详情、PSY12 从属展示、真实关键价格图层和历史验证提醒，并完成三种视口的真实页面验收。

**Architecture:** 新增纯只读 `chanlun/recommendation_evidence.py`，同时读取原始正式报告和已经序列化的 `daily_data`，生成独立的 HTML 展示平面 `CHANLUN_BOOTSTRAP.recommendationEvidence`。展示平面不进入 `docs/data/YYYY-MM-DD.json`、`data.json`、`workspace`、正式池、账本、数据库或预跑快照，因此现有正式报告 digest 与生产 guard 无需放宽；前端只按 `view + code` 将证据与现有 workspace 行关联。所有缺失、陈旧、冲突和样本不足都 fail-closed，唯一正式动作始终来自 `formal_decision_contract.action`。

**Tech Stack:** Python 3.9、`unittest`、Vanilla JavaScript、CSS、ECharts、Node VM 前端契约测试、真实 Chromium 页面截图、GitHub Pages。

---

## 0. 已确认边界与基线

- 设计来源：`docs/plans/2026-08-30-recommendation-evidence-display-optimization-design.md`
- 原始设计 SHA-256：`680a90894a6943535402f2b5c40ead8f3df7188595813be3e3c61808dabe9f85`
- 用户确认后的设计 SHA-256：`d69effb8060057a14d4a7f68b9cfa9cf084d7642fb0e76b7ec023796c70651ac`
- 实施基线：`origin/main = 1e2f82d8335a8ad8c0d9064cff4168035cd88831`
- 基线全量测试：`/usr/bin/python3 -m unittest discover -s tests`，1521 tests，exit 0。
- 现有 chart-signal-lane 已在 main；本计划必须复用信号车道、成交量、MACD、价格标签碰撞治理，不得回退。
- 不修改 `run.py` 选股阶段、`decision_engine.py`、`scoring_engine.py`、各筛选器、`market_sentiment.py` 正式公式、preclose、ledger/store、launchd、Worker。
- 不把展示对象写进正式 JSON。线上 JSON 用于证明正式数据未变；线上 HTML Bootstrap 用于回读展示投影。
- 不新增默认压力位、失效位、目标价、成本价、资金流或成功概率。
- 默认 `python3` 是 3.7.9；本项目的验证和生产运行统一使用 `/usr/bin/python3` 3.9.6。
- 用户要求最终远端历史保持一个干净提交，因此任务间不创建远端提交；最终同步最新 main 后一次性提交。必要的本地 checkpoint 必须在最终 push 前 squash 为一个提交。

## Task 1: 建立展示平面与正式数据隔离护栏

**Files:**
- Create: `chanlun/recommendation_evidence.py`
- Create: `tests/test_recommendation_evidence.py`
- Modify: `chanlun/report_generator.py`
- Modify: `tests/test_report_generator.py`

**Step 1: Write the failing tests**

新增测试：

```python
def test_evidence_projection_does_not_mutate_formal_report_or_daily_projection():
    ...

def test_report_bootstrap_contains_evidence_but_daily_json_does_not():
    ...

def test_formal_and_aggregate_digests_are_identical_before_and_after_evidence_build():
    ...

def test_projection_is_strict_json_without_nan_or_infinity():
    ...
```

测试必须深拷贝原始 `report_data` 与 `daily_data`，调用展示投影后逐字比较；还要断言 `recommendationEvidence` 只存在于 Bootstrap envelope，不在 `build_full_daily_projection()`、`build_aggregate_day_projection()` 或 workspace 行中。

**Step 2: Run RED**

Run:

```bash
/usr/bin/python3 -m unittest \
  tests.test_recommendation_evidence \
  tests.test_report_generator -v
```

Expected: FAIL because `chanlun.recommendation_evidence` and the Bootstrap projection do not exist.

**Step 3: Implement the minimal display plane**

新增：

```python
def build_recommendation_evidence_projection(formal_report, daily_data):
    return {
        "schema_version": 1,
        "report_date": str(daily_data.get("date") or ""),
        "views": {},
        "market_sentiment": {},
    }
```

在 `report_generator.py` 提取 `_build_report_bootstrap(...)`，生成 `inlineReportData` 后单独加入：

```python
bootstrap["recommendationEvidence"] = build_recommendation_evidence_projection(
    report_data,
    daily_data,
)
```

不得改动 `_serialize_picks()`、`build_full_daily_projection()`、`build_aggregate_day_projection()` 或任何 digest helper。

**Step 4: Run GREEN and invariants**

Run the same command and confirm PASS. Then run:

```bash
git diff --check
git status --short --untracked-files=all
```

Expected: only the four allowed implementation/test files plus the two exact plan files.

## Task 2: 建立统一证据状态合同与推荐结论/决策分/排序证据

**Files:**
- Modify: `chanlun/recommendation_evidence.py`
- Modify: `tests/test_recommendation_evidence.py`
- Modify: `tests/test_report_view_model.py`

**Step 1: Write failing tests**

新增：

```python
def test_projection_contains_all_eleven_evidence_sections_with_status_metadata():
    ...

def test_formal_action_only_comes_from_formal_decision_contract():
    ...

def test_decision_score_never_falls_back_to_opportunity_score():
    ...

def test_rank_evidence_preserves_view_rank_and_existing_order():
    ...

def test_missing_evidence_is_missing_not_zero_or_default_score():
    ...
```

每只票必须有完整 11 个键：

```text
summary
decision_score
rank_evidence
price_evidence
daily_structure
sublevel_30m
volume_and_capital
market_and_sector
risk_and_next
historical_validation
display_derived
```

每个模块至少包含 `status`，并包含 `as_of`、`source` 或 `reason` 之一。

**Step 2: Run RED**

Run:

```bash
/usr/bin/python3 -m unittest \
  tests.test_recommendation_evidence \
  tests.test_report_view_model -v
```

Expected: FAIL on missing schema and score/rank separation.

**Step 3: Implement minimal mapping**

- 按 workspace `view_order` 和现有行顺序生成 `views[view]`，禁止重新排序。
- 以 `row.ref.pool + row.code` 找到序列化 raw；找不到时保持 workspace 事实并将模块标为 missing。
- `summary.formal_action` 只读 `row.formal_decision_contract.action`。
- `decision_score` 数值只读 `decision_engine_v1.total_score`，并读取
  `structure/position/sentiment` 分项；`score`、`final_score` 和
  `opportunity_score` 都不得作为 fallback。
- `rank_evidence` 只读 `view_rank`、`opportunity_score`、`rank_trace`，标注“仅用于当前池内排序”。
- 保留 `decision_code`，但不生成第二个动作。

**Step 4: Run GREEN**

Run the same command; then run `git diff --check`.

## Task 3: 完成价格证据、展示派生值与风险/下一步的 fail-closed 投影

**Files:**
- Modify: `chanlun/recommendation_evidence.py`
- Modify: `tests/test_recommendation_evidence.py`

**Step 1: Write failing tests**

新增：

```python
def test_non_positive_or_non_finite_prices_are_missing():
    ...

def test_conflicting_formal_prices_are_hidden_but_audit_reason_is_preserved():
    ...

def test_price_distance_upside_downside_and_rr_require_real_boundaries():
    ...

def test_missing_pressure_invalidation_and_targets_do_not_create_defaults():
    ...

def test_strategy_without_next_condition_uses_declared_missing_copy():
    ...
```

**Step 2: Run RED**

```bash
/usr/bin/python3 -m unittest tests.test_recommendation_evidence -v
```

**Step 3: Implement minimal adapters**

- 只接受 finite 且大于 0 的价格。
- 正式合同 diagnostics 出现 conflict/invalid 时隐藏对应值，并保留审计原因。
- `display_derived` 只计算现价与参考价偏离、压力上行空间、失效下行空间、真实上下边界齐全时的风险收益比。
- `trailing_targets` 逐个过滤，不生成固定百分比目标。
- 优先使用正式 invalidation；仅在正式值缺失且 raw `stop_loss` 为真实正数时，以来源标记展示。
- `risk_and_next` 只映射已声明的 risk/upgrade/keep/retest/cancel/invalidation；未声明时写“当前策略未声明……”，不写“暂无新增确认条件”。

**Step 4: Run GREEN and mutation check**

同一 fixture 重复构建两次，结果必须 deterministic；原报告必须逐字不变。

## Task 4: 新增推荐池完整横向比较，不产生第二套排序

**Files:**
- Modify: `chanlun/report_assets/report-v2.js`
- Modify: `chanlun/report_assets/report-v2.css`
- Modify: `tests/test_auxiliary_frontend.py`

**Step 1: Write failing Node VM tests**

新增：

```python
def test_candidate_evidence_comparison_preserves_workspace_order():
    ...

def test_comparison_distinguishes_formal_action_decision_score_and_rank_evidence():
    ...

def test_comparison_has_no_sort_control_or_third_composite_score():
    ...

def test_mobile_comparison_uses_ticket_cards_and_desktop_uses_own_scroll_region():
    ...

def test_comparison_escapes_all_evidence_text():
    ...
```

**Step 2: Run RED**

```bash
/usr/bin/python3 -m unittest tests.test_auxiliary_frontend -v
```

Expected: FAIL because comparison renderer does not exist.

**Step 3: Implement comparison UI**

新增 `getRecommendationEvidenceProjection()`、`getEvidenceRowsForView()`、`renderCandidateEvidenceComparison()`。

桌面列展示：

- 原 `view_rank`
- 股票/代码/行业
- 唯一正式动作
- 决策代码与决策分项
- 排序证据
- 信号/日期/新鲜度
- 现价/参考价/偏离
- 日线/30 分钟状态
- 量价/资金
- 板块状态
- 风险
- 数据状态

不得复用 `/compare` 历史收益排序页，不得在浏览器重新排序。390px 转逐票证据卡。

**Step 4: Run GREEN**

Run targeted test, `node --check chanlun/report_assets/report-v2.js`, and `git diff --check`.

## Task 5: 将个股详情重组为八个完整模块

**Files:**
- Modify: `chanlun/report_assets/report-v2.js`
- Modify: `chanlun/report_assets/report-v2.css`
- Modify: `tests/test_auxiliary_frontend.py`

**Step 1: Write failing tests**

新增：

```python
def test_candidate_detail_renders_eight_modules_in_required_order():
    ...

def test_detail_renders_exactly_one_formal_action():
    ...

def test_detail_uses_real_missing_copy_instead_of_zero_or_placeholder_target():
    ...

def test_detail_exposes_source_date_and_status_metadata():
    ...

def test_incident_review_never_restores_executable_action():
    ...
```

**Step 2: Run RED**

```bash
/usr/bin/python3 -m unittest tests.test_auxiliary_frontend -v
```

**Step 3: Implement eight renderers**

按顺序建立：

```text
01 推荐结论
02 价格与关键位置
03 日线结构
04 30分钟确认
05 量价与资金
06 市场与板块共振
07 风险与下一步
08 历史验证与回测提醒
```

`buildMergedCandidateDetail()` 只消费证据投影；图表保留在 02 与 03 之间的上部区域，但不能替代八模块。审计抽屉继续保留底层原因。

**Step 4: Run GREEN**

运行 targeted suite 和 `node --check`。

## Task 6: 将 PSY12 归并为正式市场情绪的影子子面板

**Files:**
- Create: `chanlun/psy12_shadow_audit.py`
- Modify: `chanlun/recommendation_evidence.py`
- Modify: `chanlun/report_generator.py`
- Modify: `scripts/evaluate_market_sentiment_psy12_shadow.py`
- Modify: `chanlun/report_assets/report-v2.js`
- Modify: `chanlun/report_assets/report-v2.css`
- Modify: `tests/test_recommendation_evidence.py`
- Modify: `tests/test_auxiliary_frontend.py`
- Modify: `tests/test_report_sentiment_layout.py`
- Modify: `tests/test_market_sentiment_psy12_shadow.py`

**Step 1: Write failing tests**

新增或调整：

```python
def test_psy12_is_nested_below_formal_market_sentiment():
    ...

def test_psy12_window_days_and_evaluation_progress_are_distinct():
    ...

def test_psy12_never_changes_formal_score_label_or_components():
    ...

def test_missing_audit_progress_is_explicit_not_fabricated():
    ...

def test_audit_progress_is_computed_from_existing_reports_plus_current_day():
    ...

def test_historical_report_normalizer_injects_sorts_and_deduplicates_trade_dates():
    ...

def test_page_and_cli_audit_use_the_same_pure_implementation():
    ...

def test_twenty_days_does_not_render_auto_promotion():
    ...
```

**Step 2: Run RED**

```bash
/usr/bin/python3 -m unittest \
  tests.test_recommendation_evidence \
  tests.test_auxiliary_frontend \
  tests.test_report_sentiment_layout \
  tests.test_market_sentiment_psy12_shadow -v
```

**Step 3: Implement subordinate panel**

- `renderMarketTemperatureCard()` 内部渲染 PSY12 影子子面板。
- 不再在 `buildAuxiliaryStacks()` 中生成同级独立大卡。
- `6/12` 只来自 `psy12.up_days/valid_days/window`。
- 将 `scripts/evaluate_market_sentiment_psy12_shadow.py` 的纯审计逻辑提取到 `chanlun/psy12_shadow_audit.py`，CLI 继续调用同一实现，防止页面与审计脚本出现两套口径。
- `chanlun/psy12_shadow_audit.py` 提供显式纯函数输入合同，例如 `normalize_historical_reports(historical_reports, current_report, as_of_date)` 与 `evaluate_psy12_shadow_audit(...)`；模块不得自行查找或读取源 checkout。`historical_reports` 的每项必须由调用方注入 `trade_date`，因为现有 `data.json.reports` 子项本身不含日期。
- normalizer 必须从聚合 `reports` 映射的键注入交易日、按交易日稳定排序、用当前 `daily_data` 覆盖同日历史项并去重、拒绝未来于 `as_of_date` 的报告；无历史文件、错误日期、非映射项或审计异常均 fail-closed 为明确 missing 状态，不得部分成功后伪报进度。
- 报告生成调用方只读现有 `data.json`，将日期键与当前 `daily_data` 显式传给上述纯函数，计算真实 `psy12_shadow_audit.valid_days/required_days`；结果仅进入 Bootstrap 展示平面，不回写日报 JSON 或历史文件。
- CLI 与页面生成必须通过同一个 normalizer 和 audit 实现；测试用乱序、同日重复、未来日期、无文件和异常输入证明两端结果 parity。
- `X/20` 只来自该真实审计结果；历史聚合缺失或审计失败时显示“影子评测进度未随本期报告提供”，不得用 12 日窗口冒充。
- 始终显示 `affects_production=false`、`promotion_eligible=false` 的用户文案和“仍需新授权”。

**Step 4: Run GREEN**

运行同一 suite；再运行 `tests.test_run_market_sentiment`，证明正式 sentiment 输入未变。

## Task 7: 完成日线结构和 30 分钟确认证据

**Files:**
- Modify: `chanlun/recommendation_evidence.py`
- Modify: `tests/test_recommendation_evidence.py`
- Modify: `tests/test_auxiliary_frontend.py`

**Step 1: Write failing tests**

新增：

```python
def test_daily_structure_maps_only_declared_trend_pivot_and_buy_point_evidence():
    ...

def test_missing_ma_values_are_not_computed_or_fabricated():
    ...

def test_30m_ema_alignment_never_becomes_healthy_confirmation():
    ...

def test_stale_or_missing_30m_is_not_confirmed():
    ...

def test_30m_summary_never_contains_full_minute_kline_arrays():
    ...
```

**Step 2: Run RED**

```bash
/usr/bin/python3 -m unittest \
  tests.test_recommendation_evidence \
  tests.test_auxiliary_frontend -v
```

**Step 3: Implement read-only summaries**

- 日线映射已有 trend/pivot/buy-point/signal date/age/health/macd facts。
- MA5/10/20/50 只有 raw 明确提供真实值时显示，否则 missing。
- 30 分钟优先读取已有 `confirmation_evidence`、`sublevel_confirm_*`、confirm date/age/bar metadata。
- “EMA5 高于 EMA10”单独显示为滞后状态，不能生成“走势健康”。
- 不序列化 `result_30min` 的完整 dates/OHLCV，不调用新的策略判定，不重新执行 admission。

**Step 4: Run GREEN**

同时运行：

```bash
/usr/bin/python3 -m unittest \
  tests.test_sublevel_confirm \
  tests.test_startup_labels \
  tests.test_report_generator -v
```

## Task 8: 完成量价资金和市场/板块共振

**Files:**
- Modify: `chanlun/recommendation_evidence.py`
- Modify: `tests/test_recommendation_evidence.py`
- Modify: `tests/test_auxiliary_frontend.py`

**Step 1: Write failing tests**

新增：

```python
def test_volume_and_capital_distinguishes_volume_from_stock_and_sector_flow():
    ...

def test_pool_quality_zero_defaults_render_as_missing_without_source_evidence():
    ...

def test_sector_support_and_risk_merge_to_disagreement():
    ...

def test_unverified_sector_data_is_unknown_not_main_fund_inflow():
    ...

def test_formal_market_sentiment_is_copied_without_psy12_override():
    ...
```

**Step 2: Run RED**

运行 targeted suite。

**Step 3: Implement mapping**

- 量能读取真实 volumes、best buy point volume ratio、pool quality `volume20/ratio20`，但仅在来源证据存在时显示。
- `money20` 标明来源；没有正式个股资金源时写“个股资金证据不足”。
- 个股成交量、个股资金、板块资金分别呈现，禁止互相替代。
- sector_heat 只有 verified 状态才用于结论；正反证据同时存在统一为“分歧”。
- 市场层只读正式 market sentiment；报告日期、版本、标签、分数、覆盖率、
  `insufficient=false`、五个 components 及对应 evidence availability
  必须形成完整一致合同，否则显示数据不足。新 Bootstrap 投影存在时它是
  唯一权威来源；旧归档无投影时只允许经过同等严格校验的 raw 合同。
  PSY12 只在子面板。

**Step 4: Run GREEN**

运行 targeted suite 和 `tests.test_report_generator`。

## Task 9: 接入真实关键价格图层并修复图表缺失 fail-open

**Files:**
- Modify: `chanlun/recommendation_evidence.py`
- Modify: `chanlun/report_assets/report-v2.js`
- Modify: `chanlun/report_assets/report-v2.css`
- Modify: `tests/test_recommendation_evidence.py`
- Modify: `tests/test_auxiliary_frontend.py`

**Step 1: Write failing tests**

新增：

```python
def test_missing_macd_remains_null_and_is_not_drawn_as_zero():
    ...

def test_missing_macd_is_null_before_echarts_option_is_built():
    ...

def test_formal_serialized_macd_and_chart_annotations_remain_unchanged():
    ...

def test_single_real_zg_or_zd_line_is_preserved():
    ...

def test_chart_never_draws_zero_price_line_for_missing_evidence():
    ...

def test_price_label_collision_keeps_all_real_values_and_kinds():
    ...

def test_chart_layers_reuse_existing_signal_lane_contract():
    ...
```

**Step 2: Run RED**

```bash
/usr/bin/python3 -m unittest \
  tests.test_report_generator \
  tests.test_auxiliary_frontend -v
```

**Step 3: Implement minimal chart changes**

- 不修改 `_serialize_macd()`、`build_chart_annotations()` 或正式 JSON 图表数组；展示投影根据原始正式报告是否具有真实 MACD 证据标记 available/missing。前端必须在构建 ECharts option 之前派生只读的 display series：missing 时整组值为 `null`，不得把 raw 的 `0` 或占位数组交给 ECharts，也不得改写 raw payload。
- 真实 current/reference/invalidation/pressure/trailing target 分层，缺失不画。
- ZG 或 ZD 单独存在时，前端直接读取现有 raw `pivot_zg/pivot_zd` 与展示投影生成结构线，来源清楚；不回写正式 annotations。
- 价格相近时车道合并说明但保留真实值。
- 保留现有成交量、MACD、信号车道、历史 tooltip 和默认最近 20 根窗口，不恢复满屏标签。

**Step 4: Run GREEN**

运行 targeted suite、`node --check`、`git diff --check`。

## Task 10: 增加主升浪线索，不新增策略或动作

**Files:**
- Modify: `chanlun/recommendation_evidence.py`
- Modify: `chanlun/report_assets/report-v2.js`
- Modify: `tests/test_recommendation_evidence.py`
- Modify: `tests/test_auxiliary_frontend.py`

**Step 1: Write failing tests**

覆盖：

```python
def test_main_rise_clue_only_maps_existing_strategy_sources():
    ...

def test_main_rise_clue_includes_support_and_opposing_evidence():
    ...

def test_no_existing_signal_renders_no_clue_without_action():
    ...

def test_main_rise_clue_cannot_override_formal_action():
    ...
```

**Step 2: Run RED**

运行 targeted suite。

**Step 3: Implement mapping**

仅映射：

- 强势启动 → 启动确认线索
- 趋势延续 → 趋势延续线索
- 加速池 → 加速线索
- 过远/过热 → 加速过热风险
- 结构破坏 → 主升线索失效
- 无证据 → 尚未形成主升浪线索

不新增分数、阈值、排序或动作。

**Step 4: Run GREEN**

运行 targeted suite。

## Task 11: 增加策略模拟跟踪和历史验证/样本门

**Files:**
- Modify: `chanlun/recommendation_evidence.py`
- Modify: `chanlun/report_assets/report-v2.js`
- Modify: `tests/test_recommendation_evidence.py`
- Modify: `tests/test_auxiliary_frontend.py`
- Modify: `tests/test_strategy_review.py`

**Step 1: Write failing tests**

新增：

```python
def test_historical_validation_keeps_exact_strategy_contract_identity():
    ...

def test_immature_scorecard_shows_progress_without_win_rate_claim():
    ...

def test_missing_entry_mode_never_creates_simulated_entry_price():
    ...

def test_same_contract_tracking_uses_ledger_identity_only():
    ...

def test_simulation_copy_never_says_real_holding_or_real_trade():
    ...
```

**Step 2: Run RED**

```bash
/usr/bin/python3 -m unittest \
  tests.test_recommendation_evidence \
  tests.test_auxiliary_frontend \
  tests.test_strategy_review -v
```

**Step 3: Implement exact matching**

按以下完整 identity 匹配，禁止合并：

```text
strategy
version
source_pool
entry_mode
intended_horizon
research_tier
```

- 成熟门未满足时只显示样本数、活跃日、月份、右删失和不足原因。
- 成熟后才显示对应 T+1/T+3/T+5 的 mean/median/up-rate/benchmark excess/MFE/MAE/worst。
- daily_fusion 未声明统一周期时明确显示，不默认 T+3。
- 个股记录只有合法 ledger contract 才显示“策略模拟跟踪”；不显示“真实持仓中”。

**Step 4: Run GREEN**

运行 targeted suite，确认既有 scorecard/shadow contracts 不变。

## Task 12: 完成桌面、平板和移动端布局/可访问性

**Files:**
- Modify: `chanlun/report_assets/report-v2.css`
- Modify: `chanlun/report_assets/report-v2.js`
- Modify: `tests/test_auxiliary_frontend.py`

**Step 1: Write failing tests**

新增 CSS/DOM 契约：

```python
def test_evidence_layout_has_no_page_level_horizontal_overflow_contract():
    ...

def test_1366_keeps_two_columns_and_comparison_owns_its_scroll():
    ...

def test_390_stacks_evidence_cards_and_chart_lane():
    ...

def test_comparison_and_detail_have_keyboard_and_aria_labels():
    ...
```

**Step 2: Run RED**

```bash
/usr/bin/python3 -m unittest tests.test_auxiliary_frontend -v
```

**Step 3: Implement responsive CSS**

- 1440×900：列表/比较入口左侧，详情八模块右侧纵向展开。
- 1366×768：保留双栏，宽表仅自身横向滚动，页面本身不溢出。
- 390px：比较表变逐票卡，详情/图表车道单列，字段名、值、日期、状态均保留。
- 使用现有冷色工作台 token，不重做产品风格；所有内容是真实数据或明确空态。

**Step 4: Run GREEN**

运行 targeted suite 和 `node --check`。

兼容历史日报：前端读取 `bootstrap.recommendationEvidence` 时必须允许旧日期 HTML 完全没有该键，统一降级为明确的“本期未提供证据展示”。候选列表、详情、图表和研究验证仍可正常打开且不得抛异常。用 Node VM 对缺 key、空对象和 schema 不兼容三种 Bootstrap 增加回归测试；本轮不向所有旧日期归档补造 evidence。

## Task 13: 同步资产、运行全量回归并证明正式数据不变

**Files:**
- Create: `scripts/stage_recommendation_evidence_pages.py`
- Create: `tests/test_stage_recommendation_evidence_pages.py`
- Modify generated assets only through repository asset-copy/report-generation flow:
  - `docs/assets/report-v2.js`
  - `docs/assets/report-v2.css`
  - `docs/index.html`
  - `docs/<latest-trade-date>/index.html`
  - `docs/compare/index.html`
  - generated local test output outside source docs when possible
- Test all modified source/tests.

**Step 1: Snapshot protected production evidence before generation**

记录但不打印凭证：

```text
docs/data/2026-08-28.json core selection digest
workspace main/h4_t3/acceleration code/action/order digest
market_sentiment score/label/components digest
decision_engine_v1 digest
recommendation ledger SHA
shadow ledger SHA
market_history.sqlite SHA
latest preclose snapshot SHA
```

**Step 2: Run focused suites**

```bash
/usr/bin/python3 -m unittest \
  tests.test_recommendation_evidence \
  tests.test_report_view_model \
  tests.test_report_generator \
  tests.test_auxiliary_frontend \
  tests.test_report_sentiment_layout \
  tests.test_market_sentiment_psy12_shadow \
  tests.test_run_market_sentiment \
  tests.test_strategy_review \
  tests.test_shadow_evaluation \
  tests.test_run_shadow_integration \
  tests.test_preclose_formal_isolation \
  tests.test_preclose_e2e -v
```

**Step 3: Run full suite**

```bash
/usr/bin/python3 -m unittest discover -s tests
```

Expected: all tests pass, exit 0.

**Step 4: Run syntax/diff checks**

```bash
node --check chanlun/report_assets/report-v2.js
/usr/bin/python3 -m py_compile chanlun/recommendation_evidence.py chanlun/report_generator.py
git diff --check
```

**Step 5: Generate a real local report in an isolated output directory**

使用 `docs/data/2026-08-28.json` 的正式序列化日报作为当前线上重建输入生成 HTML，不写正式 ledger/DB/docs。该输入没有完整 `result_30min`，所以当前页面必须把未序列化的 30 分钟值显示为 missing；不得为截图补造字段。下一次正常日报由原始 `report_data` 生成时可显示其中已有的更多只读证据。验证：

- daily JSON/core digest 与 baseline 相同；
- evidence 只在 Bootstrap；
- workspace three-pool members/actions/order identical；
- ledgers/DB/preclose hashes identical；
- HTML/JS/CSS asset version synchronized。

**Step 6: Build a guarded page-only staging tool**

`scripts/stage_recommendation_evidence_pages.py` 必须：

- 只读正式 `docs/data/<date>.json`、既有 HTML Bootstrap 和源资产；
- 在临时目录重建首页与目标日期归档 HTML，并注入 `recommendationEvidence`；同时只更新 `docs/compare/index.html` 的共享 JS/CSS asset query，研究验证入口不得继续引用旧缓存版本；
- 保留 `inlineReportData`、API base、访问控制 envelope 和所有正式 JSON 字节；
- 使用 byte/结构双重 allowlist：首页与同日归档只允许 `CHANLUN_BOOTSTRAP.recommendationEvidence` 节点和真实 `<link>/<script>` 的 JS/CSS asset query/version 改变；`inlineReportData`、API base、access envelope、其他 Bootstrap 键、正文/注释/内嵌字符串及其余 HTML 字节必须不变。`compare/index.html` 只允许真实 asset query/version 改变；
- 对错误报告日期、目标归档日期不一致、Bootstrap 缺失/重复、非白名单字节变化、输入 HTML 被外部篡改、输出解析失败全部拒绝并保持目标文件不变；
- 校验首页和归档的 evidence schema/date/content 一致；
- 校验首页、归档和 `compare/index.html` 的 JS/CSS query 都等于当前资产摘要；
- 校验 `docs/data/<date>.json`、`data.json`、ledger、DB、preclose hash 均未变化；
- 输出明确的 staged file 清单供正式发布流程精确暂存。

先写 `tests/test_stage_recommendation_evidence_pages.py` 并观察 RED，再实现；禁止直接在源 checkout 上试跑写入。

## Task 14: 真实截图验收、最终同步、单提交发布和线上回读

**Files:**
- Stage only explicitly reviewed source, tests, the two exact new plan files, and repository-managed assets required by the release.
- Do not stage source checkout dirty files, `.wrangler/`, screenshots, caches, generated historical reports, `.codegraph/`, or `.idea/`.

**Step 1: Local screenshot acceptance**

用真实生成页面拍摄：

- 1440×900：今日决策首屏、候选比较、选中票八模块、研究验证 PSY12。
- 1366×768：同一关键区域，检查双栏和表格自身滚动。
- 390px：候选列表/比较卡/详情/图表/研究验证。

浏览器运行时断言：

```javascript
document.documentElement.scrollWidth === document.documentElement.clientWidth
```

逐项人工截图分析：唯一正式动作、决策分/排序证据分离、缺失空态、30 分钟不误判、量价资金不混淆、价格标签不重叠、PSY12 从属。

**Step 2: Review changed files**

```bash
git status --short --untracked-files=all
git diff --stat
git diff --check
```

默认忽略 `.codegraph/` 和 `.idea/`。独立代码 review 必须确认无 Critical/Important。

**Step 3: Stage and verify the actual Pages surfaces**

在生产发布 worktree 中使用 Task 13 的 guarded staging tool 更新：

- `docs/index.html`
- `docs/2026-08-28/index.html`（若发布时最新正式日期已前进，则改为当时最新正式日期）
- `docs/compare/index.html`（仅同步共享资产 query/version，不注入日报 evidence）
- `docs/assets/report-v2.js`
- `docs/assets/report-v2.css`

首页与归档必须都回读出同一 `recommendationEvidence.report_date/schema_version`；`inlineReportData` 与正式 JSON core digest 保持不变；研究验证页必须回读到同一 JS/CSS asset query。不要把隔离目录中的临时输出或截图提交。

**Step 4: Sync latest target branch before final commit**

```bash
git fetch origin main
git merge-base --is-ancestor origin/main HEAD
```

若 main 前进，必须显式安全 rebase 到最新 `origin/main` 或在新的 latest-main worktree 重新应用本提交并完成必要适配，随后重新执行 Task 13 的 guarded staging、全部测试和全部 hash 验证。不得 stash、覆盖或清理源 checkout 的用户改动。

**Step 5: Create one clean final commit**

只用 `git add -f` 精确添加：

```text
docs/plans/2026-08-30-recommendation-evidence-display-optimization-design.md
docs/plans/2026-08-30-recommendation-evidence-display-optimization-implementation-plan.md
```

其他源文件、测试、上述首页/日期归档和两份正式 assets 必须逐路径 `git add`；不得使用目录级或全仓 add。提交标题遵守：

资产必须成对逐路径暂存源文件与生成副本，至少明确包含：

```text
chanlun/report_assets/report-v2.js
chanlun/report_assets/report-v2.css
docs/assets/report-v2.js
docs/assets/report-v2.css
```

不得只提交 `docs/assets` 而漏掉下一次日报生成所复制的源资产。

```text
feat: 完善推荐票证据展示
```

最终远端历史只保留一个干净提交。

**Step 6: Push, merge, deploy**

通过仓库安全流程合入 `main`，让 production-runtime 同步到最新 main；运行正式 Pages 发布保护流程。不得修改 preclose Worker、top10 Worker、launchd、正式策略配置或数据库。

push/合入后必须重新 fetch 并回读远端 `main` SHA、最终提交 SHA，证明 `origin/main` 含该提交且发布 checkout 的 HEAD 与目标远端一致；不能只引用提交前的 merge-base。

**Step 7: Live readback and screenshots**

线上回读：

- `docs/data/YYYY-MM-DD.json` 正式 JSON/core digest；
- 首页 HTML Bootstrap `recommendationEvidence` schema/report date/views；
- 同日归档 HTML Bootstrap 的同一 evidence identity/content；
- 研究验证页 `docs/compare/index.html` 与首页/归档使用同一最新 JS/CSS asset query；
- JS/CSS 资产及 query version；
- 唯一正式动作和三池成员/顺序；
- PSY12 正式/影子边界；
- 1440×900、1366×768、390px 真实线上截图；
- 零横向溢出。

**Step 8: Preserve long-running goal**

本展示优化发布成功不等于整个 P0-P4 生产 goal 完成。仍需遵守原 25 项门槛和下一真实交易日的 14:47/14:49/14:56:30、盘后复核、WxPusher 手机到达等证据；门槛未齐不得调用 `update_goal(complete)`。
