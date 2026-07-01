# ChanlunStrategy Scoring Engine 重构 PR（Codex 可执行版）

> 目标：统一全系统排序逻辑，消除多评分体系并存问题

---

# 🎯 一、重构目标

## 当前问题

系统存在多套评分：

- watch_score（旧主排序）
- score（局部策略）
- boom_score（加速池）
- luojie score（独立体系）
- 前端 fallback 计算

结果：

- 排序不一致
- view 之间不可比较
- opportunity 无法统一

---

# ✅ 重构目标

唯一评分体系：

opportunity_score（统一排序入口）

所有 view 必须使用该 score。

---

# 🧠 二、设计架构

新增文件：

chanlun/scoring_engine.py

---

核心函数：

compute_opportunity_score(item, source, context)

---

score 结构：

- entry_score
- momentum_score
- signal_score
- market_score
- risk_penalty
- data_penalty

---

# 📊 三、评分模块

## entry_score（0-20）

<=1% : 16
<=2% : 14
<=3% : 11
<=5% : 8
<=8% : 4
>8%  : 0

---

## momentum_score（0-20）

change_pct * 1.5 capped at 20

---

## signal_score（0-25）

- main: 25
- acceleration: 18
- luojie: 15
- confirming: 10
- baseline: 8

---

## market_score（0-15）

- base weight
- multi-source bonus

---

## risk_penalty（0-30）

- 距离过高
- 涨幅过热
- 信号过期
- 确认弱

---

## data_penalty（0-20）

- stale_cache
- missing
- fallback
- unverified

---

# 🔁 四、修改范围

## report_view_model.py

替换 _extract_score()

→ compute_opportunity_score()

---

## run.py

统一排序改为：

opportunity_score

---

## report_generator.py

注入：

item["opportunity_score"]

---

## report-v2.js

移除 fallback ranking

---

# 🧪 五、验收标准

- main / highlights / baseline 统一排序
- luojie / boom / acceleration 支持 score
- 不再存在多评分体系
- UI 不依赖 fallback

---

# 🚨 六、禁止修改

- 不改缠论策略
- 不改K线逻辑
- 不改信号生成
- 不改UI结构

---

# 📦 七、Codex Task拆分

Task 1 scoring_engine.py
Task 2 report_view_model
Task 3 run.py
Task 4 report_generator
Task 5 JS migration

---

# 🎯 最终目标

唯一排序源：

opportunity_score

系统结构：

signal → scoring engine → workspace → UI
