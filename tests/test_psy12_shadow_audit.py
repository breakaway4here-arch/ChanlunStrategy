"""Pure PSY12 shadow-audit contract tests.

The audit module is deliberately fed already-loaded reports.  These tests do
not grant it permission to discover files or mutate the formal report plane.
"""

import copy
import json
import unittest
from datetime import date, datetime, timedelta
from importlib import import_module

from chanlun.market_sentiment import build_market_sentiment_psy12_shadow


def _api():
    """Turn a missing feature module into a useful RED assertion."""
    try:
        return import_module("chanlun.psy12_shadow_audit")
    except Exception as exc:  # pragma: no cover - exercised only in RED
        raise AssertionError(
            "chanlun.psy12_shadow_audit is not implemented"
        ) from exc


def _market_history(end_date, count=12):
    end = date.fromisoformat(end_date)
    points = []
    for index in range(count):
        trade_date = (end - timedelta(days=count - index - 1)).isoformat()
        points.append({
            "date": trade_date,
            "evidence": {
                "index": {
                    "available": True,
                    "average_change_pct": 0.8 if index % 2 else -0.4,
                }
            },
        })
    return points


def _report(trade_date, *, stored=True):
    components = {
        "breadth": 62.0,
        "limit_ecology": 58.0,
        "index": 49.0,
        "turnover": 54.0,
        "trend": 51.0,
    }
    formal_raw = (
        components["breadth"] * 0.30
        + components["limit_ecology"] * 0.30
        + components["index"] * 0.15
        + components["turnover"] * 0.15
        + components["trend"] * 0.10
    )
    formal = {
        "date": trade_date,
        "score": round(formal_raw),
        "label": "偏强" if round(formal_raw) >= 60 else "平衡",
        "components": components,
    }
    history = _market_history(trade_date)
    fields = build_market_sentiment_psy12_shadow(formal, history)
    report = {
        "date": trade_date,
        "market_sentiment": formal,
        "market_sentiment_history": history,
    }
    if stored:
        report.update(copy.deepcopy(fields))
    return report


def _reports(count=20, start=date(2026, 7, 1), *, stored=True):
    return [
        _report((start + timedelta(days=index)).isoformat(), stored=stored)
        for index in range(count)
    ]


