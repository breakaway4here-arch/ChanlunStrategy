# K 线特殊信号车道 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在不恢复 K 线文字叠压的前提下，让最新特殊信号、历史信号、`ZG/ZD` 结构位和补充提示在桌面与移动端重新可辨识。

**Architecture:** 保留现有日报 `chart_annotations` 合同，在 `report-v2.js` 中建立一个只读规范化层，将原始标注拆成动作点、最新短标、结构线和最多三条的 DOM 信号车道。ECharts 继续负责真实坐标与 tooltip，独立车道负责完整名称、日期和状态；所有变化仅影响展示资产，不改变正式池、动作、账本或数据库。

**Tech Stack:** Python `unittest`、Node VM 前端合同测试、原生 JavaScript、ECharts、CSS、GitHub Pages。

---

### Task 1: 冻结信号选择与短标纯函数

**Files:**
- Modify: `tests/test_auxiliary_frontend.py`
- Modify: `chanlun/report_assets/report-v2.js:3032-3066`

**Step 1: 写失败测试——最新短标和历史点化**

扩展 `test_historical_chart_actions_keep_only_latest_text_and_layer_entries_are_data_driven`：

```javascript
const marks = selectChartActionMarkers([
  { coord: ['2026-08-21', 10], name: '底背驰候选' },
  { coord: ['2026-08-28', 11], name: '趋势延续候选' }
], 40);
assert(marks.filter(item => item.label.show).length === 1);
assert(marks[1].label.formatter === '趋势');
assert(marks[0].label.show === false);
assert(marks[0].symbolSize < marks[1].symbolSize);
```

再覆盖四个短标映射、未知真实名称截断、无效坐标过滤、每 40 根最多三个文字标记且最新优先。

**Step 2: 运行 RED**

Run:

```bash
/usr/bin/python3 -m unittest tests.test_auxiliary_frontend.AuxiliaryFrontendContractTest.test_historical_chart_actions_keep_only_latest_text_and_layer_entries_are_data_driven -v
```

Expected: FAIL，当前所有 `label.show` 都被强制设为 `false`。

**Step 3: 实现最小纯函数**

在 `report-v2.js` 增加：

```javascript
function shortChartSignalLabel(name) { /* 真实类型映射和长度约束 */ }
function selectChartActionMarkers(markPoints, barCount) { /* 最新一个有短标，历史点化 */ }
```

函数不得修改输入；用 `barIndex` 和原始顺序确定最新标记；无效坐标直接排除。

**Step 4: 运行 GREEN**

Run 同 Step 2。

Expected: PASS。

**Step 5: 提交**

```bash
git add tests/test_auxiliary_frontend.py chanlun/report_assets/report-v2.js
git commit -m "fix: 恢复K线最新信号短标"
```

### Task 2: 建立最多三条的独立信号车道

**Files:**
- Modify: `tests/test_auxiliary_frontend.py`
- Modify: `chanlun/report_assets/report-v2.js:3041-3066,3162-3192`
- Modify: `chanlun/report_assets/report-v2.css:389-510,4300-4420`

**Step 1: 写失败测试——完整名称、日期和补充说明**

替换当前仅检查最新一条的 lane 测试，输入四个动作点和：

```javascript
annotations.labels = ['确认日: 2026-08-28', '接近20日低点；接近swing参考价'];
```

断言：

- 车道最多三条，按日期/索引从新到旧。
- 同时包含 `趋势延续候选 · 2026-08-28` 与 `底背驰候选 · 2026-08-21`。
- 展示真实确认日和种子原因，不展示第四条动作。
- 无有效信号和补充说明时隐藏并清空。
- 所有文本通过 `escapeHtml`。

**Step 2: 运行 RED**

Run:

```bash
/usr/bin/python3 -m unittest tests.test_auxiliary_frontend.AuxiliaryFrontendContractTest.test_chart_moves_action_text_into_annotation_lane -v
```

