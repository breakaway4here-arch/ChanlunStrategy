import tempfile
import unittest
from pathlib import Path

from chanlun.candidate_funnel import CandidateFunnel
from chanlun.market_history_store import MarketHistoryStore
from scripts.audit_next_day_top_recall import audit_recall_pairs


def _bar(ts, close):
    return {
        "ts": ts,
        "open": close,
        "high": close * 1.01,
        "low": close * 0.99,
        "close": close,
        "volume": 1_000_000,
        "amount": 100_000_000,
        "adjustment": "qfq",
        "is_final": True,
        "source_batch": "fixture",
    }


class NextDayTopRecallAuditTest(unittest.TestCase):
    def _build_store(self, path, official=True):
        signal_date = "2026-07-10"
        outcome_date = "2026-07-13"
        with MarketHistoryStore(path) as store:
            funnel = CandidateFunnel("run-official", signal_date)
            for index in range(35):
                code = "{:06d}".format(index)
                instrument_id = store.upsert_instrument(
                    "stock", "SZ", code, code
                )
                gain_pct = 15.0 - index * 0.4
                store.upsert_bars(
                    "day",
                    instrument_id,
                    [
                        _bar(signal_date, 10.0),
                        _bar(outcome_date, 10.0 * (1.0 + gain_pct / 100.0)),
                    ],
                    adjustment="qfq",
                )
                funnel.register(
                    {
                        "code": code,
                        "source_channel": (
                            "trend" if index in (0, 1, 22) else "low_position"
                        ),
                        "retrieval_pool": (
                            "overlay" if index in (1, 22) else "base"
                        ),
                    }
                )
                funnel.pass_stage(code, "eligible")
                if index < 30:
                    funnel.pass_stage(code, "retrieval")
                if index < 25:
                    funnel.pass_stage(code, "daily_channel")
                if index < 15:
                    funnel.pass_stage(code, "minute30")
                if index < 10:
                    funnel.pass_stage(code, "fusion")
            funnel.finalize(
                main_codes=["{:06d}".format(i) for i in range(10)],
                observation_codes=["{:06d}".format(i) for i in range(10, 15)],
            )
            store.save_candidate_funnel(
                funnel.run_record(
                    metadata={
                        "is_official": bool(official),
                        "generated_at": signal_date + "T15:05:00+08:00",
                    }
                ),
                funnel.events,
            )

    def test_audits_top20_top30_and_limit_like_sets_by_funnel_stage(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "market.sqlite"
            self._build_store(path)
            result = audit_recall_pairs(
                path,
                [("2026-07-10", "2026-07-13")],
            )

        pair = result["pairs"][0]
        self.assertEqual(20, pair["targets"]["top20"]["count"])
        self.assertEqual(30, pair["targets"]["top30"]["count"])
        self.assertEqual(14, pair["targets"]["gain_ge_9_5"]["count"])
        self.assertEqual(20, pair["targets"]["top20"]["stages"]["retrieval"]["hit"])
        self.assertEqual(15, pair["targets"]["top20"]["stages"]["minute30"]["hit"])
        self.assertEqual(10, pair["targets"]["top20"]["terminal"]["main"])
        self.assertEqual(5, pair["targets"]["top20"]["terminal"]["observe"])
        self.assertEqual(
            ["000000", "000001"],
            pair["targets"]["top20"]["independent_increment"]["trend_codes"],
        )
        self.assertEqual(
            ["000001"],
            pair["targets"]["top20"]["independent_increment"]["overlay_codes"],
        )
        top30_failures = pair["targets"]["top30"]["failure_breakdown"]
        self.assertEqual(5, top30_failures["by_category"]["日线通道未匹配"])
        self.assertEqual(
            ["000025", "000026", "000027", "000028", "000029"],
            top30_failures["category_codes"]["日线通道未匹配"],
        )
        self.assertEqual(
            5,
            result["aggregate"]["top30"]["failure_breakdown"][
                "by_category"
            ]["日线通道未匹配"],
        )

    def test_requires_an_official_signal_run(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "market.sqlite"
            self._build_store(path, official=False)
            with self.assertRaisesRegex(ValueError, "official"):
                audit_recall_pairs(
                    path,
                    [("2026-07-10", "2026-07-13")],
                )

    def test_signal_run_never_reads_bars_after_outcome_date(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "market.sqlite"
            self._build_store(path)
            with MarketHistoryStore(path) as store:
                instrument = store.resolve_instrument(
                    "stock", "SZ", "000000"
                )
                store.upsert_bars(
                    "day",
                    instrument["instrument_id"],
                    [_bar("2026-07-14", 99.0)],
                    adjustment="qfq",
                )
            result = audit_recall_pairs(
                path,
                [("2026-07-10", "2026-07-13")],
            )

        leader = result["pairs"][0]["outcomes"][0]
        self.assertEqual("000000", leader["code"])
        self.assertAlmostEqual(15.0, leader["gain_pct"], places=6)


if __name__ == "__main__":
    unittest.main()