class Psy12ShadowNormalizerTests(unittest.TestCase):

    def test_normalizer_injects_dates_sorts_and_current_overrides_same_day(self):
        module = _api()
        historical = {
            "2026-08-27": _report("2026-08-27"),
            "2026-08-26": _report("2026-08-26"),
            "2026-08-28": _report("2026-08-28"),
        }
        current = _report("2026-08-28")
        current["market_sentiment"]["score"] = 99
        before = copy.deepcopy(historical)

        result = module.normalize_historical_reports(
            historical,
            current_report=current,
            as_of_date="2026-08-28",
        )

        self.assertEqual(result["status"], "available")
        self.assertEqual(result["as_of_date"], "2026-08-28")
        entries = result["reports"]
        self.assertEqual(
            [entry["trade_date"] for entry in entries],
            ["2026-08-26", "2026-08-27", "2026-08-28"],
        )
        self.assertEqual(entries[-1]["source"], "current")
        self.assertEqual(
            entries[-1]["report"]["market_sentiment"]["score"],
            99,
        )
        self.assertEqual(historical, before)

    def test_normalizer_rejects_duplicate_historical_dates(self):
        module = _api()
        historical = [
            {"trade_date": "2026-08-27", "report": _report("2026-08-27")},
            {"trade_date": "2026-08-27", "report": _report("2026-08-27")},
        ]

        result = module.normalize_historical_reports(
            historical,
            as_of_date="2026-08-28",
        )

        self.assertEqual(result["status"], "missing")
        self.assertEqual(result["reason"], "duplicate_trade_date")
        self.assertEqual(result["reports"], [])

    def test_normalizer_rejects_bad_date_future_and_conflicting_inner_date(self):
        module = _api()
        cases = [
            (
                {"2026-8-1": _report("2026-08-01")},
                "invalid_trade_date",
            ),
            (
                {"2026-08-29": _report("2026-08-29")},
                "future_trade_date",
            ),
            (
                {
                    "2026-08-27": {
                        **_report("2026-08-27"),
                        "date": "2026-08-26",
                    }
                },
                "conflicting_trade_date",
            ),
        ]
        for historical, reason in cases:
            with self.subTest(reason=reason):
                result = module.normalize_historical_reports(
                    historical,
                    as_of_date="2026-08-28",
                )
                self.assertEqual(result["status"], "missing")
                self.assertEqual(result["reason"], reason)
                self.assertEqual(result["reports"], [])

    def test_normalizer_rejects_datetime_keys_without_raising(self):
        module = _api()

        result = module.normalize_historical_reports(
            {datetime(2026, 8, 28): {}},
            as_of_date="2026-08-28",
        )

        self.assertEqual(result["status"], "missing")
        self.assertEqual(result["reason"], "invalid_trade_date")
        self.assertEqual(result["reports"], [])

    def test_normalizer_rejects_future_current_and_current_date_mismatch(self):
        module = _api()
        for current_date, reason in (
            ("2026-08-29", "future_trade_date"),
            ("2026-08-27", "current_date_mismatch"),
        ):
            with self.subTest(reason=reason):
                result = module.normalize_historical_reports(
                    {},
                    current_report=_report(current_date),
                    as_of_date="2026-08-28",
                )
                self.assertEqual(result["status"], "missing")
                self.assertEqual(result["reason"], reason)

    def test_normalizer_rejects_non_mapping_or_invalid_as_of_without_partial_progress(self):
        module = _api()
        for historical, as_of, reason in (
            (None, "2026-08-28", "historical_reports_not_mapping"),
            ({"2026-08-27": []}, "2026-08-28", "report_not_mapping"),
            ({"2026-08-27": _report("2026-08-27")}, "2026-8-28", "invalid_as_of_date"),
        ):
            with self.subTest(reason=reason):
                result = module.normalize_historical_reports(
                    historical,
                    as_of_date=as_of,
                )
                self.assertEqual(result["status"], "missing")
                self.assertEqual(result["reason"], reason)
                self.assertEqual(result["reports"], [])


