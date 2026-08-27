# 渐进式决策工作台综合优化实施计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在同一版中完成桌面决策工作台、统一空态、图表治理、PSY12 影子评测、14:47 三池预跑、简洁推送和盘后正式/预跑差异提醒，并证明预跑不会改变盘后正式结果。

**Architecture:** 保留现有日报 JSON、workspace 候选身份和正式融合决策语义，在前端增加 `今日决策 / 研究验证` 两层视图和明确的 UI 状态。P0 只消费现有可信字段并重排 DOM；P1 增加 `sector_heat` 与 `formal_decision_contract`；P2 将策略、影子和 AI 比较迁入研究验证页并执行严格样本门；P3 从历史市场情绪证据计算 PSY12 和 10% 权重影子分，但不覆盖正式市场情绪分、市场温度或决策门控；P4 新建独立的 14:47 预跑进程、快照命名空间、独立 `preclose-worker` Durable Object 和盘后只读复核器，只复用纯策略模块，不进入 `daily_run.sh`、正式行情库、正式账本、现有 Top10 Worker 或 Pages 发布关键路径。

**Tech Stack:** Python 3、`unittest`、原生 JavaScript、CSS、ECharts 5、静态 HTML/JSON 日报、Cloudflare Worker/Durable Objects、Vitest、launchd、WxPusher（主通道）/企业微信机器人（可选）、现有 GitHub Pages 发布链。

---

## 实施前边界

1. 当前主工作区有用户未提交修改。实施必须新建独立 worktree，禁止 stash、覆盖或误提交现有工作区内容。
2. 新分支使用 `codex/decision-workbench-ui` 或同类 `codex/` 前缀。
3. 创建任何提交前，先同步最新 `origin/main`，确认 `origin/main` 是当前提交祖先，再重新执行相关测试。
4. 本计划不修改盘后正式选股算法、各池正式候选逻辑、正式推荐门槛、影子准入或收益计算口径；P3 只增加 PSY12 影子结果，不修改现有正式市场情绪分。
5. P0 不新增伪造仓位、周期、压力位或板块热度字段。
6. 每个阶段都先写失败测试，再实现最小改动。
7. 视觉验收必须基于真实生成页面截图；字符串测试只能作为合同保护，不能替代浏览器验收。
8. P0-P4 属于同一版综合优化，不再建立独立的预收盘产品版本；P4 仍必须使用独立运行边界。
9. P4 不修改 `daily_run.sh` 的正式执行依赖，不写正式 `market_history.sqlite`、`recommendation_ledger.jsonl`、日报 JSON/HTML、记分卡或 comparison index。
10. P4 只生成主推池、H4 T+3 和加速池；新闻、LLM、iWencai、15 分钟策略和其他研究池不得进入 14:47 关键路径。
11. PSY12 在本版本保持 10% 影子权重，不参与 P4 预跑选股；交易时点变化和新情绪权重不得同时接管动作。
12. P4 的公开主推必须运行当前确定性市场情绪和 `chanlun.decision_engine.evaluate_stock()` 门控；不得用原始融合候选替代页面正式推荐语义。
13. 盘后差异必须通过 `chanlun.report_view_model.build_workspace()` 读取三个用户可见池，不得直接比较原始 `picks_fusion`。
14. `preclose-worker` 独立部署；不得修改现有 `cloudflare/top10-worker` 的路由、KV、binding 或 Durable Object migration。
15. 方案文档当前受源工作区 `.git/info/exclude` 的 `*.md` 规则影响。独立 worktree 中必须从源工作区复制这两份已 Review 文档并仅对它们执行 `git add -f`，不得顺带加入其他被忽略或未跟踪文件。

### Worktree 准备

```bash
git fetch origin main
git worktree add .worktrees/decision-workbench-ui -b codex/decision-workbench-ui origin/main
cd .worktrees/decision-workbench-ui
git merge-base --is-ancestor origin/main HEAD
```

Expected: 最后一条命令退出码为 `0`；原主工作区的未提交修改保持不变。

## P0：首屏减法与图表治理

### Task 1: 冻结 P0 前端合同

**Files:**
- Modify: `tests/test_auxiliary_frontend.py`
- Modify: `tests/test_report_sentiment_layout.py`
- Modify: `tests/test_report_generator.py`

**Step 1: 写失败测试——一级页面和首屏组件**

新增断言：

- 页面存在 `今日决策` 与 `研究验证` 两个一级入口。
- 默认视图是 `今日决策`。
- 页头不再渲染临时 Top10 小组件。
- 默认首屏包含资金主线、候选列表、个股决策头和 K 线容器。
- 研究验证视图包含策略记分牌、影子评测与诊断入口。

**Step 2: 写失败测试——候选行和正式动作**

通过现有 Node VM 测试辅助方法断言：

- 候选行最多输出两个标签。
- 每个候选详情只输出一个 `formal-action` 元素。
- 单策略意见不能覆盖正式融合动作。
- `position_band`、`intended_horizon` 或 `pressure_price` 缺失时不渲染伪值。

**Step 3: 运行测试并确认 RED**

Run:

```bash
python3 -m unittest \
  tests.test_auxiliary_frontend \
  tests.test_report_sentiment_layout \
  tests.test_report_generator -v
```

Expected: FAIL，原因是当前仍使用旧 App Shell、同权辅助 Grid 和七段个股详情。

**Step 4: 提交测试**

同步并确认祖先后执行：

```bash
git add tests/test_auxiliary_frontend.py tests/test_report_sentiment_layout.py tests/test_report_generator.py
git commit -m "test: 固化决策工作台首屏合同"
```

### Task 2: 重建 App Shell 和紧凑页头

**Files:**
- Modify: `chanlun/report_assets/report-v2.js`
- Modify: `chanlun/report_assets/report-v2.css`
- Test: `tests/test_auxiliary_frontend.py`
- Test: `tests/test_report_sentiment_layout.py`

**Step 1: 修改 App Shell**

将页面骨架调整为：

```text
report-shell
├── compact-header
├── primary-mode-tabs
├── today-decision-view
│   ├── sector-strip
│   ├── workspace
│   └── supporting-decisions
└── research-validation-view
```

保留现有 mobile drawer，不在本任务重写移动端交互。

**Step 2: 实现紧凑页头**

常驻展示报告日期、数据更新时间、数据状态、市场状态和操作节奏。移除 Top10 DOM；六张指数卡和市场情绪趋势迁到可展开的“市场证据”。

**Step 3: 实现一级视图状态**

新增前端状态 `primaryMode = "today" | "research"`。切换只改变可见区域，不重写日报 JSON，也不触发网络请求。

**Step 4: 实现桌面布局与移动端不退化样式**

- 桌面候选列 320–340px。
- 页头 56–64px。
- 资金主线条 72–80px。
- 760px 以下保持现有单列和 drawer 逻辑。

**Step 5: 运行局部测试**

Run:

```bash
python3 -m unittest tests.test_auxiliary_frontend tests.test_report_sentiment_layout -v
```

Expected: PASS。

**Step 6: 提交**

```bash
git add chanlun/report_assets/report-v2.js chanlun/report_assets/report-v2.css tests/test_auxiliary_frontend.py tests/test_report_sentiment_layout.py
git commit -m "feat: 重排日报决策工作台首屏"
```

### Task 3: 重组候选导航并压缩候选行

**Files:**
- Modify: `chanlun/report_view_model.py`
- Modify: `chanlun/report_assets/report-v2.js`
- Modify: `chanlun/report_assets/report-v2.css`
- Test: `tests/test_report_view_model.py`
- Test: `tests/test_auxiliary_frontend.py`
- Test: `tests/test_report_generator.py`

**Step 1: 写失败测试——候选导航与推荐空态**

在 `tests/test_report_view_model.py` 断言公共导航输出：

```text
main        → 主推
confirming  → 待确认
observation_top5 → 观察
research    → 独立研究池容器
```

研究池中保留 `baseline`、`h4_t3`、`acceleration`、`luojie`、`growth_quality` 等原始 key 与独立说明。

再准备正常空池、数据不可用、正式动作封闭三个 fixture，断言：

