# 行情单库与强股召回优化 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 修复错误决策和数据发布问题，建立 ongoing/backtest 共用的 SQLite 行情事实源，并上线全 A 召回、趋势延续、Top5 观察及严格样本外阈值校准。

**Architecture:** 保留现有缠论核心和上层 `fetch_*_kline()` 调用形状，新增 `MarketHistoryStore/KLineRepository` 作为唯一行情事实源。上游用全 A 低成本特征构建 800 只基础池并叠加最多 400 只热板块候选，下游分为低位、趋势延续和观察视图；所有阈值通过冻结 SQLite 快照上的门前 walk-forward 决定。

**Tech Stack:** Python 3、SQLite、NumPy、`unittest`、现有 `chanlun` 分析模块与报告流水线。

---

## 实施原则

- 每项行为变更先写失败测试，再写最小实现。
- 不修改缠论走势、笔、线段、中枢核心算法。
- 不碰当前工作区中与本计划无关的修改。
- 每个提交只包含对应任务文件，提交标题遵循仓库全局规范。
- P0 修复不得以功能开关回退到已确认的错误语义。
- 阈值实验不得自动改生产配置。

### Task 1: 修复位置缺失被误判为高位风险

**Files:**
- Modify: `chanlun/decision_engine.py`
- Modify: `config.py`
- Test: `tests/test_decision_engine.py`

**Step 1: 写失败测试**

覆盖：缺失距离、`NaN`、`Inf` 均返回 `observe + 暂不判断（位置信息不足）`；显式 35% 距离仍返回高位拒绝；仅有 `best_buy_point.price + closes` 不自动推荐。

**Step 2: 运行测试确认失败**

Run: `python3 -m unittest tests.test_decision_engine -v`
Expected: 新增断言在旧实现上失败。

**Step 3: 实现最小保护**

- 在总分判定前区分 `position_known`。
- 缺失位置直接返回 observe，不让位置扣分触发高位文案。
- 增加默认关闭的 `ENABLE_DISTANCE_DECISION`，禁止未校准推导距离参与推荐。

**Step 4: 运行测试**

Run: `python3 -m unittest tests.test_decision_engine -v`
Expected: PASS。

**Step 5: 提交**

```bash
git add chanlun/decision_engine.py config.py tests/test_decision_engine.py
git commit -m "fix: 区分位置缺失与高位风险"
```

### Task 2: 增加正式收盘发布门

**Files:**
- Modify: `chanlun/data_fetcher.py`
- Modify: `run.py`
- Modify: `scripts/validate_today_report.py`
- Modify: `daily_run.sh`
- Test: `tests/test_market_data_guard.py`

**Step 1: 写失败测试**

覆盖：同一天 14:35 日线不能标记 closed；`bar_state != closed` 不能成为 official；15:05 遇到盘中缓存必须刷新；validator 失败时发布流程终止。

**Step 2: 运行测试确认失败**

Run: `python3 -m unittest tests.test_market_data_guard -v`
Expected: 新增正式收盘断言失败。

**Step 3: 扩展数据契约**

- 为数据质量增加 `generated_at/as_of/bar_state`。
- `is_official` 同时要求日期一致、来源可信、`bar_state=closed`。
- `daily_run.sh` 在提交/推送前再次运行 validator。

**Step 4: 运行验证**

Run: `python3 -m unittest tests.test_market_data_guard -v`
Run: `python3 -m py_compile chanlun/data_fetcher.py run.py scripts/validate_today_report.py`
Expected: PASS。

**Step 5: 提交**

```bash
git add chanlun/data_fetcher.py run.py scripts/validate_today_report.py daily_run.sh tests/test_market_data_guard.py
git commit -m "fix: 增加正式收盘发布门"
```

### Task 3: 修复板块成分页

**Files:**
- Modify: `chanlun/data_fetcher.py`
- Modify: `config.py`
- Test: `tests/test_market_data_guard.py`

**Step 1: 写失败测试**

测试 100+50 返回 150、total=200 不取第三页、重复页停止、分页失败产生 incomplete 诊断且不能静默 official。

**Step 2: 运行测试确认失败**

Run: `python3 -m unittest tests.test_market_data_guard -v`
Expected: 旧代码只返回第一页或错误结束。

**Step 3: 实现分页 V2**

- `pz=100`，依据 `total` 和唯一代码数结束。
- `seen_codes` 去重，本页无新增时停止。
- 使用稳定代码排序。
- 输出 requested/fetched/unique/complete/error 结构化诊断。

**Step 4: 运行测试**

Run: `python3 -m unittest tests.test_market_data_guard -v`
Expected: PASS。

**Step 5: 提交**

