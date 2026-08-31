import unittest

import config
import run
from chanlun.preclose_pipeline import (
    PreclosePipelineComponents,
    build_preclose_main_pool,
)
from chanlun.right_side_startup import (
    POLICY_VERSION,
    apply_right_side_startup_mode,
    build_right_side_startup_state,
    resolve_right_side_startup_mode,
)
from chanlun.trend_continuation import (
    upgrade_trend_continuation_with_30min,
)
from tests.test_trend_continuation import _fixture, _fixture_result


def _candidate(code, score=None):
    row = {
        "code": code,
        "source_channel": "right_side_startup",
        "source_type": "日线右侧启动",
    }
    if score is not None:
        row["score"] = score
    return row


class RightSideStartupModeTests(unittest.TestCase):
    def test_default_mode_is_shadow(self):
        self.assertEqual("shadow", config.RIGHT_SIDE_STARTUP_MODE)
        self.assertEqual("shadow", resolve_right_side_startup_mode(None))

    def test_invalid_mode_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "off, shadow or active"):
            resolve_right_side_startup_mode("legacy")

    def test_off_returns_without_scanning_invalid_inputs(self):
        state = build_right_side_startup_state(
            [object()], [object()], mode="off"
        )

        self.assertEqual("off", state["mode"])
        self.assertEqual(POLICY_VERSION, state["policy_version"])
        self.assertEqual([], state["candidates"])
        self.assertEqual([], state["published"])
        self.assertEqual(0, state["diagnostics"]["input_count"])

    def test_shadow_keeps_candidates_out_of_published(self):
        result = apply_right_side_startup_mode(
            [_candidate("300001", 80)], mode="shadow"
        )

        self.assertEqual(["300001"], [row["code"] for row in result["candidates"]])
        self.assertEqual([], result["published"])
        self.assertEqual("shadow", result["mode"])

    def test_active_requires_unified_score_and_publishes_top_three(self):
        rows = [
            _candidate("300001", 70),
            _candidate("300002", 92),
            _candidate("300003"),
            _candidate("300004", 85),
            _candidate("300005", 80),
        ]

        result = apply_right_side_startup_mode(rows, mode="active")

        self.assertEqual(
            ["300002", "300004", "300005"],
            [row["code"] for row in result["published"]],
        )
        self.assertEqual(["300003"], result["diagnostics"]["missing_score_codes"])

    def test_active_does_not_mutate_or_remove_existing_candidates(self):
        existing = [{"code": "600000", "score": 88, "marker": ["keep"]}]
        result = apply_right_side_startup_mode(
            [_candidate("300001", 90)],
            existing_candidates=existing,
            mode="active",
        )

        self.assertEqual(existing, result["existing_candidates"])
        self.assertEqual(["keep"], existing[0]["marker"])
        self.assertEqual(["300001"], [row["code"] for row in result["published"]])

    @staticmethod
    def _preclose_components():
        def score(rows, version="pure", sector_rank_map=None):
            del version, sector_rank_map
            output = [dict(row) for row in rows]
            for row in output:
                row["score"] = 80
            return output

        return PreclosePipelineComponents(
            build_daily_structure_pool=lambda *_args, **_kwargs: ([], {}),
            upgrade_daily_candidates=lambda *_args, **_kwargs: ([], {}),
            build_strong_startup_pool=lambda *_args, **_kwargs: ([], [], {}),
            upgrade_strong_startup=lambda *_args, **_kwargs: ([], [], {}),
            right_side_startup_mode="active",
            apply_fusion_admission=lambda rows, *_args, **_kwargs: (
                [dict(row) for row in rows],
                {"output_count": len(rows)},
            ),
            apply_scores=score,
        )

    def test_frozen_fixture_matches_formal_and_preclose_adapters(self):
        fixture = _fixture()
        daily = [_fixture_result(code) for code in fixture["cases"]]
        minute30 = [_fixture_result("300709", interval="min30")]
        formal_daily = run._build_independent_daily_channels(
            daily,
            [],
            {},
            mode="active",
            classic_builder=lambda *_args: ([], [], {}),
        )
        formal_candidates, _, _ = upgrade_trend_continuation_with_30min(
            formal_daily["right_seeds"], minute30
        )

        preclose = build_preclose_main_pool(
            daily,
            minute30,
            sector_stocks={},
            sh_closes=[],
            components=self._preclose_components(),
        )

        self.assertEqual(["300709"], [row["code"] for row in formal_candidates])
        self.assertEqual(
            [row["code"] for row in formal_candidates],
            [row["code"] for row in preclose["picks_fusion"]],
        )
        self.assertEqual(
            {"002636", "002952"},
            {row["code"] for row in formal_daily["right_watchlist"]},
        )
        self.assertEqual(
            2,
            preclose["diagnostics"]["right_side_startup"]["daily_watch_count"],
        )

    def test_intraday_change_can_demote_with_same_explainable_failure(self):
        fixture = _fixture()
        daily = [_fixture_result(code) for code in fixture["cases"]]
        broken = _fixture_result("300709", interval="min30")
        broken.closes[-1] = fixture["cases"]["300709"]["reference_price"] - 1.0
        broken.opens[-1] = broken.closes[-1]
        broken.highs[-1] = broken.closes[-1] + 0.1
        broken.lows[-1] = broken.closes[-1] - 0.1
        formal_daily = run._build_independent_daily_channels(
            daily,
            [],
            {},
            mode="active",
            classic_builder=lambda *_args: ([], [], {}),
        )
        formal_candidates, formal_waiting, formal_diag = (
            upgrade_trend_continuation_with_30min(
                formal_daily["right_seeds"], [broken]
            )
        )

        preclose = build_preclose_main_pool(
            daily,
            [broken],
            sector_stocks={},
            sh_closes=[],
            components=self._preclose_components(),
        )

        self.assertEqual([], formal_candidates)
        self.assertEqual("30min_reference_hold", formal_waiting[0]["failure_gate"])
        self.assertEqual(1, formal_diag["watch_due_to_reference_break"])
        self.assertEqual([], preclose["picks_fusion"])
        self.assertEqual(
            1,
            preclose["diagnostics"]["right_side_startup"]["upgrade"][
                "watch_due_to_reference_break"
            ],
        )


if __name__ == "__main__":
    unittest.main()
