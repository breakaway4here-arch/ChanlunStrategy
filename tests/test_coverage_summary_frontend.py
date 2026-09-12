"""User-visible coverage summary contracts for projected audit facts."""

import json
import unittest

from chanlun.decision_workbench import _coverage
from tests.test_auxiliary_frontend import _assert_node_contract


class TestCoverageSummaryFrontend(unittest.TestCase):
    def _render_assertions(self, coverage, assertions):
        _assert_node_contract(
            self,
            "{ render: renderCoverageSummary }",
            "const text=globalThis.__auxTest.render({});\n{}".format(
                json.dumps(coverage, ensure_ascii=False), assertions
            ),
        )

    def test_actual_python_projection_exposes_close_and_identity_counts(self):
        coverage = _coverage({
            "selection_input_health": {
                "status": "partial",
                "market_close_snapshot": {
                    "status": "partial",
                    "reason": "identity_migration_pending",
                    "coverage": 11 / 12,
                    "coverage_numerator": 11,
                    "coverage_denominator": 12,
                    "minimum_coverage": 0.9,
                    "identity_pending_rows": 1,
                    "identity_pending_codes": ["920001"],
                },
            },
        })

        self.assertEqual(coverage["market_close_snapshot"]["available"], 11)
        self.assertEqual(coverage["market_close_snapshot"]["required"], 12)
        self._render_assertions(
            coverage,
            """
assert(text.includes('收盘核验 11/12'), 'close snapshot count hidden: ' + text);
assert(text.includes('身份待核验 1'), 'identity pending count hidden: ' + text);
assert(!text.includes('identity_migration_pending'), 'internal reason leaked: ' + text);
assert(!text.includes('920001'), 'internal pending code leaked: ' + text);
""",
        )

    def test_partial_and_unavailable_quantity_show_only_provided_counts(self):
        for status, available, required, pending, label in (
            ("partial", 9, 10, 1, "量能部分核验"),
            ("unavailable", 3, 10, 7, "量能不可用"),
        ):
            with self.subTest(status=status):
                coverage = _coverage({
                    "selection_input_health": {
                        "status": status,
                        "by_strategy": {
                            "daily_fusion": {
                                "quantity": {
                                    "status": status,
                                    "available_count": available,
                                    "required_count": required,
                                    "pending_codes": [
                                        "Q{}".format(index) for index in range(pending)
                                    ],
                                },
                            },
                        },
                    },
                })
                self._render_assertions(
                    coverage,
                    """
assert(text.includes({label}), 'quantity status hidden: ' + text);
assert(text.includes({counts}), 'quantity available/required hidden: ' + text);
assert(text.includes({pending}), 'quantity pending hidden: ' + text);
""".format(
                        label=json.dumps(label, ensure_ascii=False),
                        counts=json.dumps(
                            "{}/{}".format(available, required), ensure_ascii=False
                        ),
                        pending=json.dumps(
                            "待核验 {}".format(pending), ensure_ascii=False
                        ),
                    ),
                )

    def test_unknown_counts_do_not_invent_zero_or_add_absent_field_noise(self):
        legacy = _coverage({})
        self._render_assertions(
            legacy,
            """
assert(!text.includes('收盘核验'), 'absent snapshot added noisy text: ' + text);
assert(!text.includes('量能'), 'absent quantity added noisy text: ' + text);
assert(!text.includes('0/0'), 'unknown counts became zero: ' + text);
""",
        )

        unknown_counts = {
            "status": "partial",
            "market_close_snapshot": {"status": "partial"},
            "quantity": {"status": "partial", "pending": 2},
        }
        self._render_assertions(
            unknown_counts,
            """
assert(text.includes('收盘核验部分缺失'), 'known snapshot status hidden: ' + text);
assert(text.includes('量能部分核验'), 'known quantity status hidden: ' + text);
assert(text.includes('待核验 2'), 'provided pending count hidden: ' + text);
assert(!text.includes('0/0'), 'unknown counts became zero: ' + text);
""",
        )


if __name__ == "__main__":
    unittest.main()
