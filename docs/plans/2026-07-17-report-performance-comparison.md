# 榜单表现比对功能 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在日报首页与独立页面实现最近 26 个正式报告日的榜单收益比对，并仅在用户点击按钮时批量刷新当前价。

**Architecture:** Python 生成器从共享 SQLite 行情库和历史日报构建轻量静态价格索引；浏览器负责历史收益、沪深300和超额收益计算；现有 Cloudflare Worker 新增受限的批量行情代理端点，仅服务手动当前价刷新。桌面端使用左侧榜单、右侧明细的宽屏主从布局，手机端降级为单列卡片。

**Tech Stack:** Python 3、SQLite、原生 JavaScript/CSS、Cloudflare Worker、Node test、unittest。

---

### Task 1: 26 日榜单价格索引

**Files:**
- Create: `chanlun/report_comparison.py`
- Modify: `chanlun/report_generator.py`
- Test: `tests/test_report_comparison.py`
- Test: `tests/test_report_generator.py`

**Steps:**
1. 先写失败测试，覆盖正式报告日筛选、八榜单代码提取、跨榜单去重、26 日滚动窗口、DB 收盘价读取、沪深300序列和缺失状态。
2. 运行 `python3 -m unittest tests.test_report_comparison -v`，确认测试因模块缺失而失败。
3. 实现纯函数统计/抽取和 DB 读取边界，禁止远程补齐；输出 `docs/data/comparison-index.json`。
4. 修改报告生成器，在当日报告与 manifest 写入后刷新索引；历史日报生成失败不得留下半文件。
5. 运行目标测试并确认通过。

### Task 2: 手动批量当前行情接口

**Files:**
- Modify: `cloudflare/top10-worker/src/index.js`
- Modify: `cloudflare/top10-worker/test/top10-worker.test.js`

**Steps:**
1. 先写失败测试，覆盖 `POST /api/quotes/current`、代码白名单、去重、数量上限、空请求、上游部分失败、沪深300和行情时间。
2. 运行 `cd cloudflare/top10-worker && npm test`，确认新增测试失败。
3. 实现批量行情代理，使用服务器端固定行情 URL，不允许客户端传任意 URL；按上游限制分批，逐项返回 `ok/error`。
4. 保留现有 CORS 白名单和 Top10 API 行为，不新增自动轮询。
5. 运行 Worker 全部测试。

### Task 3: 浏览器比对引擎与页面布局

**Files:**
- Modify: `chanlun/report_assets/report-v2.js`
- Modify: `chanlun/report_assets/report-v2.css`
- Create: `chanlun/report_assets/comparison.html`
- Test: `tests/test_report_comparison_frontend.py`

**Steps:**
1. 写静态契约测试，覆盖首页入口、独立页面、两个日期选择器、手动刷新、未刷新状态和移动端断点。
2. 实现纯前端收益函数：实际涨跌、平均值、中位数、上涨比例、沪深300、超额收益、缺失计数和整体去重。
3. 首页注入“昨日榜单表现”入口与宽屏主从区域；初始状态不得调用当前行情接口。
4. 独立页面加载最近 26 日索引，对比日期不得早于榜单日期；历史使用静态收盘，当前只有点击按钮才请求 Worker。
5. 实现横向实际涨跌柱状图与沪深300基准线；实际涨跌决定红绿，超额收益使用独立标签。
6. 桌面端 30/70 主从布局；手机端单列卡片且无强制横向滚动。
7. 运行前端契约测试。

### Task 4: 生成、集成与回归验收

**Files:**
- Modify: `chanlun/report_generator.py`
- Modify: `scripts/validate_today_report.py`
- Modify: `tests/test_report_generator.py`
- Modify: `tests/test_validate_today_report.py`

**Steps:**
1. 将 `comparison.html` 与前端资源复制到 `docs/compare/index.html` 和 `docs/assets/`，首页加入可发现入口。
2. 校验器检查比较页、26 日索引、最新报告日、价格结构和 Worker API base。
3. 生成当日报告并检查输出文件大小、日期范围与无远程历史补齐。
4. 运行 `python3 -m unittest discover -s tests -v`、Worker `npm test` 和 `python3 -m py_compile`。
5. 本地启动静态站，分别验证桌面和手机：初始无行情请求、按钮单次请求、历史比对、部分缺失和榜单切换。
6. 仅暂存本功能文件，提交并推送 `main`；等待 Pages 成功后验证线上页面与接口。
