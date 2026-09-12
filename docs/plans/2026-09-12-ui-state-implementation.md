# 2026-09-12 UI 状态实现记录（U01/U02/U03）

## 范围与约束

- 工作树：`codex/ui-final-state-20260912`，实现前基于 `origin/main` `31249b6b`。
- 本批只改 `chanlun/report_assets/report-v2.js` 与对应行为测试；不改候选资格、正式动作、分数、排序、价格、风险条件、图表算法、生产数据或通知。
- 影响边界：B03、B04、B06、B08、B09、B10；状态展示属于 A 类同源逻辑收敛。
- 实现配置按主进程授权记录：GPT-5.6 Sol / xhigh，Fast 关闭，`service_tier=default`。

## U01：候选、选中与详情生命周期

- 根因：`renderCandidateList` 只在可见项变化时调用详情渲染。搜索无结果时没有释放现有图表实例；清空搜索后 active 仍在候选集合内，因而跳过详情挂载，导致列表恢复而详情为空。视图、板块、手机抽屉与桌面恢复还分别维护挂载边界。
- 实现：增加当前快照/视图/股票的详情 key；候选选择统一经过 `getCandidateSelection` 和 `beginCandidateSelection`；空集合清理图表与详情挂载；有效 active 但详情缺失时自动重挂载；抽屉关闭与桌面恢复复用同一清理路径。选择版本在详情渲染前校验，旧股票/旧快照不能继续提交当前图表渲染。
- 第 1 轮：新增行为测试并实现最小修复。
- 第 2 轮：自审并修正初始加载、视图切换、抽屉关闭、worktree 包装行和旧详情 target 合同；保留显式 target 入口。
- 验证：`test_u01_search_empty_releases_chart_and_clear_remounts_valid_selection`、`test_u01_old_selection_token_cannot_win_after_new_snapshot`；旧实现均按预期失败，修复后通过。
- 未解项：本批未改 `renderChart` 内部算法；浏览器三视口修复后验收由主进程复跑。

## U02：统一候选比较

- 根因：比较直接按 `recommendationEvidence.views[viewKey]` 取证据；`decision_all` 是统一 workbench 视图而不是旧 evidence view key，导致 25 只统一候选显示“本期未选出推荐票”，并且潜在只覆盖前 20 个 DOM 行。
- 实现：比较与列表共用完整逻辑候选选择器（搜索、板块和当前状态作用于全集合，`visibleItems` 只用于列表分页）；统一实体从 `strategy_results` 读取来源证据。比较行按来源策略展示动作、周期、价格合同、分数和证据状态；缺证据的实体保留在比较结果中，不转换为空股票。
- 第 1 轮：补充 `decision_all` 全集合、研究对象缺证据和同股多来源行为测试并实现。
- 第 2 轮：自审并修正无 workbench 的旧 evidence 快照回退、来源证据状态聚合和旧比较边界文案。
- 第 3 轮：移除移动端票据中 selected evidence 的“唯一正式动作”行；旧 evidence 回退仅在缺少 workspace 能力时启用，并复用搜索/板块过滤；分页改由行为测试验证完整集合与可见页。
- 第 4 轮：搜索、加载更多、板块切换/清除统一经过 workspace 刷新入口，比较挂载与列表在每次现有事件处理后同步更新；新增真实事件路径回归。
- 验证：`test_u02_decision_all_comparison_uses_all_entities_and_each_source_contract`；前端比较及工作台相关回归包含在下述 234 项中。
- 未解项：两三只手动比较（U13）不在本批；未新增跨策略合并动作。

## U03：身份、条件、证据与风险语义

- 根因：`decision_wait` 通过通用 `page_status` 把研究 `waiting_trigger` 与正式待确认混在一起；状态展示没有把身份、结构化条件、证据质量和风险标签拆开，理由中的“等待”不能作为策略判断依据。
- 实现：正式结果/正式待确认按真实 formal `strategy_results` 或正式合同识别；研究等待仅由结构化 `page_status` 保留为研究待条件，纯文本理由不会升级状态。列表、统一详情和比较均展示身份、条件、证据、风险四个维度；未知、未声明和未核验保持显式，不渲染成已满足或无风险。比较边界说明标签可重叠、股票按当前集合去重。
- 第 1 轮：补充正式/研究混合状态与未知证据行为测试并实现。
- 第 2 轮：自审并修正 workbench 包装实体的字段读取、研究实体不能因 `evidence_blocked` 通用状态升格、旧正式视图身份回退。
- 验证：`test_u03_formal_pending_excludes_research_waiting_reason_and_unknown_is_not_satisfied`；统一工作台和前端回归通过。
- 未解项：没有改变后端 workbench 的正式状态生产逻辑；只消费现有结构化字段。

## 运行记录

- RED：`/usr/bin/python3 -m unittest tests.test_ui_final_state`，旧实现 4 项失败，分别覆盖详情不重挂载、图表不释放、统一比较空白、研究等待混入正式待确认。
- GREEN：同命令 4/4 通过。
- 相关回归：`/usr/bin/python3 -m unittest tests.test_auxiliary_frontend tests.test_unified_workbench_frontend tests.test_chart_centered_decision_workbench`，160/160 通过；叠加新增测试为 164/164。
- 扩展前端回归：`/usr/bin/python3 -m unittest tests.test_auxiliary_frontend tests.test_coverage_summary_frontend tests.test_preclose_frontend tests.test_psy12_shadow_frontend tests.test_recommendation_evidence_frontend tests.test_recommendation_historical_validation_frontend tests.test_recommendation_main_rise_frontend tests.test_recommendation_volume_sector_frontend tests.test_report_comparison_frontend tests.test_unified_workbench_frontend tests.test_chart_centered_decision_workbench tests.test_candidate_basic_info tests.test_recommendation_chart_evidence`，234/234 通过。
- 第 3 轮目标回归：`/usr/bin/python3 -m unittest tests.test_ui_final_state tests.test_auxiliary_frontend`，138/138 通过；新增覆盖 25 项分页计数、旧载荷过滤回退与显式空 workspace 不回退。
- 第 4 轮目标回归：扩展前端回归 241/241 通过；新增覆盖搜索有结果→无匹配→清空、板块切换/清除后的比较内容同步。
- 静态检查：`node --check chanlun/report_assets/report-v2.js`、`git diff --check` 通过。
- 未启动 HTTP 服务、生产入口或常驻进程；未写正式数据/账本/通知。
