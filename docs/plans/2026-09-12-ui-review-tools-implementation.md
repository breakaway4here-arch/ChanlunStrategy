# UI Review Tools 实施记录（U11/U13/U15）

- 工作树：`.worktrees/ui-final-review-tools-20260912`
- 分支基线：`codex/ui-final-review-tools-20260912`，起点 `2bc07358`
- 执行模型：GPT-5.6 Sol / xhigh；Fast 关闭；`service_tier=default`
- 范围：`report-v2.js` 的变化复盘、轻量比较、历史验证入口及必要展示 CSS；没有修改选股资格、正式动作、分数、排序、价格合同、策略数据或通知边界。

## U11 变化复盘

- 轮次：1/5。
- 根因：已有 `decisionWorkbench.changes` 只有概览计数，页面没有把 `added/removed/changed`、上一有效快照身份和逐股不可比原因展示出来，无法下钻真实记录；不可用跨期比较也缺少“不能确认跨期是否变化”的边界。
- 实现：新增 `renderDecisionChangesPanel`。复用当前投影中的变化数组、上一报告日期/阶段、snapshot/version 和 `value_unavailable_reasons`，以成员、来源策略、日期/阶段、字段原因呈现；移出文案明确“不等于破位”，不把可读到的最早记录称为首次出现，也不扫描全历史。条目保留 `data-change-*` 下钻入口。用户打开“查看已有快照”后，才按 `previous_report_date` 读取现有 `data/<date>.json`，并分别呈现当前与上一有效快照的来源策略、阶段、版本、动作、条件、价位、证据和风险；读取失败/缺失明确显示历史缺口。
- 测试：`test_u11_changes_panel_drills_real_changes_and_keeps_comparison_identity`、`test_u11_unavailable_history_does_not_claim_no_change`、`test_u11_selected_stock_history_keeps_current_and_previous_source_contracts`、`test_u11_history_button_reads_previous_snapshot_only_when_opened`；先以缺少 `renderDecisionChangesPanel` 的 ReferenceError 红灯，再通过。
- 未解项：完整时间线依赖用户打开后的已有当前/上期快照材料，本批不新增历史引擎、不补历史数据；只有当前/上期时明确保留历史缺口。

## U13 轻量比较

- 轮次：1/5。
- 根因：已有完整比较表适合证据审阅，但没有独立的最多三只选择状态，筛选后也没有保存已选对象并标识其已离开当前集合的能力。
- 实现：新增独立选择区和 `renderQuickComparison`/`toggleQuickComparisonSelection`。选择状态按快照、视图、股票代码保存；第四只不会静默替换，独立控件可移除；六维按每个来源策略分别保留动作、周期、价格合同、分数/证据，突出差异并弱化相同项，不计算跨策略总分/胜率。来源策略 ID 映射为用户名称，缺周期只显示一次“周期未声明”。
- 测试：`test_u13_quick_comparison_caps_three_preserves_sources_and_keeps_filtered_selection`；覆盖三只上限、第四只提示、来源合同保留、过滤后“不在当前集合”及移除控件。
- 未解项：挂载点由布局批次提供，当前渲染函数在挂载点缺失时安全空操作。

## U15 历史验证连接

- 轮次：1/5。
- 根因：详情中已有 `historical_validation` 渲染，但没有把历史验证、榜单表现和模拟跟踪的语义边界集中提示；样本进度与成熟门槛需要继续沿用已有数据合同。
- 实现：新增 `renderHistoricalValidationLink` 并接入统一/旧版详情；历史验证增加已有记录、样本身份/范围（若上游声明）、成熟/未成熟/缺失进度及边界说明。指标仍只在 `ready_for_manual_comparison` 门槛满足时展示；不生成新回测、不把榜单涨跌写成成交收益、不把个股最差不利波动写成组合回撤。
- 测试：`test_u15_history_link_names_existing_validation_performance_and_simulation_boundaries`；覆盖历史入口、成熟样本进度、缺失跟踪和未达门槛不显示均值/上涨率。
- 未解项：真实榜单/模拟数据由既有数据合同提供，当前没有补历史样本或重跑策略。

## 共用验证

- 先失败：`/usr/bin/python3 -m unittest tests.test_ui_review_tools`，4 项红灯（3 个接口缺失，1 个测试 fixture 声明冲突已修正）。
- 第 2 轮红灯：新增 nested previous identity、错误日期/阶段/价基、重复 source/code 和 legacy 合同测试后，接口/兼容行为先失败；修正后新测试 10 项通过。
- 第 2 轮修正：previous identity 统一从顶层或 `previous_snapshot` 解析；按现有 `date`、显式 phase 或正式收盘事实核验 JSON；缺版本/snapshot/价基保留来源事实并标未核验，冲突不作为上一快照或价格可比证据；重复 source/code 按声明身份选择。legacy candidate 复用已有 action/page_action/formal_decision_contract/score/price/horizon/basis，不推算新字段。
- 无障碍定向修正：比较选择改为 `fieldset`，相同项去除整块 opacity，辅助文字使用可读色值。
- 第 3 轮 U11/U15：变化分组计数改为可操作按钮，定位已有名单分组；历史验证入口展开现有 module 08，榜单表现连接既有 compare 路径，模拟跟踪连接已有记录或显示历史缺口。主界面只显示中文能力名，内部字段保留在证据审计层；未声明身份继续标未核验，不扩大统计或历史扫描。
- 第 4 轮 U15：历史入口 helper 仅绑定 `historical-validation`/`simulation-tracking` 白名单并尊重 `data-evidence-bound`，价格、日线等其他证据跳转不会误开 module 08。
- 第 4 轮 U11：单条来源也核对行级日期/阶段/报告版本/快照/价基；行级冲突或缺失保留原始来源事实但标记身份未核验、价格和升级不作可比。策略版本与报告版本分开显示。
- 通过：`/usr/bin/python3 -m unittest tests.test_ui_review_tools tests.test_ui_final_state tests.test_auxiliary_frontend tests.test_unified_workbench_frontend tests.test_recommendation_historical_validation_frontend tests.test_report_comparison_frontend tests.test_recommendation_evidence_responsive tests.test_recommendation_evidence_contract_guards tests.test_recommendation_evidence_bounds tests.test_recommendation_evidence_completion tests.test_project_audit_ui_contracts`，266 项通过。
- `node --check chanlun/report_assets/report-v2.js` 通过，`git diff --check` 通过。
- `chanlun/report_assets` 与 `docs/assets` 的 JS/CSS 保持字节一致。
