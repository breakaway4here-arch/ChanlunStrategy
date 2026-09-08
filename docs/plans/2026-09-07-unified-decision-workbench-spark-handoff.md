# GPT-5.3-Codex-Spark 实施交接

主 spec：`docs/plans/2026-09-07-unified-decision-workbench-spec.md`。

2026-09-08 执行状态：用户在 Spark 额度不足后已要求主任务直接接手。修复与本地验收见 `2026-09-08-unified-decision-workbench-acceptance.md`；以下保留最初交接约束，不再派发 Spark。

用户已要求完整 spec 后由 **GPT-5.3-Codex-Spark** 实施，并明确选择新建 Spark 任务。用户 token 紧张：读取这两份文档即可接管；不要复读旧会话，不要扩展成算法研究，不得静默换其他模型或新开多模型代理。

## A. 起点、授权与原目录保护

- 项目源目录：`/Users/yangfan/yf_source/ChanlunStrategy`。
- 本次两份文档新建在源目录，可能尚未提交，因此自动创建的 worktree 未必包含。可只读绝对路径，再把这两个新文件复制进本任务 worktree；不能复制其他 dirty 文件。
- 已核验源仓库 `.git/info/exclude` 有 `*.md`，因此这两份真实存在的文档不会出现在普通 git status 中。提交时仅对这两份明确授权文档使用精确路径 `git add -f`；不要修改全局排除规则或强制添加其他文件。
- 已知本地 UI 提交：`f649af62aad39732cd9ff3f5d2e94f045d9c44d8`，标题 `feat: 落地图表中心决策工作台`。
- 交接时本地 main 是 f649af6，缓存的 origin/main 是 `4015041`（9/7 日报）；二者 1/9 分叉。它们会变化，实施前重新 fetch，不能把缓存当最新远端。
- 不得在原目录 stash、reset、clean、覆盖、提交无关改动；忽略 `.codegraph/`、`.idea/`。
- 使用 Codex 新任务的独立 worktree；分支前缀 `codex/`。从最新 origin/main 起步，将 f649af6 尚未包含的增量迁入；不要把整个旧 main 合并覆盖过来。冲突保留最新历史归档修复和本 spec 要求，解决后重跑相关测试。
- 实施方案已交付，用户要求代码落地；正常实现、测试、隔离分支及可审提交无需重新询问方向。上线是目标，必须先准备具体提交、预览、受保护差异与回滚方式，再按已有授权和项目发布边界推进；尚未上线必须明确报告。
- 不发送真实测试微信/企微通知，不读出令牌/地址，不修改持仓/正式行情库/推荐账本。真实渠道实收不能用 mock 或服务端 success 冒充。

## B. 小步骤执行计划

### Task 1：整合已有图表基线

1. 记录本任务 worktree 状态、源目录 dirty 路径及相关内容指纹，核实 spec 两文件。
2. fetch origin/main，检查 f649af6 是否已在远端祖先内；仅迁入尚缺的功能增量。
3. 检查 `buildDecisionMarketSummary`、`buildCandidateRowSummary`、`renderDecisionWorkbenchBrief`、`buildMergedCandidateDetail` 及其测试均保留。
4. 运行图表中心、推荐证据前端及资产相关回归；失败先分清基线问题与迁移引入的问题。

### Task 2：先修理由语义与观察身份

文件：`chanlun/recommendation_evidence.py`、`chanlun/report_view_model.py` 及现有 evidence 测试。

1. 增加行为回归：结构理由与观察原因不同不冲突；同语义数值矛盾仍冲突；研究身份不要求正式合同。
2. 先确认回归能暴露原问题，再实现最小修复。
3. 保留 raw decision_engine_v1 和各源分数，不以删数据解决页面身份问题。

### Task 3：实现纯展示投影

文件：新增 `chanlun/decision_workbench.py`、`tests/test_decision_workbench.py`；接入 report view model / generator。

1. 覆盖 spec AC-01 至 AC-12、AC-18：去重、策略独立、状态优先级、空选原因、分数、差异。
2. 实现 build_decision_workbench，确保输入不可变、输出稳定、不调用行情或 LLM。
3. Bootstrap 添加 `decisionWorkbench`；旧 workspace 原视图保留。
4. 当前来源无法提供的条件明确缺失，不扩展成行情补采任务。

### Task 4：落地统一清单和图表详情

文件：`chanlun/report_assets/report-v2.js`、`report-v2.css`；相关前端合同/响应式测试。

