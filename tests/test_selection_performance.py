"""Published-list price observations have their own six-horizon contract."""

import datetime as dt
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from chanlun.selection_performance import (
    HORIZONS,
    _theme_refs,
    _trading_calendar,
    _strategy_refs,
    aggregate_selection_performance,
    build_selection_performance,
    evaluate_observations,
    load_published_observations,
    write_selection_performance,
)
from chanlun.report_comparison import (
    _published_member_receipt, _workbench_review_entries,
)
from scripts.build_selection_performance import main as build_cli


def _calendar(start, count):
    day = dt.date.fromisoformat(start)
    dates = []
    while len(dates) < count:
        if day.weekday() < 5:
            dates.append(day.isoformat())
        day += dt.timedelta(days=1)
    return dates


def _series(identity, dates, milestones):
    bars = [
        {"date": day, "close": milestones.get(i, 100), "is_final": True}
        for i, day in enumerate(dates)
    ]
    digest = hashlib.sha256(json.dumps(
        bars, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()
    response = {
        "instrument_id": identity, "adjustment": "qfq",
        "provider": "frozen-fixture", "bars": bars,
    }
    response_digest = hashlib.sha256(json.dumps(
        response, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()
    return {
        "instrument_id": identity,
        "series_ref": "fixture:" + identity,
        "adjustment": "qfq",
        "basis_evidence": {
            "status": "verified", "kind": "single_historical_response",
            "content_sha256": digest, "response_sha256": response_digest,
            "source_ref": "frozen-fixture:" + identity,
        },
        "source_response": response,
        "bars": bars,
    }


class SelectionPerformanceTests(unittest.TestCase):
    def setUp(self):
        self.dates = _calendar("2026-08-03", 31)
        self.observations = [
            {"observation_id": "o:" + code, "instrument_id": "SH" + code,
             "code": code, "name": name, "report_date": self.dates[0],
             "source_views": ["main"], "strategy_refs": [], "theme_refs": [],
             "publication_ref": {"snapshot_id": "published-test"}}
            for code, name in (("600001", "甲"), ("600002", "乙"), ("600003", "丙"))
        ]
        points = {
            "SH600001": {1: 110, 3: 105, 5: 120, 10: 130, 20: 110, 30: 140},
            "SH600002": {1: 95, 3: 110, 5: 90, 10: 80, 20: 105, 30: 90},
            "SH600003": {1: 100, 3: 100, 5: 110, 10: 90, 20: 95, 30: 100},
        }
        self.series = {
            identity: _series(identity, self.dates, milestones)
            for identity, milestones in points.items()
        }

    def test_full_six_horizon_close_results_and_extrema(self):
        self.assertEqual(HORIZONS, (1, 3, 5, 10, 20, 30))
        observed = evaluate_observations(
            self.observations, self.dates, self.series, self.dates[-1]
        )
        dataset = {"observations": observed, "horizons": list(HORIZONS)}
        expected = {
            1: (1.6666666667, "甲", "乙"),
            3: (5, "乙", "丙"),
            5: (6.6666666667, "甲", "乙"),
            10: (0, "甲", "乙"),
            20: (3.3333333333, "甲", "丙"),
            30: (10, "甲", "乙"),
        }
        for horizon, (mean, best, worst) in expected.items():
            with self.subTest(horizon=horizon):
                key = "t{}".format(horizon)
                self.assertEqual([o["outcomes"][key]["status"] for o in observed],
                                 ["ready"] * 3)
                group = aggregate_selection_performance(dataset, horizon=horizon)
                self.assertEqual(group["counts"]["ready"], 3)
                self.assertAlmostEqual(group["mean_return_pct"], mean)
                if horizon == 10:
                    self.assertEqual(group["mean_return_pct"], 0)
                self.assertEqual(group["best_observations"][0]["name"], best)
                self.assertEqual(group["worst_observations"][0]["name"], worst)
                self.assertEqual(group["best_observations"][0]["publication_ref"],
                                 {"snapshot_id": "published-test"})
                self.assertTrue(group["best_observations"][0]["price_series_ref"])
        self.assertAlmostEqual(observed[0]["outcomes"]["t5"]["return_pct"], 20)

    def test_waiting_missing_zero_and_unverified_basis_stay_distinct(self):
        self.series["SH600003"]["bars"] = [
            bar for bar in self.series["SH600003"]["bars"]
            if bar["date"] != self.dates[20]
        ]
        bars = self.series["SH600003"]["bars"]
        self.series["SH600003"]["basis_evidence"]["content_sha256"] = (
            hashlib.sha256(json.dumps(
                bars, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            ).encode()).hexdigest()
        )
        self.series["SH600003"]["source_response"]["bars"] = bars
        self.series["SH600003"]["basis_evidence"]["response_sha256"] = (
            hashlib.sha256(json.dumps(
                self.series["SH600003"]["source_response"],
                ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            ).encode()).hexdigest()
        )
        observed = evaluate_observations(
            self.observations, self.dates, self.series, self.dates[20]
        )
        self.assertEqual(observed[0]["outcomes"]["t30"]["status"], "waiting")
        self.assertEqual(observed[2]["outcomes"]["t20"]["status"], "missing_price")
        self.assertEqual(observed[2]["outcomes"]["t1"]["return_pct"], 0)
        group = aggregate_selection_performance(
            {"observations": observed}, horizon=20
        )
        self.assertEqual(group["counts"]["ready"], 2)
        self.assertEqual(group["counts"]["missing_price"], 1)
        self.assertAlmostEqual(group["mean_return_pct"], 7.5)
        self.series["SH600003"]["basis_evidence"]["content_sha256"] = "0" * 64
        unverified = evaluate_observations(
            self.observations, self.dates, self.series, self.dates[20]
        )
        self.assertEqual(unverified[2]["outcomes"]["t1"]["status"],
                         "price_basis_unverified")

    def test_signed_bar_metadata_conflict_cannot_prove_same_price_series(self):
        for conflict in (
            {"instrument_id": "SZ000001"}, {"adjustment": "hfq"},
            {"code": "000001"}, {"exchange": "SZ"},
            {"asset_type": "index"},
        ):
            with self.subTest(conflict=conflict):
                series = json.loads(json.dumps(self.series["SH600001"]))
                series["bars"][0].update(conflict)
                series["source_response"]["bars"] = series["bars"]
                encode = lambda value: json.dumps(
                    value, ensure_ascii=False, sort_keys=True,
                    separators=(",", ":"),
                ).encode()
                series["basis_evidence"]["content_sha256"] = hashlib.sha256(
                    encode(series["bars"])).hexdigest()
                series["basis_evidence"]["response_sha256"] = hashlib.sha256(
                    encode(series["source_response"])).hexdigest()
                observed = evaluate_observations(
                    self.observations[:1], self.dates,
                    {"SH600001": series}, self.dates[-1],
                )
                self.assertEqual(observed[0]["outcomes"]["t1"]["status"],
                                 "price_basis_unverified")
        valid = json.loads(json.dumps(self.series["SH600001"]))
        for bar in valid["bars"]:
            bar.update({"instrument_id": "SH600001", "adjustment": "qfq",
                        "code": "600001", "exchange": "SH", "asset_type": "stock"})
        valid["source_response"]["bars"] = valid["bars"]
        valid["basis_evidence"]["content_sha256"] = hashlib.sha256(
            encode(valid["bars"])).hexdigest()
        valid["basis_evidence"]["response_sha256"] = hashlib.sha256(
            encode(valid["source_response"])).hexdigest()
        self.assertEqual(evaluate_observations(
            self.observations[:1], self.dates, {"SH600001": valid},
            self.dates[-1],
        )[0]["outcomes"]["t1"]["status"], "ready")

    def test_historical_nonfinal_is_missing_and_target_day_intraday_waits(self):
        self.series["SH600001"]["bars"][1]["is_final"] = False
        self.series["SH600001"] = _series(
            "SH600001", self.dates, {1: 110}
        )
        self.series["SH600001"]["bars"][1]["is_final"] = False
        self.series["SH600001"]["source_response"]["bars"] = self.series["SH600001"]["bars"]
        self.series["SH600001"]["basis_evidence"]["content_sha256"] = (
            hashlib.sha256(json.dumps(
                self.series["SH600001"]["bars"], ensure_ascii=False,
                sort_keys=True, separators=(",", ":"),
            ).encode()).hexdigest()
        )
        self.series["SH600001"]["basis_evidence"]["response_sha256"] = (
            hashlib.sha256(json.dumps(
                self.series["SH600001"]["source_response"],
                ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            ).encode()).hexdigest()
        )
        mature = evaluate_observations(
            self.observations, self.dates, self.series, self.dates[3]
        )
        self.assertEqual(mature[0]["outcomes"]["t1"]["status"], "missing_price")
        self.assertEqual(mature[0]["outcomes"]["t1"]["reason_code"],
                         "target_close_unconfirmed")
        waiting = evaluate_observations(
            self.observations, self.dates, self.series,
            self.dates[3] + "T14:30:00+08:00",
        )
        self.assertEqual(waiting[1]["outcomes"]["t3"]["status"], "waiting")

    def test_final_zero_volume_target_is_not_a_traded_close(self):
        series = self.series["SH600001"]
        series["bars"][1]["volume"] = 0
        series["basis_evidence"]["content_sha256"] = hashlib.sha256(json.dumps(
            series["bars"], ensure_ascii=False, sort_keys=True,
            separators=(",", ":"),
        ).encode()).hexdigest()
        series["basis_evidence"]["response_sha256"] = hashlib.sha256(json.dumps(
            series["source_response"], ensure_ascii=False, sort_keys=True,
            separators=(",", ":"),
        ).encode()).hexdigest()
        observed = evaluate_observations(
            self.observations, self.dates, self.series, self.dates[3]
        )
        self.assertEqual(observed[0]["outcomes"]["t1"]["status"], "missing_price")
        self.assertEqual(observed[0]["outcomes"]["t1"]["reason_code"],
                         "target_no_traded_close")

    def test_strategy_and_role_filters_match_the_same_source(self):
        self.observations[0]["strategy_refs"] = [
            {"strategy_key": "formal-a", "role": "formal"},
            {"strategy_key": "research-b", "role": "research"},
        ]
        rows = evaluate_observations(
            self.observations, self.dates, self.series, self.dates[-1]
        )
        dataset = {"observations": rows}
        bad_pair = aggregate_selection_performance(
            dataset, horizon=1, strategy_key="research-b", role="formal"
        )
        self.assertEqual(bad_pair["total_observations"], 0)
        valid_pair = aggregate_selection_performance(
            dataset, horizon=1, strategy_key="research-b", role="research"
        )
        self.assertEqual(valid_pair["total_observations"], 1)

    def test_unrecorded_theme_and_overlapping_themes_keep_global_denominator(self):
        self.observations[0]["theme_refs"] = [
            {"theme_id": "kaipanla:ai", "name": "AI应用"},
        ]
        self.observations[1]["theme_refs"] = [
            {"theme_id": "kaipanla:battery", "name": "电池"},
        ]
        self.observations[2]["theme_refs"] = [
            {"theme_id": "kaipanla:ai", "name": "AI应用"},
            {"theme_id": "kaipanla:battery", "name": "电池"},
        ]
        dataset = {"observations": evaluate_observations(
            self.observations, self.dates, self.series, self.dates[-1]
        )}
        self.assertEqual(aggregate_selection_performance(
            dataset, horizon=1)["total_observations"], 3)
        self.assertEqual(aggregate_selection_performance(
            dataset, horizon=1, theme_id="kaipanla:ai")["total_observations"], 2)
        self.assertEqual(aggregate_selection_performance(
            dataset, horizon=1, theme_id="kaipanla:battery")["total_observations"], 2)
        self.observations[2]["theme_refs"] = []
        dataset = {"observations": evaluate_observations(
            self.observations, self.dates, self.series, self.dates[-1]
        )}
        self.assertEqual(aggregate_selection_performance(
            dataset, horizon=1, theme_id="unrecorded")["total_observations"], 1)

    def test_partial_theme_keeps_known_members_and_name_only_scope(self):
        report = {"date": self.dates[0], "kaipanla_context": {
            "source": "kaipanla", "status": "partial",
            "data_date": self.dates[0],
            "fetched_at": self.dates[0] + "T14:00:00+08:00",
            "groups": [
                "bad group",
                {"code": "ai", "name": "AI应用", "stock_list_status": "partial",
                 "stocks": [{"code": "600001"}, "bad stock"]},
                {"code": "", "name": "仅名称题材", "stocks": [{"code": "600001"}]},
                {"code": "broken", "name": "坏股票组", "stocks": "not-a-list"},
            ],
        }}
        refs = _theme_refs(report, self.dates[0] + "T15:20:00+08:00", "600001")
        self.assertEqual(len(refs), 2)
        self.assertEqual(refs[0]["theme_id"], "kaipanla:ai")
        self.assertEqual(refs[1]["identity_status"], "name_only")
        self.assertTrue(refs[1]["theme_id"].startswith("kaipanla:name:"))
        self.assertEqual(_theme_refs(
            report, self.dates[0] + "T13:00:00+08:00", "600001"
        ), [])

    def test_incomplete_unknown_year_calendar_does_not_skip_gap_to_later_open_day(self):
        with tempfile.TemporaryDirectory() as root:
            db = Path(root) / "calendar.sqlite"
            connection = sqlite3.connect(str(db))
            connection.execute("CREATE TABLE trade_calendar (exchange TEXT, trade_date TEXT, is_open INTEGER)")
            for day in ("2027-01-04", "2027-01-06"):
                for exchange in ("SH", "SZ"):
                    connection.execute("INSERT INTO trade_calendar VALUES (?,?,1)", (exchange, day))
            connection.commit()
            connection.close()
            calendar = _trading_calendar(db, "2027-01-04", "2027-01-04")
            self.assertNotIn("2027-01-06", calendar)

    def test_conflicting_exchange_calendar_does_not_shift_unknown_year_target(self):
        with tempfile.TemporaryDirectory() as root:
            db = Path(root) / "calendar.sqlite"
            connection = sqlite3.connect(str(db))
            connection.execute("CREATE TABLE trade_calendar (exchange TEXT, trade_date TEXT, is_open INTEGER)")
            for exchange, day, flag in (
                ("SH", "2027-01-04", 1), ("SZ", "2027-01-04", 1),
                ("SH", "2027-01-05", 1), ("SZ", "2027-01-05", 0),
                ("SH", "2027-01-06", 1), ("SZ", "2027-01-06", 1),
            ):
                connection.execute("INSERT INTO trade_calendar VALUES (?,?,?)",
                                   (exchange, day, flag))
            connection.commit()
            connection.close()
            calendar = _trading_calendar(db, "2027-01-04", "2027-01-04")
            self.assertNotIn("2027-01-06", calendar)

    def test_partial_strategy_group_key_does_not_expose_untrusted_snapshot_text(self):
        refs = _strategy_refs(
            [{"view": "unknown-view", "role": "research", "score": 1}],
            {}, "2026-08-03", "<script>alert(1)</script>",
        )
        self.assertEqual(refs[0]["identity_status"], "partial")
        self.assertNotIn("<", refs[0]["strategy_key"])
        self.assertNotIn("/", refs[0]["strategy_key"])

    def test_strategy_identity_key_preserves_intended_horizon_and_decision_version(self):
        source = {"view": "main", "role": "formal", "strategy_version": "v1",
                  "policy_version": "p1", "decision_version": "d1",
                  "formal_performance_status": "formal_eligible", "action": "可上车"}
        identity = {"strategy_id": "daily_fusion", "strategy_version": "v1",
                    "policy_version": "p1", "source_pool": "picks_fusion",
                    "entry_mode": "immediate_close", "intended_horizon": 3,
                    "research_tier": None}
        first = _strategy_refs([source], {"strategy_identities": [identity]},
                               "2026-08-03", "snap")[0]
        second = _strategy_refs([source], {"strategy_identities": [
            dict(identity, intended_horizon=5)]}, "2026-08-03", "snap")[0]
        third = _strategy_refs([dict(source, decision_version="d2")],
                               {"strategy_identities": [identity]},
                               "2026-08-03", "snap")[0]
        self.assertEqual(first["identity_status"], "complete")
        self.assertEqual(first["intended_horizon"], 3)
        self.assertNotEqual(first["strategy_key"], second["strategy_key"])
        self.assertNotEqual(first["strategy_key"], third["strategy_key"])

    def test_formal_recommendation_requires_same_eligible_action_source(self):
        base = {"view": "main", "role": "formal", "action": "可上车",
                "formal_performance_status": "formal_eligible"}
        chosen = _strategy_refs([base], {}, "2026-08-03", "snap")[0]
        watch = _strategy_refs([dict(base, action="仅观察")], {},
                               "2026-08-03", "snap")[0]
        blocked = _strategy_refs([dict(base,
                                       formal_performance_status="formal_input_blocked")],
                                 {}, "2026-08-03", "snap")[0]
        research = _strategy_refs([dict(base, role="research")], {},
                                  "2026-08-03", "snap")[0]
        self.assertEqual(chosen["recommendation_scope"], "formal_recommendation")
        for ref in (watch, blocked, research):
            self.assertNotEqual(ref["recommendation_scope"], "formal_recommendation")
        self.observations[0]["strategy_refs"] = [chosen, research]
        self.observations[1]["strategy_refs"] = [watch]
        self.observations[2]["strategy_refs"] = [blocked]
        rows = evaluate_observations(self.observations, self.dates,
                                     self.series, self.dates[-1])
        dataset = {"observations": rows}
        formal = aggregate_selection_performance(
            dataset, horizon=1, recommendation_scope="formal_recommendation"
        )
        self.assertEqual(formal["total_observations"], 1)
        impossible = aggregate_selection_performance(
            dataset, horizon=1, strategy_key=research["strategy_key"],
            recommendation_scope="formal_recommendation"
        )
        self.assertEqual(impossible["total_observations"], 0)

    def test_display_rounding_does_not_create_false_ties_and_negative_best_is_negative(self):
        self.series["SH600001"] = _series("SH600001", self.dates, {1: 99.004})
        self.series["SH600002"] = _series("SH600002", self.dates, {1: 99.003})
        self.series["SH600003"] = _series("SH600003", self.dates, {1: 90})
        rows = evaluate_observations(
            self.observations, self.dates, self.series, self.dates[1]
        )
        group = aggregate_selection_performance({"observations": rows}, horizon=1)
        self.assertEqual(len(group["best_observations"]), 1)
        self.assertEqual(group["best_observations"][0]["name"], "甲")
        self.assertLess(group["best_observations"][0]["return_pct"], 0)
        self.assertEqual(group["worst_observations"][0]["name"], "丙")

    def test_full_builder_uses_one_published_cohort_for_six_periods_and_themes(self):
        with tempfile.TemporaryDirectory() as root:
            data = Path(root) / "data"
            data.mkdir()
            d0 = self.dates[0]
            (data / "index.json").write_text(json.dumps({"dates": [d0]}))
            report = {"date": d0, "kaipanla_context": {
                "status": "available", "source": "kaipanla", "data_date": d0,
                "fetched_at": d0 + "T14:00:00+08:00",
                "groups": [
                    {"code": "ai", "name": "AI应用", "stocks": [
                        {"code": "600001"}, {"code": "600003"}]},
                    {"code": "battery", "name": "电池", "stocks": [
                        {"code": "600002"}, {"code": "600003"}]},
                ],
            }}
            (data / (d0 + ".json")).write_text(json.dumps(report))
            workbench = {
                "schema_version": "decision-workbench-v1",
                "report_date": d0, "snapshot_id": "formal-published",
                "phase": "formal", "as_of": d0 + "T15:20:00+08:00",
                "comparison_contract": {}, "items": [
                    {"code": o["code"], "instrument_id": o["instrument_id"],
                     "name": o["name"], "strategy_results": [{
                         "strategy_id": "main", "role": "formal", "score": 10,
                         "candidate": {"strategy_version": "v1"},
                     }]}
                    for o in self.observations
                ],
            }
            html = data.parent / d0 / "index.html"
            html.parent.mkdir()
            html.write_text("<script>window.CHANLUN_BOOTSTRAP= " + json.dumps({
                "pageDate": d0, "inlineReportData": report,
                "decisionWorkbench": workbench,
            }, ensure_ascii=False) + ";</script>")
            series_file = Path(root) / "series.json"
            series_file.write_text(json.dumps({
                "schema_version": "verified-price-series-v1",
                "series": list(self.series.values()),
            }, ensure_ascii=False))
            dataset = build_selection_performance(
                data, Path(root) / "absent.sqlite", d0, self.dates[-1],
                price_series_file=series_file,
            )
            self.assertEqual(dataset["coverage"]["registered_observations"], 3)
            self.assertEqual(dataset["trading_dates"][-1], d0)
            self.assertGreaterEqual(len(dataset["trading_dates"]), 60)
            self.assertLess(dataset["trading_dates"][0], d0)
            self.assertEqual(dataset["summary"]["t30"]["counts"]["ready"], 3)
            self.assertEqual(dataset["summary"]["t30"]["best_observations"][0]["name"], "甲")
            self.assertEqual(dataset["groups"]["themes"]["kaipanla:ai"]["horizons"]["t1"]
                             ["total_observations"], 2)
            self.assertEqual(dataset["groups"]["themes"]["kaipanla:battery"]["horizons"]["t1"]
                             ["total_observations"], 2)
            self.assertEqual(dataset["summary"]["t1"]["total_observations"], 3)

    def test_all_saved_dates_use_only_bound_published_members_and_keep_sources(self):
        with tempfile.TemporaryDirectory() as root:
            data = Path(root) / "data"
            data.mkdir()
            (data / "index.json").write_text(json.dumps({
                "dates": ["2026-08-04"],
            }))
            report = {"date": "2026-08-03", "kaipanla_context": {
                "status": "available", "data_date": "2026-08-03",
                "fetched_at": "2026-08-03T17:30:00+08:00", "groups": [{
                    "code": "theme-a", "name": "甲题材", "stocks": [{"code": "600001"}],
                }],
            }}
            (data / "2026-08-03.json").write_text(json.dumps(report))
            (data / "2026-08-04.json").write_text(json.dumps({
                "date": "2026-08-04", "picks_pure": [{"code": "600002"}],
            }))
            workbench = {
                "schema_version": "decision-workbench-v1",
                "report_date": "2026-08-03", "snapshot_id": "published-a",
                "phase": "formal", "comparison_contract": {}, "items": [{
                    "code": "600001", "instrument_id": "SH600001", "name": "甲",
                    "strategy_results": [
                        {"strategy_id": "main", "role": "formal", "score": 12,
                         "candidate": {"strategy_version": "v1"}},
                        {"strategy_id": "highlights", "role": "research", "score": 7,
                         "candidate": {"strategy_version": "v2"}},
                    ],
                }],
            }
            entries = _workbench_review_entries(
                report, "2026-08-03", workbench,
                "current_generation_bootstrap", "confirmed_display_snapshot",
            )
            receipt = _published_member_receipt(
                report, "2026-08-03", workbench,
                "current_generation_bootstrap", entries,
            )
            (data / "comparison-index.json").write_text(json.dumps({
                "review_registry": {"published_member_snapshots": {
                    "2026-08-03": receipt,
                }},
            }))
            result = load_published_observations(data, "2026-08-04")
            self.assertEqual(result["coverage"]["saved_report_dates"], 2)
            self.assertEqual(result["coverage"]["published_report_dates"], 1)
            self.assertEqual(result["coverage"]["unproven_report_dates"], 1)
            self.assertEqual(len(result["observations"]), 1)
            row = result["observations"][0]
            self.assertEqual(row["instrument_id"], "SH600001")
            self.assertEqual(len(row["strategy_refs"]), 2)
            self.assertIsNone(row["strategy_refs"][0]["score_definition"])
            self.assertEqual(row["strategy_refs"][0]["score_definition_status"],
                             "unrecorded")
            self.assertEqual(row["theme_refs"], [])

    def test_build_does_not_create_missing_market_db_or_promote_raw_candidates(self):
        with tempfile.TemporaryDirectory() as root:
            data = Path(root) / "data"
            data.mkdir()
            (data / "index.json").write_text(json.dumps({
                "dates": ["2026-08-02", "2026-08-03"],
                "date_meta": {"2026-08-02": {"is_trading_day": False}},
            }))
            (data / "2026-08-02.json").write_text(json.dumps({
                "date": "2026-08-02", "picks_pure": [{"code": "600099"}],
            }))
            (data / "2026-08-03.json").write_text(json.dumps({
                "date": "2026-08-03", "picks_pure": [{"code": "600001"}],
            }))
            db = Path(root) / "never-create.sqlite"
            result = build_selection_performance(
                data, db, "2026-08-03", "2026-08-04T14:30:00+08:00"
            )
            self.assertFalse(db.exists())
            self.assertEqual(result["observations"], [])
            self.assertEqual(result["coverage"]["unproven_report_dates"], 1)
            self.assertEqual(result["coverage"]["listed_report_dates"], 2)
            self.assertEqual(result["coverage"]["nontrading_report_dates"], 1)
            self.assertEqual(result["summary"]["t1"]["counts"]["ready"], 0)
            self.assertIsNone(result["summary"]["t1"]["mean_return_pct"])
            output = Path(root) / "derived"
            target = write_selection_performance(result, output)
            first_bytes = target.read_bytes()
            self.assertEqual(target.name, "selection-performance.json")
            self.assertEqual(write_selection_performance(result, output), target)
            self.assertEqual(target.read_bytes(), first_bytes)
            changed = json.loads(json.dumps(result))
            changed["summary"]["t1"]["total_observations"] = 77
            write_selection_performance(changed, output)
            self.assertEqual(json.loads(target.read_text())["summary"]["t1"]
                             ["total_observations"], 77)
            cli_output = Path(root) / "cli-derived"
            self.assertEqual(build_cli([
                "--reports-dir", str(data),
                "--market-db", str(db),
                "--report-as-of", "2026-08-03",
                "--evaluation-as-of", "2026-08-04T14:30:00+08:00",
                "--output-dir", str(cli_output),
            ]), 0)
            self.assertTrue((cli_output / "selection-performance.json").is_file())


if __name__ == "__main__":
    unittest.main()
