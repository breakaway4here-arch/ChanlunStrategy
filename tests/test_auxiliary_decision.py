import unittest

from chanlun.auxiliary_decision import build_limit_up_snapshot


def _item(code="300308", sector="通信设备", lianban=1, first_time="09:25"):
    return {
        "code": code,
        "name": code,
        "sector": sector,
        "lianban": lianban,
        "first_time": first_time,
        "fund": 100,
    }


def _diagnostics(total, parsed, *, errors=0, status="verified", date="2026-08-20"):
    return {
        "raw_total": total,
        "parsed_count": parsed,
        "parse_error_count": errors,
        "evidence_date": date,
        "data_status": status,
        "source": "eastmoney_limit_pools",
        "error": "" if status == "verified" else "upstream unavailable",
    }


class LimitUpSnapshotTests(unittest.TestCase):
    def test_verified_complete_requires_total_and_parsed_items_to_match(self):
        snapshot = build_limit_up_snapshot(
            "2026-08-20",
            [_item("300308"), _item("002281")],
            _diagnostics(2, 2),
            limit_down_total=12,
            as_of="2026-08-20T15:10:00+08:00",
            generated_at="2026-08-20T15:11:00+08:00",
        )

        self.assertEqual(snapshot["status"], "verified_complete")
        self.assertEqual(snapshot["raw_total"], 2)
        self.assertEqual(snapshot["parsed_count"], 2)
        self.assertEqual(snapshot["coverage"], 1.0)
        self.assertEqual(snapshot["limit_down_total"], 12)

    def test_verified_zero_is_distinct_from_missing_items(self):
        snapshot = build_limit_up_snapshot(
            "2026-08-20", [], _diagnostics(0, 0), limit_down_total=0
        )

        self.assertEqual(snapshot["status"], "verified_empty")
        self.assertEqual(snapshot["coverage"], 1.0)

    def test_nonzero_total_with_some_items_is_partial(self):
        snapshot = build_limit_up_snapshot(
            "2026-08-20",
            [_item()],
            _diagnostics(3, 1, errors=2),
            limit_down_total=12,
        )

        self.assertEqual(snapshot["status"], "partial")
        self.assertEqual(snapshot["coverage"], 0.3333)
        self.assertEqual(snapshot["parse_error_count"], 2)

    def test_nonzero_total_with_no_items_is_error_not_verified_empty(self):
        snapshot = build_limit_up_snapshot(
            "2026-08-20", [], _diagnostics(79, 0, errors=79)
        )

        self.assertEqual(snapshot["status"], "error")
        self.assertEqual(snapshot["coverage"], 0.0)

    def test_missing_upstream_evidence_is_missing(self):
        snapshot = build_limit_up_snapshot(
            "2026-08-20",
            [],
            _diagnostics(None, 0, status="missing"),
        )

        self.assertEqual(snapshot["status"], "missing")
        self.assertIn("upstream unavailable", snapshot["error"])

    def test_evidence_date_mismatch_is_error(self):
        snapshot = build_limit_up_snapshot(
            "2026-08-20",
            [_item()],
            _diagnostics(1, 1, date="2026-08-19"),
        )

        self.assertEqual(snapshot["status"], "error")
        self.assertIn("date mismatch", snapshot["error"])

    def test_theme_groups_and_leaders_are_derived_from_facts(self):
        snapshot = build_limit_up_snapshot(
            "2026-08-20",
            [
                _item("300308", "通信设备", 2, "09:25"),
                _item("002281", "通信设备", 1, "09:31"),
                _item("688525", "半导体", 1, "10:05"),
            ],
            _diagnostics(3, 3),
        )

        self.assertEqual(snapshot["theme_groups"][0]["name"], "通信设备")
        self.assertEqual(snapshot["theme_groups"][0]["count"], 2)
        self.assertEqual(snapshot["leaders"][0]["code"], "300308")
        self.assertEqual(snapshot["leaders"][0]["link_type"], "limit_up_leader")


if __name__ == "__main__":
    unittest.main()
