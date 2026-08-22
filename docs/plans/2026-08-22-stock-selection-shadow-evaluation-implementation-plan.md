# Stock Selection Shadow Evaluation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在完全不改变正式主推链路的前提下，将独立策略候选的收盘价影子评测、账本、页面和发布验收真正上线。

**Architecture:** 以当前 `origin/main` 为冻结生产基线；影子模块只消费正式结果或独立池结果的深拷贝，使用独立 pending/ledger、独立 scorecard 和顶层 `shadow_evaluations` 合同。正式主推执行前后计算规范化摘要并 fail-close，影子异常不能阻断日报。

**Tech Stack:** Python 3.9、`unittest`、SQLite 行情库、JSONL 影子账本、plain JavaScript/CSS、GitHub Pages。

---

### Task 1: 冻结正式输出并建立影子合同

**Files:**
- Create: `chanlun/shadow_evaluation.py`
- Test: `tests/test_shadow_evaluation.py`

**Step 1: Write the failing tests**

新增测试锁定：规范化摘要稳定；影子输入为深拷贝；构建器修改或抛错不会改变正式列表；输出固定 `mode=shadow`、`affects_production=false` 和 production guard。

**Step 2: Run tests and verify RED**

Run: `/usr/bin/python3 -m unittest tests.test_shadow_evaluation -v`

Expected: FAIL，模块或函数尚不存在。

**Step 3: Implement the minimal contract and guard**

实现 `production_digest()`、`run_shadow_evaluations()`、实验注册表和逐实验错误隔离。只注册具有明确版本、来源池、周期和收盘价口径的实验。

**Step 4: Run tests and verify GREEN**

Run: `/usr/bin/python3 -m unittest tests.test_shadow_evaluation -v`

Expected: PASS。

### Task 2: 建立独立影子账本与收盘价回看

**Files:**
- Modify: `chanlun/shadow_evaluation.py`
- Modify: `chanlun/strategy_review.py`
- Modify: `scripts/finalize_recommendation_ledger.py`
- Test: `tests/test_shadow_evaluation.py`
- Test: `tests/test_strategy_review.py`
- Test: `tests/test_finalize_recommendation_ledger.py`

**Step 1: Write failing outcome and ledger tests**

固定 OHLC fixture：信号日收盘价入场；T+1/T+3/T+5 使用未来交易日收盘；MFE/MAE 只含 D+1..D+N。断言影子条目使用独立 ID、`publication_effect=false`，pending 只在日报校验后固化。

**Step 2: Run tests and verify RED**

Run: `/usr/bin/python3 -m unittest tests.test_shadow_evaluation tests.test_strategy_review tests.test_finalize_recommendation_ledger -v`

Expected: FAIL，`immediate_close` 或影子账本尚未支持。

**Step 3: Implement immediate-close evaluation and isolated persistence**

扩展回看函数同时支持旧 `delay1_open` 和新 `immediate_close`，不改写旧样本。实现独立 shadow pending/ledger、幂等追加和 scorecard 聚合。

**Step 4: Run tests and verify GREEN**

Run: `/usr/bin/python3 -m unittest tests.test_shadow_evaluation tests.test_strategy_review tests.test_finalize_recommendation_ledger -v`

Expected: PASS。

### Task 3: 接入日报但保持正式链字节级不变

**Files:**
- Modify: `config.py`
- Modify: `run.py`
- Modify: `daily_run.sh`
- Modify: `chanlun/shadow_evaluation.py`
- Test: `tests/test_shadow_evaluation.py`
- Test: `tests/test_runtime_cutover.py`
- Test: `tests/test_run_shadow_integration.py`

**Step 1: Write failing integration tests**

用同一 fixture 断言影子开启/关闭时正式 `picks_fusion` 的代码、顺序、decision、reason、动作和正式推荐账本输入一致；影子候选不进入 H4、next-day 输入、正式 funnel 或正式账本。

**Step 2: Run tests and verify RED**

Run: `/usr/bin/python3 -m unittest tests.test_shadow_evaluation tests.test_runtime_cutover tests.test_run_shadow_integration -v`

Expected: FAIL，日报尚无独立影子字段。

**Step 3: Implement deep-copy integration**

在正式 H4、next-day、决策和正式账本均已形成后运行影子模块；正式对象只读，影子只写 `shadow_evaluations` 和 shadow pending。配置只允许 `off/shadow`，默认及 `daily_run.sh` 均为 `shadow`，拒绝 active。

**Step 4: Run tests and verify GREEN**

Run: `/usr/bin/python3 -m unittest tests.test_shadow_evaluation tests.test_runtime_cutover tests.test_run_shadow_integration -v`

Expected: PASS。

### Task 4: 将影子评测接入正式日报页面

**Files:**
- Modify: `chanlun/report_generator.py`
- Modify: `chanlun/report_assets/report-v2.js`
- Modify: `chanlun/report_assets/report-v2.css`
- Test: `tests/test_report_generator.py`
- Test: `tests/test_auxiliary_frontend.py`
- Test: `tests/test_shadow_evaluation.py`

