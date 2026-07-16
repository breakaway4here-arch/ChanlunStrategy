import unittest

from run import _complete_sector_component_evidence


class RunSectorEvidenceTests(unittest.TestCase):
    def test_reuses_existing_evidence_and_fetches_only_missing_sectors(self):
        calls = []

        def fetcher(code, return_diagnostics=False):
            calls.append((code, return_diagnostics))
            return (
                [{"code": "600001"}, {"code": "600002"}],
                {
                    "sector_code": code,
                    "requested": 2,
                    "complete": True,
                },
            )

        result = _complete_sector_component_evidence(
            [{"code": "BK001"}, {"code": "BK002"}],
            {
                "BK001": {
                    "component_codes": ["000001", "000002"],
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
        self.assertEqual(result["BK002"]["component_codes"], ["600001", "600002"])


if __name__ == "__main__":
    unittest.main()
