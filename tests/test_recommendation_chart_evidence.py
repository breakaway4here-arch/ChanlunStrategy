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
  volume_units: dates.map(function () { return 'hands'; }),
  volume_raw_units: dates.map(function () { return 'hands'; }),
  volume_sources: dates.map(function () { return 'fixture'; }),
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
    def test_conflicting_projected_pivot_is_not_drawn_from_raw_fallback(self):
        _assert_node_contract(
            self,
            "({ structure: selectStructureChartLines })",
            r"""
const raw = { pivot_zg: 20.5, pivot_zd: 17.8, pivots: { ZG: 20.5, ZD: 17.8 } };
const projected = {
  pivots: {
    status: 'conflict', available: ['ZD'], ZG: null, ZD: 17.8,
    field_sources: { ZD: 'serialized.pivot_zd' }
  }
};
const lines = globalThis.__auxTest.structure(
  [{ name: 'ZG', yAxis: 20.5 }, { name: 'ZD', yAxis: 17.8 }],
  raw,
  projected
);
assert(!lines.some(function (line) { return line.name === 'ZG'; }),
  'conflicting ZG leaked back from raw chart annotations');
assert(lines.length === 1 && lines[0].name === 'ZD' && lines[0].yAxis === 17.8,
  'non-conflicting ZD was not preserved');
""",
        )

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
assert(selected.length === 4, 'label collision removed one or more true price lines');
const current = selected.filter(function (item) { return item.kind === 'current'; })[0];
const reference = selected.filter(function (item) { return item.kind === 'reference'; })[0];
const pressure = selected.filter(function (item) { return item.kind === 'pressure'; })[0];
assert(current && current.merged === true, 'nearby prices were not merged into one right-side label lane');
assert(current.labelVisible === true && reference.labelVisible === false && pressure.labelVisible === false, 'only the label lane should be merged');
assert(current.labelEntries.some(function (entry) { return entry.kind === 'reference' && entry.value === 10.00; })
  && current.labelEntries.some(function (entry) { return entry.kind === 'current' && entry.value === 10.03; })
  && current.labelEntries.some(function (entry) { return entry.kind === 'pressure' && entry.value === 10.05; }), 'merged label lane lost true values or kinds');
