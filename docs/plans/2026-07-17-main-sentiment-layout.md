# 主界面市场情绪卡布局优化 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将主界面市场情绪卡从四列网格中的窄卡改成半行宽的桌面大卡，并把指标与20日折线图改为左右布局。

**Architecture:** 保留现有 `market_sentiment` 数据合同和 ECharts 配置，只调整 `renderMarketTemperatureCard` 的内部容器与响应式 CSS。桌面端情绪卡和板块资金卡各跨两列；中等屏幕情绪卡独占三列；手机端内部恢复单列。

**Tech Stack:** 原生 JavaScript、CSS Grid、ECharts、Python unittest、浏览器验收。

---

### Task 1: 增加情绪布局静态合同测试

**Files:**
- Create: `tests/test_report_sentiment_layout.py`

**Step 1: 写失败测试**

测试源码包含：

- `market-temperature-card` 桌面端 `grid-column: span 2`。
- 情绪卡内部存在 `market-temp-layout`。
- 内部分栏为约30/70。
- 1180px断点情绪卡跨三列。
- 760px断点内部单列且图表高度约240px。
- `renderMarketTemperatureCard` 将仪表/指标和图表放入两个独立容器。

**Step 2: 运行测试确认失败**

Run: `python3 -m unittest tests.test_report_sentiment_layout -v`

Expected: FAIL，因为新布局类尚不存在。

### Task 2: 实现桌面和移动端布局

**Files:**
- Modify: `chanlun/report_assets/report-v2.js:1961-1988`
- Modify: `chanlun/report_assets/report-v2.css:1350-1380, 1880-1970`

**Step 1: 调整情绪卡结构**

在 `renderMarketTemperatureCard` 中生成：

```html
<div class="market-temp-layout">
  <div class="market-temp-snapshot">仪表与指标</div>
  <div class="market-temp-trend">20日折线图</div>
</div>
```

不得修改分数、构成项或历史数据来源。

**Step 2: 增加响应式CSS**

桌面端：

```css
.market-temperature-card { grid-column: span 2; }
.market-temp-layout { grid-template-columns: minmax(210px, 30%) minmax(0, 70%); }
.market-sentiment-chart { height: 300px; margin-top: 0; }
```

中等屏幕：情绪卡跨三列。手机端：情绪卡恢复单列，内部网格一列，图表高度240px。

**Step 3: 运行目标测试**

Run: `python3 -m unittest tests.test_report_sentiment_layout -v`

Expected: PASS。

### Task 3: 生成静态资源并做浏览器验收

**Files:**
- Modify: `docs/assets/report-v2.js`
- Modify: `docs/assets/report-v2.css`
- Modify: `docs/index.html`
- Modify: retained `docs/YYYY-MM-DD/index.html`

**Step 1: 复制资源并更新版本哈希**

使用 `copy_report_assets("docs")` 和 `_report_asset_version()`，同步首页及保留归档页的资源版本。

**Step 2: 桌面验收**

在1280px确认：

- 辅助决策网格为四列。
- 情绪卡和板块资金卡各占约一半宽度。
- 情绪卡内部左窄右宽。
- 折线图宽度大于高度。

**Step 3: 手机验收**

在390px确认：

- 情绪卡内部单列。
- 图表无横向溢出。
- 控件和其他辅助卡不受影响。

### Task 4: 回归、提交和发布

**Files:**
- Test: `tests/test_report_sentiment_layout.py`
- Test: full `tests/`

**Step 1: 运行验证**

```bash
python3 -m unittest discover -s tests -v
node --check chanlun/report_assets/report-v2.js
python3 scripts/validate_today_report.py 2026-07-17
git diff --check
```

Expected: 全部通过。

**Step 2: 仅暂存本功能文件并提交**

Commit: `feat: 优化主界面情绪图布局`

**Step 3: 推送 `main` 并等待 Pages 成功**

线上再次验证桌面与手机布局。
