# ChanLun Engine Phase 6.4 被过滤样本误伤审计计划

日期: 2026-06-27

## 背景

Phase 6.3 真实历史收益 gate 已通过:

```text
signal_delay1_by_type_guard | medium | coverage 1287 | pass
```

核心改善:

- T+3 mean: `-0.92 -> 0.03`
- T+3 win rate: `35.9% -> 44.5%`
- T+3 <= -5%: `23.7% -> 18.2%`
- big drop 5% rate: `44.4% -> 36.3%`

但实验过滤量较大:

```text
filtered = 805
legacy_evaluated = 1706
experiment_evaluated = 1287
```

在考虑 promotion 或继续叠加弱趋势/冷却之前，必须先回答:

```text
被过滤的 805 个样本里，有没有被误杀的大涨样本？
```

## 目标

新增 filtered-sample audit，专门分析被 signal guard 过滤掉的样本质量。

需要输出:

- 被过滤样本数量和收益分布。
- 被过滤样本中 big-run 样本比例。
- 被过滤样本中 top winners 列表。
- 按 `best_buy_point.type`、`signal_tier`、`confirmations`、`distance_from_reference_pct` 分组。
- 判断当前 `signal_delay1_by_type_guard` 是“清理噪音”还是“误伤机会”。

## 范围

### Do

- 增加 filtered sample audit 模块或脚本。
- 复用 Phase 6.3 的历史快照、行情缓存和收益计算口径。
- 输出 JSON 和 Markdown。
- 只做分析，不改 production。

### Do Not

- 不 promotion `signal_delay1_by_type_guard`。
- 不新增弱趋势过滤/冷却规则。
- 不改变 `run_engine_experiments.py` 默认行为。

## 建议实现

新增模块:

```text
chanlun/filtered_sample_audit.py
```

新增脚本:

```text
scripts/audit_filtered_samples.py
```

命令:

```bash
python3 scripts/audit_filtered_samples.py \
  --experiment signal_delay1_by_type_guard \
  --output-json /tmp/phase6_4_filtered_audit.json \
  --output-md /tmp/phase6_4_filtered_audit.md
```

## 口径

Filtered sample:

```text
legacy 可评估
且 experiment 过滤掉
```

收益口径:

```text
entry_mode = immediate_close
```

原因:

- 这是被过滤前如果按旧逻辑立即进场的表现。
- 可直接判断过滤是否挡掉了坏样本，还是错杀了好样本。

## 输出字段

建议 JSON:

```json
{
  "experiment": "signal_delay1_by_type_guard",
  "summary": {
    "filtered": 805,
    "t3_mean": -2.40,
    "t3_win_rate": 20.0,
    "t3_loss_5pct_rate": 35.0,
    "big_run_5pct_rate": 18.0,
    "big_drop_5pct_rate": 55.0
  },
  "top_winners": [
    {
      "date": "2026-06-01",
      "code": "000001",
      "name": "...",
      "type": "底背驰候选",
      "t3_close_pct": 12.3,
      "confirmations": []
    }
  ],
  "by_type": {},
  "by_confirmations": {},
  "by_distance_bucket": {}
}
```

具体数值以实际跑出来为准。

## 任务拆解

### Task 1: 抽出 filtered sample collector

文件:

- 新增: `chanlun/filtered_sample_audit.py`
- 测试: `tests/test_filtered_sample_audit.py`

要求:

- 能基于 experiment name 识别被过滤样本。
- 复用 `should_drop_pick_for_experiment()`。
- 返回包含 pick 元数据和 return sample 的结构。

### Task 2: 汇总指标和 top winners

文件:

- 修改: `chanlun/filtered_sample_audit.py`
- 测试: `tests/test_filtered_sample_audit.py`

要求:

- 输出 overall summary。
- 输出 top winners，默认按 `t3_close_pct` 降序取前 20。
- 输出 by_type / by_distance_bucket。

### Task 3: 增加 CLI

文件:

- 新增: `scripts/audit_filtered_samples.py`
- 测试: `tests/test_audit_filtered_samples_script.py`

要求:

- 支持 `--experiment`、`--output-json`、`--output-md`。
- 未知 experiment 返回非 0。
- 输出 Markdown 能直接给人看。

### Task 4: 跑真实审计并落结果 MD

文件:

```text
docs/plans/2026-06-27-chanlun-engine-phase6-4-filtered-sample-audit-result.md
```

内容:

- 命令
- summary
- top winners
- 是否存在明显误杀
- 下一步建议: promotion / iterate / 弱趋势冷却

## 验证命令

```bash
python3 -m py_compile \
  chanlun/filtered_sample_audit.py \
  scripts/audit_filtered_samples.py

python3 -m unittest \
  tests.test_filtered_sample_audit \
  tests.test_audit_filtered_samples_script \
  -v

python3 -m unittest discover tests

python3 scripts/audit_filtered_samples.py \
  --experiment signal_delay1_by_type_guard \
  --output-json /tmp/phase6_4_filtered_audit.json \
  --output-md /tmp/phase6_4_filtered_audit.md
```

## 验收标准

- Full tests pass。
- 审计脚本 exit code `0`。
- 输出 filtered summary 和 top winners。
- 能明确判断 `signal_delay1_by_type_guard` 是否存在不可接受误伤。

## 后续

如果误伤可接受:

1. Phase 6.5 做 promotion-ready dual run。
2. 再考虑弱趋势过滤/冷却组合。

如果误伤不可接受:

1. 收紧 `底背驰候选` 的 delay/filter 条件。
2. 对 big-run 被过滤样本提取共同特征。
3. 再做 candidate v2，不 promotion v1。
