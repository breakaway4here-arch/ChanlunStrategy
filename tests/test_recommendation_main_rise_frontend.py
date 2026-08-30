"""Frontend contracts for the display-only main-rise clue."""

import unittest

from tests.test_auxiliary_frontend import _assert_node_contract


_FIXTURE = r"""
globalThis.__auxTest.state.data = { date: '2026-08-28' };
window.CHANLUN_BOOTSTRAP = { pageDate: '2026-08-28', recommendationEvidence: {
  schema_version: 1,
  report_date: '2026-08-28',
  views: { main: [{
    code: '301629',
    summary: { status: 'available', source: 'workspace', as_of: '2026-08-28', code: '301629', name: '矽电股份', sector: '半导体', formal_action: '观察' },
    decision_score: { status: 'available', source: 'decision', score: 62, components: {} },
    rank_evidence: { status: 'available', source: 'workspace', view_rank: 1, opportunity_score: 88 },
    price_evidence: { status: 'partial', source: 'prices', current_price: 309.85, reference_price: 292.32, trailing_targets: [] },
    display_derived: { status: 'partial', source: 'display' },
    daily_structure: { status: 'available', source: 'daily', summary: '日线启动' },
    sublevel_30m: { status: 'missing', reason: 'minute_data_not_serialized' },
    volume_and_capital: { status: 'missing', reason: 'not provided' },
    market_and_sector: { status: 'missing', reason: 'not provided' },
    main_rise_clue: {
      status: 'available', source: 'existing candidate strategy signals', as_of: '2026-08-28',
      clue_type: 'startup_confirmation', label: '启动确认线索',
      supporting_evidence: ['强势启动候选', '低位放量并站上MA5/MA10'],
      opposing_evidence: ['加速过热风险', '距参考价过远'],
      note: '只翻译现有证据，不生成策略、分数或正式动作'
    },
    risk_and_next: { status: 'missing', reason: 'not provided' },
    historical_validation: { status: 'missing', reason: 'not provided' }
  }] }
} };
"""


class RecommendationMainRiseFrontendTests(unittest.TestCase):

    def test_detail_shows_both_sides_and_keeps_one_formal_action(self):
        _assert_node_contract(
            self,
            "({ detail: buildMergedCandidateDetail, state: state })",
            _FIXTURE
            + r"""
const html = globalThis.__auxTest.detail({ code: '301629' }, {});
assert(html.includes('主升浪线索') && html.includes('启动确认线索'), 'main-rise clue is not rendered');
assert(html.includes('支持证据') && html.includes('强势启动候选'), 'supporting evidence is missing');
assert(html.includes('反对证据') && html.includes('加速过热风险') && html.includes('距参考价过远'), 'opposing evidence is missing');
assert(html.includes('不生成策略、分数或正式动作'), 'display-only boundary is missing');
assert((html.match(/formal-action/g) || []).length === 1, 'clue created a second formal action');
""",
        )

    def test_missing_clue_uses_truthful_empty_copy(self):
        _assert_node_contract(
            self,
            "({ detail: buildMergedCandidateDetail, state: state })",
            _FIXTURE
            + r"""
window.CHANLUN_BOOTSTRAP.recommendationEvidence.views.main[0].main_rise_clue = {
  status: 'missing', source: 'existing candidate strategy signals', as_of: '2026-08-28',
  clue_type: 'none', label: '尚未形成主升浪线索', supporting_evidence: [], opposing_evidence: [],
  reason: 'main_rise_clue_not_provided'
};
const html = globalThis.__auxTest.detail({ code: '301629' }, {});
assert(html.includes('主升浪线索') && html.includes('尚未形成主升浪线索'), 'missing clue was hidden or inflated');
assert(!html.includes('启动确认线索'), 'missing clue inherited a stale positive label');
""",
        )


if __name__ == '__main__':
    unittest.main()
