# 2026-10-12 预跑行情采集时钟修复

## 目标、授权与基线

用户在根因与独立 review 后明确要求“修复”，并确认实现 agent 继承当前聊天模型与推理配置。本次工具未暴露具体模型档位，不猜测型号、推理强度或沿用旧任务配置。实现 agent 落地，主进程独立审核。本批权限是本地隔离修复和验证；没有新的合并 main、部署、生产重跑、补数、写正式库或通知授权。

- 实施树：`/Users/yangfan/.codex/worktrees/preclose-acquisition-clock/ChanlunStrategy`。
- 分支：`codex/preclose-acquisition-clock`；起点：`origin/main` 的 `2f48d2984892e655adcf7479072854fdd96f1d0b`，实施前 clean。
- 已读根目录 `AGENTS.md`（SHA256 `3dccacd0290ef3c49c0ea8921a31240d8a3e86c1aa785ab202c9f7f4b74785a4`）及实施树规则（SHA256 `9ad2a840d884c5e74729dcf116ddd3f2876d25cbfbb715269bc5acd26e58d1b0`），无其他 `AGENTS.override`。
- 已读选股修复方案第 12—14 节、`2026-09-29-full-market-quote-fallback.md`、`2026-10-08-worker-handoff-repair.md` A 批。历史发布权限和模型配置不作为本批授权。
- 根旧树及 production-runtime 的既有脏改动保持原样；本批未触碰运行树、调度或真实缓存。

## 根因与最小修改

预跑把启动时刻同时作为行情校验的 now 和最终输入 as_of，`fetch_quotes` 内部又冻结这个时刻。全市场请求持续数分钟时，新鲜报价会比该时刻晚 60 秒以上，因而被既有未来数据门拒绝。仅在 caller 再读一次当前时间无法修复请求期间冻结的问题。即便仅改行情校验，日线拼接里的风险二次门仍会按旧 as_of 拒绝新报价，最终快照也会错误标注事实时间。

本次沿原调用链修改五个产品文件：

1. `quote_sources.py`、`data_fetcher.py` 区分显式固定 now 与可注入动态 clock，二者互斥。动态采集每次响应后读取时钟；历史固定 now 不读取宿主当前时间。预算仍使用单调时钟和 caller 剩余预算，不把分钟/风险历史 as_of 当墙钟。
2. 行情采集结束时重新检查每条早期有效报价。旧日、过期、真实未来、错误身份/来源/单位和原数量门保留。最终事实时间采用合同的秒精度，晚于该时刻的报价拒绝，即使落在解析层原有 60 秒时钟偏差容忍内，也不成为未来事实。缺失报价保留在全集分母中，价格字段不补零。
3. `preclose_runtime.py` 将实际报价事实 as_of 传给日线拼接、风险校验和分钟截断；`preclose_run.py` 用返回的 input.as_of 构建 pipeline/config/snapshot。独立 `run_started_at` 继续用于 run_id、预算和审计。生成时间回拨到事实时刻之前则失败关闭，不把 generated_at 伪造到未来。
4. `preclose_data.py` 在 input 临时文件原子提升前再次检查写入期限，并清理未提升临时文件；行情缓存也在提升前核对预算。caller 采集预算或 14:56 截止用尽时不再发备用请求、不冻结输入或结果、不发布/通知。
5. 已知输入错误保留结构化原因、行情计数、有限来源尝试和最多 8 层位置摘要到本地 0600 的 `acquisition-failure.json`；行情缓存保留采集诊断。没有复制原始异常文本、局部变量或完整文件路径。附加诊断写失败为 best-effort，原 failed 快照收口继续，结果记录安全错误类型。公开 snapshot 仍仅使用既有安全 failure stage/type，不加入本地诊断详情。

内部补源预算保持原来的 180 秒，从首源开始计时，没有重置或扩大到 660 秒。205 秒后返回的首源报价可按实际时钟正常核验，但不在其后开启新备用请求；这保留有界请求行为。首源网络调用本身仍受 scheduled 的总采集闹钟约束，本批不重做东财分页框架。

## 集合与保护边界

