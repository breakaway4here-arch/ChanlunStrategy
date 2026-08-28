# Candidate Row and K-Line Density Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 修复候选行与 K 线标签碰撞，增加成交量副图，并将默认可见 K 线窗口收敛为最近 30 根且保留完整历史缩放能力。

**Architecture:** 保持 Python 报告序列化窗口和正式决策语义不变，只在 `report-v2.js/css` 重构候选行布局与 ECharts option。图表用三个同步 grid，动作文字通过 DOM 标注车道与图内价格标签分离；所有行为由 Node 合同测试和真实截图锁定。

**Tech Stack:** Vanilla JavaScript、CSS Grid、ECharts、Python unittest、Node VM 截图验收。

---

### Task 1: 固化候选行不重叠合同

**Files:**
- Modify: `tests/test_auxiliary_frontend.py`
- Modify: `scripts/repair_auxiliary_decision_snapshot.py`（仅更新已审报告资产 SHA-256）
- Modify: `chanlun/report_assets/report-v2.js`
- Modify: `chanlun/report_assets/report-v2.css`

**Step 1: 写失败测试**

增加合同断言：候选行 HTML 包含独立 `.candidate-row-meta`；`.candidate-price` 不再位于 `.candidate-row-main`；桌面和 390px CSS 都为状态区提供明确网格/换行规则，且没有 76/84px 的涨跌固定列。

**Step 2: 运行 RED**

Run: `/usr/bin/python3 -m unittest tests.test_auxiliary_frontend.TestAuxiliaryCockpitContract.test_candidate_row_meta_separates_price_from_identity -v`

Expected: FAIL，缺少 `candidate-row-meta`。

**Step 3: 最小实现**

调整 `renderCandidateList()`：第一行只渲染排名和身份；第二行 `.candidate-row-meta` 使用 `minmax(0, 1fr) auto` 渲染标签与当日涨跌。单列宽候选区可横向展开，390px 仍保持上下两层；所有子项设置 `min-width: 0` 和受控换行。

**Step 4: 运行 GREEN**

Run: `/usr/bin/python3 -m unittest tests.test_auxiliary_frontend -v`

Expected: PASS。

### Task 2: 固化三层图表与 30 根默认窗口

**Files:**
- Modify: `tests/test_auxiliary_frontend.py`
- Modify: `chanlun/report_assets/report-v2.js`

**Step 1: 写失败测试**

通过现有 Node VM ECharts stub 构造 50 根 OHLC、volumes、MACD，断言：

- option 有三个 grid/xAxis/yAxis；
- series 同时包含 `K线`、`成交量`、`MACD`；
- 成交量颜色遵循 A 股红涨绿跌，缺失量为 `null`；
- 两个 dataZoom 的 `xAxisIndex` 都是 `[0, 1, 2]`；
- `startValue` 是第 21 根日期，`endValue` 是第 50 根日期。

**Step 2: 运行 RED**

Run: `/usr/bin/python3 -m unittest tests.test_auxiliary_frontend.TestAuxiliaryCockpitContract.test_chart_renders_volume_macd_and_defaults_to_latest_thirty_bars -v`

Expected: FAIL，当前只有两个 grid 且 dataZoom 从 0 到 100。

**Step 3: 最小实现**

在 `renderChart()` 中尾部对齐 volumes，构建三层 grid/xAxis/yAxis 和成交量 series。默认窗口使用真实日期 `startValue/endValue`，三个轴共享 dataZoom；趋势 series 仍挂在 K 线主轴。

成交量与 MACD 纵轴隐藏数值刻度，只保留分区名和 tooltip，避免紧凑副图出现刻度碰撞；移动端三块 grid 左边距使用 10%，桌面使用 6%。

**Step 4: 运行 GREEN**

Run: `/usr/bin/python3 -m unittest tests.test_auxiliary_frontend -v`

Expected: PASS。

### Task 3: 固化独立动作标注车道

