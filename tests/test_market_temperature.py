import unittest

import run


class TestMarketTemperatureBuilder(unittest.TestCase):

    def test_build_market_temperature_default_when_inputs_missing(self):
        result = run.build_market_temperature()

        self.assertEqual(result["label"], "平衡")
        self.assertEqual(result["components"], {
            "index_score": 50,
            "breadth_score": 50,
            "limit_score": 50,
            "volume_score": 55,
            "sector_score": 50,
            "risk_penalty": 0,
        })
        self.assertEqual(result["score"], 48)

    def test_build_market_temperature_with_inputs(self):
        result = run.build_market_temperature(
            market_indices={
                "上证指数": {"change_pct": 1.5},
                "深证成指": {"change_pct": -0.5},
            },
            sector_flow=[
                {"name": "AI", "flow": 800},
                {"name": "新能源", "flow": -150},
            ],
            sector_outflow=[
                {"name": "消费", "flow": -1200},
            ],
            limit_up_pool=[{"code": "000001"}, {"code": "000002"}, {"code": "000003"}],
            sell_signals=[],
            sh_volumes=[1_000, 1_050, 980, 1_020, 1_100, 1_210],
        )

        self.assertEqual(result["components"]["index_score"], 59)
        self.assertEqual(result["components"]["limit_score"], 56)
        self.assertEqual(result["components"]["volume_score"], 60)
        self.assertEqual(result["components"]["sector_score"], 51)
        self.assertEqual(result["components"]["breadth_score"], 50)
        self.assertEqual(result["components"]["risk_penalty"], 0)
        self.assertEqual(result["score"], 52)

    def test_build_market_temperature_risk_penalty(self):
        base = run.build_market_temperature(
            market_indices={"上证指数": {"change_pct": 1.5}},
            sell_signals=[],
            data_quality={"is_official": True},
        )
        stressed = run.build_market_temperature(
            market_indices={"上证指数": {"change_pct": 1.5}},
            sell_signals=[{"code": "600000"} for _ in range(20)],
            data_quality={"is_official": False},
        )

        self.assertEqual(base["components"]["risk_penalty"], 0)
        self.assertEqual(stressed["components"]["risk_penalty"], 25)
        self.assertLess(stressed["score"], base["score"])
