"""RED contracts for truthful chart evidence and display-only projections."""

import copy
import unittest

from tests.test_auxiliary_frontend import _assert_node_contract
from chanlun.report_generator import (
    build_chart_annotations,
    build_chart_window,
    _serialize_picks,
)


def _chart_fixture_js(macd_expr="[0.2, -0.1, 0.3, -0.2, 0.4]"):
    """Build a small deterministic JS chart fixture.

    The chart intentionally has more than twenty bars so the default zoom
    window and all three synchronized series can be inspected independently.
    """

    return r"""
const dates = Array.from({ length: 25 }, function (_, index) {
  return 'D' + String(index + 1).padStart(2, '0');
});
const opens = dates.map(function (_, index) { return 10 + index * 0.1; });
const closes = opens.map(function (value, index) { return value + (index % 2 ? -0.04 : 0.06); });
const raw = {
  dates: dates,
  opens: opens,
  highs: opens.map(function (value) { return value + 0.2; }),
  lows: opens.map(function (value) { return value - 0.2; }),
  closes: closes,
  volumes: dates.map(function (_, index) { return 1000 + index * 10; }),
  macd_hist: MACD_EXPR,
  chart_annotations: { markLines: [], markPoints: [], labels: [] }
};
""".replace("MACD_EXPR", macd_expr)


def _set_up_chart_js():
    return r"""
let chartOption = null;
global.window.echarts = { init: function () { return {
  setOption: function (option) { chartOption = option; },
  dispose: function () {}, resize: function () {}
}; } };
globalThis.__auxTest.state.chartMount = { innerHTML: '' };
globalThis.__auxTest.state.chartAnnotationLane = null;
globalThis.__auxTest.state.isMobile = false;
globalThis.__auxTest.state.chartLayer = 'decision';
"""


def _serialization_pick():
    n = 60
    closes = [50.0 + index * 0.1 for index in range(n)]
    return {
        "code": "600519",
        "name": "测试",
        "best_buy_point": {
            "type": "底背驰候选",
            "tier": "candidate",
            "index": 45,
            "price": 54.5,
        },
        "pivots": {"ZD": 52.0, "ZG": 55.0},
        "dates": [f"2026-01-{index + 1:02d}" for index in range(n)],
        "closes": closes,
        "opens": [value - 0.1 for value in closes],
        "highs": [value + 0.2 for value in closes],
        "lows": [value - 0.2 for value in closes],
        "volumes": [1000 + index for index in range(n)],
        "macd_hist": [round((index - 30) / 100, 4) for index in range(n)],
        "buy_points": [],
        "reference_buy_points": [],
        "blocked_buy_points": [],
        "buy_points_30min": [],
    }