```bash
git add chanlun/data_fetcher.py config.py tests/test_market_data_guard.py
git commit -m "fix: 修复板块成分分页"
```

### Task 4: 统一决策、操作和 Top10 语义

**Files:**
- Modify: `chanlun/report_view_model.py`
- Modify: `scripts/generate_top10_snapshot.py`
- Modify: `scripts/validate_today_report.py`
- Test: `tests/test_report_view_model.py`
- Test: `tests/test_generate_top10_snapshot.py`
- Test: `tests/test_market_data_guard.py`

**Step 1: 写失败测试**

覆盖：reject 不得“可上车”；observe/数据不足不得“可上车”；Top10 与 workspace 的代码、排名、动作、理由一致；非 official 日期不生成 Top10。

**Step 2: 运行测试确认失败**

Run: `python3 -m unittest tests.test_report_view_model tests.test_generate_top10_snapshot tests.test_market_data_guard -v`
Expected: 至少一个矛盾组合测试失败。

**Step 3: 实现权威动作规则**

- workspace 作为 Top10 唯一事实源。
- `decision_code` 对 action 设上限。
- 看点/观察/推荐显式分区。
- validator 阻断语义冲突。

**Step 4: 运行测试并提交**

Run: `python3 -m unittest tests.test_report_view_model tests.test_generate_top10_snapshot tests.test_market_data_guard -v`
Expected: PASS。

```bash
git add chanlun/report_view_model.py scripts/generate_top10_snapshot.py scripts/validate_today_report.py tests/test_report_view_model.py tests/test_generate_top10_snapshot.py tests/test_market_data_guard.py
git commit -m "fix: 统一Top10决策语义"
```

### Task 5: 新增 SQLite 行情存储

**Files:**
- Create: `chanlun/market_history_store.py`
- Modify: `config.py`
- Modify: `.gitignore`
- Test: `tests/test_market_history_store.py`

**Step 1: 写失败测试**

覆盖 schema 初始化、幂等 UPSERT、同主键新数据覆盖、股票窗口查询、横截面查询、`as_of` 截断、只读模式、`is_final` 和批次元数据。

**Step 2: 运行测试确认失败**

Run: `python3 -m unittest tests.test_market_history_store -v`
Expected: 模块不存在。

**Step 3: 实现最小数据层**

创建 `instruments/stock_meta_asof/trade_calendar/bars_day/bars_30m/bars_15m/ingest_runs/shard_manifests`。K 线表使用 `(instrument_id, ts)` 主键并增加 `(ts, instrument_id)` 索引。

**Step 4: 运行测试和静态检查**

Run: `python3 -m unittest tests.test_market_history_store -v`
Run: `python3 -m py_compile chanlun/market_history_store.py`
Expected: PASS。

**Step 5: 提交**

```bash
git add chanlun/market_history_store.py config.py .gitignore tests/test_market_history_store.py
git commit -m "feat: 增加统一行情数据库"
```

### Task 6: 实现分片回填与归并

**Files:**
- Create: `scripts/backfill_market_history.py`
- Create: `tests/test_backfill_market_history.py`
- Modify: `chanlun/data_fetcher.py`

**Step 1: 写失败测试**

覆盖稳定 `codes[i::20]` 分片、单股票只属于一个分片、manifest 完整性、失败分片可恢复、staging DB 幂等归并、非法 OHLC 拒绝。

**Step 2: 运行测试确认失败**

Run: `python3 -m unittest tests.test_backfill_market_history -v`
Expected: 脚本模块不存在。

**Step 3: 实现 backfill CLI**

支持 day 全 A、30m 每只 500 根、15m 指定代码；每片写独立 staging DB，完成后写 manifest，主控以单事务合并。

**Step 4: 运行测试**

Run: `python3 -m unittest tests.test_backfill_market_history tests.test_market_history_store -v`
Expected: PASS。

**Step 5: 提交**

```bash
git add scripts/backfill_market_history.py chanlun/data_fetcher.py tests/test_backfill_market_history.py
git commit -m "feat: 增加行情分片回填"
```

### Task 7: ongoing 接入 DB 优先读取

**Files:**
- Create: `chanlun/kline_repository.py`
- Modify: `chanlun/data_fetcher.py`
- Modify: `config.py`
- Test: `tests/test_kline_repository.py`
- Modify: `tests/test_kline_cache.py`

**Step 1: 写失败测试**

覆盖：本地完整不联网；缺失/过期/未 final 才补齐；远端失败返回 stale 状态；重叠增量覆盖；backtest 模式禁止联网；批量读取避免 N+1 行为退化。

**Step 2: 运行测试确认失败**

