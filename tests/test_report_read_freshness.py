"""Exercise real report readers against cached and malformed index responses."""

import json
from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
HARNESS = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const config = __CONFIG__;
const calls = [];
const controls = {};
function control(id) {
  return controls[id] || (controls[id] = {
    innerHTML:'', textContent:'', value:'', disabled:false,
    addEventListener(name, handler) { this[name] = handler; },
    querySelectorAll() { return []; }
  });
}
const body = {innerHTML:'', querySelector:control};
const root = {html:'', querySelector:control, get innerHTML() {return this.html;},
  set innerHTML(value) {
    this.html=value;
    const source=value.match(/<option value="([^"]+)" selected>/);
    control('#comparisonSource').value=source ? source[1] : '';
    control('#comparisonTarget').value='current';
  }
};
const document = {readyState:'loading', addEventListener(){},
  getElementById(id) {return config.mode === 'page' && id === 'comparisonApp' ? root : null;},
  createElement() {return {innerHTML:'',querySelector(){return body;}};}
};
const window = {location:{pathname:config.path || '/ChanlunStrategy/',hash:''},
  CHANLUN_BOOTSTRAP:{}, fetch(url, options) {
    calls.push({url,options});
    if (config.failure) return Promise.reject(new Error('offline'));
    const index=options && options.cache === 'no-store' ? config.index : config.cached || config.index;
    return Promise.resolve({ok:true,json:()=>Promise.resolve(index)});
  }
};
const sandbox = {window,document,console,Promise,URL,Date,setTimeout,clearTimeout,AbortController};
let source=fs.readFileSync('chanlun/report_assets/report-v2.js','utf8');
const at=source.lastIndexOf('\n})();');
source=source.slice(0,at)+'\nglobalThis.reader={summary:initComparisonSummary,page:initComparisonPage,nodes:nodes,state:state};\n'+source.slice(at);
vm.runInNewContext(source,sandbox);
sandbox.reader.nodes.shell={querySelector(){return null;},appendChild(){}};
sandbox.reader.state.data={date:config.day === undefined ? '2026-10-19' : config.day,sentinel:'report body remains bound'};
async function settle() {for(let i=0;i<25;i++) await Promise.resolve();}
(async()=>{
  sandbox.reader[config.mode || 'summary'](); await settle();
  __BODY__
})().catch(error=>{console.error(error);process.exitCode=1;});
"""


def check(body, **config):
    script = HARNESS.replace("__CONFIG__", json.dumps(config)).replace("__BODY__", body)
    result = subprocess.run(["node"], input=script, cwd=ROOT, text=True,
                            capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr


def index_for(dates):
    return {"dates": dates, "latest_date": dates[-1] if dates else "",
            "reports": {date: {"views": {"main": []}} for date in dates}}


class ReportReadFreshnessTests(unittest.TestCase):
    def test_summary_fetches_fresh_index_when_html_has_advanced(self):
        check(r"""
assert.equal(calls[0].options.cache,'no-store');
assert.match(body.innerHTML,/源报告日 2026-10-16/);
assert.equal(sandbox.reader.state.data.sentinel,'report body remains bound');
""", index=index_for(["2026-10-14", "2026-10-16", "2026-10-19"]),
              cached=index_for(["2026-10-13", "2026-10-14", "2026-10-16"]))

    def test_summary_uses_latest_strictly_earlier_date_even_with_old_index(self):
        check("assert.match(body.innerHTML,/源报告日 2026-10-16/);",
              index=index_for(["2026-10-13", "2026-10-14", "2026-10-16"]))

    def test_summary_sorts_deduplicates_and_ignores_invalid_or_unpublished_dates(self):
        index = index_for(["2026-10-16", "2026-10-14", "2026-10-19", "2026-10-16",
                           "2026-02-30", "garbage", "2026-10-18", "2026-10-17"])
        del index["reports"]["2026-10-18"]
        index["reports"]["2026-10-17"] = []
        check("assert.match(body.innerHTML,/源报告日 2026-10-16/);", index=index)

    def test_summary_selects_prior_to_archive_without_using_index_position(self):
        check("assert.match(body.innerHTML,/源报告日 2026-10-13/);",
              day="2026-10-14", path="/ChanlunStrategy/2026-10-14/",
              index=index_for(["2026-10-16", "2026-10-14", "2026-10-13"]))

    def test_first_edition_or_archive_outside_window_degrades_only_summary(self):
        index = json.loads((ROOT / "docs/data/comparison-index.json").read_text())
        for day in ("2026-08-14", index["dates"][0], "2026-02-30", ""):
            with self.subTest(day=day):
                check(r"""
assert(!body.innerHTML.includes('源报告日 '),'future or same-day comparison must not leak');
assert.match(body.innerHTML,/暂无可用的历史榜单索引/);
assert.equal(sandbox.reader.state.data.sentinel,'report body remains bound');
assert.equal(calls.length,1,'do not fetch other dates to fill the gap');
""", day=day, path="/ChanlunStrategy/" + day + "/", index=index)

    def test_summary_network_failure_preserves_bound_report(self):
        check("assert.match(body.innerHTML,/暂无可用的历史榜单索引/);"
              "assert.equal(sandbox.reader.state.data.sentinel,'report body remains bound');",
              failure=True, index=index_for(["2026-10-16"]))

    def test_comparison_page_reads_fresh_index_and_normalizes_date_options(self):
        check(r"""
assert.equal(calls[0].url,'../data/comparison-index.json');
assert.equal(calls[0].options.cache,'no-store');
assert.equal(control('#comparisonSource').value,'2026-10-16');
const dates=[...root.innerHTML.matchAll(/<option value="([^"]+)"/g)].map(match=>match[1]);
assert.equal(dates.join(','),'2026-10-14,2026-10-16,2026-10-19,current,2026-10-14,2026-10-16,2026-10-19');
""", mode="page", index=index_for(["2026-10-19", "2026-10-14", "2026-02-30",
                                          "2026-10-16", "2026-10-16"]),
              cached=index_for(["2026-10-13", "2026-10-14", "2026-10-16"]))

    def test_comparison_page_no_usable_dates_has_local_empty_state(self):
        check("assert.match(root.innerHTML,/暂无可用的历史报告索引/);",
              mode="page", index={"dates": ["2026-02-30"], "reports": {}})


if __name__ == "__main__":
    unittest.main()
