"""R3 frontend contracts for the five-day review follow-up."""

import unittest

from tests.test_auxiliary_frontend import _assert_node_contract


class TestFiveDayR3Frontend(unittest.TestCase):
    def test_highlights_explains_research_order_without_changing_rank(self):
        _assert_node_contract(
            self,
            "({ render: renderViewDescription, state: state, nodes: nodes })",
            r"""
window.CHANLUN_BOOTSTRAP = { pageDate: '2026-09-15' };
const t = globalThis.__auxTest;
t.state.data = { date: '2026-09-15' };
t.state.currentView = 'highlights';
t.state.workspace = {
  views: { highlights: [{ code: 'first' }, { code: 'second' }] },
  view_meta: { highlights: { availability: { state: 'available' } } }
};
t.nodes.description = { innerHTML: '' };
t.render();
assert(t.nodes.description.innerHTML.includes('研究阅读顺序，不代表次日收益排名'),
  'highlights did not state the research-order boundary');
assert(t.state.workspace.views.highlights.map(function (item) { return item.code; }).join(',')
  === 'first,second', 'view description changed the original rank order');
""",
        )

    def test_real_sep15_rows_show_source_risk_or_unregistered_without_borrowing(self):
        _assert_node_contract(
            self,
            "({ rows: decisionRows, summary: buildCandidateRowSummary, reason: renderCandidateRowReason, state: state })",
            r"""
const fixture = JSON.parse(fs.readFileSync(
  'tests/fixtures/five_day_review/2026-09-15-r3-sources.json', 'utf8'
));
assert(fixture.meta.source_commit === '0fc3de99b3a7bf2ff035c1e1db55474f97bf5efb',
  'fixture source commit changed');
assert(fixture.meta.source_page_sha256
  === '689088cc68b84a13211e2d5e9915fe549fbccc208f29da8ca52167d93ccb283f',
  'fixture source page hash changed');
const snapshot = fixture.snapshot;
window.CHANLUN_BOOTSTRAP = snapshot;
const t = globalThis.__auxTest;
t.state.data = { date: snapshot.pageDate };
t.state.currentView = 'decision_all';
const workbench = snapshot.decisionWorkbench;
const rows = t.rows(workbench, 'decision_all');
assert(rows.map(function (row) { return row.code; }).join(',')
  === workbench.items.map(function (item) { return item.code; }).join(','),
  'decision rows changed the frozen original order');
assert(rows.map(function (row) { return row.code; }).join(',') === '688150,600184',
  'fixture no longer preserves the two source rows in original page order');
assert(workbench.items.map(function (item) {
  return item.strategy_results.find(function (strategy) {
    return strategy.strategy_id === item.evidence_view;
  }).view_rank;
}).join(',') === '1,2', 'original highlights ranks changed');

function rowHtml(code, sourceWorkbench) {
  const projection = sourceWorkbench || workbench;
  const row = t.rows(projection, 'decision_all').find(function (item) {
    return item.code === code;
  });
  assert(row, 'frozen row missing: ' + code);
  return t.reason(row, 'decision_all', t.summary(row, 'decision_all'));
}

const guangdian = rowHtml('600184');
assert(guangdian.includes('风险：涨幅过热'),
  'real Guangdian selected-source risk is not close to its reason');

const missing = rowHtml('688150');
assert(missing.includes('风险：未登记'),
  'missing selected-source risk was hidden instead of marked unregistered');

const conflicting = JSON.parse(JSON.stringify(workbench));
const target = conflicting.items.find(function (item) { return item.code === '688150'; });
assert(target && target.evidence_view === 'highlights', 'real missing-risk fixture changed');
target.risk_flags = ['其他来源风险'];
const other = target.strategy_results.find(function (strategy) {
  return strategy.strategy_id !== target.evidence_view;
});
assert(other, 'real multi-source fixture missing');
other.candidate.risk_flags = ['其他来源风险'];
other.evidence.risk_and_next.risk_labels = ['其他来源风险'];
const protectedHtml = rowHtml('688150', conflicting);
assert(protectedHtml.includes('风险：未登记'),
  'selected source borrowed another source risk');
assert(!protectedHtml.includes('其他来源风险'),
  'another source risk leaked next to the selected-source reason');
""",
        )


if __name__ == "__main__":
    unittest.main()
