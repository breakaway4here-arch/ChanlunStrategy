"""Compare helpers for ChanLun engine outputs."""


def _round_float(value, digits=6):
    if value is None:
        return None
    return round(float(value), digits)


def _round_array(values, digits=6):
    if values is None:
        return None
    return [_round_float(v, digits) for v in values]


def _serialize_pivot(pivot):
    return {
        "ZD": _round_float(pivot.ZD),
        "ZG": _round_float(pivot.ZG),
        "start_idx": pivot.start_idx,
        "end_idx": pivot.end_idx,
        "level": pivot.level,
    }


def serialize_chan_result(result):
    if result is None:
        return None

    return {
        "code": result.code,
        "name": result.name,
        "counts": {
            "fractals": len(result.fractals),
            "strokes": len(result.strokes),
            "segments": len(result.segments),
            "pivots": len(result.pivots),
            "buy_points": len(result.buy_points),
            "sell_points": len(result.sell_points),
            "swing_waves": len(result.swing_waves),
            "swing_zones": len(result.swing_zones),
        },
        "fractals": [
            {
                "type": f.type,
                "index": f.index,
                "price": _round_float(f.price),
            }
            for f in result.fractals
        ],
        "strokes": [
            {
                "start_idx": s.start_idx,
                "end_idx": s.end_idx,
                "start_price": _round_float(s.start_price),
                "end_price": _round_float(s.end_price),
                "direction": s.direction,
            }
            for s in result.strokes
        ],
        "segments": [
            {
                "start_idx": s.start_idx,
                "end_idx": s.end_idx,
                "direction": s.direction,
                "high": _round_float(s.high),
                "low": _round_float(s.low),
                "confirmed": s.confirmed,
                "destroyed_by_idx": s.destroyed_by_idx,
            }
            for s in result.segments
        ],
        "pivots": [_serialize_pivot(p) for p in result.pivots],
        "trend_type": result.trend_type,
        "divergence": None if result.divergence is None else {
            "type": result.divergence.get("type"),
            "is_divergence": result.divergence.get("is_divergence"),
            "area_ratio": _round_float(result.divergence.get("area_ratio")),
            "hist_divergence": _round_float(result.divergence.get("hist_divergence")),
        },
        "buy_points": [
            {
                "type": p["type"],
                "tier": p.get("tier"),
                "index": p["index"],
                "price": _round_float(p["price"]),
                "strength": p.get("strength"),
                "date": p.get("date"),
                "reason": p.get("reason"),
            }
            for p in result.buy_points
        ],
        "sell_points": [
            {
                "type": p["type"],
                "tier": p.get("tier"),
                "index": p["index"],
                "price": _round_float(p["price"]),
                "strength": p.get("strength"),
                "date": p.get("date"),
                "reason": p.get("reason"),
            }
            for p in result.sell_points
        ],
        "macd_tail": {
            "dif": _round_array(result.macd_dif[-5:]),
            "dea": _round_array(result.macd_dea[-5:]),
            "hist": _round_array(result.macd_hist[-5:]),
        },
        "swing_waves": [
            {
                "start_idx": w["start_idx"],
                "end_idx": w["end_idx"],
                "start_price": _round_float(w["start_price"]),
                "end_price": _round_float(w["end_price"]),
                "direction": w["direction"],
            }
            for w in result.swing_waves
        ],
        "swing_zones": [_serialize_pivot(p) for p in result.swing_zones],
    }


def _diff_values(path, left, right, differences):
    if left == right:
        return
    if isinstance(left, dict) and isinstance(right, dict):
        keys = sorted(set(left) | set(right))
        for key in keys:
            _diff_values(path + [str(key)], left.get(key), right.get(key), differences)
        return
    differences.append({
        "field": ".".join(path),
        "legacy": left,
        "candidate": right,
    })


def compare_chan_results(legacy, candidate):
    legacy_payload = serialize_chan_result(legacy)
    candidate_payload = serialize_chan_result(candidate)
    differences = []
    _diff_values([], legacy_payload, candidate_payload, differences)

    changed_fields = []
    for diff in differences:
        top = diff["field"].split(".", 1)[0] if diff["field"] else "result"
        if top not in changed_fields:
            changed_fields.append(top)

    return {
        "equal": not differences,
        "summary": {
            "changed_fields": changed_fields,
            "difference_count": len(differences),
        },
        "differences": differences,
    }
