# 2026-09-12 UI data implementation handoff

## U04 / M2

- 分类：C 类图表载荷修复。
- 轮次：5 轮实质修正（只读溯源与 RED；量能序列边界修复；均线展示计算与 21 根量比收束；bool/非有限值、源 MA 缺口和显式价基边界；双有效价基冲突阻断）。达到本子问题上限，后续不再扩展该子问题。未运行日报、未重生成历史、未写数据库、账本、通知或生产输出。
- 影响边界：B02、B06、B09、B10。候选资格、正式动作、正式评分、原排序、参考价和失效价不在改动范围内。

## 已核实的事实通路

可靠行情源在 `kline_repository._rows_to_kline` / `data_fetcher` 中生成逐根 `volume_units`、`volume_raw_units`、`volume_sources`、成交额可用性和来源；`run.py::_attach_kline_evidence` 将这些字段附加到分析结果，`screener_fusion`、`daily_structure_pool`、`strong_startup` 和 `trend_continuation` 再复制到候选行。此次没有改行情采集、DB 或策略生产代码。

当前仓库内的 2026-09-11 25 只历史展示样本（5 只 `picks_pure` + 20 只 `startup_watchlist`）有 `volumes`，但没有 `volume_units`、`volume_raw_units` 或 `volume_sources`。这是旧快照/旧生成时点的输入缺口；仅凭成交量数值不能补单位或来源，所以保持缺失。没有把历史报告重生成成“当时已提供证据”。

## 实际改动

### `chanlun/report_generator.py`

- 量能和成交额 metadata 只在整组长度与日线日期窗口一致时切片；任一单位、原单位、来源或成交额可用性错位，整组留空，避免把短数组错贴到别的 K 线。多根序列的 scalar 单位/来源不广播。
- 原有白名单字段继续使用：`volume_units`、`volume_raw_units`、`volume_sources`、`amount_available`、`amount_units`、`amount_sources`。`data_status` 与已有 `price_basis` 原样保留，来源、最新日期、终局和价基可回查。
- 若日线 `data_status` 为 verified、final、非 stale 且价基明确，使用同价基 `closes` 只生成展示用 SMA5/SMA10；可信原 `ma5`/`ma10`/`ema5`/`ema20` 序列优先。新增字段 `ma5`、`ma10`、`ema5`、`ema20` 及 `chart_ma`，其中 `chart_ma.series` 声明 `source` 或 `derived`、算法、窗口、价基和截至日期。只派生 SMA，不把它称为 EMA；缺价基、未核验、窗口不足或错位保持 unavailable。
- bool、`np.bool_`、NaN、无穷和非正数不能成为价格或源均线；源均线的 null 缺口保留，但全无有效值不标 available。显式有效价基优先于冲突的 `data_status` 回退值；显式无效价基不从其他字段复活。
- 双方价基均有效但 adjustment 不一致时标记 `price_basis_conflict`，不输出可用源/派生均线；双方一致，或仅一侧有效且另一侧缺失，才按上述规则继续。

### `chanlun/report_view_model.py`

- 保留原 `volume_ratio20` 作为既有 workspace 质量评分输入，避免改变 liquidity score/排序；新增展示字段 `display_volume_ratio20`，只有当日加前 20 根、共 21 根、单位和来源均核验且分母大于 0 时才计算 `current / mean(previous20)`。
- 展示字段同时给出 `display_volume_ratio20_window_bars=21`、`display_volume_ratio20_method=current_div_previous20_mean` 和可用状态；不改变正式决策分或策略资格。

## RED/GREEN 与负例

- RED 已复现：旧 serializer 对错位 metadata 仍输出短数组；旧 view model 直接接受生产 `volume_ratio=99`，且 20 根窗口不足时仍给出值；bootstrap/daily 没有可验证的均线序列白名单。
- GREEN 覆盖：完整源 metadata 进入 daily projection 和 bootstrap；缺 metadata、scalar metadata、任一组长度错位均保持空；0/缺窗口的 21 根量比不计算；同价基 closes 的 SMA5/SMA10 数值对照（测试值末根分别为 58.0、55.5）；源 MA 序列优先；缺价基不派生。
- 固定输入对照还验证了改变仅供展示的第 21 根量能数据后，所有 workspace view 的代码、顺序、view rank、opportunity score 和基础 score 不变；变化只出现在 `display_volume_ratio20`。

真实旧报告仍不能恢复：25 只历史快照缺单位/原单位/来源，且没有当时可回查的逐根 metadata；本次不猜 `hands`、不猜来源、不补历史。新运行只有在上游实际注入 metadata 后才会恢复成交量图；本次代码本身不能证明旧 25 只已经恢复。

## 验证

- `/usr/bin/python3 -m unittest tests.test_report_generator tests.test_report_view_model`：当前 226 项通过（含固定输入 workspace 不变回归和本轮五个边界用例）。
- 相关回归基线此前为 296 项通过；完整套件、主进程独立 diff 审查、目标分支同步、提交和发布由主进程继续执行。