Expected: FAIL，当前车道只渲染最新一条且不读取 `annotations.labels`。

**Step 3: 实现车道模型和 DOM**

增加 `buildChartSignalLaneModel(markPoints, extraLabels)`，让 `renderChartAnnotationLane()` 只消费模型。每条车道项包含短标、完整名、日期；补充说明进入独立 `small`，不创建动作标签。

CSS 使用 Swiss 白底、`#002FA7` 强调、1px 分隔线；桌面横向最多三条，`max-width: 760px` 时纵向排列，所有子项 `min-width: 0`、`overflow-wrap: anywhere`，禁止横向滚动。

**Step 4: 运行 GREEN 与相关布局测试**

Run:

```bash
/usr/bin/python3 -m unittest \
  tests.test_auxiliary_frontend.AuxiliaryFrontendContractTest.test_chart_moves_action_text_into_annotation_lane \
  tests.test_auxiliary_frontend.AuxiliaryFrontendContractTest.test_chart_uses_a_responsive_right_label_lane \
  tests.test_auxiliary_frontend.AuxiliaryFrontendContractTest.test_three_panel_chart_has_explicit_desktop_and_mobile_heights -v
```

Expected: PASS。

**Step 5: 提交**

```bash
git add tests/test_auxiliary_frontend.py chanlun/report_assets/report-v2.js chanlun/report_assets/report-v2.css
git commit -m "feat: 增加K线特殊信号车道"
```

### Task 3: 恢复结构图层和 tooltip 详情

**Files:**
- Modify: `tests/test_auxiliary_frontend.py`
- Modify: `chanlun/report_assets/report-v2.js:3193-3260,3338-3365`

**Step 1: 写失败测试——`ZG/ZD` 只在结构层出现**

构造包含：

```javascript
chart_annotations: {
  markLines: [
    { name: 'ZG', yAxis: 12.4 },
    { name: 'ZD', yAxis: 10.8 },
    { name: 'source', yAxis: 11.2 },
    { name: 'current', yAxis: 11.7 }
  ],
  markPoints: [{ name: '底背驰候选', coord: ['2026-08-21', 11.2] }]
}
```

断言：

- `state.chartLayer='decision'` 时只出现决策价标，不出现 `ZG/ZD`。
- `state.chartLayer='structure'` 时出现真实 `ZG/ZD` y 值，不出现现价/参考价常驻标签。
- `markPoint.tooltip.formatter` 或全局 tooltip 能返回完整名称、日期、价格。
- `ZG/ZD` 无效数值不进入 ECharts。

**Step 2: 运行 RED**

Run:

```bash
/usr/bin/python3 -m unittest tests.test_auxiliary_frontend.AuxiliaryFrontendContractTest.test_chart_renders_structure_lines_and_signal_tooltips -v
```

Expected: FAIL，当前原始 `ZG/ZD` 被价标白名单丢弃，tooltip 没有专用信号文本。

**Step 3: 实现最小结构线和 tooltip**

增加 `selectStructureChartLines(rawMarkLines)`，仅接收名称精确为 `ZG` 或 `ZD` 且 y 值有限的证据。结构层 `markLine.data` 使用该结果，决策层继续使用现有 `persistentLabels`；两层互斥。

在 ECharts tooltip formatter 中对 `componentType === 'markPoint'` 返回转义后的完整信号名、日期和价格；普通 axis tooltip 保持 ECharts 默认行为或等价数据列表。

**Step 4: 运行 GREEN**

Run 同 Step 2。

Expected: PASS。

**Step 5: 运行 P0/P1 定向回归**

Run:

```bash
/usr/bin/python3 -m unittest \
  tests.test_auxiliary_frontend \
  tests.test_report_sentiment_layout \
  tests.test_report_generator -v
```

Expected: PASS，无旧叠压合同回退。

**Step 6: 提交**

