# ChanlunStrategy

缠论选股日报当前采用“单库、DB 优先、缺失才远程补齐”的行情架构。日线、30 分钟和 15 分钟 K 线统一存放在 `.cache/chanlun/market_history.sqlite`；ongoing 与回测共用同一事实源，回测必须显式传入 `as_of`，且禁止网络兜底。

## 运行模式

- `CHANLUN_MARKET_DATA_MODE=sqlite`：正式模式，SQLite 是唯一行情事实源；默认值。
- `CHANLUN_MARKET_DATA_MODE=shadow`：迁移诊断模式，只读旧 JSON 做数值比较，旧 JSON 不能覆盖 SQLite。
- `CHANLUN_RECALL_STRATEGY_MODE=active`：新召回策略接管正式主池；默认值。
- `CHANLUN_RECALL_STRATEGY_MODE=shadow`：完整运行并记录新策略，但正式主池退回旧股票范围，用于异常排查。
- `CHANLUN_RECALL_STRATEGY_MODE=legacy`：紧急关闭全 A 新召回；不会恢复“位置缺失即高位风险”的旧错误语义。

新策略已经完成三日强股召回审计并切为正式推荐。20 日 walk-forward 继续作为阈值优化和尾部风险监控，不再阻塞新召回入口上线。

全 A 召回的总容量上限为 1200。热板块成分可用时采用“基础 800 + overlay 最多 400”；题材覆盖缺失或没有有效成分时，不浪费预留容量，自动切换为低位 525、趋势 525、中性 150 的基础 1200。趋势主通道量比仍为 1.3；弱结构观察仍为 1.2；只有强结构且仅缺量比的观察样本允许降到 1.0。

三日真实数据复盘见 `docs/analysis/2026-07-16-three-day-recall-review.md`。

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

日报推送前，`daily_run.sh` 会调用 `scripts/validate_today_report.py`，要求正式收盘数据、SQLite 模式、候选漏斗成功落库，并验证 active 模式下新策略确实接管正式主池。
