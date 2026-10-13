# 2026-10-13 三项审查问题收口与上线

**Goal:** 核实个人观察股是否真实推荐；让当日报告公开文件以最新有效数据一致交付；失败预跑不再被比较为一致。

**Architecture:** 复用当前正式报告校验、发布锁、受控暂存/原子提升，以及现有预跑合同。最新有效当日独立 JSON 是派生报告的事实基线；不可验证的新数据不靠 mtime 或旧页面冒充最新。预跑只对正常 available/empty 比较，失败/超时/未运行保留不可比身份。代码、运行目录、Worker、Pages 和自然运行分别验收。

**Tech Stack:** Python 3.9、SQLite、zsh、静态 JavaScript、Cloudflare Worker TypeScript、GitHub Pages。

## 本轮授权与配置

- 用户明确要求三项一起处理，修复目标上线；第一项以“确定 verified 是否推荐，没推荐就没事”为范围限制。若确认未推荐，保持观察及正式策略行为，只交核查证据。
- 主进程保持当前配置；用户确认代码子代理继承当前聊天模型/推理配置。工具未暴露精确型号/推理档位，不推测名称，不沿用审查阶段代理配置。
- 实施树：`/Users/yangfan/.codex/worktrees/review-closures-20261013/ChanlunStrategy`，分支 `codex/review-closures-20261013`，基线 `b5e94fa4c18fd00d8dcd4da0cc6b55cb8c8d0003`，建立时与实时远端 main、干净 production-runtime 相同。
- 根脏树保留。已读根及实施树 AGENTS.md，实施树规则 SHA256 `9ad2a840d884c5e74729dcf116ddd3f2876d25cbfbb715269bc5acd26e58d1b0`；已读选股修复总方案第 12—14 节、2026-10-08 worker handoff、2026-10-12 时钟修复与预跑运行手册。
- 允许本批源码/派生资源修复、测试、提交、合并及上线；不重跑正式选股、不扩量补数、不改变策略阈值/正式排序，不另行发送业务通知。历史失败快照不重造，旧错误对账可在公开读取时根据同身份源快照安全投影为不可比。

## Task 1：核实个人观察股是否推荐（只读）

- 核对最新正式报告里本次追加观察股与正式推荐/主推、H4、加速及账本的交集；区分纯候选、观察、研究和真实 recommend。
- 检查可用历史报告的相同路径，限定结论日期范围；不以 verified 当成 recommend。
- 若没有真实推荐证据，仅记录结论，不修改选股入口。若发现真实推荐，先向主进程提供日期、代码、身份、final/价基和原始证据，按用户范围决定最小阻断修复并做固定输入行为对照。

## Task 2：最新有效数据统一报告文件

- 相关文件：`daily_run.sh`、`scripts/repair_strategy_scorecard_snapshot.py`、`scripts/enable_shadow_evaluation_snapshot.py`、`scripts/validate_today_report.py`、`chanlun/report_generator.py` 及直接相关测试；按最短链实际选取，不要求全改。
- 先用同日新 daily/旧 aggregate+inline+archive、坏/缺聚合及中途故障反例证明旧路径失败。以最新有效当日 JSON 重建对应派生内容，来源不明/日期错误/生成时间倒退等冲突不得静默覆盖。
- 保留合法附加字段、页面外壳、历史记录、清单顺序、策略身份和原价用途；复用受控暂存/原子提升与来源保护，失败不提交半套文件。
- 生成或恢复后核验四个公开面同一份有效报告；就绪与重试不能仅凭当日 mtime，损坏派生文件应从有效源恢复或明确安全失败。
- 验收：正常一致、同日部分更新、截断/缺文件、源 JSON 不合法、不同日期、既有用户改动拒绝、原子提升中断/恢复及锁保护；不启动本地/生产服务。

## Task 3：失败预跑对账不可比