**Files:**
- Modify: `tests/test_auxiliary_frontend.py`
- Modify for Pages: `docs/assets/report-v2.js`
- Modify for Pages: `docs/assets/report-v2.css`
- Modify for cache busting: `docs/index.html`
- Modify for cache busting: `docs/2026-08-27/index.html`
- Modify for cache busting: `docs/compare/index.html`
- Modify: `chanlun/report_assets/report-v2.js`
- Modify: `chanlun/report_assets/report-v2.css`

**Step 1: 写失败测试**

断言图表占位包含 `#chartAnnotationLane`；最新动作的图钉 `label.show` 为 false；车道只展示最新动作真实名称与日期；无动作时车道隐藏。保留相近价格线合并合同。

**Step 2: 运行 RED**

Run: `/usr/bin/python3 -m unittest tests.test_auxiliary_frontend.TestAuxiliaryCockpitContract.test_chart_moves_action_text_into_annotation_lane -v`

Expected: FAIL，当前最新动作仍在 markPoint 上显示文字。

**Step 3: 最小实现**

新增车道渲染函数，从已过滤动作标记中选择最新一项，输出真实名称与日期；图钉标签全部隐藏。车道采用 Swiss hairline 样式，不新增装饰性文案。

**Step 4: 运行 GREEN**

Run: `/usr/bin/python3 -m unittest tests.test_auxiliary_frontend -v`

Expected: PASS。

### Task 4: 响应式尺寸与真实截图

**Files:**
- Modify: `chanlun/report_assets/report-v2.css`
- Test: `tests/test_auxiliary_frontend.py`
- Generate only: `.cache/chanlun/ui-acceptance/chart-volume-layout/`

**Step 1: 写失败测试**

断言桌面 chart canvas 高度足以容纳三层，390px 有独立高度和候选状态区布局，不产生横向溢出。

**Step 2: 运行 RED/GREEN**

Run: `/usr/bin/python3 -m unittest tests.test_auxiliary_frontend tests.test_report_generator -v`

Expected: 首次 FAIL，完成 CSS 后 PASS。

**Step 3: 生成真实页面与截图**

从冻结的 2026-08-27 报告数据在临时输出目录生成页面，使用 1440×900、1366×768、390px 截图。逐项检查：三个主推候选行无重叠、飞凯材料图表右端无碰撞、成交量与 MACD 同时可见、默认最近 30 根、缩放后可查看更早数据。

### Task 5: 回归、同步、提交与 Pages 发布

**Files:**
- Force add: `docs/plans/2026-08-28-candidate-chart-density-volume-design.md`
- Force add: `docs/plans/2026-08-28-candidate-chart-density-volume-implementation-plan.md`
- Modify: `chanlun/report_assets/report-v2.js`
- Modify: `chanlun/report_assets/report-v2.css`
- Modify: `tests/test_auxiliary_frontend.py`

**Step 1: 相关与全量测试**

Run: `/usr/bin/python3 -m unittest tests.test_auxiliary_frontend tests.test_report_generator -v`

Run: `/usr/bin/python3 -m unittest discover -s tests -v`

Expected: 全部 PASS，退出码 0。

**Step 2: 同步最新目标分支**

重新读取远端 `main`；若变化，将改动建立在最新 `origin/main` 上并重跑测试。确认 `origin/main` 是最终提交祖先。

**Step 3: 一个干净提交**

只暂存上述源文件、测试、两份方案文档和五个 Pages 生成/缓存失效文件；两份被 `*.md` 忽略的方案文档使用 `git add -f`。提交标题遵守 `feat: 优化候选行与量价图表`。

**Step 4: 安全合入和发布**

通过仓库现有安全流程将单提交合入远端 `main`，等待 GitHub Pages 发布完成。回读 live HTML、JS、CSS asset hash，并重新截取 1440×900、1366×768、390px 正式线上页面。

**Step 5: 边界复核**

确认 preclose Worker、Top10 Worker、正式市场库、账本、候选池身份、唯一正式动作和 14:47 调度未发生变化。该 UI 追加优化不改变仍在等待的真实交易日生产门槛。
