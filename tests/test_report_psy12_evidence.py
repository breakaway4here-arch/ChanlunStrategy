"""Integration contracts for the HTML-only PSY12 shadow audit."""

import copy
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from chanlun.market_sentiment import build_market_sentiment_psy12_shadow
from chanlun.psy12_shadow_audit import evaluate_shadow_reports as core_evaluator
from chanlun.report_generator import (
    _build_report_bootstrap,
    build_aggregate_day_projection,
    build_formal_output_projection,
    build_full_daily_projection,
    generate_report,
)
from chanlun.shadow_evaluation import production_digest
from scripts.evaluate_market_sentiment_psy12_shadow import (
    _load_reports,
    evaluate_shadow_reports as cli_evaluator,
)


def _report(trade_date="2026-08-28"):
    end = date.fromisoformat(trade_date)
    history = []
    for offset in range(11, -1, -1):
        history.append({
            "date": (end - timedelta(days=offset)).isoformat(),
            "evidence": {
                "index": {
                    "available": True,
                    "average_change_pct": 0.8 if offset % 2 else -0.4,
                }
            },
        })
    components = {
        "breadth": 62.0,
        "limit_ecology": 58.0,
        "index": 49.0,
        "turnover": 54.0,
        "trend": 51.0,
    }
    formal = {
        "date": trade_date,
        "score": 56,
        "label": "平衡",
        "coverage": 1.0,
        "components": components,
    }
    shadow = build_market_sentiment_psy12_shadow(formal, history)
    return {
        "date": trade_date,
        "market": {},
        "market_sentiment": formal,
        "market_sentiment_history": history,
        "psy12": shadow["psy12"],
        "psy12_shadow": shadow["psy12_shadow"],
        "data_quality": {"is_trading_day": True, "is_official": True},
    }


