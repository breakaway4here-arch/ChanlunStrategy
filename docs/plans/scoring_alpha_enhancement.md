# Alpha Feature Enhancement + Backtest Plan（Codex执行版）

> 目标：在不破坏现有 scoring_engine 结构的前提下，引入可回测的 Alpha 增强因子，用于提升选股命中率（胜率 + 收益 + 回撤控制）。

---

# 🧠 一、核心原则（非常重要）

本次改动必须满足：

- ❌ 不重构 scoring_engine 架构
- ❌ 不改变 opportunity_score 主公式结构
- ❌ 不改变现有池（main / luojie / acceleration / baseline）定义
- ✔ 仅在现有 score 上增加“可控增强因子”
- ✔ 所有增强必须可回测对比

---

# 🚀 二、可接入 Alpha Features（当前系统可直接加）

## 1️⃣ 市场状态因子（market_regime_factor）

### 接入位置：
- scoring_engine.compute_opportunity_score
- 或作为 final multiplier

### 定义：

```text
market_regime_factor
= index_trend_score + breadth_score
```

### 规则：
- 上证 > MA20 → +权重
- 宽度（上涨家数比例）> 0.6 → +权重
- 低于阈值 → 降权

### 作用：
- 过滤熊市/震荡假信号

---

## 2️⃣ 板块强度因子（sector_strength_factor）

### 接入位置：
- _score_market 或独立 multiplier

### 定义：

```text
sector_strength_factor
= sector_flow_strength + leader_concentration
```

### 作用：
- 提升主线板块选股命中率
- 降低杂毛股权重

---

## 3️⃣ 动量持续性因子（momentum_persistence）

### 接入位置：
- _score_momentum

### 定义：
- 3日 / 5日 / 10日同方向
- slope > 0

### 作用：
- 过滤单日脉冲行情

---

## 4️⃣ 突破质量因子（breakout_quality）

### 接入位置：
- entry_score 或 risk_penalty

### 定义：
- 放量倍数
- ATR收缩
- 是否回踩确认

### 作用：
- 降低假突破

---

## 5️⃣ 趋势一致性因子（trend_consistency）

### 接入位置：
- signal_score 或 entry_score

### 定义：
- MA alignment
- MACD方向一致
- 缠论结构一致性

---

# 🧩 三、接入方式（必须保持兼容）

## 方式A（推荐）

在 scoring_engine 内增加：

```python
alpha_multiplier = f(features)
final_score = base_score * alpha_multiplier
```

---

## 方式B（更保守）

仅作为加分项：

```python
final_score = base_score + alpha_bonus
```

---

# 📊 四、回测设计（关键）

## 🎯 目标
验证 Alpha Features 是否真正提升：

- 命中率（Win Rate）
- 平均收益
- 最大回撤
- 假突破过滤能力

---

# 🧪 五、回测方法（必须A/B对比）

## Control组（基线）

```text
current scoring_engine
```

---

## Treatment组（增强版）

```text
scoring_engine + alpha features
```

---

## 对比方式

同一时间窗口、同一股票池：

- main
- luojie
- acceleration

分别计算：

- T+1 return
- T+3 return
- T+5 return
- max drawdown

---

# 📈 六、回测数据结构

生成文件：

```
docs/backtest/alpha_feature_backtest.json
```

格式：

```json
{
  "date": "2026-07-01",
  "code": "xxxxxx",
  "pool": "main",
  "baseline_score": 72,
  "alpha_score": 81,
  "t1_return": 2.1,
  "t3_return": 4.8,
  "t5_return": 6.5,
  "max_drawdown": -1.2,
  "hit_stop": false
}
```

---

# 📊 七、核心评估指标

## 1️⃣ 收益提升

- avg T+3 return
- avg T+5 return

## 2️⃣ 胜率提升

- positive return ratio

## 3️⃣ 风险控制

- max drawdown
- stop hit rate

## 4️⃣ 假信号过滤

- breakout failure rate

---

# 🚨 八、合入标准（非常重要）

只有满足以下条件才允许 merge：

- T+3 平均收益提升 ≥ 10%
- 假突破下降 ≥ 15%
- 回撤不增加

---

# ❌ 九、禁止事项

- ❌ 不改缠论核心逻辑
- ❌ 不改K线结构
- ❌ 不改signal生成
- ❌ 不拆 scoring_engine 架构

---

# 🎯 十、最终目标

系统变为：

```text
pool → feature enhancement → scoring_engine → ranking
```

实现：

> 更高胜率 + 更强市场适应性 + 可验证alpha提升