- B01/B03：恢复被启动时刻误拒的合法报价；请求全集、有效报价、缺报价和日线覆盖的分母保持原语义。早期报价在后续慢请求中真正老化则重新拒绝。
- B06/B08：事实 as_of 与真实采集/风险/分钟/最终快照一致；固定历史回放可复现，共享正式收盘入口保留旧日和盘中 non-final 拒绝。
- B09/B10：测试全程阻断网络，SQLite 仅允许临时目录，cache 亦隔离。新旧对照、红绿反例和运行/发布边界分别记录。
- B02 不变：原价、复权换算、成交量和金额单位保护不变。
- B04/B05/B07 不变：没有改正式身份、十日时效、选股阈值、评分/排序、价格用途或研究转正式规则。

本次替代“启动时间兼作采集校验和事实截止”的实现，不替代 14:45—14:56 合同、180 秒补源预算或历史资料时点。允许个别真实旧/未来/迟到报价缺失，不将全市场有效报价为零包装为正常空池。

## TDD 与固定输入证据

新增 `tests/test_preclose_acquisition_clock.py` 共 16 项测试。关键组合保留真实 scheduled → builder → fetch_full_market_quotes → fetch_quotes → fetch_all_a_stocks → 行情清洗/日线拼接/风险校验链；仅外部行情响应、历史输入、非本批分钟/指数 I/O 和最终策略输出使用合成夹具。最终 snapshot 通过真实冻结路径写入临时目录。既有真实 pipeline 模块另做完整相关回归，没有用 fake pipeline 声称收益或正式选股验收。

- 原 SHA 的 64 项基线回归通过；初始 5 项新测试在原四模块内存重放得到 7 个预期失败：30 秒事实截止旧、61/205 秒新报价误拒、慢备用响应误拒、真实未来及过旧报价误放行、跨 14:56 后仍请求备用源。原代码从 Git 读取到独立测试进程，未回写实施树。
- 最终 30/61/205 秒实际链均正常。205 秒样本断言真实日线风险 `verified`，报价风险时间、input.as_of、config.as_of 和实际 snapshot.as_of 一致，且不晚于 generated_at；timings.started_at 仍是 14:45。
- 另有固定历史 now 跨宿主日期结果完全一致、旧日/过期/真未来、早期有效报价最终过期、180 秒预算不重启、秒精度未来拒绝、input/cache 写入跨截止、墙钟普通/跨日回退、本地异常文本脱敏、附加诊断写失败等边界。后加边界均先确认失败再最小修复。
- 相同合法合成行情的零耗时/205 秒结果除预期时间字段外，日线、市场事实、价量和风险数据相同；真实 target selector 的代码集合相同。不把数据采集恢复解释为策略规则或收益提升。
- 实现 agent 最终 14 模块 **214/214 通过**，退出码 0，`git diff --check` 通过。包含行情、当前风险、正式收盘写库隔离测试、市场历史、预跑 data/runtime/pipeline/contract/notify/e2e/formal-isolation/handoff。

复验入口：`/usr/bin/python3 /private/tmp/chanlun-preclose-clock-20261012/run_isolated_tests.py <实施树> <测试模块...>`。入口在导入前设置临时 `CHANLUN_MARKET_HISTORY_DB_PATH`，临时 K 线缓存，阻断 socket，并拒绝临时目录以外 SQLite。证据目录 `/private/tmp/chanlun-clock-fix-tests/`：`baseline-64.log`、`baseline-five-red.log`、`clock-boundaries-red.log`、`subsecond-red.log`、`cache-write-red.log`、`evidence-clock-red.log`、`final-regression.log`。

## 限制与交付状态

今日原缓存中的失败报价原价已被清空，保留下来的日期/时间/数量证据只支持时间门诊断，不能还原真实候选或收益。没有联网补采、重造今日真实结果或追加历史补数；不能把合成行情通过称为今日生产已恢复。真正自然调度、完整真实行情、结果发布及通知接收仍待后续授权和实际运行验收。

实现完成并交主进程独立审核；本记录写入时未提交、合并或部署。测试均为短进程并已退出，无本任务服务、监听端口或常驻应用；临时测试库/缓存由隔离入口退出清理，证据日志保留。产品/测试已冻结，后续独立复核结果另行追加，不用旧测试结果证明新版本。

## 主进程独立验收追加