- 相关文件：`chanlun/preclose_compare.py`、`chanlun/preclose_notify.py`、`scripts/preclose_reconcile.py`、`cloudflare/preclose-worker/src/index.ts`、`chanlun/report_assets/report-v2.js` 及对应测试。
- 新状态例如 `preclose_unavailable`，只在真实失败/超时/未运行或缺明确正常身份时使用；正式报告待就绪仍保留 formal_pending。不可比时不推断新增、移除或一致，不丢正式结果阅读能力。
- 贯通 Python 内容 hash、Worker 输入校验/公开白名单、前端和通知；同 snapshot_id/date/hash 旧对账读取可安全纠正，不能跨快照借状态或改写旧审计事实。
- 先复现真实 10/08、10/09 failed+三池空→unchanged；修复后为不可比。保留 empty+正式空→unchanged、正常 changed/unchanged、缺状态、过期 available/failed、错日期/hash、重试幂等和隐私脱敏负例。
- Node 纯 Worker 合同/构建验证；不启动 Miniflare、监听端口或常驻服务。

## 主进程验收与发布

- 逐项检查实际差异，独立复现关键反例；运行相关组合及适当完整回归。审查阶段全仓已有 4 项旧夹具/断言问题，按范围说明，不把旧失败隐藏，也不扩大成无关重构。
- 提交前 fetch 最新 main，必要时只在隔离树整合，重新回归并确认目标祖先；提交标题使用 `fix: ...`，只暂存本批文件。
- 完成规格及代码质量审查后推送/建 PR/合并。用户已授权上线，不逐步骤重复请求许可。
- 发布前记录源码/运行树/公开资源和业务文件指纹，确认自然任务未运行，持共享发布锁快进实际运行树，保留任何新增报告/脏改动。只部署本批 Worker 与静态资源，不运行正式业务入口。
- Worker 和 Pages 成功后实际 HTTP/浏览器回读本次状态及源/资源版本。没有观察到自然运行或真实用户收信时明确待验收，不能用部署代替。
- 只清理本任务资源；所有测试/构建子进程结束后复查，不停止现有任务。

## B01—B10 影响

B01/B02/B03/B04/B05/B07 保留原数据、价基、资格、身份、时效与排序；第一项仅核查。B06 修复状态及公开事实一致性；B08 保留盘中/盘后合法差异、失败不可比；B09 保持正式/预跑、来源、锁与通知幂等隔离；B10 记录固定输入、红绿反例、旧失败和实际发布证据。

## 执行与证据（追加）

本段创建时尚未修改产品、提交、合并或部署。后续按真实结果追加。

### Task 1 核查结果

只读核查全部 93 份日报（2026-05-23—10-12），其中 30 份保留追加来源、共 110 个股票日期；追加股与正式融合、H4、加速及正式视图交集为 0。正式账本 1966 行、28 个日期内，五只目标股票只有 7 条基础候选/观察/研究记录，全部 `observe / watch / cohort_eligible=false`，没有 recommend；10/12 五只在原始池、工作台与当日账本均未入选，个人状态为 awaiting_confirmation。

主进程已检查审计脚本并独立复跑，证据为 `/private/tmp/chanlun-closures-20261013/watchlist-recommendation-audit.json`，脚本同目录 `audit_watchlist_recommendations.py`。17 份可解析实际 HTML 中唯一相关工作台项为 9/16 的 002281，身份 watch_only、formal_action 为空。早期 63 份日报没有追加元数据，4 个旧 HTML 无 bootstrap，原始日线 final 状态未持久化；结论是可核查范围没有实际错荐，不是证明入口永远安全。按用户“没推荐就没事”要求，本轮不修改个人观察和正式选股行为。

### 修复与独立验收

