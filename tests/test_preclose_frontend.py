"""Browser-contract tests for the isolated 14:45 advisory panel."""

import pathlib
import subprocess
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


def _assert_node_contract(testcase, exposure, body):
    script = r"""
const fs = require('fs');
const vm = require('vm');
global.window = {
  location: { pathname: '' },
  setTimeout: function () { return 1; },
  clearTimeout: function () {}
};
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
  + '\n globalThis.__precloseTest = __EXPOSURE__;'
  + source.slice(at);
vm.runInThisContext(source, { filename: 'report-v2.js' });
function assert(value, message) { if (!value) throw new Error(message); }
async function run() { __BODY__ }
run().catch(function (error) { console.error(error.stack || error); process.exitCode = 1; });
""".replace("__EXPOSURE__", exposure).replace("__BODY__", body)
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
    )
    testcase.assertEqual(completed.returncode, 0, completed.stderr)


class PrecloseFrontendTests(unittest.TestCase):
    def test_archive_report_fallback_uses_path_date_without_bootstrap(self):
        _assert_node_contract(
            self,
            "({ resolve: resolveInitialData })",
            r"""
window.CHANLUN_BOOTSTRAP = undefined;
window.location.pathname = '/ChanlunStrategy/2026-09-04/';
const RealDate = Date;
global.Date = class extends RealDate {
  constructor(value) {
    super(value === undefined ? '2030-01-02T00:00:00Z' : value);
  }
};
const urls = [];
window.fetch = function (url) {
  urls.push(url);
  return Promise.resolve({
    ok: true,
    json: function () {
      return Promise.resolve({ date: '2026-09-04' });
    }
  });
};
const report = await globalThis.__precloseTest.resolve();
assert(urls.length === 1, 'archive fallback did not request one report');
assert(urls[0] === '../data/2026-09-04.json', 'archive fallback ignored path date: ' + urls[0]);
assert(report.date === '2026-09-04', 'archive fallback loaded the wrong report');
""",
        )

    def test_reads_independent_api_and_same_date_snapshot_and_reconciliation(self):
        _assert_node_contract(
            self,
            "({ api: getPrecloseApiBase, load: loadPrecloseAdvisory, state: state, nodes: nodes })",
            r"""
window.CHANLUN_BOOTSTRAP = {
  pageDate: '2026-08-27',
  top10ApiBase: 'https://top10.example',
  precloseApiBase: 'https://preclose.example'
};
window.location.pathname = '/ChanlunStrategy/2026-08-27/';
const classList = { add: function () {}, remove: function () {}, toggle: function () {} };
globalThis.__precloseTest.nodes.precloseAdvisory = { classList: classList };
globalThis.__precloseTest.nodes.precloseBody = { innerHTML: '' };
globalThis.__precloseTest.nodes.precloseReconciliation = { innerHTML: '', classList: classList };
const urls = [];
window.fetch = function (url) {
  urls.push(url);
  const reconciliation = url.includes('/reconciliation?');
  return Promise.resolve({
    ok: true,
    status: 200,
    json: function () { return Promise.resolve(reconciliation ? {
      status: 'unchanged',
      preclose_content_hash: 'a'.repeat(64),
      formal_content_hash: 'b'.repeat(64),
      pools: {}
    } : {
      status: 'available', trade_date: '2026-08-27',
      snapshot_id: 'preclose:2026-08-27:abc', content_hash: 'a'.repeat(64),
      generated_at: '2026-08-27T14:48:20+08:00', expires_at: '2099-08-27T14:56:30+08:00',
      pools: { main: [], h4_t3: [], acceleration: [] }
    }); }
  });
};
assert(globalThis.__precloseTest.api() === 'https://preclose.example', 'preclose API not independent');
await globalThis.__precloseTest.load();
assert(urls[0] === 'https://preclose.example/api/preclose/latest?date=2026-08-27', 'snapshot route wrong');
assert(urls[1] === 'https://preclose.example/api/preclose/reconciliation?date=2026-08-27', 'reconciliation route wrong');
assert(!urls.join('|').includes('top10.example'), 'preclose reused Top10 API');
assert(globalThis.__precloseTest.state.preclose.snapshot.content_hash === 'a'.repeat(64), 'snapshot identity not retained');
""",
        )

    def test_current_root_queries_shanghai_today_instead_of_stale_formal_date(self):
        _assert_node_contract(
            self,
            "({ load: loadPrecloseAdvisory, state: state, nodes: nodes })",
            r"""
window.CHANLUN_BOOTSTRAP = {
  pageDate: '2026-08-28',
  precloseApiBase: 'https://preclose.example'
};
window.location.pathname = '/ChanlunStrategy/';
Date.now = function () { return Date.parse('2026-08-31T00:05:10+08:00'); };
const classList = { add: function () {}, remove: function () {}, toggle: function () {} };
globalThis.__precloseTest.nodes.precloseAdvisory = { classList: classList };
globalThis.__precloseTest.nodes.precloseBody = { innerHTML: '' };
globalThis.__precloseTest.nodes.precloseReconciliation = { innerHTML: '', classList: classList };
const urls = [];
window.fetch = function (url) {
  urls.push(url);
  const reconciliation = url.includes('/reconciliation?');
  return Promise.resolve({
    ok: true,
    status: reconciliation ? 404 : 200,
    json: function () { return Promise.resolve({
      status: 'available', trade_date: '2026-08-31',
      snapshot_id: 'preclose:2026-08-31:abc', content_hash: 'a'.repeat(64),
      generated_at: '2026-08-31T14:48:20+08:00', expires_at: '2026-08-31T14:56:30+08:00',
      pools: { main: [], h4_t3: [], acceleration: [] }
    }); }
  });
};
await globalThis.__precloseTest.load();
assert(urls[0] === 'https://preclose.example/api/preclose/latest?date=2026-08-31', 'root reused stale formal date');
assert(urls[1] === 'https://preclose.example/api/preclose/reconciliation?date=2026-08-31', 'root reconciliation reused stale formal date');
""",
        )

    def test_available_empty_and_expired_render_only_public_action_fields(self):
        _assert_node_contract(
            self,
            "({ build: buildPrecloseSnapshotHtml })",
            r"""
const snapshot = {
  status: 'available', trade_date: '2026-08-27',
  snapshot_id: 'preclose:2026-08-27:abc', content_hash: 'a'.repeat(64),
  generated_at: '2026-08-27T14:48:20+08:00', expires_at: '2026-08-27T14:56:30+08:00',
  pools: {
    main: [{ code: '300998', name: '宁波方正', reference_price: 26.86, score: 99, reason_code: 'internal' }],
    h4_t3: [],
    acceleration: [{ code: '002328', name: '新朋股份', reference_price: 7.61 }]
  },
  diagnostics: { failure_reason: 'secret_failure' }
};
const available = globalThis.__precloseTest.build(snapshot, Date.parse('2026-08-27T14:50:00+08:00'));
assert(available.includes('<details class="preclose-snapshot-card preclose-snapshot-active" open>'), 'active snapshot is not expanded');
assert(available.includes('14:48:20'), 'generated time missing');
assert(available.includes('14:56:30'), 'expiry time missing');
assert(available.includes('宁波方正') && available.includes('参考 26.86'), 'main candidate missing');
assert(available.includes('H4 T+3') && available.includes('本期未选出推荐票'), 'pool empty state missing');
assert(available.includes('快照 aaaaaaaa'), 'snapshot hash identity missing');
['score', 'reason_code', 'internal', 'secret_failure', 'diagnostics'].forEach(function (term) {
  assert(!available.includes(term), 'internal field leaked: ' + term);
});

const allEmpty = Object.assign({}, snapshot, {
  status: 'empty', pools: { main: [], h4_t3: [], acceleration: [] }
});
const empty = globalThis.__precloseTest.build(allEmpty, Date.parse('2026-08-27T14:50:00+08:00'));
assert(empty.includes('本期未选出推荐票'), 'unified empty state missing');
assert(!empty.includes('参考 '), 'empty state retained price');

const expired = globalThis.__precloseTest.build(snapshot, Date.parse('2026-08-27T14:56:30+08:00'));
assert(expired.includes('<details class="preclose-snapshot-card preclose-snapshot-archived">'), 'expired snapshot is not archived');
assert(!expired.includes('<details class="preclose-snapshot-card preclose-snapshot-archived" open>'), 'archived snapshot expanded by default');
assert(expired.includes('14:45预跑 · 已封存'), 'archived title missing');
assert(expired.includes('主推 1只｜H4 T+3 0只｜加速 1只'), 'archived pool counts missing');
assert(expired.includes('14:57后不再依据预跑清单新增动作'), 'inclusive expiry message missing');
assert(expired.includes('宁波方正') && expired.includes('参考 26.86'), 'archived candidates missing');
assert(expired.includes('仅供回看'), 'archived read-only boundary missing');
assert(!expired.includes('<button'), 'expired card kept executable control');
assert(!expired.includes('<a '), 'expired card kept executable link');
""",
        )

    def test_request_failure_does_not_replace_formal_pool_or_claim_empty(self):
        _assert_node_contract(
            self,
            "({ failure: renderPrecloseFailure, nodes: nodes })",
            r"""
const formal = { innerHTML: '<strong>正式主推 宁波方正</strong>' };
globalThis.__precloseTest.nodes.precloseBody = { innerHTML: '' };
globalThis.__precloseTest.failure();
const advisory = globalThis.__precloseTest.nodes.precloseBody.innerHTML;
assert(formal.innerHTML.includes('正式主推 宁波方正'), 'formal pool was overwritten');
assert(advisory.includes('预跑暂不可用，请以盘后正式结果为准'), 'safe failure copy missing');
assert(!advisory.includes('本期未选出推荐票'), 'request failure pretended to be an empty pool');
assert(!advisory.includes('reason') && !advisory.includes('校验'), 'failure leaked internal wording');
""",
        )

    def test_reconciliation_requires_matching_preclose_hash(self):
        _assert_node_contract(
            self,
            "({ build: buildPrecloseReconciliationHtml })",
            r"""
const snapshot = { snapshot_id: 'preclose:2026-08-27:abc', content_hash: 'a'.repeat(64) };
const changed = {
  status: 'changed', preclose_content_hash: 'a'.repeat(64), formal_content_hash: 'b'.repeat(64),
  pools: {
    main: { retained: [{ code: '300998', name: '宁波方正' }], added_after_close: [{ code: '002328', name: '新朋股份' }], removed_after_close: [{ code: '600001', name: 'A股' }] },
    h4_t3: { retained: [], added_after_close: [], removed_after_close: [], unchanged: true },
    acceleration: { retained: [], added_after_close: [{ code: '600002', name: 'B股' }], removed_after_close: [] }
  }
};
const html = globalThis.__precloseTest.build(changed, snapshot);
assert(html.includes('与14:45预跑有变化'), 'changed wording missing');
assert(html.includes('保留 宁波方正') && html.includes('正式新增 新朋股份'), 'changed details missing');
assert(html.includes('预跑有、正式无 A股'), 'removed details missing');
assert(html.includes('H4 T+3：无变化'), 'unchanged pool missing');

const unchanged = globalThis.__precloseTest.build({
  status: 'unchanged', preclose_content_hash: 'a'.repeat(64), formal_content_hash: 'c'.repeat(64),
  pools: { main: { retained: [{ code: '1' }, { code: '2' }] }, h4_t3: { retained: [{ code: '3' }] }, acceleration: { retained: [{ code: '4' }] } }
}, snapshot);
assert(unchanged.includes('正式结果与14:45预跑一致'), 'unchanged wording missing');
assert(unchanged.includes('主推2只｜H4 T+3 1只｜加速1只'), 'unchanged counts missing');

const mismatch = globalThis.__precloseTest.build(Object.assign({}, changed, {
  preclose_content_hash: 'f'.repeat(64)
}), snapshot);
assert(mismatch === '', 'mismatched snapshot diff was displayed');
""",
        )

    def test_missing_api_hides_section_without_fetching(self):
        _assert_node_contract(
            self,
            "({ load: loadPrecloseAdvisory, nodes: nodes })",
            r"""
window.CHANLUN_BOOTSTRAP = { pageDate: '2026-08-27', top10ApiBase: 'https://top10.example' };
let hidden = false;
globalThis.__precloseTest.nodes.precloseAdvisory = { classList: {
  add: function (value) { if (value === 'hidden') hidden = true; },
  remove: function () {}
} };
window.fetch = function () { throw new Error('fetch must not run'); };
await globalThis.__precloseTest.load();
assert(hidden, 'missing API did not hide advisory');
""",
        )

    def test_right_side_evidence_is_compact_and_never_renders_missing_noise(self):
        _assert_node_contract(
            self,
            "({ summary: buildDecisionSummaryColumns })",
            r"""
const raw = {
  right_side_startup_evidence: {
    source_label: '右侧启动',
    reference_price: 48.11,
    why: ['突破20日平台'],
    confirmations: ['30分钟结构确认', '30分钟量能确认'],
    invalidation: ['跌破右侧突破参考位 48.11']
  }
};
const html = globalThis.__precloseTest.summary({}, raw);
assert(html.includes('右侧启动'), 'source label missing');
assert(html.includes('参考位 48.11'), 'reference missing');
assert(html.includes('为何进入') && html.includes('突破20日平台'), 'why missing');
assert(html.includes('关键确认') && html.includes('30分钟结构确认'), 'confirmation missing');
assert(html.includes('失效条件') && html.includes('跌破右侧突破参考位'), 'invalidation missing');
assert(!html.includes('未提供') && !html.includes('暂无'), 'missing-value noise rendered');
""",
        )


if __name__ == "__main__":
    unittest.main()
