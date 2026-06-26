import json
import unittest
import numpy as np

from chanlun.chan_engine import analyze


FIXTURE_PATH = "tests/fixtures/chan_engine_legacy_snapshot.json"


def _serialize_result(result):
    return {
        "fractals": [
            {
                "type": f.type,
                "index": f.index,
                "price": f.price,
            }
            for f in result.fractals
        ],
        "strokes": [
            {
                "start_idx": s.start_idx,
                "end_idx": s.end_idx,
                "start_price": s.start_price,
                "end_price": s.end_price,
                "direction": s.direction,
            }
            for s in result.strokes
        ],
        "segments": [
            {
                "start_idx": s.start_idx,
                "end_idx": s.end_idx,
                "direction": s.direction,
                "high": s.high,
                "low": s.low,
                "confirmed": s.confirmed,
                "destroyed_by_idx": s.destroyed_by_idx,
            }
            for s in result.segments
        ],
        "pivots": [
            {
                "ZD": p.ZD,
                "ZG": p.ZG,
                "start_idx": p.start_idx,
                "end_idx": p.end_idx,
                "level": p.level,
            }
            for p in result.pivots
        ],
        "divergence": None if result.divergence is None else {
            "type": result.divergence.get("type"),
            "is_divergence": result.divergence.get("is_divergence"),
            "area_ratio": result.divergence.get("area_ratio"),
            "hist_divergence": result.divergence.get("hist_divergence"),
        },
        "buy_points": [
            {
                "type": p["type"],
                "tier": p.get("tier"),
                "index": p["index"],
                "price": p["price"],
                "strength": p.get("strength"),
            }
            for p in result.buy_points
        ],
        "sell_points": [
            {
                "type": p["type"],
                "index": p["index"],
                "price": p["price"],
                "strength": p.get("strength"),
            }
            for p in result.sell_points
        ],
        "trend_type": result.trend_type,
    }


class ChanEngineSnapshotTests(unittest.TestCase):
    def test_snapshot_matches_legacy_output(self):
        dates = list(range(70))
        closes = np.array([
            9.28154636, 10.19840561, 11.32783692, 11.83613004, 12.43887384, 13.67740631,
            12.94265677, 13.11189133, 13.27126875, 12.62652898, 13.96773728, 13.58060836,
            13.09311082, 13.27158699, 13.95899872, 13.55830103, 13.15858950, 13.49466224, 12.54425258,
            12.02919550, 11.47037208, 11.18081590, 11.08597163, 12.31544392, 12.92035120, 12.93528334,
            12.78548208, 13.36838292, 13.65398288, 14.24812218, 15.16877223, 14.49664896, 12.99474566,
            12.98021066, 13.03318491, 13.22437081, 12.82515497, 12.67007478, 13.04256591, 13.45093822,
            14.33825745, 12.89407117, 11.79496552, 12.76959298, 13.17505867, 13.70401526, 13.51412560,
            13.19802200, 13.33122450, 12.70469949, 11.68459170, 10.94421176, 11.02189588, 11.44669008,
            12.54752964, 12.79541057, 13.11042190, 14.23584919, 13.71807891, 13.07855133, 12.71993022,
            12.65578085, 14.00460469, 13.77204438, 14.64345331, 14.32834611, 14.65595689, 15.11016818,
            15.46546987, 15.96616758
        ], dtype=float)
        highs = closes + 0.6
        lows = closes - 0.6
        opens = closes
        volumes = np.array([1000.0] * 70, dtype=float)

        result = analyze("TEST", "TEST", dates, opens, highs, lows, closes, volumes)
        payload = _serialize_result(result)

        with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
            baseline = json.load(f)

        self.assertEqual(payload, baseline)


if __name__ == "__main__":
    unittest.main()
