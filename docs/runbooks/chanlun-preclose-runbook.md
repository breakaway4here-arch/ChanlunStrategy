# ChanlunStrategy 14:45 预跑与盘后复核运行手册

## 运行边界

预跑是 14:45 至 14:56:30 的临时建议，只生成主推、H4 T+3、加速三个池。它不调用新闻、公告/研报、LLM、iWencai、15 分钟策略、罗姐池、报告生成或 Git 发布，也不写正式行情库、推荐账本、日报、记分卡或 comparison index。盘后复核只读正式日报，失败不影响 `daily_run.sh` 的退出码或发布状态。

交易日门禁优先读取正式行情库中的 `trade_calendar`；没有本地覆盖时使用经 Review 的上交所 2026 年休市表。更新年度休市表时必须依据[上交所休市安排](https://www.sse.com.cn/disclosure/dealinstruc/closed/)重新 Review，未知年度默认跳过。

## 专用配置

凭证只保存在 `~/.config/chanlun-strategy/preclose.env`，文件必须属于当前用户且权限为 `0600`。必需键为：

```text
PRECLOSE_API_BASE
PRECLOSE_WRITE_TOKEN
WXPUSHER_APP_TOKEN
WXPUSHER_UID
PRECLOSE_NOTIFY
```

`WECOM_BOT_WEBHOOK` 是可选通道。`PRECLOSE_NOTIFY=0` 用于真实交易日影子验收，人工核对通过后改为 `1`。不要把任何值复制到 plist、仓库、工单或日志。

检查权限和配置结构（不打印值）：

```bash
stat -f '%Su %Sp' ~/.config/chanlun-strategy/preclose.env
/usr/bin/python3 -c 'from chanlun.preclose_notify import load_preclose_env; load_preclose_env()'
```

## 安装和回读 launchd

从正式 checkout 执行：

```bash
scripts/install_preclose_launchd.sh
for label in \
  com.breakaway4here.chanlun-preclose \
  com.breakaway4here.chanlun-preclose-reconcile
do
  /bin/launchctl print "gui/$(id -u)/${label}" | /usr/bin/awk '
    /inherited environment = \{/ { inside = 1; print; next }
    inside && /^[[:space:]]*}/ { inside = 0; print; next }
    inside { sub(/=>.*/, "=> [redacted]"); print; next }
    { print }
  '
done
```

禁止把原始 `launchctl print` 直接输出到终端、日志或验收记录；当前用户会话的继承环境可能包含与本任务无关的凭证。回读必须先按上面的方式脱敏，验收只记录 label、绝对路径、状态、运行次数和退出码。

安装器拒绝覆盖已有同名 plist。若存在冲突，先查明来源，不要直接删除或覆盖。两个任务分别在工作日 14:45 和 15:05 启动；复核每 30 秒只读轮询，15:35 硬退出。15:35 到点不再启动新的正式校验、Worker 写入或提醒发送；已经启动的一轮也受同一个硬截止约束。

## 手工 dry-run 与查看证据

固定 fixture 的隔离运行必须使用临时 root、`--skip-publish` 或 mock provider，不能写正式路径：

```bash
/usr/bin/python3 preclose_run.py --input /absolute/input.json --root /private/tmp/chanlun-preclose-dry-run --trade-date YYYY-MM-DD --as-of YYYY-MM-DDT14:45:00+08:00 --generated-at YYYY-MM-DDT14:45:00+08:00 --source-sha COMMIT_SHA --skip-publish
```

生产调度日志和当日证据：

```bash
tail -n 100 .cache/chanlun/preclose/logs/preclose-run.log
tail -n 100 .cache/chanlun/preclose/logs/preclose-reconcile.log
ls -l .cache/chanlun/preclose/YYYY-MM-DD/
/usr/bin/python3 -m json.tool .cache/chanlun/preclose/YYYY-MM-DD/snapshot.json
/usr/bin/python3 -m json.tool .cache/chanlun/preclose/YYYY-MM-DD/reconciliation.json
```

当日隔离目录中的运行证据含义如下：

- `failure.json`：失败或硬截止的真实内部原因、run/source 身份及快照 hash；不得公开到今日决策页面。
- `timings.json`：行情获取、三池计算、发布/提醒三个外层阶段和全程耗时；日线、30 分钟、市场上下文、决策门控与各池细项读取 `snapshot.json` 内部 `diagnostics.stage_seconds`。
- `run-evidence.jsonl`：14:45 任务开始与结束的追加式证据；用于区分已启动任务的成功、失败和超时。
- `reconciliation-polls.jsonl`：盘后每轮只读复核状态及 15:35 终止证据。
- `reconciliation-failure.json`：盘后校验、环境读取、发布或证据写入异常的阶段与错误类型；只属于隔离复核任务。

“未运行”不能由一个从未启动的进程自行写文件；必须联合使用 launchd 当日运行次数、调度日志和当日隔离目录不存在这三项证据，不能用事后手工创建的 `not_run` 文件冒充。

14:49 前若正常快照写入失败，任务会原子提升启动前已准备的空池截止快照，使网页只显示“本期未选出推荐票”；真实失败原因继续只保存在上述内部证据。验收时应同时核对这些文件的 `trade_date`、`run_id`、`source_sha`、`snapshot_id/content_hash`，不能仅以进程退出码代替。

`run.lock` 与 `reconcile.lock` 是不同的短期活动锁。进程不存在但锁仍在时，先保留锁内容和日志作为证据，再由人工确认后处理；不要把删除锁当成常规重试。

## Worker 生产回读

发布前先从正式 checkout 进入独立 Worker 目录，使用该目录锁定的本地 Wrangler 执行 dry-run，再正式部署：

```bash
cd cloudflare/preclose-worker
npx wrangler deploy --dry-run
npx wrangler secret list
npx wrangler deploy
npx wrangler versions list
npx wrangler deployments list
```

`secret list` 只用于核对名称。若列表已包含 `PRE_CLOSE_WRITE_TOKEN`，普通发布不得运行 `secret put` 或覆盖现有值；只有确认该名称缺失，或处于明确授权的凭证轮换变更窗口时，才允许单独交互式写入。

生产 GET 使用 `/api/preclose/latest?date=YYYY-MM-DD`；PUT 后必须 GET 回读同一 `snapshot_id/content_hash`；盘后 reconciliation 还必须回读同一 `preclose_content_hash/formal_content_hash/content_hash`。检查允许的 Pages origin 可读取、其他 origin 返回拒绝、响应为 `Cache-Control: no-store`，公开字段不含 diagnostics、内部原因、审计历史或密钥。不要在终端历史中直接拼 token，使用已验证的专用 env 加载器或一次性安全进程。

现有 Top10 的前后只读回读必须比较 HTTP 状态、响应体 hash，并重跑 `cloudflare/top10-worker` 测试；不得修改其路由、KV、binding 或 migration。

## 提醒、补发和幂等

WxPusher 只有 HTTP 成功且业务 JSON `success=true` 才算成功；手机实际到达另做人工记录。企业微信若启用，必须满足 `errcode=0`。网页、预跑提醒和盘后复核都核对相同 snapshot identity/hash。

同一预跑 hash/channel 与同一 `trade_date + formal_content_hash + channel` 不重复发送。补发前先检查 `notification-outbox.jsonl` 和 `reconciliation-outbox.jsonl`；不要修改历史成功行。供应商失败可在凭证或网络修复后重跑独立发布/复核入口，正式日报无需重跑。

## 右侧启动样本外回放与激活门

右侧启动上线后默认保持 `CHANLUN_RIGHT_SIDE_STARTUP_MODE=shadow`。历史回放只允许读取现有正式行情库和正式报告，不得网络回补，也不得写行情库、账本、日报、scorecard 或 comparison index。脚本以 SQLite `mode=ro` 和 `PRAGMA query_only=ON` 打开行情库；日线特征不晚于交易日，30 分钟特征不晚于当日 15:00，之后的数据只用于计算 T+1/T+3/T+5 结果。

默认运行只向标准输出打印聚合统计，不创建文件：

```bash
/usr/bin/python3 scripts/replay_right_side_startup.py \
  --market-db /absolute/runtime/.cache/chanlun/market_history.sqlite \
  --reports /absolute/runtime/docs/data \
  --as-of YYYY-MM-DD
```

只有明确准备验收证据目录后才允许落盘：

```bash
/usr/bin/python3 scripts/replay_right_side_startup.py \
  --market-db /absolute/runtime/.cache/chanlun/market_history.sqlite \
  --reports /absolute/runtime/docs/data \
  --as-of YYYY-MM-DD \
  --evidence-dir /absolute/evidence/right-side-startup/YYYY-MM-DD
```

默认窗口为 4 个训练日、2 个隔离日、每块 2 个测试日、10 块，因此恰好覆盖 20 个样本外交易日；不得把块数降到导致样本外日期少于 20。报告必须同时包含 `right_side` 与经 `build_workspace(formal_report).views.main` 获取的 `formal_main_baseline`，以及时间分块、embargo、每日候选数和 P95、T+1/T+3/T+5 胜率/均值/中位数/P10/最差收益、最大回撤和 `<=-5%` 尾部率。

历史门只有在以下条件同时成立时才通过：`gate_events` 存在且覆盖当日完整正式检索全集；至少 20 个样本外交易日；右侧和正式基线分别至少 20 个可评估 T+3 样本；右侧 T+3 中位数不劣于正式基线；尾部率增量不超过 2 个百分点；原始确认候选每日 P95 不超过 20；公开右侧来源仍严格限制为 Top3。任何字段或样本缺失都 fail-closed。

正式 shadow 跑数的逐日诊断独立原子写入 `.cache/chanlun/right-side-startup/formal/YYYY-MM-DD.json`，权限为 `0600`。文件包含策略版本、完整 Git SHA、`as_of`、正式/预跑身份，以及候选和观察项的代码、参考位/距离/量比、30 分钟 mandatory/structure/quality、失败门、实际值和阈值；不得只保存聚合数量。该目录是运维复核入口，不属于正式日报、行情库、推荐账本、scorecard、comparison index 或 Pages 发布面；审计写入异常只报警，不得反向阻塞正式任务。

回放结果永不自动转正：`promotion_eligible` 固定为 `false`。还必须完成至少一个真实交易日 shadow 的 14:45 自然触发、14:49 截止、14:56:30 失效和盘后复核，并重新取得授权，才可把模式改为 `active`。任一门槛失败时继续 shadow，不得为了召回个别样例放宽阈值。

## 关闭与回退

停止两个调度任务：

```bash
launchctl bootout gui/$(id -u)/com.breakaway4here.chanlun-preclose
launchctl bootout gui/$(id -u)/com.breakaway4here.chanlun-preclose-reconcile
```

页面回退通过下一次正式发布把 `precloseApiBase` 置空；Worker 回退使用向前部署的 `PRECLOSE_ENABLED=false` 禁用版本并保留 Durable Object 审计数据。Durable Object 类或 migration 生命周期变化后，不承诺旧版本简单 rollback 一定可用。关闭预跑、关闭复核、关闭页面读取彼此独立，均不得修改或阻塞正式 `daily_run.sh`。

## 真实交易日验收

首次先用 `PRECLOSE_NOTIFY=0`：核对 14:45 真实触发、14:49 截止、三池快照、14:56:30 双端失效，以及正式日报/账本/Pages 的 hash 和语义不变。人工验收后开启通知，记录 WxPusher 业务成功和手机到达；盘后无论一致或有变化都应收到一次主动复核，相同正式 hash 重试不应重发。若已错过 14:45，不得用手工补跑冒充真实定时证据。
