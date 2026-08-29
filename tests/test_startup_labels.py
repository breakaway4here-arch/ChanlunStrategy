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
            "confirmation_evidence": {"buy_point": "二买"},
        })
        self.assertEqual(bp["sublevel_confirm_grade"], "S")
        self.assertEqual(bp["sublevel_confirm_label"], "S级确认")

    def test_unrecognized_structured_buy_point_cannot_receive_s_grade(self):
        bp = annotate_startup_quality({
            "change_pct": 2.0,
            "startup_signals": [],
            "confirmations": ["30min类二买"],
            "confirmation_evidence": {"buy_point": "类二买"},
        })
        self.assertEqual(bp["sublevel_confirm_grade"], "C")

    def test_unrecognized_structured_pattern_cannot_receive_a_grade(self):
        bp = annotate_startup_quality({
            "change_pct": 5.0,
            "startup_signals": [],
            "confirmations": ["30min自定义两阳结构"],
            "confirmation_evidence": {"fresh_yang_pattern": "custom"},
        })
        self.assertEqual(bp["sublevel_confirm_grade"], "C")

    def test_alignment_only_is_observation_not_a_grade(self):
        bp = annotate_startup_quality({
            "change_pct": 5.0,
            "startup_signals": [],
            "confirmations": [],
            "confirmation_evidence": {"ema_bullish_alignment": True},
        })
        self.assertEqual(bp["sublevel_confirm_grade"], "C")
        self.assertIn("均线仍为多头排列", bp["sublevel_confirm_reason"])
        self.assertIn("未形成独立确认", bp["sublevel_confirm_reason"])

    def test_legacy_ema_confirmation_string_cannot_restore_a_or_b_grade(self):
        bp = annotate_startup_quality({
            "change_pct": 2.58,
            "startup_signals": [],
            "confirmations": ["30min EMA5维持"],
        })
        self.assertEqual(bp["sublevel_confirm_grade"], "C")

    def test_legacy_yang_string_without_structured_evidence_cannot_restore_grade(self):
        bp = annotate_startup_quality({
            "change_pct": 5.0,
            "startup_signals": [],
            "confirmations": ["30min两阳夹一阴确认"],
        })
        self.assertEqual(bp["sublevel_confirm_grade"], "C")

    def test_sublevel_grade_a_for_strong_with_fresh_yang_structure(self):
        bp = annotate_startup_quality({
            "change_pct": 5.0,
            "startup_signals": [],
            "confirmations": ["30min两阳夹一阴确认"],
            "confirmation_evidence": {"fresh_yang_pattern": "two_yang_one_yin"},
        })
        self.assertEqual(bp["sublevel_confirm_grade"], "A")

    def test_sublevel_grade_b_for_fresh_yang_structure_without_strong_daily(self):
        bp = annotate_startup_quality({
            "change_pct": 2.58,
            "startup_signals": [],
            "confirmations": ["30min两阳夹一阴确认"],
            "confirmation_evidence": {"fresh_yang_pattern": "two_yang_one_yin"},
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
