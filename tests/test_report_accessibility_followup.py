"""Focused accessibility and interaction contracts for report-v2 assets."""

import unittest

from tests.test_auxiliary_frontend import CSS, JS, _assert_node_contract


class ReportAccessibilityFollowupTests(unittest.TestCase):

    def test_primary_mode_tabs_roving_keyboard_and_labeled_panels(self):
        _assert_node_contract(
            self,
            "({ build: buildAppShell, state: state })",
            r"""
const listeners = {};
function makeButton(mode) {
  const attrs = { 'data-primary-mode': mode };
  return {
    focused: false,
    getAttribute: function (name) { return attrs[name] || ''; },
    setAttribute: function (name, value) { attrs[name] = String(value); },
    classList: { toggle: function () {} },
    closest: function () { return this; },
    focus: function () { this.focused = true; }
  };
}
const buttons = [makeButton('today'), makeButton('research')];
const tabs = {
  addEventListener: function (name, handler) { listeners[name] = handler; },
  querySelectorAll: function () { return buttons; }
};
const app = {
  innerHTML: '',
  querySelector: function (selector) { return selector === '.primary-mode-tabs' ? tabs : null; }
};
global.document.getElementById = function (id) { return id === 'app' ? app : null; };
globalThis.__auxTest.build();
assert(app.innerHTML.includes('id="primary-mode-tab-today"'), 'today tab lacks a stable accessible id');
assert(app.innerHTML.includes('role="tabpanel" aria-labelledby="primary-mode-tab-today"'), 'today panel lacks its tab relationship');
assert(app.innerHTML.includes('role="tabpanel" aria-labelledby="primary-mode-tab-research"'), 'research panel lacks its tab relationship');
assert(typeof listeners.keydown === 'function', 'primary tabs lack keyboard navigation');
let prevented = false;
listeners.keydown({ key: 'End', target: buttons[0], preventDefault: function () { prevented = true; } });
assert(prevented, 'handled primary-tab key did not prevent page scrolling');
assert(globalThis.__auxTest.state.primaryMode === 'research', 'End did not activate the last primary tab');
assert(buttons[1].focused, 'roving focus did not move to the activated primary tab');
listeners.keydown({ key: 'ArrowRight', target: buttons[1], preventDefault: function () {} });
assert(globalThis.__auxTest.state.primaryMode === 'today', 'ArrowRight did not wrap primary-tab focus');
""",
        )

    def test_drawer_inerts_every_background_sibling_and_restores_exact_state(self):
        _assert_node_contract(
            self,
            "({ inert: setDrawerBackgroundInert, state: state, nodes: nodes })",
            r"""
function region(initialAria, initialInertAttribute, initialInertValue) {
  const attrs = {};
  if (initialAria !== null) attrs['aria-hidden'] = initialAria;
  if (initialInertAttribute !== null) attrs.inert = initialInertAttribute;
  return {
    inert: initialInertValue,
    setAttribute: function (name, value) { attrs[name] = String(value); },
    removeAttribute: function (name) { delete attrs[name]; },
    hasAttribute: function (name) { return Object.prototype.hasOwnProperty.call(attrs, name); },
    getAttribute: function (name) { return this.hasAttribute(name) ? attrs[name] : null; }
  };
}
const preserved = region('false', 'legacy', true);
const clean = region(null, null, false);
const drawer = region('true', null, false);
globalThis.__auxTest.nodes.drawer = drawer;
globalThis.__auxTest.nodes.shell = {
  children: [preserved, drawer, clean],
  querySelectorAll: function () { return [preserved, clean]; }
};
globalThis.__auxTest.inert(true);
assert(preserved.getAttribute('aria-hidden') === 'true' && clean.getAttribute('aria-hidden') === 'true', 'not every drawer sibling became aria-hidden');
assert(preserved.hasAttribute('inert') && clean.hasAttribute('inert'), 'not every drawer sibling became inert');
assert(drawer.getAttribute('aria-hidden') === 'true' && !drawer.hasAttribute('inert'), 'drawer itself was incorrectly inerted');
globalThis.__auxTest.inert(false);
assert(preserved.getAttribute('aria-hidden') === 'false', 'pre-existing aria-hidden value was not restored');
assert(preserved.getAttribute('inert') === 'legacy' && preserved.inert === true, 'pre-existing inert state was not restored');
assert(!clean.hasAttribute('aria-hidden') && !clean.hasAttribute('inert') && clean.inert === false, 'clean sibling did not return to its exact prior state');
""",
        )

    def test_main_rise_subsections_use_h4_heading_level(self):
        start = JS.index("function renderMainRiseClue")
        end = JS.index("function historicalMetricText", start)
        renderer = JS[start:end]
        self.assertIn("'<section><h4>'", renderer)
        self.assertNotIn("<h5>", renderer)
        self.assertIn(".recommendation-main-rise-sides h4", CSS)
        self.assertNotIn(".recommendation-main-rise-sides h5", CSS)

    def test_chart_buttons_have_hover_and_mobile_controls_contain_touch_scroll(self):
        self.assertIn(".chart-layer-switcher button:hover", CSS)
        drawer_start = CSS.index(".mobile-drawer-panel")
        drawer_end = CSS.index(".mobile-drawer-toolbar", drawer_start)
        self.assertIn("overscroll-behavior: contain", CSS[drawer_start:drawer_end])
        self.assertIn("button {\n  touch-action: manipulation;", CSS)

    def test_reduced_motion_disables_nonessential_transitions(self):
        self.assertIn("@media (prefers-reduced-motion: reduce)", CSS)
        reduced = CSS[CSS.index("@media (prefers-reduced-motion: reduce)"):]
        self.assertIn("transition: none !important", reduced)
        self.assertIn("animation: none !important", reduced)

    def test_comparison_view_cards_sync_aria_pressed_with_active_view(self):
        start = JS.index("function renderComparisonResult")
        end = JS.index("function renderComparisonTable", start)
        renderer = JS[start:end]
        self.assertIn('aria-pressed="false"', renderer)
        self.assertIn("button.setAttribute('aria-pressed', active ? 'true' : 'false')", renderer)

    def test_watchlist_add_code_has_an_accessible_name(self):
        start = JS.index("function renderWatchlistManager")
        end = JS.index("function loadWatchlistManagerConfig", start)
        renderer = JS[start:end]
        self.assertIn('data-watch-add-code', renderer)
        self.assertIn('aria-label="新增股票代码"', renderer)

    def test_comparison_summary_announces_async_updates(self):
        start = JS.index("function initComparisonSummary")
        end = JS.index("function renderComparisonSummaryResults", start)
        renderer = JS[start:end]
        self.assertIn('class="comparison-summary-body" role="status" aria-live="polite"', renderer)

    def test_app_shell_has_skip_link_and_main_landmark_without_layout_wrapper(self):
        start = JS.index("function buildAppShell")
        end = JS.index("function renderPrimaryMode", start)
        shell = JS[start:end]
        self.assertIn('class="skip-link" href="#reportShell"', shell)
        self.assertIn('<main class="report-shell" id="reportShell" tabindex="-1">', shell)
        self.assertIn("</main>'", shell)
        self.assertIn(".skip-link", CSS)


if __name__ == "__main__":
    unittest.main()