- Task 2 保留正式源 JSON 的事实及合法历史/补充字段，按有效生成时间重建轻量聚合、首页及归档两套 bootstrap。缺失/截断页面可用另一同日可信外壳恢复；聚合历史损坏或没有可信外壳时明确停止。不能以 mtime、较新派生页或相同日期掩盖来源冲突。22 项新增测试，194 项相关回归通过。
- Task 3 使用 `preclose_unavailable`；正常 available/empty 仍按原合同比较，过期状态使用原 result_status。不可比不产生增删/一致推断，正式结果独立保留。Python、通知、前端、Worker PUT/GET 和内容 hash 同步；旧对账公开投影只接受同快照身份，原存储/修订号不改。174 项相关 Python 回归及17项纯 Node合同通过。
- 主进程独立验证71项预跑测试、17项Worker合同；真实10/12同批回放保持16:12:38，混批回放从daily16:20/其余16:12:38统一为16:20，均通过四面校验且正式事实不变。规格独立48项通过，质量独立68项及共享原子发布38项通过。相关证据位于 `/private/tmp/chanlun-closures-20261013/`。
- 完整回归 `parent-full.log`：3143 passed / 4 failed / 1 skipped，退出1。四项均与基线同输入一致：`test_regression_no_adaptive_filter` 扫到旧测试夹具用词；`test_repair_auxiliary_decision_snapshot` 旧夹具缺现有 selection-performance 资源；`test_ui_availability_release` 期待旧按钮文案；`test_ui_final_layout` 只检查最后一段移动CSS。未删除或弱化这些断言，本批无新增失败。
- 质量审查保留既有 P2 限制：不遵守发布锁的外部编辑若恰在准备完成后、replace之前发生，仍可能被覆盖；基线同输入已复现。正常协作发布锁及暂存时hash保护通过，没有线上事故证据。本批不扩大成公共事务重构；所有部署持锁且运行目录必须干净。
- 发布包装仅同步 `report-v2.js` 源/资源及18个HTML资源查询串，版本 `b50b191edb37`；118份docs JSON字节不变。Worker dry-run构建通过，无绑定/迁移变更，未启动服务。
- 提交前已同步远端main，仍为基线 `b5e94fa4c18fd00d8dcd4da0cc6b55cb8c8d0003`，是本分支祖先。合并、Worker/Pages/运行树回执待实际发布后单独记录；自然14:45/15:05运行与真实通知尚未验收。

### 主进程复验发现与第二轮收口

主进程直接对当前运行目录10/12报告执行新增校验，发现正常同代页面的独立分钟证据无法从daily JSON重建；首版无条件重建会丢失5行有效分钟事实。该实际回归阻断了首版发布，前述规格/质量通过只代表首版已覆盖场景，不能替代此次补验。按项目保留有效能力规则完成最小修正：同代、同事实来源的证据先核对股票/ref/视图排名并重放原工作台，再按当前合法workspace投影；跨代数据不能捐赠独立证据。

10/12的highlights=0有明确 `output_hidden=true` 和8只共同上游不匹配的封闭记录，原HTML残留10行不属于应保留的有效视图。修正后其他视图证据逐字段保持（5行分钟available、其余合法missing继续可用），highlights仍为0；工作台重建并绑定来源、workspace和证据摘要。错日期/代码/pool/ref/rank、两页冲突及已绑定内容篡改均拒绝；暂存结果与选定的预期完整payload比较后才提升。

第二轮31项专测通过，独立增量36项通过；主进程再次执行全仓结果为 **3152 passed / 4 failed / 1 skipped**，退出1，仍仅上述4项基线旧问题，日志 `parent-full-final.log`。主进程真实同代及混批回放再次通过，保护事实不变。运行目录173个受保护文件及根工作区原脏改动保持原状。

当前10/12首页与归档的纯派生校正已离线生成并独立检查：只替换bootstrap的recommendationEvidence、decisionWorkbench及reportPublication，原inlineReportData和其他HTML字节保持（本批资源查询串另行同步），全部118份JSON不变。仅这两页允许追加本段所述派生校正，其余16个HTML继续只修改资源查询串；这替代前一阶段“18页均只改查询串”的发布包装描述。

最后直接消费者检查补上独立开盘啦更新的兼容：其既有白名单仅修改四面的kaipanla_context及独立卡片，证据/工作台不消费该字段。因此只在证据receipt来源摘要排除该独立补充，四面完整一致性仍检查它。真实“带receipt页面→补更→校验→单面回旧拒绝→恢复→再次修复”通过，未修改补更入口或放宽报告事实检查。最终修复器SHA256为 `55a78df215473a71e4049e4e3029588ccf80382bd5b37af74268d5b9c76724f5`；主进程最终9模块 **162 passed**，独立最终2例通过，退出均0。33项最新日报专测使用稳定的10/12公开分钟证据夹具，不依赖滚动首页；4项全仓旧失败保持单列。

最终待发布两页校正已在实施树通过alignment，全部未关闭视图证据逐字段保持、inline JSON原样、118份JSON不变。当前发布包可独立回滚源码及派生页面，不回退之后新增报告、库或账本。后续实际PR、Worker版本、Pages构建、运行树和浏览器回读记入本任务发布回执与PR说明；截至本段写入尚未把待发布称为已上线。