1. 复用 Task 1 的图表代码，新增今日结论、去重清单、状态筛选、具体风险/等待摘要。
2. 将预跑封存/无变化内容收起；大盘摘要保持紧凑、可见。
3. 行、详情、通知统一使用投影身份，四项解释对应真实证据。
4. 验证搜索、空选、过滤空态、切股、键盘和手机详情；保留完整候选和研究来源。

### Task 5：推送共用摘要与生命周期

文件：`chanlun/preclose_notify.py`、`scripts/preclose_reconcile.py`，必要时有限修改 preclose_compare/contract。

1. 增加 pending→formal、重试、渠道部分失败、真纠错、旧 outbox、15:35 截止测试。
2. 通知消费同一展示摘要规则；预跑仅使用本阶段已存在输入，不调用盘后流水线。
3. 抑制普通 pending 通知；实现稳定语义去重并兼容既有成功记录。
4. 使用 mock/fake sender 验收，不发送真实消息。

### Task 6：staging、历史兼容和真实预览

文件：report generator、`scripts/stage_recommendation_evidence_pages.py`、必要的精确校验白名单、docs/assets/入口。

1. 用 9/7 与一个相邻有效日期的已存报告创建隔离 staging；数据只读。
2. 精确允许派生投影变化，比较原业务载荷及行情/账本 hash 不变。
3. 同步源与发布资产、HTML query version；不批量覆盖原目录 dirty docs。
4. 在 1440×900、1366×768、390×844 浏览器走查完整/条件不足/陈旧异常/无 K 线四状态，保存截图和简短结果。

### Task 7：回归、可审提交与发布交付

1. 定向回归通过后跑一次完整现有回归。新增失败只针对根因补测，避免重复扫仓库。
2. 提交前再次 fetch origin/main，将改动建立在最新目标上，重跑受影响回归；确认最新目标是提交祖先后才提交/推送/创建 PR。
3. 提交标题为 `fix: ...` 或 `feat: ...`，不使用 scope/emoji；无 Redmine 工单号可省略。
4. 形成具体变更、截图、测试结果、业务不变证据和回滚提交。按用户与项目授权推进发布，绝不 force push。
5. 发布后检查实际 HTML/JS/CSS hash、日期/快照和三视口；通知实收单独验收。没有发布或实收证据时分别标注未完成。

## C. 已核实可用的测试与工具入口

先选择项目实际使用且支持 Python 3.9+ 的解释器；不要默认机器 `python3` 的版本。以下用 `/usr/bin/python3` 表示已安装的 3.9，若项目依赖在专属虚拟环境中则改用该解释器并报告。

```sh
/usr/bin/python3 -m unittest tests.test_chart_centered_decision_workbench tests.test_recommendation_evidence tests.test_report_view_model tests.test_report_generator
/usr/bin/python3 -m unittest tests.test_preclose_notify tests.test_preclose_compare tests.test_preclose_e2e tests.test_preclose_formal_isolation
/usr/bin/python3 -m unittest tests.test_stage_recommendation_evidence_pages tests.test_recommendation_evidence_contract_guards
node --check chanlun/report_assets/report-v2.js
npm --prefix cloudflare/top10-worker test
/usr/bin/python3 -m unittest
git diff --check
```

新增模块建立后补跑 `tests.test_decision_workbench`。若改 preclose Worker，另跑该目录已有测试，不为无关模块扩展测试范围。

`scripts/stage_recommendation_evidence_pages.py` 已有参数 `--repo-root --docs-dir --report-date --stage-root --source-assets-dir --protected-path`；先读 help/合同，用 worktree 内 fixture/staging，不把受保护原目录当输出。

`scripts/stage_report_asset_version_updates.py` 会涉及 Git staging，调用前先读参数与允许路径。`scripts/validate_today_report.py` 日期是位置参数；它是发布/事实验收，不是允许重跑 daily_run.sh 的授权。

禁止为刷新预览直接运行 `daily_run.sh`、生产 `run.py`、真实通知发送或全历史修复。不要打印原始 launchctl 环境；只能读脱敏的路径、参数、状态、退出码。

## D. 节省 token 的交付方式

- 按 Task 1–7 顺序连续执行，必要时更新本任务内简短进度；避免重述整份 spec。
- 用 rg 先定位源文件；不要全文输出生成 HTML/JSON，也不要扫描 `/` 或 `/share`。
- 不重读旧 memory 全文，本文已保留所需项目边界；发现具体冲突再查对应文档。
- 最终列出每个里程碑完成/未完成、测试、预览和线上证据。不得以任务启动代替代码完成。
- Spark 不可用或额度不足时报告准确阻塞，不自动升级模型、不赎回额度重置。