class ReportPsy12EvidenceTests(unittest.TestCase):

    def test_bootstrap_computes_real_progress_without_changing_formal_payload(self):
        report = _report()
        daily = build_full_daily_projection(report)
        report_before = copy.deepcopy(report)
        daily_before = copy.deepcopy(daily)
        digest_before = production_digest(build_formal_output_projection(report))

        bootstrap = _build_report_bootstrap(
            report,
            daily,
            "",
            "",
            "",
            "",
            historical_reports={},
        )

        audit = bootstrap["recommendationEvidence"]["market_sentiment"][
            "psy12_shadow_audit"
        ]
        self.assertEqual(audit["status"], "insufficient_observation_days")
        self.assertEqual(audit["valid_days"], 1)
        self.assertEqual(audit["stored_complete_days"], 1)
        self.assertEqual(audit["recomputable_days"], 1)
        self.assertEqual(audit["required_days"], 20)
        self.assertFalse(audit["affects_production"])
        self.assertFalse(audit["promotion_eligible"])
        self.assertTrue(audit["promotion_requires_new_authorization"])
        self.assertEqual(report, report_before)
        self.assertEqual(daily, daily_before)
        self.assertNotIn("psy12_shadow_audit", daily)
        self.assertEqual(
            production_digest(build_formal_output_projection(report)),
            digest_before,
        )

    def test_legacy_shadow_gets_html_only_non_promotion_contract(self):
        report = _report()
        report["psy12_shadow"].pop("promotion_eligible", None)
        report["psy12_shadow"].pop(
            "promotion_requires_new_authorization",
            None,
        )
        daily = build_full_daily_projection(report)

        bootstrap = _build_report_bootstrap(
            report,
            daily,
            "",
            "",
            "",
            "",
            historical_reports={},
        )

        contract = bootstrap["recommendationEvidence"]["market_sentiment"][
            "psy12_shadow_contract"
        ]
        self.assertEqual(contract["status"], "available")
        self.assertFalse(contract["affects_production"])
        self.assertFalse(contract["promotion_eligible"])
        self.assertTrue(contract["promotion_requires_new_authorization"])
        self.assertTrue(contract["legacy_boundary_applied"])
        self.assertNotIn("promotion_eligible", daily["psy12_shadow"])

    def test_unsafe_shadow_promotion_contract_is_rejected_in_html_plane(self):
        report = _report()
        report["psy12_shadow"]["promotion_eligible"] = True
        daily = build_full_daily_projection(report)

        bootstrap = _build_report_bootstrap(
            report,
            daily,
            "",
            "",
            "",
            "",
            historical_reports={},
        )

        contract = bootstrap["recommendationEvidence"]["market_sentiment"][
            "psy12_shadow_contract"
        ]
        self.assertEqual(contract["status"], "invalid")
        self.assertEqual(contract["reason"], "promotion_boundary_conflict")

    def test_missing_aggregate_history_fails_closed_without_fabricated_progress(self):
        report = _report()
        daily = build_full_daily_projection(report)

        bootstrap = _build_report_bootstrap(
            report,
            daily,
            "",
            "",
            "",
            "",
            historical_reports=None,
        )

        audit = bootstrap["recommendationEvidence"]["market_sentiment"][
            "psy12_shadow_audit"
        ]
        self.assertEqual(audit["status"], "missing")
        self.assertEqual(audit["valid_days"], 0)
        self.assertEqual(audit["required_days"], 20)
        self.assertEqual(audit["daily"], [])

    def test_generate_report_reads_existing_aggregate_but_never_rewrites_it(self):
        report = _report()
        formal_before = production_digest(build_formal_output_projection(report))
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            aggregate = {
                "dates": [report["date"]],
                "reports": {
                    report["date"]: build_aggregate_day_projection(report),
                },
            }
            data_path = root / "data.json"
            data_path.write_text(
                json.dumps(aggregate, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            aggregate_before = data_path.read_bytes()

            html_path = Path(generate_report(report, output_dir=tmpdir))
            html = html_path.read_text(encoding="utf-8")
            marker = "window.CHANLUN_BOOTSTRAP = "
            payload = html.split(marker, 1)[1].split(";", 1)[0]
            bootstrap = json.loads(payload)

            audit = bootstrap["recommendationEvidence"]["market_sentiment"][
                "psy12_shadow_audit"
            ]
            self.assertEqual(audit["stored_complete_days"], 1)
            self.assertEqual(audit["required_days"], 20)
            self.assertEqual(data_path.read_bytes(), aggregate_before)
            with (root / "data" / f"{report['date']}.json").open(
                encoding="utf-8"
            ) as handle:
                daily = json.load(handle)
            self.assertNotIn("psy12_shadow_audit", daily)
        self.assertEqual(
            production_digest(build_formal_output_projection(report)),
            formal_before,
        )

    def test_cli_and_page_import_the_same_pure_evaluator(self):
        self.assertIs(cli_evaluator, core_evaluator)

    def test_cli_loader_preserves_bad_or_conflicting_files_for_fail_closed_audit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            good = _report("2026-08-27")
            (root / "2026-08-27.json").write_text(
                json.dumps(good, ensure_ascii=False),
                encoding="utf-8",
            )
            (root / "2026-08-28.json").write_text("{not-json", encoding="utf-8")
            loaded = _load_reports(root, as_of="2026-08-28")

            self.assertEqual(len(loaded), 2)
            failed = cli_evaluator(
                loaded,
                required_days=20,
                as_of_date="2026-08-28",
            )
            self.assertEqual(failed["status"], "missing")
            self.assertEqual(failed["valid_days"], 0)

            (root / "2026-08-28.json").write_text(
                json.dumps(_report("2026-08-26"), ensure_ascii=False),
                encoding="utf-8",
            )
            conflicting = cli_evaluator(
                _load_reports(root, as_of="2026-08-28"),
                required_days=20,
                as_of_date="2026-08-28",
            )
            self.assertEqual(conflicting["status"], "missing")
            self.assertEqual(conflicting["reason"], "conflicting_trade_date")


if __name__ == "__main__":
    unittest.main()
