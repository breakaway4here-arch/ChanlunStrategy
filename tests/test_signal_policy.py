"""Unit tests for signal_policy tier classification."""
import unittest
from chanlun.signal_policy import (
    FORMAL_TYPES, CANDIDATE_TYPES, CANDIDATE_SEED_TYPES, BLOCKED_TYPES,
    UPGRADEABLE_REFERENCE_TYPES, REFERENCE_ONLY_TYPES, WATCH_TYPES,
    STRONG_STARTUP_CANDIDATE_TYPES,
    infer_signal_tier, is_formal_buy, is_upgradeable_reference,
    is_recommendable_buy, is_blocked_buy,
    is_candidate_seed, is_reference_only,
    is_watch_only, is_strong_startup_candidate, is_strong_startup_watch,
    UPGRADE_OUTPUT_TYPE, ALL_RECOMMENDABLE_TYPES,
)


class TestSignalTiers(unittest.TestCase):

    def test_formal_types(self):
        for t in ["一买", "二买", "三买"]:
            with self.subTest(type=t):
                self.assertIn(t, FORMAL_TYPES)
                self.assertEqual(infer_signal_tier({"type": t}), "formal")
                self.assertTrue(is_formal_buy({"type": t}))
                self.assertTrue(is_recommendable_buy({"type": t}))
                self.assertFalse(is_blocked_buy({"type": t}))

    def test_candidate_types(self):
        for t in ["二买候选", "盘整低吸候选", "中枢低吸候选", "三买候选"]:
            with self.subTest(type=t):
                self.assertIn(t, CANDIDATE_TYPES)
                self.assertEqual(infer_signal_tier({"type": t}), "candidate")
                self.assertTrue(is_recommendable_buy({"type": t}))
                self.assertFalse(is_formal_buy({"type": t}))

    def test_upgradeable_reference_types(self):
        for t in ["二买待确认", "盘整背驰参考", "中枢震荡低吸参考"]:
            with self.subTest(type=t):
                self.assertIn(t, UPGRADEABLE_REFERENCE_TYPES)
                self.assertEqual(infer_signal_tier({"type": t}), "reference")
                self.assertTrue(is_upgradeable_reference({"type": t}))
                self.assertFalse(is_recommendable_buy({"type": t}))

    def test_reference_only_types(self):
        for t in ["swing底背驰参考"]:
            with self.subTest(type=t):
                self.assertEqual(infer_signal_tier({"type": t}), "reference")
                self.assertFalse(is_upgradeable_reference({"type": t}))
                self.assertFalse(is_recommendable_buy({"type": t}))

    def test_blocked_types(self):
        for t in ["三买已错过", "类二买"]:
            with self.subTest(type=t):
                self.assertIn(t, BLOCKED_TYPES)
                self.assertEqual(infer_signal_tier({"type": t}), "blocked")
                self.assertTrue(is_blocked_buy({"type": t}))
                self.assertFalse(is_recommendable_buy({"type": t}))

    def test_unknown_defaults_to_reference(self):
        self.assertEqual(infer_signal_tier({"type": "unknown_xyz"}), "reference")
        self.assertFalse(is_recommendable_buy({"type": "unknown_xyz"}))

    def test_explicit_tier_overrides_type(self):
        bp = {"type": "二买待确认", "tier": "candidate"}
        self.assertEqual(infer_signal_tier(bp), "candidate")
        self.assertTrue(is_recommendable_buy(bp))

    def test_upgrade_output_map(self):
        self.assertEqual(UPGRADE_OUTPUT_TYPE["二买待确认"], "二买候选")
        self.assertEqual(UPGRADE_OUTPUT_TYPE["盘整背驰参考"], "盘整低吸候选")
        self.assertEqual(UPGRADE_OUTPUT_TYPE["中枢震荡低吸参考"], "中枢低吸候选")

    def test_all_recommendable_includes_formal_and_candidate(self):
        self.assertTrue(FORMAL_TYPES.issubset(ALL_RECOMMENDABLE_TYPES))
        self.assertTrue(CANDIDATE_TYPES.issubset(ALL_RECOMMENDABLE_TYPES))
        self.assertNotIn("二买待确认", ALL_RECOMMENDABLE_TYPES)
        self.assertNotIn("swing底背驰参考", ALL_RECOMMENDABLE_TYPES)
        self.assertNotIn("三买已错过", ALL_RECOMMENDABLE_TYPES)

    def test_swing_seed_is_seed_not_recommendable(self):
        bp = {"type": "swing底背驰候选种子"}
        self.assertEqual(infer_signal_tier(bp), "seed")
        self.assertTrue(is_candidate_seed(bp))
        self.assertFalse(is_recommendable_buy(bp))

    def test_bottom_divergence_candidate_is_recommendable(self):
        bp = {"type": "底背驰候选", "tier": "candidate"}
        self.assertEqual(infer_signal_tier(bp), "candidate")
        self.assertTrue(is_recommendable_buy(bp))

    def test_raw_swing_reference_stays_reference_only(self):
        bp = {"type": "swing底背驰参考"}
        self.assertEqual(infer_signal_tier(bp), "reference")
        self.assertTrue(is_reference_only(bp))
        self.assertFalse(is_recommendable_buy(bp))

    # —— 强势启动候选 ——

    def test_strong_startup_candidate_in_candidate_types(self):
        self.assertIn("强势启动候选", CANDIDATE_TYPES)
        self.assertIn("强势启动候选", STRONG_STARTUP_CANDIDATE_TYPES)

    def test_strong_startup_candidate_tier(self):
        bp = {"type": "强势启动候选"}
        self.assertEqual(infer_signal_tier(bp), "candidate")

    def test_strong_startup_candidate_is_recommendable(self):
        bp = {"type": "强势启动候选", "tier": "candidate"}
        self.assertTrue(is_recommendable_buy(bp))
        self.assertTrue(is_strong_startup_candidate(bp))
        self.assertFalse(is_strong_startup_watch(bp))

    # —— 强势启动观察 ——

    def test_strong_startup_watch_in_watch_types(self):
        self.assertIn("强势启动观察", WATCH_TYPES)

    def test_strong_startup_watch_tier(self):
        bp = {"type": "强势启动观察"}
        self.assertEqual(infer_signal_tier(bp), "watch")

    def test_strong_startup_watch_is_not_recommendable(self):
        bp = {"type": "强势启动观察", "tier": "watch"}
        self.assertFalse(is_recommendable_buy(bp))
        self.assertTrue(is_watch_only(bp))
        self.assertTrue(is_strong_startup_watch(bp))
        self.assertFalse(is_strong_startup_candidate(bp))

    def test_strong_startup_watch_not_in_recommendable(self):
        self.assertNotIn("强势启动观察", ALL_RECOMMENDABLE_TYPES)


if __name__ == "__main__":
    unittest.main()