assert(reference.value === 10.00 && current.value === 10.03 && pressure.value === 10.05, 'real y values changed during label collision handling');
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
const freshConfirmedEvidence = {
  code: '600001',
  summary: { code: '600001' },
  sublevel_30m: {
    status: 'available',
    confirmation_status: 'confirmed',
    confirmed: true,
    stale: false,
    is_final: true
  }
};
window.CHANLUN_BOOTSTRAP = {
  pageDate: '2026-08-28',
  recommendationEvidence: {
    schema_version: 1,
    report_date: '2026-08-28',
    views: { main: [freshConfirmedEvidence] }
  }
};
globalThis.__auxTest.state.data = { date: '2026-08-28' };
globalThis.__auxTest.state.currentView = 'main';
globalThis.__auxTest.chart(raw, freshConfirmedEvidence);
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

    def test_chart_keeps_only_row_aligned_canonical_volume_evidence(self):
        _assert_node_contract(
            self,
            "({ chart: renderChart, state: state })",
            _set_up_chart_js()
            + _chart_fixture_js("dates.map(function (_, index) { return index / 10; })")
            + r"""
raw.volume_units[3] = 'unknown';
raw.volume_raw_units[7] = 'unknown';
raw.volume_sources[11] = '';
const beforeDates = JSON.stringify(raw.dates);
const beforeOhlc = JSON.stringify([raw.opens, raw.highs, raw.lows, raw.closes]);
globalThis.__auxTest.chart(raw, {});
const volume = chartOption.series.filter(function (series) { return series.name === '成交量'; })[0];
assert(volume.data.length === raw.dates.length, 'volume projection reindexed the chart');
assert(volume.data[2] === 1020 && volume.data[4] === 1040, 'known adjacent bars changed');
assert(volume.data[3] === null && volume.data[7] === null && volume.data[11] === null,
  'mixed or missing provenance was plotted as comparable volume');
assert(!volume.data.some(function (value, index) {
  return [3, 7, 11].includes(index) && value === 0;
}), 'unproven volume became a zero bar');
assert(JSON.stringify(raw.dates) === beforeDates, 'dates changed during quantity projection');
assert(JSON.stringify([raw.opens, raw.highs, raw.lows, raw.closes]) === beforeOhlc,
  'OHLC changed during quantity projection');
""",
        )

    def test_chart_with_all_unproven_volume_keeps_price_chart_and_explains_gap(self):
        _assert_node_contract(
            self,
            "({ chart: renderChart, state: state })",
            _set_up_chart_js()
            + _chart_fixture_js("dates.map(function (_, index) { return index / 10; })")
            + r"""
raw.volume_units = Array(raw.dates.length).fill('unknown');
globalThis.__auxTest.state.chartLayerSwitcher = {
  innerHTML: '', querySelectorAll: function () { return []; }
};
globalThis.__auxTest.chart(raw, {});
const candle = chartOption.series.filter(function (series) { return series.name === 'K线'; })[0];
const volume = chartOption.series.filter(function (series) { return series.name === '成交量'; })[0];
assert(candle.data.length === raw.dates.length, 'unproven volume removed the price chart');
assert(volume.data.every(function (value) { return value === null; }), 'unproven volume was plotted');
assert(globalThis.__auxTest.state.chartLayerSwitcher.innerHTML.includes('成交量证据未核验'),
  'missing quantity evidence was not explained');
""",
        )

    def test_all_missing_volume_replaces_empty_volume_grid_with_compact_state(self):
        _assert_node_contract(
            self,
            "({ chart: renderChart, state: state })",
            _set_up_chart_js()
            + _chart_fixture_js("dates.map(function (_, index) { return index / 10; })")
            + r"""
raw.volume_units = Array(raw.dates.length).fill('unknown');
raw.volume_raw_units = Array(raw.dates.length).fill('unknown');
raw.volume_sources = Array(raw.dates.length).fill('');
globalThis.__auxTest.state.chartLayerSwitcher = {
  innerHTML: '', querySelectorAll: function () { return []; }
};
globalThis.__auxTest.chart(raw, {});
assert(chartOption.grid.length === 2, 'all-missing volume kept an empty chart grid');
const volume = chartOption.series.filter(function (series) { return series.name === '成交量'; })[0];
assert(volume && volume.show === false, 'missing volume was not represented as a hidden series');
const status = globalThis.__auxTest.state.chartLayerSwitcher.innerHTML;
assert(status.includes('成交量证据未核验') && status.includes('单位') && status.includes('来源'),
  'missing volume state did not preserve unit/source reasons');
""",
        )

    def test_chart_preserves_zoom_when_switching_layers_for_same_snapshot(self):
        _assert_node_contract(
            self,
            "({ chart: renderChart, state: state })",
            r"""
let initCount = 0;
let disposeCount = 0;
let chartOption = null;
global.window.echarts = { init: function () {
  initCount += 1;
  return {
    setOption: function (option) { chartOption = option; },
    getOption: function () { return { dataZoom: chartOption && chartOption.dataZoom }; },
    dispose: function () { disposeCount += 1; }, resize: function () {}
  };
} };
globalThis.__auxTest.state.chartMount = { innerHTML: '' };
globalThis.__auxTest.state.chartAnnotationLane = null;
globalThis.__auxTest.state.chartLayerSwitcher = null;
globalThis.__auxTest.state.chartWindowMode = '20';
const raw = {
  code: '600001', snapshot_id: 'snap-a',
  dates: Array.from({ length: 25 }, function (_, index) { return 'D' + String(index + 1).padStart(2, '0'); }),
  opens: Array.from({ length: 25 }, function (_, index) { return 10 + index * 0.1; }),
  highs: Array.from({ length: 25 }, function (_, index) { return 10.2 + index * 0.1; }),
  lows: Array.from({ length: 25 }, function (_, index) { return 9.8 + index * 0.1; }),
  closes: Array.from({ length: 25 }, function (_, index) { return 10.1 + index * 0.1; }),
  volumes: Array(25).fill(100), volume_units: Array(25).fill('hands'),
  volume_raw_units: Array(25).fill('hands'), volume_sources: Array(25).fill('fixture'),
  chart_annotations: { markLines: [], markPoints: [], labels: [] }, pivot_zg: 12.4
};
globalThis.__auxTest.chart(raw, { code: '600001', snapshot_id: 'snap-a' });
chartOption.dataZoom[0].startValue = 'D10';
chartOption.dataZoom[0].endValue = 'D25';
globalThis.__auxTest.state.chartLayer = 'structure';
globalThis.__auxTest.chart(raw, { code: '600001', snapshot_id: 'snap-a' });
assert(initCount === 1 && disposeCount === 0, 'same snapshot layer switch rebuilt the chart instance');
assert(chartOption.dataZoom[0].startValue === 'D10' && chartOption.dataZoom[0].endValue === 'D25',
  'same snapshot layer switch reset the visible date window');
""",
        )

    def test_chart_does_not_reuse_zoom_for_same_day_different_snapshot(self):
        _assert_node_contract(
            self,
            "({ chart: renderChart, state: state })",
            r"""
let initCount = 0;
let disposeCount = 0;
let chartOption = null;
global.window.echarts = { init: function () {
  initCount += 1;
  return {
    setOption: function (option) { chartOption = option; },
    getOption: function () { return { dataZoom: chartOption && chartOption.dataZoom }; },
    dispose: function () { disposeCount += 1; }, resize: function () {}
  };
} };
globalThis.__auxTest.state.chartMount = { innerHTML: '' };
globalThis.__auxTest.state.chartAnnotationLane = null;
globalThis.__auxTest.state.chartLayerSwitcher = null;
const raw = {
  code: '600001', dates: ['D01', 'D02', 'D03', 'D04', 'D05'],
  opens: [10, 10.1, 10.2, 10.3, 10.4], highs: [10.2, 10.3, 10.4, 10.5, 10.6],
  lows: [9.8, 9.9, 10, 10.1, 10.2], closes: [10.1, 10.2, 10.3, 10.4, 10.5],
  volumes: [100, 100, 100, 100, 100], volume_units: ['hands', 'hands', 'hands', 'hands', 'hands'],
  volume_raw_units: ['hands', 'hands', 'hands', 'hands', 'hands'],
  volume_sources: ['snapshot-a', 'snapshot-a', 'snapshot-a', 'snapshot-a', 'snapshot-a'],
  chart_annotations: { markLines: [], markPoints: [], labels: [] }
};
globalThis.__auxTest.chart(Object.assign({}, raw, { snapshot_id: 'snapshot-a' }), {
  code: '600001', workbench_item: { snapshot_id: 'snapshot-a', payload_hash: 'hash-a', phase: 'formal', version: 'v1' }
});
chartOption.dataZoom[0].startValue = 'D02';
globalThis.__auxTest.chart(Object.assign({}, raw, { snapshot_id: 'snapshot-b' }), {
  code: '600001', workbench_item: { snapshot_id: 'snapshot-b', payload_hash: 'hash-b', phase: 'formal', version: 'v2' }
});
assert(initCount === 2 && disposeCount === 1, 'same-day snapshot change reused the old ECharts instance');
assert(chartOption.dataZoom[0].startValue === 'D01', 'same-day snapshot change reused the old date window');
""",
        )

    def test_chart_keeps_window_when_mobile_mount_is_recreated_for_same_snapshot(self):
        _assert_node_contract(
            self,
            "({ chart: renderChart, state: state })",
            r"""
let chartOption = null;
global.window.echarts = { init: function () { return {
  setOption: function (option) { chartOption = option; },
  getOption: function () { return { dataZoom: chartOption && chartOption.dataZoom }; },
  dispose: function () {}, resize: function () {}
}; } };
globalThis.__auxTest.state.chartMount = { innerHTML: '' };
globalThis.__auxTest.state.chartAnnotationLane = null;
globalThis.__auxTest.state.chartLayerSwitcher = null;
const raw = {
  code: '600001', snapshot_id: 'snap-a', dates: ['D01', 'D02', 'D03', 'D04', 'D05'],
  opens: [10, 10.1, 10.2, 10.3, 10.4], highs: [10.2, 10.3, 10.4, 10.5, 10.6],
  lows: [9.8, 9.9, 10, 10.1, 10.2], closes: [10.1, 10.2, 10.3, 10.4, 10.5],
  volumes: [100, 100, 100, 100, 100], volume_units: ['hands', 'hands', 'hands', 'hands', 'hands'],
  volume_raw_units: ['hands', 'hands', 'hands', 'hands', 'hands'],
  volume_sources: ['fixture', 'fixture', 'fixture', 'fixture', 'fixture'],
  chart_annotations: { markLines: [], markPoints: [], labels: [] }
};
globalThis.__auxTest.chart(raw, {});
chartOption.dataZoom[0].startValue = 'D03';
globalThis.__auxTest.state.chartZoomWindow = { startValue: 'D03', endValue: 'D05' };
globalThis.__auxTest.state.chartInstance.dispose();
globalThis.__auxTest.state.chartInstance = null;
globalThis.__auxTest.state.chartMount = { innerHTML: '' };
globalThis.__auxTest.chart(raw, {});
assert(chartOption.dataZoom[0].startValue === 'D03', 'recreated mobile chart lost the saved visible date window');
""",
        )

    def test_chart_rebuilds_when_same_snapshot_points_to_a_new_mount(self):
        _assert_node_contract(
            self,
            "({ chart: renderChart, state: state })",
            r"""
let initCount = 0;
let disposeCount = 0;
let chartOption = null;
global.window.echarts = { init: function (mount) {
  initCount += 1;
  return {
    getDom: function () { return mount; },
    setOption: function (option) { chartOption = option; },
    getOption: function () { return { dataZoom: chartOption && chartOption.dataZoom }; },
    dispose: function () { disposeCount += 1; }, resize: function () {}
  };
} };
const mountA = { innerHTML: '', isConnected: true };
const mountB = { innerHTML: '', isConnected: true };
globalThis.__auxTest.state.chartMount = mountA;
globalThis.__auxTest.state.chartAnnotationLane = null;
globalThis.__auxTest.state.chartLayerSwitcher = null;
const raw = {
  code: '600001', snapshot_id: 'snap-a', dates: ['D01', 'D02', 'D03', 'D04', 'D05'],
  opens: [10, 10.1, 10.2, 10.3, 10.4], highs: [10.2, 10.3, 10.4, 10.5, 10.6],
  lows: [9.8, 9.9, 10, 10.1, 10.2], closes: [10.1, 10.2, 10.3, 10.4, 10.5],
  volumes: [100, 100, 100, 100, 100], volume_units: ['hands', 'hands', 'hands', 'hands', 'hands'],
  volume_raw_units: ['hands', 'hands', 'hands', 'hands', 'hands'],
  volume_sources: ['fixture', 'fixture', 'fixture', 'fixture', 'fixture'],
  chart_annotations: { markLines: [], markPoints: [], labels: [] }
};
globalThis.__auxTest.chart(raw, {});
chartOption.dataZoom[0].startValue = 'D03';
globalThis.__auxTest.state.chartMount = mountB;
globalThis.__auxTest.chart(raw, {});
assert(initCount === 2 && disposeCount === 1, 'same snapshot new mount reused the detached ECharts instance');
assert(globalThis.__auxTest.state.chartInstance.getDom() === mountB,
  'rebuilt chart did not attach to the current mount');
assert(chartOption.dataZoom[0].startValue === 'D03', 'new mount lost the saved visible date window');
""",
        )

    def test_mixed_volume_units_and_sources_are_not_reported_as_one_provenance(self):
        _assert_node_contract(
            self,
            "({ chart: renderChart, state: state })",
            _set_up_chart_js()
            + _chart_fixture_js("dates.map(function (_, index) { return index / 10; })")
            + r"""
raw.volume_units[2] = 'shares';
raw.volume_sources[5] = 'other-source';
globalThis.__auxTest.state.chartLayerSwitcher = {
  innerHTML: '', querySelectorAll: function () { return []; }
};
globalThis.__auxTest.chart(raw, {});
const status = globalThis.__auxTest.state.chartLayerSwitcher.innerHTML;
assert(status.includes('单位混用') && status.includes('来源冲突'),
  'mixed volume metadata was collapsed into one trusted unit/source');
assert(status.includes('混合：hands') && status.includes('shares')
  && status.includes('混合：fixture') && status.includes('other-source'),
  'mixed volume values were not retained in the visible evidence status');
""",
        )

    def test_chart_overlays_keep_decision_layer_and_add_verified_structure_and_trend(self):
        _assert_node_contract(
            self,
            "({ chart: renderChart, state: state })",
            _set_up_chart_js()
            + _chart_fixture_js("dates.map(function (_, index) { return index / 10; })")
            + r"""
raw.code = '600001';
raw.pivot_zg = 12.4;
raw.pivot_zd = 10.8;
raw.ema5 = raw.closes.map(function (value) { return value + 0.1; });
raw.ema20 = raw.closes.map(function (value) { return value - 0.1; });
globalThis.__auxTest.state.chartLayer = 'decision';
globalThis.__auxTest.state.chartOverlays = { structure: true, trend: true };
globalThis.__auxTest.chart(raw, { code: '600001', snapshot_id: 'snap-a' });
const candle = chartOption.series.filter(function (series) { return series.name === 'K线'; })[0];
assert(candle.markLine.data.some(function (line) { return line.name === 'ZG'; }),
  'structure overlay did not preserve verified ZG');
assert(candle.markLine.data.some(function (line) { return line.name === 'ZD'; }),
  'structure overlay did not preserve verified ZD');
assert(chartOption.series.some(function (series) { return series.name === 'EMA5'; }),
  'trend overlay did not add verified EMA5');
assert(chartOption.series.some(function (series) { return series.name === 'K线'; }),
  'decision layer disappeared when overlays were enabled');
""",
        )

    def test_trend_overlay_keeps_ma10_distinct_and_shows_chart_ma_declaration(self):
        _assert_node_contract(
            self,
            "({ chart: renderChart, state: state })",
            _set_up_chart_js()
            + _chart_fixture_js("dates.map(function (_, index) { return index / 10; })")
            + r"""
raw.ema5 = raw.closes.map(function (value) { return value + 0.1; });
raw.ma5 = raw.closes.map(function (value) { return value + 0.2; });
raw.ma10 = raw.closes.map(function (value) { return value + 0.3; });
raw.ema20 = raw.closes.map(function (value) { return value - 0.1; });
raw.chart_ma = {
  ma5: { source: 'derived', derived: true, algorithm: 'SMA', window: 5, price_basis: 'qfq', as_of: 'D25' },
  ma10: { source: 'derived', derived: true, algorithm: 'SMA', window: 10, price_basis: 'qfq', as_of: 'D25' }
};
globalThis.__auxTest.state.chartLayer = 'trend';
globalThis.__auxTest.state.chartLayerSwitcher = { innerHTML: '', querySelectorAll: function () { return []; } };
globalThis.__auxTest.chart(raw, {});
assert(chartOption.series.some(function (series) { return series.name === 'MA10'; }),
  'MA10 was omitted or aliased to another moving average');
assert(!chartOption.series.some(function (series) { return series.name === 'MA10' && series.name === 'MA5'; }),
  'MA10 was merged with MA5');
const controls = globalThis.__auxTest.state.chartLayerSwitcher.innerHTML;
assert(controls.includes('MA5') && controls.includes('MA10') && controls.includes('SMA')
  && controls.includes('窗口 10') && controls.includes('价基 qfq') && controls.includes('截至 D25'),
  'chart_ma declaration did not disclose derived algorithm/window/basis/as-of');
""",
        )

    def test_chart_window_tools_use_real_lengths_and_expose_signal_locator(self):
        _assert_node_contract(
            self,
            "({ chart: renderChart, state: state })",
            _set_up_chart_js()
            + _chart_fixture_js("dates.map(function (_, index) { return index / 10; })")
            + r"""
raw.chart_annotations.markPoints = [
  { coord: ['D05', 10.5], name: '旧信号' },
  { coord: ['D22', 12.2], name: '最新信号' }
];
globalThis.__auxTest.state.chartLayerSwitcher = {
  innerHTML: '', querySelectorAll: function () { return []; }
};
globalThis.__auxTest.state.chartWindowMode = '60';
globalThis.__auxTest.chart(raw, {});
assert(chartOption.dataZoom[0].startValue === 'D01' && chartOption.dataZoom[0].endValue === 'D25',
  '60-bar window exceeded the real 25-bar input');
const controls = globalThis.__auxTest.state.chartLayerSwitcher.innerHTML;
assert(controls.includes('最近20根') && controls.includes('最近60根') && controls.includes('全部'),
  'chart window controls are missing');
assert(controls.includes('定位信号') && controls.includes('重置'),
  'signal locator or reset control is missing');
globalThis.__auxTest.state.chartWindowMode = 'signal';
globalThis.__auxTest.chart(raw, {});
assert(chartOption.dataZoom[0].startValue === 'D12' && chartOption.dataZoom[0].endValue === 'D25',
  'signal locator did not focus the latest real signal window');
""",
        )

    def test_structure_geometry_requires_serialized_dates_and_endpoints(self):
        _assert_node_contract(
            self,
            "({ chart: renderChart, state: state })",
            _set_up_chart_js()
            + _chart_fixture_js("dates.map(function (_, index) { return index / 10; })")
            + r"""
raw.structure_annotations = {
  pivots: [{ ZG: 12.4, ZD: 10.8, start_date: 'D03', end_date: 'D12' }],
  segments: [{ start_date: 'D04', start_price: 10.8, end_date: 'D09', end_price: 12.4,
    source: 'serialized.segment' }]
};
globalThis.__auxTest.state.chartLayer = 'structure';
globalThis.__auxTest.chart(raw, {});
const candle = chartOption.series.filter(function (series) { return series.name === 'K线'; })[0];
assert(candle.markArea && candle.markArea.data.length === 1,
  'verified pivot dates did not produce one shallow structure area');
const area = candle.markArea.data[0];
assert(area[0].xAxis === 'D03' && area[1].xAxis === 'D12'
  && area[0].yAxis === 12.4 && area[1].yAxis === 10.8,
  'structure area changed serialized boundaries');
assert(candle.markLine.data.some(function (line) {
  return Array.isArray(line) && line[0].coord[0] === 'D04' && line[1].coord[0] === 'D09';
}), 'serialized segment endpoints were not drawn');
const withoutDates = Object.assign({}, raw, {
  structure_annotations: { pivots: [{ ZG: 12.4, ZD: 10.8 }] }
});
globalThis.__auxTest.chart(withoutDates, {});
const noAreaCandle = chartOption.series.filter(function (series) { return series.name === 'K线'; })[0];
assert(!noAreaCandle.markArea || noAreaCandle.markArea.data.length === 0,
  'pivot without dates was turned into a fabricated area');
const indexed = Object.assign({}, raw, {
  structure_annotations: { pivots: [{ ZG: 12.4, ZD: 10.8, start_idx: 3, end_idx: 12 }] }
});
globalThis.__auxTest.chart(indexed, {});
const indexedCandle = chartOption.series.filter(function (series) { return series.name === 'K线'; })[0];
assert(!indexedCandle.markArea || indexedCandle.markArea.data.length === 0,
  'integer full-series indices were applied to the sliced chart window');
const ordinaryZone = Object.assign({}, raw, {
  structure_annotations: { zones: [{ upper: 12.4, lower: 10.8, start_date: 'D03', end_date: 'D12' }] }
});
globalThis.__auxTest.chart(ordinaryZone, {});
const ordinaryCandle = chartOption.series.filter(function (series) { return series.name === 'K线'; })[0];
assert(!ordinaryCandle.markArea || ordinaryCandle.markArea.data.length === 0,
  'ordinary upper/lower interval was presented as a Chan center');
window.CHANLUN_BOOTSTRAP = {
  pageDate: '2026-08-28',
  recommendationEvidence: {
    schema_version: 1, report_date: '2026-08-28', views: { main: [{
      code: '600001', summary: { code: '600001' },
      display_derived: { chart_evidence: {
        pivots: { status: 'conflict', available: [], ZG: null, ZD: null }
      } }
    }] }
  }
};
globalThis.__auxTest.state.data = { date: '2026-08-28' };
globalThis.__auxTest.state.currentView = 'main';
const conflictCandleInput = Object.assign({}, raw, {
  structure_annotations: { pivots: [{ ZG: 12.4, ZD: 10.8, start_date: 'D03', end_date: 'D12' }] }
});
globalThis.__auxTest.chart(conflictCandleInput, { code: '600001', evidence_view: 'main' });
const conflictCandle = chartOption.series.filter(function (series) { return series.name === 'K线'; })[0];
assert(!conflictCandle.markArea || conflictCandle.markArea.data.length === 0,
  'conflicting projected pivot was bypassed by raw structure annotation');
""",
        )

    def test_switching_snapshot_replaces_old_signal_markers(self):
        _assert_node_contract(
            self,
            "({ chart: renderChart, state: state })",
            _set_up_chart_js()
            + _chart_fixture_js("dates.map(function (_, index) { return index / 10; })")
            + r"""
raw.code = '600001';
raw.snapshot_id = 'snapshot-a';
raw.chart_annotations.markPoints = [{ coord: ['D22', 12.2], name: '旧信号' }];
globalThis.__auxTest.chart(raw, {});
let candle = chartOption.series.filter(function (series) { return series.name === 'K线'; })[0];
assert(candle.markPoint.data.length === 1 && candle.markPoint.data[0].name === '旧信号',
  'initial signal fixture was not drawn');
const next = Object.assign({}, raw, {
  snapshot_id: 'snapshot-b',
  chart_annotations: { markLines: [], markPoints: [], labels: [] }
});
globalThis.__auxTest.chart(next, {});
candle = chartOption.series.filter(function (series) { return series.name === 'K线'; })[0];
assert(candle.markPoint.data.length === 0, 'old snapshot signal marker remained after switching stock data');
""",
        )

    def test_chart_rejects_shifted_volume_metadata_lengths(self):
        _assert_node_contract(
            self,
            "({ chart: renderChart, state: state })",
            _set_up_chart_js()
            + _chart_fixture_js("dates.map(function (_, index) { return index / 10; })")
            + r"""
raw.volume_sources = raw.volume_sources.slice(1);
globalThis.__auxTest.chart(raw, {});
const volume = chartOption.series.filter(function (series) { return series.name === '成交量'; })[0];
assert(volume.data.every(function (value) { return value === null; }),
  'shifted metadata was tail-aligned onto different volume rows');
""",
        )

    def test_borrowed_chart_uses_actual_chart_source_volume_metadata(self):
        _assert_node_contract(
            self,
            "({ merge: mergeChartCandidate, chart: renderChart, state: state })",
            _set_up_chart_js()
            + r"""
const chartOwner={dates:['D1','D2'],opens:[10,11],highs:[11,12],lows:[9,10],closes:[10.5,11.5],
 volumes:[100,200],volume_units:['hands','unknown'],volume_raw_units:['hands','hands'],
 volume_sources:['actual-source','actual-source'],chart_annotations:{markLines:[],markPoints:[],labels:[]}};
const primary={code:'600001',volumes:[999,999],volume_units:['hands','hands'],
 volume_raw_units:['hands','hands'],volume_sources:['wrong-primary','wrong-primary']};
const merged=globalThis.__auxTest.merge(primary,chartOwner);
assert(merged.volumes===chartOwner.volumes&&merged.volume_units===chartOwner.volume_units
 && merged.volume_raw_units===chartOwner.volume_raw_units&&merged.volume_sources===chartOwner.volume_sources,
 'borrowed chart did not keep quantity metadata ownership');
globalThis.__auxTest.chart(merged, {});
const volume=chartOption.series.filter(function (series) { return series.name === '成交量'; })[0];
assert(volume.data[0]===100&&volume.data[1]===null,
 'metadata-source mismatch made borrowed volume comparable');
""",
        )


if __name__ == "__main__":
    unittest.main()
