"""Offline behavior checks for homepage publication refresh; no server is started."""

import json
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
HARNESS = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const config = __CONFIG__;
const oldTime = Date.parse('Fri, 16 Oct 2026 07:58:12 GMT');
const newTime = Date.parse('Fri, 16 Oct 2026 09:01:57 GMT');
let now = Date.parse('Fri, 16 Oct 2026 10:00:00 GMT');
const NativeDate = Date;
class ClockDate extends NativeDate { static now() { return now; } }
const timers = new Map();
let timerId = 0;
function setTimer(fn, ms) { timers.set(++timerId, {fn, at: now + ms}); return timerId; }
function clearTimer(id) { timers.delete(id); }
function eventTarget() {
  const handlers = {};
  return {handlers, addEventListener(name, fn) {
    (handlers[name] || (handlers[name] = [])).push(fn);
  }, dispatch(name) { (handlers[name] || []).forEach(fn => fn({type:name})); }};
}
const initialUrl = new URL(config.url || 'https://example.test/ChanlunStrategy/?key=kept#market-hotspot');
const navigation = [];
const location = Object.assign(initialUrl, {replace(value) { navigation.push(value); }});
const report = {date: config.day || '2026-10-14', marker: 'old-inline-report'};
const controls = [];
const document = Object.assign(eventTarget(), {
  readyState: 'loading', visibilityState: config.hidden ? 'hidden' : 'visible',
  lastModified: config.modified === undefined ? new NativeDate(oldTime).toUTCString() : config.modified,
  currentScript: {src:'https://example.test/ChanlunStrategy/assets/report-v2.js?v=source'},
  activeElement: null,
  getElementById() { return null; },
  querySelectorAll() { return controls; }
});
const calls = [];
let respond = async () => ({ok:true, headers:{get(name) {
  return name.toLowerCase() === 'last-modified' ? new NativeDate(newTime).toUTCString() : null;
}}});
const window = Object.assign(eventTarget(), {
  location, URL, AbortController, setTimeout:setTimer, clearTimeout:clearTimer,
  CHANLUN_BOOTSTRAP: Object.assign({pageDate:report.date, dataBasePrefix:'', inlineReportData:report}, config.bootstrap),
  localStorage:{getItem() { return ''; }},
  fetch(url, options) { calls.push({url, options}); return respond(url, options); }
});
const sandbox = {window, document, URL, URLSearchParams, TextEncoder, Date:ClockDate, AbortController,
  setTimeout:setTimer, clearTimeout:clearTimer, console, Promise};
let source = fs.readFileSync('chanlun/report_assets/report-v2.js', 'utf8');
// Keep the real init, access decision, inline-data resolution and event registration.
// Rendering and unrelated data requests are outside this isolated browser boundary.
const isolated = `
  syncViewport = isMobileViewport = function () { return false; };
  buildAppShell = refreshReviewToolsMounts = renderPrimaryMode = openNextdayResearchFromHash =
  loadPrecloseAdvisory = resetTop10State = renderTop10Control = loadLatestTop10Snapshot =
  renderHeader = renderDecisionOverview = renderReviewToolPanels = renderFundingMainlineStrip =
  renderMarketHotspot = renderHistoricalReconstruction = renderWorkspaceTabs = renderViewDescription =
  renderCurrentCandidateSelection = renderAuxiliaryCenter = loadNextdayResearch =
  initComparisonSummary = initSelectionPerformance = function () {};
  fetchSectorSupplement = fetchIcepointSupplement = function () { return Promise.resolve(null); };
  globalThis.fixture = { state:state, init:initReportV2 };
`;
const at = source.lastIndexOf('\n})();');
source = source.slice(0, at) + isolated + source.slice(at);
vm.runInNewContext(source, sandbox, {filename:'report-v2.js'});
const state = sandbox.fixture.state;
async function settle() { for (let i=0; i<25; i++) await Promise.resolve(); }
async function start() { document.dispatch('DOMContentLoaded'); await settle(); }
async function advance(ms=31000) {
  now += ms;
  for (const [id, task] of [...timers]) {
    if (task.at <= now) { timers.delete(id); task.fn(); }
  }
  await settle();
}
async function show() { document.visibilityState='visible'; document.dispatch('visibilitychange'); await settle(); }
(async function () {
__BODY__
})().catch(err => { console.error(err); process.exitCode=1; });
"""


def check(body, **config):
    script = HARNESS.replace("__CONFIG__", json.dumps(config)).replace("__BODY__", body)
    result = subprocess.run(["node", "-e", script], cwd=ROOT, text=True,
                            capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("day", ["2026-10-14", "2026-10-16"])
def test_initial_homepage_reload_preserves_inline_context_query_and_hash(day):
    check(r"""