- 今日决策页均只显示“本期未选出推荐票”。
- 今日决策页 DOM、提示框、`title` 和无障碍文本不包含内部状态、原因码或校验术语。
- 日报 JSON、研究验证和数据诊断仍保留三种真实原因。
- 板块筛选零命中与整份报告加载失败使用各自空态，不复用推荐空态。
- 不得从待确认、观察或研究池回填主推荐。

**Step 2: 运行并确认 RED**

Run:

```bash
python3 -m unittest tests.test_report_view_model tests.test_auxiliary_frontend tests.test_report_generator -v
```

Expected: FAIL，因为当前 `view_order` 仍平铺九个视图，推荐空态也尚未统一隔离用户文案与内部原因。

**Step 3: 实现分组元数据**

只新增 UI 分组合同，不合并或重算任何池。保留原 `workspace.views`，增加供前端消费的分组元数据，例如 `workspace.navigation_groups`。

**Step 4: 压缩候选行**

候选行常驻字段限定为名称/代码、涨跌幅、正式动作、主要周期和最多两个标签。完整来源、共振、风险原因进入详情和审计抽屉。

同时实现主推荐区统一空态：当主推荐池因正常空池、数据不可用或正式动作封闭而为空时，今日决策页只显示“本期未选出推荐票”。内部 `status`、`reason_code` 和校验术语不得进入正文、提示框、`title` 或无障碍文本，但必须继续保留在日报 JSON、研究验证和数据诊断中。

板块筛选后零命中继续显示筛选条件；整份报告加载失败继续显示页面级错误。两者不得复用主推荐空态，也不得从其他池回填推荐票。

**Step 5: 运行测试**

```bash
python3 -m unittest tests.test_report_view_model tests.test_auxiliary_frontend tests.test_report_generator -v
```

Expected: PASS。

**Step 6: 提交**

```bash
git add chanlun/report_view_model.py chanlun/report_assets/report-v2.js chanlun/report_assets/report-v2.css tests/test_report_view_model.py tests/test_auxiliary_frontend.py tests/test_report_generator.py
git commit -m "feat: 分组候选导航并统一空态"
```

### Task 4: 建立 P0 资金主线筛选

**Files:**
- Modify: `chanlun/report_assets/report-v2.js`
- Modify: `chanlun/report_assets/report-v2.css`
- Test: `tests/test_auxiliary_frontend.py`

**Step 1: 写失败测试——资金主线语义**

断言：

- P0 标题固定为“资金主线”，不使用“热门板块”。
- 标签只消费现有 `sector_flow`/`sector_outflow` 事实。
- 无数据或过期状态不能渲染为“今日无热点”。

**Step 2: 写失败测试——筛选状态**

暴露纯函数并测试：

- 精确标准化名称匹配。
- 筛选只作用于当前池。
- 非空时选择第一只。
- 空结果保留当前池并返回明确空态。
- 清除筛选恢复原列表。
- 过滤前后 `action` 和池身份不变。

**Step 3: 实现最小筛选状态**

新增 `state.sectorFilter`，复用现有候选渲染，不改变 `state.workspace` 原始数据。

**Step 4: 运行测试**

```bash
python3 -m unittest tests.test_auxiliary_frontend -v
```

Expected: PASS。

**Step 5: 提交**

```bash
git add chanlun/report_assets/report-v2.js chanlun/report_assets/report-v2.css tests/test_auxiliary_frontend.py
git commit -m "feat: 增加资金主线候选筛选"
```

### Task 5: 合并个股详情并锁定唯一正式动作

**Files:**
- Modify: `chanlun/report_assets/report-v2.js`
- Modify: `chanlun/report_assets/report-v2.css`
- Test: `tests/test_auxiliary_frontend.py`
- Test: `tests/test_report_generator.py`

**Step 1: 写失败测试——正式动作来源**

使用包含正式融合决策与多个策略意见的固定 payload，断言：

- 决策头只显示正式融合动作。
- 策略意见只渲染为支持/保留/反对/样本不足。
- AI 文案必须包含“不改变正式动作”或等价的显式边界。

**Step 2: 写失败测试——详情结构**

断言详情只保留：

- 决策头。
- K 线工作区。
- 为什么/下一确认/失效条件三栏。
- 证据与审计抽屉。

**Step 3: 实现决策头和三栏摘要**

复用现有 `action_reason`、`primary_reason`、`risk_flags`、`upgrade_conditions`、`cancel_conditions` 和证据字段。每栏执行数量上限，不删除完整审计数据。

**Step 4: 实现缺失字段降级**

P0 不推导 `position_band`、`intended_horizon` 或 `pressure_price`。缺失则省略或显示“合同未声明”。

**Step 5: 运行测试**

```bash
python3 -m unittest tests.test_auxiliary_frontend tests.test_report_generator -v
```

Expected: PASS。

**Step 6: 提交**

```bash
git add chanlun/report_assets/report-v2.js chanlun/report_assets/report-v2.css tests/test_auxiliary_frontend.py tests/test_report_generator.py
git commit -m "feat: 合并个股决策详情"
```

### Task 6: 实现图表标签车道和碰撞治理

**Files:**
- Modify: `chanlun/report_assets/report-v2.js`
- Modify: `chanlun/report_assets/report-v2.css`
- Test: `tests/test_auxiliary_frontend.py`

**Step 1: 写失败测试——价标选择纯函数**

提取并测试 `selectPersistentPriceLabels()` 或同等纯函数：

- 优先级：失效位 > 现价 > 参考价 > 压力位。
- 最多两个常驻标签。
- 价差小于 0.6% 时合并。
- 不改变真实 y 值。

**Step 2: 写失败测试——历史动作标记**

断言：

- 只保留一个最新动作文字。
- 历史动作只有点和 tooltip。
- 每 40 根 K 线最多三个文字标记。

**Step 3: 运行并确认 RED**

```bash
python3 -m unittest tests.test_auxiliary_frontend -v
```

Expected: FAIL，因为当前直接透传全部 `markPoint.label`。

**Step 4: 实现右侧标签车道**

- grid 右边距使用 96–144px 的响应式约束。
- 价标放入右侧车道，以引线连接真实价格。
- 最后五根 K 线保留无遮挡区域。
- 标签纵向间距小于 24px 时执行合并或车道错位。

**Step 5: 实现互斥图层**

提供 `决策位 / 结构 / 趋势` 互斥切换；数据不存在时不显示相应入口。

**Step 6: 运行测试**

```bash
python3 -m unittest tests.test_auxiliary_frontend tests.test_report_sentiment_layout -v
```

Expected: PASS。

**Step 7: 提交**

```bash
git add chanlun/report_assets/report-v2.js chanlun/report_assets/report-v2.css tests/test_auxiliary_frontend.py tests/test_report_sentiment_layout.py
git commit -m "fix: 治理K线标注叠压"
```

### Task 7: 重排第二屏和研究验证页

**Files:**
- Modify: `chanlun/report_assets/report-v2.js`
- Modify: `chanlun/report_assets/report-v2.css`
- Test: `tests/test_auxiliary_frontend.py`
- Test: `tests/test_report_sentiment_layout.py`

**Step 1: 写失败测试——模块归属**

断言：

- 今日决策第二屏只包含市场方向、我的观察和持仓风控。
- 研究验证页包含策略记分牌、影子评测、数据诊断和市场证据详情。
- 正常诊断默认折叠。
- 辅助区不再使用会被长卡撑高的四列同权 Grid。

**Step 2: 实现两个独立纵向栈**

长内容不再与短卡共享同一行高；市场方向和观察池按全宽或独立列自然增长。

**Step 3: 运行测试**

```bash
python3 -m unittest tests.test_auxiliary_frontend tests.test_report_sentiment_layout -v
```

Expected: PASS。

**Step 4: 提交**

```bash
git add chanlun/report_assets/report-v2.js chanlun/report_assets/report-v2.css tests/test_auxiliary_frontend.py tests/test_report_sentiment_layout.py
git commit -m "refactor: 分离今日决策与研究验证"
```

### Task 8: 完成 P0 真实页面与截图验收

