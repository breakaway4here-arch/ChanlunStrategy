"""Research framework utility functions.

当前阶段先实现可测试的纯函数化版本，避免外部依赖。
"""

from __future__ import annotations

from typing import Any


def _to_float_list(values: Any) -> list[float]:
    """将可迭代输入转换成 float 列表，过滤异常值。"""
    if values is None:
        return []
    if isinstance(values, (list, tuple)):
        raw = values
    elif hasattr(values, "__iter__") and not isinstance(values, (str, bytes)):
        raw = list(values)
    else:
        return []

    out: list[float] = []
    for value in raw:
        try:
            out.append(float(value))
        except (TypeError, ValueError):
            continue
    return out


def _moving_average(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return None
    return round(sum(values[-window:]) / window, 4)


def _safe_pct(curr: float | None, ref: float | None) -> float | None:
    if curr is None or ref in (None, 0):
        return None
    return round((curr - ref) / ref * 100, 2)


def _avg(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def calc_gf_dma_health(stock: dict) -> dict:
    """Calculate GF-DMA health object for a stock candidate.

    仅使用 stock["closes"] 与 stock["volumes"] 推断趋势与风险特征，不发起网络调用。
    若 K 线长度不足 200，ma200 为 None 并标记 data_quality 降级。
    """
    closes = _to_float_list(stock.get("closes"))
    volumes = _to_float_list(stock.get("volumes"))
    n = len(closes)

    result: dict[str, Any] = {
        "code": stock.get("code", ""),
        "name": stock.get("name", ""),
        "label": "数据不足",
        "score": 0.0,
        "trend_stage": "insufficient",
        "ma": {
            "ma20": None,
            "ma50": None,
            "ma100": None,
            "ma200": None,
        },
        "distance_pct": {
            "vs_ma20": None,
            "vs_ma50": None,
            "vs_ma100": None,
            "vs_ma200": None,
        },
        "alignment": "insufficient",
        "extension_level": "normal",
        "pullback_health": "unknown",
        "fomo_risk": "low",
        "risk_flags": [],
        "positive_flags": [],
        "summary": "K线样本不足，未形成可用趋势评分。",
        "data_quality": "insufficient",
    }

    if n < 5:
        return result

    current_price = closes[-1]
    prev_price = closes[-2] if n > 1 else current_price

    ma20 = _moving_average(closes, 20)
    ma50 = _moving_average(closes, 50)
    ma100 = _moving_average(closes, 100)
    ma200 = _moving_average(closes, 200)

    result["ma"]["ma20"] = ma20
    result["ma"]["ma50"] = ma50
    result["ma"]["ma100"] = ma100
    result["ma"]["ma200"] = ma200

    if n >= 200:
        result["data_quality"] = "full"
    elif n >= 50:
        result["data_quality"] = "insufficient_200"
    else:
        result["data_quality"] = "insufficient"

    vs_ma20 = _safe_pct(current_price, ma20)
    vs_ma50 = _safe_pct(current_price, ma50)
    vs_ma100 = _safe_pct(current_price, ma100)
    vs_ma200 = _safe_pct(current_price, ma200)
    result["distance_pct"]["vs_ma20"] = vs_ma20
    result["distance_pct"]["vs_ma50"] = vs_ma50
    result["distance_pct"]["vs_ma100"] = vs_ma100
    result["distance_pct"]["vs_ma200"] = vs_ma200

    # 趋势排列
    if ma100 is not None and current_price < ma100:
        alignment = "broken"
    elif ma50 is not None and current_price < ma50:
        alignment = "weak"
    elif (
        ma20 is not None
        and ma50 is not None
        and ma100 is not None
        and current_price > ma20 > ma50 > ma100
        and (ma200 is None or ma100 > ma200)
    ):
        alignment = "bullish"
    elif (
        ma20 is not None and ma50 is not None
        and current_price > ma20 > ma50
    ):
        alignment = "repairing"
    else:
        alignment = "neutral"
    result["alignment"] = alignment

    # 乖离 / 过热
    if vs_ma20 is None:
        extension = "normal"
    elif vs_ma20 <= 8:
        extension = "normal"
    elif vs_ma20 <= 15:
        extension = "warm"
    else:
        extension = "overheated"
    result["extension_level"] = extension
    if extension == "warm":
        result["risk_flags"].append("价格偏离20日线中等，回撤容忍度下降")
    elif extension == "overheated":
        result["risk_flags"].append("价格偏离20日线较大，关注过热与追涨风险")

    # 回调健康
    if ma50 is not None and current_price < ma50:
        pullback = "broken_down"
    elif ma20 is not None and current_price < ma20:
        pullback = "cautionary"
    elif ma20 is not None and current_price > ma20:
        pullback = "healthy"
    else:
        pullback = "unknown"
    result["pullback_health"] = pullback

    # 成交量与价格协同
    volume_ratio = None
    if len(volumes) >= 25:
        recent_avg = _avg(volumes[-5:])
        prev_avg = _avg(volumes[-25:-5])
        if recent_avg is not None and prev_avg and prev_avg > 0:
            volume_ratio = round(recent_avg / prev_avg, 2)

    is_up = current_price >= prev_price
    if volume_ratio is not None and volume_ratio > 1.2 and is_up:
        result["positive_flags"].append(f"放量上攻，量比{volume_ratio:.2f}")
    if volume_ratio is not None and volume_ratio > 1.5 and vs_ma20 is not None and vs_ma20 > 15:
        result["risk_flags"].append("放量且远离20日线，存在过热继续扩量风险")
    if (
        volume_ratio is not None
        and not is_up
        and current_price < prev_price
        and volume_ratio > 1.2
    ):
        result["risk_flags"].append("下跌放量，回撤风险上升")

    # 评分（基础分50）
    score = 50
    if alignment == "bullish":
        score += 20
    elif alignment == "repairing":
        score += 8
    elif alignment == "weak":
        score -= 12
    elif alignment == "broken":
        score -= 20
    if extension == "normal" and vs_ma20 is not None and vs_ma20 <= 15:
        score += 10
    if volume_ratio is not None and volume_ratio > 1.2 and is_up:
        score += 10

    if pullback == "healthy":
        score += 8
    elif pullback == "broken_down":
        score -= 8

    if vs_ma20 is not None and vs_ma20 > 15:
        score -= 15
    if vs_ma50 is not None and vs_ma50 > 30:
        score -= 20
    if ma50 is not None and current_price < ma50:
        score -= 20
    if ma100 is not None and current_price < ma100:
        score -= 30
    if ma200 is not None and current_price < ma200:
        score -= 10

    # 风险等级
    if vs_ma20 is not None and vs_ma20 > 30:
        result["fomo_risk"] = "high"
    elif vs_ma20 is not None and vs_ma20 > 15:
        result["fomo_risk"] = "medium"
    elif pullback == "broken_down" and volume_ratio is not None and volume_ratio > 1.2:
        result["fomo_risk"] = "high"
    else:
        result["fomo_risk"] = "low"

    score = max(0.0, min(100.0, float(score)))
    result["score"] = round(score, 1)
    if (
        result["fomo_risk"] == "high"
        and result["alignment"] in {"bullish", "repairing", "neutral"}
        and result["score"] >= 40
    ):
        label = "强势过热"
    elif result["score"] >= 80:
        label = "强势健康"
    elif result["score"] >= 65:
        label = "趋势健康"
    elif result["score"] >= 50:
        label = "中性观察"
    elif result["score"] >= 35:
        label = "走势转弱"
    else:
        label = "结构破坏"
    result["label"] = label

    # 趋势阶段映射
    result["trend_stage"] = {
        "bullish": "uptrend",
        "repairing": "repairing",
        "neutral": "neutral",
        "weak": "weak",
        "broken": "broken",
        "insufficient": "insufficient",
    }.get(alignment, "neutral")

    # 正向标签
    if alignment == "bullish" and all(v is not None for v in (ma20, ma50, ma100)):
        result["positive_flags"].append("价格位于20/50/100日均线之上")
        result["positive_flags"].append("20/50/100日均线多头排列")
    if alignment == "repairing":
        result["positive_flags"].append("价格位于MA20之上，具修复属性")
    if pullback == "healthy":
        result["positive_flags"].append("回调后仍在MA20/MA50上方")

    if not result["positive_flags"] and result["fomo_risk"] == "low":
        result["positive_flags"].append("趋势结构尚未触发明显风险")

    if result["risk_flags"]:
        risk_part = result["risk_flags"][0] if len(result["risk_flags"]) == 1 else "；".join(result["risk_flags"][:2])
    else:
        risk_part = "未见明显短线异动"

    if alignment == "bullish":
        trend_part = "均线体系保持多头"
    elif alignment == "repairing":
        trend_part = "均线由弱转强，修复中"
    elif alignment == "weak":
        trend_part = "跌破MA50"
    elif alignment == "broken":
        trend_part = "跌破MA100，结构偏弱"
    else:
        trend_part = "短线波动中"
    result["summary"] = f"{trend_part}，{risk_part}，回撤{result['pullback_health']}。"
    if extension == "overheated":
        result["summary"] += " 当前偏离幅度较大，回踩验证更关键。"

    return result
