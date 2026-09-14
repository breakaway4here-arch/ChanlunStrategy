import json
import unittest
from pathlib import Path
from unittest.mock import patch

from chanlun import data_fetcher


def _evidence(codes, *, requested=None, complete=True):
    codes = list(codes)
    if requested is None:
        requested = len(codes)
    return {
        "component_codes": codes,
        "diagnostics": {
            "requested": requested,
            "unique": len(set(codes)),
            "complete": complete,
            "error": "" if complete else "partial",
        },
    }


def _mixed_evidence(a_codes, raw_codes, *, requested=None, complete=True, **diagnostics):
    a_codes = list(a_codes)
    raw_codes = list(raw_codes)
    if requested is None:
        requested = len(raw_codes)
    return {
        "component_codes": a_codes,
        "raw_component_codes": raw_codes,
        "diagnostics": {
            "requested": requested,
            "raw_valid_unique": len(set(raw_codes)),
            "filtered_unique": len(set(a_codes)),
            "unique": len(set(a_codes)),
            "complete": complete,
            "error": "" if complete else "partial",
            **diagnostics,
        },
    }


class TestSectorHierarchyDedup(unittest.TestCase):

    def test_complete_mixed_evidence_deduplicates_identical_raw_sets(self):
        a_codes = ["600{:03d}".format(index) for index in range(15)]
        raw_codes = a_codes + ["200{:03d}".format(index) for index in range(5)]
        rows = [
            {"code": "LEFT", "name": "左板块", "flow": 300},
            {"code": "RIGHT", "name": "右板块", "flow": 200},
        ]
        evidence = {
            "LEFT": _mixed_evidence(a_codes, raw_codes),
            "RIGHT": _mixed_evidence(a_codes, raw_codes),
        }

        result = data_fetcher.deduplicate_sector_hierarchy(rows, evidence)

        self.assertEqual([row["code"] for row in result], ["LEFT"])
        self.assertEqual(result[0]["component_coverage"], 1.0)
        self.assertEqual(
            result[0]["hierarchy_dedup_suppressed_codes"], ["RIGHT"]
        )

    def test_complete_mixed_evidence_uses_raw_codes_for_coverage_and_overlap(self):
        a_codes = ["600{:03d}".format(index) for index in range(15)]
        left_raw = a_codes + ["200{:03d}".format(index) for index in range(5)]
        right_raw = a_codes + ["900{:03d}".format(index) for index in range(5)]
        rows = [
            {"code": "LEFT", "name": "左板块", "flow": 300},
            {"code": "RIGHT", "name": "右板块", "flow": 200},
        ]
        evidence = {
            "LEFT": _mixed_evidence(a_codes, left_raw),
            "RIGHT": _mixed_evidence(a_codes, right_raw),
        }

        result = data_fetcher.deduplicate_sector_hierarchy(rows, evidence)

        self.assertEqual([row["code"] for row in result], ["LEFT", "RIGHT"])
        self.assertEqual(
            [row["component_coverage"] for row in result], [1.0, 1.0]
        )
        self.assertEqual(
            [row["hierarchy_dedup_status"] for row in result],
            ["checked_unique", "checked_unique"],
        )

    def test_unverifiable_raw_component_evidence_never_self_certifies(self):
        valid = _mixed_evidence(
            ["600001", "600002"],
            ["600001", "600002"],
        )
        invalid_cases = {
            "missing_raw_set_with_mixed_count": {
                "component_codes": ["600001", "600002"],
                "diagnostics": {
                    "requested": 3,
                    "raw_valid_unique": 3,
                    "filtered_unique": 2,
                    "unique": 2,
                    "complete": True,
                },
            },
            "duplicate_raw_code": {
                **valid,
                "raw_component_codes": ["600001", "600001", "600002"],
            },
            "scalar_raw_codes": {
                **valid,
                "raw_component_codes": "600001",
            },
            "raw_count_conflict": {
                **valid,
                "diagnostics": {**valid["diagnostics"], "raw_valid_unique": 3},
            },
            "filtered_count_conflict": {
                **valid,
                "diagnostics": {**valid["diagnostics"], "filtered_unique": 3},
            },
            "component_not_in_raw_set": {
                **valid,
                "component_codes": ["600001", "600003"],
            },
            "unknown_total": {
                **valid,
                "diagnostics": {**valid["diagnostics"], "requested": None},
            },
            "incomplete_page": {
                **valid,
                "diagnostics": {**valid["diagnostics"], "complete": False},
            },
        }

        for label, evidence in invalid_cases.items():
            with self.subTest(label=label):
                result = data_fetcher.deduplicate_sector_hierarchy(
                    [{"code": "ONLY", "name": label, "flow": 1}],
                    {"ONLY": evidence},
                )
                self.assertEqual(
                    result[0]["hierarchy_dedup_status"],
                    "insufficient_evidence",
                )

    def test_subset_chain_keeps_strongest_flow_representative(self):
        rows = [
            {"code": "PARENT", "name": "电子", "flow": -300},
            {"code": "CHILD", "name": "半导体", "flow": -200},
            {"code": "GRANDCHILD", "name": "数字芯片设计", "flow": -100},
            {"code": "OTHER", "name": "银行", "flow": -80},
        ]
        evidence = {
            "PARENT": _evidence(["1", "2", "3", "4", "5"]),
            "CHILD": _evidence(["2", "3", "4"]),
            "GRANDCHILD": _evidence(["3", "4"]),
            "OTHER": _evidence(["8", "9"]),
        }

        result = data_fetcher.deduplicate_sector_hierarchy(
            rows, evidence, top_n=5
        )

        self.assertEqual([row["code"] for row in result], ["PARENT", "OTHER"])
        self.assertEqual(
            result[0]["hierarchy_dedup_status"], "deduped_representative"
        )
        self.assertEqual(result[0]["component_coverage"], 1.0)
        self.assertEqual(
            result[0]["hierarchy_dedup_suppressed_codes"],
            ["CHILD", "GRANDCHILD"],
        )
        self.assertEqual(
            result[1]["hierarchy_dedup_status"], "checked_unique"
        )

    def test_complete_count_conflict_is_not_used_for_hierarchy_dedup(self):
        rows = [
            {"code": "LOW", "name": "低覆盖", "flow": 100},
            {"code": "HIGH", "name": "高覆盖", "flow": 100},
        ]
        evidence = {
            "LOW": _evidence(["1", "2", "3", "4"], requested=5),
            "HIGH": _evidence(["1", "2", "3", "4", "5"], requested=5),
        }

        result = data_fetcher.deduplicate_sector_hierarchy(rows, evidence)

        self.assertEqual([row["code"] for row in result], ["LOW", "HIGH"])
        self.assertEqual(result[0]["component_coverage"], 0.8)
        self.assertEqual(
            result[0]["hierarchy_dedup_status"], "insufficient_evidence"
        )
        self.assertEqual(
            result[1]["hierarchy_dedup_status"], "partial_check_only"
        )

    def test_incomplete_evidence_is_kept_and_not_claimed_as_deduped(self):
        rows = [
            {"code": "A", "name": "板块A", "flow": 300},
            {"code": "B", "name": "板块B", "flow": 200},
        ]
        evidence = {
            "A": _evidence(["1", "2", "3"], complete=False),
            "B": _evidence(["1", "2", "3"]),
        }

        result = data_fetcher.deduplicate_sector_hierarchy(rows, evidence)

        self.assertEqual([row["code"] for row in result], ["A", "B"])
        self.assertEqual(
            result[0]["hierarchy_dedup_status"], "insufficient_evidence"
        )
        self.assertEqual(
            result[1]["hierarchy_dedup_status"], "partial_check_only"
        )

    def test_high_overlap_chain_is_deduped_without_summing_flows(self):
        rows = [
            {"code": "A", "name": "IT服务II", "flow": 1_451_000_000},
            {"code": "B", "name": "IT服务III", "flow": 1_451_000_000},
        ]
        evidence = {
            "A": _evidence(["1", "2", "3", "4", "5"]),
            "B": _evidence(["1", "2", "3", "4", "6"]),
        }

        result = data_fetcher.deduplicate_sector_hierarchy(rows, evidence)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["flow"], 1_451_000_000)
        self.assertNotIn("aggregated_flow", result[0])

    @patch.object(data_fetcher, "_fetch_eastmoney_json")
    def test_fetch_flow_applies_injected_component_evidence(self, mock_fetch):
        mock_fetch.return_value = {
            "data": {
                "diff": [
                    {"f12": "P", "f14": "IT服务II", "f3": 2, "f62": 300},
                    {"f12": "C", "f14": "IT服务III", "f3": 1, "f62": 200},
                    {"f12": "O", "f14": "银行", "f3": 1, "f62": 100},
                ]
            }
        }
        evidence = {
            "P": _evidence(["1", "2", "3"]),
            "C": _evidence(["2", "3"]),
            "O": _evidence(["8", "9"]),
        }

        result = data_fetcher.fetch_sector_flow(
            2, component_evidence=evidence
        )

        self.assertEqual([row["code"] for row in result], ["P", "O"])
        self.assertEqual(
            result[0]["hierarchy_dedup_status"], "deduped_representative"
        )

    @patch.object(data_fetcher, "_fetch_eastmoney_json")
    def test_fetch_outflow_applies_injected_component_evidence(self, mock_fetch):
        mock_fetch.return_value = {
            "data": {
                "diff": [
                    {"f12": "P", "f14": "电子", "f3": -2, "f62": -300},
                    {"f12": "C", "f14": "半导体", "f3": -1, "f62": -200},
                    {"f12": "O", "f14": "银行", "f3": -1, "f62": -100},
                ]
            }
        }
        evidence = {
            "P": _evidence(["1", "2", "3"]),
            "C": _evidence(["2", "3"]),
            "O": _evidence(["8", "9"]),
        }

        result = data_fetcher.fetch_sector_outflow(
            2, component_evidence=evidence
        )

        self.assertEqual([row["code"] for row in result], ["P", "O"])
        self.assertEqual(
            result[0]["hierarchy_dedup_status"], "deduped_representative"
        )