**Files:**
- Modify if needed: `chanlun/report_assets/report-v2.js`
- Modify if needed: `chanlun/report_assets/report-v2.css`
- Verify: `docs/2026-08-27/index.html`
- Verify: `docs/data/2026-08-27.json`

**Step 1: 运行 P0 回归**

```bash
python3 -m unittest \
  tests.test_report_view_model \
  tests.test_report_generator \
  tests.test_auxiliary_frontend \
  tests.test_report_sentiment_layout -v
```

Expected: PASS。

**Step 2: 运行全量测试**

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

Expected: PASS；记录实际测试数量和耗时。

**Step 3: 使用已有当日报告或冻结 fixture 生成预览**

不得为了 UI 验收触发未经授权的正式数据补跑或发布。优先使用已有 `docs/data/YYYY-MM-DD.json` 和本地静态服务器。

**Step 4: 截图验收**

保存：

- 1440×900 今日决策首屏。
- 1366×768 今日决策首屏。
- 1440px K 线最右侧近距价标场景。
- 主推荐池为空场景，验证只显示“本期未选出推荐票”。
- 390px 不退化回归截图。

逐项核对设计文档第 19.1 节。

**Step 5: 修复视觉问题并重新执行局部测试与截图**

任何 CSS 调整后重新运行 `tests.test_auxiliary_frontend` 和 `tests.test_report_sentiment_layout`。

**Step 6: 提交 P0 验收修复**

```bash
git add chanlun/report_assets/report-v2.js chanlun/report_assets/report-v2.css tests
git commit -m "test: 完成决策工作台P0验收"
```

## P1：热门板块与正式决策合同

### Task 9: 增加 `sector_heat` 合同

**Files:**
- Modify: `chanlun/auxiliary_decision.py`
- Modify: `run.py`
- Modify: `chanlun/report_generator.py`
- Modify: `chanlun/report_assets/report-v2.js`
- Test: `tests/test_auxiliary_decision.py`
- Test: `tests/test_report_generator.py`
- Test: `tests/test_auxiliary_frontend.py`

**Step 1: 写失败合同测试**

覆盖：

- `sector_code`、`sector_name`、`change_pct`、`rank`。
- `up_count`、`total_count`、`limit_up_count`。
- `as_of`、`source`、`status`。
- 完整、部分、缺失、过期和错误状态。
- 无广度时不能冒充完整热门板块。

**Step 2: 实现确定性合同构建**

事实获取与 UI 排序分离；不将资金、涨幅和涨停合成综合分。

**Step 3: 序列化到日报 JSON**

保留 `sector_flow` 兼容字段；`sector_heat` 是“热门板块”唯一权威合同。

**Step 4: 前端切换标题与字段**

只有 `sector_heat.status=verified_complete` 或满足设计允许的明确部分状态时才展示“热门板块”；否则继续使用“资金主线”或明确降级。

**Step 5: 运行测试**

```bash
python3 -m unittest tests.test_auxiliary_decision tests.test_report_generator tests.test_auxiliary_frontend -v
python3 -m py_compile chanlun/auxiliary_decision.py run.py chanlun/report_generator.py
```

Expected: PASS。

**Step 6: 提交**

```bash
git add chanlun/auxiliary_decision.py run.py chanlun/report_generator.py chanlun/report_assets/report-v2.js tests/test_auxiliary_decision.py tests/test_report_generator.py tests/test_auxiliary_frontend.py
git commit -m "feat: 增加可审计热门板块合同"
```

### Task 10: 增加 `formal_decision_contract`

**Files:**
- Modify: `chanlun/report_view_model.py`
- Modify: `chanlun/report_generator.py`
- Modify: `chanlun/report_assets/report-v2.js`
- Test: `tests/test_report_view_model.py`
- Test: `tests/test_report_generator.py`
- Test: `tests/test_auxiliary_frontend.py`

**Step 1: 写失败合同测试**

覆盖 `action`、`action_reason`、`intended_horizon`、`position_band`、`reference_price`、`invalidation_price`、`pressure_price`、`horizon_states`、`policy_version` 和 `evidence_refs`。

**Step 2: 写失败降级测试**

- 缺少唯一已验证周期时不显示周期。
- 周期冲突未解决时不得选择最乐观周期。
- 仓位合同缺失时不显示 `0%` 或推导区间。
- 压力位缺失时不从近期最高价临时推导。

**Step 3: 实现公共外层合同**

合同只消费各策略池已经形成并验收的输出，不改变池内逻辑。汇总层只能保持或降低状态，不能升级观察为推荐。

**Step 4: 前端按合同显示字段**

决策头只从 `formal_decision_contract` 读取仓位、周期和关键位；旧快照按 P0 降级。

**Step 5: 运行测试**

```bash
python3 -m unittest tests.test_report_view_model tests.test_report_generator tests.test_auxiliary_frontend -v
python3 -m py_compile chanlun/report_view_model.py chanlun/report_generator.py
```

Expected: PASS。

**Step 6: 提交**

```bash
git add chanlun/report_view_model.py chanlun/report_generator.py chanlun/report_assets/report-v2.js tests/test_report_view_model.py tests/test_report_generator.py tests/test_auxiliary_frontend.py
git commit -m "feat: 增加正式决策展示合同"
```

### Task 11: 完成 P1 联动与截图验收

**Files:**
- Modify if needed: `chanlun/report_assets/report-v2.js`
- Modify if needed: `chanlun/report_assets/report-v2.css`
- Test: `tests/test_auxiliary_frontend.py`

**Step 1: 增加 `sector_code/sector_refs` 精确映射测试**

禁止以模糊中文包含关系完成跨板块映射。

**Step 2: 验证四个交互场景**

1. 有结果热门板块。
2. 零结果热门板块。
3. 清除筛选。
4. 过滤前后正式动作不变。

**Step 3: 验证合同缺失场景**

准备一只无周期/仓位合同的股票，截图中不得出现伪值。

**Step 4: 运行 P1 回归和全量测试**

```bash
python3 -m unittest tests.test_auxiliary_decision tests.test_report_view_model tests.test_report_generator tests.test_auxiliary_frontend -v
python3 -m unittest discover -s tests -p 'test_*.py'
```

Expected: PASS。

**Step 5: 提交**

```bash
git add chanlun/report_assets/report-v2.js chanlun/report_assets/report-v2.css tests/test_auxiliary_frontend.py
git commit -m "test: 完成热门板块联动验收"
```

## P2：策略与 AI 研究验证

### Task 12: 增加正式动作与策略分歧模型

**Files:**
- Modify: `chanlun/report_generator.py`
- Modify: `chanlun/report_assets/report-v2.js`
- Test: `tests/test_report_generator.py`
- Test: `tests/test_auxiliary_frontend.py`

**Step 1: 写失败测试——策略立场**

将每个策略相对正式动作规范为 `support`、`reserve`、`oppose` 或 `insufficient_sample`，保留原因、周期、版本和证据引用。

**Step 2: 写失败测试——AI 边界**

AI 只能输出支持、风险提醒或证据不足。任何新的动作、仓位或目标价字段必须被拒绝或忽略，并记录诊断。

**Step 3: 实现分歧摘要与下钻抽屉**

首屏只显示数量摘要；研究验证页显示各策略详情。

**Step 4: 运行测试并提交**

```bash
python3 -m unittest tests.test_report_generator tests.test_auxiliary_frontend -v
git add chanlun/report_generator.py chanlun/report_assets/report-v2.js tests/test_report_generator.py tests/test_auxiliary_frontend.py
git commit -m "feat: 增加策略分歧审计视图"
```

### Task 13: 落实策略样本门和同口径比较

**Files:**
- Modify: `chanlun/strategy_review.py`
- Modify: `chanlun/report_generator.py`
- Modify: `chanlun/report_assets/report-v2.js`
- Test: `tests/test_strategy_review.py`
- Test: `tests/test_report_generator.py`
- Test: `tests/test_auxiliary_frontend.py`

**Step 1: 写失败测试——比较身份**

仅允许相同 `strategy + version + source_pool + entry_mode + intended_horizon + research_tier` 的统计进入同一比较组。

**Step 2: 写失败测试——成熟门**

少于 100 个成熟样本、20 个活跃交易日或 2 个非重叠自然月时：

