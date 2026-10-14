"""After-close sector facts stay outside the frozen daily selection report."""

import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.build_sector_supplement import build_sector_supplement, write_sector_supplement


ROOT = Path(__file__).resolve().parents[1]


def verified_input():
    return {
        "schema_version": 1,
        "report_date": "2026-10-14",
        "observed_at": "2026-10-14T15:39:31+08:00",
        "fetched_at": "2026-10-14T19:00:00+08:00",
        "source": "eastmoney_dataapi",
        "status": "verified",
        "selection_usage": "not_used",
        "sector_flow": [
            {"code": "BK0001", "name": "测试流入甲", "flow": 300000000.0,
             "change_pct": 1.2, "source": "eastmoney_dataapi", "as_of": "2026-10-14T15:39:31+08:00"},
            {"code": "BK0002", "name": "测试流入乙", "flow": 100000000.0,
             "change_pct": None, "source": "eastmoney_dataapi", "as_of": "2026-10-14T15:39:31+08:00"},
        ],
        "sector_outflow": [
            {"code": "BK0003", "name": "测试流出", "flow": -200000000.0,
             "change_pct": -0.8, "source": "eastmoney_dataapi", "as_of": "2026-10-14T15:39:31+08:00"},
        ],
        "component_diagnostics": [
            {"sector_code": "BK0001", "requested": 60, "raw_valid_unique": 60,
             "filtered_unique": 59, "complete": True, "error": ""},
            {"sector_code": "BK0002", "requested": 40, "raw_valid_unique": 40,
             "filtered_unique": 40, "complete": True, "error": ""},
        ],
        "source_evidence": [
            {"url": "https://data.eastmoney.com/dataapi/bkzj/getbkzj",
             "sha256": "a" * 64, "requested_at": "2026-10-14T18:59:00+08:00",
             "received_at": "2026-10-14T18:59:01+08:00"},
        ],
    }


