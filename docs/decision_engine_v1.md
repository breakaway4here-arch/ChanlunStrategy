# ChanlunStrategy 决策引擎 v1（结构 + 位置 + 情绪评分系统）

## 1. 目标

在现有选股系统基础上新增一层**可解释决策系统**：

输出每只股票：

- 推荐 / 不推荐
- 总评分
- 三维拆解原因（结构 / 位置 / 情绪）

用于解决核心问题：

> ❌ 追高  
> ❌ 只看涨幅  
> ❌ 无法解释为什么买/不买  

---

## 2. 系统结构

新增模块：

chanlun/
  decision_engine.py

接入点：

run.py → evaluate_stock()
report_generator.py → inject decision result
report_view_model.py → 前端展示

---

## 3. 三大评分体系设计

TOTAL_SCORE = STRUCTURE + POSITION + SENTIMENT

---

# 4. 结构评分（STRUCTURE SCORE）

def calc_structure_score(stock):
    score = 0
    reasons = []

    if stock.get("breakout_structure") is True:
        score += 40
        reasons.append("突破结构")

    trend = stock.get("trend_type")
    if trend == "上升趋势":
        score += 20
        reasons.append("趋势向上")
    elif trend == "震荡":
        score += 5
        reasons.append("震荡结构")
    else:
        score -= 10
        reasons.append("趋势弱")

    if stock.get("pullback_confirmed") is True:
        score += 15
        reasons.append("回踩确认")

    return score, reasons

---

# 5. 位置评分（POSITION SCORE）

def calc_position_score(stock):
    score = 0
    reasons = []

    dist = stock.get("distance_from_breakout_pct", 999)

    if dist <= 5:
        score += 35
        reasons.append("低位启动区")
    elif dist <= 15:
        score += 15
        reasons.append("中位运行")
    elif dist <= 30:
        score -= 10
        reasons.append("偏高位置")
    else:
        score -= 35
        reasons.append("高位追涨风险")

    if stock.get("is_extended_move"):
        score -= 25
        reasons.append("加速末端")

    if stock.get("recent_run_days", 0) >= 5:
        score -= 15
        reasons.append("连续上涨过久")

    return score, reasons

---

# 6. 情绪评分（SENTIMENT SCORE）

def calc_sentiment_score(stock):
    score = 0
    reasons = []

    if stock.get("sector_hot"):
        score += 20
        reasons.append("板块热点")

    if stock.get("volume_expansion"):
        score += 15
        reasons.append("放量启动")

    phase = stock.get("market_phase")
    if phase == "主升":
        score += 25
        reasons.append("主升周期")
    elif phase == "震荡":
        score += 5
        reasons.append("震荡市")
    elif phase == "退潮":
        score -= 30
        reasons.append("退潮期风险")

    if stock.get("overheat"):
        score -= 25
        reasons.append("情绪过热")

    if stock.get("limit_up_recent"):
        score += 10
        reasons.append("涨停情绪强化")

    return score, reasons

---

# 7. 总决策引擎

def evaluate_stock(stock):
    s_score, s_reason = calc_structure_score(stock)
    p_score, p_reason = calc_position_score(stock)
    m_score, m_reason = calc_sentiment_score(stock)

    total = s_score + p_score + m_score

    if p_score < -10:
        decision = "不推荐（高位风险）"
    elif total >= 60:
        decision = "推荐"
    elif total >= 40:
        decision = "观察"
    else:
        decision = "不推荐"

    return {
        "code": stock["code"],
        "name": stock["name"],
        "decision": decision,
        "total_score": total,
        "structure": {"score": s_score, "reasons": s_reason},
        "position": {"score": p_score, "reasons": p_reason},
        "sentiment": {"score": m_score, "reasons": m_reason}
    }
