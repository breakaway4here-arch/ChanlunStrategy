import tempfile
import unittest
from pathlib import Path

from chanlun.candidate_funnel import CandidateFunnel, FUNNEL_STAGES
from chanlun.market_history_store import MarketHistoryStore


class CandidateFunnelTest(unittest.TestCase):
    def test_first_failure_is_recorded_once_and_raw_features_are_preserved(self):
        funnel = CandidateFunnel("run-1", "2026-07-15")
        funnel.register(
            {
                "code": "000001",
                "source_channel": "trend",
                "retrieval_pool": "base",
                "low_position_retrieval_score": 72.5,
                "trend_retrieval_score": 68.0,
                "neutral_retrieval_score": 55.0,
                "volume_ratio": 1.31,
                "amount_ratio": 1.08,
                "distance_3pct": 0.027,
                "distance_12pct": 0.084,
                "distance_from_reference_pct": 2.7,
                "ma5": 10.5,
                "ma10": 10.2,
                "ma20": 9.9,
                "ma_gap_pct": 0.029,
                "ma_direction": "up",
            }
        )
        funnel.pass_stage("000001", "eligible")
        funnel.fail_stage(
            "000001",
            "daily_channel",
            "volume_ratio_below_threshold",
            actual_value=1.31,
            threshold=1.5,
        )
        funnel.fail_stage(
            "000001",
            "minute30",
            "minute30_not_confirmed",
            actual_value=1,
            threshold=2,
        )
        funnel.finalize(main_codes=[], observation_codes=[])

        event = funnel.events[0]
        self.assertEqual("daily_channel", event["first_failure_gate"])
        self.assertEqual(
            "volume_ratio_below_threshold", event["first_failure_reason"]
        )
        self.assertEqual(1.31, event["actual_value"])
        self.assertEqual(1.5, event["threshold"])
        self.assertEqual(1.31, event["volume_ratio"])
        self.assertEqual(72.5, event["low_position_retrieval_score"])
        self.assertEqual(68.0, event["trend_retrieval_score"])
        self.assertEqual(55.0, event["neutral_retrieval_score"])
        self.assertEqual(1.08, event["amount_ratio"])
        self.assertEqual(0.027, event["distance_3pct"])
        self.assertEqual(0.084, event["distance_12pct"])
        self.assertEqual(2.7, event["distance_from_reference_pct"])
        self.assertEqual(10.5, event["ma5"])
        self.assertEqual(10.2, event["ma10"])
        self.assertEqual(9.9, event["ma20"])
        self.assertEqual(0.029, event["ma_gap_pct"])
        self.assertEqual("up", event["ma_direction"])
        self.assertEqual("reject", event["final_state"])

    def test_stage_order_and_terminal_states_are_complete(self):
        funnel = CandidateFunnel("run-2", "2026-07-15")
        for code in ("000001", "000002", "000003"):
            funnel.register({"code": code})
            funnel.pass_stage(code, "eligible")
            funnel.pass_stage(code, "retrieval")
            funnel.pass_stage(code, "daily_channel")

        funnel.pass_stage("000001", "minute30")
        funnel.pass_stage("000001", "fusion")
        funnel.pass_stage("000001", "display")
        funnel.pass_stage("000002", "minute30")
        funnel.fail_stage("000003", "minute30", "minute30_not_confirmed")
        funnel.finalize(
            main_codes=["000001"],
            observation_codes=["000002"],
        )

        self.assertEqual(
            ["full_a", "eligible", "retrieval", "daily_channel", "minute30", "fusion", "display"],
            funnel.event_for("000001")["passed_stages"],
        )
        self.assertEqual(list(FUNNEL_STAGES), sorted(
            FUNNEL_STAGES, key=FUNNEL_STAGES.index
        ))
        self.assertEqual("main", funnel.event_for("000001")["final_state"])
        self.assertEqual("observe", funnel.event_for("000002")["final_state"])
        self.assertEqual("reject", funnel.event_for("000003")["final_state"])
        self.assertEqual(
            {"main": 1, "observe": 1, "reject": 1},
            funnel.summary()["terminal_counts"],
        )

    def test_funnel_run_and_events_persist_to_single_market_database(self):
        funnel = CandidateFunnel("run-3", "2026-07-15")
        funnel.register(
            {
                "code": "600001",
                "source_channel": "low_position",
                "retrieval_sources": ["low_position", "neutral"],
                "retrieval_score": 78.5,
                "data_quality": {"daily": "verified"},
            }
        )
        funnel.pass_stage("600001", "eligible")
        funnel.pass_stage("600001", "retrieval")
        funnel.finalize(main_codes=[], observation_codes=["600001"])

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "market.sqlite"
            with MarketHistoryStore(path) as store:
                store.save_candidate_funnel(
                    funnel.run_record(metadata={"mode": "test"}),
                    funnel.events,
                )
                saved_run = store.get_funnel_run("run-3")
                saved_events = store.list_gate_events("run-3")

        self.assertEqual("2026-07-15", saved_run["report_date"])
        self.assertEqual("complete", saved_run["status"])
        self.assertEqual({"mode": "test"}, saved_run["metadata"])
        self.assertEqual(1, len(saved_events))
        self.assertEqual("observe", saved_events[0]["final_state"])
        self.assertEqual(
            ["low_position", "neutral"],
            saved_events[0]["retrieval_sources"],
        )
        self.assertEqual(
            {"daily": "verified"},
            saved_events[0]["data_quality"],
        )

    def test_report_date_is_the_as_of_boundary(self):
        with self.assertRaises(ValueError):
            CandidateFunnel("run-4", "2026-07-15", as_of="2026-07-16")


if __name__ == "__main__":
    unittest.main()