- 只输出采集进度。
- 不输出收益排名、累计收益或胜率结论。
- 右删失样本不进入收益统计。

**Step 3: 实现成熟统计展示**

成熟后显示样本数、区间、中位收益、均值、基准超额、最大回撤、MFE 和 MAE，不输出无公式的综合分。

**Step 4: 运行测试**

```bash
python3 -m unittest tests.test_strategy_review tests.test_report_generator tests.test_auxiliary_frontend -v
```

Expected: PASS。

**Step 5: 提交**

```bash
git add chanlun/strategy_review.py chanlun/report_generator.py chanlun/report_assets/report-v2.js tests/test_strategy_review.py tests/test_report_generator.py tests/test_auxiliary_frontend.py
git commit -m "feat: 增加策略比较成熟门"
```

### Task 14: 完成 P2 确定性截图和全量回归

**Files:**
- Verify: `chanlun/report_assets/report-v2.js`
- Verify: `chanlun/report_assets/report-v2.css`
- Verify: generated report HTML/JSON

**Step 1: 准备三个固定场景**

1. 样本不足。
2. 样本成熟。
3. 正式动作与策略意见冲突。

**Step 2: 截图**

每个场景保存 1440px 桌面截图，逐项核对设计文档第 19.3 节。

**Step 3: 运行全量测试**

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m py_compile \
  chanlun/auxiliary_decision.py \
  chanlun/report_view_model.py \
  chanlun/report_generator.py \
  chanlun/strategy_review.py \
  run.py
```

Expected: PASS；记录实际测试数量、退出码和截图路径。

**Step 4: 验证 Git 边界**

```bash
git fetch origin main
git merge-base --is-ancestor origin/main HEAD
git status --short
git diff --check origin/main...HEAD
```

Expected:

- `origin/main` 是当前分支祖先。
- 工作区没有无关改动。
- `git diff --check` 退出码为 `0`。

**Step 5: 提交 P2 阶段**

```bash
git add chanlun tests docs/plans/2026-08-27-decision-workbench-ui-optimization-design.md docs/plans/2026-08-27-decision-workbench-ui-optimization-implementation-plan.md
git commit -m "feat: 完成决策工作台研究视图"
```

## P3：PSY12 市场情绪影子评测

### Task 15: 冻结 PSY12 证据与影子分合同

**Files:**
- Modify: `tests/test_market_sentiment.py`
- Modify: `tests/test_run_market_sentiment.py`

**Step 1: 写失败测试——12 日窗口**

覆盖：

- 报告日及此前 11 个有效交易日，按日期升序且日期唯一。
- `average_change_pct > 0` 计上涨日，`<= 0` 计非上涨日。
- `PSY12 = up_days / 12 × 100`。
- 少于 12 日、重复日期、未来日期、顺序异常或指数证据不可验证时返回 `unavailable`。
- 不可用时不得以 50 分补齐，影子总分必须为空。

**Step 2: 写失败测试——影子权重**

冻结以下权重：

```text
breadth=0.25
limit_ecology=0.30
index=0.10
turnover=0.15
trend=0.10
psy12=0.10
```

断言权重和为 1，并用固定组件分验证影子公式。2026-08-26 固定样例应得到 `PSY12=50`、影子原始分 `60.645`、展示分 `61`、标签“偏强”。

**Step 3: 写失败测试——生产隔离**

同一输入在增加 PSY12 后必须满足：

- `market_sentiment.score` 和 `label` 不变。
- `market_temperature` 不变。
- 正式 decision gate 输入不变。
- 新字段明确包含 `mode=shadow` 与 `affects_production=false`。

**Step 4: 运行测试并确认 RED**

```bash
python3 -m unittest tests.test_market_sentiment tests.test_run_market_sentiment -v
```

Expected: FAIL，原因是当前没有 PSY12 和影子分合同。

**Step 5: 提交测试**

```bash
git add tests/test_market_sentiment.py tests/test_run_market_sentiment.py
git commit -m "test: 固化PSY12影子情绪合同"
```

### Task 16: 实现 PSY12 计算与影子序列化

**Files:**
- Modify: `chanlun/market_sentiment.py`
- Modify: `run.py`
- Test: `tests/test_market_sentiment.py`
- Test: `tests/test_run_market_sentiment.py`

**Step 1: 实现 PSY12 纯函数**

只消费报告日及之前的市场情绪历史证据，输出 `status`、`score`、`up_days`、`valid_days`、`window`、`start_date`、`end_date` 和逐日方向审计。函数不读取未来日期，也不修改历史快照。

**Step 2: 实现影子分**

只有 PSY12 与五个现有组件全部可用时才计算：

```text
shadow_score_with_psy12 =
  breadth × 0.25
  + limit_ecology × 0.30
  + index × 0.10
  + turnover × 0.15
  + trend × 0.10
  + psy12 × 0.10
```

同时输出正式分、影子分、差值、正式标签、影子标签、权重版本和 `affects_production=false`。不得修改正式 `COMPONENT_WEIGHTS`。

**Step 3: 接入日报构建顺序**

在正式市场情绪和可用历史证据产生后构建 PSY12 影子结果，再序列化到日报 JSON。现有 `market_temperature`、融合解释和决策门控继续只消费正式市场情绪字段。

**Step 4: 运行测试**

```bash
python3 -m unittest tests.test_market_sentiment tests.test_run_market_sentiment tests.test_market_temperature -v
python3 -m py_compile chanlun/market_sentiment.py run.py
```

Expected: PASS；正式结果与修改前固定夹具一致。

**Step 5: 提交实现**

```bash
git add chanlun/market_sentiment.py run.py tests/test_market_sentiment.py tests/test_run_market_sentiment.py
git commit -m "feat: 增加PSY12市场情绪影子分"
```

### Task 17: 展示影子差异并建立 20 日观察门

**Files:**
- Create: `scripts/evaluate_market_sentiment_psy12_shadow.py`
- Create: `tests/test_market_sentiment_psy12_shadow.py`
- Modify: `chanlun/report_assets/report-v2.js`
- Modify: `chanlun/report_assets/report-v2.css`
- Modify: `tests/test_report_sentiment_layout.py`
- Modify: `tests/test_auxiliary_frontend.py`

**Step 1: 增加研究验证展示**

在“市场证据”或“研究验证”中展示 PSY12 窗口、上涨日数、正式分、影子分、差值和状态。所有影子内容常驻“影子，不影响正式决策”标识；首屏市场状态仍使用正式分。

**Step 2: 增加降级状态**

- 少于 12 日：显示“PSY12 数据不足”，不显示影子分。
- 历史证据异常：显示具体状态，禁止用最近自然日或中性分补齐。
- 正式/影子标签不同：差异只显示在研究验证页，不覆盖首屏正式标签。

**Step 3: 生成 20 日影子审计**

通过独立只读评测脚本对最近 20 个可完整计算 PSY12 的交易日输出：

- 逐日正式分、影子分、差值和标签变化。
- 平均差值、最大绝对差和标签变化次数。
- 假设转正式时会发生的 `market_temperature` 或决策门控变化清单。
- PSY12 与 `breadth`、`index` 的相关性，供重复计权复核。

结果只用于人工评审，不按事后收益自动选择权重，也不自动转正。

**Step 4: 确定性截图验收**

分别准备 PSY12 可用、数据不足、正式/影子标签不同三个场景，按设计文档第 20.4 节截图验收。

**Step 5: 运行回归**

```bash
python3 -m unittest \
  tests.test_market_sentiment \
  tests.test_market_sentiment_psy12_shadow \
  tests.test_run_market_sentiment \
  tests.test_market_temperature \
  tests.test_report_sentiment_layout \
  tests.test_auxiliary_frontend -v