```bash
git add tests/test_auxiliary_frontend.py chanlun/report_assets/report-v2.js
git commit -m "fix: 恢复K线结构提示"
```

### Task 4: 同步 Pages 资产并验证正式数据零变化

**Files:**
- Modify: `docs/assets/report-v2.js`
- Modify: `docs/assets/report-v2.css`
- Modify: `docs/index.html`
- Modify: `docs/2026-08-28/index.html`
- Modify: `docs/compare/index.html`

**Step 1: 记录保护哈希**

记录：

```bash
shasum -a 256 \
  docs/data/2026-08-28.json docs/data.json docs/data/comparison-index.json \
  .cache/chanlun/market_history.sqlite \
  .cache/chanlun/recommendation_ledger.jsonl \
  .cache/chanlun/shadow_evaluation_ledger.jsonl
```

缺失的运行时文件在独立 worktree 中记录为“not present”，不得从源 checkout 复制或修改。

**Step 2: 机械同步资产和版本号**

调用 `chanlun.report_generator.copy_report_assets('docs')`，再用 `_report_asset_version()` 将三份 HTML 中 `report-v2.js/css?v=<12hex>` 更新为同一个新版本；不得重新生成或格式化日报 JSON。

**Step 3: 验证哈希和 Bootstrap**

断言：

- `cmp` 确认源资产与 `docs/assets` 一致。
- 三份 HTML 只变化资产版本号。
- `docs/data/*.json` 和所有可用保护文件哈希不变。
- `scripts/validate_today_report.py --docs-dir docs 2026-08-28` 退出 0。

**Step 4: 运行全量测试**

Run:

```bash
/usr/bin/python3 -m unittest discover -s tests -v
```

Expected: 全部 PASS，退出 0。

**Step 5: 提交**

```bash
git add chanlun/report_assets/report-v2.js chanlun/report_assets/report-v2.css \
  docs/assets/report-v2.js docs/assets/report-v2.css \
  docs/index.html docs/2026-08-28/index.html docs/compare/index.html \
  tests/test_auxiliary_frontend.py
git commit -m "feat: 完善K线特殊指标提示"
```

### Task 5: 审查、合入、发布和截图验收

**Files:**
- Evidence only: `/Users/yangfan/.codex/visualizations/2026/08/27/01a04288-e322-7360-a0d5-7dea202a0572/`

**Step 1: 代码审查和最终同步**

重新 `git fetch origin main`，确认 `origin/main` 是分支祖先；若远端变化，只做必要适配。检查 staged/unstaged/untracked 时忽略 `.codegraph/` 和 `.idea/`。

**Step 2: 压成一个最终代码提交并回归**

通过安全的 squash 集成方式让目标 `main` 只新增一个代码提交，标题为：

```text
feat: 完善K线特殊指标提示
```

重新运行 Task 3 定向回归、Task 4 全量回归和验证器。

**Step 3: 推送并等待 Pages**

通过仓库现有安全流程推送 `main`，等待 GitHub Pages 对应 SHA 成功；回读线上 HTML、JS、CSS，并核对资产 SHA 与提交一致。

**Step 4: 真实线上截图**

使用线上 2026-08-28 页面：

- 1440×900：上海石化详情，显示“趋势”短标、完整车道、成交量、MACD。
- 1366×768：同上，验证最后五根 K 线和右侧价标。
- 390px：打开移动抽屉，验证车道纵向排列、图钉可点击、零横向溢出。
- 切换分众传媒，验证“底背驰候选 · 2026-08-21”。
- 切换“结构”图层；有真实 `ZG/ZD` 时展示，无数据时不补造。

**Step 5: 保留长期目标**

本次 UI 缺口通过后仍不得调用 `update_goal(complete)`；继续等待下一真实交易日14:47/14:49/14:56:30、盘后复核、notify=1 供应商成功和手机到达等剩余生产门槛。
