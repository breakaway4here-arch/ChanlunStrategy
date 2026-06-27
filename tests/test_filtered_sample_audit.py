import unittest
from unittest.mock import patch

from chanlun.filtered_sample_audit import build_filtered_sample_audit, collect_filtered_samples


def _fake_kline(code):
    if code == "000001":
        closes = [100.0, 101.0, 102.0, 120.0, 130.0, 140.0, 150.0, 160.0]
    elif code == "000002":
        closes = [100.0, 101.0, 102.0, 110.0, 105.0, 103.0, 100.0, 102.0]
    else:
        closes = [100.0, 101.0, 102.0, 103.0, 104.0, 103.0, 102.0, 101.0]

    opens = closes
    highs = [x + 1.0 for x in closes]
    lows = [x - 1.0 for x in closes]
    return {
        "dates": [
            "2026-01-01",
            "2026-01-02",
            "2026-01-03",
            "2026-01-04",
            "2026-01-05",
            "2026-01-06",
            "2026-01-07",
            "2026-01-08",
        ],
        "opens": opens,
        "highs": highs,
        "lows": lows,
        "closes": closes,
    }


def _fake_picks():
    return [
        (
            "2026-01-03",
            "picks_pure",
            {
                "code": "000001",
                "name": "AAA",
                "signal_tier": "tier1",
                "best_buy_point": {
                    "type": "底背驰候选",
                    "index": 6,
                    "distance_from_reference_pct": 2.1,
                    "confirmations": ["止跌结构", "EMA5收复"],
                },
                "closes": [1, 2, 3, 4, 5, 6, 7],
            },
        ),
        (
            "2026-01-03",
            "picks_pure",
            {
                "code": "000002",
                "name": "BBB",
                "signal_tier": "tier1",
                "best_buy_point": {
                    "type": "底背驰候选",
                    "index": 6,
                    "distance_from_reference_pct": 7.2,
                    "confirmations": ["EMA5收复", "关键位不破"],
                },
                "closes": [1, 2, 3, 4, 5, 6, 7],
            },
        ),
        (
            "2026-01-03",
            "picks_pure",
            {
                "code": "000003",
                "name": "CCC",
                "best_buy_point": {
                    "type": "强势启动候选",
                    "index": 6,
                    "distance_from_reference_pct": 2.1,
                },
                "closes": [1, 2, 3, 4, 5, 6, 7],
            },
        ),
        (
            "2026-01-03",
            "picks_pure",
            {
                "name": "DDD",
                "best_buy_point": {"type": "底背驰候选", "index": 6},
            },
        ),
    ]


class FilteredSampleAuditTests(unittest.TestCase):
    @patch("chanlun.filtered_sample_audit.fetch_daily_kline")
    @patch("chanlun.filtered_sample_audit.iter_snapshot_picks")
    def test_collect_filtered_samples(self, iter_snapshot_picks_mock, fetch_kline_mock):
        iter_snapshot_picks_mock.side_effect = lambda: iter(_fake_picks())
        fetch_kline_mock.side_effect = lambda code, **_: _fake_kline(code)

        records = collect_filtered_samples("signal_delay1_by_type_guard")
        self.assertEqual(len(records), 2)

        codes = {item["code"] for item in records}
        self.assertEqual(codes, {"000001", "000002"})
        for item in records:
            self.assertIn("version", item)
            self.assertIn("t3_close_pct", item["return_sample"])
            self.assertEqual(item["return_sample"].get("entry_mode"), "immediate_close")

    @patch("chanlun.filtered_sample_audit.fetch_daily_kline")
    @patch("chanlun.filtered_sample_audit.iter_snapshot_picks")
    def test_summary_and_top_winners(self, iter_snapshot_picks_mock, fetch_kline_mock):
        iter_snapshot_picks_mock.side_effect = lambda: iter(_fake_picks())
        fetch_kline_mock.side_effect = lambda code, **_: _fake_kline(code)

        payload = build_filtered_sample_audit("signal_delay1_by_type_guard", top_winners=2)
        summary = payload["summary"]
        self.assertEqual(summary["filtered"], 2)
        self.assertEqual(summary["return_summary"]["n"], 2)

        top_winners = payload["top_winners"]
        self.assertEqual(len(top_winners), 2)
        self.assertEqual(top_winners[0]["code"], "000001")
        self.assertEqual(top_winners[1]["code"], "000002")
        self.assertEqual(top_winners[0]["name"], "AAA")
        self.assertEqual(top_winners[0]["version"], "picks_pure")

        by_type = payload["by_type"]
        self.assertIn("底背驰候选", by_type)
        self.assertEqual(by_type["底背驰候选"]["n"], 2)

        by_signal_tier = payload["by_signal_tier"]
        self.assertIn("tier1", by_signal_tier)
        self.assertEqual(by_signal_tier["tier1"]["n"], 2)

        by_confirmations = payload["by_confirmations"]
        self.assertIn("EMA5收复+止跌结构", by_confirmations)
        self.assertIn("EMA5收复+关键位不破", by_confirmations)
        self.assertEqual(by_confirmations["EMA5收复+止跌结构"]["n"], 1)

        by_distance = payload["by_distance_bucket"]
        self.assertIn("0-3%", by_distance)
        self.assertIn("6-10%", by_distance)
        self.assertEqual(by_distance["0-3%"]["n"], 1)
        self.assertEqual(by_distance["6-10%"]["n"], 1)

    @patch("chanlun.filtered_sample_audit.supports_historical_return_metrics")
    def test_unsupported_experiment_raises_collector(self, supports_mock):
        supports_mock.return_value = False
        with self.assertRaises(ValueError):
            collect_filtered_samples("not_supported")


if __name__ == "__main__":
    unittest.main()
