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

  function clamp(value, min, max) {
    var num = safeNumber(value, null);
    if (num === null) return min;
    return Math.max(min, Math.min(max, num));
  }

  function getActionClass(action) {
    if (action === '可上车') return 'tag tag-action-buy';
    if (action === '等回踩') return 'tag tag-action-wait';
    if (action === '盯盘') return 'tag tag-action-watch';
    if (action === '慎追') return 'tag tag-action-risk';
    if (action === '仅观察') return 'tag tag-action-neutral';
    return 'tag tag-action-neutral';
  }

  function getRiskClass(risk) {
    var label = normalizeString(risk);
    if (label.indexOf('过热') !== -1) return 'tag tag-risk is-hot';
    if (label.indexOf('过期') !== -1) return 'tag tag-risk is-expiry';
    return 'tag tag-risk';
  }

  function getSourceClass(label) {
    var text = normalizeString(label);
    if (text === '主推') return 'tag tag-main';
    if (text === '加速') return 'tag tag-acceleration';
    if (text === '罗姐池') return 'tag tag-luojie';
    if (text === '等确认') return 'tag tag-confirming';
    if (text === '基准') return 'tag tag-baseline';
    return 'tag tag-baseline';
  }

  function getRankClass(rank) {
    var value = safeNumber(rank, 0);
    if (value === 1) return 'rank-badge rank-01';
    if (value === 2) return 'rank-badge rank-02';
    if (value === 3) return 'rank-badge rank-03';
    return 'rank-badge rank-normal';
  }

  function getResonanceClass(label) {
    var text = normalizeString(label);
    if (text === '强共振') return 'tag tag-resonance is-strong';
    if (text === '共振·防守') return 'tag tag-resonance is-defensive';
    return 'tag tag-resonance';
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
      + '  <header class="report-header market-header">'
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
      + '  <section class="aux-center decision-center">'
      + '    <details id="auxCenter" open>'
      + '      <summary>'
      + '        <span><strong>辅助决策中心</strong><small>市场、资金、情绪、事件、风险、回看、诊断</small></span>'
      + '      </summary>'
      + '      <div class="aux-grid decision-grid" id="auxGrid"></div>'
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
    var summary = buildMarketSummary(data.market || {});

    setTextNode(nodes.headerTitle, '缠论策略日报');
    setTextNode(nodes.headerSubtitle, dateLabel + ' · 交易观测台');
    nodes.headerMetrics.innerHTML = renderMarketRegime(summary) + renderMarketIndexCards(summary.items);
  }

  function getMarketItems(market) {
    var source = market || {};
    return Object.keys(source).map(function (name) {
      var rec = source[name] || {};
      return {
        name: normalizeString(name),
        close: safeNumber(rec.close, null),
        change_pct: safeNumber(rec.change_pct, null),
        date: normalizeString(rec.date || ''),
        source: normalizeString(rec.source || ''),
      };
    }).filter(function (item) {
      return item.close !== null || item.change_pct !== null;
    });
  }

  function buildMarketSummary(market) {
    var items = getMarketItems(market);
    if (items.length === 0) {
      return {
        status: '数据不足',
        tone: 'neutral',
        pace: '暂不判断',
        note: '暂无市场指数数据',
        avgChange: null,
        upCount: 0,
        downCount: 0,
        best: null,
        worst: null,
        items: [],
      };
    }

    var validChanges = items.filter(function (item) {
      return item.change_pct !== null;
    });
    var total = validChanges.reduce(function (sum, item) {
      return sum + item.change_pct;
    }, 0);
    var avgChange = validChanges.length ? total / validChanges.length : null;
    var upCount = validChanges.filter(function (item) {
      return item.change_pct > 0;
    }).length;
    var downCount = validChanges.filter(function (item) {
      return item.change_pct < 0;
    }).length;
    var sorted = validChanges.slice().sort(function (a, b) {
      return b.change_pct - a.change_pct;
    });
    var best = sorted[0] || null;
    var worst = sorted[sorted.length - 1] || null;
    var status = '震荡';
    var tone = 'neutral';
    var pace = '精选等待';

    if (avgChange === null) {
      status = '数据不足';
      tone = 'neutral';
      pace = '暂不判断';
    } else if (avgChange >= 1.0 && upCount >= 4) {
      status = '偏强';
      tone = 'positive';
      pace = '积极观察';
    } else if (avgChange >= 0.3 && upCount >= downCount) {
      status = '修复';
      tone = 'info';
      pace = '轻仓试错';
    } else if (avgChange <= -0.3 || downCount > upCount) {
      status = '偏弱';
      tone = 'danger';
      pace = '防守观察';
    }

    return {
      status: status,
      tone: tone,
      pace: pace,
      note: buildMarketStyleHint(best),
      avgChange: avgChange,
      upCount: upCount,
      downCount: downCount,
      best: best,
      worst: worst,
      items: items,
    };
  }

  function buildMarketStyleHint(best) {
    if (!best) return '风格不明确，继续观察。';
    if (best.name === '科创50' && best.change_pct > 1.5) {
      return '科创50领涨，成长风格占优。';
    }
    if (best.name === '创业板指' && best.change_pct > 1.0) {
      return '创业板活跃，题材修复较强。';
    }
    if (best.name === '沪深300') {
      return '沪深300领先，权重修复较强。';
    }
    if (best.name === '中证500') {
      return '中证500领先，中小盘扩散较好。';
    }
    return best.name + '相对领先，继续观察持续性。';
  }

  function getMarketTemperatureLabel(score) {
    if (score >= 90) return '过热';
    if (score >= 75) return '热';
    if (score >= 60) return '偏强';
    if (score >= 45) return '平衡';
    if (score >= 30) return '偏冷';
    return '冰点';
  }

  function getMarketTemperatureTone(score) {
    if (score >= 90) return 'overheat';
    if (score >= 75) return 'hot';
    if (score >= 60) return 'strong';
    if (score >= 45) return 'neutral';
    if (score >= 30) return 'cold';
    return 'ice';
  }

  function getMarketTemperatureSummary(score) {
    if (score >= 90) return '市场热度较高，追高与追击迹象明显，请严格控位。';
    if (score >= 75) return '市场偏热，机会较多，但注意控制回撤。';
    if (score >= 60) return '市场温度偏强，积极观察可执行机会。';
    if (score >= 45) return '市场温度平衡，精选优质标的。';
    if (score >= 30) return '市场偏冷，优先等待更强信号。';
    return '市场温度较冷，防守和筛选效率优先。';
  }

  function buildMarketTemperature(data) {
    data = data || {};
    var market = data.market || {};
    var marketItems = getMarketItems(market);
    var items = asArray(marketItems);
    var validItems = items.filter(function (item) {
      return item.change_pct !== null;
    });
    var advanceCount = safeNumber(data.advance_count, null);
    var declineCount = safeNumber(data.decline_count, null);
    var flatCount = safeNumber(data.flat_count, null);
    var limitUpCount = asArray(data.limit_up_pool).length;
    var limitDownCount = safeNumber(data.limit_down_count, 0);
    var prevLimitUpCount = safeNumber(data.prev_limit_up_count, null);
    var turnover = safeNumber(data.turnover, null);
    var prevTurnover = safeNumber(data.prev_turnover, null);
    var turnoverMA5 = safeNumber(data.turnover_ma5, null);
    var sectorIn = asArray(data.sector_flow);
    var sectorOut = asArray(data.sector_outflow);
    var diagnosticsHasError = data.diagnostics && data.diagnostics.error ? true : false;
    var sellSignals = asArray(data.sell_signals);
    var rawTemperature = data.market_temperature || {};

    if (Number.isFinite(safeNumber(rawTemperature.score, NaN))) {
      var preScore = clamp(rawTemperature.score, 0, 100);
      var preComponents = rawTemperature.components || {};
      return {
        score: preScore,
        label: getMarketTemperatureLabel(preScore),
        tone: getMarketTemperatureTone(preScore),
        components: {
          breadth_score: safeNumber(preComponents.breadth_score, 50),
          index_score: safeNumber(preComponents.index_score, 50),
          limit_score: safeNumber(preComponents.limit_score, 50),
          volume_score: safeNumber(preComponents.volume_score, 55),
          sector_score: safeNumber(preComponents.sector_score, 50),
          risk_penalty: safeNumber(preComponents.risk_penalty, 0),
        },
        summary: normalizeString(rawTemperature.summary || getMarketTemperatureSummary(preScore)),
      };
    }

    var avgIndexChange = 0;
    if (validItems.length > 0) {
      avgIndexChange = validItems.reduce(function (sum, item) {
        return sum + item.change_pct;
      }, 0) / validItems.length;
    }
    var indexScore = validItems.length > 0 ? clamp(50 + avgIndexChange * 18, 0, 100) : 50;

    var breadthScore = 50;
    if (advanceCount !== null && declineCount !== null) {
      var denom = advanceCount + declineCount + (flatCount !== null ? flatCount : 0);
      if (denom > 0) {
        breadthScore = clamp((advanceCount / denom) * 100, 0, 100);
      }
    } else if (validItems.length > 0) {
      var upCount = validItems.filter(function (item) {
        return item.change_pct > 0;
      }).length;
      breadthScore = clamp((upCount / validItems.length) * 100, 0, 100);
    }

    var limitScore = clamp(50 + limitUpCount * 2, 0, 90);
    if (prevLimitUpCount !== null) {
      limitScore = clamp(limitScore + clamp((limitUpCount - prevLimitUpCount) * 0.8, -10, 10), 0, 90);
    }

    var volumeScore = 55;
    var volumeRatio = 1;
    if (turnover !== null && turnoverMA5 !== null && turnoverMA5 !== 0) {
      volumeRatio = turnover / turnoverMA5;
      volumeScore = clamp(50 + (volumeRatio - 1) * 80, 20, 90);
    } else if (turnover !== null && prevTurnover !== null && prevTurnover !== 0) {
      volumeRatio = turnover / prevTurnover;
      volumeScore = clamp(50 + (volumeRatio - 1) * 80, 20, 90);
    }

    var sectorScore;
    if (sectorIn.length === 0 && sectorOut.length === 0) {
      sectorScore = 50;
    } else {
      var sectorScoreByValue = null;
      var inCount = 0;
      var outCount = 0;
      var netSectorFlow = 0;
      for (var i = 0; i < sectorIn.length; i += 1) {
        var inItem = sectorIn[i] || {};
        var inFlow = safeNumber(inItem.flow, safeNumber(inItem.net_flow, safeNumber(inItem.amount, null)));
        if (inFlow !== null) {
          sectorScoreByValue = 0;
          if (inFlow > 0) {
            inCount += 1;
          }
          netSectorFlow += inFlow;
        }
      }
      for (var j = 0; j < sectorOut.length; j += 1) {
        var outItem = sectorOut[j] || {};
        var outFlow = safeNumber(outItem.flow, safeNumber(outItem.net_flow, safeNumber(outItem.amount, null)));
        if (outFlow !== null) {
          sectorScoreByValue = 0;
          if (outFlow < 0) {
            outCount += 1;
          }
          netSectorFlow += outFlow;
        }
      }

      if (sectorScoreByValue === 0) {
        sectorScore = clamp(50 + inCount * 4 - outCount * 3, 20, 85);
      } else {
        sectorScore = clamp(50 + netSectorFlow / 10, 20, 85);
      }
    }

    var hotRiskCount = 0;
    var allRisks = [];
    if (Array.isArray(data.hot_risk_flags)) {
      allRisks = data.hot_risk_flags.slice(0);
    }
    for (var r = 0; r < allRisks.length; r += 1) {
      if (normalizeString(allRisks[r]).indexOf('涨幅过热') !== -1) {
        hotRiskCount += 1;
      }
    }
    var riskPenalty = Math.min(15, sellSignals.length * 1.5);
    riskPenalty += Math.min(10, hotRiskCount * 1);
    riskPenalty += limitDownCount ? Math.min(12, limitDownCount * 1.2) : 0;
    riskPenalty += diagnosticsHasError ? 10 : 0;

    if (rawTemperature.risk_penalty !== undefined && rawTemperature.risk_penalty !== null) {
      riskPenalty = clamp(rawTemperature.risk_penalty, 0, 30);
    }

    var rawScore =
      breadthScore * 0.30
      + indexScore * 0.20
      + limitScore * 0.20
      + volumeScore * 0.15
      + sectorScore * 0.10
      - riskPenalty * 0.05;

    var score = Math.round(clamp(rawScore, 0, 100));
    return {
      score: score,
      label: getMarketTemperatureLabel(score),
      tone: getMarketTemperatureTone(score),
      components: {
        breadth_score: Math.round(breadthScore),
        index_score: Math.round(indexScore),
        limit_score: Math.round(limitScore),
        volume_score: Math.round(volumeScore),
        sector_score: Math.round(sectorScore),
        risk_penalty: Math.round(riskPenalty),
      },
      summary: getMarketTemperatureSummary(score),
    };
  }

  function renderMarketRegime(summary) {
    var avgText = summary.avgChange === null ? '--' : formatPct(summary.avgChange, true);
    var widthText = summary.upCount + '/' + summary.items.length;
    return ''
      + '<div class="market-regime-row">'
      + '  <div class="market-regime-card">'
      + '    <span class="market-label">市场状态</span>'
      + '    <strong class="market-value is-' + escapeHtml(summary.tone) + '">' + escapeHtml(summary.status) + '</strong>'
      + '    <span class="market-note">' + escapeHtml(summary.note) + '</span>'
      + '  </div>'
      + '  <div class="market-regime-card">'
      + '    <span class="market-label">操作节奏</span>'
      + '    <strong class="market-value">' + escapeHtml(summary.pace) + '</strong>'
      + '    <span class="market-note">主推与共振优先，风险标签优先过滤。</span>'
      + '  </div>'
      + '  <div class="market-regime-card">'
      + '    <span class="market-label">市场广度</span>'
      + '    <strong class="market-value">' + escapeHtml(widthText) + '</strong>'
      + '    <span class="market-note">平均涨幅 ' + escapeHtml(avgText) + '</span>'
      + '  </div>'
      + '</div>';
  }

  function renderMarketIndexCards(items) {
    var list = asArray(items);
    if (list.length === 0) {
      return '<div class="market-index-empty">暂无市场指数数据</div>';
    }
    return ''
      + '<div class="market-index-grid">'
      + list.map(function (item) {
        var change = safeNumber(item.change_pct, null);
        var tone = change === null ? 'flat' : change > 0 ? 'up' : change < 0 ? 'down' : 'flat';
        return ''
          + '<div class="market-index-card is-' + escapeHtml(tone) + '">'
          + '  <span class="market-index-name">' + escapeHtml(item.name) + '</span>'
          + '  <strong class="market-index-close">' + escapeHtml(item.close === null ? '--' : formatNumber(item.close, 2)) + '</strong>'
          + '  <span class="market-index-change">' + escapeHtml(change === null ? '--' : formatPct(change, true)) + '</span>'
          + '</div>';
      }).join('')
      + '</div>';
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
      var rankClass = getRankClass(rank);
      var changeCls = '';
      if (change === null) {
        changeCls = '';
      } else if (change > 0) {
        changeCls = 'is-up';
      } else if (change < 0) {
        changeCls = 'is-down';
      }

      var sourceLabels = asArray(item.source_labels);
      if (sourceLabels.length === 0 && Array.isArray(item.sources)) {
        sourceLabels = item.sources.map(function (source) {
          return String(source || '');
        });
      }

      var resonance = normalizeString(item.resonance_label || '');
      var action = normalizeString(item.action || '待判定');
      var riskFlags = asArray(item.risk_flags);

      var tagHtml = '';
      for (var s = 0; s < sourceLabels.length; s += 1) {
        if (sourceLabels[s]) {
          tagHtml += makeChip(sourceLabels[s], getSourceClass(sourceLabels[s]));
        }
      }
      if (resonance) {
        tagHtml += makeChip(resonance, getResonanceClass(resonance));
      }
      if (action) {
        tagHtml += makeChip(action, getActionClass(action));
      }

      for (var r = 0; r < riskFlags.length; r += 1) {
        if (riskFlags[r]) {
          tagHtml += makeChip(riskFlags[r], getRiskClass(riskFlags[r]));
        }
      }

      row.type = 'button';
      row.className = 'candidate-row';
      row.setAttribute('data-code', code);
      row.setAttribute('data-name', name);
      row.innerHTML = ''
        + '<div class="candidate-row-main">'
        + '  <span class="' + escapeHtml(rankClass) + '">' + escapeHtml((rank || i + 1).toString().padStart(2, '0')) + '</span>'
        + '  <div class="candidate-identity">'
        + '    <span class="candidate-name">' + escapeHtml(name || ('未命名 ' + String(code))) + '</span>'
        + '    <span class="candidate-code"> ' + escapeHtml(code) + '</span>'
        + (sector ? ' <span class="candidate-code">· ' + escapeHtml(sector) + '</span>' : '')
        + '  </div>'
        + '  <div class="candidate-price' + (changeCls ? ' ' + changeCls : '') + '">' + escapeHtml(change === null ? '--' : formatPct(change, true)) + '</div>'
        + '</div>'
        + '<div class="candidate-tags">' + tagHtml + '</div>'
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

  function renderStatusBadge(badge) {
    if (!badge || !badge.text) return '';
    var tone = normalizeString(badge.tone || 'neutral');
    return '<span class="status-badge is-' + escapeHtml(tone) + '">' + escapeHtml(badge.text) + '</span>';
  }

  function renderDecisionCard(config) {
    var className = normalizeString(config.className || '');
    var bodyHtml = config.bodyHtml || '<div class="decision-empty">暂无数据</div>';
    return ''
      + '<section class="decision-card ' + escapeHtml(className) + '">'
      + '  <div class="decision-card-head">'
      + '    <div>'
      + '      <h3>' + escapeHtml(config.title || '') + '</h3>'
      + '      <p>' + escapeHtml(config.subtitle || '') + '</p>'
      + '    </div>'
      + renderStatusBadge(config.badge)
      + '  </div>'
      + '  <div class="decision-card-body">' + bodyHtml + '</div>'
      + '</section>';
  }

  function renderMetricPair(label, value, className) {
    return ''
      + '<div class="metric-pair">'
      + '  <span>' + escapeHtml(label) + '</span>'
      + '  <strong class="' + escapeHtml(className || '') + '">' + escapeHtml(value) + '</strong>'
      + '</div>';
  }

  function renderMarketTemperatureCard(data) {
    var temperature = buildMarketTemperature(data || {});
    var components = temperature.components || {};
    var gaugeStyle = '--gauge-score: ' + escapeHtml(temperature.score) + ';';
    var body = ''
      + '<div class="market-temp-gauge is-' + escapeHtml(temperature.tone) + '" style="' + gaugeStyle + '">'
      + '  <div class="gauge-meter" aria-hidden="true"></div>'
      + '  <div class="gauge-value">' + escapeHtml(temperature.score + ' / 100') + '</div>'
      + '  <div class="gauge-summary">' + escapeHtml(temperature.summary) + '</div>'
      + '</div>'
      + '<div class="metric-pair-grid">'
      + renderMetricPair('市场温度', temperature.score + ' / 100', 'is-' + escapeHtml(temperature.tone))
      + renderMetricPair('广度得分', (components.breadth_score === null || components.breadth_score === undefined) ? '--' : components.breadth_score, '')
      + renderMetricPair('指数得分', (components.index_score === null || components.index_score === undefined) ? '--' : components.index_score, '')
      + renderMetricPair('涨停得分', (components.limit_score === null || components.limit_score === undefined) ? '--' : components.limit_score, '')
      + renderMetricPair('量能得分', (components.volume_score === null || components.volume_score === undefined) ? '--' : components.volume_score, '')
      + renderMetricPair('板块得分', (components.sector_score === null || components.sector_score === undefined) ? '--' : components.sector_score, '')
      + renderMetricPair('风险扣分', (components.risk_penalty === null || components.risk_penalty === undefined) ? '--' : components.risk_penalty, components.risk_penalty > 0 ? 'is-weak' : '')
      + '</div>';
    return renderDecisionCard({
      title: '市场温度',
      subtitle: '指数、宽度、情绪的复合温度',
      badge: { text: temperature.label, tone: temperature.tone },
      className: 'market-temperature-card',
      bodyHtml: body,
    });
  }

  function renderFlowRow(kind, item) {
    var rec = item || {};
    var flow = rec.flow_str || rec.net_flow_str || rec.amount_str || formatNumber(rec.flow || rec.net_flow || rec.amount, 2);
    var tone = kind === '流入' ? 'in' : 'out';
    return ''
      + '<div class="flow-row">'
      + '  <span class="flow-chip is-' + escapeHtml(tone) + '">' + escapeHtml(kind) + '</span>'
      + '  <span class="flow-name">' + escapeHtml(normalizeString(rec.name || rec.sector || '--')) + '</span>'
      + '  <strong class="flow-value ' + (tone === 'in' ? 'is-up' : 'is-down') + '">' + escapeHtml(normalizeString(flow || '--')) + '</strong>'
      + '</div>';
  }

  function renderSectorFlowCard(data) {
    var sectorIn = asArray((data || {}).sector_flow).slice(0, 5);
    var sectorOut = asArray((data || {}).sector_outflow).slice(0, 5);
    var inHtml = sectorIn.length ? sectorIn.map(function (item) { return renderFlowRow('流入', item); }).join('') : '<div class="decision-empty">暂无流入数据</div>';
    var outHtml = sectorOut.length ? sectorOut.map(function (item) { return renderFlowRow('流出', item); }).join('') : '<div class="decision-empty">暂无流出数据</div>';
    var body = ''
      + '<div class="flow-columns">'
      + '  <div><div class="mini-section-title">流入 Top5</div>' + inHtml + '</div>'
      + '  <div><div class="mini-section-title">流出 Top5</div>' + outHtml + '</div>'
      + '</div>';
    return renderDecisionCard({
      title: '板块资金',
      subtitle: '资金流入与流出方向',
      badge: { text: sectorIn.length || sectorOut.length ? '资金方向' : '暂无', tone: sectorIn.length ? 'positive' : 'neutral' },
      className: 'sector-flow-card',
      bodyHtml: body,
    });
  }

  function renderLimitUpCard(data) {
    var rows = asArray((data || {}).limit_up_pool).slice(0, 6);
    var body = rows.length ? rows.map(function (item) {
      var rec = item || {};
      return ''
        + '<div class="stock-signal-row">'
        + '  <div class="stock-signal-main"><strong>' + escapeHtml(rec.name || '--') + '</strong><span>' + escapeHtml(rec.code || '') + '</span></div>'
        + '  <div class="stock-signal-reason"><span class="tag-chip">题材</span>' + escapeHtml(rec.reason || rec.note || '原因未标注') + '</div>'
        + '</div>';
    }).join('') : '<div class="decision-empty">暂无涨停池</div>';
    return renderDecisionCard({
      title: '涨停情绪',
      subtitle: '短线情绪观察',
      badge: { text: rows.length ? rows.length + '只' : '暂无', tone: rows.length ? 'warning' : 'neutral' },
      className: 'limit-up-card',
      bodyHtml: body,
    });
  }

  function renderEventsCard(data) {
    var rows = asArray((data || {}).events).slice(0, 6);
    var body = rows.length ? rows.map(function (item) {
      var rec = item || {};
      var summary = rec.impact && rec.impact.summary ? rec.impact.summary : (rec.summary || rec.brief || '暂无影响摘要');
      return ''
        + '<div class="event-row">'
        + '  <strong>' + escapeHtml(rec.title || rec.display_title || '未命名事件') + '</strong>'
        + '  <span class="event-summary">影响：' + escapeHtml(summary) + '</span>'
        + '</div>';
    }).join('') : '<div class="decision-empty">暂无事件</div>';
    return renderDecisionCard({
      title: '事件驱动',
      subtitle: '题材催化与影响摘要',
      badge: { text: rows.length ? '待确认' : '暂无', tone: rows.length ? 'info' : 'neutral' },
      className: 'events-card',
      bodyHtml: body,
    });
  }

  function renderSellSignalsCard(data) {
    var rows = asArray((data || {}).sell_signals).slice(0, 6);
    var body = rows.length ? rows.map(function (item) {
      var rec = item || {};
      var firstPoint = rec.sell_points && rec.sell_points.length ? rec.sell_points[0] : null;
      var reason = firstPoint && firstPoint.reason ? firstPoint.reason : (rec.reason || '暂无卖出理由');
      var action = firstPoint && firstPoint.action ? firstPoint.action : '优先处理';
      return ''
        + '<div class="stock-signal-row is-risk-row">'
        + '  <div class="stock-signal-main"><strong>' + escapeHtml(rec.name || '--') + '</strong><span>' + escapeHtml(rec.code || '') + '</span></div>'
        + '  <div class="stock-signal-reason"><span class="tag-chip is-risk">风险</span>' + escapeHtml(reason) + '</div>'
        + '  <div class="decision-note">动作：' + escapeHtml(action) + '</div>'
        + '</div>';
    }).join('') : '<div class="decision-empty">暂无卖出信号</div>';
    return renderDecisionCard({
      title: '卖出提醒',
      subtitle: '风险优先展示',
      badge: { text: rows.length ? '风险' : '暂无', tone: rows.length ? 'danger' : 'neutral' },
      className: 'sell-signals-card',
      bodyHtml: body,
    });
  }

  function getReviewName(rec) {
    return normalizeString(rec.name || rec.display_name || rec.stock_name || rec.code || '--');
  }

  function buildReviewMeta(rec) {
    var parts = [];
    var date = formatDateLabel(rec.rec_date || rec.date);
    var type = normalizeString(rec.type || rec.signal_type);
    var version = normalizeString(rec.version);
    if (date !== '--') parts.push('推荐日 ' + date);
    if (type) parts.push(type);
    if (version) parts.push(version);
    return parts.join(' · ') || '近期信号';
  }

  function buildReviewDataLine(rec) {
    var parts = [];
    var refPrice = safeNumber(rec.ref_price, null);
    var currentPrice = safeNumber(rec.current_price, null);
    var lookbackDays = safeNumber(rec.lookback_days, null);
    var triggerDate = normalizeString(rec.trigger_date);
    if (refPrice !== null) parts.push('推荐 ' + formatNumber(refPrice, 2));
    if (currentPrice !== null) parts.push('现价 ' + formatNumber(currentPrice, 2));
    if (lookbackDays !== null && lookbackDays > 0) parts.push('回看 ' + formatNumber(lookbackDays, 0) + '日');
    if (triggerDate) parts.push('触发 ' + formatDateLabel(triggerDate));
    return parts.join(' · ') || '暂无现价';
  }

  function buildReviewOutcome(rec) {
    var change = safeNumber(rec.change_pct, null);
    var refPrice = safeNumber(rec.ref_price, null);
    var currentPrice = safeNumber(rec.current_price, null);
    if (change === null && refPrice !== null && currentPrice !== null && refPrice !== 0) {
      change = ((currentPrice - refPrice) / refPrice) * 100;
    }
    if (change !== null) {
      return {
        text: formatPct(change, true),
        tone: change >= 0 ? 'is-up' : 'is-down'
      };
    }
    if (rec.stop_triggered === true) {
      return { text: '触止损', tone: 'is-down' };
    }
    if (normalizeString(rec.result || rec.outcome)) {
      return { text: normalizeString(rec.result || rec.outcome), tone: 'is-neutral' };
    }
    return { text: '暂无现价', tone: 'is-neutral' };
  }

  function renderRecentReviewsCard(data) {
    var rows = asArray((data || {}).recent_reviews).slice(0, 6);
    var body = rows.length ? rows.map(function (item) {
      var rec = item || {};
      var outcome = buildReviewOutcome(rec);
      return ''
        + '<div class="review-row">'
        + '  <div class="review-main">'
        + '    <strong>' + escapeHtml(getReviewName(rec)) + '</strong>'
        + '    <span>' + escapeHtml(rec.code || '') + '</span>'
        + '  </div>'
        + '  <div class="review-detail">'
        + '    <span>' + escapeHtml(buildReviewMeta(rec)) + '</span>'
        + '    <small>' + escapeHtml(buildReviewDataLine(rec)) + '</small>'
        + '  </div>'
        + '  <strong class="review-outcome ' + outcome.tone + '">' + escapeHtml(outcome.text) + '</strong>'
        + '</div>';
    }).join('') : '<div class="decision-empty">暂无回看记录</div>';
    return renderDecisionCard({
      title: '策略回看',
      subtitle: '近期信号反馈',
      badge: { text: rows.length ? rows.length + '条' : '暂无', tone: rows.length ? 'info' : 'neutral' },
      className: 'recent-reviews-card',
      bodyHtml: body,
    });
  }

  function renderDiagnosticsCard(data) {
    var diagnostics = (data || {}).diagnostics || {};
    var allKeys = Object.keys(diagnostics);
    var keys = allKeys.slice(0, 8);
    var rowsHtml = keys.length ? keys.map(function (key) {
      var value = diagnostics[key];
      var text = '';
      if (value && typeof value === 'object') {
        text = normalizeString(value.status || value.summary || '已记录');
      } else {
        text = normalizeString(value);
      }
      return ''
        + '<div class="diagnostic-row">'
        + '  <strong>' + escapeHtml(key) + '</strong>'
        + '  <span>' + escapeHtml(text || '已记录') + '</span>'
        + '</div>';
    }).join('') : '<div class="decision-empty">暂无诊断信息</div>';
    var summaryText = keys.length
      ? '已记录 ' + allKeys.length + ' 项，点击展开'
      : '暂无诊断信息';
    var body = ''
      + '<details class="diagnostics-details">'
      + '  <summary>'
      + '    <strong>后台数据诊断</strong>'
      + '    <span>' + escapeHtml(summaryText) + '</span>'
      + '  </summary>'
      + '  <div class="diagnostics-list">' + rowsHtml + '</div>'
      + '</details>';
    return renderDecisionCard({
      title: '数据诊断',
      subtitle: '数据完整性与生成状态',
      badge: { text: keys.length ? '正常' : '暂无', tone: keys.length ? 'positive' : 'neutral' },
      className: 'diagnostics-card',
      bodyHtml: body,
    });
  }

  function renderAuxiliaryCenter() {
    if (!nodes.auxGrid) return;
    var data = state.data || {};
    nodes.auxGrid.innerHTML = ''
      + renderMarketTemperatureCard(data)
      + renderSectorFlowCard(data)
      + renderLimitUpCard(data)
      + renderEventsCard(data)
      + renderSellSignalsCard(data)
      + renderRecentReviewsCard(data)
      + renderDiagnosticsCard(data);
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