python3 -m unittest discover -s tests -p 'test_*.py'
```

Expected: PASS；记录测试数量、退出码、20 日审计路径和三张截图路径。

**Step 6: 提交**

```bash
git add scripts/evaluate_market_sentiment_psy12_shadow.py tests/test_market_sentiment_psy12_shadow.py chanlun/report_assets/report-v2.js chanlun/report_assets/report-v2.css tests/test_report_sentiment_layout.py tests/test_auxiliary_frontend.py
git commit -m "feat: 增加PSY12影子评测视图"
```

## P4：14:47 预收盘三池预跑与盘后差异提醒

### Task 18: 冻结预跑快照、差异和正式隔离合同

**Files:**
- Create: `tests/test_preclose_contract.py`
- Create: `tests/test_preclose_formal_isolation.py`
- Create: `tests/fixtures/preclose/available.json`
- Create: `tests/fixtures/preclose/empty.json`
- Create: `tests/fixtures/preclose/expired.json`
- Create: `chanlun/preclose_contract.py`

**Step 1: 写失败测试——预跑快照最小合同**

在 `tests/test_preclose_contract.py` 固定以下约束：

```python
def test_available_snapshot_is_advisory_and_non_final():
    snapshot = build_preclose_snapshot(
        trade_date="2026-08-27",
        as_of="2026-08-27T14:47:00+08:00",
        generated_at="2026-08-27T14:48:30+08:00",
        pools={"main": [], "h4_t3": [], "acceleration": []},
        source_sha="6412624",
    )
    assert snapshot["schema_version"] == "preclose-selection-v1"
    assert snapshot["mode"] == "preclose_advisory"
    assert snapshot["is_final"] is False
    assert snapshot["affects_formal"] is False
    assert snapshot["expires_at"] == "2026-08-27T14:56:30+08:00"
    assert set(snapshot["pools"]) == {"main", "h4_t3", "acceleration"}
```

补充断言：

- `content_hash` 对规范化内容稳定，对股票代码、顺序或 `as_of` 变化敏感。
- 股票公开字段只包含合同允许的字段；内部诊断单独保存。
- 超时或三个池均不可执行时公开文案为“本期未选出推荐票”。
- 过期判断同时覆盖服务端时间和浏览器使用的 ISO 时间。

**Step 2: 写失败测试——正式路径零写入**

在 `tests/test_preclose_formal_isolation.py` 建立临时目录，创建以下哨兵文件并记录内容 hash 与 mtime：

```text
market_history.sqlite
recommendation_ledger.jsonl
docs/data/2026-08-27.json
docs/index.html
docs/data/comparison-index.json
```

运行预跑 fixture 后断言全部保持不变，同时断言预跑只写入：

```text
.cache/chanlun/preclose/2026-08-27/snapshot.json
.cache/chanlun/preclose/2026-08-27/diagnostics.json
```

**Step 3: 写失败测试——正式输出生产不变性**

用固定行情 fixture 计算两组正式摘要：

```python
baseline = normalized_formal_summary(run_formal_fixture())
run_preclose_fixture()
after = normalized_formal_summary(run_formal_fixture())
assert after == baseline
assert sha256_json(after) == sha256_json(baseline)
```

摘要至少包含 `picks_pure`、`picks_fusion`、H4、加速池、正式动作、股票顺序和策略版本。分别覆盖预跑成功、失败、超时和未运行。

**Step 4: 运行测试并确认 RED**

Run:

```bash
python3 -m unittest \
  tests.test_preclose_contract \
  tests.test_preclose_formal_isolation -v
```

Expected: FAIL，原因是预跑合同和隔离入口尚不存在。

**Step 5: 实现最小合同纯函数**

在 `chanlun/preclose_contract.py` 只实现：

- `normalize_preclose_candidate()`
- `build_preclose_snapshot()`
- `snapshot_content_hash()`
- `is_preclose_expired()`
- `build_public_preclose_view()`
- `normalized_formal_summary()`

该模块不得导入 `run.py`、数据抓取器、账本或报告生成器。

**Step 6: 运行测试并确认 GREEN**

Run: 同 Step 4。

Expected: PASS。

**Step 7: 提交**

```bash
git add chanlun/preclose_contract.py tests/test_preclose_contract.py tests/test_preclose_formal_isolation.py tests/fixtures/preclose
git commit -m "test: 固化预跑与正式隔离合同"
```

### Task 19: 实现独立盘中行情快照

**Files:**
- Create: `chanlun/preclose_data.py`
- Create: `tests/test_preclose_data.py`
- Modify: `.gitignore`

**Step 1: 写失败测试——只读取允许的数据粒度**

用 spy fetcher 断言：

- 读取历史日线和 14:47 盘中日线快照。
- 日线初筛前不批量读取 30 分钟数据。
- 日线初筛后只为目标代码读取 30 分钟数据。
- 不请求 1 分钟、5 分钟、15 分钟、新闻、LLM 或 iWencai。
- 行情源返回正在形成的 30 分钟柱时保留 `is_final=false`，不得改写为正式收盘柱。
- 当前 30 分钟证据缺失时返回可审计的 unavailable 状态，不使用旧日期缓存冒充当日数据。

**Step 2: 写失败测试——独立数据命名空间**

用 `tempfile.TemporaryDirectory()` 创建隔离根目录后显式传入：

```python
with tempfile.TemporaryDirectory() as temp_dir:
    root = Path(temp_dir)
    paths = PrecloseDataPaths(
        root=root / ".cache/chanlun/preclose",
        formal_market_db=root / "market_history.sqlite",
    )
```

断言 `formal_market_db` 只允许只读打开，所有盘中快照写入 `root/<trade_date>/input.json`；路径解析拒绝 `docs/`、正式 ledger 和正式 market DB 作为输出目标。

**Step 3: 运行测试并确认 RED**

Run:

```bash
python3 -m unittest tests.test_preclose_data -v
```

Expected: FAIL，原因是 `preclose_data` 尚不存在。

**Step 4: 实现最小数据适配器**

实现：

- `PrecloseDataPaths`
- `build_intraday_daily_snapshot()`
- `fetch_target_30m_snapshots()`
- `build_preclose_market_inputs()`
- `write_preclose_input_snapshot()`

只复用现有行情请求的只读能力，不调用 `collect_daily_data(required_date=today)` 的正式终局门禁，不写正式 repository。正在形成的日线和 30 分钟柱都附加 `bar_state=intraday`、`is_final=false` 和实际 `as_of`。

**Step 5: 忽略本地预跑产物**

在 `.gitignore` 增加：

```gitignore
.cache/chanlun/preclose/
```

不得忽略方案文档或测试 fixture。

**Step 6: 运行测试并确认 GREEN**

Run: 同 Step 3。

Expected: PASS。

**Step 7: 提交**

```bash
git add .gitignore chanlun/preclose_data.py tests/test_preclose_data.py
git commit -m "feat: 增加独立预收盘行情快照"
```

### Task 20: 实现三池轻量预跑入口和 120 秒截止

**Files:**
- Create: `chanlun/preclose_pipeline.py`
- Create: `preclose_run.py`
- Create: `scripts/preclose_run.sh`
- Create: `tests/test_preclose_pipeline.py`
- Modify: `tests/test_preclose_formal_isolation.py`

**Step 1: 写失败测试——只生成三个目标池**

在 `tests/test_preclose_pipeline.py` 注入固定日线、30 分钟和指数 fixture，断言输出只包含：

```python
assert set(result["pools"]) == {"main", "h4_t3", "acceleration"}
assert result["diagnostics"]["executed_stages"] == [
    "daily_structure",
    "target_30m_confirm",
    "market_context",
    "decision_engine",
    "main_public_view",
    "h4_t3",
    "acceleration",
]
```

为新闻、LLM、15 分钟、罗姐池、观察榜、Top10、报告生成、账本和 Git 发布注入抛错 spy；完整预跑仍必须通过，以证明这些依赖没有进入关键路径。

**Step 2: 写失败测试——保持三个池现有语义**

断言：

- 主推池沿用日线结构池、30 分钟候选升级、融合准入和统一评分。
- 主推候选使用盘中独立快照构建指数、上涨家数、涨停生态、成交额、趋势和板块等确定性市场输入，沿用当前正式组件权重；不调用 `_build_market_sentiment_history()`，不写正式 `MarketHistoryStore`。
- 为融合候选附加盘中只读行情形成的仓位/结构证据并调用 `chanlun.decision_engine.evaluate_stock()`；公开 `main` 只保留 `decision_engine_v1.decision_code == "recommend"`。
- 固定 fixture 下，预跑 `main` 与对等正式 fixture 经 `build_workspace()` 得到的 `workspace.views.main` 具有相同公开筛选语义；允许因 14:47 与收盘行情不同而产生成员差异。
- 正式日线一买/二买/三买不因 30 分钟缺失被删除；依赖 30 分钟升级的候选在证据缺失时不升级。
- H4 输入严格来自本次预跑 `picks_pure`，并保持自身生产模型和门槛。
- 加速池输入只来自本次预跑主推和强势启动观察输入，并保留现有指数涨幅门槛。
- PSY12 影子字段无论存在与否都不改变三个池的代码、顺序和动作。
- 加速池保持研究/观察语义，通知标签不得把它描述为正式主推动作。

**Step 3: 写失败测试——硬截止和幂等锁**

注入 monotonic clock：

- 120 秒内完成时发布 `available` 快照。
- 到 14:49 仍未完成时终止后续阶段，生成公开空态，内部状态记录 `deadline_exceeded`。
- 同一交易日已有活动 lock 时第二次运行退出且不覆盖首个成功快照。
- 相同输入重复运行产生相同 `content_hash`，但 `run_id` 不同。

**Step 4: 运行测试并确认 RED**

Run:

```bash
python3 -m unittest \
  tests.test_preclose_pipeline \
  tests.test_preclose_formal_isolation -v
