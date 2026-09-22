# 分钟数据诊断与研究观察修复实施计划

> **For Codex:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Apply superpowers:test-driven-development for every behavior change and superpowers:verification-before-completion before claiming success.

**Goal:** 在不改变正式选股、L1 v0、B0 与 H4 的前提下，补齐分钟数据失败证据，修正诊断/漏斗语义，并把固定 56 范围安全投影到现有观察入口。

**Architecture:** A 批沿 provider → repository → run 透传经过净化的失败证据；B 批从共同上游过滤前的观察项生成带明确研究标志的投影，只合并到最终 `observation_watchlist`。正式消费者显式拒绝该投影，`startup_watchlist` 保持原语义。

**Tech Stack:** Python 3、`unittest`、现有 JSON 报告与浏览器端静态资源。

---

## Task 1: 固定样本与边界测试夹具

**Files:**
- Create: `tests/fixtures/selection_2026_09_21_scope.json`
- Create: `tests/test_selection_0921_scope.py`

1. 先写失败测试，校验固定范围具有 29 个 30m 缺失、60 个 15m 缺失、56 个研究观察对象，并校验 56 中四个分钟缺失标的和 52 个有效未确认标的互斥且并集完整。
2. 夹具只保存身份和期望分类，不保存凭证、完整行情响应或可变运行结果。
3. 运行定向测试，确认夹具自洽。

## Task 2: A1 Provider 尝试证据

**Files:**
- Modify: `chanlun/data_fetcher.py`
- Create or Modify: `tests/test_minute_failure_evidence.py`

1. 先写测试覆盖：HTTP 非 JSON、连接错误、超时、响应校验失败、前一 provider 失败后一 provider 成功。
2. 实现响应摘要净化/截断、异常分类和专用耗尽异常。
3. 保持四次交替尝试和既有成功返回合同；成功时允许携带前序尝试诊断，耗尽时抛出安全诊断。
4. 运行新测试与既有行情保护测试。

## Task 3: A2 Repository 与输入健康透传

**Files:**
- Modify: `chanlun/kline_repository.py`
- Modify: `chanlun/data_fetcher.py`
- Modify: `run.py`
- Modify: `tests/test_market_data_guard.py`
- Modify: `tests/test_run_shadow_integration.py`

1. 先写测试证明远端耗尽后仍保留最后缓存日期、过期状态、最终不采用和拒绝原因。
2. repository 捕获专用异常并把诊断写入 `KLineResult`，不把无效远端结果落库。
3. 为批量 15m/30m 接口增加兼容的可选诊断接收参数；现有调用和返回值不变。
4. 在 `sublevel_input_health` 中只为缺失代码附加诊断，并校验无 URL、Cookie、token、完整请求参数。
5. 运行 repository、行情保护与 run 集成测试。

## Task 4: A3 强启动三分法与候选漏斗

**Files:**
- Modify: `chanlun/strong_startup.py`
- Modify: `run.py`
- Modify: `chanlun/candidate_funnel.py`（仅在现有字段合同确需扩展时）
- Modify: `tests/test_strong_startup.py`
- Modify: `tests/test_candidate_funnel.py`
- Modify: `tests/test_run_shadow_integration.py`

1. 先写三类输入测试并断言新计数互斥、旧字段兼容。
2. 实现 `watch_missing_30min`、`watch_valid_no_confirm` 与旧字段同步。
3. 先写漏斗失败测试，证明缺输入与有效未确认都不能通过 `minute30`，但各自输入/确认/展示状态可读。
4. 修正漏斗注册与阶段事件，不改变正式确认算法。
5. 运行 A 批相关完整回归。
6. 对比固定 29/60 范围与基线计数，记录证据后创建 A 批提交。

## Task 5: B1 研究观察投影与去重合并

**Files:**
- Modify: `run.py`
- Modify: `chanlun/report_view_model.py`
- Modify: `tests/test_market_data_guard.py`
- Modify: `tests/test_report_view_model.py`
- Modify: `tests/test_run_shadow_integration.py`

1. 先写测试：过滤前观察项被投影，52/4 状态正确，既有观察项按标准身份合并且不重复。
2. 实现独立纯函数，输入既有观察项和过滤前观察项，输出稳定、去重、非覆盖合并结果。
3. 投影只进入最终 `observation_watchlist`，保留当前 `startup_watchlist`。
4. view model 输出“待确认”或“分钟数据不足”，并保留日线依据和研究边界字段。
5. 运行 run 与 view model 回归。

## Task 6: B2 正式消费者隔离

**Files:**
- Modify: `nextday_research.py`
- Modify: `tests/test_nextday_research.py`
- Modify: `tests/test_nextday_public.py`
- Modify: `tests/test_strategy_review.py`
- Modify: `tests/test_h4_production_boundary.py`

1. 先写失败测试，证明研究投影当前会被 L1 原始池或 workspace 来源吸收。
2. 在 L1 两条来源路径统一拒绝 `eligible_for_l1_v0=false`，默认旧记录仍兼容为可用。
3. 断言固定输入下 L1 v0/B0、正式池、正式统计与 H4 输出不变，观察数量允许增加。
4. 运行 L1、策略复盘和 H4 边界测试。

## Task 7: B3 页面合同与固定 56 验收

**Files:**
- Modify: `chanlun/report_view_model.py`
- Modify: relevant report asset only if current renderer cannot display the status label
- Modify: `tests/test_report_generator.py`
- Modify: relevant frontend test
- Modify: `tests/test_selection_0921_scope.py`

1. 先写页面合同测试，要求两种状态标签可见且研究项不可执行。
2. 仅在必要时调整现有观察卡片渲染；不新增页面入口。
3. 用固定夹具验证 56 = 52 待确认 + 4 分钟数据不足、身份无重复。
4. 创建 B 批提交。

## Task 8: 独立审查、总回归与交付边界

1. 对 A/B 两个提交逐项审查差异，确认无 DB migration、无新 provider、无重试扩张、无历史报告写入。
2. 运行定向测试、受影响完整测试和静态编译检查；校验工作树只包含本批文件。
3. 验证 `origin/main` 仍为当前分支祖先；如目标分支变化，先同步后重跑相关测试。
4. 未获得发布授权时只交付分支/提交和验证结果；不得宣称线上生效。
5. 最终报告先列实际修复、恢复可见内容、未解决外部问题和正式链路影响。
