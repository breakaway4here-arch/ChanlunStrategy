import unittest

from chanlun.market_sentiment import (
    build_daily_inputs_from_windows,
    build_market_sentiment,
    build_sentiment_history,
    classify_price_limit,
    compute_limit_ecology,
    compute_market_breadth,
    detect_turning_signal,
    historical_percentile,
)


def _bar(code, prev_close=10.0, close=10.0, **kwargs):
    row = {
        "code": code,
        "name": kwargs.pop("name", "测试股票"),
        "prev_close": prev_close,
        "close": close,
    }
    row.update(kwargs)
    return row


def _day(date, up_count, down_count, unchanged=0, turnover=100.0):
    bars = []
    for idx in range(up_count):
        bars.append(_bar("600%03d" % idx, close=10.1))
    for idx in range(down_count):
        bars.append(_bar("601%03d" % idx, close=9.9))
    for idx in range(unchanged):
        bars.append(_bar("603%03d" % idx))
    return {
        "date": date,
        "stock_bars": bars,
        "index_bars": [{"code": "000001", "change_pct": (up_count - down_count) / 10.0}],
        "turnover": turnover,
        "turnover_ma5": 100.0,
        "trend": {"above_ma20_ratio": up_count / max(1, up_count + down_count + unchanged)},
    }


class PriceLimitClassificationTests(unittest.TestCase):
    def test_identifies_main_board_limit_prices_from_previous_close(self):
        self.assertEqual(
            classify_price_limit(_bar("600001", prev_close=10.01, close=11.01)),
            "limit_up",
        )
        self.assertEqual(
            classify_price_limit(_bar("000001", prev_close=10.01, close=9.01)),
            "limit_down",
        )

    def test_uses_twenty_percent_for_chinext_and_star_market(self):
        self.assertEqual(
            classify_price_limit(_bar("300001", prev_close=10.0, close=12.0)),
            "limit_up",
        )
        self.assertEqual(
            classify_price_limit(_bar("688001", prev_close=10.0, close=8.0)),
            "limit_down",
        )
        self.assertEqual(
            classify_price_limit(_bar("300001", prev_close=10.0, close=11.0)),
            "normal",
        )

    def test_uses_five_percent_for_st_and_thirty_percent_for_beijing(self):
        self.assertEqual(
            classify_price_limit(_bar("600001", name="ST测试", close=10.5)),
            "limit_up",
        )
        self.assertEqual(
            classify_price_limit(_bar("830001", close=13.0)),
            "limit_up",
        )

    def test_growth_star_and_beijing_st_keep_their_board_limit(self):
        self.assertEqual(
            classify_price_limit(_bar("300001", name="ST测试", close=12.0)),
            "limit_up",
        )
        self.assertEqual(
            classify_price_limit(_bar("688001", name="*ST测试", close=8.0)),
            "limit_down",
        )
        self.assertEqual(
            classify_price_limit(_bar("830001", name="ST测试", close=13.0)),
            "limit_up",
        )

    def test_excludes_explicit_or_listing_period_without_price_limit(self):
        self.assertEqual(
            classify_price_limit(_bar("600001", close=15.0, no_price_limit=True)),
            "excluded",
        )
        self.assertEqual(
            classify_price_limit(_bar("301001", close=15.0, listing_trade_days=3)),
            "excluded",
        )
        self.assertEqual(
            classify_price_limit(_bar("830001", close=15.0, listing_trade_days=1)),
            "excluded",
        )

    def test_explicit_price_limit_rule_overrides_board_inference(self):
        self.assertEqual(
            classify_price_limit(_bar("600001", close=11.5, price_limit_pct=15)),
            "limit_up",
        )


