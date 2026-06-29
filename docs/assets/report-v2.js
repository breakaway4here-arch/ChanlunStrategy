(function () {
  'use strict';

  var DEFAULT_VIEW_ORDER = ['highlights', 'main', 'acceleration', 'luojie', 'confirming', 'baseline'];
  var DEFAULT_VIEW_LABELS = {
    highlights: '看点 Top10',
    main: '主推',
    acceleration: '加速',
    luojie: '罗姐池',
    confirming: '等确认',
    baseline: '基准',
  };
  var DEFAULT_VIEW_DESCRIPTIONS = {
    highlights: '看点 Top10：跨池混合优先观察榜。用于快速扫今天最值得看的标的，不等于全部可立即买入；请结合身份标签、共振标签和操作状态判断。',
    main: '主推：融合推荐池，可执行优先。来自纯净缠论结构 + 30min 确认 + 市场状态 / MA 多头 / admission 门槛过滤。',
    acceleration: '加速：强市场下的情绪加速榜。用于从强势启动类候选中二次排序，不是常规主推荐池。',
    luojie: '罗姐池：硬方向 + 15min 生命线观察，不等同于主推。',
    confirming: '等确认：日线已有启动线索，但等待 30min 或次日确认，观察为主，不直接追高。',
    baseline: '基准：纯净缠论结构参考池，用于看原始结构信号和主推来源参考。',
  };
  var CHART_EMPTY_TEXT = '暂无图表数据，但保留推荐原因和来源。请检查原始池子数据或 K 线数据。';

  var state = {
    data: null,
    workspace: null,
    currentView: 'highlights',
    activeItem: null,
    isMobile: false,
    chartInstance: null,
    chartMount: null,
    rawPoolCandidates: null,
  };

  var nodes = {
    shell: null,
    headerTitle: null,
    headerSubtitle: null,
    headerMetrics: null,
    tabs: null,
    description: null,
    candidateList: null,
    detailPanel: null,
    auxGrid: null,
    drawer: null,
    drawerBackdrop: null,
    drawerPanel: null,
    drawerContent: null,
    app: null,
  };

  function escapeHtml(value) {
    var text = String(value == null ? '' : value);
    return text
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;')
      .replace(/\//g, '&#47;');
  }

  function safeNumber(value, fallback) {
    if (value === null || value === undefined || value === '' || Number.isNaN(Number(value))) {
      return fallback;
    }
    return Number(value);
  }

  function isString(value) {
    return typeof value === 'string';
  }

  function normalizeString(value) {
    if (value === null || value === undefined) return '';
    if (isString(value)) return value;
    return String(value);
  }

  function isMobileViewport() {
    if (!window.matchMedia) return false;
    return window.matchMedia('(max-width: 760px)').matches;
  }

  function formatNumber(value, decimals) {
    var num = safeNumber(value, null);
    if (num === null) {
      return '--';
    }
    if (decimals === undefined) decimals = 2;
    return num.toFixed(decimals);
  }

  function formatPct(value, plusSign) {
    var num = safeNumber(value, null);
    if (num === null) {
      return '--';
    }
    var result = num.toFixed(2) + '%';
    if (plusSign && num > 0) {
      return '+' + result;
    }
    return result;
  }

  function formatDateLabel(dateStr) {
    if (!dateStr) return '--';
    var m = normalizeString(dateStr).match(/^\d{4}-\d{2}-\d{2}/);
    return m ? m[0] : normalizeString(dateStr);
  }

  function toCodeKey(value) {
    return normalizeString(value).trim();
  }

  function asArray(value) {
    return Array.isArray(value) ? value : [];
  }

  function getBootstrap() {
    return window.CHANLUN_BOOTSTRAP || {};
  }

  function detectDataUrl(dateStr) {
    var path = window.location.pathname || '';
    var prefix = /\/\d{4}-\d{2}-\d{2}$/.test(path.replace(/\/+$/, '')) ? '../' : '';
    var resolvedDate = normalizeString(dateStr || getBootstrap().pageDate || formatDateLabel(new Date().toISOString()));
    return prefix + 'data/' + resolvedDate + '.json';
  }

  function getRawPools() {
    if (state.rawPoolCandidates) {
      return state.rawPoolCandidates;
    }

    var data = state.data || {};
    var luojiePool = data.luojie_pool;
    var nextDayBoom = data.next_day_boom;
    state.rawPoolCandidates = {
      picks_fusion: asArray(data.picks_fusion),
      picks_pure: asArray(data.picks_pure),
      startup_watchlist: asArray(data.startup_watchlist),
      next_day_boom: asArray((nextDayBoom && nextDayBoom.candidates) || []),
      luojie_pool: asArray((luojiePool && luojiePool.candidates) || []),
    };
    return state.rawPoolCandidates;
  }

  function getWorkspaceDataFromRef(refPool) {
    var pools = getRawPools();
    var key = normalizeString(refPool).toLowerCase().replace(/-/g, '_');
    if (key === 'main') {
      return pools.picks_fusion;
    }
    if (key === 'acceleration' || key === 'accel' || key === 'next_day_boom') {
      return pools.next_day_boom;
    }
    if (key === 'luojie' || key === 'luojie_pool') {
      return pools.luojie_pool;
    }
    if (key === 'confirming') {
      return pools.startup_watchlist;
    }
    if (key === 'baseline') {
      return pools.picks_pure;
    }
    if (key === 'highlights') {
      return [];
    }
    return pools[key] || [];
  }

  function findRawCandidate(ref) {
    if (!ref || !ref.code) {
      return null;
    }
    var targetCode = toCodeKey(ref.code);
    var explicit = getWorkspaceDataFromRef(ref.pool || '');
    var found = null;

    if (explicit && explicit.length > 0) {
      found = explicit.find(function (item) {
        return toCodeKey(item && item.code) === targetCode;
      }) || null;
    }
    if (found) {
      return found;
    }

    var pools = getRawPools();
    var allPools = [
      pools.picks_fusion,
      pools.picks_pure,
      pools.startup_watchlist,
      pools.luojie_pool,
      pools.next_day_boom,
    ];

    for (var i = 0; i < allPools.length; i += 1) {
      var candidate = allPools[i].find(function (item) {
        return toCodeKey(item && item.code) === targetCode;
      });
      if (candidate) {
        return candidate;
      }
    }
    return null;
  }

  function setTextNode(el, value) {
    if (!el) return;
    el.innerHTML = escapeHtml(value);
  }

  function getCandidateViews() {
    var workspace = state.workspace || {};
    return {
      meta: workspace.view_meta || {},
      views: workspace.views || {},
      order: workspace.view_order || DEFAULT_VIEW_ORDER,
      defaultView: workspace.default_view || 'highlights',
      diagnostics: workspace.diagnostics || {},
    };
  }

  function getCurrentViewItems() {
    var views = getCandidateViews().views;
    return asArray(views[state.currentView]);
  }

  function getCurrentDescription(viewKey) {
    var viewDef = getCandidateViews();
    var meta = viewDef.meta[viewKey] || {};
    return meta.description || DEFAULT_VIEW_DESCRIPTIONS[viewKey] || '';
  }

  function getCurrentLabel(viewKey) {
    var viewDef = getCandidateViews();
    var meta = viewDef.meta[viewKey] || {};
    return meta.label || DEFAULT_VIEW_LABELS[viewKey] || viewKey;
  }

  function getCurrentShortLabel(viewKey) {
    var viewDef = getCandidateViews();
    var meta = viewDef.meta[viewKey] || {};
    return meta.short_label || getCurrentLabel(viewKey);
  }

  function buildAppShell() {
    var app = document.getElementById('app') || document.body;
    app.innerHTML = ''
      + '<div class="report-shell" id="reportShell">'
      + '  <header class="report-header">'
      + '    <div class="report-title-wrap">'
      + '      <h1 class="report-title"></h1>'
      + '      <div class="report-subtitle"></div>'
      + '    </div>'
      + '    <div class="header-metrics"></div>'
      + '  </header>'
      + '  <section class="workspace">'
      + '    <nav class="workspace-tabs" id="workspaceTabs"></nav>'
      + '    <div class="view-description" id="viewDescription"></div>'
      + '    <div class="workspace-body">'
      + '      <div>'
      + '        <div class="candidate-list" id="candidateList"></div>'
      + '      </div>'
      + '      <aside class="detail-panel workspace-detail" id="detailPanel"></aside>'
      + '    </div>'
      + '  </section>'
      + '  <section class="aux-center">'
      + '    <details id="auxCenter">'
      + '      <summary>'
      + '        <span>辅助信息</span>'
      + '        <span class="aux-summary-sub">市场、板块、涨停、事件、卖出、回看、诊断</span>'
      + '      </summary>'
      + '      <div class="aux-grid" id="auxGrid"></div>'
      + '    </details>'
      + '  </section>'
      + '  <div class="mobile-drawer" id="mobileDrawer">'
      + '    <div class="mobile-drawer-backdrop" id="mobileDrawerBackdrop"></div>'
      + '    <div class="mobile-drawer-panel" id="mobileDrawerPanel">'
      + '      <button class="mobile-drawer-close" id="mobileDrawerClose">关闭</button>'
      + '      <div id="mobileDrawerContent"></div>'
      + '    </div>'
      + '  </div>'
      + '  <div class="text-empty hidden" id="globalError"></div>'
      + '</div>';

    nodes.app = app;
    nodes.shell = app.querySelector('#reportShell');
    nodes.headerTitle = app.querySelector('.report-title');
    nodes.headerSubtitle = app.querySelector('.report-subtitle');
    nodes.headerMetrics = app.querySelector('.header-metrics');
    nodes.tabs = app.querySelector('#workspaceTabs');
    nodes.description = app.querySelector('#viewDescription');
    nodes.candidateList = app.querySelector('#candidateList');
    nodes.detailPanel = app.querySelector('#detailPanel');
    nodes.auxGrid = app.querySelector('#auxGrid');
    nodes.drawer = app.querySelector('#mobileDrawer');
    nodes.drawerBackdrop = app.querySelector('#mobileDrawerBackdrop');
    nodes.drawerPanel = app.querySelector('#mobileDrawerPanel');
    nodes.drawerContent = app.querySelector('#mobileDrawerContent');
    nodes.globalError = app.querySelector('#globalError');
  }

  function renderHeader() {
    if (!nodes.headerTitle || !state.data) return;
    var data = state.data || {};
    var dateLabel = data.date || getBootstrap().pageDate || formatDateLabel(new Date().toISOString());
    var ws = state.workspace || {};
    var views = ws.views || {};
    var market = data.market || {};
    var marketState = '--';
    if (isNaN(0) === false && market && Object.keys(market).length > 0) {
      var first = market[Object.keys(market)[0]];
      if (first && first.change_pct !== null && first.change_pct !== undefined) {
        marketState = (first.change_pct >= 0 ? '强' : '弱');
      }
    }

    var totalViews = getCandidateViews();
    var totalMain = asArray(views.main).length;
    var totalAccel = asArray(views.acceleration).length;
    var totalLuojie = asArray(views.luojie).length;
    var totalConfirm = asArray(views.confirming).length;
    var totalBase = asArray(views.baseline).length;

    setTextNode(nodes.headerTitle, '缠论策略日报');
    setTextNode(nodes.headerSubtitle, dateLabel + ' · ' + marketState + ' · 交易观测台');
    nodes.headerMetrics.innerHTML = ''
      + '<span class="metric-chip">看点 <strong>' + asArray(views.highlights).length + '</strong></span>'
      + '<span class="metric-chip">主推 <strong>' + totalMain + '</strong></span>'
      + '<span class="metric-chip">加速 <strong>' + totalAccel + '</strong></span>'
      + '<span class="metric-chip">罗姐池 <strong>' + totalLuojie + '</strong></span>'
      + '<span class="metric-chip">等确认 <strong>' + totalConfirm + '</strong></span>'
      + '<span class="metric-chip">基准 <strong>' + totalBase + '</strong></span>';
  }

  function renderWorkspaceTabs() {
    if (!nodes.tabs) return;
    nodes.tabs.innerHTML = '';
    var wsInfo = getCandidateViews();
    var order = asArray(wsInfo.order);
    if (order.length === 0) {
      order = DEFAULT_VIEW_ORDER;
    }
    for (var i = 0; i < order.length; i += 1) {
      var viewKey = order[i];
      var views = asArray(wsInfo.views[viewKey]);
      var button = document.createElement('button');
      button.type = 'button';
      button.className = 'workspace-tab' + (viewKey === state.currentView ? ' is-active' : '');
      button.setAttribute('data-view', viewKey);
      button.innerHTML = ''
        + '<span class="workspace-tab-label">' + escapeHtml(state.isMobile ? getCurrentShortLabel(viewKey) : getCurrentLabel(viewKey)) + '</span>'
        + '<span class="workspace-tab-count">(' + views.length + ')</span>';
      button.addEventListener('click', function (event) {
        var buttonEl = event.currentTarget;
        if (!buttonEl) return;
        var nextView = buttonEl.getAttribute('data-view');
        if (!nextView || nextView === state.currentView) return;
        state.currentView = nextView;
        renderWorkspaceTabs();
        renderViewDescription();
        renderCandidateList();
        var firstItem = getCurrentViewItems()[0] || null;
        renderCandidateDetail(firstItem);
        state.activeItem = firstItem;
      });
      nodes.tabs.appendChild(button);
    }
  }

  function renderViewDescription() {
    if (!nodes.description) return;
    var text = getCurrentDescription(state.currentView) || '';
    setTextNode(nodes.description, text);
  }

  function makeChip(text, className) {
    return '<span class="' + className + '">' + escapeHtml(text) + '</span>';
  }

  function renderCandidateList() {
    if (!nodes.candidateList) return;
    nodes.candidateList.innerHTML = '';

    var items = getCurrentViewItems();
    if (!items || items.length === 0) {
      nodes.candidateList.innerHTML = '<div class="candidate-empty">当前视图无候选。</div>';
      nodes.detailPanel.innerHTML = '<div class="detail-empty">当前视图无详情。</div>';
      return;
    }

    for (var i = 0; i < items.length; i += 1) {
      var item = items[i] || {};
      var row = document.createElement('button');
      var rankValue = safeNumber(item.view_rank, i + 1);
      var rank = (safeNumber(rankValue, i + 1) || i + 1);
      var code = normalizeString(item.code || '');
      var name = normalizeString(item.name || '');
      var sector = normalizeString(item.sector || '');
      var change = safeNumber(item.change_pct, null);
      var changeCls = '';
      if (change === null) {
        changeCls = '';
      } else if (change > 0) {
        changeCls = ' is-up';
      } else if (change < 0) {
        changeCls = ' is-down';
      }

      var sourceLabels = asArray(item.source_labels);
      if (sourceLabels.length === 0 && Array.isArray(item.sources)) {
        sourceLabels = item.sources.map(function (source) {
          return String(source || '');
        });
      }

      var resonance = normalizeString(item.resonance_label || '');
      var action = normalizeString(item.action || '');
      var riskFlags = asArray(item.risk_flags);

      var sourceHtml = '';
      for (var s = 0; s < sourceLabels.length; s += 1) {
        if (sourceLabels[s]) {
          sourceHtml += makeChip(sourceLabels[s], 'source-chip');
        }
      }
      if (resonance) {
        sourceHtml += makeChip(resonance, 'resonance-chip');
      }

      var actionCls = action.indexOf('慎追') !== -1 || action.indexOf('仅观察') !== -1 ? ' action-pill is-risk' : ' action-pill';

      row.type = 'button';
      row.className = 'candidate-row';
      row.setAttribute('data-code', code);
      row.setAttribute('data-name', name);
      row.innerHTML = ''
        + '<div class="candidate-row-main">'
        + '  <span class="candidate-rank">' + escapeHtml((i + 1).toString().padStart(2, '0')) + '</span>'
        + '  <span>'
        + '    <span class="candidate-name">' + escapeHtml(name || ('未命名 ' + String(code))) + '</span>'
        + '    <span class="candidate-code"> ' + escapeHtml(code) + '</span>'
        + (sector ? ' <span class="candidate-code">· ' + escapeHtml(sector) + '</span>' : '')
        + '  </span>'
        + '  <span class="candidate-change' + changeCls + '">' + escapeHtml(change === null ? '--' : formatPct(change, true)) + '</span>'
        + '  <span class="' + actionCls + '">' + escapeHtml(action || '待判定') + '</span>'
        + '</div>'
        + '<div class="candidate-row-sub">' + sourceHtml + '</div>'
        + (riskFlags.length > 0 ? ('<div class="candidate-row-risk">' + riskFlags.map(function (itemRisk) { return makeChip(itemRisk, 'risk-chip'); }).join('') + '</div>') : '')
      ;
      if (state.activeItem && state.activeItem.code === code) {
        row.classList.add('is-selected');
      }
      row.addEventListener('click', function (candidate) {
        return function () {
          state.activeItem = candidate;
          renderCandidateDetail(candidate);
          renderCandidateList();
          if (state.isMobile) {
            openMobileDetailDrawer(candidate);
          }
        };
      }(item));
      nodes.candidateList.appendChild(row);
    }
  }

  function buildConclusionSection(item, raw) {
    var sourceLabels = asArray(item.source_labels);
    if (sourceLabels.length === 0 && Array.isArray(item.sources)) {
      sourceLabels = item.sources.map(function (source) {
        return String(source || '');
      });
    }
    var action = normalizeString(item.action || '待确认');
    var actionClass = action.indexOf('慎追') !== -1 || action.indexOf('仅观察') !== -1 ? 'action-pill is-risk' : 'action-pill';

    var sourceHtml = '';
    for (var i = 0; i < sourceLabels.length; i += 1) {
      if (sourceLabels[i]) {
        sourceHtml += makeChip(sourceLabels[i], 'source-chip');
      }
    }
    if (item.resonance_label) {
      sourceHtml += makeChip(item.resonance_label, 'resonance-chip');
    }

    var conclusion = item.action_reason || item.primary_reason || '无明确结论说明';
    return ''
      + '<div class="detail-header">'
      + '  <div>'
      + '    <h2 class="detail-title">' + escapeHtml(normalizeString(item.name)) + '</h2>'
      + '    <p class="detail-subtitle">' + escapeHtml(normalizeString(item.code) + (item.sector ? (' · ' + item.sector) : '')) + '</p>'
      + '  </div>'
      + '  <div class="detail-meta">'
      + '    <span class="' + actionClass + '">' + escapeHtml(action) + '</span>'
      + sourceHtml
      + '  </div>'
      + '</div>'
      + '<div class="detail-section">'
      + '  <h3 class="detail-section-title">01 结论</h3>'
      + '  <div class="detail-section-body text-item">' + escapeHtml(conclusion) + '</div>'
      + '</div>';
  }

  function buildPriceSection(item, raw) {
    var currentPrice = safeNumber(item.current_price, null);
    if (currentPrice === null && raw && raw.current_price !== undefined) {
      currentPrice = safeNumber(raw.current_price, null);
    }
    if (currentPrice === null && raw && raw.close !== undefined) {
      currentPrice = safeNumber(raw.close, null);
    }

    var refPrice = safeNumber(item.reference_price, null);
    if (refPrice === null && raw && raw.reference_price !== undefined) {
      refPrice = safeNumber(raw.reference_price, null);
    }
    if (refPrice === null && raw && raw.current_price !== undefined && currentPrice !== null) {
      refPrice = safeNumber(raw.current_price, null);
    }

    var dist = safeNumber(item.distance_from_reference_pct, null);
    if (dist === null && refPrice !== null && currentPrice !== null && refPrice !== 0) {
      dist = ((currentPrice - refPrice) / refPrice) * 100;
    }

    var stopLoss = safeNumber(item.stop_loss, null);
    if (stopLoss === null && raw) {
      stopLoss = safeNumber(raw.stop_loss, null);
    }

    return ''
      + '<div class="detail-section">'
      + '  <h3 class="detail-section-title">02 价格</h3>'
      + '  <div class="detail-price-grid">'
      + '    <div class="price-cell"><div class="price-label">现价</div><div class="price-value">' + escapeHtml(currentPrice === null ? '--' : formatNumber(currentPrice, 2)) + '</div></div>'
      + '    <div class="price-cell"><div class="price-label">参考价</div><div class="price-value">' + escapeHtml(refPrice === null ? '--' : formatNumber(refPrice, 2)) + '</div></div>'
      + '    <div class="price-cell"><div class="price-label">距参考价</div><div class="price-value">' + escapeHtml(dist === null ? '--' : formatPct(dist, true)) + '</div></div>'
      + '    <div class="price-cell"><div class="price-label">止损</div><div class="price-value">' + escapeHtml(stopLoss === null ? '--' : formatNumber(stopLoss, 2)) + '</div></div>'
      + '  </div>'
      + '</div>';
  }

  function buildReasonSection(item, raw) {
    var lines = [];
    if (item.primary_reason) {
      lines.push(item.primary_reason);
    }
    if (item.action_reason) {
      lines.push(item.action_reason);
    }
    if (raw && raw.sublevel_confirm_reason) {
      lines.push(raw.sublevel_confirm_reason);
    }
    if (raw && raw.daily_startup_warning) {
      lines.push(raw.daily_startup_warning);
    }

    if (lines.length === 0) {
      lines.push('暂无关键理由说明。');
    }

    return ''
      + '<div class="detail-section">'
      + '  <h3 class="detail-section-title">04 理由</h3>'
      + '  <div class="detail-section-body">'
      + '    <ul>'
      + lines.map(function (line) { return '<li>' + escapeHtml(line) + '</li>'; }).join('')
      + '    </ul>'
      + '  </div>'
      + '</div>';
  }

  function buildRiskSection(item, raw) {
    var risks = asArray(item.risk_flags);
    if (risks.length === 0 && raw && Array.isArray(raw.growth_risk_flags)) {
      risks = asArray(raw.growth_risk_flags);
    }
    if (risks.length === 0 && raw && Array.isArray(raw.risk_flags)) {
      risks = asArray(raw.risk_flags);
    }
    if (risks.length === 0) {
      risks = ['暂无标记风险标签。'];
    }
    return ''
      + '<div class="detail-section">'
      + '  <h3 class="detail-section-title">05 风险</h3>'
      + '  <div class="detail-section-body">'
      + '    <ul>'
      + risks.map(function (line) { return '<li class="risk-chip">' + escapeHtml(line) + '</li>'; }).join('')
      + '    </ul>'
      + '  </div>'
      + '</div>';
  }

  function buildDetailsSection(item, raw) {
    var details = [];
    if (item.code) details.push('代码：' + item.code);
    if (item.sector) details.push('板块：' + item.sector);
    if (item.distance_from_reference_pct !== undefined) details.push('距参考价：' + formatPct(item.distance_from_reference_pct, true));
    if (item.watch_score !== undefined) details.push('权重：' + formatNumber(item.watch_score, 0));
    if (raw && raw.daily_startup_grade) details.push('启动评级：' + raw.daily_startup_grade);
    if (raw && raw.source_type) details.push('来源类型：' + raw.source_type);
    if (raw && raw.signal_age_days !== undefined && raw.signal_age_days !== null) details.push('信号年龄：' + raw.signal_age_days + ' 个交易日');
    if (raw && raw.confirm_age_days !== undefined && raw.confirm_age_days !== null) details.push('确认年龄：' + raw.confirm_age_days + ' 个交易日');
    if (raw && raw.buy_points_30min && raw.buy_points_30min.length > 0) {
      details.push('30min 点：' + raw.buy_points_30min.length);
    }
    if (raw && raw.volume_ratio !== undefined && raw.volume_ratio !== null) {
      details.push('量能比：' + formatNumber(raw.volume_ratio, 2));
    }

    if (details.length === 0) {
      details.push('暂无补充细节。');
    }

    return ''
      + '<div class="detail-section">'
      + '  <h3 class="detail-section-title">06 细节</h3>'
      + '  <div class="detail-section-body">'
      + '    <ul>'
      + details.map(function (line) { return '<li>' + escapeHtml(line) + '</li>'; }).join('')
      + '    </ul>'
      + '  </div>'
      + '</div>';
  }

  function buildChartPlaceholder() {
    return ''
      + '<div class="detail-section">'
      + '  <h3 class="detail-section-title">03 图表</h3>'
      + '  <div class="chart-panel">'
      + '    <div id="chartCanvas" class="chart-canvas"></div>'
      + '  </div>'
      + '</div>';
  }

  function renderCandidateDetail(item, target) {
    target = target || nodes.detailPanel;
    if (!target) return;

    if (!item) {
      target.innerHTML = '<div class="detail-empty">当前视图尚无可选候选。</div>';
      return;
    }

    var raw = findRawCandidate(item.ref || {});
    target.innerHTML = ''
      + '<div class="detail-empty-wrap">'
      + buildConclusionSection(item, raw)
      + buildPriceSection(item, raw)
      + buildChartPlaceholder()
      + buildReasonSection(item, raw)
      + buildRiskSection(item, raw)
      + buildDetailsSection(item, raw)
      + '</div>';
    state.chartMount = target.querySelector('#chartCanvas');
    renderChart(raw, item);
  }

  function renderChart(raw, workspaceItem) {
    if (!state.chartMount) return;
    if (!window.echarts) {
      state.chartMount.innerHTML = '<div class="chart-empty">未检测到 ECharts 加载环境。</div>';
      return;
    }

    if (state.chartInstance) {
      state.chartInstance.dispose();
      state.chartInstance = null;
    }

    if (!raw) {
      state.chartMount.innerHTML = '<div class="chart-empty">' + escapeHtml(CHART_EMPTY_TEXT) + '</div>';
      return;
    }

    var dates = asArray(raw.dates);
    var opens = asArray(raw.opens);
    var highs = asArray(raw.highs);
    var lows = asArray(raw.lows);
    var closes = asArray(raw.closes);
    var macd = asArray(raw.macd_hist);
    var minLen = Math.min(dates.length, opens.length, highs.length, lows.length, closes.length);
    if (minLen < 2) {
      state.chartMount.innerHTML = '<div class="chart-empty">' + escapeHtml(CHART_EMPTY_TEXT) + '</div>';
      return;
    }

    var xAxis = dates.slice(0, minLen);
    var kLines = [];
    for (var i = 0; i < minLen; i += 1) {
      kLines.push([
        opens[i],
        closes[i],
        lows[i],
        highs[i],
      ]);
    }

    var macdSlice = [];
    var macdLen = Math.min(minLen, macd.length);
    for (var m = 0; m < macdLen; m += 1) {
      macdSlice.push(macd[m]);
    }
    if (macdLen > minLen) {
      macdSlice = macdSlice.slice(-minLen);
    }
    while (macdSlice.length < minLen) {
      macdSlice.push(0);
    }

    var markPoints = [];
    var annotations = raw.chart_annotations || {};
    var rawMarkPoints = asArray(annotations.markPoints);
    for (var p = 0; p < rawMarkPoints.length; p += 1) {
      var mp = rawMarkPoints[p] || {};
      var coord = mp.coord || [];
      if (coord.length >= 2) {
        markPoints.push({
          coord: [coord[0], coord[1]],
          name: normalizeString(mp.name),
          value: coord[1],
          itemStyle: mp.itemStyle || {},
          label: mp.label || {},
          symbol: mp.symbol || 'pin',
          symbolSize: mp.symbolSize || 16,
        });
      }
    }

    var markLines = [];
    var rawMarkLines = asArray(annotations.markLines);
    for (var l = 0; l < rawMarkLines.length; l += 1) {
      var ml = rawMarkLines[l] || {};
      if (ml && ml.name && ml.yAxis !== undefined) {
        markLines.push({
          name: normalizeString(ml.name),
          yAxis: ml.yAxis,
          label: ml.label || {},
          lineStyle: ml.lineStyle || {},
        });
      }
    }

    var refPrice = safeNumber(workspaceItem.reference_price, null);
    if (refPrice === null && raw.reference_buy_points && raw.reference_buy_points.length > 0) {
      refPrice = safeNumber(raw.reference_buy_points[0].reference_price, null);
    }
    var curPrice = safeNumber(workspaceItem.current_price, null);
    if (curPrice === null) {
      curPrice = safeNumber(raw.current_price, safeNumber(raw.close, null));
    }
    if (refPrice !== null) {
      markLines.push({
        name: '参考价',
        yAxis: refPrice,
        label: { show: true, position: 'middle', formatter: '参考 ' + formatNumber(refPrice, 2) },
      });
    }
    if (curPrice !== null) {
      markLines.push({
        name: '现价',
        yAxis: curPrice,
        label: { show: true, position: 'end', formatter: '现价 ' + formatNumber(curPrice, 2) },
      });
    }

    state.chartInstance = window.echarts.init(state.chartMount);
    state.chartInstance.setOption({
      animation: false,
      backgroundColor: '#ffffff',
      grid: [
        { left: '6%', right: '6%', top: '8%', height: '58%' },
        { left: '6%', right: '6%', top: '72%', height: '20%' },
      ],
      xAxis: [
        {
          type: 'category',
          data: xAxis,
          boundaryGap: true,
          axisLine: { lineStyle: { color: '#d1d5db' } },
          splitLine: { show: false },
        },
        {
          type: 'category',
          data: xAxis,
          gridIndex: 1,
          boundaryGap: true,
          axisLine: { lineStyle: { color: '#d1d5db' } },
          splitLine: { show: false },
        },
      ],
      yAxis: [
        {
          scale: true,
          splitLine: { lineStyle: { color: '#f3f4f6' } },
          axisLine: { lineStyle: { color: '#d1d5db' } },
        },
        {
          scale: true,
          gridIndex: 1,
          splitLine: { lineStyle: { color: '#f3f4f6' } },
          axisLine: { lineStyle: { color: '#d1d5db' } },
        },
      ],
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
      },
      dataZoom: [
        { type: 'inside', xAxisIndex: [0, 1], start: 0, end: 100 },
        { xAxisIndex: [0, 1], height: 18, start: 0, end: 100 },
      ],
      series: [
        {
          name: 'K线',
          type: 'candlestick',
          data: kLines,
          markPoint: {
            data: markPoints,
          },
          markLine: {
            symbol: 'none',
            data: markLines.map(function (line) {
              return {
                name: line.name,
                yAxis: line.yAxis,
                label: {
                  show: true,
                  color: '#374151',
                  ...line.label,
                },
                lineStyle: {
                  color: '#9ca3af',
                  width: 1,
                  type: 'dashed',
                  ...(line.lineStyle || {}),
                },
              };
            }),
          },
          itemStyle: {
            color: '#EF4444',
            color0: '#10B981',
            borderColor: '#EF4444',
            borderColor0: '#10B981',
          },
        },
        {
          name: 'MACD',
          type: 'bar',
          xAxisIndex: 1,
          yAxisIndex: 1,
          data: macdSlice,
          itemStyle: {
            color: function (params) {
              if (params && params.value === null) return '#94a3b8';
              return params.value >= 0 ? '#EF4444' : '#10B981';
            },
          },
        },
      ],
    }, true);
    setTimeout(function () {
      if (state.chartInstance) {
        state.chartInstance.resize();
      }
    }, 0);
  }

  function renderAuxiliarySection(title, rows) {
    var list = asArray(rows);
    if (list.length === 0) {
      return ''
        + '<section class="aux-module">'
        + '  <h3>' + escapeHtml(title) + '</h3>'
        + '  <div class="text-item aux-empty">暂无数据</div>'
        + '</section>';
    }
    return ''
      + '<section class="aux-module">'
      + '  <h3>' + escapeHtml(title) + '</h3>'
      + '  <ul>'
      + list.map(function (item) { return '<li>' + escapeHtml(item) + '</li>'; }).join('')
      + '  </ul>'
      + '</section>';
  }

  function renderAuxiliaryCenter() {
    if (!nodes.auxGrid) return;
    var data = state.data || {};

    var marketRows = [];
    var market = data.market || {};
    Object.keys(market).forEach(function (name) {
      var rec = market[name] || {};
      if (rec.change_pct !== undefined && rec.close !== undefined) {
        marketRows.push(name + '：' + formatNumber(rec.close, 2) + ' ' + formatPct(rec.change_pct, true));
      }
    });
    if (marketRows.length === 0) marketRows.push('暂无市场数据');

    var sectorRows = [];
    var sectorIn = asArray(data.sector_flow).slice(0, 5);
    var sectorOut = asArray(data.sector_outflow).slice(0, 5);
    for (var i = 0; i < sectorIn.length; i += 1) {
      sectorRows.push('入场 ' + normalizeString(sectorIn[i].name) + '：' + normalizeString(sectorIn[i].flow_str || formatNumber(sectorIn[i].flow, 2)));
    }
    for (var o = 0; o < sectorOut.length; o += 1) {
      sectorRows.push('流出 ' + normalizeString(sectorOut[o].name) + '：' + normalizeString(sectorOut[o].flow_str || formatNumber(sectorOut[o].flow, 2)));
    }
    if (sectorRows.length === 0) sectorRows.push('暂无板块净流向信息');

    var limitRows = asArray(data.limit_up_pool).slice(0, 6).map(function (item) {
      return normalizeString(item.name) + ' ' + normalizeString(item.code) + ' (' + normalizeString(item.reason || '无') + ')';
    });
    if (limitRows.length === 0) limitRows.push('暂无涨停池');

    var eventsRows = asArray(data.events).slice(0, 6).map(function (item) {
      return normalizeString(item.title || item.display_title || '未命名事件') + '：' + normalizeString(item.impact && item.impact.summary ? item.impact.summary : item.summary || item.brief || '');
    });
    if (eventsRows.length === 0) eventsRows.push('暂无事件');

    var sellRows = asArray(data.sell_signals).slice(0, 6).map(function (item) {
      return normalizeString(item.name) + ' ' + normalizeString(item.code) + '：' + normalizeString(item.sell_points && item.sell_points.length ? item.sell_points[0].reason : '暂无卖出理由');
    });
    if (sellRows.length === 0) sellRows.push('暂无卖出信号');

    var reviewRows = asArray(data.recent_reviews).slice(0, 6).map(function (item) {
      return normalizeString(item.name) + ' ' + normalizeString(item.code) + '：' + formatPct(item.change_pct, true);
    });
    if (reviewRows.length === 0) reviewRows.push('暂无回看记录');

    var diagRows = [];
    var diagnostics = data.diagnostics || {};
    Object.keys(diagnostics).forEach(function (key) {
      var value = diagnostics[key];
      if (value && typeof value === 'object') {
        diagRows.push(key + '：' + normalizeString(value.status || value.summary || '已记录'));
      } else {
        diagRows.push(key + '：' + normalizeString(value));
      }
    });
    if (diagRows.length === 0) diagRows.push('暂无诊断信息');

    nodes.auxGrid.innerHTML = ''
      + renderAuxiliarySection('市场', marketRows)
      + renderAuxiliarySection('板块', sectorRows)
      + renderAuxiliarySection('涨停', limitRows)
      + renderAuxiliarySection('事件', eventsRows)
      + renderAuxiliarySection('卖出', sellRows)
      + renderAuxiliarySection('回看', reviewRows)
      + renderAuxiliarySection('诊断', diagRows);
  }

  function openMobileDetailDrawer(item) {
    if (!state.isMobile || !nodes.drawer) return;
    if (item) {
      state.activeItem = item;
    }
    if (!state.activeItem) return;
    nodes.drawerContent.innerHTML = '';
    renderCandidateDetail(state.activeItem, nodes.drawerContent);
    nodes.drawer.classList.add('is-open');
    document.body.style.overflow = 'hidden';
    setTimeout(function () {
      if (state.chartInstance) {
        state.chartInstance.resize();
      }
    }, 40);
  }

  function closeMobileDetailDrawer() {
    if (!nodes.drawer) return;
    nodes.drawer.classList.remove('is-open');
    document.body.style.overflow = '';
  }

  function renderGlobalError(message) {
    if (!nodes.globalError || !nodes.shell) return;
    nodes.globalError.classList.remove('hidden');
    setTextNode(nodes.globalError, message || '报告加载失败');
  }

  function syncViewport() {
    state.isMobile = isMobileViewport();
  }

  function getQueryParam(name) {
    try {
      var params = new URLSearchParams(window.location.search || '');
      return params.get(name) || '';
    } catch (err) {
      return '';
    }
  }

  function bytesToHex(buffer) {
    var bytes = new Uint8Array(buffer);
    var out = '';
    for (var i = 0; i < bytes.length; i += 1) {
      out += bytes[i].toString(16).padStart(2, '0');
    }
    return out;
  }

  function sha256Hex(text) {
    if (!window.crypto || !window.crypto.subtle || !window.TextEncoder) {
      return Promise.resolve('');
    }
    return window.crypto.subtle.digest('SHA-256', new TextEncoder().encode(text)).then(bytesToHex);
  }

  function resolveGranted() {
    var bootstrap = getBootstrap();
    if (!bootstrap.accessControlEnabled) {
      return Promise.resolve(true);
    }
    if (!bootstrap.accessKeyHash) {
      return Promise.resolve(false);
    }
    if (bootstrap.isFileProtocol) {
      return Promise.resolve(true);
    }

    var stored = '';
    try {
      stored = window.localStorage ? window.localStorage.getItem('chanlun_daily_access') || '' : '';
    } catch (err) {
      stored = '';
    }
    if (stored === bootstrap.accessKeyHash) {
      return Promise.resolve(true);
    }

    var key = getQueryParam('key');
    if (!key) {
      return Promise.resolve(false);
    }
    return sha256Hex(key + (bootstrap.accessKeySalt || '')).then(function (digest) {
      var granted = digest === bootstrap.accessKeyHash;
      if (granted) {
        try {
          if (window.localStorage) {
            window.localStorage.setItem('chanlun_daily_access', bootstrap.accessKeyHash);
          }
        } catch (err) {}
      }
      return granted;
    });
  }

  function resolveInitialData() {
    var bootstrap = getBootstrap();
    if (!state.granted && bootstrap.dataBasePrefix) {
      return Promise.reject(new Error('暂无日报数据'));
    }
    if (window.REPORT_DATA) {
      return Promise.resolve(window.REPORT_DATA);
    }
    if (bootstrap.inlineReportData) {
      return Promise.resolve(bootstrap.inlineReportData);
    }
    if (window.INLINE_REPORT_DATA) {
      return Promise.resolve(window.INLINE_REPORT_DATA);
    }
    var date = bootstrap.pageDate || formatDateLabel(new Date().toISOString());
    var url = detectDataUrl(date);
    if (!window.fetch) {
      return Promise.reject(new Error('当前环境不支持 fetch，且无内联 REPORT_DATA。'));
    }
    return window.fetch(url).then(function (resp) {
      if (!resp || !resp.ok) {
        throw new Error('加载日报 JSON 失败：' + url);
      }
      return resp.json();
    });
  }

  function normalizeWorkspace(data) {
    var ws = data && data.workspace ? data.workspace : null;
    if (!ws) {
      state.workspace = {
        default_view: 'highlights',
        view_order: DEFAULT_VIEW_ORDER,
        view_meta: {},
        views: {},
      };
      return;
    }

    state.workspace = ws;
    state.currentView = ws.default_view || state.currentView;
    if (!state.currentView) state.currentView = 'highlights';
  }

  function initReportV2() {
    syncViewport();
    state.isMobile = isMobileViewport();
    buildAppShell();
    state.rawPoolCandidates = null;

    resolveGranted().then(function (granted) {
      state.granted = granted;
      return resolveInitialData();
    }).then(function (data) {
      state.data = data || {};
      window.REPORT_DATA = state.data;
      normalizeWorkspace(state.data);
      state.currentView = state.workspace && state.workspace.default_view ? state.workspace.default_view : 'highlights';
      renderHeader();
      renderWorkspaceTabs();
      renderViewDescription();
      renderCandidateList();
      var first = getCurrentViewItems()[0] || null;
      renderCandidateDetail(first);
      state.activeItem = first;
      renderAuxiliaryCenter();
      if (state.isMobile && first) {
        nodes.detailPanel.innerHTML = '<div class="detail-empty">选择后查看详情</div>';
      }
    }).catch(function (error) {
      renderGlobalError(error && error.message ? error.message : '加载失败');
    });

    if (nodes.drawerBackdrop) {
      nodes.drawerBackdrop.addEventListener('click', closeMobileDetailDrawer);
    }
    if (nodes.drawer && nodes.drawer.querySelector('#mobileDrawerClose')) {
      nodes.drawer.querySelector('#mobileDrawerClose').addEventListener('click', function () {
        closeMobileDetailDrawer();
      });
    }

    window.addEventListener('resize', function () {
      syncViewport();
      if (state.chartInstance) {
        state.chartInstance.resize();
      }
    });
  }

  window.initReportV2 = initReportV2;
  window.renderHeader = renderHeader;
  window.renderWorkspaceTabs = renderWorkspaceTabs;
  window.renderViewDescription = renderViewDescription;
  window.renderCandidateList = renderCandidateList;
  window.renderCandidateDetail = renderCandidateDetail;
  window.openMobileDetailDrawer = openMobileDetailDrawer;
  window.closeMobileDetailDrawer = closeMobileDetailDrawer;
  window.findRawCandidate = findRawCandidate;
  window.renderChart = renderChart;
  window.renderAuxiliaryCenter = renderAuxiliaryCenter;
  window.resolveGranted = resolveGranted;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initReportV2);
  } else {
    initReportV2();
  }
})();
