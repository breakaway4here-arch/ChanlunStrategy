"""Generate deterministic ChanLun legacy snapshot fixtures.

Only run this intentionally when accepting a deliberate legacy behavior change.
Do not use this script to make failing snapshot tests pass without reviewing the diff.
"""

import json
import os
import numpy as np
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from chanlun.chan_engine import analyze


def _round_float(value, digits=6):
    if value is None:
        return None
    return round(float(value), digits)


def _round_array(values, digits=6):
    if values is None:
        return None
    return [_round_float(v, digits) for v in values]


def _serialize_pivot(p):
    return {
        "ZD": _round_float(p.ZD),
        "ZG": _round_float(p.ZG),
        "start_idx": p.start_idx,
        "end_idx": p.end_idx,
        "level": p.level,
    }


def _serialize_result(result):
    return {
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
        "trend_type": result.trend_type,
        "input_lengths": {
            "closes": len(result.closes),
            "highs": len(result.highs),
            "lows": len(result.lows),
            "opens": len(result.opens),
            "volumes": len(result.volumes),
            "dates": len(result.dates),
        },
        "input_tail": {
            "closes": _round_array(result.closes[-5:]),
            "highs": _round_array(result.highs[-5:]),
            "lows": _round_array(result.lows[-5:]),
            "opens": _round_array(result.opens[-5:]),
            "volumes": _round_array(result.volumes[-5:]),
            "dates": list(result.dates[-5:]),
        },
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


def _make_kline(closes):
    closes = np.asarray(closes, dtype=float)
    return {
        "dates": list(range(len(closes))),
        "opens": closes.copy(),
        "highs": closes + 0.6,
        "lows": closes - 0.6,
        "closes": closes,
        "volumes": np.array([1000.0] * len(closes), dtype=float),
    }


# These scenarios must stay in sync with tests/test_chan_engine_snapshot.py.
SCENARIOS = {
    "legacy_mixed": [
        9.28154636, 10.19840561, 11.32783692, 11.83613004, 12.43887384, 13.67740631,
        12.94265677, 13.11189133, 13.27126875, 12.62652898, 13.96773728, 13.58060836,
        13.09311082, 13.27158699, 13.95899872, 13.55830103, 13.15858950, 13.49466224,
        12.54425258, 12.02919550, 11.47037208, 11.18081590, 11.08597163, 12.31544392,
        12.92035120, 12.93528334, 12.78548208, 13.36838292, 13.65398288, 14.24812218,
        15.16877223, 14.49664896, 12.99474566, 12.98021066, 13.03318491, 13.22437081,
        12.82515497, 12.67007478, 13.04256591, 13.45093822, 14.33825745, 12.89407117,
        11.79496552, 12.76959298, 13.17505867, 13.70401526, 13.51412560, 13.19802200,
        13.33122450, 12.70469949, 11.68459170, 10.94421176, 11.02189588, 11.44669008,
        12.54752964, 12.79541057, 13.11042190, 14.23584919, 13.71807891, 13.07855133,
        12.71993022, 12.65578085, 14.00460469, 13.77204438, 14.64345331, 14.32834611,
        14.65595689, 15.11016818, 15.46546987, 15.96616758
    ],
    "sideways": [10.0 + (i % 5 - 2) * 0.4 for i in range(80)],
    "trend_up": [10.0 + i * 0.25 for i in range(80)],
    "trend_down": [32.0 - i * 0.3 for i in range(80)],
    "volatile_with_pivots": [
        12.0, 15.2, 13.1, 16.4, 11.8, 14.0, 12.0, 16.6, 11.3, 15.1,
        12.4, 14.9, 10.8, 13.7, 11.0, 16.3, 12.2, 15.7, 10.6, 13.1,
        12.9, 14.8, 11.5, 15.9, 10.9, 16.0, 12.5, 14.2, 11.4, 15.6,
        13.0, 13.8, 12.1, 16.2, 10.5, 14.7, 11.2, 15.8, 12.8, 14.4,
        10.7, 16.1, 12.3, 13.9, 11.1, 15.3, 12.6, 14.6, 10.2, 16.5,
        12.7, 13.6, 11.6, 15.0, 10.4, 14.1, 12.0, 15.5, 10.1, 16.4,
        12.4, 13.5, 11.3, 14.3, 10.6, 15.4, 12.9, 14.0, 11.8, 16.3,
        10.8, 13.4, 12.2, 15.6, 10.9, 14.9, 12.6, 16.0, 11.0, 14.7,
        12.7, 13.2, 11.5, 15.1, 10.3, 14.5, 12.1, 15.9, 10.7, 16.2,
    ],
}


def main():
    payload = {}
    for name, closes in SCENARIOS.items():
        kline = _make_kline(closes)
        result = analyze(
            code=name,
            name=name,
            dates=kline["dates"],
            opens=kline["opens"],
            highs=kline["highs"],
            lows=kline["lows"],
            closes=kline["closes"],
            volumes=kline["volumes"],
        )
        payload[name] = _serialize_result(result)

    path = "tests/fixtures/chan_engine_snapshots.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