```

Expected: FAIL，原因是轻量编排和入口尚不存在。

**Step 5: 实现独立编排**

`chanlun/preclose_pipeline.py` 直接调用现有独立策略模块，不导入或调用 `run.main()`，也不抽取/改写正式 `run.py` 阶段。实现：

- `PreclosePipelineConfig`
- `run_preclose_pipeline()`
- `build_preclose_main_pool()`
- `build_preclose_market_context()`
- `evaluate_preclose_main_candidates()`
- `build_preclose_h4_pool()`
- `build_preclose_acceleration_pool()`
- `PrecloseDeadlineExceeded`

`preclose_run.py` 只负责参数、锁、独立路径、退出码和诊断；`scripts/preclose_run.sh` 固定工作目录、Python 路径和日志路径，不 source 会改变正式策略模式的环境开关。

**Step 6: 运行测试并确认 GREEN**

Run: 同 Step 4。

Expected: PASS。

**Step 7: 回归正式三个池**

Run:

```bash
python3 -m unittest \
  tests.test_candidate_upgrade \
  tests.test_h4_t3_pool \
  tests.test_next_day_boom \
  tests.test_market_data_guard \
  tests.test_preclose_formal_isolation -v
```

Expected: PASS；正式摘要 hash 在四种预跑状态下不变。

**Step 8: 提交**

```bash
git add chanlun/preclose_pipeline.py preclose_run.py scripts/preclose_run.sh tests/test_preclose_pipeline.py tests/test_preclose_formal_isolation.py
git commit -m "feat: 增加14点47三池预跑入口"
```

### Task 21: 发布冻结快照并发送简洁预跑提醒

**Files:**
- Create: `chanlun/preclose_notify.py`
- Create: `tests/test_preclose_notify.py`
- Create: `cloudflare/preclose-worker/package.json`
- Create: `cloudflare/preclose-worker/src/index.ts`
- Create: `cloudflare/preclose-worker/wrangler.jsonc`
- Create: `cloudflare/preclose-worker/test/index.test.ts`
- Create: `cloudflare/preclose-worker/vitest.config.ts`
- Modify: `scripts/preclose_run.sh`

**Step 1: 写失败测试——Worker 独立 Durable Object 合同**

在独立 Worker 测试中创建 `PrecloseSnapshot` namespace，覆盖：

- `PUT /api/preclose/snapshot` 缺少或错误 `PRE_CLOSE_WRITE_TOKEN` 时返回 401。
- 首次写入成功；同一 `snapshot_id/content_hash` 重试幂等。
- 同日不同 hash 的并发覆盖需要 `If-Match` 或显式 revision，旧 revision 返回 412。
- `GET /api/preclose/latest?date=2026-08-27` 返回 `Cache-Control: no-store`。
- 服务端时间超过 `expires_at` 后，公开响应不再返回可执行候选。
- 只允许正式 GitHub Pages origin 的 CORS 和预检请求；拒绝其他 origin，写接口不得返回通配符 CORS。
- 公开 GET 不包含内部 diagnostics、失败原因、审计历史或写 token。
- 不同交易日通过 `env.PRE_CLOSE_SNAPSHOT.getByName(trade_date)` 命中不同实例，不得用一个全局对象保存全部日期。
- Worker 路由调用 Durable Object RPC，不自建绕过单线程语义的外部读写路径。
- 单独运行现有 Top10 Worker 回归并对其线上只读接口做前后回读；其 job、lock、latest、路由和 migration 文件均无代码改动。

**Step 2: 写失败测试——简洁提醒文案**

在 `tests/test_preclose_notify.py` 固定：

```text
【14:47预跑】14:56:30前有效
主推：宁波方正 300998｜参考26.86
H4 T+3：本期未选出推荐票
加速：新朋股份 002328｜参考7.61
14:57后不再下单
```

以及统一空态：

```text
【14:47预跑】
本期未选出推荐票
```

断言每池最多三只，不出现评分、PSY12、新闻、内部原因码、校验术语、仓位或“最高可买价”。

**Step 3: 运行测试并确认 RED**

Run:

```bash
cd cloudflare/preclose-worker && npm test
cd ../top10-worker && npm test
cd ../..
python3 -m unittest tests.test_preclose_notify -v
```

Expected: 新 Worker 测试和 Python 提醒测试先 FAIL；现有 Top10 Worker 回归继续 PASS。

**Step 4: 实现 Durable Object 和路由**

在独立 `cloudflare/preclose-worker` 中实现默认 Worker export 和 SQLite-backed `PrecloseSnapshot`。Worker 对交易日做严格格式校验后调用 `getByName(trade_date)`；Durable Object 暴露 `putSnapshot()`、`getPublicSnapshot()`、`putReconciliation()`、`getReconciliation()` RPC，并在对象内保存 snapshot、revision、reconciliation 和审计版本。HTTP 路由为：

```text
PUT /api/preclose/snapshot
GET /api/preclose/latest?date=YYYY-MM-DD
PUT /api/preclose/reconciliation
GET /api/preclose/reconciliation?date=YYYY-MM-DD
```

`wrangler.jsonc` 使用当前受支持的 `compatibility_date`、`nodejs_compat`、`observability.enabled=true`、正式 Pages `ALLOWED_ORIGINS`、`PRE_CLOSE_SNAPSHOT` binding 和首个 `new_sqlite_classes` migration。实现前先用当前 Wrangler v4 schema 校验配置并运行 `wrangler types`；写 token 通过 `wrangler secret put PRE_CLOSE_WRITE_TOKEN` 注入。鉴权比较使用 timing-safe 实现，密钥不得写入仓库、文档、构建日志或 Worker vars。

该任务严禁修改现有 `cloudflare/top10-worker`。Durable Object 类生命周期变更后不把简单 rollback 当作保证；回退路径是停止 launchd、禁用页面 `precloseApiBase`，并向前部署禁用写入/读取的 `preclose-worker` 版本，同时保留审计数据。

**Step 5: 实现 WxPusher 主提醒适配器**

在 `chanlun/preclose_notify.py` 实现：

- `format_preclose_message()`
- `format_reconciliation_message()`
- `send_wxpusher_message()`
- `send_wecom_text()`（可选通道）
- `NotificationOutbox`

主通道从专用 `~/.config/chanlun-strategy/preclose.env` 读取 `WXPUSHER_APP_TOKEN` 和 `WXPUSHER_UID`；部署时可安全复用本机已有股票推送凭证，但不得跨仓库运行时 import、输出变量值或提交 env 文件，文件权限必须为 `0600`。WxPusher 只有在 HTTP 成功且业务 JSON `success == true` 时才算发送成功。若配置 `WECOM_BOT_WEBHOOK`，可作为可选通道，且必须校验企业微信 JSON `errcode == 0`。失败只记录到预跑 outbox，不改变正式任务状态。

**Step 6: 串接快照发布和提醒**

`scripts/preclose_run.sh` 在本地快照原子落盘后：

1. PUT 相同 `snapshot_id/content_hash` 到 Worker。
2. GET 回读并核对 hash。
3. 只有回读一致才发送 WxPusher 主提醒；可选企业微信按独立 channel 记录结果。
4. Worker 或提醒失败只影响预跑状态和重试，不写正式路径。

**Step 7: 运行测试并确认 GREEN**

Run: 同 Step 3。

Expected: PASS。

**Step 8: 提交**

```bash
git add chanlun/preclose_notify.py tests/test_preclose_notify.py cloudflare/preclose-worker scripts/preclose_run.sh
git commit -m "feat: 发布预跑快照并发送简洁提醒"
```

### Task 22: 在同版工作台展示预跑和盘后复核

**Files:**
- Modify: `chanlun/report_assets/report-v2.js`
- Modify: `chanlun/report_assets/report-v2.css`
- Modify: `chanlun/report_generator.py`
- Create: `tests/test_preclose_frontend.py`
- Modify: `tests/test_auxiliary_frontend.py`

**Step 1: 写失败测试——即时预跑卡片**

用 Node VM 和固定 fetch fixture 断言：

- 今日决策页读取独立 `precloseApiBase + /api/preclose/latest?date=<pageDate>`，不得复用 `top10ApiBase`。
- 未过期时展示生成时间、失效时间和三个池；每池空态为“本期未选出推荐票”。
- 浏览器时钟超过 `expires_at` 后移除候选和参考价，不再保留可执行按钮。
- 请求失败不覆盖盘后正式主推，不把整页故障伪装成正式空池。
- DOM、`title` 和无障碍文本不泄露预跑内部失败原因。

**Step 2: 写失败测试——同一快照与盘后差异**

断言页面记录并展示 `snapshot_id/content_hash` 对应的更新时间；盘后 reconciliation 必须引用同一 `preclose_content_hash`，不匹配时拒绝展示差异。完全一致和存在变化分别使用设计文档 18.9 的用户文案。

**Step 3: 运行测试并确认 RED**

Run:

```bash
python3 -m unittest \
  tests.test_preclose_frontend \
  tests.test_auxiliary_frontend \
  tests.test_report_generator -v