class TestFullAIndustryMetadata(unittest.TestCase):
    @patch.object(data_fetcher, "_fetch_eastmoney_json")
    def test_fetch_all_a_stocks_preserves_industry_metadata(self, mock_fetch):
        mock_fetch.return_value = {
            "data": {
                "total": 1,
                "diff": [{
                    "f12": "301230",
                    "f14": "泓博医药",
                    "f2": 37.21,
                    "f3": 2.14,
                    "f5": 12345,
                    "f6": 45678900.0,
                    "f15": 38.0,
                    "f16": 36.4,
                    "f17": 36.8,
                    "f18": 36.43,
                    "f26": "20221101",
                    "f100": "医疗服务",
                }],
            }
        }

        rows, diagnostics = data_fetcher.fetch_all_a_stocks(
            return_diagnostics=True
        )

        self.assertTrue(diagnostics["complete"])
        self.assertEqual(rows[0]["industry"], "医疗服务")
        self.assertEqual(rows[0]["exchange"], "SZ")
        self.assertEqual(rows[0]["current_price"], 37.21)
        self.assertEqual(rows[0]["open"], 36.8)
        self.assertEqual(rows[0]["high"], 38.0)
        self.assertEqual(rows[0]["low"], 36.4)
        self.assertEqual(rows[0]["volume"], 12345.0)
        self.assertEqual(rows[0]["amount"], 45678900.0)
        requested_fields = mock_fetch.call_args[0][0]["fields"].split(",")
        self.assertIn("f100", requested_fields)
        self.assertIn("f2", requested_fields)
        self.assertIn("f17", requested_fields)
        self.assertIn("m:0+t:81+s:2048", mock_fetch.call_args[0][0]["fs"])

    @patch.object(data_fetcher, "_fetch_eastmoney_json")
    def test_fetch_all_a_stocks_recognizes_new_beijing_920_codes(self, mock_fetch):
        mock_fetch.return_value = {
            "data": {
                "total": 1,
                "diff": [{"f12": "920003", "f14": "中诚咨询"}],
            }
        }

        rows, diagnostics = data_fetcher.fetch_all_a_stocks(
            return_diagnostics=True
        )

        self.assertTrue(diagnostics["complete"])
        self.assertEqual(rows[0]["exchange"], "BJ")


