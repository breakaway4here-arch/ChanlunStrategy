"""User-visible coverage summary contracts for projected audit facts."""

import json
from pathlib import Path
import unittest

from chanlun.decision_workbench import _coverage
from tests.test_auxiliary_frontend import _assert_node_contract
from tests.test_selection_coverage_summary import recorded_report


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

    def test_new_projection_names_evaluation_scopes_and_preserves_unique_stock_counts(self):
        coverage = _coverage(recorded_report())
        self._render_assertions(coverage, """
assert(text.includes('资格通过 60只'), 'eligible count hidden: ' + text);
assert(text.includes('实际日线扫描 42只'), 'actual scan hidden: ' + text);
assert(text.includes('检索名额外 20只'), 'quota scope hidden: ' + text);
assert(text.includes('经典30分钟（3只）：口径待核验 1只'), 'basis stock count wrong: ' + text);
assert(text.includes('有效无确认 1只'), 'valid no confirmation hidden: ' + text);
assert(text.includes('评估通过 1只'), 'confirmation result hidden: ' + text);
assert(text.includes('上市年限未核验 8只'), 'unknown listing age hidden: ' + text);
assert(text.includes('上市年限不足 1只'), 'known age rejection hidden: ' + text);
assert(!text.includes('口径待核验 2只'), 'buy points counted as stocks: ' + text);
""")

    def test_legacy_reasons_remain_unrecorded_and_empty_formal_is_scope_limited(self):
        self._render_assertions(_coverage({}), """
assert(text.includes('经典30分钟评估未记录'), 'missing evaluation became zero: ' + text);
assert(text.includes('实际日线扫描未记录'), 'missing scan became retrieval: ' + text);
assert(!text.includes('有效无确认 0只'), 'unknown became no confirmation: ' + text);
""")

    def test_real_legacy_report_renders_recorded_scans_without_inventing_confirmation(self):
        report = json.loads((Path(__file__).resolve().parents[1]
                            / 'docs/data/2026-10-19.json').read_text())
        self._render_assertions(_coverage(report), """
assert(text.includes('资格通过 3465只'), 'real eligibility hidden: ' + text);
assert(text.includes('实际日线扫描 1205只（含附加目标）'), 'real scan scope unclear: ' + text);
assert(text.includes('检索名额外 2265只'), 'real quota count hidden: ' + text);
assert(text.includes('日线未定稿 469'), 'real nonfinal gaps hidden: ' + text);
assert(text.includes('经典30分钟评估未记录'), 'legacy drops mistaken for no confirmation: ' + text);
assert(text.includes('上市年限细分未记录'), '347 exclusions mistaken for known age rejection: ' + text);
assert(!text.includes('有效无确认 0只'), 'legacy unknown count became zero: ' + text);
""")
        _assert_node_contract(self, '{ explain: buildFormalOutcomeExplanation }', """
const html=globalThis.__auxTest.explain({main:{state:'verified_empty',count:0},
  coverage:{status:'partial'}}, {});
assert(html.includes('已评估范围内暂无'), 'empty result lacks scope: ' + html);
assert(html.includes('覆盖'), 'empty result hides coverage boundary: ' + html);
""")

    def test_existing_projected_summary_keeps_legacy_recorded_retrieval_count(self):
        self._render_assertions({'retrieval': {'full_a': 100, 'retrieval': 40,
                                               'first_failure': 20}}, """
assert(text.includes('检索筛选未入 20只（旧记录）'), 'legacy recorded count lost: ' + text);
""")

    def test_primary_empty_state_references_evaluated_scope_and_pending_facts(self):
        _assert_node_contract(self, '{ empty: buildCandidateEmptyState, state: state }', """
window.CHANLUN_BOOTSTRAP={pageDate:'2026-10-19',decisionWorkbench:{
  schema_version:'decision-workbench-v1',report_date:'2026-10-19',phase:'formal',items:[]}};
globalThis.__auxTest.state.data={date:'2026-10-19'};
globalThis.__auxTest.state.workspace={views:{main:[]},view_meta:{}};
const html=globalThis.__auxTest.empty('decision_formal',{},{});
assert(html.includes('本期暂无主推'), 'empty state identity changed: ' + html);
assert(html.includes('评估范围与待核验'), 'primary empty state hides coverage boundary: ' + html);
""")

    def test_candidate_identity_does_not_explain_empty_formal_recommendations(self):
        _assert_node_contract(self, '{ explain: buildFormalOutcomeExplanation }', """
const historical=JSON.parse(fs.readFileSync('docs/data/2026-09-22.json','utf8'));
const candidate=historical.picks_fusion.find(row=>row.code==='688262');
assert(candidate.signal_tier==='candidate' && candidate.decision_engine_v1.total_score===61,
  'historical candidate positive control changed');
const historicalMain=historical.workspace.views.main;
assert(historicalMain.some(row=>row.code==='688262'), 'candidate main positive control missing');
const positive=globalThis.__auxTest.explain({main:{state:'available',count:historicalMain.length}},historical);
assert(positive.includes('本期 1 只正式结果'), 'candidate was treated as ineligible for main: '+positive);
const current=JSON.parse(fs.readFileSync('docs/data/2026-10-19.json','utf8'));
assert(current.workspace.views.main.length===0 && current.diagnostics.fusion_admission.kept_candidate===3,
  'current empty control changed');
const empty=globalThis.__auxTest.explain({main:{state:'verified_empty',count:0}},current);
assert(!empty.includes('尚未形成正式买点'), 'candidate tier falsely explains main=0: '+empty);
assert(empty.includes('融合筛选保留 3 只候选'), 'recorded candidate count hidden: '+empty);
assert(empty.includes('决策评分及风险条件'), 'remaining decision gates hidden: '+empty);
""")

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
