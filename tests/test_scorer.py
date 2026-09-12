import unittest
from unittest.mock import patch

from chanlun.scorer import (
    _score_sector_strength,
    apply_scores,
    normalize_sector_rank_map,
)


class ScorerSectorRankTests(unittest.TestCase):

    @staticmethod
    def _pick():
        return {
            "code": "600001",
            "name": "测试票",
            "sector": "甲板块",
            "sector_rank": 1,
            "sector_strength_label": "资金流入TOP1",
            "best_buy_point": {"type": "一买", "tier": "candidate", "index": 1},
            "closes": [10.0, 10.2],
            "resonance": {"level": "中"},
            "volumes": [100.0] * 10,
        }

    def test_apply_scores_writes_the_same_normalized_rank_contract_it_scores(self):
        pick = self._pick()
        apply_scores(
            [pick],
            version="fusion",
            sector_rank_map=[
                {"name": "甲板块", "sector_rank": 100},
                {"name": "甲板块", "sector_rank": 1},
            ],
        )

        self.assertEqual(pick["sector_rank"], 2)
        self.assertEqual(pick["sector_rank_used"], 2)
        self.assertEqual(pick["sector_rank_source"], "ordered_fallback_conflict")
        self.assertEqual(pick["sector_strength_label"], "资金流入TOP2")
        self.assertTrue(any(
            item["type"] == "duplicate_name_rank_conflict"
            for item in pick["sector_rank_diagnostics"]
        ))
        self.assertEqual(_score_sector_strength({"sector": "甲板块"}, [
            {"name": "甲板块", "sector_rank": 100},
            {"name": "甲板块", "sector_rank": 1},
        ]), 85)

    def test_invalid_rank_map_is_explicit_and_does_not_use_stock_rank_for_score(self):
        pick = self._pick()
        apply_scores([pick], version="fusion", sector_rank_map={"甲板块": 1})

        self.assertEqual(pick["sector_rank"], 1)
        self.assertIsNone(pick["sector_rank_used"])
        self.assertEqual(pick["sector_rank_source"], "invalid_rank_map")
        self.assertEqual(
            pick["sector_rank_diagnostics"][0]["type"],
            "invalid_sector_rank_map",
        )

    def test_apply_scores_normalizes_rank_map_once_for_the_whole_batch(self):
        picks = [self._pick(), self._pick()]
        picks[1]["code"] = "600002"
        with patch(
            "chanlun.scorer.normalize_sector_rank_map",
            wraps=normalize_sector_rank_map,
        ) as normalize:
            apply_scores(
                picks,
                version="fusion",
                sector_rank_map=[{"name": "甲板块", "sector_rank": 2}],
            )

        self.assertEqual(normalize.call_count, 1)
    def test_explicit_sector_rank_is_used_instead_of_list_position(self):
        sectors = [
            {"name": "甲板块", "sector_rank": 5},
            {"name": "乙板块", "sector_rank": 1},
        ]

        self.assertEqual(
            _score_sector_strength({"sector": "甲板块"}, sectors),
            70,
        )

    def test_invalid_explicit_rank_falls_back_to_position_without_crashing(self):
        sectors = [
            {"name": "一"},
            {"name": "二"},
            {"name": "三"},
            {"name": "甲板块", "sector_rank": 1.9},
            {"name": "乙板块", "sector_rank": float("inf")},
        ]

        self.assertEqual(
            _score_sector_strength({"sector": "甲板块"}, sectors),
            70,
        )
        self.assertEqual(
            _score_sector_strength({"sector": "乙板块"}, sectors),
            70,
        )

    def test_missing_rank_map_keeps_neutral_sector_score(self):
        self.assertEqual(
            _score_sector_strength({"sector": "甲板块"}, None),
            40,
        )

    def test_duplicate_explicit_ranks_do_not_make_every_sector_top_one(self):
        sectors = [
            {"name": "甲板块", "sector_rank": 1},
            {"name": "乙板块", "sector_rank": 1},
        ]

        self.assertEqual(
            _score_sector_strength({"sector": "甲板块"}, sectors),
            100,
        )
        self.assertNotEqual(
            _score_sector_strength({"sector": "乙板块"}, sectors),
            100,
        )

    def test_duplicate_name_does_not_hide_later_valid_rank(self):
        sectors = [
            {"name": "甲板块"},
            {"name": "甲板块", "sector_rank": 2},
        ]

        self.assertEqual(
            _score_sector_strength({"sector": "甲板块"}, sectors),
            85,
        )

    def test_non_mapping_sector_rows_are_ignored(self):
        sectors = [
            None,
            {"name": "甲板块", "sector_rank": 2},
            "invalid",
        ]

        self.assertEqual(
            _score_sector_strength({"sector": "甲板块"}, sectors),
            85,
        )

    def test_same_name_conflicting_ranks_are_conservatively_degraded(self):
        sectors = [
            {"name": "甲板块", "sector_rank": 100},
            {"name": "甲板块", "sector_rank": 1},
        ]

        normalized, diagnostics = normalize_sector_rank_map(
            sectors,
            return_diagnostics=True,
        )
        self.assertEqual(normalized[0]["sector_rank"], 2)
        self.assertNotEqual(
            _score_sector_strength({"sector": "甲板块"}, sectors),
            100,
        )
        self.assertTrue(any(
            item["type"] == "duplicate_name_rank_conflict"
            for item in diagnostics
        ))


if __name__ == "__main__":
    unittest.main()
