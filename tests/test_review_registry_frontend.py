"""Frontend contracts for the read-only five-day review registry."""

import unittest

from tests.test_auxiliary_frontend import _assert_node_contract


FIXTURE = r"""
const fixture = JSON.parse(fs.readFileSync(
  'tests/fixtures/five_day_review/review-registry-frontend.json', 'utf8'
));
const index = JSON.parse(JSON.stringify(fixture.index));
index.review_registry.entries.push(
  JSON.parse(JSON.stringify(fixture.synthetic_boundary_entry)),
  JSON.parse(JSON.stringify(fixture.synthetic_calendar_unknown_entry))
);
"""


class TestReviewRegistryFrontend(unittest.TestCase):
    def test_registry_renders_complete_rows_counts_sources_and_safe_horizons(self):
        _assert_node_contract(
            self,
            "({ render: renderReviewRegistry, entry: renderReviewRegistryEntry })",
            FIXTURE + r"""
const html = globalThis.__auxTest.render(index, '2026-09-14');
assert(html.includes('展示对象复盘'), 'registry heading missing');
assert(html.includes('登记窗口 2026-09-09 — 2026-09-15'), 'window boundary missing');
assert(html.includes('价格数据截止 2026-09-16'), 'price cutoff missing');
['登记对象</span><strong>4', '已到期端点</span><strong>3',
 '可计算端点（含内部诊断）</span><strong>2',
 '内部诊断端点</span><strong>1', '缺价端点</span><strong>1',
 '待到期端点</span><strong>5', '未知&#47;不兼容</span><strong>4'].forEach(function (text) {
  assert(html.includes(text), 'selected-date count missing: ' + text);
});
['603344', '603400', '000001', '000002'].forEach(function (code) {
  assert(html.includes('data-review-code="' + code + '"'), 'registered row missing: ' + code);
});
assert((html.match(/data-review-code=/g) || []).length === 4,
  'complete registry was truncated or duplicated');
assert(html.includes('窗口第2次（非首次信号）'), 'occurrence was presented as a new signal');
assert(html.includes('正式主推 · 正式 · 原名次 #1')
  && html.includes('原动作 可上车') && html.includes('原分 62')
  && html.includes('版本 daily-fusion-close-v2'),
  'formal source trace disappeared');
assert(html.includes('基础候选 · 研究 · 原名次 #1')
  && html.includes('版本 daily-pure-close-v2'),
  'research/version trace disappeared');
assert(html.includes('决策版本 decision-v2') && html.includes('政策版本 decision-v2'),
  'decision or policy version trace disappeared');
assert(html.includes('事故排除'), 'incident-excluded source was not disclosed');
assert(html.includes('原分 0'), 'real numeric zero score became missing');
assert(html.includes('该快照执行状态原值 future_execution_state（未识别）'),
  'unknown execution status was guessed or discarded');
assert(html.includes('风险未登记') && html.includes('涨幅过热'),
  'registered and missing risks were not separated');
assert(html.includes('缺价') && html.includes('待到期')
  && html.includes('交易日历未知'), 'horizon states collapsed together');
assert(html.includes('状态原值 future_status_v2（未识别，不计收益）'),
  'unknown horizon status was not kept as a non-return gap');
assert(html.includes('0.00%'), 'verified numeric zero return disappeared');
assert(html.includes('-9.99%'), 'permitted legacy internal price change disappeared');
assert(html.includes('价格变化（内部口径）')
  && html.includes('价基元数据未完整；不等于策略/成交收益'),
  'legacy internal diagnostic was promoted or left unexplained');
assert(!html.includes('20.00%'), 'unknown future status leaked a return');
assert(html.includes('源值 25.29 → 22.76'),
  'unverified pairing did not preserve readable original values');
assert(html.includes('正式与研究来源逐条追溯，不跨角色/版本合并收益'),
  'mixed role/version boundary missing');
assert(html.includes('覆盖已确认 2 · 覆盖待核验 2'),
  'registry summary did not disclose unconfirmed coverage');

const confirmedEntry = globalThis.__auxTest.entry(
  index.review_registry.entries.find(function (entry) { return entry.code === '603344'; })
);
assert(confirmedEntry.includes('源报告日 2026-09-14'),
  'entry did not state which report snapshot it reads');
assert(confirmedEntry.includes('该快照执行状态 等待条件（原值 waiting）'),
  'historical execution state still looked current');
assert(confirmedEntry.includes('页面状态 正式待确认（原值 formal_incomplete）'),
  'known page status was not mapped without rejudging execution');
assert(confirmedEntry.includes('正式主推 · 正式 · 原名次 #1')
  && confirmedEntry.includes('看点 Top10 · 研究 · 原名次 #1')
  && confirmedEntry.includes('基础候选 · 研究 · 原名次 #1'),
  'source views still exposed raw technical keys');
assert(confirmedEntry.includes('研究阅读顺序，不代表次日收益排名'),
  'reachable research rank lacks its interpretation boundary');
assert(!confirmedEntry.includes('覆盖未确认')
  && !confirmedEntry.includes('报告身份待核验'),
  'confirmed display snapshot was downgraded');

function coverageHtml(kind, coverage) {
  const row = JSON.parse(JSON.stringify(index.review_registry.entries[0]));
  row.snapshot_kind = kind;
  row.coverage_status = coverage;
  return globalThis.__auxTest.entry(row);
}
assert(coverageHtml('legacy_workspace_fallback', 'unconfirmed_legacy_workspace')
  .includes('旧视图口径，覆盖未确认'), 'legacy workspace coverage warning missing');
assert(coverageHtml('postprocessed_html_bootstrap', 'unconfirmed_report_identity')
  .includes('另版展示快照，报告身份待核验'),
  'postprocessed snapshot identity warning missing');
assert(coverageHtml('future_snapshot_kind', 'future_coverage_state')
  .includes('覆盖状态原值 future_coverage_state（未识别）'),
  'unknown coverage state was guessed or discarded');
const unknownPageEntry = JSON.parse(JSON.stringify(index.review_registry.entries[0]));
unknownPageEntry.current_page_status = 'future_page_state';
assert(globalThis.__auxTest.entry(unknownPageEntry)
  .includes('页面状态原值 future_page_state（未识别）'),
  'unknown page status was guessed or discarded');
""",
        )

    def test_legacy_internal_diagnostic_is_narrow_and_new_pairs_stay_hidden(self):
        _assert_node_contract(
            self,
            "({ horizon: renderReviewRegistryHorizon, entry: renderReviewRegistryEntry })",
            FIXTURE + r"""
const star = index.review_registry.entries.find(function (entry) {
  return entry.report_date === '2026-09-14' && entry.code === '603344';
});
const starHtml = globalThis.__auxTest.entry(star);
assert(starHtml.includes('价格变化（内部口径）'),
  'real StarDeSheng legacy internal T+1 was hidden');
assert(starHtml.includes('-9.99%'), 'real legacy internal price change missing');
assert(starHtml.includes('价基元数据未完整；不等于策略/成交收益'),
  'legacy internal limitation missing');
assert(starHtml.includes('review-registry-internal-change')
  && !starHtml.includes('review-registry-return'),
  'internal price change was styled as verified return');

assert(fixture.real_unverified_new_pairs.length === 9, 'real new-pair fixture incomplete');
fixture.real_unverified_new_pairs.forEach(function (pair) {
  const horizon = Object.assign({}, fixture.real_unverified_new_pair_contract, {
    base_price: pair.base_price,
    endpoint_price: pair.endpoint_price
  });
  const rendered = globalThis.__auxTest.horizon('T+1', horizon);
  assert(rendered.includes('价基未核验，不计收益'),
    pair.code + ' new pair was not identified as unverified');
  assert(!rendered.includes('review-registry-return')
    && !rendered.includes('review-registry-internal-change')
    && !rendered.includes('%'), pair.code + ' new pair leaked a calculated value');
});

function renderCase(overrides) {
  const base = {
    target_trading_date: '2026-09-15',
    status: 'calculated_legacy_internal', matured: true,
    base_price: 10, endpoint_price: 11,
    price_basis_status: 'legacy_same_index_qfq_metadata_incomplete',
    return_pct: 10
  };
  return globalThis.__auxTest.horizon('T+1', Object.assign(base, overrides || {}));
}
const newPairTrap = Object.assign({}, fixture.real_unverified_new_pair_contract, {
  base_price: 10, endpoint_price: 11, return_pct: 10
});
[
  globalThis.__auxTest.horizon('T+1', newPairTrap),
  renderCase({status: 'calculated_internal',
    price_basis_status: 'internal_qfq_metadata_incomplete'}),
  renderCase({status: 'future_calculated', price_basis_status: 'canonical_qfq_verified'}),
  renderCase({status: 'calculated_verified',
    price_basis_status: 'canonical_qfq_verified_extra'}),
  renderCase({status: 'invalid_price'}),
  renderCase({status: 'pending', matured: false}),
  renderCase({endpoint_price: 0, return_pct: -100}),
  renderCase({return_pct: Infinity}),
  renderCase({return_pct: '10'}),
  renderCase({endpoint_price: '11'}),
  renderCase({price_basis_status: 'legacy_same_index_future_metadata_incomplete'})
].forEach(function (rendered, index) {
  assert(!rendered.includes('review-registry-return')
    && !rendered.includes('review-registry-internal-change'),
    'negative boundary leaked a value at index ' + index);
});
assert(renderCase({endpoint_price: 0, return_pct: -100}).includes('源值 10.00 → 0.00'),
  'real zero endpoint was not kept readable');
""",
        )

    def test_page_renders_registry_before_quote_refresh_and_filters_with_source_date(self):
        _assert_node_contract(
            self,
            "({ page: renderComparisonPage, registry: renderReviewRegistry })",
            FIXTURE + r"""
function control(value) {
  return {
    value: value, textContent: '', innerHTML: '', handlers: {},
    addEventListener: function (name, handler) { this.handlers[name] = handler; }
  };
}
const nodes = {
  '#comparisonSource': control('2026-09-14'),
  '#comparisonTarget': control('current'),
  '#comparisonRefresh': control(''),
  '#comparisonQuoteStatus': control(''),
  '#comparisonReviewRegistry': control(''),
  '#comparisonContent': control('')
};
const root = {
  innerHTML: '',
  querySelector: function (selector) { return nodes[selector] || null; }
};
globalThis.__auxTest.page(index, root);
assert(nodes['#comparisonReviewRegistry'].innerHTML.includes('603344'),
  'registry waited for a live quote refresh');
assert(nodes['#comparisonContent'].innerHTML.includes('尚未刷新当前行情'),
  'legacy comparison refresh boundary changed');
nodes['#comparisonSource'].value = '2026-09-15';
nodes['#comparisonSource'].handlers.change();
assert(nodes['#comparisonReviewRegistry'].innerHTML.includes('该源报告日没有登记对象'),
  'source report dropdown did not filter registry entries');
assert(nodes['#comparisonReviewRegistry'].innerHTML.includes('登记覆盖截至 2026-09-15'),
  'registry coverage cutoff was hidden');
assert(nodes['#comparisonReviewRegistry'].innerHTML.includes('登记对象</span><strong>0'),
  'normal empty registration was not kept distinct from unavailable');

const unavailableIndex = JSON.parse(JSON.stringify(index));
unavailableIndex.review_registry.status = 'unavailable';
unavailableIndex.review_registry.unavailable_reason = 'review_task_failed';
unavailableIndex.review_registry.entries = [];
const unavailable = globalThis.__auxTest.registry(unavailableIndex, '2026-09-14');
assert(unavailable.includes('展示对象复盘暂不可用'),
  'explicit unavailable registry was shown as a valid zero');
assert(unavailable.includes('登记窗口 2026-09-09 — 2026-09-15')
  && unavailable.includes('价格数据截止 2026-09-16'),
  'unavailable registry lost its known window/cutoff');
assert(unavailable.includes('复盘任务失败（原值 review_task_failed）'),
  'backend unavailable reason was hidden');
assert(!unavailable.includes('登记对象</span><strong>0'),
  'unavailable registry fabricated a valid zero count');

const legacy = globalThis.__auxTest.registry({
  latest_date: '2026-09-10', dates: ['2026-09-10'], reports: {}
}, '2026-09-10');
assert(legacy.includes('展示对象登记暂未提供'), 'legacy index did not degrade locally');
assert(legacy.includes('原正式/研究比较仍可使用'),
  'missing registry incorrectly disabled the existing comparison');
assert(legacy.includes('当前索引覆盖截至 2026-09-10'),
  'legacy index coverage date was presented as current');
""",
        )


if __name__ == "__main__":
    unittest.main()
