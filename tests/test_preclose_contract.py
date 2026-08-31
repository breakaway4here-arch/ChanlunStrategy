import json
import unittest
from pathlib import Path

from chanlun.preclose_contract import (
    build_preclose_snapshot,
    build_public_preclose_view,
    is_preclose_expired,
    normalize_preclose_candidate,
    snapshot_content_hash,
)


FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "preclose"


def _fixture(name):
    return json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))


class PrecloseContractTests(unittest.TestCase):
    def test_available_snapshot_is_advisory_and_non_final(self):
        fixture = _fixture("available.json")
        snapshot = build_preclose_snapshot(**fixture)

        self.assertEqual(snapshot["schema_version"], "preclose-selection-v1")
        self.assertEqual(snapshot["mode"], "preclose_advisory")
        self.assertEqual(snapshot["strategy_version"], "preclose-1445-v2")
        self.assertFalse(snapshot["is_final"])
        self.assertFalse(snapshot["affects_formal"])
        self.assertEqual(snapshot["expires_at"], "2026-08-27T14:56:30+08:00")
        self.assertEqual(set(snapshot["pools"]), {"main", "h4_t3", "acceleration"})
        self.assertEqual(snapshot["status"], "available")
        self.assertEqual(snapshot_content_hash(snapshot), snapshot["content_hash"])
        self.assertTrue(snapshot["snapshot_id"].endswith(snapshot["content_hash"][:16]))

    def test_candidate_public_fields_are_strictly_whitelisted(self):
        candidate = normalize_preclose_candidate({
            "code": "300998.SZ",
            "name": " 宁波方正 ",
            "reference_price": 26.864,
            "score": 88,
            "psy12": 50,
            "news": "internal",
            "internal_reason": "decision_engine_recommend",
            "position_band": "10%-30%",
        })

        self.assertEqual(candidate, {
            "code": "300998",
            "name": "宁波方正",
            "reference_price": 26.86,
        })

    def test_content_hash_is_stable_and_sensitive_to_order_code_and_as_of(self):
        fixture = _fixture("available.json")
        first = build_preclose_snapshot(**fixture)
        repeated = build_preclose_snapshot(**fixture)
        self.assertEqual(first["content_hash"], repeated["content_hash"])

        reversed_fixture = json.loads(json.dumps(fixture))
        reversed_fixture["pools"]["main"].append({
            "code": "600000", "name": "浦发银行", "reference_price": 10.0
        })
        reversed_first = build_preclose_snapshot(**reversed_fixture)
        reversed_fixture["pools"]["main"].reverse()
        reversed_second = build_preclose_snapshot(**reversed_fixture)
        self.assertNotEqual(reversed_first["content_hash"], reversed_second["content_hash"])

        changed_code = json.loads(json.dumps(fixture))
        changed_code["pools"]["main"][0]["code"] = "300999"
        self.assertNotEqual(
            first["content_hash"],
            build_preclose_snapshot(**changed_code)["content_hash"],
        )
        changed_as_of = dict(fixture, as_of="2026-08-27T14:47:01+08:00")
        self.assertNotEqual(
            first["content_hash"],
            build_preclose_snapshot(**changed_as_of)["content_hash"],
        )

    def test_empty_and_failed_states_use_one_public_empty_message(self):
        empty = build_preclose_snapshot(**_fixture("empty.json"))
        failed = build_preclose_snapshot(
            **_fixture("empty.json"),
            status="deadline_exceeded",
            diagnostics={"reason": "deadline_exceeded", "stage": "market_context"},
        )

        for snapshot in (empty, failed):
            public = build_public_preclose_view(
                snapshot,
                now="2026-08-27T14:50:00+08:00",
            )
            self.assertEqual(public["message"], "本期未选出推荐票")
            self.assertEqual(public["pools"], {
                "main": [], "h4_t3": [], "acceleration": []
            })
            self.assertNotIn("diagnostics", public)
            self.assertNotIn("reason", public)
            self.assertEqual(public["strategy_version"], "preclose-1445-v2")

    def test_server_and_browser_iso_times_expire_at_the_same_boundary(self):
        fixture = _fixture("expired.json")
        now = fixture.pop("now")
        snapshot = build_preclose_snapshot(**fixture)

        self.assertFalse(
            is_preclose_expired(snapshot, "2026-08-27T14:56:29+08:00")
        )
        self.assertTrue(is_preclose_expired(snapshot, now))
        public = build_public_preclose_view(snapshot, now=now)
        self.assertEqual(public["status"], "expired")
        self.assertEqual(public["pools"]["main"], [])
        self.assertIn("14:57", public["message"])
        self.assertNotIn("300998", json.dumps(public, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