class SectorSupplementBuilderTests(unittest.TestCase):
    def test_build_verified_preserves_raw_cny_and_explicit_component_scope(self):
        source = verified_input()
        original = copy.deepcopy(source)
        result = build_sector_supplement(source, report_date="2026-10-14")
        self.assertEqual(original, source)
        self.assertEqual(300000000.0, result["sector_flow"][0]["flow"])
        self.assertEqual("3.00亿", result["sector_flow"][0]["flow_str"])
        self.assertEqual("流入前2板块成分", result["component_scope"])
        self.assertEqual("not_used", result["selection_usage"])
        self.assertEqual(2, len(result["component_diagnostics"]))

    def test_wrong_day_and_unverified_source_fail_closed(self):
        mutations = (
            lambda value: value.update(report_date="2026-10-13"),
            lambda value: value.update(observed_at="2026-10-13T15:39:31+08:00"),
            lambda value: value["sector_flow"][0].update(as_of="2026-10-13T15:39:31+08:00"),
            lambda value: value.update(source="unknown"),
            lambda value: value.update(selection_usage="used_for_selection"),
            lambda value: value.update(source_evidence=[]),
            lambda value: value["source_evidence"][0].update(sha256="bad"),
        )
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                value = verified_input()
                mutate(value)
                with self.assertRaises(ValueError):
                    build_sector_supplement(value, report_date="2026-10-14")

    def test_verified_requires_exact_complete_inflow_component_scope(self):
        for change in ("missing", "incomplete", "duplicate", "wrong_count", "inexact_complete"):
            with self.subTest(change=change):
                value = verified_input()
                if change == "missing":
                    value["component_diagnostics"].pop()
                elif change == "incomplete":
                    value["component_diagnostics"][0].update(complete=False, error="request_failed")
                elif change == "duplicate":
                    value["component_diagnostics"][1]["sector_code"] = "BK0001"
                else:
                    value["component_diagnostics"][0]["raw_valid_unique"] = 61
                if change == "inexact_complete":
                    value["component_diagnostics"][0]["raw_valid_unique"] = 59
                with self.assertRaises(ValueError):
                    build_sector_supplement(value, report_date="2026-10-14")

    def test_beijing_observation_day_and_negative_outflow_are_required(self):
        value = verified_input()
        value["observed_at"] = "2026-10-13T23:39:31+00:00"
        for row in value["sector_flow"] + value["sector_outflow"]:
            row["as_of"] = value["observed_at"]
        self.assertEqual("verified", build_sector_supplement(value, report_date="2026-10-14")["status"])
        value["observed_at"] = "2026-10-14T23:39:31+00:00"
        for row in value["sector_flow"] + value["sector_outflow"]:
            row["as_of"] = value["observed_at"]
        with self.assertRaises(ValueError):
            build_sector_supplement(value, report_date="2026-10-14")
        value = verified_input()
        value["sector_outflow"][0]["flow"] = 1
        with self.assertRaises(ValueError):
            build_sector_supplement(value, report_date="2026-10-14")

    def test_partial_retains_funds_but_reports_member_gap(self):
        value = verified_input()
        value["status"] = "partial"
        value["component_diagnostics"][0].update(complete=False, error="request_failed")
        result = build_sector_supplement(value, report_date="2026-10-14")
        self.assertEqual("partial", result["status"])
        self.assertEqual(1, sum(bool(row["complete"]) for row in result["component_diagnostics"]))
        self.assertEqual(2, len(result["sector_flow"]))

    def test_file_builder_only_writes_explicit_output(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            source = folder / "validated.json"
            target = folder / "sector-supplement.json"
            source.write_text(json.dumps(verified_input(), ensure_ascii=False), encoding="utf-8")
            write_sector_supplement(source, target, report_date="2026-10-14")
            self.assertEqual("verified", json.loads(target.read_text())["status"])
            self.assertEqual(verified_input(), json.loads(source.read_text()))
            self.assertEqual({"validated.json", "sector-supplement.json"},
                             {path.name for path in folder.iterdir()})


def run_js(exposure, body):
    script = """
const fs = require('fs');
const vm = require('vm');
global.window = { location: { pathname: '/' } };
global.document = { readyState: 'loading', addEventListener() {}, getElementById() { return null; } };
let source = fs.readFileSync('chanlun/report_assets/report-v2.js', 'utf8');
const at = source.lastIndexOf('\\n})();');
if (at < 0) throw Error('IIFE marker missing');
source = source.slice(0, at) + '\\n globalThis.__sectorTest = __EXPOSURE__;' + source.slice(at);
vm.runInThisContext(source, { filename: 'report-v2.js' });
function assert(value, message) { if (!value) throw Error(message); }
__BODY__
""".replace("__EXPOSURE__", exposure).replace("__BODY__", body)
    return subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=10)