await start();
assert.equal(calls.length, 1, 'opening the homepage must check its publication');
assert.equal(calls[0].options.method, 'HEAD');
assert.equal(calls[0].options.cache, 'no-store');
assert.equal(calls[0].options.redirect, 'error');
const probe = new URL(calls[0].url);
assert.equal(probe.origin, location.origin);
assert.equal(probe.pathname, '/ChanlunStrategy/index.html');
assert.equal(probe.searchParams.get('key'), 'kept');
assert.equal(probe.hash, '');
assert.equal(navigation.length, 1, 'new day and same-day update require a full document load');
const target = new URL(navigation[0]);
assert.equal(target.pathname, location.pathname);
assert.equal(target.searchParams.get('key'), 'kept');
assert.equal(target.hash, '#market-hotspot');
assert.equal(target.searchParams.get('_report_version'), String(newTime));
assert.equal(window.REPORT_DATA, report, 'do not merge newer JSON into an older bootstrap');
""", day=day)


@pytest.mark.parametrize("url,bootstrap", [
    ("https://example.test/ChanlunStrategy/2026-10-14/", {}),
    ("https://example.test/ChanlunStrategy/2026-10-14/index.html", {}),
    ("https://example.test/ChanlunStrategy/compare/index.html", {"pageMode":"comparison"}),
    ("https://example.test/ChanlunStrategy/selection-performance/", {}),
    ("file:///tmp/ChanlunStrategy/index.html", {"isFileProtocol":True}),
    ("https://example.test/ChanlunStrategy/", {"dataBasePrefix":"../"}),
])
def test_archive_compare_nonhome_and_file_pages_do_not_check(url, bootstrap):
    check("await start(); assert.equal(calls.length, 0); assert.equal(navigation.length, 0);",
          url=url, bootstrap=bootstrap)


def test_public_homepage_without_access_key_still_checks_and_keeps_existing_inline_access():
    check("await start(); assert.equal(state.granted,false); assert.equal(window.REPORT_DATA,report);"
          "assert.equal(calls.length,1); assert.equal(navigation.length,1);",
          bootstrap={"accessControlEnabled":True, "accessKeyHash":"not-granted"})


def test_protected_archive_without_access_key_keeps_existing_denial():
    check("await start(); assert.equal(state.granted,false); assert.equal(window.REPORT_DATA,undefined);"
          "assert.equal(calls.length,0); assert.equal(navigation.length,0);",
          url="https://example.test/ChanlunStrategy/2026-10-14/",
          bootstrap={"dataBasePrefix":"../", "accessControlEnabled":True, "accessKeyHash":"not-granted"})


def test_pageshow_before_access_resolution_still_checks_once_after_initialization():
    check(r"""
let grant;
window.TextEncoder=TextEncoder;
window.crypto={subtle:{digest(){return new Promise(resolve=>{grant=resolve;});}}};
await start(); window.dispatch('pageshow'); await show(); assert.equal(calls.length,0);
grant(new Uint8Array([1]).buffer); await settle();
assert.equal(state.granted,true); assert.equal(calls.length,1); assert.equal(navigation.length,1);
""", bootstrap={"accessControlEnabled":True, "accessKeyHash":"01"})


@pytest.mark.parametrize("header", [None, "garbage", "1", "Thu, 15 Oct 2026 07:58:12 GMT",
                                    "Fri, 16 Oct 2026 07:58:12 GMT",
                                    "Sun, 16 Oct 2050 09:01:57 GMT"])
def test_missing_invalid_old_equal_or_future_metadata_keeps_current_report(header):
    check("respond=async()=>({ok:true,headers:{get(){return " + json.dumps(header) + ";}}});"
          "await start(); assert.equal(calls.length, 1); assert.equal(navigation.length, 0);"
          "assert.equal(window.REPORT_DATA, report);")


@pytest.mark.parametrize("failure", ["throw new Error('offline')", "return {ok:false,status:503}"])
def test_network_and_http_failure_keep_current_report(failure):
    check("respond=async()=>{" + failure + ";}; await start();"
          "assert.equal(calls.length,1); assert.equal(navigation.length,0); assert.equal(window.REPORT_DATA,report);")


def test_no_valid_document_timestamp_means_no_speculative_reload():
    check("await start(); assert.equal(calls.length,0); assert.equal(navigation.length,0);", modified="invalid")


def test_return_and_visible_events_are_throttled_without_polling():
    check(r"""
