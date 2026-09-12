"""
评分模型 — 纯净版和融合版两套评分函数。
"""

import math
import re
from collections.abc import Mapping
import numpy as np
from config import (
    PURE_WEIGHT_DIVERGENCE, PURE_WEIGHT_RESONANCE, PURE_WEIGHT_POSITION,
    FUSION_WEIGHT_DIVERGENCE, FUSION_WEIGHT_RESONANCE, FUSION_WEIGHT_POSITION,
    FUSION_WEIGHT_SECTOR, FUSION_WEIGHT_VOLUME,
    TOP_SECTOR_COUNT,
)

SIGNAL_TIER_BASE = {
    "formal": 100,
    "candidate": 75,
    "reference": 30,
    "blocked": 0,
}

BUY_TYPE_PRIORITY = {
    "强势启动候选": 0,
    "三买": 1,
    "二买": 2,
    "一买": 3,
    "三买候选": 4,
    "二买候选": 5,
    "盘整低吸候选": 6,
    "中枢低吸候选": 7,
    "底背驰候选": 8,
}


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
    normalized_sectors = normalize_sector_rank_map(sector_rank_map)
    return _score_fusion_with_normalized_sectors(stock, normalized_sectors)


def _score_fusion_with_normalized_sectors(stock, normalized_sectors):
    """Score one fusion row after its sector contract was normalized once."""
    # 1-3: 与纯净版相同
    div_score = _score_divergence_clarity(stock)
    resonance_score = _score_resonance(stock)
    position_score = _score_trend_position(stock)

    # 4. 板块强度
    sector_score = _score_sector_strength(
        stock,
        normalized_sectors,
        normalized=True,
    )

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


def _score_sector_strength(stock, sector_rank_map=None, *, normalized=False):
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

    normalized_sectors = (
        sector_rank_map
        if normalized
        else normalize_sector_rank_map(sector_rank_map)
    )
    if not normalized_sectors:
        return 40

    # 查找板块排名
    rank = None
    for s in normalized_sectors:
        if s["name"] == sector:
            rank = s["sector_rank"]
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