Run: `python3 -m unittest tests.test_kline_repository -v`
Expected: 模块不存在。

**Step 3: 实现 Repository**

保留 `fetch_daily_kline/fetch_30min_kline/fetch_15min_kline` 对上层返回形状，底层改为 DB-first。旧 JSON 仅在 shadow 开关下做结果对比，不长期双写。

**Step 4: 运行测试**

Run: `python3 -m unittest tests.test_kline_repository tests.test_kline_cache tests.test_market_data_guard -v`
Expected: PASS。

**Step 5: 提交**

```bash
git add chanlun/kline_repository.py chanlun/data_fetcher.py config.py tests/test_kline_repository.py tests/test_kline_cache.py
git commit -m "feat: ongoing接入DB优先行情"
```

### Task 8: 新增全 A 基础池与热板块 Overlay

**Files:**
- Create: `chanlun/universe_builder.py`
- Modify: `run.py`
- Modify: `config.py`
- Test: `tests/test_universe_builder.py`

**Step 1: 写失败测试**

覆盖 as-of 股票状态、低位350/趋势350/中性100、基础池硬上限800、overlay配额、上下级板块去重、最终800-1200、基础800不被overlay裁掉。

**Step 2: 运行测试确认失败**

Run: `python3 -m unittest tests.test_universe_builder -v`
Expected: 模块不存在。

**Step 3: 实现召回层**

- 计算 `low_position_retrieval_score` 和 `trend_retrieval_score`。
- `retrieval_score` 不进入推荐决策。
- 输出基础池、overlay来源和配额诊断。

**Step 4: 运行测试**

Run: `python3 -m unittest tests.test_universe_builder tests.test_market_data_guard -v`
Expected: PASS。

**Step 5: 提交**

```bash
git add chanlun/universe_builder.py run.py config.py tests/test_universe_builder.py
git commit -m "feat: 增加全A候选召回层"
```

### Task 9: 增加趋势延续通道和 Top5 观察视图

**Files:**
- Create: `chanlun/trend_continuation.py`
- Modify: `chanlun/strong_startup.py`
- Modify: `chanlun/fusion_admission.py`
- Modify: `chanlun/report_view_model.py`
- Modify: `run.py`
- Modify: `config.py`
- Test: `tests/test_trend_continuation.py`
- Modify: `tests/test_strong_startup.py`
- Modify: `tests/test_fusion_admission.py`
- Modify: `tests/test_report_view_model.py`

**Step 1: 写失败测试**

覆盖：趋势通道使用突破线/平台/MA10，不使用旧底背驰源价；条件化量比1.3必须伴随结构确认；涨停/过延伸只观察；Top5、同业最多2、同失败原因最多2；观察不进入主推荐计数。

**Step 2: 运行测试确认失败**

Run: `python3 -m unittest tests.test_trend_continuation tests.test_strong_startup tests.test_fusion_admission tests.test_report_view_model -v`
Expected: 新通道模块不存在。

**Step 3: 实现正交字段与分流**

加入 `source_channel/tier/category/quality_tier/view`；低位规则保持原义，趋势延续使用独立类型；后端保留完整 watch，workspace 派生 observation_top5。

**Step 4: 运行测试并提交**

Run: `python3 -m unittest tests.test_trend_continuation tests.test_strong_startup tests.test_fusion_admission tests.test_report_view_model -v`
Expected: PASS。

```bash
git add chanlun/trend_continuation.py chanlun/strong_startup.py chanlun/fusion_admission.py chanlun/report_view_model.py run.py config.py tests/test_trend_continuation.py tests/test_strong_startup.py tests/test_fusion_admission.py tests/test_report_view_model.py
git commit -m "feat: 增加趋势延续与Top5观察"
```

### Task 10: 保存门前漏斗和首杀原因

**Files:**
- Create: `chanlun/candidate_funnel.py`
- Modify: `run.py`
- Modify: `chanlun/market_history_store.py`
- Test: `tests/test_candidate_funnel.py`

**Step 1: 写失败测试**

覆盖每只股票仅记录一个 first_failure、全流程阶段顺序、量比/成交额比分列、距离和MA原始值保留、main/observe/reject终态完整。

**Step 2: 运行测试确认失败**

Run: `python3 -m unittest tests.test_candidate_funnel -v`
Expected: 模块不存在。

**Step 3: 实现 gate_events/funnel_runs**

记录全 A -> 合格 -> 基础/overlay -> 日线通道 -> 30m -> fusion -> 展示的数量和首个失败门。

**Step 4: 运行测试并提交**

Run: `python3 -m unittest tests.test_candidate_funnel -v`
Expected: PASS。

