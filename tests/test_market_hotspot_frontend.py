"""Frontend contracts for the read-only daily market-hotspot map."""

import json
import pathlib
import subprocess
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
CSS = (ROOT / "chanlun/report_assets/report-v2.css").read_text(encoding="utf-8")


def _assert_node_contract(testcase, exposure, body):
    script = r"""
const fs = require('fs');
const vm = require('vm');
global.window = { location: { pathname: '', search: '' } };
global.document = {
  readyState: 'loading',
  addEventListener: function () {},
  getElementById: function () { return null; }
};
let source = fs.readFileSync('chanlun/report_assets/report-v2.js', 'utf8');
const marker = '\n})();';
const at = source.lastIndexOf(marker);
if (at < 0) throw new Error('IIFE marker missing');
source = source.slice(0, at)
  + '\n globalThis.__hotspotTest = __EXPOSURE__;'
  + source.slice(at);
vm.runInThisContext(source, { filename: 'report-v2.js' });
function assert(value, message) { if (!value) throw new Error(message); }
__BODY__
""".replace("__EXPOSURE__", exposure).replace("__BODY__", body)
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=15,
    )
    testcase.assertEqual(completed.returncode, 0, completed.stderr)


VALID_PROJECTION = r"""
function projection(rows) {
  return {
    schema_version: 'decision-workbench-v1',
    report_date: '2026-09-16',
    phase: 'formal',
    snapshot_id: 'formal:2026-09-16:frozen',
    payload_hash: 'a'.repeat(64),
    health: {
      status: 'verified', formal_actions_allowed: true,
      blocking_reasons: [], fact_blocking_reasons: []
    },
    items: rows || [],
    featured_ids: []
  };
}
function install(rows) {
  window.CHANLUN_BOOTSTRAP = {
    pageDate: '2026-09-16',
    decisionWorkbench: projection(rows)
  };
}
"""


