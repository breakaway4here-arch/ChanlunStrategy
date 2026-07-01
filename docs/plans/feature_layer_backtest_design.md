# Feature Layer 落地设计 + 回测验证方案（Codex执行版）

> 目标：在不破坏现有缠论与 scoring_engine 的前提下，引入可验证的 Alpha Feature Layer，用于提升选股命中率，并通过回测决定是否正式合入生产评分体系。

---

# 🧠 一、背景与问题

当前系统已具备：

- 缠论结构信号
- 多池选股（main / luojie / acceleration / baseline）
- scoring_engine（opportunity_score）

但仍缺：

> ❗市场环境 + 结构质量 + 动量持续性 的统一表达层

导致问题：

- 同样 score 在不同市场表现不稳定
- 假突破信号无法过滤
- 板块轮动未参与决策

---

# 🚀 二、Feature Layer 总体结构

Feature Layer 位于：

```
pool → feature layer → scoring_engine → ranking
```

不直接参与排序，而是提供统一输入特征。

---

# 📦 三、Feature 分类设计

## 1️⃣ 市场状态类（Market Regime）

### feature:
```
market_regime_score
```

来源：
- 指数趋势（MA20/MA60）
- 宽度（上涨家数 / 总数）
- 波动率

作用：
- 控制是否允许交易
- 调整整体score权重

---

## 2️⃣ 板块强度类（Sector Strength）

### feature:
```
sector_strength_score
```

来源：
- sector_flow
- sector_outflow
- leader concentration

作用：
- 提升主线股权重
- 降低杂毛股评分

---

## 3️⃣ 动量持续性（Momentum Persistence）

### feature:
```
momentum_persistence_score
```

来源：
- 3日/5日/10日同方向
- 价格斜率

作用：
- 过滤单日反弹假信号

---

## 4️⃣ 突破质量（Breakout Quality）

### feature:
```
breakout_quality_score
```

来源：
- 成交量倍数
- 波动率收缩（ATR）
- 是否回踩确认

作用：
- 过滤假突破

---

## 5️⃣ 趋势一致性（Trend Consistency）

### feature:
```
trend_consistency_score
```

来源：
- MA alignment
- MACD direction
- 缠论结构方向一致性

作用：
- 提升趋势统一性选股

---

# 🧩 四、Feature 与现有池关系

## pool 作用不变：

- main：主推信号
- luojie：主题观察
- acceleration：情绪加速
- baseline：结构参考

---

## feature layer 作用：

> 对所有 pool 统一“二次加工”

| Pool | Feature影响 |
|------|------------|
| main | 强增强 |
| acceleration | 强过滤 |
| luojie | 中等增强 |
| baseline | 结构参考 |

---

# ⚙️ 五、接入方式（不改核心逻辑）

## Step 1：新增 feature 计算模块

文件：
```
chanlun/feature_engine.py
```

输出结构：
```python
{
  "market_regime_score": ...,
  "sector_strength_score": ...,
  "momentum_persistence_score": ...,
  "breakout_quality_score": ...,
  "trend_consistency_score": ...
}
```

---

## Step 2：注入 scoring_engine

修改：
```
scoring_engine.compute_opportunity_score()
```

增加：

```
feature_multiplier = f(feature_layer)
final_score = raw_score * feature_multiplier
```

建议初始权重：

- market: 0.3
- sector: 0.25
- momentum: 0.2
- breakout: 0.15
- trend: 0.1

---

# 🧪 六、回测验证设计（关键）

## 🎯 回测目标

判断 Feature Layer 是否提升：

- 命中率（Win Rate）
- 平均收益
- 最大回撤
- 假突破过滤能力

---

## 📊 回测数据结构

生成文件：

```
docs/backtest/feature_backtest.json
```

记录：

```json
{
  "date": "2026-07-01",
  "code": "xxxxxx",
  "pool": "main",
  "baseline_score": 72,
  "feature_score": 81,
  "t1_return": 2.1,
  "t3_return": 4.5,
  "t5_return": 6.8,
  "max_drawdown": -1.2,
  "hit_stop": false
}
```

---

## 📈 回测指标

### 1️⃣ 收益提升
- avg T+3 return
- avg T+5 return

### 2️⃣ 命中率
- positive return ratio

### 3️⃣ 风险控制
- max drawdown
- stop hit rate

### 4️⃣ 过滤能力
- false breakout reduction

---

# 🔬 七、A/B 测试方案

## Control组

当前 scoring_engine

## Test组

scoring_engine + feature layer

---

## 对比方式

```
Same pool → 两套 score → 同一时间窗口回测
```

---

# 🚨 八、合入标准（非常重要）

只有满足以下条件才允许 merge：

- T+3 平均收益提升 > 10%
- false breakout 降低 > 15%
- 回撤不增加

---

# ❌ 九、禁止事项

- 不改缠论核心逻辑
- 不改 K线结构
- 不改 signal 生成
- 不改变 pool 定义

---

# 🎯 十、最终目标

系统升级为：

```
pool → feature layer → scoring_engine → ranking
```

实现：

> 📈 更高命中率 + 更强市场适应性 + 可验证alpha提升

---

# ✔ 结束
