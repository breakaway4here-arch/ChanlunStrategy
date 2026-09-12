# M5 非阻塞图表加载实验归档

这里保留 `0ab00599`/`e6d0e0a5` 版本的 M5/U14 合成浏览器断言和 Python 合同测试，作为停止证据与复现材料。它们不属于当前发布验收，也不应加入当前全量测试；当前发布路径恢复为 ECharts 先加载、业务随后初始化。

撤回原因：HTTPS 根页 1440px 真实验收中，库仍在 loading 时点击已选 `000636`，ECharts 就绪后 `#chartCanvas` 仍是加载态且 30 秒内没有实例。`beginCandidateSelection` 递增选择版本，旧异步回调因此被丢弃；同股挂载判断又阻止了新的挂载。该生命周期问题已达到本批五轮上限，按边界隔离，不在本次撤回中绕过修复。此前手机首页等待库的 detached 图实例问题已在 e6 轮修正并保留手机清理。

完整实验断言保留在本目录。要复现实验通过结果，应使用原实现提交 `0ab00599` 或最终 M5 提交 `e6d0e0a5` 的独立工作树，并使用旧提交中的原路径：

```sh
NODE_PATH=/Users/yangfan/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules \
node scripts/check_ui_loading_browser.cjs \
  --root "$PWD" \
  --echarts /private/tmp/chanlun-ui-final-20260912/echarts-5.4.3.min.js \
  --output /private/tmp/chanlun-ui-final-20260912/loading-browser-archive
```

对应的 Python 合同测试为旧提交中的 `tests.test_ui_loading_contract`，同样只在上述旧提交工作树中手动运行：

```sh
/usr/bin/python3 -m unittest -q tests.test_ui_loading_contract
```

归档副本只保留完整字节，复现命令需要在包含对应旧提交源码和 vendor 文件的隔离工作树中运行；输出只写入 `/private/tmp`。当前回滚树上的发布验收应使用 `scripts/check_ui_final_browser.cjs`，并验证 ECharts 先加载、业务后初始化及手机详情清理。
