"""A dated icepoint sidecar may replace only the observation card it proves."""

import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_js(body):
    full = json.loads((ROOT / "docs/data/2026-10-14.json").read_text(encoding="utf-8"))
    report = {key: full[key] for key in ("date", "data_quality", "market_icepoint")}
    report["data_quality"] = {"bar_state": report["data_quality"]["bar_state"]}
    script = r"""
const fs = require('fs');
const vm = require('vm');
global.window = { location: { pathname: '/' } };
global.document = { readyState: 'loading', addEventListener() {}, getElementById() { return null; } };
let source = fs.readFileSync('chanlun/report_assets/report-v2.js', 'utf8');
const at = source.lastIndexOf('\n})();');
if (at < 0) throw Error('IIFE marker missing');
source = source.slice(0, at) + '\n globalThis.__iceTest = { validate: validateIcepointSupplement, url: icepointSupplementUrl, load: fetchIcepointSupplement, render: buildMarketIcepoint, card: renderIcepointObservation };' + source.slice(at);
vm.runInThisContext(source, { filename: 'report-v2.js' });
function assert(value, message) { if (!value) throw Error(message); }
const report = __REPORT__;
__BODY__
""".replace("__REPORT__", json.dumps(report, ensure_ascii=False)).replace("__BODY__", body)
    return subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=10)