class _JsonResponse:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class TestLimitPoolEvidence(unittest.TestCase):
    @patch.object(data_fetcher.SESSION, "get")
    def test_fetch_limit_up_pool_formats_integer_first_board_time(self, mock_get):
        fixture_path = (
            Path(__file__).parent / "fixtures" / "limit_up_pool_int_fbt.json"
        )
        mock_get.return_value = _JsonResponse(
            json.loads(fixture_path.read_text(encoding="utf-8"))
        )

        result = data_fetcher.fetch_limit_up_pool("20260820")

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["code"], "300308")
        self.assertEqual(result[0]["first_time"], "09:25")

    @patch.object(data_fetcher.SESSION, "get")
    def test_fetch_limit_up_pool_can_return_auditable_diagnostics(self, mock_get):
        fixture_path = (
            Path(__file__).parent / "fixtures" / "limit_up_pool_int_fbt.json"
        )
        mock_get.return_value = _JsonResponse(
            json.loads(fixture_path.read_text(encoding="utf-8"))
        )

        rows, diagnostics = data_fetcher.fetch_limit_up_pool(
            "20260820", return_diagnostics=True
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(diagnostics["raw_total"], 1)
        self.assertEqual(diagnostics["parsed_count"], 1)
        self.assertEqual(diagnostics["parse_error_count"], 0)
        self.assertEqual(diagnostics["evidence_date"], "2026-08-20")
        self.assertEqual(diagnostics["data_status"], "verified")

    @patch.object(data_fetcher.SESSION, "get")
    def test_fetch_limit_up_pool_reports_partial_row_parsing(self, mock_get):
        mock_get.return_value = _JsonResponse({
            "data": {
                "qdate": 20260820,
                "tc": 2,
                "pool": [
                    {
                        "c": "300308",
                        "n": "中际旭创",
                        "p": 468200,
                        "fbt": 92500,
                    },
                    {
                        "c": "002281",
                        "n": "光迅科技",
                        "p": "invalid-price",
                        "fbt": 93100,
                    },
                ],
            }
        })

        rows, diagnostics = data_fetcher.fetch_limit_up_pool(
            "20260820", return_diagnostics=True
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(diagnostics["raw_total"], 2)
        self.assertEqual(diagnostics["parsed_count"], 1)
        self.assertEqual(diagnostics["parse_error_count"], 1)

    @patch.object(data_fetcher.SESSION, "get")
    def test_fetch_limit_up_pool_fails_closed_on_date_mismatch(self, mock_get):
        mock_get.return_value = _JsonResponse({
            "data": {"qdate": 20260819, "tc": 1, "pool": []}
        })

        rows, diagnostics = data_fetcher.fetch_limit_up_pool(
            "20260820", return_diagnostics=True
        )

        self.assertEqual(rows, [])
        self.assertEqual(diagnostics["data_status"], "missing")
        self.assertIn("date mismatch", diagnostics["error"])

    @patch.object(data_fetcher.SESSION, "get")
    def test_fetch_limit_pool_counts_requires_same_verified_date(self, mock_get):
        mock_get.side_effect = [
            _JsonResponse({
                "data": {
                    "tc": 42,
                    "qdate": 20260716,
                    "pool": [],
                }
            }),
            _JsonResponse({
                "data": {
                    "tc": 33,
                    "qdate": 20260716,
                    "pool": [],
                }
            }),
        ]

        result = data_fetcher.fetch_limit_pool_counts("20260716")

        self.assertEqual(result["limit_up_count"], 42)
        self.assertEqual(result["limit_down_count"], 33)
        self.assertEqual(result["evidence_date"], "2026-07-16")
        self.assertEqual(result["data_status"], "verified")

    @patch.object(data_fetcher.SESSION, "get")
    def test_fetch_limit_pool_counts_fails_closed_on_date_mismatch(self, mock_get):
        mock_get.side_effect = [
            _JsonResponse({"data": {"tc": 42, "qdate": 20260715}}),
            _JsonResponse({"data": {"tc": 33, "qdate": 20260716}}),
        ]

        result = data_fetcher.fetch_limit_pool_counts("20260716")

        self.assertEqual(result["data_status"], "missing")
        self.assertIsNone(result["limit_up_count"])
        self.assertIsNone(result["limit_down_count"])


if __name__ == "__main__":
    unittest.main()