```

Expected: FAIL，原因是预跑卡片和复核读取尚不存在。

**Step 4: 实现最小 UI**

在 P0 已建立的今日决策工作台中加入紧凑 `preclose-advisory` 区块，不新增第三个一级页面。预跑候选只提供池名、股票名/代码、参考价、生成和失效时间；详细差异放在同一区块的盘后复核折叠区。

`report_generator.py` 只注入独立 `precloseApiBase`，并保留现有 `top10ApiBase` 不变；不把预跑内容写进静态日报 bootstrap，避免 Pages 内容被盘中快照污染。`precloseApiBase` 缺失时只隐藏预跑区块，不影响正式日报和 Top10 功能。

**Step 5: 运行测试并确认 GREEN**

Run: 同 Step 3。

Expected: PASS。

**Step 6: 真实截图验收**

分别用 available、empty、expired、reconciliation-changed fixture 生成 1440×900 和 1366×768 截图；390px 只验证不退化。核对通知和网页的 `snapshot_id/content_hash` 一致。

**Step 7: 提交**

```bash
git add chanlun/report_assets/report-v2.js chanlun/report_assets/report-v2.css chanlun/report_generator.py tests/test_preclose_frontend.py tests/test_auxiliary_frontend.py
git commit -m "feat: 在决策工作台展示预跑复核"
```

### Task 23: 实现盘后正式/预跑差异和主动提醒

**Files:**
- Create: `chanlun/preclose_compare.py`
- Create: `scripts/preclose_reconcile.py`
- Create: `scripts/preclose_reconcile.sh`
- Create: `tests/test_preclose_compare.py`
- Modify: `tests/test_preclose_notify.py`
- Modify: `cloudflare/preclose-worker/test/index.test.ts`

**Step 1: 写失败测试——正式结果只读准入**

`scripts/preclose_reconcile.py` 只有同时满足以下条件才允许比较：

- 当日 `docs/data/<trade_date>.json` 存在且日期一致。
- 正式行情是收盘终局状态。
- 现有 `scripts/validate_today_report.py` 校验成功。
- 对正式 JSON 调用 `chanlun.report_view_model.build_workspace()` 后，`workspace.views.main`、`workspace.views.h4_t3` 和 `workspace.views.acceleration` 可按现有公开合同解析。

不满足时返回 `formal_pending`，用户提醒为“今日正式结果尚未生成，暂不继续参考预跑清单”，不得生成空池差异。

新增反例 fixture：原始 `picks_fusion` 含 A、B，但只有 B 的 `decision_engine_v1.decision_code == "recommend"`；正式主推必须解析为 B。输入健康门控清空 `workspace.views.main` 时也必须尊重清空结果，不得把原始候选恢复进差异。

**Step 2: 写失败测试——三池差异集合**

在 `tests/test_preclose_compare.py` 固定：

```python
assert diff_pool(["A", "B"], ["B", "C"]) == {
    "retained": ["B"],
    "added_after_close": ["C"],
    "removed_after_close": ["A"],
    "unchanged": False,
}
```

覆盖空对空、跨池移动、重复代码、不同顺序、正式结果重试和缺失池合同。默认提醒只比较成员变化；排名、参考价、信号类型和输入水位变化写入 `details`。

**Step 3: 写失败测试——主动提醒与幂等**

固定两类文案：

```text
【盘后复核】
正式结果与14:47预跑一致
主推2只｜H4 T+3 1只｜加速1只
```

```text
【盘后复核】与14:47预跑有变化
主推：保留 宁波方正｜正式新增 新朋股份｜预跑有、正式无 A股
H4 T+3：无变化
加速：正式新增 B股
```

幂等键固定为 `trade_date + formal_content_hash + channel`。相同正式 hash 的重复运行不重发；正式 hash 改变后允许新提醒，并保存前一个 reconciliation revision。

**Step 4: 运行测试并确认 RED**

Run:

```bash
python3 -m unittest \
  tests.test_preclose_compare \
  tests.test_preclose_notify -v
```

Expected: FAIL，原因是差异计算和独立复核器尚不存在。

**Step 5: 实现只读复核器**

在 `chanlun/preclose_compare.py` 实现：

- `normalize_preclose_pools()`
- `normalize_formal_workspace_views()`
- `diff_pool()`
- `build_reconciliation()`
- `reconciliation_content_hash()`

`scripts/preclose_reconcile.py` 只读预跑快照和正式日报，通过现有验证后调用 `build_workspace(formal_report)`，仅从三个用户可见 view 生成本地 reconciliation，PUT 到独立 Worker，GET 回读核对 hash，再调用 `NotificationOutbox`。不得直接比较原始 `picks_fusion`，不得导入 finalizer，不得修改日报、账本、记分卡或 comparison index。

`scripts/preclose_reconcile.sh` 使用独立锁和日志；任何异常只影响复核提醒自身退出码，不得向 `daily_run.sh` 传播。

**Step 6: 运行测试并确认 GREEN**

Run: 同 Step 4。

Expected: PASS。

**Step 7: 提交**

```bash
git add chanlun/preclose_compare.py scripts/preclose_reconcile.py scripts/preclose_reconcile.sh tests/test_preclose_compare.py tests/test_preclose_notify.py cloudflare/preclose-worker/test/index.test.ts
git commit -m "feat: 主动提醒盘后预跑差异"
```

### Task 24: 配置独立调度并完成端到端验收

**Files:**
- Create: `launchd/com.breakaway4here.chanlun-preclose.plist`
- Create: `launchd/com.breakaway4here.chanlun-preclose-reconcile.plist`
- Create: `scripts/install_preclose_launchd.sh`
- Create: `tests/test_preclose_launchd.py`
- Create: `docs/runbooks/chanlun-preclose-runbook.md`

**Step 1: 写失败测试——调度完全独立**

解析两个 plist 并断言：

- 预跑任务工作日 14:47 触发 `scripts/preclose_run.sh`。
- 复核任务工作日 15:05 独立启动 `scripts/preclose_reconcile.sh`；脚本每 30 秒只读轮询正式就绪状态，最晚 15:35 退出。
- 两个任务使用不同 label、锁和日志路径。
- 两个任务都不调用 `daily_run.sh`，正式 launchd 配置也不依赖预跑或复核任务。
- `daily_run.sh` 的文件内容在 P4 实施前后保持不变。

**Step 2: 运行测试并确认 RED**

Run:

```bash
python3 -m unittest tests.test_preclose_launchd -v
```

Expected: FAIL，原因是独立调度尚不存在。

**Step 3: 实现 launchd 配置和安装脚本**

安装脚本负责模板校验、复制、`launchctl bootstrap` 和加载后回读；不自动覆盖已有同名任务，发现冲突先退出。两个 wrapper 从专用 `~/.config/chanlun-strategy/preclose.env` 安全读取 `PRECLOSE_API_BASE`、`PRECLOSE_WRITE_TOKEN`、`WXPUSHER_APP_TOKEN`、`WXPUSHER_UID` 和可选 `WECOM_BOT_WEBHOOK`；env 文件必须属于当前用户且权限为 `0600`，不得把任何密钥写入 plist 明文、仓库、测试输出或运行手册。launchd 不依赖交互 shell profile。

脚本启动后先校验交易日；周末、法定休市日和非交易日直接记录 `skipped_non_trading_day`，不抓行情、不推送。

**Step 4: 运行自动化回归**

Run:

```bash
python3 -m unittest \
  tests.test_preclose_contract \
  tests.test_preclose_data \
  tests.test_preclose_pipeline \
  tests.test_preclose_formal_isolation \
  tests.test_preclose_compare \
  tests.test_preclose_notify \
  tests.test_preclose_frontend \
  tests.test_preclose_launchd -v
