# 2026-09-12 图表库非阻塞加载实施记录

## 范围与授权

本批只处理 M5/U14 的展示加载边界：页头、本期结论、候选列表和文字证据先就绪；ECharts 5.4.3 延迟、失败和重试只影响对应图表。未改变策略、候选、排序、价位、风险、通知、正式数据或业务写入。

影响边界：B09 运行/公开隔离、B10 演进与验收证据。保留旧报告缺字段时的文字降级能力。

## 根因与实现

基线壳在 `DOMContentLoaded` 前以 `defer` 加载 CDN ECharts；实测 ECharts 约 8 秒，导致报告初始化和列表可操作性被串行阻塞。图表渲染函数在 `window.echarts` 未就绪时直接返回，市场情绪图也没有失败状态或重试入口。

本批改为固定本地 ECharts 5.4.3 资源（Apache-2.0 文件头保留），壳只声明异步资源配置，`report-v2.js` 负责单例加载 promise。DOM/data/mount 缺口独立降级；库加载中显示状态，失败显示原因和“重试加载图表库”。个股图和市场情绪图共用库 promise，各自按当前 mount、候选身份、渲染 token 回查，旧股票/旧 DOM 的延迟回调直接丢弃；从任一图表点击重试都会让另一图表消费同一份已就绪库。`initReportV2` 增加幂等 guard，避免重复业务初始化。资源版本计算、完整复制和完整性声明对 CSS/JS/ECharts 均要求文件存在，缺失直接失败。

报告生成器同时提供 `refresh_report_chart_library_references()`，只替换 v2 HTML 的图表资源壳，不触碰 inline bootstrap 或 data JSON。已同步根页、14 个 v2 历史/比对入口的资源引用；旧版非 v2 页面保留原兼容路径。

源与发布 ECharts 文件 SHA256：

`1156429a16a38cb8604dcc6518c19406d4226142d908f8edd2e3531443c54d19`

## 实际验证

- `/usr/bin/python3 -m unittest -q tests.test_ui_loading_contract tests.test_report_generator tests.test_repair_auxiliary_decision_snapshot`：169 项通过。
- `/usr/bin/python3 -m unittest discover -s tests -q`：2236 项通过，1 项既有 skip。
- `scripts/check_ui_loading_browser.cjs` 使用本机 Chrome、`file://` fixture 和固定本地 ECharts，真实覆盖 10 秒延迟、首次失败、切换股票后快速双击用户重试；1440×900、1366×768、390×844 的延迟路径均通过。工作台约 66–76ms 可操作，延迟完成后只挂载当前股票；市场情绪图与个股图均真实就绪；失败模式列表保留；重试模式请求次数为 2（一次失败、一次成功），两张图均恢复，重复点击复用 in-flight Promise；无 pageerror、无外部请求。
- `node --check chanlun/report_assets/report-v2.js` 与 `node --check scripts/check_ui_loading_browser.cjs` 通过。
- 最终输出证据保存在 `/private/tmp/chanlun-ui-final-20260912/loading-browser-v14/browser.json` 及同目录截图，仅供本地验收，不进入仓库。

## 轮次台账

本批 M5 的实质修正为 5 轮：①单例异步库加载、壳配置和 token 生命周期；②资源升级 helper 幂等化并对必需资源缺失 fail-closed；③失败后切股重试时让个股图和市场情绪图共享同一库恢复；④ in-flight 重试复用、双击 loading 状态和合法合成日期；⑤手机首屏清理 detached 详情挂载，并增加连接状态回归。`loading-browser-v7` 至 `v14` 是回归运行编号，不是额外实现轮次；v14 是最终三视口/手机初始等待/失败/快速双击重试结果。

## 未覆盖项

本批未部署、未启动 HTTP 服务、未接触正式数据/推送；最终三视口上线资源同步由主进程执行。15/30 分钟标题语义问题属于 layout 子任务，保留给对应 agent。