class IcepointSupplementFrontendTests(unittest.TestCase):
    def test_natural_same_day_provider_result_renders_without_sidecar(self):
        from chanlun.market_icepoint import supplement_icepoint
        from tests.test_build_icepoint_supplement import normalized_evidence

        full = json.loads((ROOT / "docs/data/2026-10-14.json").read_text(encoding="utf-8"))
        evidence = normalized_evidence()
        evidence["turnover"]["as_of"] = "2026-10-14T15:23:50+08:00"
        evidence["turnover"]["retrieved_at"] = evidence["turnover"]["as_of"]
        evidence["breadth"]["retrieved_at"] = evidence["turnover"]["as_of"]
        produced = supplement_icepoint(full["market_icepoint"], evidence)
        self.assertEqual((4, 0), (produced["verified_count"], produced["matched_count"]))
        body = """
report.market_icepoint=__PRODUCED__;
const html=__iceTest.render(report);
assert(html.includes('已核验 4/4') && html.includes('已满足 0/4')
  && !html.includes('证据不一致'), 'natural same-day provider result rejected');
assert(html.includes('停牌 11'), 'verified suspension count hidden');
const forged=JSON.parse(JSON.stringify(report));
forged.market_icepoint.items.volume_drop.actual.source_code='883421.TI';
assert(__iceTest.render(forged).includes('证据不一致'), 'wrong provider index accepted');
const lateSameDay=JSON.parse(JSON.stringify(report));
lateSameDay.market_icepoint.items.volume_drop.as_of='2026-10-14T15:24:00+08:00';
lateSameDay.market_icepoint.items.volume_drop.actual.retrieved_at=lateSameDay.market_icepoint.items.volume_drop.as_of;
assert(__iceTest.render(lateSameDay).includes('证据不一致'), 'receipt after supplement time accepted');
const wrongSuspended=JSON.parse(JSON.stringify(report));
wrongSuspended.market_icepoint.items.breadth.actual.suspended_count=10;
assert(__iceTest.render(wrongSuspended).includes('证据不一致'), 'unreconciled suspension displayed');
const late=JSON.parse(JSON.stringify(report));
late.market_icepoint.items.volume_drop.as_of='2026-10-15T15:23:50+08:00';
late.market_icepoint.items.volume_drop.actual.retrieved_at=late.market_icepoint.items.volume_drop.as_of;
late.market_icepoint.supplemented_at=late.market_icepoint.items.volume_drop.as_of;
assert(__iceTest.render(late).includes('证据不一致'), 'next-day claim embedded in natural report');
""".replace("__PRODUCED__", json.dumps(produced, ensure_ascii=False))
        result = run_js(body)
        self.assertEqual(0, result.returncode, result.stderr)

    def test_published_dated_sidecar_matches_the_frozen_report(self):
        sidecar = json.loads((ROOT / "docs/data/icepoint-supplement/2026-10-14.json").read_text(encoding="utf-8"))
        body = """
const sidecar=__SIDECAR__;
assert(__iceTest.validate(report,sidecar), 'dated public sidecar failed original binding');
const html=__iceTest.card(report,sidecar);
assert(html.includes('已核验 4/4') && html.includes('已满足 0/4')
  && html.includes('停牌 11') && html.includes('0.8592')
  && html.includes('10月15日补证'), 'dated result not visible');
""".replace("__SIDECAR__", json.dumps(sidecar, ensure_ascii=False))
        result = run_js(body)
        self.assertEqual(0, result.returncode, result.stderr)

    def test_binds_frozen_original_and_renders_only_icepoint_observation(self):
        body = r"""
const frozen = JSON.stringify(report);
const original = JSON.parse(JSON.stringify(report.market_icepoint));
const corrected = JSON.parse(JSON.stringify(original));
corrected.status = 'not_matched';
corrected.verified_count = 4;
corrected.supplemented_at = '2026-10-15T10:30:00+08:00';
corrected.items.volume_drop.status = 'not_matched';
corrected.items.volume_drop.reason = '';
corrected.items.volume_drop.source = 'wencai';
corrected.items.volume_drop.as_of = '2026-10-15T10:30:00+08:00';
corrected.items.volume_drop.actual = {
  current_cny:1426389200000, prior_mean_cny:1660128520000, ratio:0.8592,
  prior_dates:['2026-09-30','2026-10-08','2026-10-09','2026-10-12','2026-10-13'],
  market_date:'2026-10-14', source_code:'883957.TI', amount_unit:'CNY',
  retrieved_at:'2026-10-15T10:30:00+08:00'
};
corrected.items.breadth.status = 'not_matched';
corrected.items.breadth.reason = '';
corrected.items.breadth.source = 'quote_snapshot+wencai';
corrected.items.breadth.as_of = original.as_of;
corrected.items.breadth.actual = {
  advance_count:978, decline_count:4496, flat_count:88,
  valid_count:5562, denominator:5562, quote_snapshot_count:5573,
  trading_count:5562, suspended_count:11, unknown_count:0,
  retrieved_at:'2026-10-15T10:30:00+08:00'
};
const supplement = {
  schema_version:1, report_date:'2026-10-14', source:'hithink_iwencai_883957',
  selection_usage:'not_used', supplemented_at:'2026-10-15T10:30:00+08:00',
  original_market_icepoint:original, supplemented_market_icepoint:corrected,
  turnover_days:[
    {date:'2026-09-30', amount_cny:1600000000000},
    {date:'2026-10-08', amount_cny:1600000000000},
    {date:'2026-10-09', amount_cny:1700000000000},
    {date:'2026-10-12', amount_cny:1700000000000},
    {date:'2026-10-13', amount_cny:1700642600000},
    {date:'2026-10-14', amount_cny:1426389200000}
  ],
  source_evidence:[{url:'https://openapi.iwencai.com/v1/query2data',
    sha256:'a'.repeat(64), received_at:'2026-10-15T10:30:00+08:00'}]
};
assert(__iceTest.validate(report,supplement), 'valid bound supplement rejected');
const html=__iceTest.card(report,supplement);
assert(html.includes('已核验 4/4') && html.includes('已满足 0/4'), 'new status hidden');
assert(html.includes('10月14日收盘事实') && html.includes('10月15日补证'), 'two dates not distinguished');
assert(html.includes('同花顺全A（沪深京）') && html.includes('停牌 11'), 'scope or suspension hidden');
assert(html.includes('14263.89') && html.includes('16601.29') && html.includes('0.86'), 'turnover facts hidden');
assert(html.includes('2026-09-30') && html.includes('2026-10-13'), 'six dates hidden');
assert(JSON.stringify(report)===frozen, 'frozen report changed');
assert(JSON.stringify(window.REPORT_DATA || {})==='{}', 'published report changed');
const wrongOriginal=JSON.parse(JSON.stringify(supplement));
wrongOriginal.original_market_icepoint.items.breadth.actual.advance_count++;
assert(__iceTest.validate(report,wrongOriginal)===null, 'changed original accepted');
assert(__iceTest.card(report,wrongOriginal)===__iceTest.render(report), 'bad binding changed observation');
const wrongDay=Object.assign({},supplement,{report_date:'2026-10-13'});
assert(__iceTest.validate(report,wrongDay)===null, 'wrong day accepted');
const wrongAmount=JSON.parse(JSON.stringify(supplement));
wrongAmount.turnover_days[5].amount_cny++;
assert(__iceTest.validate(report,wrongAmount)===null, 'unreconciled turnover accepted');
const wrongSuspension=JSON.parse(JSON.stringify(supplement));
wrongSuspension.supplemented_market_icepoint.items.breadth.actual.suspended_count=10;
assert(__iceTest.validate(report,wrongSuspension)===null, 'unreconciled suspension accepted');
const changedFrozenCondition=JSON.parse(JSON.stringify(supplement));
changedFrozenCondition.supplemented_market_icepoint.items.six_indices.actual.changes_pct['上证指数']=-2;
assert(__iceTest.validate(report,changedFrozenCondition)===null, 'frozen index condition changed');
const unproven=Object.assign({},supplement,{source_evidence:[]});
assert(__iceTest.validate(report,unproven)===null, 'unproven source accepted');
const wrongIdentity=JSON.parse(JSON.stringify(supplement));
wrongIdentity.supplemented_market_icepoint.items.volume_drop.source='unknown';
assert(__iceTest.validate(report,wrongIdentity)===null, 'unknown turnover source accepted');
const malformed=JSON.parse(JSON.stringify(supplement));
delete malformed.supplemented_market_icepoint.items.volume_drop;
assert(__iceTest.validate(report,malformed)===null, 'malformed sidecar did not fail locally');
const undatedTime=JSON.parse(JSON.stringify(supplement));
undatedTime.supplemented_at='2026-10-15';
undatedTime.supplemented_market_icepoint.supplemented_at='2026-10-15';
assert(__iceTest.validate(report,undatedTime)===null, 'date without source time accepted');
assert(__iceTest.card(report,null)===__iceTest.render(report), 'missing sidecar changed old observation');
"""
        result = run_js(body)
        self.assertEqual(0, result.returncode, result.stderr)

    def test_loader_paths_and_failure_are_local(self):
        body = r"""
assert(__iceTest.url('2026-10-14')==='data/icepoint-supplement/2026-10-14.json', 'root path');
window.location.pathname='/2026-10-14/';
assert(__iceTest.url('2026-10-14')==='../data/icepoint-supplement/2026-10-14.json', 'archive path');
window.location.pathname='/2026-10-14/index.html';
window.CHANLUN_BOOTSTRAP={pageDate:'2026-10-14',dataBasePrefix:''};
assert(__iceTest.url('2026-10-14')==='../data/icepoint-supplement/2026-10-14.json', 'explicit index path');
window.fetch=()=>Promise.reject(Error('offline'));
__iceTest.load(report).then(value=>{assert(value===null,'failed sidecar blocked old observation');});
"""
        result = run_js(body)
        self.assertEqual(0, result.returncode, result.stderr)


if __name__ == '__main__':
    unittest.main()
