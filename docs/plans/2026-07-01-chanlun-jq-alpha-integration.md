# Chanlun JQ Alpha Integration Plan

## Goal

在不新增正式股票池、不改变现有 `pool -> scoring -> ranking` 结构的前提下，把高收益聚宽脚本中可复用的择时和质量因子轻量接入现有缠论选股：

- 日线 MA5 > MA10 > MA20 的短线多头结构
- 30min 两阳夹一阴 / 两阳夹两阴的分时确认
- 强市场环境下对启动票的小幅追击倾斜
- 只作为加分项或 bounded alpha，不作为硬过滤

本轮实现后先运行单测和本地历史快照回测，不提交代码。

## Scope

允许改动：

- `chanlun/strong_startup.py`
- `chanlun/next_day_boom.py`
- `chanlun/scoring_engine.py`
- 对应测试文件
- 必要时轻量增强 `scripts/backtest_scoring_alpha_impact.py` 的实验输出

不做：

- 不新增新模块或新系统
- 不新增正式主股票池
- 不引入新的回测框架
- 不拆分 scoring pipeline
- 不引入固定股票代码白名单
- 不提交 / 不 push

## Implementation Tasks

### Task A: Strong Startup 30min Confirmation

Owner: subagent

Files:

- `chanlun/strong_startup.py`
- `tests/test_strong_startup.py`
- `tests/test_startup_labels.py` only if label expectations need coverage

Work:

- 在 `_check_30min_confirmations` 内识别 30min 两阳夹一阴、两阳夹两阴。
- 信号命名建议：
  - `30min两阳夹一阴确认`
  - `30min两阳夹两阴确认`
- 只追加 confirmations，不改变原有升级流程。
- 若确认信号存在，继续走现有候选升级逻辑。
- `annotate_startup_quality` 可把这类确认视为已有 B 级确认；不需要硬升 S。

Acceptance:

- 现有 30min EMA / 二买三买 / 回踩确认测试不回退。
- 新增测试覆盖两种形态与非形态样本。

### Task B: Boom Ranking And Scoring Alpha

Owner: subagent

Files:

- `chanlun/next_day_boom.py`
- `chanlun/scoring_engine.py`
- `tests/test_next_day_boom.py`
- `tests/test_scoring_engine.py`

Work:

- `next_day_boom` 从 `confirmations` / `confirmed_by` 读取两阳确认，给 `boom_score` 小幅加分，并在 `boom_reason` 输出原因。
- 将 confirmations 继续透传到 candidate，避免信息丢失。
- `scoring_engine` 在 alpha features 中识别：
  - `ma_bullish`
  - `confirmations`
  - `confirmed_by`
  - `startup_signals`
- breakout quality alpha 中对 30min 两阳确认、MA 多头、启动信号质量做小幅正向加分。
- 所有新增 alpha 仍受 `ALPHA_BONUS_LIMIT` 和 multiplier 上限保护。

Acceptance:

- baseline scoring 在 `alpha_enabled=False` 时不变。
- alpha 只能正向小幅影响，不引入负向惩罚。
- 新增测试覆盖 capped bonus 与两阳确认加分。

### Task C: Backtest Diagnostics

Owner: subagent or main review

Files:

- `scripts/backtest_scoring_alpha_impact.py`

Work:

- 在不改框架的前提下，增加当前 alpha 实验可读性。
- 输出应能区分：
  - before alpha
  - after alpha
  - switched in / switched out
  - 如可行，补充 alpha factor 命中计数或代表样本。
- 不依赖网络，不写报告文件。

Acceptance:

- 脚本继续支持现有参数。
- 可以直接用于本轮改动后效果判断。

## Verification

Targeted tests:

```bash
python3 -m unittest tests.test_strong_startup tests.test_startup_labels tests.test_next_day_boom tests.test_scoring_engine -v
```

Backtest:

```bash
python3 scripts/backtest_scoring_alpha_impact.py --min-forward-days 3
python3 scripts/backtest_scoring_alpha_impact.py --min-forward-days 1
```

Decision criteria:

- 如果 mean return 和 win rate 都改善，且最大回撤或尾部亏损不明显恶化，则认为本轮 alpha 有保留价值。
- 如果只在宽松样本改善、严格样本不改善，则保留代码但标记为需要更大样本验证。
- 如果 switched-in 明显变差，则回退或压低新增权重。

## Delegation Notes

- subagent model: `gpt-5.3-codex-spark`
- 小兵实现完成后不要 commit，不要 push。
- 不要改动未跟踪的 `scripts/joinquant_alpha_weight_experiment.py`。
- 各小兵只改自己分配的文件，主线程统一 review、跑测试和回测。
