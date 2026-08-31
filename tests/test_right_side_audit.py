import json
import stat
import tempfile
import unittest
from pathlib import Path

from chanlun.right_side_audit import write_right_side_startup_audit


class RightSideStartupAuditTests(unittest.TestCase):
    def test_shadow_audit_is_isolated_atomic_and_non_production(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "isolated-audit"
            result = write_right_side_startup_audit(
                {
                    "mode": "shadow",
                    "policy_version": "right-side-startup-v1",
                    "diagnostics": {"daily": {"trend_seed": 3}},
                },
                trade_date="2026-08-31",
                generated_at="2026-08-31T15:10:00+08:00",
                as_of="2026-08-31T15:00:00+08:00",
                candidates=[{
                    "code": "300709",
                    "name": "精研科技",
                    "source_channel": "right_side_startup",
                    "reference_type": "platform_high_20d",
                    "reference_price": 48.11,
                    "distance_from_reference_pct": 1.2,
                    "volume_ratio": 1.8,
                    "confirmation_evidence": {
                        "data": {"valid": True},
                        "mandatory": {"reference_hold": True},
                        "structure": {"fresh_event": True},
                        "quality": {"independent_confirm": True},
                        "risk": {"macd_weakening": False},
                        "passed": True,
                    },
                }],
                watchlist=[{
                    "code": "002952",
                    "name": "亚世光电",
                    "source_channel": "right_side_startup",
                    "reference_type": "platform_high_20d",
                    "reference_price": 21.79,
                    "distance_from_reference_pct": -3.2,
                    "volume_ratio": 1.4,
                    "failure_gate": "daily_breakout",
                    "reason_code": "daily_breakout_near_miss",
                    "actual_value": {"close": 21.08},
                    "threshold": {"close_gt_reference_price": 21.79},
                }],
                run_identity={
                    "plane": "formal_postclose",
                    "candidate_funnel_run_id": "formal:2026-08-31",
                },
                source_sha="a" * 40,
                audit_root=root,
            )
            target = root / "2026-08-31.json"
            payload = json.loads(target.read_text(encoding="utf-8"))

            self.assertEqual(result["status"], "written")
            self.assertFalse(payload["affects_production"])
            self.assertEqual(payload["published_codes"], [])
            self.assertEqual(payload["source_sha"], "a" * 40)
            self.assertEqual(payload["as_of"], "2026-08-31T15:00:00+08:00")
            self.assertEqual(payload["run_identity"]["plane"], "formal_postclose")
            self.assertEqual(payload["candidates"][0]["code"], "300709")
            self.assertTrue(
                payload["candidates"][0]["confirmation_30m"]["mandatory"][
                    "reference_hold"
                ]
            )
            self.assertEqual(
                payload["watchlist"][0]["failure_gate"],
                "daily_breakout",
            )
            self.assertEqual(
                payload["watchlist"][0]["threshold"][
                    "close_gt_reference_price"
                ],
                21.79,
            )
            self.assertEqual(
                stat.S_IMODE(target.stat().st_mode),
                0o600,
            )
            self.assertEqual(list(root.glob("*.tmp")), [])

    def test_non_shadow_mode_does_not_create_audit_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "isolated-audit"
            result = write_right_side_startup_audit(
                {"mode": "active"},
                trade_date="2026-08-31",
                generated_at="2026-08-31T15:10:00+08:00",
                as_of="2026-08-31T15:00:00+08:00",
                source_sha="b" * 40,
                audit_root=root,
            )
            self.assertEqual(result["status"], "skipped")
            self.assertFalse(root.exists())


if __name__ == "__main__":
    unittest.main()
