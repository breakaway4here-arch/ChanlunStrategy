import unittest

from chanlun import data_fetcher
from run import _complete_sector_component_evidence


class RunSectorEvidenceTests(unittest.TestCase):
    def test_preserves_explicit_invalid_raw_component_codes(self):
        sectors = [
            {"code": "BAD", "name": "非法证据", "flow": 300},
            {"code": "GOOD", "name": "正常证据", "flow": 200},
        ]
        a_codes = ["600001", "600002"]

        for label, invalid_raw in (
            ("scalar", "600001"),
            ("mapping", {"600001": 1}),
            ("null", None),
            ("integer", 2),
        ):
            with self.subTest(label=label):
                def fetcher(code, return_diagnostics=False):
                    diagnostics = {
                        "sector_code": code,
                        "requested": 2,
                        "raw_valid_unique": 2,
                        "filtered_unique": 2,
                        "unique": 2,
                        "complete": True,
                        "raw_component_codes": (
                            invalid_raw if code == "BAD" else list(a_codes)
                        ),
                    }
                    rows = [{"code": item} for item in a_codes]
                    return (rows, diagnostics) if return_diagnostics else rows

                evidence = _complete_sector_component_evidence(
                    sectors, fetcher=fetcher, max_workers=1
                )

                self.assertIn("raw_component_codes", evidence["BAD"])
                self.assertEqual(
                    evidence["BAD"]["raw_component_codes"], invalid_raw
                )
                hierarchy = data_fetcher.deduplicate_sector_hierarchy(
                    sectors, evidence
                )
                self.assertEqual(
                    [row["code"] for row in hierarchy], ["BAD", "GOOD"]
                )
                self.assertEqual(
                    [row["hierarchy_dedup_status"] for row in hierarchy],
                    ["insufficient_evidence", "partial_check_only"],
                )

    def test_keeps_legacy_pure_a_evidence_without_raw_field(self):
        def fetcher(code, return_diagnostics=False):
            diagnostics = {
                "sector_code": code,
                "requested": 2,
                "raw_valid_unique": 2,
                "filtered_unique": 2,
                "unique": 2,
                "complete": True,
            }
            rows = [{"code": "600001"}, {"code": "600002"}]
            return (rows, diagnostics) if return_diagnostics else rows

        evidence = _complete_sector_component_evidence(
            [{"code": "LEGACY", "name": "旧纯A", "flow": 1}],
            fetcher=fetcher,
            max_workers=1,
        )

        self.assertNotIn("raw_component_codes", evidence["LEGACY"])
        hierarchy = data_fetcher.deduplicate_sector_hierarchy(
            [{"code": "LEGACY", "name": "旧纯A", "flow": 1}], evidence
        )
        self.assertEqual(hierarchy[0]["hierarchy_dedup_status"], "checked_unique")

    def test_reuses_existing_evidence_and_fetches_only_missing_sectors(self):
        calls = []

        def fetcher(code, return_diagnostics=False):
            calls.append((code, return_diagnostics))
            return (
                [{"code": "600001"}, {"code": "600002"}],
                {
                    "sector_code": code,
                    "requested": 3,
                    "raw_valid_unique": 3,
                    "filtered_unique": 2,
                    "unique": 2,
                    "raw_component_codes": ["200012", "600001", "600002"],
                    "complete": True,
                },
            )

        result = _complete_sector_component_evidence(
            [{"code": "BK001"}, {"code": "BK002"}],
            {
                "BK001": {
                    "component_codes": ["000001", "000002"],
                    "raw_component_codes": ["000001", "000002"],
                    "diagnostics": {
                        "sector_code": "BK001",
                        "requested": 2,
                        "complete": True,
                    },
                },
            },
            fetcher=fetcher,
            max_workers=20,
        )

        self.assertEqual(calls, [("BK002", True)])
        self.assertEqual(result["BK001"]["component_codes"], ["000001", "000002"])
        self.assertEqual(
            result["BK001"]["raw_component_codes"], ["000001", "000002"]
        )
        self.assertEqual(result["BK002"]["component_codes"], ["600001", "600002"])
        self.assertEqual(
            result["BK002"]["raw_component_codes"],
            ["200012", "600001", "600002"],
        )
        hierarchy = data_fetcher.deduplicate_sector_hierarchy(
            [{"code": "BK002", "name": "补齐板块", "flow": 1}], result
        )
        self.assertEqual(hierarchy[0]["component_coverage"], 1.0)
        self.assertEqual(
            hierarchy[0]["hierarchy_dedup_status"], "checked_unique"
        )


if __name__ == "__main__":
    unittest.main()