class SentimentEvidenceTests(unittest.TestCase):
    def test_daily_inputs_derive_listing_trade_days_without_misclassifying_old_stocks(self):
        dates = [
            "2026-07-01",
            "2026-07-02",
            "2026-07-03",
            "2026-07-06",
            "2026-07-07",
            "2026-07-08",
        ]
        rows = []
        for trade_date in dates:
            for code, listed_date in (
                ("600001", "20000101"),
                ("301001", "20260703"),
            ):
                rows.append({
                    "code": code,
                    "name": code,
                    "ts": trade_date,
                    "close": 10.0,
                    "amount": 100.0,
                    "stock_meta_asof": {
                        "listed_date": listed_date,
                        "is_st": False,
                    },
                })

        daily = build_daily_inputs_from_windows(
            {"dates": dates, "rows": rows},
        )
        final_by_code = {
            item["code"]: item
            for item in daily[-1]["stock_bars"]
        }

        self.assertGreater(final_by_code["600001"]["listing_trade_days"], 5)
        self.assertEqual(final_by_code["301001"]["listing_trade_days"], 4)

    def test_market_breadth_uses_all_valid_stocks_and_reports_distribution(self):
        result = compute_market_breadth([
            _bar("600001", close=10.5),
            _bar("600002", close=10.2),
            _bar("600003", close=9.9),
            _bar("600004", close=10.0),
            {"code": "600005", "close": None, "prev_close": 10.0},
        ])

        self.assertEqual(result["valid_count"], 4)
        self.assertEqual(result["advance_count"], 2)
        self.assertEqual(result["decline_count"], 1)
        self.assertEqual(result["flat_count"], 1)
        self.assertEqual(result["advance_ratio"], 50.0)
        self.assertGreater(result["score"], 50)

    def test_limit_ecology_contains_counts_and_smoothed_limit_ratio(self):
        rows = [
            _bar("600001", close=11.0),
            _bar("600002", close=11.0),
            _bar("600003", close=9.0),
            _bar("300001", close=11.0),
        ]

        result = compute_limit_ecology(rows)

        self.assertEqual(result["limit_up_count"], 2)
        self.assertEqual(result["limit_down_count"], 1)
        self.assertEqual(result["limit_ratio"], 1.5)
        self.assertAlmostEqual(result["log_limit_ratio"], 0.405465, places=5)
        expected = (
            result["ratio_score"] * 0.40
            + result["limit_up_score"] * 0.25
            + result["limit_down_score"] * 0.25
            + result["improvement_score"] * 0.10
        )
        self.assertEqual(result["score"], round(expected, 2))

    def test_limit_ecology_improvement_uses_only_prior_days(self):
        weak_prior = {
            "evidence": {
                "limit_ecology": {
                    "log_limit_ratio": -1.0,
                    "limit_up_count": 1,
                    "limit_down_count": 8,
                }
            }
        }
        result = compute_limit_ecology(
            [
                _bar("600001", close=11.0),
                _bar("600002", close=11.0),
                _bar("600003", close=10.1),
            ],
            prior_history=[weak_prior],
        )

        self.assertGreater(result["improvement_score"], 50)

    def test_verified_limit_pool_counts_override_bar_classification(self):
        result = build_market_sentiment(
            date="2026-07-16",
            stock_bars=[
                _bar("600001", close=10.1),
                _bar("600002", close=9.9),
            ],
            index_bars=[{"change_pct": 0.5}],
            turnover=100,
            turnover_ma5=100,
            turnover_ma20=100,
            trend={"above_ma20_ratio": 0.5},
            limit_counts={
                "limit_up_count": 42,
                "limit_down_count": 33,
                "evidence_date": "2026-07-16",
                "data_status": "verified",
                "source": "eastmoney_limit_pools",
            },
        )

        ecology = result["evidence"]["limit_ecology"]
        self.assertEqual(ecology["limit_up_count"], 42)
        self.assertEqual(ecology["limit_down_count"], 33)
        self.assertEqual(ecology["source"], "eastmoney_limit_pools")

    def test_historical_percentile_uses_only_supplied_prior_values(self):
        self.assertEqual(historical_percentile(10, []), 50.0)
        self.assertEqual(historical_percentile(10, [1, 5, 9]), 100.0)
        self.assertAlmostEqual(historical_percentile(1, [1, 2, 3]), 100.0 / 6.0)

    def test_five_component_weights_and_coverage_are_explicit(self):
        result = build_market_sentiment(
            date="2026-07-16",
            stock_bars=[
                _bar("600001", close=11.0),
                _bar("600002", close=10.2),
                _bar("600003", close=9.8),
            ],
            index_bars=[{"change_pct": 1.0}, {"change_pct": 0.5}],
            turnover=120.0,
            turnover_ma5=100.0,
            turnover_ma20=80.0,
            trend={"above_ma20_ratio": 0.7},
        )

        self.assertEqual(
            result["weights"],
            {
                "breadth": 0.30,
                "limit_ecology": 0.30,
                "index": 0.15,
                "turnover": 0.15,
                "trend": 0.10,
            },
        )
        self.assertEqual(result["coverage"], 1.0)
        self.assertFalse(result["insufficient"])
        self.assertIn("limit_ratio", result["evidence"]["limit_ecology"])
        self.assertEqual(
            result["evidence"]["turnover"]["ratio_to_ma20"],
            1.5,
        )
        expected = sum(
            result["components"][name] * weight
            for name, weight in result["weights"].items()
        )
        self.assertEqual(result["score"], round(expected))

    def test_missing_core_evidence_is_not_filled_with_neutral_fake_scores(self):
        result = build_market_sentiment(
            date="2026-07-16",
            stock_bars=[],
            index_bars=[],
        )

        self.assertIsNone(result["score"])
        self.assertTrue(result["insufficient"])
        self.assertEqual(result["coverage"], 0.0)
        self.assertEqual(result["missing_components"], [
            "breadth",
            "limit_ecology",
            "index",
            "turnover",
            "trend",
        ])

    def test_partial_score_is_diagnostic_only_and_not_published_as_sentiment(self):
        result = build_market_sentiment(
            date="2026-07-16",
            stock_bars=[_bar("600001", close=10.2), _bar("600002", close=9.8)],
            index_bars=[],
        )

        self.assertIsNone(result["score"])
        self.assertIsNotNone(result["partial_score"])
        self.assertEqual(result["coverage"], 0.6)
        self.assertTrue(result["insufficient"])