class TestMarketHotspotFrontend(unittest.TestCase):
    def test_h01_grouping_dedupes_within_theme_and_counts_unique_across_themes(self):
        _assert_node_contract(
            self,
            "({ build: buildMarketHotspotModel, filter: filterMarketHotspotItems })",
            VALID_PROJECTION
            + r"""
install([]);
const data = {
  date: '2026-09-16',
  limit_up_snapshot: {
    status: 'verified_complete', date: '2026-09-16',
    as_of: '2026-09-16T15:20:48+08:00', source: 'unit-test',
    items: [
      { code: '600001', name: '甲公司', sector: '电子', change_pct: 10 },
      { code: '600002', name: '乙公司', sector: '通信', change_pct: 0 },
      { code: '600003', name: '丙公司', sector: '机械', change_pct: -2 },
      { name: '仅名称对象', sector: '待分类', change_pct: null }
    ],
    theme_groups: [
      { name: '主题甲', codes: ['600001', '600001', '600002'] },
      { name: '主题乙', codes: ['600002', '600003'] }
    ]
  }
};
const frozen = JSON.stringify(data);
const model = globalThis.__hotspotTest.build(data);
assert(model.totalSecurityCount === 3, 'unique determined-security total is wrong');
assert(model.totalAppearanceCount === 4, 'cross-theme appearances were not kept separate');
assert(model.groups.length === 3, 'unresolved-name fallback group was lost');
assert(model.groups[0].items.map(function (item) { return item.code; }).join(',') === '600001,600002',
  'same-theme duplicate or trusted source order changed');
assert(model.groups[1].items.map(function (item) { return item.code; }).join(',') === '600002,600003',
  'cross-theme membership was removed');
assert(model.items.find(function (item) { return item.name === '仅名称对象'; }).isDeterminedSecurity === false,
  'name-only object was promoted to a determined security');
const filtered = globalThis.__hotspotTest.filter(model, {
  query: '乙公司', theme: '', onlySystem: false
});
assert(filtered.items.length === 1 && filtered.items[0].code === '600002',
  'search did not operate on the full unique collection');
assert(filtered.groups.length === 2
  && filtered.groups.every(function (group) { return group.items.length === 1; }),
  'map groups and list collection diverged after filtering');
assert(JSON.stringify(data) === frozen, 'hotspot model mutated its source input');
""",
        )

    def test_h02_date_partial_and_quote_tones_fail_closed_without_zero_fill(self):
        _assert_node_contract(
            self,
            "({ build: buildMarketHotspotModel })",
            VALID_PROJECTION
            + r"""
install([]);
const partial = globalThis.__hotspotTest.build({
  date: '2026-09-16',
  limit_up_snapshot: {
    status: 'partial', date: '2026-09-16', as_of: '2026-09-16T14:30:00+08:00',
    source: 'partial-source', items: [
      { code: '600001', name: '正值', change_pct: 1.2, price: 10 },
      { code: '600002', name: '负值', change_pct: -0.5, price: 9 },
      { code: '600003', name: '平值', change_pct: 0, price: 8 },
      { code: '600004', name: '未知', change_pct: null, price: null }
    ], theme_groups: []
  }
});
assert(partial.status === 'partial' && partial.items.length === 4,
  'valid partial sample was discarded');
assert(partial.items.map(function (item) { return item.quoteTone; }).join(',')
  === 'up,down,flat,missing', 'positive/negative/flat/missing quote tones collapsed');
assert(partial.items[3].changePct === null && partial.items[3].price === null,
  'unknown quote was filled with zero');
const stale = globalThis.__hotspotTest.build({
  date: '2026-09-16',
  sector_heat: { status: 'verified_complete', items: [{
    sector_code: 'BK1', sector_name: '仍可见板块', change_pct: 1, rank: 1,
    up_count: 2, total_count: 3, limit_up_count: 1, status: 'verified_complete'
  }] },
  limit_up_snapshot: {
    status: 'verified_complete', date: '2026-09-15',
    items: [{ code: '600001', name: '昨日对象', change_pct: 10 }]
  }
});
assert(stale.items.length === 0 && stale.status === 'date_mismatch',
  'another-day quote was presented as today');
assert(stale.sectorOverview.items.length === 1
  && stale.sectorOverview.items[0].name === '仍可见板块',
  'valid same-day sector summary was erased by a bad hotspot date');
const staleAsOf = globalThis.__hotspotTest.build({
  date: '2026-09-16', limit_up_snapshot: {
    status: 'verified_complete', as_of: '2026-09-15T15:20:48+08:00',
    items: [{ code: '600009', name: '只有异日时间', change_pct: 10 }]
  }
});
assert(staleAsOf.items.length === 0 && staleAsOf.status === 'date_mismatch',
  'another-day as_of bypassed a missing snapshot date');
const undated = globalThis.__hotspotTest.build({
  date: '2026-09-16', limit_up_snapshot: {
    status: 'verified_complete', items: [
      { code: '600010', name: '无日期行情', change_pct: 10 }
    ]
  }
});
assert(undated.items.length === 0 && undated.status === 'date_unknown',
  'undated quote was presented as current-day market fact');
""",
        )

    def test_row_level_quote_dates_isolate_only_conflicting_market_facts(self):
        _assert_node_contract(
            self,
            "({ build: buildMarketHotspotModel, readonly: renderMarketHotspotReadOnlyDetail })",
            VALID_PROJECTION
            + r"""
install([]);
const model = globalThis.__hotspotTest.build({
  date: '2026-09-16', limit_up_snapshot: {
    status: 'verified_complete', date: '2026-09-16',
    as_of: '2026-09-16T15:20:48+08:00', source: 'frozen-source',
    raw_total: 4, items: [
      { code: '600001', name: '旧行情仍保留名称', sector: '电子', date: '2026-09-15',
        price: 10, change_pct: 10, lianban: 2, first_time: '09:31', fund: 12, zhaban: 1 },
      { code: '600002', name: '独立日期正常', report_date: '2026-09-16',
        quote_date: '2026-09-16', as_of: '2026-09-16T14:00:00+08:00',
        price: 11, change_pct: -1, lianban: 1, first_time: '10:00', fund: 13, zhaban: 0 },
      { code: '600003', name: '继承明确父快照', price: 12, change_pct: 0, lianban: 1 },
      { code: '600004', name: '行内日期互相冲突', date: '2026-09-16',
        quote_date: '2026-09-15', price: 13, change_pct: 5, lianban: 3 }
    ], theme_groups: []
  }
});
const byCode = Object.fromEntries(model.items.map(function (item) { return [item.code, item]; }));
['600001', '600004'].forEach(function (code) {
  const item = byCode[code];
  assert(item && item.name, code + ' conflicting record was erased instead of locally isolated');
  assert(item.price === null && item.changePct === null && item.lianban === null
    && item.firstTime === '' && item.fund === null && item.zhaban === null,
    code + ' stale quote/limit facts survived a row-level date conflict');
  assert(item.quoteStatus === 'date_conflict', code + ' date-conflict status is not traceable');
});
assert(byCode['600001'].sector === '电子', 'independently readable sector/name fields were erased');
assert(byCode['600002'].price === 11 && byCode['600002'].changePct === -1
  && byCode['600002'].quoteStatus === 'available'
  && byCode['600002'].quoteDate === '2026-09-16T14:00:00+08:00',
  'independently dated current quote was lost');
assert(byCode['600003'].price === 12 && byCode['600003'].changePct === 0
  && byCode['600003'].quoteDate === '2026-09-16T15:20:48+08:00',
  'row without its own date did not inherit the explicit verified parent snapshot');
const html = globalThis.__hotspotTest.readonly(byCode['600001']);
assert(html.includes('报告日 2026-09-16') && html.includes('行情日期冲突，报价已隔离')
  && !html.includes('¥ 10.00'), 'read-only UI mislabeled an old quote as current');
""",
        )

    def test_snapshot_date_and_as_of_conflict_isolates_the_snapshot(self):
        _assert_node_contract(
            self,
            "({ build: buildMarketHotspotModel })",
            VALID_PROJECTION
            + r"""
install([]);
const model = globalThis.__hotspotTest.build({
  date: '2026-09-16', limit_up_snapshot: {
    status: 'verified_complete', date: '2026-09-16',
    as_of: '2026-09-15T15:00:00+08:00', raw_total: 1,
    items: [{ code: '600001', name: '父时间冲突', price: 10, change_pct: 10 }]
  }
});
assert(model.status === 'date_mismatch' && model.items.length === 0,
  'parent snapshot date/as_of conflict leaked old quotes');
""",
        )

    def test_raw_quote_identity_conflicts_close_market_fields_but_keep_readable_record(self):
        _assert_node_contract(
            self,
            "({ build: buildMarketHotspotModel, card: renderMarketHotspotCard })",
            VALID_PROJECTION
            + r"""
install([]);
const model = globalThis.__hotspotTest.build({
  date: '2026-09-16',
  events: [{ title: '只属于确定600001的事件', stock_list: ['600001'] }],
  limit_up_snapshot: {
    status: 'verified_complete', date: '2026-09-16',
    as_of: '2026-09-16T15:20:48+08:00', raw_total: 4, items: [
      { code: '600001', instrument_id: 'SZ000001', name: '代码身份冲突', price: 10,
        change_pct: 10, lianban: 2, first_time: '09:30', fund: 1, zhaban: 1 },
      { code: '600002', exchange: 'SZ', name: '交易所代码冲突', price: 11,
        change_pct: 9, lianban: 1 },
      { code: '600003', candidate: { code: '000003' }, name: '候选身份冲突',
        price: 12, change_pct: 8, lianban: 1 },
      { code: '600004', exchange: 'SH', name: '身份一致', price: 13,
        change_pct: 7, lianban: 1 }
    ], theme_groups: []
  }
});
const byCode = Object.fromEntries(model.items.map(function (item) { return [item.code, item]; }));
['600001', '600002', '600003'].forEach(function (code) {
  const item = byCode[code];
  assert(item && item.name && item.identityConflict === true,
    code + ' conflicting record/name was not retained as readable unknown data');
  assert(item.price === null && item.changePct === null && item.lianban === null
    && item.firstTime === '' && item.fund === null && item.zhaban === null
    && item.quoteStatus === 'identity_conflict',
    code + ' ambiguous identity kept definite quote/limit facts');
});
assert(byCode['600004'].identity === 'SH600004' && byCode['600004'].price === 13,
  'consistent explicit exchange/code was rejected');
const conflictHtml = globalThis.__hotspotTest.card(byCode['600001']);
assert(conflictHtml.includes('原记录 600001 · 身份冲突')
  && !conflictHtml.includes('<small>600001</small>'),
  'ambiguous raw code was rendered as a confirmed security identity');
assert(byCode['600001'].events.length === 0,
  'ambiguous identity inherited an event through its conflicting raw code');
""",
        )

    def test_same_named_theme_objects_dedupe_across_objects_and_keep_cross_theme_order(self):
        _assert_node_contract(
            self,
            "({ build: buildMarketHotspotModel })",
            VALID_PROJECTION
            + r"""
install([]);
const model = globalThis.__hotspotTest.build({
  date: '2026-09-16', limit_up_snapshot: {
    status: 'verified_complete', date: '2026-09-16', raw_total: 2,
    items: [
      { code: '600001', name: '甲', price: 10, change_pct: 10 },
      { code: '600002', name: '乙', price: 11, change_pct: 10 }
    ], theme_groups: [
      { name: '同题材', codes: ['600002'] },
      { name: '同题材', codes: ['600001', '600002'] },
      { name: '另一题材', codes: ['600001'] }
    ]
  }
});
assert(model.groups.length === 2, 'same-name theme objects created duplicate groups');
assert(model.groups[0].name === '同题材'
  && model.groups[0].items.map(function (item) { return item.code; }).join(',') === '600002,600001',
  'same-name theme dedupe changed first trusted appearance order');
assert(model.groups[1].items.map(function (item) { return item.code; }).join(',') === '600001',
  'cross-theme appearance was incorrectly removed');
assert(model.totalAppearanceCount === 3 && model.totalSecurityCount === 2,
  'cross-theme appearances and unique-security totals were collapsed');
""",
        )

    def test_h03_h04_strict_membership_reuses_pool_summary_and_quarantines_conflicts(self):
        _assert_node_contract(
            self,
            "({ build: buildMarketHotspotModel, card: renderMarketHotspotCard })",
            VALID_PROJECTION
            + r"""
const rows = [{
  code: '600001', instrument_id: 'SH600001', name: '系统甲',
  report_date: '2026-09-16', phase: 'formal',
  snapshot_id: 'formal:2026-09-16:frozen',
  sources: ['main', 'highlights'],
  strategy_results: [{ strategy_id: 'main', role: 'formal',
    action_semantics: 'formal', formal_action: '可上车',
    candidate: { code: '600001', ref: { pool: 'picks_fusion', code: '600001' } } }]
}, {
  code: '600003', instrument_id: 'SZ000003', name: '身份冲突',
  report_date: '2026-09-16', phase: 'formal',
  snapshot_id: 'formal:2026-09-16:frozen', sources: ['confirming']
}, {
  code: '600004', instrument_id: 'SH600004', name: '快照冲突',
  report_date: '2026-09-16', phase: 'formal', snapshot_id: 'other',
  sources: ['confirming']
}];
install(rows);
const data = { date: '2026-09-16', limit_up_snapshot: {
  status: 'verified_complete', date: '2026-09-16', items: [
    { code: '600001', name: '热点甲', change_pct: 10 },
    { code: '600002', name: '系统外', change_pct: 10 },
    { code: '600003', name: '冲突代码', change_pct: 10 },
    { code: '000003', name: '冲突身份另一侧', change_pct: 10 },
    { code: '600004', name: '冲突快照', change_pct: 10 }
  ], theme_groups: []
} };
let model = globalThis.__hotspotTest.build(data);
let byCode = Object.fromEntries(model.items.map(function (item) { return [item.code, item]; }));
assert(byCode['600001'].membership === 'in'
  && byCode['600001'].poolSummary.count === 1
  && byCode['600001'].poolSummary.pools[0].label === '主推策略'
  && byCode['600001'].poolSummary.collections[0].label === '看点榜',
  'same-snapshot match did not reuse the existing pool-summary contract');
const cardHtml = globalThis.__hotspotTest.card(byCode['600001']);
assert(cardHtml.includes('<span class="pool-hit-summary')
  && !cardHtml.includes('<div class="pool-hit-summary'),
  'block source-summary container was nested inside a hotspot button');
assert(byCode['600002'].membership === 'unknown',
  'invalid workbench rows still allowed a negative membership conclusion');
assert(byCode['600003'].membership === 'unknown'
  && byCode['000003'].membership === 'unknown'
  && byCode['600004'].membership === 'unknown',
  'explicit identity/snapshot conflicts were mislabeled as non-members');
assert(model.systemHitCount === 1 && model.systemOutCount === 0
  && model.systemUnknownCount === 4, 'membership totals hid quarantined conflicts');

install([rows[0]]);
let cleanModel = globalThis.__hotspotTest.build({
  date: '2026-09-16', limit_up_snapshot: {
    status: 'verified_complete', date: '2026-09-16', raw_total: 2,
    items: [
      { code: '600001', name: '热点甲', change_pct: 10 },
      { code: '600002', name: '系统外', change_pct: 10 }
    ], theme_groups: []
  }
});
let cleanByCode = Object.fromEntries(cleanModel.items.map(function (item) { return [item.code, item]; }));
assert(cleanByCode['600001'].membership === 'in' && cleanByCode['600002'].membership === 'out',
  'clean complete same-day list could not prove a true nonmember');

window.CHANLUN_BOOTSTRAP.decisionWorkbench.report_date = '2026-09-15';
model = globalThis.__hotspotTest.build(data);
assert(model.items.every(function (item) { return item.membership === 'unknown'; }),
  'wrong-date workbench was treated as the current system list');
window.CHANLUN_BOOTSTRAP.decisionWorkbench.report_date = '2026-09-16';
window.CHANLUN_BOOTSTRAP.decisionWorkbench.phase = 'research';
model = globalThis.__hotspotTest.build(data);
assert(model.items.every(function (item) { return item.membership === 'unknown'; }),
  'wrong-phase workbench was treated as formal membership');
window.CHANLUN_BOOTSTRAP.decisionWorkbench.phase = 'formal';
delete window.CHANLUN_BOOTSTRAP.decisionWorkbench.snapshot_id;
model = globalThis.__hotspotTest.build(data);
assert(model.items.every(function (item) { return item.membership === 'unknown'; }),
  'snapshot-less workbench produced definite membership');
window.CHANLUN_BOOTSTRAP.decisionWorkbench.snapshot_id = 'formal:2026-09-16:frozen';
window.CHANLUN_BOOTSTRAP.decisionWorkbench.health.blocked_strategies = ['luojie_pool'];
model = globalThis.__hotspotTest.build(data);
byCode = Object.fromEntries(model.items.map(function (item) { return [item.code, item]; }));
assert(byCode['600001'].membership === 'in',
  'known unaffected present member was dropped with incomplete negative coverage');
assert(byCode['600002'].membership === 'unknown',
  'absent member was labeled out while source coverage was incomplete');
window.CHANLUN_BOOTSTRAP.decisionWorkbench.health.blocked_strategies = [];
window.CHANLUN_BOOTSTRAP.decisionWorkbench.health.formal_actions_allowed = false;
model = globalThis.__hotspotTest.build(data);
byCode = Object.fromEntries(model.items.map(function (item) { return [item.code, item]; }));
assert(byCode['600001'].membership === 'in' && byCode['600002'].membership === 'out',
  'execution permission was conflated with membership completeness');
window.CHANLUN_BOOTSTRAP.decisionWorkbench.health.blocked_strategies = ['main'];
model = globalThis.__hotspotTest.build(data);
byCode = Object.fromEntries(model.items.map(function (item) { return [item.code, item]; }));
assert(byCode['600001'].membership === 'unknown',
  'record whose own source was explicitly blocked remained a known hit');
""",
        )

    def test_h05_map_list_filters_share_full_collection_and_render_explicit_limit(self):
        _assert_node_contract(
            self,
            "({ build: buildMarketHotspotModel, render: renderMarketHotspotSection })",
            VALID_PROJECTION
            + r"""
install([]);
const items = Array.from({ length: 35 }, function (_, index) {
  return { code: String(600000 + index), name: '样本' + index,
    sector: index < 32 ? '主题甲' : '主题乙', change_pct: index % 3 - 1 };
});
const data = { date: '2026-09-16', limit_up_snapshot: {
  status: 'verified_complete', date: '2026-09-16', raw_total: 35,
  parsed_count: 35, as_of: '2026-09-16T15:20:48+08:00', source: 'frozen',
  items: items, theme_groups: [
    { name: '主题甲', codes: items.slice(0, 32).map(function (item) { return item.code; }) },
    { name: '主题乙', codes: items.slice(32).map(function (item) { return item.code; }) }
  ]
} };
const model = globalThis.__hotspotTest.build(data);
const mapHtml = globalThis.__hotspotTest.render(model, {
  mode: 'map', query: '样本34', theme: '', onlySystem: false, visibleLimit: 30
});
const listHtml = globalThis.__hotspotTest.render(model, {
  mode: 'list', query: '样本34', theme: '', onlySystem: false, visibleLimit: 30
});
assert(mapHtml.includes('样本34') && listHtml.includes('样本34'),
  'search was applied after the 30-item display limit');
assert(mapHtml.includes('显示 1 / 1') && listHtml.includes('显示 1 / 1'),
  'map/list result counts diverged');
const initialHtml = globalThis.__hotspotTest.render(model, {
  mode: 'map', query: '', theme: '', onlySystem: false, visibleLimit: 30
});
assert(initialHtml.includes('显示 30 / 35') && initialHtml.includes('加载更多'),
  'default display limit masqueraded as the complete market sample');
assert(initialHtml.includes('搜索名称或代码') && initialHtml.includes('清空')
  && initialHtml.includes('只看系统命中') && initialHtml.includes('详细清单'),
  'required reading controls are missing');
""",
        )

    def test_partial_workbench_keeps_unaffected_confirming_hit_but_not_absent_negative(self):
        _assert_node_contract(
            self,
            "({ build: buildMarketHotspotModel })",
            VALID_PROJECTION
            + r"""
const current = projection([{
  code: '600001', instrument_id: 'SH600001', name: '已知等确认成员',
  report_date: '2026-09-16', phase: 'formal',
  snapshot_id: 'formal:2026-09-16:frozen', sources: ['confirming'],
  source_refs: [{ view: 'confirming', ref: {
    pool: 'startup_watchlist', code: '600001'
  }}]
}]);
current.health.formal_actions_allowed = false;
current.health.blocked_strategies = ['h4_t3'];
window.CHANLUN_BOOTSTRAP = { pageDate: '2026-09-16', decisionWorkbench: current };
const model = globalThis.__hotspotTest.build({
  date: '2026-09-16', limit_up_snapshot: {
    status: 'verified_complete', date: '2026-09-16', raw_total: 2,
    items: [
      { code: '600001', name: '已知等确认成员', price: 10, change_pct: 10 },
      { code: '600002', name: '清单外待确认', price: 11, change_pct: 10 }
    ], theme_groups: []
  }
});
const byCode = Object.fromEntries(model.items.map(function (item) { return [item.code, item]; }));
assert(byCode['600001'].membership === 'in'
  && byCode['600001'].poolSummary.pools.map(function (pool) { return pool.label; }).join(',') === '等确认',
  'known confirming member was erased by unrelated H4 coverage or execution permission');
assert(byCode['600002'].membership === 'unknown',
  'absent item was labeled out while H4 coverage was incomplete');
""",
        )

    def test_market_and_row_scope_mismatch_only_close_membership_not_quotes(self):
        _assert_node_contract(
            self,
            "({ build: buildMarketHotspotModel })",
            VALID_PROJECTION
            + r"""
install([{
  code: '600001', instrument_id: 'SH600001', name: '系统成员', sources: ['confirming']
}]);
function hotspot(extraReport, extraSnapshot, rows) {
  return Object.assign({ date: '2026-09-16' }, extraReport || {}, {
    limit_up_snapshot: Object.assign({
      status: 'verified_complete', date: '2026-09-16', raw_total: rows.length,
      items: rows, theme_groups: []
    }, extraSnapshot || {})
  });
}
let model = globalThis.__hotspotTest.build(hotspot(
  { phase: 'preclose', snapshot_id: 'preclose:2026-09-16:other' },
  { phase: 'preclose', snapshot_id: 'preclose:2026-09-16:other' },
  [{ code: '600001', name: '报告范围冲突', price: 10, change_pct: 10 }]
));
assert(model.items[0].membership === 'unknown',
  'explicit preclose market report was matched to formal workbench');
assert(model.items[0].price === 10 && model.items[0].changePct === 10,
  'association scope mismatch erased independent quote facts');
model = globalThis.__hotspotTest.build(hotspot({}, {}, [
  { code: '600001', name: '行范围冲突', phase: 'preclose',
    snapshot_id: 'preclose:2026-09-16:row', price: 11, change_pct: 9 },
  { code: '600002', name: '无可选范围字段', price: 12, change_pct: 8 }
]));
const byCode = Object.fromEntries(model.items.map(function (item) { return [item.code, item]; }));
assert(byCode['600001'].membership === 'unknown' && byCode['600001'].price === 11,
  'row-level scope conflict did not isolate association only');
assert(byCode['600002'].membership === 'out' && byCode['600002'].price === 12,
  'row without optional scope fields was globally downgraded');
""",
        )

    def test_workbench_declared_total_and_invalid_identities_only_gate_negative_proof(self):
        _assert_node_contract(
            self,
            "({ build: buildMarketHotspotModel })",
            VALID_PROJECTION
            + r"""
function installRows(rows, totalItems, healthStatus) {
  const current = projection(rows);
  current.health.status = healthStatus || 'verified';
  if (totalItems !== undefined) current.summary = { total_items: totalItems };
  window.CHANLUN_BOOTSTRAP = { pageDate: '2026-09-16', decisionWorkbench: current };
}
function market() {
  return { date: '2026-09-16', limit_up_snapshot: {
    status: 'verified_complete', date: '2026-09-16', raw_total: 2,
    items: [
      { code: '600001', name: '存在成员', price: 10, change_pct: 10 },
      { code: '600002', name: '缺席对象', price: 11, change_pct: 9 }
    ], theme_groups: []
  } };
}
const present = { code: '600001', instrument_id: 'SH600001',
  name: '存在成员', sources: ['confirming'] };
installRows([present], 1);
let model = globalThis.__hotspotTest.build(market());
let byCode = Object.fromEntries(model.items.map(function (item) { return [item.code, item]; }));
assert(byCode['600001'].membership === 'in' && byCode['600002'].membership === 'out',
  'correct declared total did not allow positive and negative membership proof');
installRows([present], 2);
model = globalThis.__hotspotTest.build(market());
byCode = Object.fromEntries(model.items.map(function (item) { return [item.code, item]; }));
assert(byCode['600001'].membership === 'in' && byCode['600002'].membership === 'unknown',
  'truncated list erased a present member or proved an absent member');
installRows([present]);
model = globalThis.__hotspotTest.build(market());
byCode = Object.fromEntries(model.items.map(function (item) { return [item.code, item]; }));
assert(byCode['600001'].membership === 'in' && byCode['600002'].membership === 'out',
  'missing optional summary broke legacy complete input compatibility');
installRows([present], 1, 'partial');
model = globalThis.__hotspotTest.build(market());
byCode = Object.fromEntries(model.items.map(function (item) { return [item.code, item]; }));
assert(byCode['600001'].membership === 'in' && byCode['600002'].membership === 'unknown',
  'partial list did not preserve positive-only proof');
installRows([present, Object.assign({}, present)], 2);
model = globalThis.__hotspotTest.build(market());
byCode = Object.fromEntries(model.items.map(function (item) { return [item.code, item]; }));
assert(byCode['600001'].membership === 'unknown' && byCode['600002'].membership === 'unknown',
  'duplicate workbench identity still allowed negative proof');
installRows([present, { name: '无身份坏行' }], 2);
model = globalThis.__hotspotTest.build(market());
byCode = Object.fromEntries(model.items.map(function (item) { return [item.code, item]; }));
assert(byCode['600001'].membership === 'in' && byCode['600002'].membership === 'unknown',
  'invalid workbench entry erased valid positive or still allowed negative proof');
""",
        )

    def test_h04_h05_detail_routes_system_hits_and_keeps_nonmembers_read_only(self):
        _assert_node_contract(
            self,
            "({ build: buildMarketHotspotModel, open: openMarketHotspotDetail, readonly: renderMarketHotspotReadOnlyDetail, state: state })",
            VALID_PROJECTION
            + r"""
install([{ code: '600001', instrument_id: 'SH600001', name: '系统甲',
  report_date: '2026-09-16', phase: 'formal',
  snapshot_id: 'formal:2026-09-16:frozen', sources: ['confirming'],
  candidate: { code: '600001', name: '系统甲', ref: { pool: 'startup_watchlist', code: '600001' } }
}]);
const model = globalThis.__hotspotTest.build({
  date: '2026-09-16', limit_up_snapshot: {
    status: 'verified_complete', date: '2026-09-16', source: 'safe-source',
    as_of: '2026-09-16T15:20:48+08:00', items: [
      { code: '600001', name: '系统甲', price: 10, change_pct: 10 },
      { code: '600002', name: '<img src=x onerror=alert(1)>', price: 20, change_pct: null }
    ], theme_groups: []
  }
});
globalThis.__hotspotTest.state.hotspot = {
  mode: 'list', query: '系统', theme: '测试', onlySystem: true, visibleLimit: 60
};
const before = JSON.stringify(globalThis.__hotspotTest.state.hotspot);
let candidateOpened = '';
let readonlyOpened = '';
const hit = model.items.find(function (item) { return item.code === '600001'; });
const miss = model.items.find(function (item) { return item.code === '600002'; });
let target = globalThis.__hotspotTest.open(hit, {
  openCandidate: function (code) { candidateOpened = code; return true; },
  openReadonly: function (item) { readonlyOpened = item.code; return true; }
});
assert(target === 'candidate' && candidateOpened === '600001' && readonlyOpened === '',
  'same-day system hit did not use the existing candidate detail path');
target = globalThis.__hotspotTest.open(miss, {
  openCandidate: function (code) { candidateOpened = code; return true; },
  openReadonly: function (item) { readonlyOpened = item.code; return true; }
});
assert(target === 'readonly' && readonlyOpened === '600002',
  'nonmember was injected into the system candidate detail path');
assert(JSON.stringify(globalThis.__hotspotTest.state.hotspot) === before,
  'detail navigation discarded hotspot mode/filter state');
const html = globalThis.__hotspotTest.readonly(miss);
assert(html.includes('本期系统清单未入选') && html.includes('没有可靠 K 线')
  && html.includes('原因未补') && html.includes('2026-09-16'),
  'read-only detail omitted its membership/date/chart/reason boundary');
assert(!html.includes('<img') && html.includes('&lt;img'),
  'untrusted hotspot text was not escaped');
assert(!html.includes('chart-panel') && !html.includes('data-chart'),
  'read-only nonmember detail created or borrowed a chart');
""",
        )

    def test_h03_explicit_events_only_and_links_are_http_safe(self):
        _assert_node_contract(
            self,
            "({ build: buildMarketHotspotModel, readonly: renderMarketHotspotReadOnlyDetail })",
            VALID_PROJECTION
            + r"""
install([]);
const data = {
  date: '2026-09-16',
  events: [{ title: '不能广播到全题材', stock_list: [], url: 'https://example.com/all' }],
  decision_brief: {
    status: 'ok', evidence_registry: [
      { evidence_ref: 'event:one', kind: 'event', title: '<b>明确关联事件</b>',
        url: 'https://example.com/one' },
      { evidence_ref: 'event:bad', kind: 'event', title: '危险链接',
        url: 'javascript:alert(1)' }
    ],
    theses: [{ theme: '测试题材', llm_summary: '<i>模型归纳</i>',
      evidence_refs: ['event:one', 'event:bad'], stock_links: [
        { code: '600001', name: '甲公司', link_type: 'candidate_intersection' }
      ] }]
  },
  limit_up_snapshot: { status: 'verified_complete', date: '2026-09-16', items: [
    { code: '600001', name: '甲公司', change_pct: 10 },
    { code: '600002', name: '乙公司', change_pct: 10 }
  ], theme_groups: [{ name: '测试题材', codes: ['600001', '600002'] }] }
};
const model = globalThis.__hotspotTest.build(data);
const first = model.items.find(function (item) { return item.code === '600001'; });
const second = model.items.find(function (item) { return item.code === '600002'; });
assert(first.events.length === 2 && first.modelSummaries.length === 1,
  'explicit stock-linked evidence was not preserved');
assert(second.events.length === 0 && second.modelSummaries.length === 0,
  'theme-level news was hard-bound to every stock');
const html = globalThis.__hotspotTest.readonly(first);
assert(html.includes('关联事件，不代表已证实涨停原因') && html.includes('模型归纳'),
  'fact/event/model boundaries are not visible');
assert(html.includes('href="https:&#47;&#47;example.com&#47;one"')
  && !html.includes('href="javascript:'), 'unsafe event URL reached the detail link');
assert(!html.includes('<b>') && !html.includes('<i>'), 'event/model text was not escaped');
""",
        )

    def test_h07_local_failure_degrades_only_hotspot_and_keeps_sector_summary(self):
        _assert_node_contract(
            self,
            "({ build: buildMarketHotspotModel, render: renderMarketHotspotSection })",
            VALID_PROJECTION
            + r"""
install([]);
const data = { date: '2026-09-16', sector_flow: [{ name: '有效板块', flow: 12 }],
  data_quality: { sector_source: 'eastmoney' } };
Object.defineProperty(data, 'limit_up_snapshot', {
  get: function () { throw new Error('/private/path/secret'); }
});
const model = globalThis.__hotspotTest.build(data);
assert(model.status === 'degraded' && model.items.length === 0,
  'hotspot exception did not become a local degraded model');
assert(model.reasonCode === 'hotspot_model_unavailable'
  && model.sectorOverview.items[0].name === '有效板块',
  'fixed degradation state or valid sector fallback is missing');
const html = globalThis.__hotspotTest.render(model, {});
assert(html.includes('热点个股暂不可用') && html.includes('有效板块')
  && !html.includes('/private/path') && !html.includes('secret'),
  'local fallback leaked error detail or erased other valid facts');
""",
        )

    def test_only_verified_empty_is_confirmed_empty_and_unknown_counts_are_not_zero(self):
        _assert_node_contract(
            self,
            "({ build: buildMarketHotspotModel, render: renderMarketHotspotSection })",
            VALID_PROJECTION
            + r"""
install([]);
const declaredCompleteEmpty = globalThis.__hotspotTest.build({
  date: '2026-09-16', limit_up_snapshot: {
    status: 'verified_complete', date: '2026-09-16', raw_total: 3, items: []
  }
});
assert(declaredCompleteEmpty.status === 'unavailable'
  && declaredCompleteEmpty.countsKnown === false,
  'declared complete nonempty upstream with empty items became a confirmed empty pool');
let html = globalThis.__hotspotTest.render(declaredCompleteEmpty, {});
assert(!html.includes('确认空池') && html.includes('暂不可用')
  && html.includes('已取得样本') && !html.includes('<strong>0</strong><small>市场样本'),
  'unknown sample count was rendered as a confirmed zero');
const badItems = globalThis.__hotspotTest.build({
  date: '2026-09-16', limit_up_snapshot: {
    status: 'verified_complete', date: '2026-09-16', raw_total: 2,
    items: { code: '600001' }
  }
});
assert(badItems.status === 'unavailable' && badItems.countsKnown === false,
  'bad items type became a confirmed empty pool');
const verifiedEmpty = globalThis.__hotspotTest.build({
  date: '2026-09-16', limit_up_snapshot: {
    status: 'verified_empty', date: '2026-09-16', raw_total: 0, items: []
  }
});
assert(verifiedEmpty.status === 'empty' && verifiedEmpty.countsKnown === true,
  'verified_empty lost its explicit zero contract');
html = globalThis.__hotspotTest.render(verifiedEmpty, {});
assert(html.includes('确认空池') && html.includes('<strong>0</strong><small>已取得样本'),
  'verified_empty was not rendered as the sole confirmed-zero state');
""",
        )

    def test_real_0916_model_is_89_unique_with_26_hits_and_63_nonmembers(self):
        _assert_node_contract(
            self,
            "({ build: buildMarketHotspotModel })",
            r"""
const report = JSON.parse(fs.readFileSync('docs/data/2026-09-16.json', 'utf8'));
const bootstrapLine = fs.readFileSync('docs/index.html', 'utf8').split('\n').find(function (line) {
  return line.includes('window.CHANLUN_BOOTSTRAP = ');
});
const bootstrap = JSON.parse(bootstrapLine.split('window.CHANLUN_BOOTSTRAP = ')[1].replace(/;\s*$/, ''));
window.CHANLUN_BOOTSTRAP = {
  pageDate: bootstrap.pageDate,
  decisionWorkbench: bootstrap.decisionWorkbench
};
const frozenReport = JSON.stringify(report.limit_up_snapshot);
const frozenWorkbench = JSON.stringify(bootstrap.decisionWorkbench);
const model = globalThis.__hotspotTest.build(report);
assert(model.totalSecurityCount === 89 && model.items.length === 89,
  'real complete market sample was truncated to candidates or a display limit');
assert(model.systemHitCount === 26 && model.systemOutCount === 63
  && model.systemUnknownCount === 0, 'real 89/26/63 relationship changed');
const fixed = {
  '605358': '等确认,罗姐池', '002281': '等确认', '688432': '罗姐池',
  '003026': '等确认', '688478': '等确认', '301486': '等确认', '300656': '等确认'
};
Object.keys(fixed).forEach(function (code) {
  const item = model.items.find(function (row) { return row.code === code; });
  assert(item && item.membership === 'in', code + ' lost its strict system match');
  assert(item.poolSummary.pools.map(function (pool) { return pool.label; }).join(',') === fixed[code],
    code + ' source-pool summary changed or counted a derived collection');
});
assert(JSON.stringify(report.limit_up_snapshot) === frozenReport,
  'real 89-item market input was mutated');
assert(JSON.stringify(bootstrap.decisionWorkbench) === frozenWorkbench,
  'real 80-item system input was mutated');
""",
        )

    def test_h06_css_keeps_mobile_groups_single_column_and_stock_cards_two_columns(self):
        required = (
            ".market-hotspot-section",
            ".hotspot-group-grid",
            ".hotspot-stock-grid",
            ".hotspot-readonly-dialog",
            "@media (max-width: 760px)",
        )
        for token in required:
            self.assertIn(token, CSS)
        mobile = CSS[CSS.rfind("@media (max-width: 760px)") :]
        self.assertIn(".hotspot-group-grid", mobile)
        self.assertIn("grid-template-columns: 1fr", mobile)
        self.assertIn(".hotspot-stock-grid", mobile)
        self.assertIn("grid-template-columns: repeat(2, minmax(0, 1fr))", mobile)
        self.assertIn("overflow-wrap: anywhere", CSS)
        self.assertNotIn(".hotspot-stock-card:hover .hotspot", CSS)

    def test_h08_production_assets_do_not_embed_prototype_fixed_names(self):
        js = (ROOT / "chanlun/report_assets/report-v2.js").read_text(encoding="utf-8")
        for forbidden in ("中际旭创", "新易盛", "原帖名单模式", "30只名称、四组分类"):
            self.assertNotIn(forbidden, js)


if __name__ == "__main__":
    unittest.main()