class TestRecommendationChartEvidence(unittest.TestCase):
    def test_missing_macd_remains_null_and_is_not_drawn_as_zero(self):
        _assert_node_contract(
            self,
            "({ chart: renderChart, state: state })",
            _set_up_chart_js()
            + _chart_fixture_js("[]")
            + r"""
const before = JSON.stringify(raw);
globalThis.__auxTest.chart(raw, {});
const macd = chartOption.series.filter(function (series) { return series.name === 'MACD'; })[0];
assert(macd, 'MACD series is missing');
assert(macd.data.length === raw.dates.length, 'MACD series lost alignment with K lines');
assert(macd.data.every(function (value) { return value === null; }), 'missing MACD was drawn as placeholder zero');
assert(JSON.stringify(raw) === before, 'display preparation mutated formal raw chart payload');
""",
        )

    def test_missing_macd_is_null_before_echarts_option_is_built(self):
        _assert_node_contract(
            self,
            "({ chart: renderChart, state: state })",
            _set_up_chart_js()
            + _chart_fixture_js("Array(25).fill(0)")
            + r"""
globalThis.__auxTest.chart(raw, {});
const macd = chartOption.series.filter(function (series) { return series.name === 'MACD'; })[0];
assert(macd.data.every(function (value) { return value === null; }), 'zero-only MACD placeholders reached ECharts as evidence');
assert(!macd.data.some(function (value) { return value === 0; }), 'ECharts option contains a fabricated zero MACD value');
""",
        )

    def test_formal_serialized_macd_and_chart_annotations_remain_unchanged(self):
        pick = _serialization_pick()
        before = copy.deepcopy(pick)
        slice_start, slice_end = build_chart_window(pick)
        expected_macd = pick["macd_hist"][slice_start:slice_end]
        expected_annotations = build_chart_annotations(
            pick,
            slice_start,
            pick["dates"][slice_start:slice_end],
            pick["closes"][slice_start:slice_end],
        )

        serialized = _serialize_picks([pick])[0]

        self.assertEqual(serialized["macd_hist"], expected_macd)
        self.assertEqual(serialized["chart_annotations"], expected_annotations)
        self.assertEqual(pick, before)

    def test_single_real_zg_or_zd_structure_line_is_preserved(self):
        _assert_node_contract(
            self,
            "({ chart: renderChart, state: state })",
            _set_up_chart_js()
            + _chart_fixture_js("[0.2, -0.1, 0.3, -0.2, 0.4]")
            + r"""
function structureLines(pivot) {
  const one = Object.assign({}, raw, {
    pivot_zg: pivot.zg,
    pivot_zd: pivot.zd,
    structure_annotations: { source: 'formal-pivot' },
    chart_annotations: { markLines: [], markPoints: [], labels: [] }
  });
  globalThis.__auxTest.state.chartLayer = 'structure';
  globalThis.__auxTest.chart(one, {});
  return chartOption.series.filter(function (series) { return series.name === 'K线'; })[0].markLine.data;
}
const onlyZg = structureLines({ zg: 12.4, zd: null });
assert(onlyZg.length === 1 && onlyZg[0].name === 'ZG', 'single real ZG structure line was dropped');
assert(onlyZg[0].yAxis === 12.4, 'ZG line changed its true y value');
const onlyZd = structureLines({ zg: null, zd: 10.8 });
assert(onlyZd.length === 1 && onlyZd[0].name === 'ZD', 'single real ZD structure line was dropped');
assert(onlyZd[0].yAxis === 10.8, 'ZD line changed its true y value');
""",
        )

    def test_chart_never_draws_zero_price_line_for_missing_evidence(self):
        _assert_node_contract(
            self,
            "({ chart: renderChart, state: state })",
            _set_up_chart_js()
            + _chart_fixture_js("[0.2, -0.1, 0.3, -0.2, 0.4]")
            + r"""
raw.chart_annotations.markLines = [
  { name: '现价', yAxis: 0 },
  { name: '参考价', yAxis: null },
  { name: '失效位', yAxis: 0 }
];
raw.formal_decision_contract = { invalidation_price: 0, pressure_price: null };
globalThis.__auxTest.chart(raw, {});
const lines = chartOption.series.filter(function (series) { return series.name === 'K线'; })[0].markLine.data;
assert(!lines.some(function (line) { return line.yAxis === 0; }), 'missing price evidence produced a y=0 line');
""",
        )

    def test_price_label_collision_keeps_all_real_values_and_kinds(self):
        _assert_node_contract(
            self,
            "({ select: selectPersistentPriceLabels })",
            r"""
const labels = [
  { kind: 'reference', value: 10.00, label: '参考价' },
  { kind: 'current', value: 10.03, label: '现价' },
  { kind: 'pressure', value: 10.05, label: '压力位' },
  { kind: 'invalidation', value: 9.20, label: '失效位' }
];
const before = JSON.stringify(labels);
const selected = globalThis.__auxTest.select(labels);
const merged = selected.filter(function (item) {
  return item.kinds.includes('reference') && item.kinds.includes('current');
})[0];
assert(merged, 'nearby reference/current prices were not merged into one lane');
assert(merged.merged === true, 'collision merge was not marked');
assert(merged.values.includes(10.00) && merged.values.includes(10.03), 'merged lane lost true price values');
assert(merged.kinds.includes('reference') && merged.kinds.includes('current'), 'merged lane lost true price kinds');
assert(JSON.stringify(labels) === before, 'price collision handling mutated formal annotations');
""",
        )

    def test_chart_reuses_existing_signal_annotation_lane(self):
        _assert_node_contract(
            self,
            "({ chart: renderChart, state: state })",
            _set_up_chart_js()
            + r"""
let hidden = null;
globalThis.__auxTest.state.chartAnnotationLane = {
  innerHTML: '',
  classList: { toggle: function (_name, value) { hidden = value; } }
};
const raw = {
  dates: ['D01', 'D02', 'D03', 'D04'],
  opens: [10, 10.2, 10.1, 10.4],
  highs: [10.3, 10.4, 10.5, 10.8],
  lows: [9.8, 10.0, 9.9, 10.2],
  closes: [10.2, 10.1, 10.4, 10.7],
  volumes: [100, 110, 120, 130],
  macd_hist: [0.1, 0.2, 0.3, 0.4],
  chart_annotations: {
    markPoints: [
      { coord: ['D02', 10.1], barIndex: 1, name: '底背驰候选' },
      { coord: ['D04', 10.7], barIndex: 3, name: '启动日' }
    ],
    markLines: [],
    labels: ['确认日: D04']
  }
};
globalThis.__auxTest.chart(raw, {});
const lane = globalThis.__auxTest.state.chartAnnotationLane.innerHTML;
assert(lane.includes('chart-signal-list'), 'chart did not reuse the signal annotation lane');
assert(lane.includes('chart-signal-item'), 'signal lane did not receive chart actions');
assert(lane.includes('确认日: D04'), 'signal lane lost annotation labels');
assert(hidden === false, 'signal annotation lane stayed hidden despite evidence');
""",
        )

    def test_chart_keeps_three_panels_volume_and_latest_twenty_bar_default(self):
        _assert_node_contract(
            self,
            "({ chart: renderChart, state: state })",
            _set_up_chart_js()
            + _chart_fixture_js("dates.map(function (_, index) { return index / 10; })")
            + r"""
globalThis.__auxTest.chart(raw, {});
assert(chartOption.grid.length === 3, 'three chart panels were collapsed');
const names = chartOption.series.map(function (series) { return series.name; });
assert(names.includes('K线') && names.includes('成交量') && names.includes('MACD'), 'volume or MACD panel disappeared');
const volume = chartOption.series.filter(function (series) { return series.name === '成交量'; })[0];
assert(volume.data.length === raw.dates.length, 'volume series lost K-line alignment');
assert(volume.data[24] === 1240, 'volume evidence changed before rendering');
chartOption.dataZoom.forEach(function (zoom) {
  assert(zoom.startValue === 'D06' && zoom.endValue === 'D25', 'default view is not the latest twenty bars');
});
""",
        )


if __name__ == "__main__":
    unittest.main()