respond=async()=>({ok:true,headers:{get(){return new NativeDate(oldTime).toUTCString();}}});
await start(); assert.equal(calls.length,1);
window.dispatch('pageshow'); await show(); assert.equal(calls.length,1);
await advance(); assert.equal(calls.length,1,'elapsed time alone must not poll');
window.dispatch('pageshow'); await settle(); assert.equal(calls.length,2);
document.visibilityState='hidden'; document.dispatch('visibilitychange'); await advance();
assert.equal(calls.length,2,'hidden tabs must not check');
await show(); assert.equal(calls.length,3);
assert.equal(timers.size,0,'completed checks must release their timeout');
""")


def test_initial_hidden_document_waits_until_visible():
    check("await start(); assert.equal(calls.length,0); await show(); assert.equal(calls.length,1);", hidden=True)


def test_pending_check_is_deduplicated_times_out_and_can_retry():
    check(r"""
let finish;
respond=()=>new Promise(resolve=>{finish=resolve;});
await start(); assert.equal(calls.length,1);
await advance(31000); // Timeout must settle even if fetch ignores abort.
assert.equal(calls[0].options.signal.aborted,true);
assert.equal(navigation.length,0);
finish({ok:true,headers:{get(){return new NativeDate(newTime).toUTCString();}}});
await settle(); assert.equal(navigation.length,0,'late response must not reload after timeout');
respond=async()=>({ok:true,headers:{get(){return new NativeDate(oldTime).toUTCString();}}});
window.dispatch('pageshow'); await settle(); assert.equal(calls.length,2);
""")


def test_duplicate_events_do_not_start_parallel_requests_or_duplicate_reload():
    check(r"""
let finish;
respond=()=>new Promise(resolve=>{finish=resolve;});
await start();
window.dispatch('pageshow'); await show(); assert.equal(calls.length,1);
finish({ok:true,headers:{get(){return new NativeDate(newTime).toUTCString();}}});
await settle(); assert.equal(navigation.length,1);
await advance(); window.dispatch('pageshow'); await show();
assert.equal(navigation.length,1); assert.equal(calls.length,1);
""")


def test_query_version_marker_stops_same_version_reload_loop_but_allows_a_newer_publication():
    check(r"""
await start(); assert.equal(calls.length,1); assert.equal(navigation.length,0);
await advance();
respond=async()=>({ok:true,headers:{get(){return new NativeDate(newTime+1000).toUTCString();}}});
window.dispatch('pageshow'); await settle(); assert.equal(navigation.length,1);
assert.equal(new URL(navigation[0]).searchParams.get('key'),'kept');
""", url="https://example.test/ChanlunStrategy/index.html?key=kept&_report_version=1792141317000#market-hotspot")


def test_alternating_cdn_versions_do_not_reload_versions_older_than_the_last_attempt():
    check(r"""
await start(); assert.equal(navigation.length,0,'version B already attempted; do not navigate back to A');
await advance();
respond=async()=>({ok:true,headers:{get(){return new NativeDate(newTime+1000).toUTCString();}}});
window.dispatch('pageshow'); await settle(); assert.equal(navigation.length,0,'B must not repeat either');
await advance();
respond=async()=>({ok:true,headers:{get(){return new NativeDate(newTime+2000).toUTCString();}}});
window.dispatch('pageshow'); await settle(); assert.equal(navigation.length,1,'newer C is still eligible');
""", url="https://example.test/ChanlunStrategy/?_report_version=1792141318000")


@pytest.mark.parametrize("marker", ["invalid", "9999999999999", "1792141317000x", "1.792141317e12"])
def test_invalid_or_future_reload_marker_cannot_suppress_a_real_update(marker):
    check("await start(); assert.equal(calls.length,1); assert.equal(navigation.length,1);",
          url="https://example.test/ChanlunStrategy/?_report_version=" + marker)


@pytest.mark.parametrize("edit", ["state.watchlistManager.dirty=true", "state.watchlistManager.saving=true",
                                   "document.activeElement={matches(){return true;}}",
                                   "controls.push({value:'unsaved add code'})"])
def test_unsaved_or_active_edits_defer_refresh_until_safe(edit):
    check(edit + r""";
await start(); assert.equal(navigation.length,0,'automatic refresh must not discard editing');
state.watchlistManager.dirty=false; state.watchlistManager.saving=false;
document.activeElement=null; controls.length=0;
await advance(); window.dispatch('pageshow'); await settle();
assert.equal(navigation.length,1,'later safe entry must still load the new version');
""")


@pytest.mark.parametrize("change", ["state.watchlistManager.dirty=true", "document.visibilityState='hidden'"])
def test_edit_or_hidden_state_beginning_during_probe_prevents_navigation(change):
    check(r"""
let finish;
respond=()=>new Promise(resolve=>{finish=resolve;});
await start(); assert.equal(calls.length,1);
""" + change + r""";
finish({ok:true,headers:{get(){return new NativeDate(newTime).toUTCString();}}});
await settle(); assert.equal(navigation.length,0);
""")