主进程对冻结产品/测试独立运行 14 模块 **210/210 通过**（含新增16项），退出码0；`git diff --check` 通过。日志：`/private/tmp/chanlun-preclose-clock-20261012/parent-final-regression.log`。这组是独立验收口径，不与实现 agent 的214项累加：两组共用12模块，主进程另含 `test_preclose_compare` / `test_preclose_launchd`，实现组另含 `test_current_quote_risk` / `test_config_market_history_path`。

同一隔离入口、同一实施树，主进程模块参数为：

```text
tests.test_quote_sources tests.test_preclose_acquisition_clock
tests.test_preclose_runtime tests.test_preclose_handoff tests.test_preclose_data
tests.test_preclose_pipeline tests.test_preclose_contract tests.test_preclose_notify
tests.test_preclose_e2e tests.test_preclose_formal_isolation
tests.test_market_close_snapshot tests.test_market_history_store
tests.test_preclose_compare tests.test_preclose_launchd
```

实现组仅将最后两个模块替换为 `tests.test_current_quote_risk tests.test_config_market_history_path`。最终独立 review 尚待回执；没有因测试通过扩大发布或生产执行范围。

最终独立 review 已回执通过：五个产品文件及新增测试的冻结 SHA256 与验收版本一致，未发现本批剩余代码阻断；真实风险二次门/快照时间一致性与附加诊断写失败两项建议均已有实现和负例验证。历史“待回执”描述至此闭合。全部本任务测试进程已退出，未启动服务或监听端口，临时库/缓存已由测试入口清理，无待清理运行资源；仅保留隔离树和证据日志供交付。最终状态为本地修复和独立验收完成，未提交、合并、上线或重跑生产。

## 2026-10-12 合并 main 授权与准备

用户随后明确要求“合并到main”，授权将本批8个文件提交、推送并合并到最新远端 main。此授权替代前文“尚未获合并授权”的阶段状态；本次不据此宣称运行目录已同步或自然任务已恢复。

合并前重新 fetch，目标分支为 `053b9b94`。相对原基线新增的两笔上游提交没有修改本批产品或测试文件，仅与选股方案文档共用一个路径。先完整备份本批 patch、方案原文及文件指纹，精确移开本任务追加段落，快进后恢复段落和上游全部内容；根旧工作区和生产运行树不参与提交。六个产品/测试文件仍保持最终审查指纹，提交前重新执行14模块隔离回归，并核对最新目标分支为提交祖先。

同步后主进程210项回归209通过、1项旧脚本哈希断言失败，日志 `/private/tmp/chanlun-preclose-clock-20261012/pre-merge-regression.log`。已逐字证明修改前 `tests/test_preclose_launchd.py` 与 `daily_run.sh` 均等于 `origin/main`；失败来自目标分支自身尚未更新的测试常量，不是本批修改了正式脚本。上游 `b09a5f0e` 为正式日报提交接入独立的 `stage_selection_performance.py` 暂存步骤，失败时停止提交保护已暂存产物；该合法上游变化将脚本 SHA256 从旧常量 `77dc136adba7c5fe28bc0a88db8c5d0b9b8da756a9088a82a677985cd0948f60` 改为 `e098670d9adad33adfd4165be72be11c07c2cc243e9e20c65be9e5662856d5f7`。

因此本次合并增加第9个文件 `tests/test_preclose_launchd.py`，仅更新基线常量和说明注释，原脚本字节、实际哈希比较、日志/锁区分和预跑无正式依赖断言全部保留。10项 launchd 测试先9通过/1失败，刷新后10/10通过（退出0）；日志 `/private/tmp/chanlun-clock-fix-tests/post-sync-launchd-red.log` 与 `post-sync-launchd-green.log`。产品五文件和新增16项测试仍保持原冻结指纹；该过时测试更新不改变产品行为或扩大生产授权。主进程将对当前9文件版本重跑210项后决定提交合并，本段尚不宣称提交/推送/合并完成。

提交前复验回执：主进程已在 `053b9b94` 及最终9文件版本独立重跑原14模块，**210/210通过、退出码0**，日志 `/private/tmp/chanlun-preclose-clock-20261012/pre-commit-regression.log`；`git diff --check` 通过，目标 main 已为当前修复基线祖先，五个产品和原新增测试指纹保持。范围及过时测试来源核查完成，按本轮用户授权提交并合并；实际远端合并状态以关联 PR 和 Git 回读为准，不代替运行目录或自然任务验收。