class SentimentHistoryTests(unittest.TestCase):
    def test_builds_daily_inputs_from_one_database_window_without_future_data(self):
        dates = ["2026-06-%02d" % day for day in range(1, 26)]
        rows = []
        for index, trade_date in enumerate(dates):
            rows.extend([
                {
                    "code": "600001",
                    "name": "上涨股",
                    "ts": trade_date,
                    "close": 10 + index * 0.1,
                    "amount": 100 + index,
                    "stock_meta_asof": {},
                },
                {
                    "code": "600002",
                    "name": "下跌股",
                    "ts": trade_date,
                    "close": 20 - index * 0.1,
                    "amount": 200 + index,
                    "stock_meta_asof": {},
                },
            ])
        limit_counts = {
            trade_date: {
                "limit_up_count": index,
                "limit_down_count": 1,
                "evidence_date": trade_date,
                "data_status": "verified",
                "source": "eastmoney_limit_pools",
            }
            for index, trade_date in enumerate(dates)
        }

        daily = build_daily_inputs_from_windows(
            {"dates": dates, "rows": rows},
            {"dates": [], "rows": []},
            limit_counts,
        )

        self.assertEqual(len(daily), 25)
        self.assertIsNone(daily[0]["turnover_ma5"])
        self.assertEqual(
            daily[5]["turnover_ma5"],
            sum(day["turnover"] for day in daily[:5]) / 5,
        )
        self.assertIsNotNone(daily[-1]["turnover_ma20"])
        self.assertEqual(daily[-1]["limit_counts"]["limit_up_count"], 24)
        self.assertEqual(len(daily[-1]["stock_bars"]), 2)
        self.assertEqual(
            daily[-1]["stock_bars"][0]["prev_close"],
            rows[-4]["close"],
        )

    def test_history_keeps_latest_twenty_days_and_adds_ma3(self):
        days = [
            _day("2026-06-%02d" % day, up_count=day, down_count=25 - day)
            for day in range(1, 25)
        ]

        result = build_sentiment_history(days, window=20)

        self.assertEqual(len(result), 20)
        self.assertEqual(result[0]["date"], "2026-06-05")
        self.assertIsNone(result[0]["ma3"])
        self.assertIsNone(result[1]["ma3"])
        self.assertIsNotNone(result[2]["ma3"])

    def test_historical_scores_do_not_change_when_future_day_is_appended(self):
        days = [
            _day("2026-07-%02d" % day, up_count=day + 3, down_count=10 - day)
            for day in range(1, 7)
        ]
        initial = build_sentiment_history(days)
        future = _day("2026-07-07", up_count=100, down_count=0, turnover=500.0)

        extended = build_sentiment_history(days + [future])

        self.assertEqual(
            [(item["date"], item["score"]) for item in initial],
            [(item["date"], item["score"]) for item in extended[:-1]],
        )

    def test_less_than_five_valid_days_has_no_turning_signal(self):
        points = [{"score": score} for score in [25, 30, 40, 55]]
        self.assertIsNone(detect_turning_signal(points))

    def test_detects_strengthening_and_weakening_turns(self):
        strengthening = [{"score": score} for score in [28, 29, 31, 36, 44]]
        weakening = [{"score": score} for score in [78, 76, 74, 68, 58]]

        self.assertEqual(detect_turning_signal(strengthening), "turning_stronger")
        self.assertEqual(detect_turning_signal(weakening), "turning_weaker")


if __name__ == "__main__":
    unittest.main()
