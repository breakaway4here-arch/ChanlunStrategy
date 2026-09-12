# 决策工作台离线浏览器验收

`build_fixture.py` 生成完全合成的固定日报。它调用 `build_decision_workbench`，再为少量候选补充人工构造的 K 线；不包含真实股票、账户、持仓、凭证或推送载荷。浏览器脚本只读取指定 worktree 的 `report-v2.js` / `report-v2.css`，不改产品文件。

从仓库根目录运行：

```sh
NODE_PATH="$PLAYWRIGHT_NODE_PATH" node scripts/check_ui_final_browser.cjs \
  --root "$UI_SOURCE_ROOT" \
  --echarts "$ECHARTS_543_FILE" \
  --output /private/tmp/chanlun-ui-final-browser/latest
```

`PLAYWRIGHT_NODE_PATH`、`UI_SOURCE_ROOT` 和 `ECHARTS_543_FILE` 由本机运行环境提供。脚本不启动 HTTP 服务；`file://` 页面只放行本地 fixture、指定源 JS/CSS、固定 ECharts 5.4.3 和本地比较索引空响应，其余外部请求均 abort。浏览器在 `finally` 中关闭，截图与 `browser.json` 只写入 `/private/tmp`。

验收覆盖 1440×900、1366×768、390×844，包含：完整/缺价/分歧/研究/过期冲突/无日线/部分量能/长名称/旧版缺 workspace；全部候选、20→25 分页、比较表、搜索有/无/清空、板块筛选/清空、K 线缩放后切层、同股抽屉重挂载、手机焦点和 390→1440→390。M3/M4/M5 以真实能力范围记录 `pending`：阅读摘要/锚点/候选密度/只读我的关注，变化下钻/三只比较/历史入口，图表库非阻塞及延迟失败重试。

当前源版本若将 15m 证据放在固定“30分钟确认”标题下，脚本会保留其他通过项并以 `FAIL` 报告该周期错配；这是产品验收结果，不在本目录修复产品代码。