class SectorSupplementFrontendTests(unittest.TestCase):
    def test_funding_strip_points_to_supplement_without_using_it_for_filters(self):
        payload = json.dumps(build_sector_supplement(verified_input(), report_date="2026-10-14"), ensure_ascii=False)
        body = """
const report = {date:'2026-10-14',sector_flow:[],sector_outflow:[],
  data_quality:{sector_source:'fallback_static',sector_data_status:'unavailable'}};
const supplement = __PAYLOAD__;
const original = globalThis.__sectorTest.model(report);
assert(original.items.length === 0 && original.status.label === '暂不可用', 'sidecar changed original filter model');
const notice = globalThis.__sectorTest.notice(report, supplement);
assert(notice.includes('盘后资金已补充') && notice.includes('#supportingDecisionsStack')
  && notice.includes('未参与本期筛选'), 'sidecar notice/link missing');
assert(globalThis.__sectorTest.notice(report, Object.assign({}, supplement, {report_date:'2026-10-13'})) === '',
  'wrong-day sidecar advertised in funding strip');
""".replace("__PAYLOAD__", payload)
        completed = run_js("{model: buildFundingMainlineModel, notice: sectorSupplementStripNotice}", body)
        self.assertEqual(0, completed.returncode, completed.stderr)

    def test_valid_supplement_is_visible_without_changing_frozen_report(self):
        body = """
const report = { date: '2026-10-14', sector_flow: [], sector_outflow: [],
  data_quality: { sector_source: 'fallback_static', sector_data_status: 'unavailable',
    warnings: ['板块资金流向接口不可用；静态板块代码仅供成分检索，资金排名缺失',
               '板块成分连续5次抓取失败，未请求剩余15个板块'] } };
const frozen = JSON.stringify(report);
const supplement = { schema_version: 1, report_date: '2026-10-14',
  observed_at: '2026-10-14T15:39:31+08:00', fetched_at: '2026-10-14T19:00:00.171353+08:00',
  source: 'eastmoney_dataapi', status: 'verified', selection_usage: 'not_used',
  component_scope: '流入前2板块成分', component_diagnostics: [
    { sector_code: 'BK0001', requested: 60, raw_valid_unique: 60, filtered_unique: 59, complete: true, error: '' },
    { sector_code: 'BK0002', requested: 40, raw_valid_unique: 40, filtered_unique: 40, complete: true, error: '' }],
  sector_flow: [{ code: 'BK0001', name: '测试流入甲', flow: 300000000, flow_str: '3.00亿', change_pct: 1.2, as_of: '2026-10-14T15:39:31+08:00', source: 'eastmoney_dataapi' },
                { code: 'BK0002', name: '测试流入乙', flow: 100000000, flow_str: '1.00亿', change_pct: null, as_of: '2026-10-14T15:39:31+08:00', source: 'eastmoney_dataapi' }],
  sector_outflow: [{ code: 'BK0003', name: '测试流出', flow: -200000000, flow_str: '-2.00亿', change_pct: -0.8, as_of: '2026-10-14T15:39:31+08:00', source: 'eastmoney_dataapi' }],
  source_evidence: [{ url: 'https://data.eastmoney.com/dataapi/bkzj/getbkzj', sha256: 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', requested_at: '2026-10-14T18:59:00+08:00', received_at: '2026-10-14T18:59:01+08:00' }] };
const accepted = globalThis.__sectorTest.validate(report, supplement);
assert(accepted && accepted.status === 'verified', 'valid supplement rejected');
const html = globalThis.__sectorTest.render(report, accepted);
assert(html.includes('测试流入甲') && html.includes('测试流出'), 'supplementary funds invisible');
assert(html.includes('流入前2板块成分') && html.includes('2&#47;2'), 'component scope not disclosed');
assert(html.includes('板块行情时间') && html.includes('资金获取') && html.includes('北京时间')
  && html.includes('15:39') && html.includes('盘后补齐，未参与本期选股'), 'time or selection boundary missing');
assert(!html.includes('流入 Top5</div><div class="decision-empty">'), 'old empty flow occupied the restored card');
assert(globalThis.__sectorTest.gaps({coverage:{status:'partial'}}, report, accepted).join(' · ').includes('板块原采集缺口；盘后已补充'), 'long gap not condensed');
assert(JSON.stringify(report) === frozen, 'frozen report was mutated');
"""
        completed = run_js("{validate: validateSectorSupplement, render: renderSectorFlowCard, gaps: decisionOverviewGaps}", body)
        self.assertEqual(0, completed.returncode, completed.stderr)

    def test_missing_wrong_day_and_partial_supplement_fail_locally(self):
        body = """
const report = { date: '2026-10-14', sector_flow: [], sector_outflow: [],
  data_quality: { sector_source: 'fallback_static', sector_data_status: 'unavailable' } };
const base = { schema_version: 1, report_date: '2026-10-14',
  observed_at: '2026-10-14T15:39:31+08:00', fetched_at: '2026-10-14T19:00:00+08:00',
  source: 'eastmoney_dataapi', status: 'partial', selection_usage: 'not_used',
  component_scope: '流入前1板块成分', component_diagnostics: [
    {sector_code:'BK0001', requested:60, raw_valid_unique:30, filtered_unique:30, complete:false, error:'failed'}],
  sector_flow: [{code:'BK0001',name:'部分板块',flow:123,flow_str:'123.00元',change_pct:null,as_of:'2026-10-14T15:39:31+08:00',source:'eastmoney_dataapi'}],
  sector_outflow: [{code:'BK0002',name:'流出板块',flow:-100,flow_str:'-100.00元',change_pct:null,as_of:'2026-10-14T15:39:31+08:00',source:'eastmoney_dataapi'}],
  source_evidence:[{url:'https://data.eastmoney.com/dataapi/bkzj/getbkzj',sha256:'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',requested_at:'2026-10-14T18:59:00+08:00',received_at:'2026-10-14T18:59:01+08:00'}] };
assert(globalThis.__sectorTest.validate(report, null) === null, 'missing supplement accepted');
assert(globalThis.__sectorTest.validate(report, Object.assign({},base,{report_date:'2026-10-13'})) === null, 'wrong report date accepted');
assert(globalThis.__sectorTest.validate(report, Object.assign({},base,{source:'unknown'})) === null, 'unknown source accepted');
const partial = globalThis.__sectorTest.validate(report, base);
assert(partial && partial.status === 'partial', 'partial supplement hidden');
const html = globalThis.__sectorTest.render(report, partial);
assert(html.includes('盘后部分补充') && html.includes('0&#47;1'), 'partial member gap was hidden');
assert(!globalThis.__sectorTest.render(report, null).includes('部分板块'), 'missing supplement leaked stale funds');
const wrongMoney = JSON.parse(JSON.stringify(base));
wrongMoney.sector_outflow[0].flow_str = '100.00元';
const acceptedWrongText = globalThis.__sectorTest.validate(report, wrongMoney);
assert(acceptedWrongText !== null, 'text-only mismatch hid verified numeric funds');
const moneyHtml = globalThis.__sectorTest.render(report, acceptedWrongText);
assert(moneyHtml.includes('-100.00元') && !moneyHtml.includes('>100.00元<'),
  'untrusted amount text overrode the signed CNY value');
const wrongDirection = JSON.parse(JSON.stringify(base));
wrongDirection.sector_outflow[0].flow = 100;
wrongDirection.sector_outflow[0].flow_str = '100.00元';
assert(globalThis.__sectorTest.validate(report, wrongDirection) === null, 'positive funding called outflow');
"""
        completed = run_js("{validate: validateSectorSupplement, render: renderSectorFlowCard}", body)
        self.assertEqual(0, completed.returncode, completed.stderr)

    def test_loader_uses_report_date_and_ignores_failed_fetch(self):
        body = """
const report = {date:'2026-10-14',sector_flow:[],sector_outflow:[],data_quality:{sector_data_status:'unavailable'}};
assert(globalThis.__sectorTest.url('2026-10-14') === 'data/sector-supplement/2026-10-14.json', 'root URL wrong');
window.location.pathname='/2026-10-14/';
assert(globalThis.__sectorTest.url('2026-10-14') === '../data/sector-supplement/2026-10-14.json', 'archive URL wrong');
window.location.pathname='/2026-10-14/index.html';
window.CHANLUN_BOOTSTRAP={pageDate:'2026-10-14',dataBasePrefix:''};
assert(globalThis.__sectorTest.url('2026-10-14') === '../data/sector-supplement/2026-10-14.json', 'explicit archive index URL wrong');
window.fetch = () => Promise.reject(Error('offline'));
globalThis.__sectorTest.load(report).then(value => { assert(value === null, 'failed supplement blocked original page'); });
"""
        completed = run_js("{url: sectorSupplementUrl, load: fetchSectorSupplement}", body)
        self.assertEqual(0, completed.returncode, completed.stderr)


if __name__ == "__main__":
    unittest.main()
