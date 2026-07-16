# ChanlunStrategy

缠论选股日报当前采用“单库、DB 优先、缺失才远程补齐”的行情架构。日线、30 分钟和 15 分钟 K 线统一存放在 `.cache/chanlun/market_history.sqlite`；ongoing 与回测共用同一事实源，回测必须显式传入 `as_of`，且禁止网络兜底。

## 运行模式

- `CHANLUN_MARKET_DATA_MODE=sqlite`：正式模式，SQLite 是唯一行情事实源；默认值。
- `CHANLUN_MARKET_DATA_MODE=shadow`：迁移诊断模式，只读旧 JSON 做数值比较，旧 JSON 不能覆盖 SQLite。
- `CHANLUN_RECALL_STRATEGY_MODE=shadow`：运行全 A、趋势通道和观察池并保存漏斗，但正式主池仍按旧股票范围推送；默认值。
- `CHANLUN_RECALL_STRATEGY_MODE=active`：新召回策略接管正式主池。
- `CHANLUN_RECALL_STRATEGY_MODE=legacy`：紧急关闭全 A 新召回；不会恢复“位置缺失即高位风险”的旧错误语义。

正式切换前至少保留 3 个交易日 shadow 结果，并通过三日强股召回审计和 20 日 walk-forward 风险门禁。

## 审计命令

```bash
python3 scripts/audit_next_day_top_recall.py \
  --db .cache/chanlun/market_history.sqlite \
  --json-output output/recall-3day.json \
  --markdown-output output/recall-3day.md

python3 scripts/run_recall_walkforward.py \
  --db .cache/chanlun/market_history.sqlite \
  --output-json output/recall-walkforward.json \
  --output-md output/recall-walkforward.md
```

日报推送前，`daily_run.sh` 会调用 `scripts/validate_today_report.py`，要求正式收盘数据、SQLite 模式、候选漏斗成功落库，并验证 shadow 模式下新策略没有接管正式主池。
