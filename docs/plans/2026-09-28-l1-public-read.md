# L1公开读取 Implementation Plan

**Goal:** 按用户明确要求去掉L1读取前的日报授权限制。
**Architecture:** L1已是公开脱敏JSON，仅移除loadNextdayResearch内state.granted门；不改resolveGranted、日报读取、Cookie、数据合同或策略。禁止通过伪造granted=true放行其他能力。
**Tech Stack:** 原生JavaScript，Python unittest调用Node契约测试。

基线324b00c，隔离树l1-public-read-20260928。主进程沿用本任务直接实现授权。B09访问范围仅L1公开数据，B10保留错日期/异步过期/异常响应保护；其他B项无策略或行情影响。

1. tests/test_nextday_research_frontend.py增加granted=false仍读取正确日期并展示名单、granted仍false的失败测试；负例改用未授权状态检验404、错日期、乱序响应。
2. 仅删除chanlun/report_assets/report-v2.js内4行授权拦截。
3. 运行L1前端及相关回归，同步docs/assets/report-v2.js，刷新资源版本引用但不重渲染或重跑日报；保护9/24额外AI段落和全部数据JSON。
4. 同步远端后限定暂存、提交和发布；保护运行树两处用户docs改动，源/发布资源核对，线上未授权路径验收。

实施补充：归档未授权时resolveInitialData拒绝，使原成功分支的L1调用不可达。因此在失败分支仍加载公开L1，只有日报日期缺失时使用已校验页面日期；已有两种日期冲突仍拒绝。新增空日报未授权测试先失败后通过，未设置granted=true，原归档拒绝逻辑逐字保留。

定向44项通过。159项report_generator基线有2项旧失败（旧取图文本断言、历史shell版本）；候选初次另有未同步资源失败，同步后须复核无新增失败。源JS/发布JS一致；历史HTML仅刷新资源查询版本，跳过生产已有dirty的9/8及compare入口。全部数据JSON、9/24AI段落与既有L1结果不变。无行情补跑、通知或常驻服务。