def _finite_positive_integer(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0 or not number.is_integer():
        return None
    return int(number)


def normalize_sector_rank_map(sector_rank_map, *, return_diagnostics=False):
    """Normalize one ordered sector ranking list into unique explicit ranks.

    The market provider's list order is the only fallback order.  Mapping
    rows without a usable name are ignored.  A later duplicate name replaces
    an earlier row only when it carries a valid rank where the earlier row did
    not.  Conflicting valid ranks for the same name are discarded together
    and assigned a conservative ordered fallback; they are never resolved by
    choosing the smaller (and potentially more favorable) value.  Set
    ``return_diagnostics=True`` to retain the conflict records.
    """
    return _normalize_sector_rank_map(sector_rank_map, return_diagnostics=return_diagnostics)


def _normalize_sector_rank_map(sector_rank_map, *, return_diagnostics=False):
    """Implementation shared by the scoring path and diagnostic callers."""
    if sector_rank_map is None:
        result = None
        return (result, []) if return_diagnostics else result
    if not isinstance(sector_rank_map, (list, tuple)):
        # A mapping/dict has no ranking contract here.  Do not silently turn
        # its insertion order into strategy evidence.
        result = None
        diagnostics = [{
            "type": "invalid_sector_rank_map",
            "action": "neutral_score",
        }]
        return (result, diagnostics) if return_diagnostics else result

    diagnostics = []
    selected = []
    name_to_index = {}
    for row in sector_rank_map:
        if not isinstance(row, Mapping):
            continue
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        candidate = dict(row)
        candidate["name"] = name
        candidate_rank = _finite_positive_integer(candidate.get("sector_rank"))
        existing_index = name_to_index.get(name)
        if existing_index is None:
            selected.append({
                "row": candidate,
                "rank": candidate_rank,
                "conflict": False,
            })
            name_to_index[name] = len(selected) - 1
            continue

        existing = selected[existing_index]
        existing_rank = existing["rank"]
        if existing["conflict"]:
            continue
        if existing_rank is None and candidate_rank is not None:
            existing["row"] = candidate
            existing["rank"] = candidate_rank
        elif (
            existing_rank is not None
            and candidate_rank is not None
            and candidate_rank != existing_rank
        ):
            existing["rank"] = None
            existing["conflict"] = True
            diagnostics.append({
                "type": "duplicate_name_rank_conflict",
                "name": name,
                "ranks": [existing_rank, candidate_rank],
                "action": "ordered_fallback",
            })

    used = set()
    unresolved = []
    rank_owners = {}
    for index, item in enumerate(selected):
        row = item["row"]
        explicit_rank = item["rank"]
        if explicit_rank is not None and explicit_rank not in used:
            row["sector_rank"] = explicit_rank
            row["sector_rank_source"] = "explicit"
            used.add(explicit_rank)
            rank_owners[explicit_rank] = row["name"]
        else:
            if explicit_rank is not None:
                diagnostics.append({
                    "type": "duplicate_explicit_rank",
                    "name": row["name"],
                    "rank": explicit_rank,
                    "kept_name": rank_owners.get(explicit_rank, ""),
                    "action": "ordered_fallback",
                })
            unresolved.append((index, item))

    for index, item in unresolved:
        row = item["row"]
        next_rank = index + 1
        if item["conflict"] and next_rank <= 1:
            next_rank = 2
        while next_rank in used:
            next_rank += 1
        row["sector_rank"] = next_rank
        row["sector_rank_source"] = (
            "ordered_fallback_conflict"
            if item["conflict"] else "ordered_fallback"
        )
        used.add(next_rank)

    result = [item["row"] for item in selected]
    return (result, diagnostics) if return_diagnostics else result


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


def _sector_rank_diagnostics_for_name(diagnostics, name):
    return [
        dict(item) for item in (diagnostics or [])
        if not name or item.get("name") in (None, "", name)
    ]


def _rewrite_rank_label(label, rank):
    """Keep generated TOP labels aligned with the rank used for scoring."""
    if not isinstance(label, str) or not label.strip():
        return label
    return re.sub(r"TOP\s*\d+", "TOP{}".format(rank), label, count=1)


def _attach_sector_rank_contract(pick, normalized_sectors, diagnostics):
    """Write the exact normalized ranking contract consumed by fusion score."""
    if not isinstance(pick, dict):
        return
    sector = str(pick.get("sector") or "").strip()
    matching = next(
        (
            row for row in (normalized_sectors or [])
            if row.get("name") == sector
        ),
        None,
    )
    if matching is not None:
        rank = matching.get("sector_rank")
        pick["sector_rank"] = rank
        pick["sector_rank_used"] = rank
        pick["sector_rank_source"] = matching.get(
            "sector_rank_source", ""
        )
        relevant = _sector_rank_diagnostics_for_name(diagnostics, sector)
        pick["sector_rank_diagnostics"] = relevant
        label = pick.get("sector_strength_label")
        if not label:
            label = matching.get("sector_strength_label", "")
        rewritten = _rewrite_rank_label(label, rank)
        if rewritten:
            pick["sector_strength_label"] = rewritten
        return

    # The map was supplied but did not contain this stock's sector.  Preserve
    # any independently verified metadata while making the score's absence
    # explicit; never manufacture a rank from a stock dictionary's order.
    pick["sector_rank_used"] = None
    invalid_map = any(
        item.get("type") == "invalid_sector_rank_map"
        for item in diagnostics or []
        if isinstance(item, dict)
    )
    pick["sector_rank_source"] = (
        "invalid_rank_map" if invalid_map else "not_in_rank_map"
    )
    pick["sector_rank_diagnostics"] = (
        _sector_rank_diagnostics_for_name(diagnostics, sector)
        + ([{
            "type": "sector_not_in_rank_map",
            "name": sector,
            "action": "neutral_score",
        }] if not invalid_map else [])
    )


def apply_scores(picks, version="pure", sector_rank_map=None):
    """
    为一组 picks 评分并附加 score 字段。
    排序: formal > candidate, then type priority, then score.
    """
    score_func = score_pure if version == "pure" else score_fusion
    normalized_sectors = None
    sector_rank_diagnostics = []
    if version == "fusion" and sector_rank_map is not None:
        normalized_sectors, sector_rank_diagnostics = (
            normalize_sector_rank_map(
                sector_rank_map,
                return_diagnostics=True,
            )
        )
    for pick in picks:
        if version == "fusion":
            if sector_rank_map is not None:
                _attach_sector_rank_contract(
                    pick,
                    normalized_sectors,
                    sector_rank_diagnostics,
                )
            pick["score"] = _score_fusion_with_normalized_sectors(
                pick,
                normalized_sectors,
            )
        else:
            pick["score"] = score_func(pick)

    def _sort_key(p):
        bp = p.get("best_buy_point", {})
        tier = bp.get("tier", "reference")
        tier_order = 0 if tier == "formal" else 1 if tier == "candidate" else 2
        type_order = BUY_TYPE_PRIORITY.get(bp.get("type", ""), 9)
        score = p.get("score", 0)
        return (tier_order, type_order, -score)

    picks.sort(key=_sort_key)
    return picks
