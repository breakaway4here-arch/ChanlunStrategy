"""The current report shell exposes the B4 view and keeps old research reachable."""

import unittest

from tests.test_auxiliary_frontend import _assert_node_contract


class SelectionPerformanceShellTests(unittest.TestCase):
    def test_two_tabs_keep_research_inside_collapsed_performance_details(self):
        _assert_node_contract(self, "({build: buildAppShell})", r"""
const app = {innerHTML: '', querySelector: function () { return null; }};
document.getElementById = function (id) { return id === 'app' ? app : null; };
__auxTest.build();
const html = app.innerHTML;
assert(html.indexOf('data-primary-mode="today"') < html.indexOf('data-primary-mode="performance"'), 'performance is not after today');
assert(!html.includes('data-primary-mode="research"'), 'research became a third primary tab');
assert(html.includes('>选股表现</button>'), 'second tab is not named selection performance');
assert(html.includes('id="selectionPerformanceView"'), 'performance panel missing');
assert(html.includes('id="selectionPerformanceMount"'), 'performance mount missing');
assert(html.includes('<details class="advanced-research-details" id="advancedResearchDetails">'), 'old research is not folded');
assert(html.indexOf('id="selectionPerformanceMount"') < html.indexOf('id="advancedResearchDetails"'), 'advanced content is above performance');
assert(html.includes('id="nextday-research"') && html.includes('id="auxGrid"'), 'old research modules lost');
""")

    def test_switching_performance_hides_other_panels_and_resizes_existing_charts(self):
        _assert_node_contract(
            self, "({render: renderPrimaryMode, state: state, nodes: nodes})",
            r"""
const hidden = {};
function panel(name) { return {classList: {toggle: function (_key, value) { hidden[name] = value; }}}; }
__auxTest.nodes.todayDecisionView = panel('today');
__auxTest.nodes.selectionPerformanceView = panel('performance');
__auxTest.nodes.researchValidationView = panel('research');
__auxTest.nodes.primaryTabs = {querySelectorAll: function () { return ['today','performance'].map(function (mode) {
  return {getAttribute: function () { return mode; }, classList: {toggle: function () {}}, setAttribute: function () {}};
}); }};
let resized = 0;
window.requestAnimationFrame = function (callback) { callback(); };
__auxTest.state.chartInstance = {resize: function () { resized++; }};
__auxTest.state.primaryMode = 'performance';
__auxTest.render();
assert(hidden.today === true && hidden.performance === false, 'panel visibility is wrong');
assert(resized === 1, 'existing chart did not resize');
""")

    def test_report_mount_passes_bound_date_and_archive_prefix(self):
        _assert_node_contract(
            self, "({mount: initSelectionPerformance, nodes: nodes})",
            r"""
const mount = {innerHTML: ''};
__auxTest.nodes.selectionPerformanceMount = mount;
let called = null;
window.CHANLUN_BOOTSTRAP = {pageDate: '2026-10-09', dataBasePrefix: '../'};
window.ChanlunSelectionPerformance = {mount: function (target, options) { called = {target, options}; }};
__auxTest.mount();
assert(called && called.target === mount, 'module did not mount');
assert(called.options.pageDate === '2026-10-09', 'module did not bind report date');
assert(called.options.dataBasePrefix === '../', 'archive prefix lost');
""")

    def test_performance_fetch_waits_for_original_report_access_and_success(self):
        _assert_node_contract(
            self,
            "({run: initReportV2, state: state, configure: function () {"
            "syncViewport=function(){}; isMobileViewport=function(){return false;};"
            "buildAppShell=function(){nodes.selectionPerformanceMount={innerHTML:\"\"};};"
            "refreshReviewToolsMounts=function(){}; renderPrimaryMode=function(){};"
            "openNextdayResearchFromHash=function(){}; loadPrecloseAdvisory=function(){};"
            "resetTop10State=function(){}; renderTop10Control=function(){};"
            "loadLatestTop10Snapshot=function(){};"
            "normalizeWorkspace=function(){state.workspace={default_view:\"main\"};};"
            "renderHeader=function(){}; renderDecisionOverview=function(){};"
            "renderReviewToolPanels=function(){}; renderFundingMainlineStrip=function(){};"
            "renderMarketHotspot=function(){}; renderHistoricalReconstruction=function(){};"
            "renderWorkspaceTabs=function(){}; renderViewDescription=function(){};"
            "renderCurrentCandidateSelection=function(){return null;};"
            "renderAuxiliaryCenter=function(){}; loadNextdayResearch=function(){};"
            "initComparisonSummary=function(){}; renderGlobalError=function(){};"
            "}})",
            r"""
__auxTest.configure();
window.addEventListener = function () {};
window.location.search = '';
async function checkCase(label, options) {
  let mounted = 0;
  let derivedFetches = 0;
  let reportFetches = 0;
  window.REPORT_DATA = undefined;
  __auxTest.state.granted = false;
  window.CHANLUN_BOOTSTRAP = {
    pageDate: '2026-10-09', dataBasePrefix: options.prefix,
    accessControlEnabled: options.accessControlEnabled,
    accessKeyHash: 'valid-hash', isFileProtocol: !!options.file,
    inlineReportData: options.reportFailure ? null : {date: '2026-10-09'}
  };
  window.localStorage = {getItem: function () { return options.stored ? 'valid-hash' : ''; }};
  window.fetch = function (url) {
    if (url === 'derived-performance') {
      derivedFetches++;
      return Promise.resolve({ok: true});
    }
    reportFetches++;
    return Promise.resolve({ok: false});
  };
  window.ChanlunSelectionPerformance = {mount: function () {
    mounted++;
    window.fetch('derived-performance');
  }};
  __auxTest.run();
  await new Promise(function (resolve) { setTimeout(resolve, 0); });
  assert(mounted === options.expectedMount, label + ': mount count changed');
  assert(derivedFetches === options.expectedMount, label + ': derived fetch crossed access boundary');
  assert(reportFetches === (options.reportFailure ? 1 : 0), label + ': original report read changed');
}
(async function () {
  await checkCase('denied archive', {prefix: '../', accessControlEnabled: true, expectedMount: 0});
  await checkCase('denied root inline', {prefix: '', accessControlEnabled: true, expectedMount: 0});
  await checkCase('granted archive', {prefix: '../', accessControlEnabled: true, stored: true, expectedMount: 1});
  await checkCase('no access gate', {prefix: '', accessControlEnabled: false, expectedMount: 1});
  await checkCase('allowed file', {prefix: '../', accessControlEnabled: true, file: true, expectedMount: 1});
  await checkCase('report load fails', {prefix: '', accessControlEnabled: false, reportFailure: true, expectedMount: 0});
})().catch(function (error) { process.stderr.write(String(error.stack || error)); process.exitCode = 1; });
""",
        )


if __name__ == "__main__":
    unittest.main()
