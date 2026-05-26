"""Tests for fusion_admission — threshold matrix, market regime, MA checks."""
import unittest
import numpy as np

from chanlun.fusion_admission import (
    apply_fusion_admission,
    is_market_strong,
    is_ma_bullish,
)


class TestFusionAdmission(unittest.TestCase):

    # ---- market / MA helpers ----

    def test_is_ma_bullish_true(self):
        closes = list(range(1, 30))
        closes[-5:] = [100, 90, 80, 70, 60]
        closes[-10:-5] = [50, 40, 30, 20, 10]
        closes[-20:-10] = [5] * 10
        self.assertTrue(is_ma_bullish(closes))

    def test_is_ma_bullish_false(self):
        closes = list(range(1, 30))
        closes[-5:] = [5, 5, 5, 5, 5]
        self.assertFalse(is_ma_bullish(closes))

    def test_is_ma_bullish_short_data(self):
        self.assertFalse(is_ma_bullish([1, 2, 3]))

    def test_is_market_strong_true(self):
        closes = list(range(1, 80))
        closes[-60:] = list(range(100, 160))
        self.assertTrue(is_market_strong(closes))

    def test_is_market_strong_false_short(self):
        self.assertFalse(is_market_strong(list(range(1, 30))))

    # ---- admission matrix ----

    def _make_stock(self, bp_type, tier="candidate", strength="中", confirmed_by="底分型+MACD金叉"):
        """Default closes are MA-bullish (MA5>MA10>MA20)."""
        closes = list(range(1, 30))
        closes[-5:] = [100, 90, 80, 70, 60]
        return {
            "code": "600519",
            "name": "测试",
            "best_buy_point": {
                "type": bp_type,
                "tier": tier,
                "strength": strength,
                "confirmed_by": confirmed_by,
                "index": 25,
                "price": 50.0,
                "reason": "test",
            },
            "closes": closes,
            "buy_points": [],
        }

    @staticmethod
    def _make_non_bullish_closes():
        """Closes where MA is NOT bullish: recent prices declining."""
        closes = list(range(1, 30))
        closes[-5:] = [1, 1, 1, 1, 1]     # MA5 low
        closes[-10:-5] = [50, 40, 30, 20, 10]  # MA10 higher
        closes[-20:-10] = [100] * 10            # MA20 highest
        return closes

    def _make_sh_closes(self, strong=True):
        n = 80
        if strong:
            return list(range(100, 100 + n))
        else:
            closes = list(range(100, 100 + n))
            closes[-10:] = list(range(80, 90))
            return closes

    def test_sanmai_candidate_ma_false_filtered(self):
        stock = self._make_stock("三买候选")
        stock["closes"] = self._make_non_bullish_closes()
        picks, diag = apply_fusion_admission([stock], self._make_sh_closes(True))
        self.assertEqual(len(picks), 0)
        self.assertEqual(diag["dropped_by_ma"], 1)

    def test_sanmai_candidate_ma_true_kept(self):
        stock = self._make_stock("三买候选")
        picks, diag = apply_fusion_admission([stock], self._make_sh_closes(True))
        self.assertEqual(len(picks), 1)

    def test_dibeichi_candidate_no_ma_strong_confirm_kept_strong_market(self):
        stock = self._make_stock("底背驰候选", strength="强", confirmed_by="底分型+MACD金叉")
        stock["closes"] = self._make_non_bullish_closes()  # MA not bullish
        picks, diag = apply_fusion_admission([stock], self._make_sh_closes(True))
        self.assertEqual(len(picks), 1)
        self.assertEqual(diag["market_regime"], "strong")

    def test_dibeichi_candidate_no_ma_medium_confirm_filtered_weak_market(self):
        stock = self._make_stock("底背驰候选", strength="中", confirmed_by="EMA5收复")
        stock["closes"] = self._make_non_bullish_closes()
        picks, diag = apply_fusion_admission([stock], self._make_sh_closes(False))
        self.assertEqual(len(picks), 0)

    def test_dibeichi_candidate_weak_market_key_level_ema5_kept(self):
        stock = self._make_stock("底背驰候选", strength="中",
                                 confirmed_by="关键位不破+EMA5收复")
        stock["closes"] = self._make_non_bullish_closes()
        picks, diag = apply_fusion_admission([stock], self._make_sh_closes(False))
        self.assertEqual(len(picks), 1)

    def test_zhongshu_dixi_strong_confirm_no_ma_kept_strong_market(self):
        stock = self._make_stock("中枢低吸候选", strength="强", confirmed_by="底分型+MACD金叉")
        stock["closes"] = self._make_non_bullish_closes()
        picks, diag = apply_fusion_admission([stock], self._make_sh_closes(True))
        self.assertEqual(len(picks), 1)

    def test_zhongshu_dixi_medium_confirm_no_ma_filtered_weak_market(self):
        stock = self._make_stock("中枢低吸候选", strength="中", confirmed_by="EMA5收复")
        stock["closes"] = self._make_non_bullish_closes()
        picks, diag = apply_fusion_admission([stock], self._make_sh_closes(False))
        self.assertEqual(len(picks), 0)

    def test_panzheng_dixi_strong_confirm_weak_market_kept(self):
        stock = self._make_stock("盘整低吸候选", strength="强")
        picks, diag = apply_fusion_admission([stock], self._make_sh_closes(False))
        self.assertEqual(len(picks), 1)

    def test_panzheng_dixi_medium_confirm_weak_market_filtered(self):
        stock = self._make_stock("盘整低吸候选", strength="中")
        picks, diag = apply_fusion_admission([stock], self._make_sh_closes(False))
        self.assertEqual(len(picks), 0)

    def test_yimai_formal_always_kept(self):
        stock = self._make_stock("一买", tier="formal", strength="弱")
        stock["closes"] = self._make_non_bullish_closes()
        picks, diag = apply_fusion_admission([stock], self._make_sh_closes(False))
        self.assertEqual(len(picks), 1)
        self.assertEqual(diag["kept_formal"], 1)

    def test_ermai_formal_always_kept(self):
        stock = self._make_stock("二买", tier="formal", strength="弱")
        stock["closes"] = self._make_non_bullish_closes()
        picks, diag = apply_fusion_admission([stock], self._make_sh_closes(False))
        self.assertEqual(len(picks), 1)
        self.assertEqual(diag["kept_formal"], 1)

    def test_sanmai_formal_no_ma_filtered(self):
        stock = self._make_stock("三买", tier="formal", strength="强")
        stock["closes"] = self._make_non_bullish_closes()
        picks, diag = apply_fusion_admission([stock], self._make_sh_closes(True))
        self.assertEqual(len(picks), 0)
        self.assertEqual(diag["dropped_by_ma"], 1)

    def test_sanmai_formal_ma_ok_kept(self):
        stock = self._make_stock("三买", tier="formal", strength="强")
        picks, diag = apply_fusion_admission([stock], self._make_sh_closes(True))
        self.assertEqual(len(picks), 1)

    # ---- diagnostics ----

    def test_diagnostics_counts(self):
        s1 = self._make_stock("一买", tier="formal", strength="弱")
        s1["closes"] = self._make_non_bullish_closes()
        s2 = self._make_stock("三买候选")
        s2["closes"] = self._make_non_bullish_closes()
        s3 = self._make_stock("底背驰候选", strength="强")
        s3["closes"] = self._make_non_bullish_closes()
        picks, diag = apply_fusion_admission([s1, s2, s3], self._make_sh_closes(True))
        self.assertEqual(diag["input_count"], 3)
        self.assertEqual(diag["kept_formal"], 1)
        self.assertEqual(diag["kept_candidate"], 1)
        self.assertEqual(diag["dropped_by_ma"], 1)
        self.assertEqual(diag["output_count"], 2)

    def test_pure_fusion_identical_flag(self):
        stock = self._make_stock("一买", tier="formal", strength="强")
        picks, diag = apply_fusion_admission([stock], self._make_sh_closes(True))
        self.assertTrue(diag["pure_fusion_identical"])

    def test_pure_fusion_not_identical(self):
        s1 = self._make_stock("三买候选")
        s1["closes"] = self._make_non_bullish_closes()
        picks, diag = apply_fusion_admission([s1], self._make_sh_closes(True))
        self.assertFalse(diag["pure_fusion_identical"])

    def test_ermai_candidate_strong_market_no_ma_kept(self):
        stock = self._make_stock("二买候选", strength="中")
        stock["closes"] = self._make_non_bullish_closes()
        picks, diag = apply_fusion_admission([stock], self._make_sh_closes(True))
        self.assertEqual(len(picks), 1)

    # —— 强势启动候选 fusion admission ——

    def test_strong_startup_candidate_strong_market_ma_ok(self):
        stock = self._make_stock("强势启动候选", strength="强")
        picks, diag = apply_fusion_admission([stock], self._make_sh_closes(True))
        self.assertEqual(len(picks), 1)
        self.assertEqual(picks[0]["fusion_admission"]["reason"], "强势启动候选强市通过")

    def test_strong_startup_candidate_no_ma_filtered(self):
        stock = self._make_stock("强势启动候选", strength="强")
        stock["closes"] = self._make_non_bullish_closes()
        picks, diag = apply_fusion_admission([stock], self._make_sh_closes(True))
        self.assertEqual(len(picks), 0)
        self.assertEqual(diag["drop_details"][0]["reason"], "强势启动候选要求MA多头(MA5>MA10>MA20)")

    def test_strong_startup_candidate_weak_market_medium_confirm_ok(self):
        stock = self._make_stock("强势启动候选", strength="中")
        picks, diag = apply_fusion_admission([stock], self._make_sh_closes(False))
        self.assertEqual(len(picks), 1)

    def test_strong_startup_candidate_weak_market_weak_confirm_filtered(self):
        stock = self._make_stock("强势启动候选", strength="弱")
        picks, diag = apply_fusion_admission([stock], self._make_sh_closes(False))
        self.assertEqual(len(picks), 0)


if __name__ == "__main__":
    unittest.main()
