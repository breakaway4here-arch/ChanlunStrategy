"""
评分模型 — 纯净版和融合版两套评分函数。
"""

import numpy as np
from config import (
    PURE_WEIGHT_DIVERGENCE, PURE_WEIGHT_RESONANCE, PURE_WEIGHT_POSITION,
    FUSION_WEIGHT_DIVERGENCE, FUSION_WEIGHT_RESONANCE, FUSION_WEIGHT_POSITION,
    FUSION_WEIGHT_SECTOR, FUSION_WEIGHT_VOLUME,
    TOP_SECTOR_COUNT,
)


def score_pure(stock):
    """
    纯净版评分：
    - 背驰清晰度 (40%)
    - 级别共振程度 (35%)
    - 走势位置得分 (25%)
    返回: 0-100 分
    """
    # 1. 背驰清晰度
    div_score = _score_divergence_clarity(stock)

    # 2. 级别共振
    resonance_score = _score_resonance(stock)

    # 3. 走势位置
    position_score = _score_trend_position(stock)

    total = (
        div_score * PURE_WEIGHT_DIVERGENCE
        + resonance_score * PURE_WEIGHT_RESONANCE
        + position_score * PURE_WEIGHT_POSITION
    )
    return round(total, 1)


def score_fusion(stock, sector_rank_map=None):
    """
    融合版评分：
    - 背驰清晰度 (30%)
    - 级别共振程度 (25%)
    - 走势位置得分 (20%)
    - 板块强度 (15%)
    - 量能配合 (10%)
    返回: 0-100 分
    """
    # 1-3: 与纯净版相同
    div_score = _score_divergence_clarity(stock)
    resonance_score = _score_resonance(stock)
    position_score = _score_trend_position(stock)

    # 4. 板块强度
    sector_score = _score_sector_strength(stock, sector_rank_map)

    # 5. 量能配合
    volume_score = _score_volume_confirmation(stock)

    total = (
        div_score * FUSION_WEIGHT_DIVERGENCE
        + resonance_score * FUSION_WEIGHT_RESONANCE
        + position_score * FUSION_WEIGHT_POSITION
        + sector_score * FUSION_WEIGHT_SECTOR
        + volume_score * FUSION_WEIGHT_VOLUME
    )
    return round(total, 1)


# ============================================================
# 评分子项
# ============================================================

def _score_divergence_clarity(stock):
    """
    背驰清晰度评分 (0-100)
    - 面积比越小（背离越明显）得分越高
    - MACD柱子背离额外加分
    """
    div = stock.get("divergence")
    if div is None or not div.get("is_divergence"):
        return 20  # 无背驰，基础分

    area_ratio = div.get("area_ratio", 1.0)
    hist_div = div.get("hist_divergence", False)

    # 面积比：0.3以下=100分，0.3-0.5=80分，0.5-0.7=60分，0.7-0.85=40分，0.85+=20分
    if area_ratio < 0.3:
        score = 100
    elif area_ratio < 0.5:
        score = 80
    elif area_ratio < 0.7:
        score = 60
    elif area_ratio < 0.85:
        score = 40
    else:
        score = 20

    # MACD柱子背离加10分
    if hist_div:
        score = min(100, score + 10)

    return score


def _score_resonance(stock):
    """
    级别共振评分 (0-100)
    - 日线+30分钟强共振: 100
    - 中等共振: 70
    - 弱共振: 40
    - 无共振: 10
    """
    resonance = stock.get("resonance", {})
    level = resonance.get("level", "无")

    level_scores = {"强": 100, "中": 70, "弱": 40, "无": 10}
    return level_scores.get(level, 10)


def _score_trend_position(stock):
    """
    走势位置得分 (0-100)
    - 买点刚形成（最近2-3根K线内）: 90+
    - 买点形成较久（>10根K线前）: 50以下

    bp_idx 来自分型 _orig_idx()（原始K线索引），closes 也是原始未合并的K线数组，
    两者使用同一坐标系，distance = n - bp_idx 含义正确。
    """
    best_bp = stock.get("best_buy_point", {})
    bp_idx = best_bp.get("index", 0)
    closes = stock.get("closes", [])

    if len(closes) == 0:
        return 50

    n = len(closes)
    distance = n - bp_idx  # 买点距离最后一根K线的距离

    if distance <= 2:
        return 95
    elif distance <= 5:
        return 80
    elif distance <= 10:
        return 60
    elif distance <= 20:
        return 40
    else:
        return 20


def _score_sector_strength(stock, sector_rank_map=None):
    """
    板块强度评分 (0-100)
    - TOP1板块: 100
    - TOP5: 80
    - TOP10: 60
    - TOP20: 40
    """
    sector = stock.get("sector", "")
    if not sector or sector_rank_map is None:
        return 40

    # 查找板块排名
    rank = None
    for i, s in enumerate(sector_rank_map):
        if s["name"] == sector:
            rank = i + 1
            break

    if rank is None:
        return 30

    if rank <= 1:
        return 100
    elif rank <= 3:
        return 85
    elif rank <= 5:
        return 70
    elif rank <= 10:
        return 55
    elif rank <= 20:
        return 40
    return 25


def _score_volume_confirmation(stock):
    """
    量能配合评分 (0-100)
    - 近5日量能持续放大: 90+
    - 量能平稳: 60
    - 量能萎缩: 30
    """
    volumes = stock.get("volumes", [])
    if len(volumes) < 10:
        return 50

    recent_5 = volumes[-5:]
    prev_5 = volumes[-10:-5]

    avg_recent = np.mean(recent_5) if len(recent_5) > 0 else 0
    avg_prev = np.mean(prev_5) if len(prev_5) > 0 else 0

    if avg_prev == 0:
        return 50

    ratio = avg_recent / avg_prev

    # 量能趋势
    if ratio > 1.5:
        return 95   # 大幅放量
    elif ratio > 1.2:
        return 80   # 温和放量
    elif ratio > 0.9:
        return 60   # 量能平稳
    elif ratio > 0.6:
        return 40   # 缩量
    else:
        return 20   # 明显缩量


def apply_scores(picks, version="pure", sector_rank_map=None):
    """
    为一组 picks 评分并附加 score 字段。
    返回按评分降序排列的列表。
    """
    score_func = score_pure if version == "pure" else score_fusion
    for pick in picks:
        if version == "fusion":
            pick["score"] = score_func(pick, sector_rank_map)
        else:
            pick["score"] = score_func(pick)

    picks.sort(key=lambda x: x.get("score", 0), reverse=True)
    return picks
