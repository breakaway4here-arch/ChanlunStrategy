(function (root, factory) {
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.ChanlunSelectionPerformance = api;
})(typeof window !== 'undefined' ? window : null, function () {
  'use strict';

  var STATUSES = ['ready', 'waiting', 'missing_price', 'price_basis_unverified', 'calendar_unknown', 'excluded'];
  var UI_UNAVAILABLE = 'result_unavailable';
  var TIE_ABS_TOLERANCE = 1e-10;

  function list(value) { return Array.isArray(value) ? value : []; }
  function text(value) { return value == null ? '' : String(value); }
  function escapeHtml(value) {
    var visible = text(value);
    if (/(?:\/private\/|\/Users\/|\/etc\/|[A-Za-z]:\\|(?:api[_-]?key|secret|token)\s*[:=])/i.test(visible)) {
      visible = '资料未显示';
    }
    return visible.replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }
  function pct(value) {
    return typeof value === 'number' && Number.isFinite(value)
      ? (value > 0 ? '+' : '') + value.toFixed(2) + '%' : '—';
  }
  function equalsReturn(a, b) {
    return Math.abs(a - b) <= Math.max(TIE_ABS_TOLERANCE,
      1e-12 * Math.max(Math.abs(a), Math.abs(b)));
  }
  function matchesRef(row, filters) {
    return list(row.strategy_refs).some(function (ref) {
      return ref && typeof ref === 'object'
        && (!filters.strategyKey || ref.strategy_key === filters.strategyKey)
        && (filters.role !== 'formal' ||
          (ref.role === 'formal' && ref.recommendation_scope === 'formal_recommendation'))
        && (!filters.recommendationScope || ref.recommendation_scope === filters.recommendationScope);
    });
  }
  function matches(row, filters) {
    var day = text(row.report_date);
    if (filters.reportStart && day < filters.reportStart) return false;
    if (filters.reportEnd && day > filters.reportEnd) return false;
    if (filters.themeId) {
      var refs = list(row.theme_refs);
      if (filters.themeId === 'unrecorded' ? refs.length !== 0
        : !refs.some(function (ref) { return ref && ref.theme_id === filters.themeId; })) return false;
    }
    if (filters.strategyKey || filters.role === 'formal' || filters.recommendationScope) {
      return matchesRef(row, filters);
    }
    return true;
  }
  function outcomeFor(row, horizon) { return (row.outcomes || {})['t' + horizon] || {}; }
  function outcomeStatus(outcome) {
    if (!STATUSES.includes(outcome.status)) return UI_UNAVAILABLE;
    if (outcome.status === 'ready' && (typeof outcome.return_pct !== 'number'
      || !Number.isFinite(outcome.return_pct))) return UI_UNAVAILABLE;
    return outcome.status;
  }
  function compareRef(a, b) {
    return text(a.report_date).localeCompare(text(b.report_date))
      || text(a.instrument_id).localeCompare(text(b.instrument_id))
      || text(a.observation_id).localeCompare(text(b.observation_id));
  }
  function extremaRef(row, outcome) {
    return {observation_id: row.observation_id, instrument_id: row.instrument_id,
      code: row.code, name: row.name, report_date: row.report_date,
      target_date: outcome.target_date, start_close: outcome.start_close,
      end_close: outcome.end_close, return_pct: outcome.return_pct,
      publication_ref: row.publication_ref, price_series_ref: outcome.price_series_ref};
  }
  function aggregate(rows, horizon) {
    var counts = Object.fromEntries(STATUSES.map(function (status) { return [status, 0]; }));
    var unavailable = 0;
    var ready = [];
    rows.forEach(function (row) {
      var outcome = outcomeFor(row, horizon);
      var status = outcomeStatus(outcome);
      if (status === UI_UNAVAILABLE) unavailable += 1;
      else counts[status] += 1;
      if (status === 'ready') {
        ready.push({row: row, outcome: outcome, value: outcome.return_pct});
      }
    });
    var values = ready.map(function (item) { return item.value; }).sort(function (a, b) { return a - b; });
    if (unavailable) counts.result_unavailable = unavailable;
    var sum = values.reduce(function (total, value) { return total + value; }, 0);
    var median = values.length ? (values[Math.floor((values.length - 1) / 2)]
      + values[Math.floor(values.length / 2)]) / 2 : null;
    function refs(extreme) {
      return ready.filter(function (item) { return equalsReturn(item.value, extreme); })
        .sort(function (a, b) { return compareRef(a.row, b.row); })
        .map(function (item) { return extremaRef(item.row, item.outcome); });
    }
    return {horizon: horizon, total_observations: rows.length, counts: counts,
      expected_results: counts.ready + counts.missing_price + counts.price_basis_unverified,
      unique_stocks: new Set(rows.map(function (row) { return row.instrument_id; }).filter(Boolean)).size,
      report_dates: new Set(rows.map(function (row) { return row.report_date; }).filter(Boolean)).size,
      mean_return_pct: values.length ? sum / values.length : null,
      median_return_pct: median,
      positive_ratio_pct: values.length
        ? values.filter(function (value) { return value > 0; }).length / values.length * 100 : null,
      best_observations: values.length ? refs(values[values.length - 1]) : [],
      worst_observations: values.length ? refs(values[0]) : []};
  }
  function dateRange(dataset) {
    var asOf = text(dataset.report_as_of);
    var dates = Array.from(new Set(list(dataset.trading_dates).filter(function (day) {
      return /^\d{4}-\d{2}-\d{2}$/.test(day) && day <= asOf;
    }))).sort();
    if (dates.length) {
      var windowDays = dates.slice(-60);
      return {start: windowDays[0], end: asOf, actualDays: windowDays.length,
        status: windowDays.length < 60 ? 'short_history' : 'complete'};
    }
    var observed = Array.from(new Set(list(dataset.observations).map(function (row) {
      return row.report_date;
    }).filter(Boolean))).sort();
    return {start: observed[0] || asOf, end: asOf, actualDays: null,
      status: 'calendar_unavailable'};
  }
  function groupModels(rows, horizon, kind, filters) {
    var groups = new Map();
    rows.forEach(function (row) {
      var refs = kind === 'themes' ? list(row.theme_refs) : list(row.strategy_refs);
      if (kind === 'themes' && refs.length === 0) refs = [{theme_id: 'unrecorded', name: '题材未记录'}];
      var seen = new Set();
      refs.forEach(function (ref) {
        if (!ref || typeof ref !== 'object') return;
        if (kind === 'strategies' && (
          (filters.strategyKey && ref.strategy_key !== filters.strategyKey)
          || (filters.role === 'formal' && (ref.role !== 'formal'
            || ref.recommendation_scope !== 'formal_recommendation'))
          || (filters.recommendationScope
            && ref.recommendation_scope !== filters.recommendationScope))) return;
        var id = kind === 'themes' ? ref.theme_id : ref.strategy_key;
        if (!id || seen.has(id)) return;
        seen.add(id);
        if (!groups.has(id)) groups.set(id, {
          id: id, label: kind === 'themes' ? (ref.name || '题材未记录')
            : (ref.strategy_id || ref.view || '策略未记录'),
          identity: kind === 'strategies' ? ref : null, rows: []});
        groups.get(id).rows.push(row);
      });
    });
    return Array.from(groups.values()).map(function (group) {
      return {id: group.id, label: group.label, identity: group.identity,
        summary: aggregate(group.rows, horizon)};
    }).sort(function (a, b) {
      var av = a.summary.mean_return_pct;
      var bv = b.summary.mean_return_pct;
      if (av == null && bv != null) return 1;
      if (av != null && bv == null) return -1;
      return (bv == null ? 0 : bv) - (av == null ? 0 : av) || text(a.id).localeCompare(text(b.id));
    });
  }
  function scoreSortInfo(rows, strategyKey) {
    if (!strategyKey || !rows.length) return null;
    var scores = rows.map(function (row) {
      var refs = list(row.strategy_refs).filter(function (ref) { return ref && ref.strategy_key === strategyKey; });
      return refs.length === 1 ? refs[0] : null;
    });
    if (scores.some(function (ref) { return !ref || ref.score_definition_status !== 'recorded'
      || !ref.score_name || !ref.score_definition || typeof ref.score !== 'number'
      || !Number.isFinite(ref.score); })) return null;
    var identity = scores[0].score_name + '\u0000' + scores[0].score_definition;
    if (scores.some(function (ref) { return ref.score_name + '\u0000' + ref.score_definition !== identity; })) return null;
    return {name: scores[0].score_name, definition: scores[0].score_definition,
      scoreByObservation: new Map(rows.map(function (row, i) { return [row.observation_id, scores[i].score]; }))};
  }
  function computeView(dataset, input) {
    if (!dataset || dataset.schema_version !== 'selection-performance-v1') throw new Error('Invalid performance dataset');
    var options = input || {};
    var horizons = list(dataset.horizons).filter(function (n) { return Number.isInteger(n) && n > 0; });
    var horizon = options.horizon == null ? horizons[0] : Number(options.horizon);
    if (!horizons.includes(horizon)) throw new Error('Unsupported performance horizon');
    var range = dateRange(dataset);
    var filters = {horizon: horizon,
      reportStart: options.reportStart === undefined ? range.start : options.reportStart,
      reportEnd: options.reportEnd === undefined ? range.end : options.reportEnd,
      themeId: options.themeId || null, strategyKey: options.strategyKey || null,
      role: options.role === 'formal' ? 'formal' : 'all',
      recommendationScope: options.recommendationScope || null};
    var selected = list(dataset.observations).filter(function (row) { return matches(row, filters); });
    var summary = aggregate(selected, horizon);
    var groupBase = selected;
    var scoreInfo = scoreSortInfo(selected, filters.strategyKey);
    var allDetails = selected.slice().sort(function (a, b) {
      if (options.sortByScore && scoreInfo) {
        var delta = scoreInfo.scoreByObservation.get(b.observation_id)
          - scoreInfo.scoreByObservation.get(a.observation_id);
        if (delta) return delta;
      }
      return compareRef(a, b);
    });
    var pageSize = Math.max(1, Math.min(100, Number(options.pageSize) || 20));
    var page = Math.max(0, Math.floor(Number(options.page) || 0));
    return {dataset: dataset, horizons: horizons, filters: filters, range: range,
      summary: summary, groups: {themes: groupModels(groupBase, horizon, 'themes', filters),
        strategies: groupModels(groupBase, horizon, 'strategies', filters)},
      details: allDetails.slice(page * pageSize, (page + 1) * pageSize),
      allDetails: allDetails, page: page, pageSize: pageSize,
      scoreSort: scoreInfo ? {name: scoreInfo.name, definition: scoreInfo.definition} : null,
      sortByScore: Boolean(options.sortByScore && scoreInfo),
      activeView: options.view === 'strategies' || options.view === 'details' ? options.view : 'themes'};
  }
  function emptyReason(summary) {
    if (summary.total_observations === 0) return '所选范围没有已发布入选记录';
    if (summary.counts.price_basis_unverified) return '价基未核验，暂无已到期可核验结果';
    if (summary.counts.missing_price) return '目标日缺行情，暂无已到期可核验结果';
    if (summary.counts.result_unavailable) return '结果缺项，暂无已到期可核验结果';
    if (summary.counts.waiting) return '尚未到目标交易日收盘';
    if (summary.counts.calendar_unknown) return '交易日历未核验';
    return '暂无已到期可核验结果';
  }
  function extremaHtml(label, refs) {
    if (!refs.length) return '';
    var first = refs[0];
    return '<div class="sp-extrema"><span>' + escapeHtml(label) + '</span><strong>'
      + escapeHtml(first.name || first.code) + ' ' + escapeHtml(first.code) + ' · '
      + pct(first.return_pct) + '</strong><small>入选 ' + escapeHtml(first.report_date)
      + ' · 目标 ' + escapeHtml(first.target_date) + (refs.length > 1 ? ' · 并列 ' + refs.length + ' 笔' : '')
      + '</small><button type="button" data-sp-focus="' + escapeHtml(first.observation_id)
      + '">看这次入选的表现</button></div>';
  }
  function groupHtml(group, kind) {
    var summary = group.summary;
    var best = summary.best_observations[0];
    var worst = summary.worst_observations[0];
    var identity = kind === 'strategy' ? (group.identity || {}) : null;
    var identityText = identity ? [
      '版本 ' + (identity.strategy_version || '未记录'),
      '策略原入场 ' + (identity.entry_mode || '未记录'),
      identity.role === 'formal' ? '正式来源' : '研究来源',
    ].join(' · ') : '';
    return '<button type="button" class="sp-group" data-sp-' + kind + '="' + escapeHtml(group.id) + '">'
      + '<strong>' + escapeHtml(group.label) + '</strong>'
      + (identity ? '<small>' + escapeHtml(identityText) + '</small>' : '')
      + '<span>' + pct(summary.mean_return_pct)
      + '</span><small>中位数 ' + pct(summary.median_return_pct) + ' · 上涨比例 '
      + pct(summary.positive_ratio_pct) + ' · 结果 ' + summary.counts.ready + '/'
      + summary.expected_results + ' 笔</small>'
      + (best ? '<small>最好 ' + escapeHtml(best.name || best.code) + ' ' + escapeHtml(best.code)
        + ' ' + pct(best.return_pct) + ' · 入选 ' + escapeHtml(best.report_date) + '</small>' : '')
      + (worst ? '<small>最差 ' + escapeHtml(worst.name || worst.code) + ' ' + escapeHtml(worst.code)
        + ' ' + pct(worst.return_pct) + ' · 入选 ' + escapeHtml(worst.report_date) + '</small>' : '')
      + (!best ? '<small>' + escapeHtml(emptyReason(summary)) + '</small>' : '')
      + '</button>';
  }
  function detailHtml(row, horizon) {
    var outcome = outcomeFor(row, horizon);
    var status = outcomeStatus(outcome);
    var sources = list(row.strategy_refs).filter(function (ref) {
      return ref && typeof ref === 'object';
    }).map(function (ref) {
      var score = typeof ref.score === 'number' && Number.isFinite(ref.score)
        ? String(ref.score) : '未记录';
      var scoreText = ref.score_name && ref.score_definition
        ? ref.score_name + ' ' + score
        : '当时记录分数 ' + score + ' · 定义未记录';
      return '<small class="sp-source-score">'
        + escapeHtml(ref.strategy_id || ref.view || '策略未记录')
        + (ref.strategy_version ? ' · ' + escapeHtml(ref.strategy_version) : '')
        + ' · ' + escapeHtml(ref.role === 'formal' ? '正式来源' : '研究来源')
        + ' · ' + escapeHtml(scoreText) + '</small>';
    }).join('');
    return '<article class="sp-detail" id="sp-observation-' + escapeHtml(row.observation_id) + '">'
      + '<strong>' + escapeHtml(row.name || row.code) + ' ' + escapeHtml(row.code) + '</strong>'
      + '<span>' + pct(outcome.return_pct) + '</span><small>入选 ' + escapeHtml(row.report_date)
      + ' · 目标 ' + escapeHtml(outcome.target_date || '未定位') + ' · '
      + escapeHtml(status === 'ready' ? '已核验' : emptyReason({total_observations: 1,
        counts: Object.fromEntries(STATUSES.concat([UI_UNAVAILABLE]).map(function (key) { return [key, status === key ? 1 : 0]; }))}))
      + '</small>' + sources + '</article>';
  }
  function renderHtml(view) {
    var dataset = view.dataset;
    var summary = view.summary;
    var filters = view.filters;
    var readyStocks = new Set(view.allDetails.filter(function (row) {
      return outcomeStatus(outcomeFor(row, filters.horizon)) === 'ready';
    }).map(function (row) { return row.instrument_id; }).filter(Boolean)).size;
    var groups = view.activeView === 'strategies' ? view.groups.strategies : view.groups.themes;
    var groupKind = view.activeView === 'strategies' ? 'strategy' : 'theme';
    var themeGroup = view.groups.themes.find(function (group) { return group.id === filters.themeId; });
    var strategyGroup = view.groups.strategies.find(function (group) { return group.id === filters.strategyKey; });
    var activeGroupText = [
      filters.themeId ? '当前题材：' + (themeGroup ? themeGroup.label : '筛选结果为空') : '',
      filters.strategyKey ? '当前策略：' + (strategyGroup ? strategyGroup.label : '筛选结果为空') : '',
    ].filter(Boolean).join(' · ');
    var headline = summary.counts.ready ? '<div class="sp-metrics"><div><small>平均价格收益</small><strong>'
      + pct(summary.mean_return_pct) + '</strong></div><div><small>中位数</small><strong>'
      + pct(summary.median_return_pct) + '</strong></div><div><small>上涨比例</small><strong>'
      + pct(summary.positive_ratio_pct) + '</strong></div></div>'
      + extremaHtml('最好的一笔', summary.best_observations)
      + extremaHtml('最差的一笔', summary.worst_observations)
      : '<p class="sp-empty" role="status">' + escapeHtml(emptyReason(summary)) + '</p>';
    var rangeNote = view.range.status === 'short_history'
      ? '已保存交易日不足 60 日，实际 ' + view.range.actualDays + ' 日'
      : view.range.status === 'calendar_unavailable' ? '交易日日历未提供，显示已保存范围' : '';
    var coverage = dataset.coverage || {};
    var historyNote = typeof coverage.published_report_dates === 'number'
      ? '已证发布报告 ' + coverage.published_report_dates + ' 日 · 已登记 '
        + (coverage.registered_observations || 0) + ' 笔观察'
      : '';
    var periods = view.horizons.map(function (n) {
      return '<button type="button" data-sp-horizon="' + n + '" aria-pressed="'
        + (n === filters.horizon ? 'true' : 'false') + '">T+' + n + '</button>';
    }).join('');
    var groupRows = view.activeView === 'details' ? '' : groups.map(function (group) {
      return groupHtml(group, groupKind);
    }).join('');
    return '<section class="selection-performance" aria-label="选股表现">'
      + '<header><h2>选股表现</h2><p>统计当时发布的股票，之后 N 个交易日的价格变化；不是实盘成交收益。</p></header>'
      + '<div class="sp-filters"><label>范围 <select data-sp-role><option value="all"'
      + (filters.role === 'all' ? ' selected' : '') + '>全部已发布候选（含研究）</option><option value="formal"'
      + (filters.role === 'formal' ? ' selected' : '') + '>正式推荐</option></select></label>'
      + '<label>入选日期起 <input type="date" data-sp-start value="' + escapeHtml(filters.reportStart) + '"></label>'
      + '<label>止 <input type="date" data-sp-end value="' + escapeHtml(filters.reportEnd) + '"></label></div>'
      + (rangeNote ? '<p class="sp-range-note">' + escapeHtml(rangeNote) + '</p>' : '')
      + (historyNote ? '<p class="sp-range-note">' + escapeHtml(historyNote) + '</p>' : '')
      + '<p class="sp-asof">报告日收盘 → T+' + filters.horizon + ' 收盘 · 行情截至 '
      + escapeHtml(dataset.evaluation_as_of) + (view.updateFailed ? ' · 更新失败，仍显示该截至日期' : '') + '</p>'
      + '<div class="sp-horizons" role="group" aria-label="结果周期">' + periods + '</div>'
      + headline + '<p class="sp-coverage">已有结果 ' + summary.counts.ready + ' 笔（'
      + readyStocks + ' 只） · 应跟踪 ' + summary.total_observations + ' 笔（'
      + summary.unique_stocks + ' 只） · 应有结果 ' + summary.expected_results
      + ' 笔 · 待到期 ' + summary.counts.waiting + ' 笔 · 缺数据 '
      + (summary.counts.missing_price + summary.counts.price_basis_unverified)
      + ' 笔' + (summary.counts.result_unavailable
        ? ' · 结果缺项 ' + summary.counts.result_unavailable + ' 笔' : '')
      + (summary.counts.calendar_unknown
        ? ' · 日期未核验 ' + summary.counts.calendar_unknown + ' 笔' : '')
      + (summary.counts.excluded
        ? ' · 已排除 ' + summary.counts.excluded + ' 笔' : '')
      + (summary.counts.ready === 1 ? ' · 仅 1 笔可核验' : '') + '</p>'
      + '<nav class="sp-view-tabs" aria-label="表现视角"><button type="button" data-sp-view="themes">按题材</button>'
      + '<button type="button" data-sp-view="strategies">按策略</button><button type="button" data-sp-view="details">逐股明细</button></nav>'
      + (activeGroupText ? '<p class="sp-active-filter">' + escapeHtml(activeGroupText) + '</p>' : '')
      + ((filters.themeId || filters.strategyKey)
        ? '<button type="button" data-sp-clear>清除题材／策略筛选</button>' : '')
      + (view.activeView === 'themes' ? '<p>本系统入选股票 · 按入选当时题材看表现。题材可重叠，组间样本数不可相加。</p>' : '')
      + (groupRows ? '<div class="sp-groups">' + groupRows + '</div>' : '')
      + (view.scoreSort ? '<button type="button" data-sp-score aria-pressed="'
        + (view.sortByScore ? 'true' : 'false') + '">按当时策略分排序（'
        + escapeHtml(view.scoreSort.name) + '）</button>' : '')
      + '<div class="sp-details"><h3>逐股明细</h3>' + view.details.map(function (row) {
        return detailHtml(row, filters.horizon);
      }).join('') + '</div>'
      + (view.allDetails.length > view.pageSize ? '<div class="sp-pages"><button type="button" data-sp-page="prev">上一页</button>'
        + '<span>第 ' + (view.page + 1) + ' 页／共 ' + Math.ceil(view.allDetails.length / view.pageSize)
        + ' 页</span><button type="button" data-sp-page="next">下一页</button></div>' : '')
      + '<details class="sp-explain"><summary>数据范围与计算说明</summary><p>同股跨日重复入选分别记录，不代表独立实盘交易。只有同一可核验价基的报告日和目标日收盘可计算结果。</p></details>'
      + '</section>';
  }
  function createLoader(fetchJson) {
    var serial = 0;
    var last = null;
    var cache = new Map();
    return {load: async function (pageDate, url, refresh) {
      var token = ++serial;
      if (!refresh && cache.has(url)) {
        last = {pageDate: pageDate, dataset: cache.get(url)};
        return {dataset: last.dataset, stale: false, updateFailed: false};
      }
      try {
        var dataset = await fetchJson(url);
        if (token !== serial) return {dataset: null, stale: true, updateFailed: false};
        var evaluationDate = text(dataset && dataset.evaluation_as_of).slice(0, 10);
        if (!dataset || dataset.schema_version !== 'selection-performance-v1'
          || !/^\d{4}-\d{2}-\d{2}$/.test(text(dataset.report_as_of))
          || !/^\d{4}-\d{2}-\d{2}$/.test(evaluationDate)
          || dataset.report_as_of > pageDate || evaluationDate > pageDate) {
          throw new Error('Invalid performance dataset');
        }
        cache.set(url, dataset);
        last = {pageDate: pageDate, dataset: dataset};
        return {dataset: dataset, stale: false, updateFailed: false};
      } catch (_error) {
        if (token !== serial) return {dataset: null, stale: true, updateFailed: false};
        return {dataset: last && last.pageDate === pageDate ? last.dataset : null,
          stale: false, updateFailed: true};
      }
    }};
  }
  function mount(container, config) {
    var options = config || {};
    var pageDate = text(options.pageDate);
    var prefix = text(options.dataBasePrefix || '');
    var fetchJson = options.fetchJson || function (url) {
      return window.fetch(url, {cache: 'no-store'}).then(function (response) {
        if (!response.ok) throw new Error('Performance data unavailable');
        return response.json();
      });
    };
    var loader = createLoader(fetchJson);
    var state = {dataset: null, updateFailed: false, filters: {horizon: null, view: 'themes',
      page: 0, pageSize: 20}};
    var sequence = 0;
    var viewCache = new Map();
    function dataUrl(day) { return prefix + 'data/selection-performance/' + day + '.json'; }
    function view() {
      if (!state.dataset) return null;
      var dataset = state.dataset;
      var cacheKey = JSON.stringify([dataset.dataset_id, dataset.evaluation_as_of,
        dataset.measurement, dataset.calculation_version, state.filters]);
      if (!viewCache.has(cacheKey)) {
        viewCache.set(cacheKey, computeView(dataset, state.filters));
      }
      return Object.assign({}, viewCache.get(cacheKey), {updateFailed: state.updateFailed});
    }
    function render() {
      if (!state.dataset) {
        container.innerHTML = '<section class="selection-performance" aria-label="选股表现">'
          + '<h2>选股表现</h2><p class="sp-empty" role="status">'
          + (state.updateFailed ? '本期表现数据暂不可用，已发布清单仍可查看。' : '正在读取已发布清单表现…')
          + '</p></section>';
        return;
      }
      container.innerHTML = renderHtml(view());
      if (typeof container.querySelectorAll === 'function') {
        Array.from(container.querySelectorAll('[data-sp-view]')).forEach(function (button) {
          button.setAttribute('aria-pressed', button.getAttribute('data-sp-view') === state.filters.view
            ? 'true' : 'false');
        });
      }
    }
    function setFilters(update) {
      state.filters = Object.assign({}, state.filters, update);
      render();
      return view();
    }
    async function load(refresh) {
      var token = ++sequence;
      var current = await loader.load(pageDate, dataUrl(pageDate), refresh);
      if (token !== sequence || current.stale) return null;
      if (current.dataset) {
        state.dataset = current.dataset;
        state.updateFailed = current.updateFailed;
        if (!current.updateFailed) {
          try {
            var status = await fetchJson(prefix + 'data/selection-performance/status.json');
            if (token !== sequence) return null;
            if (status && status.status === 'update_failed'
              && status.attempted_report_as_of === pageDate) state.updateFailed = true;
          } catch (_statusError) { /* A missing optional status sidecar is harmless. */ }
        }
      } else {
        state.updateFailed = true;
        try {
          var index = await fetchJson(prefix + 'data/selection-performance/index.json');
          if (token !== sequence) return null;
          var earlier = list(index && index.dates).filter(function (day) {
            return /^\d{4}-\d{2}-\d{2}$/.test(day) && day <= pageDate;
          }).sort().pop();
          if (earlier) {
            var fallback = await loader.load(pageDate, dataUrl(earlier), refresh);
            if (token !== sequence || fallback.stale) return null;
            state.dataset = fallback.dataset;
          }
        } catch (_indexError) { /* The main report remains usable. */ }
      }
      viewCache.clear();
      render();
      return view();
    }
    if (container && typeof container.addEventListener === 'function') {
      container.addEventListener('click', function (event) {
        var button = event.target && event.target.closest ? event.target.closest('button') : null;
        if (!button || !container.contains(button)) return;
        var horizon = button.getAttribute('data-sp-horizon');
        var choice = button.getAttribute('data-sp-view');
        var theme = button.getAttribute('data-sp-theme');
        var strategy = button.getAttribute('data-sp-strategy');
        var focus = button.getAttribute('data-sp-focus');
        var page = button.getAttribute('data-sp-page');
        if (horizon) setFilters({horizon: Number(horizon), page: 0});
        else if (choice) setFilters({view: choice, page: 0});
        else if (theme) setFilters({themeId: theme, page: 0});
        else if (strategy) setFilters({strategyKey: strategy, page: 0});
        else if (button.hasAttribute('data-sp-clear')) setFilters({themeId: null, strategyKey: null, page: 0});
        else if (button.hasAttribute('data-sp-score')) setFilters({sortByScore: !state.filters.sortByScore, page: 0});
        else if (page) {
          var pages = Math.ceil(view().allDetails.length / state.filters.pageSize);
          setFilters({page: Math.max(0, Math.min(pages - 1,
            state.filters.page + (page === 'next' ? 1 : -1)))});
        } else if (focus) {
          var rows = view().allDetails;
          var index = rows.findIndex(function (row) { return row.observation_id === focus; });
          if (index >= 0) {
            setFilters({view: 'details', page: Math.floor(index / state.filters.pageSize)});
            if (typeof document !== 'undefined') {
              var target = document.getElementById('sp-observation-' + focus);
              if (target && target.scrollIntoView) target.scrollIntoView({block: 'center'});
            }
          }
        }
      });
      container.addEventListener('change', function (event) {
        var target = event.target;
        if (!target || !container.contains(target)) return;
        if (target.hasAttribute('data-sp-role')) setFilters({role: target.value, page: 0});
        if (target.hasAttribute('data-sp-start')) setFilters({reportStart: target.value, page: 0});
        if (target.hasAttribute('data-sp-end')) setFilters({reportEnd: target.value, page: 0});
      });
    }
    render();
    return {ready: load(false), reload: function () { return load(true); },
      setFilters: setFilters, getView: view};
  }
  return {aggregate: aggregate, computeView: computeView, createLoader: createLoader,
    dateRange: dateRange, renderHtml: renderHtml, escapeHtml: escapeHtml, mount: mount};
});
