# H4 T+3 Production Pool Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将冻结 H4 T+3 K30 tail-safe 规则接入每日真实数据链，并增量补算 2026-08-20 的 H4 池。

**Architecture:** 新增独立生产模块读取精简冻结训练集，对当日 `picks_fusion` 计算完全相同的微状态、148 维向量和日期等权 K30 预测。`run.py` 调用该模块，报告层序列化独立 H4 视图；增量脚本复用同一模块，只更新已有当日 JSON/页面。

**Tech Stack:** Python 3、NumPy、现有 unittest、现有静态日报生成器。

---

### Task 1: 冻结精简 H4 训练模型

**Files:**
- Create: `scripts/export_h4_t3_production_model.py`
- Create: `chanlun/data/h4_t3_model_v1.json`
- Test: `tests/test_h4_t3_pool.py`

**Steps:**
1. 先写失败测试，要求模型包含冻结策略版本、148 维向量、唯一日期/代码身份和仅 T+3 训练标签。
2. 运行 `python3 -m unittest tests.test_h4_t3_pool`，确认因模型/模块缺失失败。
3. 实现导出器，从既有冻结开发特征和标签提取延续微状态行，写出精简确定性 JSON。
4. 运行导出器生成模型，并确认产物远小于原 90MB 特征/标签输入。
5. 运行 focused test 变绿。

### Task 2: 实现生产 H4 全量过门池

**Files:**
- Create: `chanlun/h4_t3_pool.py`
- Modify: `tests/test_h4_t3_pool.py`

**Steps:**
1. 先写失败测试覆盖：精确微状态、K30 预测、三个门槛、全部过门候选保留、不回填、技术失败与成功空选区分。
2. 运行 focused test，确认缺失行为导致预期失败。
3. 最小实现冻结向量、日期等权 KNN 和 `build_h4_t3_pool(picks_fusion, trade_date)`。
4. 对同一输入与研究实现做预测/排序对齐测试。
5. 运行 focused test 变绿。

### Task 3: 接入每日运行和报告

**Files:**
- Modify: `run.py`
- Modify: `chanlun/report_generator.py`
- Modify: `chanlun/report_view_model.py`
- Modify: `chanlun/report_assets/report-v2.js`
- Modify: `docs/assets/report-v2.js`
- Modify: `tests/test_report_generator.py`
- Modify: `tests/test_report_view_model.py`
- Modify: `tests/test_h4_production_boundary.py`

**Steps:**
1. 先写失败测试：日报包含已认证 H4 池；H4 全量显示；同一候选保留统一分并可按现有规则进入主推；H4 不额外加分。
2. 运行三个报告测试模块，确认预期失败。
3. 在 `fusion_scored` 生成后构建 H4 池并加入 `report_data`。
4. 恢复 H4 序列化和独立视图；删除旧的“命中 H4 必定仅观察”行为。
5. 运行报告 focused tests 变绿。

### Task 4: 增量补算 2026-08-20

**Files:**
- Create: `scripts/backfill_h4_t3_pool.py`
- Modify: `docs/data/2026-08-20.json`
- Modify: `docs/index.html`
- Modify: `docs/2026-08-20/index.html`（若当前发布结构包含该归档）
- Test: `tests/test_h4_t3_pool.py`

**Steps:**
1. 先写失败测试，确认增量入口只读取既有日报、保持其他池原始数量不变，并重建 H4/工作区。
2. 实现单日期增量入口。
3. 运行 `python3 scripts/backfill_h4_t3_pool.py --date 2026-08-20 --output-dir docs`，不调用全量 `run.py`。
4. 比较补算前后其他池数量和关键摘要，确认仅增加 H4 相关字段/视图。
5. 检查当天 H4 候选、预测值、统一分和主推归属。

### Task 5: 验证、同步并创建 MR

**Files:**
- Verify all changed files only.

**Steps:**
1. 运行 H4、报告生成和视图 focused tests。
2. 运行 `python3 -m py_compile` 检查新增/修改 Python 文件。
3. 重新读取远端 `main`，将最新目标分支合入当前分支。
4. 重跑 focused tests 和 2026-08-20 增量验证。
5. 检查 diff，排除 `.codegraph/`、`.idea/` 和其他无关内容。
6. 按仓库规范提交、推送并创建目标为 `main` 的 MR。
