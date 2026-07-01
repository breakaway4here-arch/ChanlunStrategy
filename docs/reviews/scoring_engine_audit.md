# Scoring Engine 全量审计报告（Codex 执行前 Review）

> 审计目标：验证 scoring_engine 重构是否真正成为唯一排序入口，并识别残留多评分路径

---

# 🧠 一、结论摘要（重要）

当前系统已完成 80% scoring 收敛，但仍存在：

> ⚠️ **多评分入口残留 + 排序未完全收敛**

系统处于：

- 🟢 scoring_engine 已成型
- 🟡 但未成为唯一 truth source

---

# 🔍 二、核心问题清单

## ❗问题1：排序入口未完全统一

### 现状
run.py 中仍存在：

- apply_scores 结果参与排序
- 旧 score / watch_score 仍在部分 view 使用

### 风险

- main / luojie / acceleration 排序可能不一致
- highlight 与 baseline 不保证一致性

---

## ❗问题2：opportunity_score 未成为唯一排序键

### 现状

虽然 scoring_engine 已引入：

```
opportunity_score
```

但：

- 未在 run.py 全面接管排序
- view_model 仍可能输出 legacy score

---

## ❗问题3：双层评分结构仍存在

当前结构：

```
report_view_model → metrics
scorer/scoring_engine → score
run.py → sorting
```

### 问题

> ❌ scoring_engine 不是唯一决策层

---

## ❗问题4：risk / data penalty 存在潜在重复路径

### 风险点

- run.py market_temperature 已计算 risk
- scoring_engine 也计算 risk_penalty
- view_model 可能再次推导

👉 可能导致：

> ❌ 同一风险被多次扣分

---

## ❗问题5：luojie / acceleration 仍存在非统一 schema

### 现状

- main / baseline → structured scoring
- luojie / acceleration → 半独立结构

### 风险

> ❌ 不同 view 无法真正横向比较

---

# 🧪 三、验证结果

## ✔ 已正确部分

- opportunity_score 已实现完整公式
- entry / momentum / signal / market 已结构化
- data_quality penalty 已引入
- market_temperature 已后端化

---

## ❌ 未完成部分

- scoring_engine 未完全接管排序
- run.py 未完全去除旧 score
- JS fallback ranking 仍可能存在

---

# ⚠️ 四、架构风险等级

| 模块 | 状态 |
|------|------|
| scoring_engine | 🟢 完成 |
| metric unify | 🟢 完成 |
| ranking unify | ❌ 未完成 |
| single source of truth | ❌ 未达成 |

---

# 🚨 五、必须修复项（Codex 执行优先级）

## P0（关键）

- run.py 必须只使用 opportunity_score 排序
- 禁止 watch_score / score 参与排序

---

## P1

- 删除 view_model 中任何 ranking fallback

---

## P2

- luojie / acceleration 统一 schema
- 强制加入 opportunity_score

---

## P3

- risk_penalty 统一来源（避免重复扣分）

---

# 🧭 六、推荐最终结构

```
signal
  ↓
scoring_engine (唯一决策层)
  ↓
workspace view
  ↓
frontend render
```

---

# 🎯 七、最终结论

当前系统已经：

> 🟡 从“多策略系统”升级到“半统一评分系统”

但还未达到：

> 🔴 single-source scoring architecture

---

# 📌 八、Codex 下一步指令建议

必须执行：

1. 强制 run.py 排序收敛
2. 移除所有 legacy score fallback
3. luojie / acceleration schema 对齐
4. 禁止多评分入口

---

# ✔ 审计完成