class Psy12ShadowAuditTests(unittest.TestCase):

    def test_twenty_complete_stored_days_are_ready_only_for_manual_review(self):
        module = _api()
        reports = _reports()
        normalized = module.normalize_historical_reports(
            {report["date"]: report for report in reports},
            as_of_date=reports[-1]["date"],
        )

        result = module.evaluate_psy12_shadow_audit(
            normalized,
            required_days=20,
        )

        self.assertEqual(result["status"], "ready_for_manual_review")
        self.assertEqual(result["required_days"], 20)
        self.assertEqual(result["valid_days"], 20)
        self.assertEqual(result["stored_complete_days"], 20)
        self.assertEqual(result["recomputable_days"], 20)
        self.assertEqual(result["complete_days"], 20)
        self.assertEqual(result["missing_days"], 0)
        self.assertEqual(result["mismatch_days"], 0)
        self.assertFalse(result["affects_production"])
        self.assertFalse(result["promotion_eligible"])
        self.assertTrue(result["promotion_requires_new_authorization"])

    def test_missing_stored_day_does_not_count_toward_twenty_day_gate(self):
        module = _api()
        reports = _reports()
        reports[4].pop("psy12_shadow")
        normalized = module.normalize_historical_reports(
            {report["date"]: report for report in reports},
            as_of_date=reports[-1]["date"],
        )

        result = module.evaluate_psy12_shadow_audit(
            normalized,
            required_days=20,
        )

        self.assertEqual(result["status"], "insufficient_observation_days")
        self.assertEqual(result["valid_days"], 19)
        self.assertEqual(result["stored_complete_days"], 19)
        self.assertEqual(result["recomputable_days"], 20)
        self.assertEqual(result["complete_days"], 19)
        self.assertEqual(result["missing_days"], 1)
        self.assertEqual(result["mismatch_days"], 0)
        self.assertFalse(result["promotion_eligible"])

    def test_stored_mismatch_blocks_manual_review_without_becoming_promotion(self):
        module = _api()
        reports = _reports()
        reports[-1]["psy12_shadow"]["shadow_score_with_psy12"] += 1
        normalized = module.normalize_historical_reports(
            {report["date"]: report for report in reports},
            as_of_date=reports[-1]["date"],
        )

        result = module.evaluate_psy12_shadow_audit(
            normalized,
            required_days=20,
        )

        self.assertEqual(result["status"], "recalculation_mismatch")
        self.assertEqual(result["valid_days"], 20)
        self.assertEqual(result["stored_complete_days"], 20)
        self.assertEqual(result["recomputable_days"], 20)
        self.assertEqual(result["complete_days"], 19)
        self.assertEqual(result["mismatch_days"], 1)
        self.assertLess(result["recalculation_consistency_rate"], 1.0)
        self.assertFalse(result["promotion_eligible"])

    def test_unsafe_stored_shadow_is_missing_and_cannot_enter_gate(self):
        module = _api()
        reports = _reports()
        reports[-1]["psy12_shadow"]["affects_production"] = True
        normalized = module.normalize_historical_reports(
            {report["date"]: report for report in reports},
            as_of_date=reports[-1]["date"],
        )

        result = module.evaluate_psy12_shadow_audit(
            normalized,
            required_days=20,
        )

        self.assertEqual(result["status"], "insufficient_observation_days")
        self.assertEqual(result["valid_days"], 19)
        self.assertEqual(result["missing_days"], 1)
        self.assertFalse(result["affects_production"])

    def test_unsafe_stored_promotion_contract_cannot_enter_gate(self):
        module = _api()
        for field, value in (
            ("promotion_eligible", True),
            ("promotion_requires_new_authorization", False),
        ):
            with self.subTest(field=field):
                reports = _reports()
                reports[-1]["psy12_shadow"][field] = value
                normalized = module.normalize_historical_reports(
                    {report["date"]: report for report in reports},
                    as_of_date=reports[-1]["date"],
                )

                result = module.evaluate_psy12_shadow_audit(
                    normalized,
                    required_days=20,
                )

                self.assertEqual(
                    result["status"],
                    "insufficient_observation_days",
                )
                self.assertEqual(result["stored_complete_days"], 19)
                self.assertEqual(result["missing_days"], 1)
                self.assertFalse(result["promotion_eligible"])
                self.assertTrue(
                    result["promotion_requires_new_authorization"]
                )

    def test_missing_history_returns_explicit_missing_without_progress(self):
        module = _api()
        normalized = module.normalize_historical_reports(
            {},
            as_of_date="2026-08-28",
        )

        result = module.evaluate_psy12_shadow_audit(normalized, required_days=20)

        self.assertEqual(result["status"], "missing")
        self.assertEqual(result["reason"], "no_historical_reports")
        self.assertEqual(result["valid_days"], 0)
        self.assertEqual(result["required_days"], 20)
        self.assertEqual(result["daily"], [])
        self.assertFalse(result["promotion_eligible"])

    def test_audit_rejects_invalid_normalized_input_instead_of_partial_progress(self):
        module = _api()
        result = module.evaluate_psy12_shadow_audit(
            {"status": "available", "reports": [{"bad": True}]},
            required_days=20,
        )

        self.assertEqual(result["status"], "missing")
        self.assertEqual(result["reason"], "invalid_normalized_report")
        self.assertEqual(result["valid_days"], 0)
        self.assertEqual(result["daily"], [])

    def test_legacy_list_adapter_uses_the_same_pure_audit_contract(self):
        module = _api()
        result = module.evaluate_shadow_reports(_reports(), required_days=20)

        self.assertEqual(result["status"], "ready_for_manual_review")
        self.assertEqual(result["valid_days"], 20)
        self.assertEqual(result["stored_complete_days"], 20)

    def test_audit_output_is_strict_json_native(self):
        module = _api()
        normalized = module.normalize_historical_reports(
            {"2026-08-28": _report("2026-08-28")},
            as_of_date="2026-08-28",
        )
        result = module.evaluate_psy12_shadow_audit(normalized, required_days=20)

        encoded = json.dumps(result, ensure_ascii=False, allow_nan=False)
        self.assertEqual(json.loads(encoded), result)


if __name__ == "__main__":
    unittest.main()
