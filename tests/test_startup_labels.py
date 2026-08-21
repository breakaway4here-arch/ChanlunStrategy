"""Tests for annotate_startup_quality — daily startup grade + sublevel confirm grade."""
import unittest

from chanlun.strong_startup import annotate_startup_quality


class TestAnnotateStartupQuality(unittest.TestCase):

    def test_daily_startup_grade_pullback_for_negative_change(self):
        bp = annotate_startup_quality({
            "change_pct": -3.65,
            "startup_signals": ["close_above_ma5"],
            "confirmations": ["30min回踩不破突破位"],
        })
        self.assertEqual(bp["daily_startup_grade"], "pullback")
        self.assertEqual(bp["daily_startup_label"], "回踩型启动观察")
        self.assertIn("daily_startup_warning", bp)

    def test_daily_startup_grade_strong_for_breakout_even_small_gain(self):
        bp = annotate_startup_quality({
            "change_pct": 2.58,
            "startup_signals": ["break_20d_high"],
            "confirmations": ["30min EMA5维持"],
        })
        self.assertEqual(bp["daily_startup_grade"], "strong")

    def test_daily_startup_grade_strong_for_change_above_4(self):
        bp = annotate_startup_quality({
            "change_pct": 5.0,
            "startup_signals": [],
            "confirmations": [],
        })
        self.assertEqual(bp["daily_startup_grade"], "strong")

    def test_daily_startup_grade_weak_for_small_positive_change(self):
        bp = annotate_startup_quality({
            "change_pct": 2.0,
            "startup_signals": [],
            "confirmations": [],
        })
        self.assertEqual(bp["daily_startup_grade"], "weak")
        self.assertEqual(bp["daily_startup_label"], "弱启动确认")

    def test_sublevel_grade_s_for_buy23(self):
        bp = annotate_startup_quality({
            "change_pct": 2.0,
            "startup_signals": [],
            "confirmations": ["30min二买", "30min回踩不破"],
        })
        self.assertEqual(bp["sublevel_confirm_grade"], "S")
        self.assertEqual(bp["sublevel_confirm_label"], "S级确认")
        fact = bp["confirmation_facts"][0]
        self.assertEqual(fact["owner_pool"], "strong_startup")
        self.assertEqual(fact["stage"], "30min_confirmation")
        self.assertEqual(fact["effect"], "observe")
        self.assertFalse(fact["eligible"])
        self.assertEqual(fact["reason_code"], "strong_startup_daily_not_strong")

    def test_sublevel_grade_a_for_strong_with_ema5(self):
        bp = annotate_startup_quality({
            "change_pct": 5.0,
            "startup_signals": [],
            "confirmations": ["30min EMA5维持"],
        })
        self.assertEqual(bp["sublevel_confirm_grade"], "A")
        fact = bp["confirmation_facts"][0]
        self.assertEqual(fact["effect"], "candidate")
        self.assertTrue(fact["eligible"])
        self.assertEqual(fact["reason_code"], "strong_startup_sa_confirmed")

    def test_arbitrary_nonempty_confirmation_is_typed_as_ineligible_b(self):
        bp = annotate_startup_quality({
            "change_pct": 5.0,
            "startup_signals": [],
            "confirmations": ["任意确认文本"],
        })

        self.assertEqual(bp["sublevel_confirm_grade"], "B")
        self.assertFalse(bp["confirmation_facts"][0]["eligible"])

    def test_sublevel_grade_b_for_ema_only_confirmation_not_strong(self):
        bp = annotate_startup_quality({
            "change_pct": 2.58,
            "startup_signals": [],
            "confirmations": ["30min EMA5维持"],
        })
        self.assertEqual(bp["sublevel_confirm_grade"], "B")

    def test_sublevel_grade_c_when_no_confirmations(self):
        bp = annotate_startup_quality({
            "change_pct": 5.0,
            "startup_signals": [],
            "confirmations": [],
        })
        self.assertEqual(bp["sublevel_confirm_grade"], "C")

    def test_does_not_modify_original(self):
        original = {
            "change_pct": 2.0,
            "startup_signals": [],
            "confirmations": [],
        }
        bp = annotate_startup_quality(original)
        self.assertNotIn("daily_startup_grade", original)


if __name__ == "__main__":
    unittest.main()
