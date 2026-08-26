# Shadow Evaluation Runtime Repair Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 恢复 H4 影子 cohort 的每日冻结、账本归因与 T+1/T+3/T+5 展示，同时保证正式公开输出在影子运行前后完全不变，并记录事故复盘与防复发门禁。

**Architecture:** `report_generator.py` 提供 full daily 与 aggregate light 的唯一公开投影，writer 和 shadow guard 共用；`shadow_evaluation.py` 只把 H4 所需的最小候选快照交给 builder。状态分为采集健康、周期到期和人工比较准备度，历史失败日只记 gap。

**Tech Stack:** Python 3.7、NumPy、`unittest`、原生 JavaScript、GitHub Pages。

> 实施状态（2026-08-26）：Task 1–5 已完成；production-like off/shadow 验收与最终全量 1222 项测试通过。Task 6 等待同步、发布和 15:00 后首个正式 cohort 验收。

---

### Task 1: 建立权威正式公开投影

**Files:**
- Modify: `tests/test_report_generator.py`
- Modify: `tests/test_run_shadow_integration.py`
- Modify: `chanlun/report_generator.py`

**Step 1: Write the failing tests**

- 断言 full daily projector 与 `write_daily_data_json` 产物一致。
- 断言 aggregate light projector 与 `update_data_json` 当日 entry 一致。
- 断言未知 raw 顶层瞬态字段既不发布，也不改变 formal digest。
- 断言进入共享 projector 的正式字段发生变化时 digest 必须变化。

**Step 2: Run tests to verify RED**

Run:

```bash
python3 -m unittest tests.test_report_generator tests.test_run_shadow_integration
```

Expected: FAIL because shared `build_full_daily_projection` / `build_aggregate_day_projection` do not exist and guard still hashes raw data.

**Step 3: Implement minimal shared projectors**

- 从 `_generate_report_v2` 抽出 `build_full_daily_projection(report_data, include_shadow=True)`。
- 从 `update_data_json` 抽出 `build_aggregate_day_projection(report_data, include_shadow=True)`。
- 增加 `build_formal_output_projection(report_data)`，组合两种排除 shadow 的公开数据面。
- writer 复用 projector，不维护第二份字段 allowlist。

**Step 4: Run tests to verify GREEN**

Run the same command and require exit 0.

### Task 2: 建立 H4 最小输入与路径诊断

**Files:**
- Modify: `tests/test_shadow_evaluation.py`
- Modify: `tests/test_run_shadow_integration.py`
- Modify: `chanlun/shadow_evaluation.py`

**Step 1: Write the failing tests**

- 构造含 `np.array([1.0, np.nan])`、datetime/object array、bytes 和未发布 arbitrary object 的 production-like report。
- 断言未发布脏字段不阻断 shadow；H4 最小输入仍可生成 available experiment。
- 断言 H4 不读取的候选脏字段不进入 builder。
- 断言最小输入必需字段不合法时，错误包含 `failure_stage` 与 JSON path，且不 staging。
- 断言 builder 尝试修改输入不会改变正式公开摘要。

**Step 2: Verify RED**

Run:

```bash
python3 -m unittest tests.test_shadow_evaluation tests.test_run_shadow_integration
```

Expected: FAIL with the current raw projection error or missing path/stage fields.

**Step 3: Implement minimal H4 input**

- 显式投影 H4 固定特征、候选身份、收盘证明和 attestation。
- 对数组/标量做路径感知的 strict JSON 转换；研究输入中的非有限数按既有 H4 missing-value 语义转为 `None`。
- 外层 `production_guard` 改为共享 formal projection before/after digest。
- 内层 runner 只接收最小快照的深拷贝。

**Step 4: Verify GREEN**

Run the same command and require exit 0.

### Task 3: 增加三层状态与到期统计

**Files:**
- Modify: `tests/test_shadow_evaluation.py`
- Modify: `tests/test_run_shadow_integration.py`
- Modify: `chanlun/shadow_evaluation.py`

**Step 1: Write the failing tests**

- 正常零候选：`collection_health.status=ok`、staged empty batch、不是 unavailable。
- 系统失败：`collection_failed`、`data_gap=true`、包含 failure stage，pending 不存在。
- as-of D/D+1/D+3/D+5：T+1/T+3/T+5 从 right-censored 正确推进到 mature。
- comparison readiness 仅按同一实验身份、100 样本/20 日期/2 月派生，且始终不可自动晋级。

