import tempfile
import unittest
import json
from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path

from chanlun.market_history_store import MarketHistoryStore
from run import (
    _build_market_sentiment_shadow_fields,
    _build_market_sentiment_history,
    _load_limit_count_evidence,
)


class RunMarketSentimentTests(unittest.TestCase):
    def test_psy12_shadow_fields_do_not_mutate_formal_decision_inputs(self):
        formal_sentiment = {
            "date": "2026-08-26",
            "score": 61,
            "label": "偏强",
            "components": {
                "breadth": 52.69,
                "limit_ecology": 82.71,
                "index": 62.8,
                "turnover": 38.09,
                "trend": 56.66,
            },
        }
        history = []
        dates = [
            "2026-08-11", "2026-08-12", "2026-08-13", "2026-08-14",
            "2026-08-17", "2026-08-18", "2026-08-19", "2026-08-20",
            "2026-08-21", "2026-08-24", "2026-08-25", "2026-08-26",
        ]
        for index, trade_date in enumerate(dates):
            history.append({
                "date": trade_date,
                "evidence": {
                    "index": {
                        "available": True,
                        "average_change_pct": 0.5 if index % 2 == 0 else -0.5,
                    }
                },
            })
        market_temperature = {
            "score": formal_sentiment["score"],
            "label": formal_sentiment["label"],
        }
        decision_gate_input = {
            "market_sentiment_score": formal_sentiment["score"],
            "market_sentiment_label": formal_sentiment["label"],
        }
        before = (
            deepcopy(formal_sentiment),
            deepcopy(market_temperature),
            deepcopy(decision_gate_input),
        )

        fields = _build_market_sentiment_shadow_fields(
            formal_sentiment,
            history,
        )

        self.assertEqual(
            (formal_sentiment, market_temperature, decision_gate_input),
            before,
        )
        self.assertEqual(fields["psy12_shadow"]["mode"], "shadow")
        self.assertFalse(fields["psy12_shadow"]["affects_production"])
        self.assertNotIn("market_temperature", fields)
        self.assertNotIn("decision_gate", fields)

    def test_reuses_previous_report_for_scoreless_historical_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "market.sqlite"
            report_dir = root / "docs" / "data"
            report_dir.mkdir(parents=True)
            with MarketHistoryStore(path) as store:
                stock_ids = [
                    store.upsert_instrument(
                        "stock", "SH", code, name=code
                    )
                    for code in ("600000", "600001")
                ]
                trade_dates = [
                    (date(2026, 5, 1) + timedelta(days=offset)).isoformat()
                    for offset in range(45)
                ]
                for day, trade_date in enumerate(trade_dates, start=1):
                    amount_scale = 100_000_000 if day < 44 else 10_000
                    for index, instrument_id in enumerate(stock_ids):
                        close = 10 + index + day * 0.01
                        store.upsert_bars(
                            "day",
                            instrument_id,
                            [{
                                "ts": trade_date,
                                "open": close,
                                "high": close + 0.1,
                                "low": close - 0.1,
                                "close": close,
                                "volume": 1000,
                                "amount": amount_scale + day,
                                "adjustment": "qfq",
                                "is_final": True,
                                "source_batch": "test",
                            }],
                        )
                        store.upsert_stock_meta(
                            instrument_id,
                            trade_date,
                            {
                                "name": "股票",
                                "is_st": False,
                                "listed_date": "20000101",
                            },
                        )

            previous = {
                "date": trade_dates[-2],
                "market_sentiment_history": [{
                    "date": trade_dates[-2],
                    "score": 8,
                    "partial_score": 8,
                    "label": "冰点",
                    "coverage": 0.85,
                    "insufficient": False,
                    "components": {"index": 0.0},
                    "evidence": {"index": {"available": True, "score": 0.0}},
                }],
            }
            (report_dir / (trade_dates[-2] + ".json")).write_text(
                json.dumps(previous), encoding="utf-8"
            )

            def fetcher(date_str):
                evidence_date = "{}-{}-{}".format(
                    date_str[:4], date_str[4:6], date_str[6:8]
                )
                return {
                    "limit_up_count": 2,
                    "limit_down_count": 1,
                    "evidence_date": evidence_date,
                    "data_status": "verified",
                    "source": "test",
                }

            current, history = _build_market_sentiment_history(
                trade_dates[-1],
                market_indices={"上证指数": {"change_pct": 0.5}},
                db_path=str(path),
                report_data_dir=str(report_dir),
                minimum_instruments=2,
                fetcher=fetcher,
                max_workers=4,
            )

        by_date = {item["date"]: item for item in history}
        self.assertEqual(by_date[trade_dates[-2]]["score"], 8)
        self.assertIsNotNone(current["score"])
        self.assertEqual(current["date"], trade_dates[-1])

    def test_builds_twenty_day_sentiment_from_shared_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "market.sqlite"
            with MarketHistoryStore(path) as store:
                stock_ids = [
                    store.upsert_instrument(
                        "stock", "SH", code, name=code
                    )
                    for code in ("600000", "600001")
                ]
                for day in range(1, 46):
                    trade_date = "2026-05-%02d" % day
                    for index, instrument_id in enumerate(stock_ids):
                        close = 10 + index + day * (0.02 if index == 0 else -0.01)
                        store.upsert_bars(
                            "day",
                            instrument_id,
                            [{
                                "ts": trade_date,
                                "open": close,
                                "high": close + 0.1,
                                "low": close - 0.1,
                                "close": close,
                                "volume": 1000,
                                "amount": 100_000_000 + day,
                                "adjustment": "qfq",
                                "is_final": True,
                                "source_batch": "test",
                            }],
                        )
                        store.upsert_stock_meta(
                            instrument_id,
                            trade_date,
                            {
                                "name": "股票",
                                "is_st": False,
                                "listed_date": "20000101",
                            },
                        )

            def fetcher(date_str):
                evidence_date = "{}-{}-{}".format(
                    date_str[:4], date_str[4:6], date_str[6:8]
                )
                return {
                    "limit_up_count": 2,
                    "limit_down_count": 1,
                    "evidence_date": evidence_date,
                    "data_status": "verified",
                    "source": "test",
                }

            current, history = _build_market_sentiment_history(
                "2026-05-45",
                market_indices={"上证指数": {"change_pct": 0.5}},
                db_path=str(path),
                minimum_instruments=2,
                fetcher=fetcher,
                max_workers=4,
            )

        self.assertEqual(len(history), 20)
        self.assertEqual(history[-1]["date"], "2026-05-45")
        self.assertEqual(current, history[-1])
        self.assertEqual(
            history[-1]["evidence"]["limit_ecology"]["limit_up_count"],
            2,
        )

    def test_limit_counts_use_database_first_and_fetch_only_missing_dates(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "market.sqlite"
            with MarketHistoryStore(path) as store:
                store.upsert_market_sentiment_evidence(
                    "2026-07-15",
                    {
                        "limit_up_count": 20,
                        "limit_down_count": 10,
                        "evidence_date": "2026-07-15",
                        "data_status": "verified",
                        "source": "cache",
                    },
                )
                calls = []

                def fetcher(date_str):
                    calls.append(date_str)
                    return {
                        "limit_up_count": 42,
                        "limit_down_count": 33,
                        "evidence_date": "2026-07-16",
                        "data_status": "verified",
                        "source": "remote",
                    }

                evidence = _load_limit_count_evidence(
                    store,
                    ["2026-07-15", "2026-07-16"],
                    fetcher=fetcher,
                    max_workers=2,
                )

                persisted = store.query_market_sentiment_evidence(
                    ["2026-07-16"]
                )

        self.assertEqual(calls, ["20260716"])
        self.assertEqual(evidence["2026-07-15"]["source"], "cache")
        self.assertEqual(evidence["2026-07-16"]["limit_up_count"], 42)
        self.assertEqual(persisted["2026-07-16"]["limit_down_count"], 33)


if __name__ == "__main__":
    unittest.main()
