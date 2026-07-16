import unittest

from run import _attach_position_evidence


class RunPositionEvidenceTests(unittest.TestCase):
    def test_builds_verified_trend_channel_reference_before_decision(self):
        row = {
            "code": "600000",
            "source_channel": "trend_continuation",
            "reference_type": "platform_high_20d",
            "reference_price": 10.0,
            "closes": [10.5] * 60,
            "data_status": {
                "daily": "verified",
                "latest_date": "2026-07-16",
            },
        }

        result = _attach_position_evidence(row, "2026-07-16")

        self.assertEqual(result["position_data_status"], "verified")
        self.assertEqual(
            result["position_reference_type"],
            "channel_reference:platform_high_20d",
        )
        self.assertEqual(result["position_reference_price"], 10.0)
        self.assertEqual(result["position_evidence_date"], "2026-07-16")
        self.assertEqual(result["position_distance_pct"], 5.0)

    def test_low_position_startup_uses_verified_startup_reference(self):
        row = {
            "code": "600001",
            "source_channel": "low_position",
            "best_buy_point": {
                "type": "强势启动候选",
                "source_type": "日线强势启动",
                "price": 10.0,
            },
            "closes": [10.0] * 60,
            "data_status": {
                "daily": "verified",
                "latest_date": "2026-07-16",
            },
        }

        result = _attach_position_evidence(row, "2026-07-16")

        self.assertEqual(result["position_data_status"], "verified")
        self.assertEqual(
            result["position_reference_type"],
            "low_position_channel:日线强势启动",
        )
        self.assertEqual(result["position_distance_pct"], 0.0)

    def test_does_not_verify_position_when_daily_evidence_is_stale(self):
        row = {
            "code": "600000",
            "closes": [10.0] * 60,
            "lows": [9.8] * 60,
            "highs": [10.2] * 60,
            "data_status": {
                "daily": "stale_cache",
                "latest_date": "2026-07-15",
            },
        }

        result = _attach_position_evidence(row, "2026-07-16")

        self.assertEqual(result["position_data_status"], "missing")
        self.assertIsNone(result["position_distance_pct"])

    def test_missing_explicit_reference_is_invalid_instead_of_default_zero(self):
        row = {
            "code": "600000",
            "closes": [10.0] * 20,
            "data_status": {
                "daily": "verified",
                "latest_date": "2026-07-16",
            },
        }

        result = _attach_position_evidence(row, "2026-07-16")

        self.assertEqual(result["position_data_status"], "invalid")
        self.assertIsNone(result["position_distance_pct"])


if __name__ == "__main__":
    unittest.main()