**Step 2: Verify RED**

Run focused shadow tests and confirm expected assertions fail.

**Step 3: Implement state derivation**

- 输出 `collection_health`、`outcome_maturity`、`comparison_readiness`。
- 保留旧 top-level status 兼容。
- scorecard 暴露三个周期 maturity counts，不把首个 T+3 称为策略成熟。

**Step 4: Verify GREEN**

Run focused shadow tests and require exit 0.

### Task 4: 收紧 finalizer 授权并更新页面

**Files:**
- Modify: `tests/test_finalize_recommendation_ledger.py`
- Modify: `tests/test_auxiliary_frontend.py`
- Modify: `scripts/finalize_recommendation_ledger.py`
- Modify: `chanlun/report_generator.py`
- Modify: `chanlun/report_assets/report-v2.js`

**Step 1: Write the failing tests**

- finalizer 只接受 schema、影子隔离声明、正式输出双摘要、`collection_health=ok|partial`、`data_gap is False` 且 report/pending digest 全部通过的批次。
- `collection_failed` 与旧 `unavailable` 均不得 append。
- 前端分别显示“采集成功，今日0只”“采集失败，本日形成数据缺口”“T+3已到期 n”“可/不可进入人工验收”。
- 未知或不合法三层状态继续 fail closed，隐藏研究指标。

**Step 2: Verify RED**

Run:

```bash
python3 -m unittest tests.test_finalize_recommendation_ledger tests.test_auxiliary_frontend tests.test_report_generator
```

Expected: FAIL because authorization and renderer do not understand the new contract.

**Step 3: Implement minimal authorization and renderer**

- 保留旧 payload 向后兼容。
- 新 payload 对 schema、隔离声明、formal guard、collection health、`data_gap` 和批次摘要全部 fail closed。
- 页面三块分别展示系统健康、周期到期和比较门槛。

**Step 4: Verify GREEN**

Run the same command and require exit 0.

### Task 5: 集成、真实回归与事故复盘

**Files:**
- Modify: `docs/plans/2026-08-22-auxiliary-decision-post-launch-audit.md`
- Create: `docs/reviews/2026-08-26-shadow-evaluation-runtime-incident-review.md`

**Step 1: Run targeted integration tests**

```bash
python3 -m unittest \
  tests.test_report_generator \
  tests.test_shadow_evaluation \
  tests.test_run_shadow_integration \
  tests.test_finalize_recommendation_ledger \
  tests.test_auxiliary_frontend
```

**Step 2: Run the full suite**

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

Expected: all tests pass with exit 0.

**Step 3: Run a production-like local acceptance**

- 对同一冻结输入分别运行 off/shadow，比较 full daily + aggregate light 正式摘要。
- 验证 experiment available、两个正式 SHA 均为相同 64 位值、pending staged，允许 zero candidates。
- 验证 finalizer 只在已验证报告与 pending digest 一致时 append。

**Step 4: Write the incident review**

复盘至少包含时间线、直接原因、系统性原因、为什么既有测试/发布验收漏检、哪些保护实际生效、哪些判断当时是错误的、整改项及其自动化证据。

### Task 6: 同步、提交、发布与线上验收

**Files:** all intended files only.

**Step 1: Sync target branch before commit**

```bash
git fetch origin main
git merge --ff-only origin/main
```

若远端有新提交，合并后重新运行 targeted + full suite。

**Step 2: Audit changes**

```bash
git status --short --branch --untracked-files=all
git diff --check
git diff --stat
git diff
```

确认不含主工作区用户文件与无关生成物。

**Step 3: Create the single release commit**

```bash
git add <intended files>
git commit -m "fix: 修复影子评测运行时采集"
```

**Step 4: Push and publish**

- fast-forward 推送目标分支/`main`，不覆盖远端新提交。
- 等待 GitHub Pages workflow 成功。

**Step 5: Verify live output**

- local SHA = remote main SHA；
- Raw 与 Pages JSON/JS 一致；
- 最新正式日报显示 collection health，不再显示 NumPy unavailable；
- 桌面与 390px 移动端无溢出；
- 首个正式 batch 完成 staged/finalized；
- 后续在首个 T+1、T+3 到期日继续验证 maturity 自动推进。

本仓库按用户偏好保留一个最终远端提交；各 RED/GREEN 证据记录在执行日志和复盘文档中，不制造多个远端中间提交。