**Step 1: Write failing serialization and UI contract tests**

断言 `shadow_evaluations` 同时进入 inline bootstrap、单日 JSON 和聚合 JSON；页面顺序为“策略记分牌 → 影子评测 → 数据诊断”；必须出现“影子评测中”“不影响正式主推”“样本进度”“尚未晋级原因”和“不是推荐”。

**Step 2: Run tests and verify RED**

Run: `/usr/bin/python3 -m unittest tests.test_report_generator tests.test_auxiliary_frontend tests.test_shadow_evaluation -v`

Expected: FAIL，页面尚未消费该字段。

**Step 3: Implement the Swiss audit card**

使用冷白底、蓝色状态、1px 分隔线和左右指标网格；不虚构数据、不截断影子候选。空状态明确“等待首个收盘样本”。

**Step 4: Run tests and syntax check**

Run: `/usr/bin/python3 -m unittest tests.test_report_generator tests.test_auxiliary_frontend tests.test_shadow_evaluation -v`

Run: `node --check chanlun/report_assets/report-v2.js`

Expected: 全部 PASS。

### Task 5: 生成可公开验收的最新页面

**Files:**
- Create: `scripts/enable_shadow_evaluation_snapshot.py`
- Modify generated artifacts only after verification: `docs/index.html`, `docs/data.json`, `docs/data/2026-08-21.json`, `docs/2026-08-21/index.html`
- Test: `tests/test_enable_shadow_evaluation_snapshot.py`

**Step 1: Write a failing snapshot test**

断言脚本只给最新已发布快照增加“从部署日起启用、等待首个新收盘样本”的真实空状态，不把 8 月 21 日已观察数据冒充 OOT；重建页面后正式主推摘要不变。

**Step 2: Run test and verify RED**

Run: `/usr/bin/python3 -m unittest tests.test_enable_shadow_evaluation_snapshot -v`

Expected: FAIL，脚本不存在。

**Step 3: Implement and run the snapshot enablement**

脚本读取最新正式 JSON，校验 report date 和正式摘要，注入 enabled-empty 合同，重建 index/archive/data aggregate，并再次验证摘要。

**Step 4: Verify generated artifacts**

Run: `/usr/bin/python3 scripts/enable_shadow_evaluation_snapshot.py --report-date 2026-08-21 --started-at 2026-08-22`

Run: `/usr/bin/python3 scripts/validate_today_report.py 2026-08-21`

Expected: 退出码 0；正式主推摘要不变，影子字段可见。

### Task 6: 全量回归、双重审查和发布

**Files:**
- Modify documentation only with actual results: `docs/plans/2026-08-20-auxiliary-decision-copilot-implementation.md`

**Step 1: Run full verification**

Run: `/usr/bin/python3 -m unittest discover -s tests`

Run: `/usr/bin/python3 -m py_compile run.py chanlun/shadow_evaluation.py chanlun/strategy_review.py chanlun/report_generator.py scripts/finalize_recommendation_ledger.py scripts/enable_shadow_evaluation_snapshot.py`

Run: `node --check chanlun/report_assets/report-v2.js`

Run: `/bin/zsh -n daily_run.sh`

Run: `git diff --check`

Expected: 全部退出码 0。

**Step 2: Perform independent spec and quality reviews**

审查必须逐项确认正式摘要不变、影子不进入正式消费者、收盘价窗口无泄漏、失败降级和页面字段完整。

**Step 3: Synchronize target branch before commit/merge**

Run: `git fetch origin`

确认 `origin/main` 为当前分支祖先；若远端前进，安全合入并重跑完整验证。

**Step 4: Push, merge and publish**

推送分支、创建 PR、复核远端差异后合并至 `main`。发布最新日报产物并等待 GitHub Pages 刷新。

**Step 5: Verify live state**

核对远端 main SHA、raw JSON、Pages 页面、桌面/390px 页面和日报日志；HTTP 200 不能代替内容验收。

### Task 7: 上线后审查辅助模块

**Files:**
- Modify only after evidence-backed review: auxiliary decision modules, tests and the implementation record.

**Step 1: Inspect the live auxiliary module**

检查方向、风险原因、关联个股、涨停生态、动态关注池、持仓风险、策略记分牌、影子评测和数据诊断的数据来源、空状态、重复信息及误导性措辞。

**Step 2: Classify findings**

P0：会误导正式决策或越权；P1：关键数据缺失/不可验证；P2：展示和可读性。任何改变选股池或主推的优化先进入影子。

**Step 3: Add failing tests before safe fixes**

只直接修复不会改变正式选股语义的 P0/P1 展示或数据合同问题；策略变化另立影子实验。

**Step 4: Re-run verification and live acceptance**

重复 Task 6 的相关回归与线上内容验收，记录已修项和保留项。
