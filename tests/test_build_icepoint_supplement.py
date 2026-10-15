"""Historical observation evidence is built offline, never into the frozen report."""

import copy
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def frozen_report():
    full = json.loads((ROOT / "docs/data/2026-10-14.json").read_text(encoding="utf-8"))
    return {key: full[key] for key in ("date", "data_quality", "market_icepoint")}


def normalized_evidence():
    prior = [1600000000000, 1600000000000, 1700000000000,
             1700000000000, 1700642600000]
    return {
        "schema_version": 1, "report_date": "2026-10-14",
        "source": "hithink_iwencai_883957", "selection_usage": "not_used",
        "turnover": {
            "source": "wencai", "source_code": "883957.TI",
            "evidence_contract": "provider_aggregate_v1", "amount_unit": "CNY",
            "date": "2026-10-14", "market_date": "2026-10-14",
            "market_phase": "closed", "scope": "all_a_cny", "current": 1426389200000,
            "prior": prior, "prior_dates": ["2026-09-30", "2026-10-08",
                                            "2026-10-09", "2026-10-12", "2026-10-13"],
            "quality": "comparable", "trading_days_verified": True, "complete": True,
            "as_of": "2026-10-15T10:30:00+08:00",
            "retrieved_at": "2026-10-15T10:30:00+08:00",
        },
        "breadth": {
            "source": "quote_snapshot+wencai", "scope": "all_a",
            "date": "2026-10-14", "as_of": "2026-10-14T15:20:09+08:00",
            "retrieved_at": "2026-10-15T10:29:00+08:00",
            "advance_count": 978, "decline_count": 4496, "flat_count": 88,
            "valid_count": 5562, "denominator": 5562, "trading_count": 5562,
            "quote_snapshot_count": 5573, "suspended_count": 11,
            "unknown_count": 0, "complete": True,
        },
        "source_evidence": [
            {"url": "https://openapi.iwencai.com/v1/query2data",
             "sha256": "a" * 64, "received_at": "2026-10-15T10:27:00+08:00"},
            {"url": "https://openapi.iwencai.com/v1/query2data",
             "sha256": "b" * 64, "received_at": "2026-10-15T10:28:00+08:00"},
        ],
    }


class IcepointSupplementBuilderTests(unittest.TestCase):
    def test_builds_bound_sidecar_without_mutating_original(self):
        from scripts.build_icepoint_supplement import build_icepoint_supplement

        report = frozen_report()
        original = copy.deepcopy(report)
        evidence = normalized_evidence()
        original_evidence = copy.deepcopy(evidence)
        sidecar = build_icepoint_supplement(report, evidence)
        self.assertEqual(original, report)
        self.assertEqual(original_evidence, evidence)
        self.assertEqual(original["market_icepoint"], sidecar["original_market_icepoint"])
        self.assertEqual("not_matched", sidecar["supplemented_market_icepoint"]["status"])
        self.assertEqual(4, sidecar["supplemented_market_icepoint"]["verified_count"])
        self.assertEqual(0, sidecar["supplemented_market_icepoint"]["matched_count"])
        self.assertEqual(11, sidecar["supplemented_market_icepoint"]["items"]["breadth"]["actual"]["suspended_count"])
        self.assertEqual(6, len(sidecar["turnover_days"]))
        self.assertEqual("2026-10-14", sidecar["report_date"])
        self.assertEqual("not_used", sidecar["selection_usage"])

    def test_rejects_wrong_date_provenance_or_incomplete_counts(self):
        from scripts.build_icepoint_supplement import build_icepoint_supplement

        changes = (
            lambda e: e.update(report_date="2026-10-13"),
            lambda e: e.update(source="unknown"),
            lambda e: e.update(selection_usage="selected"),
            lambda e: e["turnover"].update(source_code="883421.TI"),
            lambda e: e["turnover"].update(market_date="2026-10-15"),
            lambda e: e["turnover"].update(amount_unit="wan"),
            lambda e: e["breadth"].update(suspended_count=10),
            lambda e: e["breadth"].update(unknown_count=1),
            lambda e: e.update(source_evidence=[]),
            lambda e: e["source_evidence"][0].update(sha256="not-a-hash"),
        )
        for index, change in enumerate(changes):
            with self.subTest(index=index):
                evidence = normalized_evidence()
                change(evidence)
                with self.assertRaises(ValueError):
                    build_icepoint_supplement(frozen_report(), evidence)

    def test_file_builder_only_writes_explicit_output(self):
        from scripts.build_icepoint_supplement import write_icepoint_supplement

        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            report_path = directory / "report.json"
            evidence_path = directory / "validated.json"
            output_path = directory / "sidecar.json"
            report = frozen_report()
            report_path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
            evidence_path.write_text(json.dumps(normalized_evidence(), ensure_ascii=False), encoding="utf-8")
            write_icepoint_supplement(report_path, evidence_path, output_path)
            result = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(4, result["supplemented_market_icepoint"]["verified_count"])
            self.assertEqual(report, json.loads(report_path.read_text(encoding="utf-8")))
            self.assertEqual({"report.json", "validated.json", "sidecar.json"},
                             {file.name for file in directory.iterdir()})

    def test_built_sidecar_is_accepted_by_page_consumer(self):
        from scripts.build_icepoint_supplement import build_icepoint_supplement
        from tests.test_icepoint_supplement_frontend import run_js

        sidecar = build_icepoint_supplement(frozen_report(), normalized_evidence())
        body = """
const supplement=__SIDECAR__;
assert(__iceTest.validate(report,supplement)!==null,'built sidecar rejected by page');
const html=__iceTest.card(report,supplement);
assert(html.includes('已核验 4/4') && html.includes('停牌 11')
  && !html.includes('证据不一致'),'page did not render derived result');
""".replace("__SIDECAR__", json.dumps(sidecar, ensure_ascii=False))
        result = run_js(body)
        self.assertEqual(0, result.returncode, result.stderr)


if __name__ == "__main__":
    unittest.main()