```bash
git add chanlun/candidate_funnel.py chanlun/market_history_store.py run.py tests/test_candidate_funnel.py
git commit -m "feat: 增加候选首杀漏斗"
```

### Task 11: 实现三日强股召回审计

**Files:**
- Create: `scripts/audit_next_day_top_recall.py`
- Create: `tests/test_next_day_top_recall_audit.py`

**Step 1: 写失败测试**

固定三组 T/T+1，验证只使用 T 日 official 数据；输出 Top20、Top30、>=9.5% 在各漏斗阶段的召回和独立增量。

**Step 2: 运行测试确认失败**

Run: `python3 -m unittest tests.test_next_day_top_recall_audit -v`
Expected: 脚本模块不存在。

**Step 3: 实现只读审计**

输入冻结数据库和 run 配置；输出 JSON + Markdown；禁止网络 fallback 和 T+1 题材反推。

**Step 4: 运行测试并提交**

Run: `python3 -m unittest tests.test_next_day_top_recall_audit -v`
Expected: PASS。

```bash
git add scripts/audit_next_day_top_recall.py tests/test_next_day_top_recall_audit.py
git commit -m "feat: 增加三日强股召回审计"
```

### Task 12: 实现门前 walk-forward 阈值实验

**Files:**
- Create: `scripts/run_recall_walkforward.py`
- Modify: `chanlun/policy_experiment_metrics.py`
- Modify: `scripts/run_policy_experiments.py`
- Test: `tests/test_recall_walkforward.py`
- Modify: `tests/test_policy_experiment_metrics.py`

**Step 1: 写失败测试**

覆盖30日训练、3日隔离、5个4日测试块、严格 `as_of`、单因子扫描、相邻档组合、bootstrap、阈值稳定性、注意力和尾部风险门禁。

**Step 2: 运行测试确认失败**

Run: `python3 -m unittest tests.test_recall_walkforward tests.test_policy_experiment_metrics -v`
Expected: 新runner测试失败。

**Step 3: 实现实验 runner**

扫描 3%/12%/量比/MA 参数，但生产默认不变；输出数据 hash、配置 hash、代码版本、覆盖、召回、收益、风险、观察数量和置信区间。

**Step 4: 运行测试并提交**

Run: `python3 -m unittest tests.test_recall_walkforward tests.test_policy_experiment_metrics tests.test_policy_experiment_runner_script -v`
Expected: PASS。

```bash
git add scripts/run_recall_walkforward.py chanlun/policy_experiment_metrics.py scripts/run_policy_experiments.py tests/test_recall_walkforward.py tests/test_policy_experiment_metrics.py
git commit -m "feat: 增加召回阈值样本外回放"
```

### Task 13: 影子运行、正式切换和全量验证

**Files:**
- Modify: `config.py`
- Modify: `scripts/validate_today_report.py`
- Modify: `daily_run.sh`
- Modify: `README.md`
- Test: relevant existing suites

**Step 1: 加影子比较和开关测试**

验证 legacy/new 数据与策略可以并行采集，但只有旧策略负责推送；切换后 SQLite 是唯一事实源；回滚不恢复错误高位标签。

**Step 2: 运行目标测试矩阵**

```bash
python3 -m unittest \
  tests.test_decision_engine \
  tests.test_market_data_guard \
  tests.test_generate_top10_snapshot \
  tests.test_report_view_model \
  tests.test_market_history_store \
  tests.test_backfill_market_history \
  tests.test_kline_repository \
  tests.test_universe_builder \
  tests.test_trend_continuation \
  tests.test_candidate_funnel \
  tests.test_next_day_top_recall_audit \
  tests.test_recall_walkforward -v
```

Expected: PASS。

**Step 3: 运行仓库回归和静态检查**

```bash
python3 -m unittest discover -s tests
python3 -m py_compile chanlun/*.py scripts/*.py run.py
git diff --check
```

Expected: 目标测试全绿；全量测试若出现已知环境噪声，必须单独报告，不得混成通过。

**Step 4: 执行数据验收**

- 数据覆盖率 >= 98%。
- 重复主键、非法 OHLC、`ts > as_of` 均为 0。
- 回测网络请求为 0。
- 三日召回达到最低线。
- 20 日风险和稳定性门禁通过。
- shadow 至少运行 3 个交易日。

**Step 5: 提交切换**

```bash
git add config.py scripts/validate_today_report.py daily_run.sh README.md
git commit -m "feat: 切换行情单库与召回策略"
```

## 执行交接

推荐使用当前会话的 Subagent-Driven 方式：按上述任务依次派发实现小兵，主控逐项审查测试证据和提交范围。P0、数据层、召回层、实验层之间存在明确依赖，不建议跨依赖并行改同一批文件。