python3 -m unittest discover -s tests -p 'test_*.py'
cd cloudflare/preclose-worker && npm test && npx wrangler deploy --dry-run
cd ../top10-worker && npm test
```

Expected: PASS；记录测试数量和退出码。

**Step 5: 执行隔离 dry-run**

使用固定历史 fixture 和临时目录运行完整预跑、Worker 内存适配、提醒 mock、正式 fixture、差异计算。验收：

- 14:47 到快照生成的模拟耗时不超过 120 秒。
- 只产生三个池。
- 页面和提醒 hash 一致。
- 14:56:30 后双方同时失效。
- 预跑前后正式产物、数据库和账本 hash/mtime 不变。
- 盘后完全一致和有差异都主动生成一条幂等提醒。

**Step 6: 真实交易日影子验收**

当前任务已获得实施和上线授权，但外部提醒仍按门槛分阶段开启。先以 `notify=false` 连续运行至少一个真实交易日：

1. 14:47 真实抓取但只写预跑隔离目录。
2. 记录每阶段耗时和 14:49 截止状态。
3. 盘后读取正式结果并生成差异，但不发外部提醒。
4. 核对正式日报 SHA、正式账本和 Pages 与未启用预跑的基线语义一致。
5. 人工核对三个池、网页失效和差异文案后，再启用 WxPusher 主提醒；用真实测试消息校验供应商业务 JSON 与实际手机到达，企业微信仅在已配置时作为可选通道。

若当前实施时间已错过 14:47，不得用手工补跑冒充真实定时验收。应完成部署和调度后保持目标继续进行，在下一个真实交易日采集 14:47 触发、14:49 截止、14:56:30 失效和盘后复核证据；这些证据齐全前状态只能是“已部署待生产验收”。

**Step 7: 补充运行手册**

记录：手工运行、dry-run、查看锁/日志/快照、校验 Worker 回读、补发提醒、关闭预跑、关闭复核、供应商业务响应检查、现有 Top10 非回归回读，以及通过关闭 `precloseApiBase`/停止 launchd/向前部署禁用版本完成回退。不得把 webhook 或 token 写入手册，不得承诺在 Durable Object 生命周期变更后一定可以简单 rollback。

**Step 8: 提交**

```bash
git add launchd scripts/install_preclose_launchd.sh tests/test_preclose_launchd.py docs/runbooks/chanlun-preclose-runbook.md
git commit -m "chore: 配置预跑与盘后复核调度"
```

## 发布前独立门槛

实现完成不等于正式上线。本次用户已授权按方案完整发布，但仍必须逐项通过以下门槛：

1. 重新同步 `origin/main` 并解决非快进状态。
2. 在最新目标分支基础上重跑相关回归和全量测试。
3. 核对本地 HEAD、远端目标 SHA 和 Pages workflow。
4. 校验 Raw/Pages JSON、JS/CSS hash 与 HTML bootstrap。
5. 在已发布页面重复 1440×900、1366×768 和 390px 截图验收。
6. 确认线上同一股票只有一个正式动作，板块筛选不改变动作。
7. 确认小样本场景没有收益排名，AI 明确不改变正式动作。
8. 确认 PSY12 只输出影子结果，线上正式市场情绪分、市场温度和决策门控未被覆盖。
9. PSY12 连续 20 个有效交易日审计未完成或未单独授权时，禁止切换正式权重。
10. 确认主推荐空池只显示“本期未选出推荐票”，内部状态和原因仍可在研究验证或数据诊断中追溯。
11. 确认预跑成功、失败、超时和未运行四种场景下，盘后正式三池、动作、顺序和规范化 hash 与基线一致。
12. 确认预跑未写正式行情库、正式账本、日报产物、记分卡或 comparison index。
13. 确认 14:47 任务没有调用新闻、LLM、iWencai、15 分钟策略、报告生成或 Git 发布。
14. 确认预跑在 14:49 前生成可用快照或真实空态，页面和提醒在 14:56:30 后同时失效。
15. 核对独立 Worker 回读、网页和 WxPusher 主提醒使用相同 `snapshot_id/content_hash`；供应商业务 JSON 明确成功且真实手机收到消息。
16. 确认正式结果生成后主动发送差异提醒；完全一致也提醒，相同正式 hash 的重试不重复发送。
17. 确认复核提醒失败不会改变 `daily_run.sh` 的退出码、正式产物或 Pages 发布状态。
18. 确认盘后正式三池来自 `build_workspace()` 的 `workspace.views.main/h4_t3/acceleration`，原始 `picks_fusion` 不直接参与差异。
19. 确认预跑主推运行当前确定性市场情绪和 `decision_engine_v1` 门控，同时没有写正式 `MarketHistoryStore`。
20. `cloudflare/preclose-worker` 完成 `wrangler deploy --dry-run`、正式 deploy、版本/部署 ID 记录以及生产 PUT/GET hash 回读；写 token 只存在 Wrangler secret。
21. 现有 Top10 Worker 代码、migration 和线上只读接口在部署前后无变化；若预跑回退，使用停止调度、禁用 `precloseApiBase` 和向前部署禁用版本。
22. `launchctl print` 显示两个任务已加载，专用 env 文件权限为 `0600`，日志中的真实 14:47 和盘后任务均由预期绝对路径执行。
23. 最新 `origin/main` 是发布提交祖先，最终提交已推送；Pages/Worker/launchd 三个运行面均回读到同一发布 SHA 或明确记录其对应版本。
24. 下一个真实交易日完成 14:47 触发、14:49 截止、14:56:30 失效、盘后正式结果不变和主动差异提醒的生产验收。
25. 正式 Pages origin 的跨域读取成功，其他 origin 被拒绝；公开 GET 不泄露 diagnostics、内部原因、审计历史或任何密钥。

未完成代码/部署门槛时只能描述为“本地实现/本地验收”；已部署但未完成真实交易日门槛时只能描述为“已部署待生产验收”；25 项全部有新鲜证据后才能宣布“完全上线”。

## 执行方式

本计划已完成最终 Review，并已获得实施和完全上线授权。执行任务必须先把本计划作为显式目标，在独立 worktree 中使用 `superpowers:executing-plans` 逐任务执行；每完成一个任务，先复核测试、视觉结果和变更范围，再进入下一任务。若因交易时点必须跨日等待，应保持目标未完成并继续到真实生产验收，不得在“已部署待生产验收”阶段提前结束。
