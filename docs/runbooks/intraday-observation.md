# 14:45 完整分池观察任务

独立观察任务，保留原盘后 15:05／15:20、原预跑、正式行情库、账本和网页。新增微信标题为“14:45完整选股观察”，仅向现有个人 WxPusher UID 发送池名、名称和代码。

## 行情与边界

- 交易日北京时间 14:45 启动，行情截止固定 14:45；生成时间独立。
- 当天日线来自 15 个完整 15 分钟桶，保持盘中非 final；30 分钟最后到 14:30。
- 每标的每轮四个逻辑请求：截至上一交易日的 raw/qfq 日线及截至 14:45 的 raw/qfq 分钟，整标的额外最多一次连接瞬断重试，单轮上限五次。仅全轮后来源覆盖低于90%或缺核心指数、基础资料已过门且剩余至少60秒时，冷却2秒再对明确最终连接失败的标的恢复一轮，整批每标的绝对上限十次。成功及证书、HTTP/限流、身份、解析、价基错误不重抓。历史分钟逐日四价认证，正式库只读。
- 全母集先检查基础资格，采集后按当日流动性和原 no-overlay 配额召回。ST/上市不足与基础资料缺失分开计数。
- 局部缺失推送覆盖不完整；低于 90%、超时、限流或核心指数缺失均明确失败，不伪装正常空池。
- 无法证明截止的板块资金、综合情绪等辅助项暂不可用并简短提示。与盘后差异可能来自价量截止、辅助缺项及记录的覆盖差异，不能据此直接认定收益改善。
- 采集止于 14:57:30，预留 30 秒用于汇总、冻结输入、完整计算及验证；计算进程组硬截止 14:58，微信整体墙钟截止 14:59。未知发送状态不自动重复。

## 归档

运行目录 `.cache/chanlun/intraday-observation/YYYY-MM-DD/` 独立保存：`inputs/` 逐标的证据、实际请求 attempt 与失败，`input.json` 和 `input-final.json` 冻结输入、`snapshot.json` 分池结果、`outbox.json` 发送回执、`timings.json` 分阶段耗时、失败时的 `failure.json` 及 `calculation.log`。输入和结果禁止同日覆盖；捕获以完整文件 create-once 暴露。接口成功不等于用户已接收。

首轮捕获保留在 `inputs/`，恢复只写 `inputs/recovery-1/`；`inputs/_requests/` 保存每轮 fsync 后的不可变母集/identity/前日/截止/预算意图。崩溃后已有完成捕获继续可读，该轮没有结果的标的视为 dispatch 未知，不盲重发，也不开第三轮。任一已记录429/456在重启前预检后继续停止来源；低覆盖、截止与未知发送仍如实失败。

## 安装与停用

新 label 为 `com.breakaway4here.chanlun-intraday-observation`。安装器参数依次为绝对观察 checkout、预期提交、正式数据库绝对路径；验证干净版本，只创建这一 label，同名已存在则拒绝覆盖。微信仅读现有 `~/.config/chanlun-strategy/preclose.env`，不复制或打印凭据。

```zsh
/bin/zsh scripts/install_intraday_observation_launchd.sh /absolute/observation-checkout EXPECTED_COMMIT /absolute/market_history.sqlite
```

`RunAtLoad=false`，不手动 kickstart，不启动常驻服务。当前宿主已核实 Asia/Shanghai；迁移时必须再核对系统时区，launchd 日历使用宿主时区。

停用只卸载这一 label，保留原 daily/preclose 与所有归档：

```zsh
/bin/launchctl bootout "gui/$(id -u)/com.breakaway4here.chanlun-intraday-observation"
```

## 离线回放

手动运行必须提供已冻结输入。不加 `--send` 不会发微信；允许盘后或历史日期，另有 13 分钟有限预算，数据截止不变。

```zsh
/usr/bin/python3 intraday_observation_run.py --date YYYY-MM-DD --input /absolute/input.json --root /private/tmp/replay/intraday-observation --formal-market-db /absolute/market_history.sqlite
```

## 验收范围

已验证真实少量来源、日/分钟构建、冻结输入完整主流程、默认盘后非空样本不变，以及缺口、异常、超时和重复投递边界。默认盘后 off/shadow 两组公开投影与生产基线一致（只去除纯工作目录路径）。

10/19 冻结全量回放已证明 capture 等价提速，5,021 份捕获字节及九池结果不变，最后采集线程完成后 18.870 秒可以完成计算与冻结，见[可靠性修复记录](../plans/2026-10-19-intraday-observation-reliability.md)。真实全市场 20 并发是否在新预算内完成、修复后自然启动、微信接口回执与用户接收仍须分别观察；离线回放和少量来源不能替代这些证据。
