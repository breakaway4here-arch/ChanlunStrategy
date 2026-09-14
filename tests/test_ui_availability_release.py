"""Round 7 availability contracts for the published report UI.

These tests are deliberately limited to the availability release boundary:
the published ref-to-chart path, local degradation of optional facts, the
three current-detail entry points, and source/purpose preservation.  They do
not enable or specify the rejected cross-period fact merger.
"""

import unittest

from tests.test_auxiliary_frontend import _assert_node_contract


class UIAvailabilityRelease(unittest.TestCase):
    def test_published_ref_pool_candidate_keeps_real_ohlc(self):
        _assert_node_contract(self, "{ find: findRawCandidate, state: state }", r'''
const t = globalThis.__auxTest;
t.state.data = {
  date: '2026-09-11',
  startup_watchlist: [{
    code: '000636', name: '风华高科',
    dates: ['2026-09-10', '2026-09-11'],
    opens: [50.0, 51.5], highs: [52.0, 55.99],
    lows: [49.0, 51.09], closes: [51.0, 55.99]
  }]
};
t.state.rawPoolCandidates = null;
const raw = t.find({ pool: 'startup_watchlist', code: '000636' });
if (!raw || raw.code !== '000636' || raw.closes[1] !== 55.99)
  throw new Error('published ref pool did not return the real OHLC candidate');
''')

    def test_ohlc_chart_survives_missing_quantity_and_moving_average_series(self):
        _assert_node_contract(self, "{ chart: renderChart, state: state }", r'''
const t = globalThis.__auxTest;
let option = null;
const mount = { innerHTML: '', isConnected: true };
const lane = { innerHTML: '' };
const switcher = { innerHTML: '', querySelectorAll() { return []; } };
window.echarts = { init(node) { return {
  getDom() { return node; },
  setOption(value) { option = value; },
  getOption() { return option || {}; },
  dispose() {}, resize() {}
}; } };
        t.state.data = { date: '2026-09-11' };
t.state.chartMount = mount;
t.state.chartAnnotationLane = lane;
t.state.chartLayerSwitcher = switcher;
t.state.chartLayer = 'decision';
const raw = {
  code: '000636', snapshot_id: '2026-09-11',
  dates: ['2026-09-10', '2026-09-11'],
  opens: [50.0, 51.5], highs: [52.0, 55.99],
  lows: [49.0, 51.09], closes: [51.0, 55.99],
  volumes: [], ema5: [], ema20: [], ma5: [], ma10: [],
  chart_annotations: { markPoints: [], markLines: [], labels: [] }
};
t.chart(raw, { code: '000636', snapshot_id: '2026-09-11' });
const candle = (option.series || []).find((series) => series.type === 'candlestick');
if (!candle || candle.data.length !== 2)
  throw new Error('OHLC series disappeared when optional series were missing');
const last = candle.data[candle.data.length - 1];
if (JSON.stringify(last) !== JSON.stringify([51.5, 55.99, 51.09, 55.99]))
  throw new Error('OHLC values were changed while degrading optional modules');
''')

    def test_short_judgment_keeps_real_next_and_cancel_conditions(self):
        _assert_node_contract(self, "{ brief: buildUnifiedShortJudgment }", r'''
const t = globalThis.__auxTest;
const html = t.brief({
  code: '000636', primary_reason: '等待回踩',
  next_confirmation: [], invalidation: [], blocking_reasons: []
}, { risk_and_next: {
  status: 'available',
  next_confirmation: { status: 'available', items: [{ text: '回踩 55.00 确认' }] },
  cancel_conditions: { status: 'available', items: [{ text: '跌破 51.00 取消' }] }
} }, false, 'formal', 'after');
if (!html.includes('回踩 55.00 确认') || !html.includes('跌破 51.00 取消'))
  throw new Error('real next/cancel conditions were not shown in the short judgment');
if (html.includes('具体失效条件待补充'))
  throw new Error('real cancel condition was replaced by the missing-condition placeholder');
''')

    def test_not_applicable_conditions_are_explicit_without_claiming_satisfied(self):
        _assert_node_contract(self, "{ brief: buildUnifiedShortJudgment }", r'''
const t = globalThis.__auxTest;
const html = t.brief({
  code: '900003', primary_reason: '条件不适用于本期',
  next_confirmation: [], invalidation: [], blocking_reasons: []
}, { risk_and_next: {
  status: 'available',
  next_confirmation: { status: 'not_applicable', items: [], empty_text: '本期不适用下一核验' },
  cancel_conditions: { status: 'not_applicable', items: [], empty_text: '本期不适用取消条件' }
} }, false, 'formal', 'after');
if (!html.includes('本期不适用下一核验') || !html.includes('本期不适用取消条件'))
  throw new Error('not-applicable condition status was reduced to generic missing text');
if (html.includes('已满足') || html.includes('条件已完整'))
  throw new Error('not-applicable conditions were presented as satisfied');
''')

    def test_selected_quick_comparison_exposes_current_detail_action(self):
        _assert_node_contract(self, "{ render: renderQuickComparison, state: state }", r'''
const t = globalThis.__auxTest;
const item = { code: '000636', name: '风华高科', page_status: 'formal_ready',
  action_semantics: 'formal', formal_action: '可上车' };
t.state.data = {
  date: '2026-09-11',
  selection_input_health: {
    schema_version: 2, status: 'verified',
    by_view: { main: { status: 'verified', formal_actions_allowed: true } },
    by_strategy: { daily_fusion: { status: 'verified', formal_actions_allowed: true } }
  }
};
t.state.workspace = { views: { main: [item] }, view_meta: {
  main: { role: 'formal', action_semantics: 'formal', availability: { state: 'available' } }
} };
t.state.currentView = 'main';
t.state.quickComparison = {
  selectedKeys: ['2026-09-11::main::000636'], selectedItems: {
    '2026-09-11::main::000636': item
  }, message: '', max: 3
};
const target = { innerHTML: '', querySelectorAll() { return []; } };
const html = t.render(target);
if (!html.includes('data-quick-detail="000636"')
    || !html.includes('查看当前图表'))
  throw new Error('selected comparison did not expose a current-detail action');
''')

    def test_changes_panel_only_offers_current_chart_for_current_members(self):
        _assert_node_contract(self, "{ render: renderDecisionChangesPanel, state: state }", r'''
const t = globalThis.__auxTest;
const current = { id: 'id-000636', code: '000636', name: '风华高科',
  candidate: { code: '000636', name: '风华高科' } };
window.CHANLUN_BOOTSTRAP = { pageDate: '2026-09-11', decisionWorkbench: {
  schema_version: 'decision-workbench-v1', report_date: '2026-09-11', phase: 'formal',
  snapshot_id: 'current-snapshot', version: 'v1', items: [current],
  changes: { status: 'available', previous_report_date: '2026-09-10',
    added: ['000636'], removed: ['600644'], changed: [] }
} };
        t.state.data = { date: '2026-09-11', selection_input_health: {
          schema_version: 2, status: 'verified',
          by_view: { main: { status: 'verified', formal_actions_allowed: true } },
          by_strategy: { daily_fusion: { status: 'verified', formal_actions_allowed: true } }
        } };
const target = { innerHTML: '', querySelectorAll() { return []; } };
const html = t.render(target);
if (!html.includes('data-change-current="000636"') || !html.includes('查看当前图表'))
  throw new Error('current member had no current-chart action');
if (html.includes('data-change-current="600644"'))
  throw new Error('removed-only member was offered a fabricated current chart');
''')

    def test_unverified_legacy_reference_keeps_its_purpose_in_history_source(self):
        _assert_node_contract(self, "{ source: renderDecisionHistorySource }", r'''
const t = globalThis.__auxTest;
const html = t.source({ source: '旧来源', record: {
  code: '600184', reference_price: 19.8,
  reference_price_purpose: 'raw_reference',
  reference_price_purpose_status: 'unverified',
  role: 'research', action: '仅观察', report_date: '2026-09-10',
  workbench_item: { strategy_results: [{ strategy_id: 'main', role: 'formal',
    formal_action: '可上车', contract: { reference_price: 10, invalidation_price: 9,
      price_basis: 'qfq', intended_horizon: 'T+3' }, evidence: {} }] }
} }, null);
        if (!html.includes('参考价 10') || !html.includes('19.80'))
  throw new Error('formal contract or legacy raw reference value was dropped');
if (!/用途未核验|原始记录参考/.test(html))
  throw new Error('legacy reference purpose was presented as an ordinary formal price');
''')

    def test_quick_comparison_keeps_formal_contract_and_unverified_raw_reference(self):
        _assert_node_contract(self, "{ dimension: quickComparisonDimensionValues, state: state }", r'''
const t = globalThis.__auxTest;
const item = { code: '600184', name: '复合来源股', reference_price: 19.8,
  reference_price_purpose: 'raw_reference', reference_price_purpose_status: 'unverified',
  strategy_results: [{ strategy_id: 'main', role: 'formal', formal_action: '可上车',
    contract: { reference_price: 10, invalidation_price: 9, intended_horizon: 'T+3', price_basis: 'qfq' },
    evidence: { summary: { status: 'available' } } }] };
const before = JSON.stringify(item);
const prices = t.dimension(item)['关键价位'];
        if (!prices.includes('参考价 10') || !prices.includes('19.80'))
  throw new Error('comparison replaced one source price with another');
if (!/用途未核验|原始记录参考/.test(prices))
  throw new Error('comparison hid the raw reference purpose status');
if (JSON.stringify(item) !== before)
  throw new Error('comparison renderer mutated the source record');
''')

    def test_history_source_rows_keep_same_strategy_versions_and_contract_plans(self):
        _assert_node_contract(self, "{ source: renderDecisionHistorySource }", r'''
const t = globalThis.__auxTest;
const strategy = (version, contractId, reference) => ({ strategy_id: 'main',
  strategy_version: version, contract_id: contractId, role: 'formal',
  formal_action: '等回踩', contract: {
    reference_price: reference, invalidation_price: reference - 1,
    price_basis: 'qfq', intended_horizon: 'T+3'
  }, evidence: { summary: { status: 'available' } } });
const html = t.source({ source: '统一来源', record: {
  code: '600184', workbench_item: { strategy_results: [
    strategy('sv1', 'P', 10), strategy('sv1', 'Q', 11), strategy('sv2', 'P', 10)
  ] }
} }, null);
if ((html.match(/class="decision-history-source"/g) || []).length !== 3
    || !html.includes('策略版本 sv1') || !html.includes('策略版本 sv2')
    || !html.includes('合同 P') || !html.includes('合同 Q')
    || !html.includes('参考价 10') || !html.includes('参考价 11'))
  throw new Error('same-strategy versions or distinct contract plans were merged or hidden');
''')

    def test_history_entries_keep_version_conflicts_and_attached_raw_source(self):
        _assert_node_contract(self, "{ entries: decisionHistoryEntries }", r'''
const t = globalThis.__auxTest;
const row = (version, marker) => ({ code: '600184', version,
  strategy_version: version, source_marker: marker, phase: 'formal',
  report_date: '2026-09-10' });
const payload = { workspace: { views: { main: [row('sv1', 'workspace-v1'), row('sv2', 'workspace-v2')] } },
  picks_fusion: [row('sv2', 'raw-attached')] };
const projection = { items: [row('sv2', 'projection')] };
const rows = t.entries(payload, '600184', projection, { version: 'sv2', phase: 'formal', date: '2026-09-10' });
const markers = rows.map((entry) => entry.record.source_marker);
if (!markers.includes('workspace-v1') || !markers.includes('workspace-v2') || !markers.includes('projection')
    || !markers.includes('raw-attached'))
  throw new Error('history source rows were silently replaced by a preferred source/version');
const old = rows.find((entry) => entry.record.source_marker === 'workspace-v1');
if (!old.validation || old.validation.versionStatus !== 'conflict')
  throw new Error('the retained conflicting version lost its validation status');
''')

    def test_same_missing_risk_is_not_rendered_as_comparable_same_fact(self):
        _assert_node_contract(self, "{ dimension: quickComparisonDimensionValues, dimensionHtml: quickComparisonDimensionHtml, state: state }", r'''
const t = globalThis.__auxTest;
const missing = (code) => ({ code, name: code, strategy_results: [{ strategy_id: 'main', role: 'formal',
  evidence: { risk_and_next: { status: 'missing', risk_labels: [],
    next_confirmation: { status: 'missing', items: [] }, cancel_conditions: { status: 'missing', items: [] } } }
}] });
const a = missing('600184');
const b = missing('002600');
const cell = t.dimensionHtml('主要风险', [{ item: a }, { item: b }], 0);
if (cell.includes('is-same'))
  throw new Error('identical missing-risk placeholders were marked as a verified same fact');
if (cell.includes('is-different'))
  throw new Error('identical missing-risk placeholders were marked as a factual difference');
const values = t.dimension(a);
if (!values['主要风险'].includes('未登记') || values['未满足条件'].includes('已满足'))
  throw new Error('missing risk/conditions were presented as satisfied facts');
''')

    def test_filtered_quick_comparison_remove_and_readd_keeps_one_selection(self):
        _assert_node_contract(self, "{ toggle: toggleQuickComparisonSelection, render: renderQuickComparison, state: state, nodes: nodes }", r'''
const t = globalThis.__auxTest;
const item = { code: '000636', name: '风华高科', page_status: 'watch_only' };
const other = { code: '002600', name: '领益智造', page_status: 'watch_only' };
t.state.data = { date: '2026-09-11', selection_input_health: {
  schema_version: 2, status: 'verified',
  by_view: {
    main: { status: 'verified', formal_actions_allowed: true },
    other: { status: 'verified', formal_actions_allowed: true }
  },
  by_strategy: { daily_fusion: { status: 'verified', formal_actions_allowed: true } }
} };
t.state.workspace = { views: { main: [item], other: [other] }, view_meta: {
  main: { role: 'research', action_semantics: 'watch_only', availability: { state: 'available' } },
  other: { role: 'research', action_semantics: 'watch_only', availability: { state: 'available' } }
} };
t.state.currentView = 'main';
t.state.quickComparison = { selectedKeys: [], selectedItems: {}, message: '', max: 3 };
let removeHandler = null;
const removeButton = {
  getAttribute(name) { return (name === 'data-quick-key' || name === 'data-quick-remove') ? this.value : ''; },
  addEventListener(name, handler) { if (name === 'click') removeHandler = handler; }
};
const comparisonTarget = { html: '', querySelectorAll(selector) {
  return selector === '[data-quick-remove]' ? [removeButton] : [];
} };
Object.defineProperty(comparisonTarget, 'innerHTML', {
  get() { return this.html; },
  set(value) {
    this.html = value;
    const match = String(value).match(/data-quick-key="([^"]+)"/);
    removeButton.value = match ? match[1] : '';
  }
});
t.nodes.candidateQuickComparison = comparisonTarget;
if (!t.toggle(item)) throw new Error('initial comparison selection failed');
t.state.currentView = 'other';
t.render(t.nodes.candidateQuickComparison);
const storedKey = '2026-09-11::main::000636';
if (removeButton.value !== storedKey || !removeHandler)
  throw new Error('filtered-out removal did not retain the selected stored key');
removeHandler({ currentTarget: removeButton });
if (t.state.quickComparison.selectedKeys.length !== 0)
  throw new Error('filtered-out selected stock was not removed by its stored key');
t.state.currentView = 'main';
if (!t.toggle('000636')) throw new Error('removed stock could not be re-added in its original view');
if (t.state.quickComparison.selectedKeys.length !== 1)
  throw new Error('remove/re-add created duplicate comparison selections');
''')

    def test_missing_optional_fact_panel_has_no_fabricated_zero_or_risk(self):
        _assert_node_contract(self, "{ facts: renderCandidateFactPanel }", r'''
const html = globalThis.__auxTest.facts({
  code: '900003', name: '缺量样本',
  data_status: { status: 'missing', daily: 'missing' },
  pool_quality: { money20: null, market_cap: null, circulating_market_cap: null }
});
if (!html.includes('量能与参考位数据未提供'))
  throw new Error('missing optional facts had no local empty state');
if (html.includes('0.00') || html.includes('无风险') || html.includes('已满足'))
  throw new Error('missing optional facts were fabricated as zero or satisfied');
''')

    def test_ref_source_does_not_borrow_same_code_from_another_pool(self):
        _assert_node_contract(self, "{ find: findRawCandidate, state: state }", r'''
const t = globalThis.__auxTest;
const primary = { code: '600184', source: 'pool-a', price_basis: 'qfq',
  data_status: { latest_date: '2026-09-11' }, dates: [], opens: [], highs: [], lows: [], closes: [] };
const borrowed = { code: '600184', source: 'pool-b', price_basis: 'hfq',
  data_status: { latest_date: '2026-09-11' }, dates: ['2026-09-10', '2026-09-11'],
  opens: [1, 2], highs: [2, 3], lows: [0.5, 1], closes: [1.5, 2.5] };
t.state.data = { date: '2026-09-11', startup_watchlist: [primary], picks_fusion: [borrowed] };
t.state.rawPoolCandidates = null;
const direct = t.find({ pool: 'startup_watchlist', code: '600184' });
if (direct !== primary || direct.dates.length)
  throw new Error('source ref borrowed OHLC from another pool');
const unknownPool = t.find({ pool: 'highlights', code: '600184' });
if (unknownPool !== null)
  throw new Error('unknown source ref fell back to the first same-code raw record');
''')

    def test_unverified_raw_reference_stays_text_only_and_off_chart(self):
        _assert_node_contract(self, "{ calc: getCandidateReferencePriceForCalculation, price: buildPriceSection, chart: renderChart, state: state }", r'''
const t = globalThis.__auxTest;
const item = { code: '600101', reference_price: 10, current_price: 11,
  data_status: { daily: 'verified', latest_date: '2026-08-14', is_final: true, stale: false },
  contract: { reference_price: 10, purpose: 'raw_reference', purpose_status: 'unverified', price_basis: 'unknown' } };
const raw = { code: '600101', data_status: item.data_status,
  dates: ['2026-08-13', '2026-08-14'], opens: [10, 10.5], highs: [10.5, 11],
  lows: [9.5, 10], closes: [10, 11],
  chart_annotations: { markLines: [{ name: '参考价', yAxis: 10 }], markPoints: [], labels: [] } };
if (t.calc(item) !== null) throw new Error('unverified raw reference entered calculation');
const price = t.price(item, raw);
if (!price.includes('10.00') || !/用途未核验|原始记录参考/.test(price))
  throw new Error('unverified raw reference was not retained with its purpose');
let chartOption = null;
window.echarts = { init(node) { return { getDom() { return node; }, setOption(value) { chartOption = value; }, getOption() { return chartOption || {}; }, dispose() {}, resize() {} }; } };
t.state.data = { date: '2026-08-14' };
t.state.chartMount = { innerHTML: '' }; t.state.chartAnnotationLane = null; t.state.chartLayerSwitcher = null;
t.chart(raw, item);
const lines = ((chartOption && chartOption.series) || []).flatMap((series) => Array.isArray(series.markLine && series.markLine.data) ? series.markLine.data : []);
if (lines.some((line) => String(line.label && line.label.formatter || '').includes('10.00')))
  throw new Error('unverified raw reference was drawn as an active chart line');
''')

    def test_reference_calculation_uses_the_consumed_contract_purpose(self):
        _assert_node_contract(self, "{ calc: getCandidateReferencePriceForCalculation, chart: renderChart, state: state }", r'''
const t = globalThis.__auxTest;
const explicitlyUnverified = {
  reference_price: 10,
  reference_price_purpose_status: 'verified',
  contract: { reference_price: 10, purpose_status: 'unverified', price_basis: 'qfq' }
};
if (t.calc(explicitlyUnverified) !== null)
  throw new Error('top-level verified status upgraded an explicitly unverified contract');
['', 'unknown', 'missing'].forEach((status) => {
  const incompletePurpose = { contract: { reference_price: 10, purpose_status: status, price_basis: 'qfq' } };
  if (t.calc(incompletePurpose) !== null)
    throw new Error('incomplete purpose status entered calculation: ' + status);
});
const currentContract = {
  formal_decision_contract: { reference_price: 12, purpose_status: 'verified', price_basis: 'qfq' },
  strategy_results: [{ contract: { reference_price: 99, purpose_status: 'unverified', price_basis: 'qfq' } }]
};
if (t.calc(currentContract) !== 12)
  throw new Error('an unrelated strategy contract supplied or blocked the current formal reference');
const missingContractReference = {
  reference_price: 19.8,
  reference_price_purpose_status: 'unverified',
  contract: { purpose_status: 'verified', price_basis: 'qfq' }
};
if (t.calc(missingContractReference) !== null)
  throw new Error('formal contract purpose upgraded a raw price when the contract had no value');
let option = null;
window.echarts = { init(node) { return { getDom() { return node; }, setOption(value) { option = value; }, getOption() { return option || {}; }, dispose() {}, resize() {} }; } };
t.state.data = { date: '2026-08-14' };
t.state.chartMount = { innerHTML: '' }; t.state.chartAnnotationLane = null; t.state.chartLayerSwitcher = null;
t.chart({ code: '600109', dates: ['2026-08-13', '2026-08-14'],
  opens: [19, 19.5], highs: [19.5, 20], lows: [18.5, 19], closes: [19, 19.8],
  chart_annotations: { markLines: [{ name: '参考价', yAxis: 19.8 }], markPoints: [], labels: [] } }, missingContractReference);
const lines = ((option && option.series) || []).flatMap((series) => Array.isArray(series.markLine && series.markLine.data) ? series.markLine.data : []);
if (lines.some((line) => String(line.label && line.label.formatter || '').includes('19.80')))
  throw new Error('raw price returned through a missing formal contract and was drawn');
''')

    def test_unverified_raw_reference_cannot_become_active_beside_verified_contract(self):
        _assert_node_contract(self, "{ facts: renderCandidateFactPanel, price: buildPriceSection, chart: renderChart, state: state }", r'''
const t = globalThis.__auxTest;
const item = { code: '600108', reference_price: 19.8, current_price: 21,
  data_status: { daily: 'verified', latest_date: '2026-08-14', is_final: true, stale: false },
  formal_decision_contract: { reference_price: 20, purpose_status: 'verified', price_basis: 'qfq' } };
 t.state.data = { date: '2026-08-14' };
const facts = t.facts(item);
if (!facts.includes('19.80') || !facts.includes('用途未核验'))
  throw new Error('raw reference was not retained with its own unverified purpose');
if (facts.includes('距结构参考'))
  throw new Error('raw reference received an active distance calculation from another contract');
const price = t.price(item, {});
if (!price.includes('20.00') || !price.includes('原始记录参考 19.80（用途未核验）'))
  throw new Error('formal and raw references were not kept distinct in the price detail');
if (price.includes('结构参考价（用途未核验'))
  throw new Error('verified formal contract was downgraded by the raw reference status');
let option = null;
window.echarts = { init(node) { return { getDom() { return node; }, setOption(value) { option = value; }, getOption() { return option || {}; }, dispose() {}, resize() {} }; } };
t.state.chartMount = { innerHTML: '' }; t.state.chartAnnotationLane = null; t.state.chartLayerSwitcher = null;
const raw = { code: '600108', dates: ['2026-08-13', '2026-08-14'],
  opens: [20, 20.5], highs: [20.5, 21], lows: [19.5, 20], closes: [20, 21],
  reference_buy_points: [{ reference_price: 19.8, purpose_status: 'verified' }],
  chart_annotations: { markLines: [{ name: '参考价', yAxis: 19.8 }], markPoints: [], labels: [] } };
t.chart(raw, item);
const lines = ((option && option.series) || []).flatMap((series) => Array.isArray(series.markLine && series.markLine.data) ? series.markLine.data : []);
if (lines.some((line) => String(line.label && line.label.formatter || '').includes('19.80')))
  throw new Error('unverified raw reference was reintroduced by chart annotation fallback');
if (!lines.some((line) => String(line.label && line.label.formatter || '').includes('20.00')))
  throw new Error('verified formal contract reference line disappeared');
''')

    def test_nonformal_source_keeps_unverified_contract_reference_as_text(self):
        _assert_node_contract(self, "{ detail: buildMergedCandidateDetail, state: state }", r'''
const t = globalThis.__auxTest;
const item = { code: '600110', name: '观察来源', workbench_item: {
  code: '600110', name: '观察来源', status_label: '仅观察',
  strategy_results: [{ strategy_id: 'observation_watchlist', role: 'watch_only',
    formal_action: '仅观察', contract: { reference_price: 10, purpose_status: 'unverified' }, evidence: {} }]
} };
t.state.data = { date: '2026-08-14' };
const html = t.detail(item, { code: '600110' });
if (!html.includes('原始记录参考价 10') || !html.includes('用途未核验'))
  throw new Error('non-formal source reference was hidden instead of retained with its purpose');
if (html.includes('正式参考价 10.00'))
  throw new Error('watch-only source reference was presented as a formal price');
''')

    def test_no_evidence_incident_detail_keeps_raw_reference_text_and_ohlc_mount(self):
        _assert_node_contract(self, "{ detail: buildMergedCandidateDetail, state: state }", r'''
const t = globalThis.__auxTest;
t.state.data = { date: '2026-08-26' }; t.state.currentView = 'main';
const item = { code: '300697', name: '事故复盘样本', incident_review_only: true,
  reference_price: 15.2, ref: { pool: 'startup_watchlist', code: '300697' } };
const raw = { code: '300697', dates: ['2026-08-25', '2026-08-26'],
  opens: [4, 4.1], highs: [4.2, 4.3], lows: [3.9, 4], closes: [4.1, 4.2] };
const html = t.detail(item, raw);
if (!html.includes('15.20')) throw new Error('no-evidence incident detail dropped the raw reference');
if (!/事故前|仅追溯|用途未核验/.test(html))
  throw new Error('no-evidence incident raw reference lacked its non-executable purpose');
if (!html.includes('id="chartCanvas"')) throw new Error('no-evidence incident detail lost the OHLC chart mount');
''')


if __name__ == '__main__':
    unittest.main()
