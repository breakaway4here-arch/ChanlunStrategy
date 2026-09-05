(function () {
  'use strict';

  var DEFAULT_VIEW_ORDER = ['main', 'h4_t3', 'highlights', 'observation_top5', 'acceleration', 'luojie', 'confirming', 'growth_quality', 'baseline'];
  var DEFAULT_VIEW_LABELS = {
    highlights: '看点 Top10',
    main: '正式主推',
    h4_t3: 'H4 T+3',
    observation_top5: '观察 Top5',
    acceleration: '加速',
    luojie: '罗姐池',
    confirming: '等确认',
    growth_quality: '高弹性观察 Top10',
    baseline: '基础候选',
  };
  var DEFAULT_VIEW_DESCRIPTIONS = {
    highlights: '看点 Top10：跨池混合优先观察榜。用于快速扫今天最值得看的标的，不等于全部可立即买入；请结合身份标签、共振标签和操作状态判断。',
    main: '正式主推：融合候选中通过正式推荐门槛的结果，可执行优先。',
    h4_t3: 'H4 T+3 生产池：展示全部过门候选，按现有统一分排序，可空选、不回填。',
    observation_top5: '观察 Top5：近失样本观察榜，不计入主推荐；显示失败门、升级条件和取消条件。',
    acceleration: '加速：强市场下的情绪加速榜。用于从强势启动类候选中二次排序，不是常规主推荐池。',
    luojie: '罗姐池：硬方向 + 15min 生命线观察，不等同于主推。',
    confirming: '等确认：日线已有启动线索，但等待 30min 或次日确认，观察为主，不直接追高。',
    growth_quality: '高弹性观察 Top10：仅展示有真实行业归属与完整交易证据的观察标的，非正式推荐；同一行业最多两只。',
    baseline: '基础候选：原始缠论结构候选 / 各策略共同上游全集；各策略独立筛选，不代表统一策略结果。',
  };
  var DEFAULT_VIEW_CONTRACTS = {
    highlights: { role: 'research', source_pool: 'picks_fusion + next_day_boom + luojie_pool + startup_watchlist', action_semantics: 'watch_only' },
    main: { role: 'formal', source_pool: 'picks_fusion', action_semantics: 'formal' },
    h4_t3: { role: 'formal', source_pool: 'h4_t3_pool', action_semantics: 'formal' },
    observation_top5: { role: 'research', source_pool: 'observation_watchlist', action_semantics: 'watch_only' },
    acceleration: { role: 'research', source_pool: 'next_day_boom', action_semantics: 'watch_only' },
    luojie: { role: 'research', source_pool: 'luojie_pool', action_semantics: 'watch_only' },
    confirming: { role: 'research', source_pool: 'startup_watchlist', action_semantics: 'watch_only' },
    growth_quality: { role: 'research', source_pool: 'picks_fusion + next_day_boom + luojie_pool + startup_watchlist', action_semantics: 'watch_only' },
    baseline: { role: 'baseline', source_pool: 'picks_pure', action_semantics: 'upstream_only' },
  };
  var CHART_EMPTY_TEXT = '暂无图表数据，但保留推荐原因和来源。请检查原始池子数据或 K 线数据。';
  var TOP10_POLL_INTERVAL_MS = 2200;
  var TOP10_MAX_POLL_ATTEMPTS = 52;

  var state = {
    data: null,
    workspace: null,
    primaryMode: 'today',
    currentView: 'main',
    activeItem: null,
    isMobile: false,
    chartInstance: null,
    chartMount: null,
    chartAnnotationLane: null,
    sentimentChartInstance: null,
    chartLayer: 'decision',
    rawPoolCandidates: null,
    drawerReturnFocus: null,
    drawerReturnCode: '',
    drawerBackgroundState: [],
    candidateQuery: '',
    sectorFilter: '',
    sectorFilterCode: '',
    sectorFilterRefs: [],
    candidateLimit: 20,
    top10: {
      jobId: '',
      status: '',
      items: [],
      message: '',
      polling: false,
      timer: null,
      pollCount: 0,
      busy: false,
    },
    preclose: {
      snapshot: null,
      reconciliation: null,
      loading: false,
      expiryTimer: null,
    },
    watchlistManager: {
      loaded: false,
      loading: false,
      saving: false,
      config: null,
      etag: '',
      dirty: false,
      conflict: false,
      open: false,
      message: '',
      tone: 'neutral',
    },
  };

  var nodes = {
    shell: null,
    headerTitle: null,
    headerSubtitle: null,
    headerMetrics: null,
    primaryTabs: null,
    todayDecisionView: null,
    researchValidationView: null,
    marketEvidence: null,
    sectorStrip: null,
    supportingStack: null,
    researchStack: null,
    tabs: null,
    description: null,
    workspaceBody: null,
    candidateList: null,
    candidateEvidenceComparison: null,
    detailPanel: null,
    auxGrid: null,
    drawer: null,
    drawerBackdrop: null,
    drawerPanel: null,
    drawerContent: null,
    top10Shell: null,
    top10RunButton: null,
    top10Status: null,
    top10Result: null,
    precloseAdvisory: null,
    precloseBody: null,
    precloseReconciliation: null,
    directionQuick: null,
    candidateSearch: null,
    candidateCount: null,
    candidateMore: null,
    app: null,
  };

  function escapeHtml(value) {
    var text = userFacingEvidenceText(value, false);
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

  function userFacingEvidenceText(value, formalContext) {
    var text = normalizeString(value);
    var replacement = formalContext ? '本期未选出推荐票' : '本期证据不足';
    var internalTerms = [
      ['数据', '不可用'].join(''),
      ['正式动作', '已封闭'].join(''),
    ];
    internalTerms.forEach(function (term) {
      text = text.split(term).join(replacement);
    });
    return text;
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

  function getCandidateChangePctFromRecord(rec) {
    var record = rec || {};
    if (!hasVerifiedSignalCloseEvidence(record)) return null;
    var direct = safeNumber(record.change_pct, null);
    if (direct !== null) return direct;

    var bp = record.best_buy_point || {};
    var bpChange = safeNumber(bp.change_pct, null);
    if (bpChange !== null) return bpChange;

    var closes = asArray(record.closes);
    if (closes.length < 2) return null;
    var prevClose = safeNumber(closes[closes.length - 2], null);
    var latestClose = safeNumber(closes[closes.length - 1], null);
    if (prevClose === null || latestClose === null || prevClose === 0) return null;
    return ((latestClose - prevClose) / prevClose) * 100;
  }

  function getCandidateChangePct(item) {
    var rec = item || {};
    var direct = getCandidateChangePctFromRecord(rec);
    if (direct !== null) return direct;

    var raw = findRawCandidate(rec.ref || {});
    if (!raw || raw === rec) {
      return null;
    }
    return getCandidateChangePctFromRecord(raw);
  }

  function getCandidateCurrentPriceFromRecord(rec) {
    var record = rec || {};
    if (!hasVerifiedSignalCloseEvidence(record)) return null;
    var direct = safeNumber(record.current_price, null);
    if (direct !== null) return direct;

    var close = safeNumber(record.close, null);
    if (close !== null) return close;

    var bp = record.best_buy_point || {};
    var bpPrice = safeNumber(bp.current_price, null);
    if (bpPrice !== null) return bpPrice;

    var closes = asArray(record.closes);
    if (closes.length === 0) return null;
    return safeNumber(closes[closes.length - 1], null);
  }

  function hasVerifiedSignalCloseEvidence(rec) {
    var record = rec || {};
    var reportDate = normalizeString(state && state.data && state.data.date);
    var candidates = [
      record.reference_close_evidence || {},
      record.data_status || {},
    ];
    return candidates.some(function (evidence) {
      var status = normalizeString(
        evidence.status || evidence.daily
      ).toLowerCase();
      var evidenceDate = normalizeString(
        evidence.latest_date || evidence.reference_date || evidence.date
      );
      return status === 'verified'
        && evidence.is_final === true
        && evidence.stale === false
        && !!reportDate
        && evidenceDate === reportDate;
    });
  }

  function getCandidateCurrentPrice(item) {
    var rec = item || {};
    var direct = getCandidateCurrentPriceFromRecord(rec);
    if (direct !== null) return direct;

    var raw = findRawCandidate(rec.ref || {});
    if (!raw || raw === rec) {
      return null;
    }
    return getCandidateCurrentPriceFromRecord(raw);
  }

  function getCandidateReferencePriceFromRecord(rec) {
    var record = rec || {};
    var direct = safeNumber(record.reference_price, null);
    if (direct !== null) return direct;

    var bp = record.best_buy_point || {};
    direct = safeNumber(bp.reference_price, null);
    if (direct !== null) return direct;
    direct = safeNumber(bp.source_price, null);
    if (direct !== null) return direct;
    return safeNumber(bp.price, null);
  }

  function getCandidateReferencePrice(item) {
    var rec = item || {};
    var direct = getCandidateReferencePriceFromRecord(rec);
    if (direct !== null) return direct;

    var raw = findRawCandidate(rec.ref || {});
    if (!raw || raw === rec) {
      return null;
    }
    return getCandidateReferencePriceFromRecord(raw);
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

  function getStrategyInputHealthForView(data, viewKey) {
    var selection = (data || {}).selection_input_health;
    if (!selection || typeof selection !== 'object') return null;
    var strategyByView = { main: 'daily_fusion', h4_t3: 'h4_t3' };
    var strategy = strategyByView[normalizeString(viewKey)];
    if (!strategy) return null;
    var byStrategy = selection.by_strategy;
    if (byStrategy && typeof byStrategy === 'object') {
      var specific = byStrategy[strategy];
      return specific && typeof specific === 'object' ? specific : null;
    }
    var legacy = selection.formal;
    if (!legacy || typeof legacy !== 'object') return null;
    return Object.assign({ status: selection.status }, legacy);
  }

  function isFormalViewActionAllowed(data, viewKey) {
    var health = getStrategyInputHealthForView(data, viewKey);
    return Boolean(health
      && health.formal_actions_allowed === true
      && normalizeString(health.status) === 'verified');
  }

  function getStrategyViewBlockingReason(data, viewKey) {
    var key = normalizeString(viewKey);
    if (!Object.prototype.hasOwnProperty.call(DEFAULT_VIEW_CONTRACTS, key)
        || key === 'baseline') return '';
    var selection = (data || {}).selection_input_health;
    if (!selection || typeof selection !== 'object'
        || Number(selection.schema_version) !== 2) {
      return (key === 'main' || key === 'h4_t3')
        ? '该历史快照未登记策略级输入健康；本期未选出推荐票，原始池仅保留追溯。'
        : '该历史快照未登记策略级输入健康；本期证据不足，原始池仅保留追溯。';
    }
    var byView = selection.by_view;
    var viewHealth = byView && typeof byView === 'object' ? byView[key] : null;
    if (viewHealth && typeof viewHealth === 'object'
        && (viewHealth.output_hidden === true
          || normalizeString(viewHealth.status) === 'unavailable')) {
      var unavailableCopy = (key === 'main' || key === 'h4_t3')
        ? '本期未选出推荐票'
        : '本期证据不足';
      return '策略上游池不符合 picks_pure 共同全集合同；' + unavailableCopy + '。'
        + '全集外代码 ' + formatNumber(asArray(viewHealth.invalid_codes).length, 0) + ' 只。';
    }
    if ((key === 'main' || key === 'h4_t3')
        && !isFormalViewActionAllowed(data, key)) {
      return '该策略输入过期、未核验或未记录；本期未选出推荐票，历史内容仅供追溯。';
    }
    return '';
  }

  function resolvePageAction(item, viewKey) {
    var rec = item || {};
    var semantics = normalizeString(rec.action_semantics);
    if (!semantics && viewKey) {
      semantics = resolveViewDisplayContract(viewKey, {}).action_semantics;
    }
    if (semantics === 'watch_only') return '仅观察';
    if (semantics === 'upstream_only') return '仅作为上游候选';
    if (semantics === 'formal') {
      if (!isFormalViewActionAllowed(state.data, viewKey)) {
        return '本期未选出推荐票';
      }
      var evidence = getCandidateRecommendationEvidence(rec, state.data, viewKey);
      var summary = evidence && typeof evidence.summary === 'object'
        ? evidence.summary : {};
      return normalizeString(summary.formal_action).trim()
        || '本期未选出推荐票';
    }
    return normalizeString(rec.page_action || rec.effective_action || rec.action || '待判定');
  }

  function getActionPillClass(action) {
    var label = normalizeString(action);
    if (label.indexOf('慎追') !== -1) return 'action-pill is-risk';
    if (label.indexOf('等回踩') !== -1) return 'action-pill is-wait';
    if (label.indexOf('盯盘') !== -1) return 'action-pill is-watch';
    if (label.indexOf('仅观察') !== -1 || label.indexOf('仅作为上游') !== -1) {
      return 'action-pill is-neutral';
    }
    return 'action-pill';
  }

  function getRiskClass(risk) {
    var label = normalizeString(risk);
    if (label.indexOf('过热') !== -1) return 'tag tag-risk is-hot';
    if (label.indexOf('过期') !== -1) return 'tag tag-risk is-expiry';
    if (/数据|缺失|不足|降级|过期/.test(label)) return 'tag tag-risk is-data';
    if (/待核实|待确认|未核实|模型/.test(label)) return 'tag tag-risk is-pending';
    if (/风险|危险|破位|卖出|减仓|调查/.test(label)) return 'tag tag-risk is-danger';
    return 'tag tag-risk is-pending';
  }

  function getDecisionTone(decision) {
    var label = normalizeString(decision && decision.decision ? decision.decision : '');
    var code = normalizeString(decision && decision.decision_code ? decision.decision_code : '');
    if (label.indexOf('不推荐') !== -1 || code === 'reject') return 'is-reject';
    if (label.indexOf('推荐') !== -1 || code === 'recommend') return 'is-recommend';
    return 'is-observe';
  }

  function resolveDecisionEngine(item, raw) {
    if (raw && raw.decision_engine_v1) return raw.decision_engine_v1;
    if (item && item.decision_engine_v1) return item.decision_engine_v1;
    return null;
  }

  function getDecisionScore(decision) {
    return safeNumber(decision && decision.total_score, null);
  }

  function renderDecisionBadge(decision) {
    if (!decision) return '';
    if (isString(decision)) {
      return '<span class="decision-badge is-observe">' + escapeHtml(normalizeString(decision)) + '</span>';
    }
    var label = normalizeString(decision.decision || decision.label || '观察');
    var score = getDecisionScore(decision);
    return ''
      + '<span class="decision-badge ' + escapeHtml(getDecisionTone(decision)) + '">'
      + '  <span class="decision-badge-label">' + escapeHtml('规则判定：' + label) + '</span>'
      + '<span class="decision-badge-score">'
      + (score === null ? '评分未提供' : '评分 ' + escapeHtml(formatNumber(score, 0)))
      + '</span>'
      + '</span>';
  }

  function isIncidentReviewItem(item) {
    return Boolean(item && item.incident_review_only === true);
  }

  function renderDataBadges(item) {
    return asArray(item && item.data_badges).map(function (badge) {
      var label = normalizeString(badge && badge.label);
      if (!label) return '';
      var badgeType = normalizeString(badge && badge.type);
      var className = badgeType === 'risk'
        ? getRiskClass(label)
        : 'tag tag-baseline';
      return makeChip(label, className);
    }).join('');
  }

  function renderCandidateDecisionBadge(item, decision) {
    if (!isIncidentReviewItem(item)) return renderDecisionBadge(decision);
    return '<span class="decision-badge is-observe">'
      + '<span class="decision-badge-label">事故前原始判定·仅追溯</span>'
      + '<span class="decision-badge-score">评分不生效</span>'
      + '</span>';
  }

  function getSourceClass(label) {
    var text = normalizeString(label);
    if (text === '主推' || text === '正式主推') return 'tag tag-main';
    if (text === '加速') return 'tag tag-acceleration';
    if (text === '罗姐池') return 'tag tag-luojie';
    if (text === '融合候选') return 'tag tag-fusion';
    if (text === '等确认') return 'tag tag-confirming';
    if (text === '基础候选' || text === '基准') return 'tag tag-baseline';
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

  function isCanonicalIsoDate(value) {
    var text = normalizeString(value).trim();
    var match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text);
    if (!match) return false;
    var year = Number(match[1]);
    var month = Number(match[2]);
    var day = Number(match[3]);
    var parsed = new Date(Date.UTC(year, month - 1, day));
    return parsed.getUTCFullYear() === year
      && parsed.getUTCMonth() === month - 1
      && parsed.getUTCDate() === day;
  }

  function getRecommendationEvidenceProjection(data) {
    var bootstrap = getBootstrap();
    var projection = bootstrap.recommendationEvidence;
    var report = data || state.data || {};
    if (!projection || typeof projection !== 'object') return null;
    if (Number(projection.schema_version) !== 1) return null;
    if (!projection.views || typeof projection.views !== 'object') return null;
    var evidenceDate = normalizeString(projection.report_date).trim();
    var reportDate = normalizeString(report.date).trim();
    var pageDate = normalizeString(bootstrap.pageDate).trim();
    if (!isCanonicalIsoDate(evidenceDate)) return null;
    if (!isCanonicalIsoDate(pageDate)) return null;
    if (pageDate !== evidenceDate) return null;
    if (reportDate && !isCanonicalIsoDate(reportDate)) return null;
    if (reportDate && evidenceDate !== reportDate) return null;
    return projection;
  }

  function getEvidenceRowsForView(viewKey, data) {
    var projection = getRecommendationEvidenceProjection(data);
    if (!projection) return [];
    return asArray(projection.views[normalizeString(viewKey)]).slice();
  }

  function getTop10ApiBase() {
    return normalizeString(getBootstrap().top10ApiBase);
  }

  function getPrecloseApiBase() {
    return normalizeString(getBootstrap().precloseApiBase).trim().replace(/\/+$/, '');
  }

  function getPreclosePageDate(nowMs) {
    var pathname = normalizeString(window.location && window.location.pathname);
    var archiveMatch = pathname.match(/\/(\d{4}-\d{2}-\d{2})(?:\/index\.html)?\/?$/);
    if (archiveMatch && isCanonicalIsoDate(archiveMatch[1])) {
      return archiveMatch[1];
    }
    if (pathname) {
      var resolvedNow = safeNumber(nowMs, Date.now());
      return new Date(resolvedNow + 8 * 60 * 60 * 1000).toISOString().slice(0, 10);
    }
    var pageDate = normalizeString(getBootstrap().pageDate || state.date || '');
    if (/^\d{4}-\d{2}-\d{2}$/.test(pageDate)) return pageDate;
    return formatDateLabel(new Date().toISOString());
  }

  function formatPrecloseTime(value) {
    var text = normalizeString(value);
    var match = text.match(/T(\d{2}:\d{2}:\d{2})/);
    return match ? match[1] : '--:--:--';
  }

  function preclosePoolRows(snapshot, key) {
    var pools = snapshot && snapshot.pools;
    var rows = pools && Array.isArray(pools[key]) ? pools[key] : [];
    return rows.map(function (candidate) {
      var source = candidate && typeof candidate === 'object' ? candidate : {};
      var code = normalizeString(source.code).trim();
      var name = normalizeString(source.name).trim();
      var price = safeNumber(source.reference_price, null);
      if (!/^\d{6}$/.test(code) || !name || price === null || price <= 0) return null;
      return { code: code, name: name, reference_price: price };
    }).filter(Boolean);
  }

  function buildPreclosePoolHtml(snapshot, key, label) {
    var rows = preclosePoolRows(snapshot, key);
    return ''
      + '<section class="preclose-pool" aria-label="' + escapeHtml(label) + '">'
      + '  <h3>' + escapeHtml(label) + '</h3>'
      + (rows.length ? rows.map(function (candidate) {
        return ''
          + '<div class="preclose-candidate" title="' + escapeHtml(candidate.name + ' ' + candidate.code) + '">'
          + '  <span><strong>' + escapeHtml(candidate.name) + '</strong><small>' + escapeHtml(candidate.code) + '</small></span>'
          + '  <em>参考 ' + escapeHtml(formatNumber(candidate.reference_price, 2)) + '</em>'
          + '</div>';
      }).join('') : '<div class="preclose-pool-empty">本期未选出推荐票</div>')
      + '</section>';
  }

  function buildPrecloseSnapshotHtml(snapshot, nowMs) {
    var source = snapshot && typeof snapshot === 'object' ? snapshot : {};
    var status = normalizeString(source.status);
    var expiresAt = normalizeString(source.expires_at);
    var expiresMs = Date.parse(expiresAt);
    var resolvedNow = safeNumber(nowMs, Date.now());
    var expired = status === 'expired'
      || (Number.isFinite(expiresMs) && resolvedNow >= expiresMs);
    var mainRows = preclosePoolRows(source, 'main');
    var h4Rows = preclosePoolRows(source, 'h4_t3');
    var accelerationRows = preclosePoolRows(source, 'acceleration');
    var rowCount = mainRows.length + h4Rows.length + accelerationRows.length;
    var available = status === 'available'
      && rowCount > 0
      && !expired;
    var hash = normalizeString(source.content_hash);
    var identity = normalizeString(source.snapshot_id);
    var countSummary = '主推 ' + mainRows.length + '只'
      + '｜H4 T+3 ' + h4Rows.length + '只'
      + '｜加速 ' + accelerationRows.length + '只';
    var meta = ''
      + '<div class="preclose-meta" aria-label="预跑快照信息">'
      + '  <span>生成 ' + escapeHtml(formatPrecloseTime(source.generated_at)) + '</span>'
      + '  <span>' + (expired ? '封存 ' : '失效 ') + escapeHtml(formatPrecloseTime(expiresAt)) + '</span>'
      + '</div>';
    if (!expired && !available) {
      return meta
        + '<div class="preclose-unified-empty" role="status">本期未选出推荐票</div>';
    }
    var archived = expired;
    var cardClass = archived ? 'preclose-snapshot-archived' : 'preclose-snapshot-active';
    var cardTitle = archived ? '14:45预跑 · 已封存' : '14:45预跑';
    var poolsHtml = rowCount
      ? '<div class="preclose-pools">'
        + buildPreclosePoolHtml(source, 'main', '主推')
        + buildPreclosePoolHtml(source, 'h4_t3', 'H4 T+3')
        + buildPreclosePoolHtml(source, 'acceleration', '加速观察')
        + '</div>'
      : '<div class="preclose-unified-empty" role="status">本期未选出推荐票</div>';
    return ''
      + '<details class="preclose-snapshot-card ' + cardClass + '"' + (archived ? '' : ' open') + '>'
      + '  <summary>'
      + '    <strong>' + cardTitle + '</strong>'
      + '    <span>' + countSummary + '</span>'
      + (hash ? '<small title="' + escapeHtml('预跑快照 ' + identity) + '">快照 ' + escapeHtml(hash.slice(0, 8)) + '</small>' : '')
      + '  </summary>'
      + '  <div class="preclose-snapshot-content">'
      + meta
      + (archived ? '<div class="preclose-expired" role="status">预跑已封存，仅供回看；14:57后不再依据预跑清单新增动作</div>' : '')
      + poolsHtml
      + '  </div>'
      + '</details>';
  }

  function precloseDiffNames(value) {
    return asArray(value).map(function (item) {
      if (item && typeof item === 'object') {
        return normalizeString(item.name || item.code).trim();
      }
      return normalizeString(item).trim();
    }).filter(Boolean);
  }

  function buildPrecloseDiffLine(label, value) {
    var source = value && typeof value === 'object' ? value : {};
    var retained = precloseDiffNames(source.retained);
    var added = precloseDiffNames(source.added_after_close);
    var removed = precloseDiffNames(source.removed_after_close);
    var details = [];
    if (retained.length) details.push('保留 ' + retained.join('、'));
    if (added.length) details.push('正式新增 ' + added.join('、'));
    if (removed.length) details.push('预跑有、正式无 ' + removed.join('、'));
    return escapeHtml(label) + '：' + (details.length ? details.map(escapeHtml).join('｜') : '无变化');
  }

  function buildPrecloseReconciliationHtml(reconciliation, snapshot) {
    var source = reconciliation && typeof reconciliation === 'object' ? reconciliation : {};
    var frozen = snapshot && typeof snapshot === 'object' ? snapshot : {};
    if (!normalizeString(frozen.content_hash)
      || normalizeString(source.preclose_content_hash) !== normalizeString(frozen.content_hash)) {
      return '';
    }
    var status = normalizeString(source.status);
    if (status === 'formal_pending') {
      return ''
        + '<details class="preclose-reconciliation-card" open>'
        + '<summary>盘后复核</summary>'
        + '<p>今日正式结果尚未生成，暂不继续参考预跑清单</p>'
        + '</details>';
    }
    var pools = source.pools && typeof source.pools === 'object' ? source.pools : {};
    if (status === 'unchanged') {
      var mainCount = precloseDiffNames((pools.main || {}).retained).length;
      var h4Count = precloseDiffNames((pools.h4_t3 || {}).retained).length;
      var accelerationCount = precloseDiffNames((pools.acceleration || {}).retained).length;
      return ''
        + '<details class="preclose-reconciliation-card" open>'
        + '<summary>盘后复核</summary>'
        + '<p>正式结果与14:45预跑一致</p>'
        + '<small>主推' + mainCount + '只｜H4 T+3 ' + h4Count + '只｜加速' + accelerationCount + '只</small>'
        + '</details>';
    }
    if (status !== 'changed') return '';
    return ''
      + '<details class="preclose-reconciliation-card">'
      + '<summary>盘后复核 · 与14:45预跑有变化</summary>'
      + '<div class="preclose-diff-lines">'
      + '<p>' + buildPrecloseDiffLine('主推', pools.main) + '</p>'
      + '<p>' + buildPrecloseDiffLine('H4 T+3', pools.h4_t3) + '</p>'
      + '<p>' + buildPrecloseDiffLine('加速', pools.acceleration) + '</p>'
      + '</div>'
      + '</details>';
  }

  function renderPrecloseSnapshot(snapshot, nowMs) {
    state.preclose.snapshot = snapshot && typeof snapshot === 'object' ? snapshot : null;
    if (nodes.precloseBody) {
      nodes.precloseBody.innerHTML = buildPrecloseSnapshotHtml(state.preclose.snapshot, nowMs);
    }
    if (nodes.precloseAdvisory && nodes.precloseAdvisory.classList) {
      nodes.precloseAdvisory.classList.remove('hidden');
    }
    if (state.preclose.expiryTimer && window.clearTimeout) {
      window.clearTimeout(state.preclose.expiryTimer);
      state.preclose.expiryTimer = null;
    }
    var expiresMs = Date.parse(normalizeString(state.preclose.snapshot && state.preclose.snapshot.expires_at));
    var delay = expiresMs - Date.now();
    if (Number.isFinite(delay) && delay > 0 && window.setTimeout) {
      state.preclose.expiryTimer = window.setTimeout(function () {
        renderPrecloseSnapshot(state.preclose.snapshot, Date.now());
        renderPrecloseReconciliation(state.preclose.reconciliation);
      }, Math.min(delay, 2147483647));
    }
  }

  function renderPrecloseReconciliation(reconciliation) {
    state.preclose.reconciliation = reconciliation && typeof reconciliation === 'object'
      ? reconciliation : null;
    if (!nodes.precloseReconciliation) return;
    var html = buildPrecloseReconciliationHtml(
      state.preclose.reconciliation,
      state.preclose.snapshot
    );
    nodes.precloseReconciliation.innerHTML = html;
    if (nodes.precloseReconciliation.classList) {
      nodes.precloseReconciliation.classList.toggle('hidden', !html);
    }
  }

  function renderPrecloseFailure() {
    state.preclose.snapshot = null;
    state.preclose.reconciliation = null;
    if (nodes.precloseBody) {
      nodes.precloseBody.innerHTML = '<div class="preclose-load-failure" role="status">预跑暂不可用，请以盘后正式结果为准</div>';
    }
    if (nodes.precloseReconciliation) {
      nodes.precloseReconciliation.innerHTML = '';
      if (nodes.precloseReconciliation.classList) nodes.precloseReconciliation.classList.add('hidden');
    }
  }

  function loadPrecloseAdvisory() {
    var apiBase = getPrecloseApiBase();
    if (!apiBase) {
      if (nodes.precloseAdvisory && nodes.precloseAdvisory.classList) {
        nodes.precloseAdvisory.classList.add('hidden');
      }
      return Promise.resolve(null);
    }
    if (nodes.precloseAdvisory && nodes.precloseAdvisory.classList) {
      nodes.precloseAdvisory.classList.remove('hidden');
    }
    if (!window.fetch) {
      renderPrecloseFailure();
      return Promise.resolve(null);
    }
    state.preclose.loading = true;
    if (nodes.precloseBody) {
      nodes.precloseBody.innerHTML = '<div class="preclose-loading">正在读取当天预跑快照…</div>';
    }
    var pageDate = getPreclosePageDate();
    var snapshotUrl = apiBase + '/api/preclose/latest?date=' + encodeURIComponent(pageDate);
    var reconciliationUrl = apiBase + '/api/preclose/reconciliation?date=' + encodeURIComponent(pageDate);
    return window.fetch(snapshotUrl).then(function (response) {
      if (!response || !response.ok) throw new Error('pre-close snapshot unavailable');
      return response.json();
    }).then(function (snapshot) {
      if (!snapshot || typeof snapshot !== 'object') throw new Error('invalid pre-close snapshot');
      renderPrecloseSnapshot(snapshot, Date.now());
      return window.fetch(reconciliationUrl).then(function (response) {
        if (response && response.status === 404) return null;
        if (!response || !response.ok) throw new Error('reconciliation unavailable');
        return response.json();
      }).then(function (reconciliation) {
        renderPrecloseReconciliation(reconciliation);
        return snapshot;
      }).catch(function () {
        renderPrecloseReconciliation(null);
        return snapshot;
      });
    }).catch(function () {
      renderPrecloseFailure();
      return null;
    }).finally(function () {
      state.preclose.loading = false;
    });
  }

  function getDecisionWatchlistUrl() {
    return normalizeString(getBootstrap().decisionWatchlistUrl);
  }

  function getTop10PageDate() {
    var pageDate = normalizeString(getBootstrap().pageDate || state.date || '');
    if (/^\d{4}-\d{2}-\d{2}$/.test(pageDate)) return pageDate;
    return formatDateLabel(new Date().toISOString());
  }

  function getTop10ApiStatusTone(status) {
    if (status === 'done') return 'is-positive';
    if (status === 'failed' || status === 'error') return 'is-danger';
    if (status === 'running' || status === 'queued') return 'is-warning';
    if (status === 'disabled') return 'is-neutral';
    return 'is-neutral';
  }

  function getTop10StatusLabel(status) {
    if (status === 'queued') return '排队中';
    if (status === 'running') return '执行中';
    if (status === 'done') return '完成';
    if (status === 'failed' || status === 'error') return '失败';
    if (status === 'disabled') return '未配置';
    return '待触发';
  }

  function formatTop10Date(value) {
    if (!value) return '--';
    var text = normalizeString(value);
    if (/^\d{4}-\d{2}-\d{2}/.test(text)) return text;
    return formatDateLabel(text);
  }

  function resetTop10State() {
    state.top10 = state.top10 || {};
    state.top10.jobId = '';
    state.top10.status = '';
    state.top10.items = [];
    state.top10.message = '';
    state.top10.polling = false;
    state.top10.busy = false;
    state.top10.loadingLatest = false;
    state.top10.pollCount = 0;
    if (state.top10.timer) {
      clearTimeout(state.top10.timer);
    }
    state.top10.timer = null;
    if (nodes.top10Result) {
      nodes.top10Result.innerHTML = '';
    }
  }

  function stopTop10Polling() {
    if (state.top10 && state.top10.timer) {
      clearTimeout(state.top10.timer);
    }
    if (state.top10) {
      state.top10.polling = false;
      state.top10.timer = null;
    }
  }

  function renderTop10Status(status, message) {
    if (!nodes.top10Status) return;
    var statusText = getTop10StatusLabel(status);
    var tone = getTop10ApiStatusTone(status);
    var line = formatTop10Date(formatDateLabel(new Date().toISOString()));
    var text = normalizeString(message || '');
    if (!text) {
      text = statusText;
      if (statusText === '完成' || statusText === '失败') {
        line = '';
      }
    }
    nodes.top10Status.className = 'top10-status ' + tone;
    nodes.top10Status.innerHTML = ''
      + '<span>' + escapeHtml(text) + '</span>'
      + (line ? ' <span class="top10-status-updated">· ' + escapeHtml(line) + '</span>' : '');

    state.top10.status = status;
    state.top10.message = text;
    if (status === 'disabled' || status === 'failed' || status === 'error') {
      nodes.top10RunButton.disabled = false;
      state.top10.busy = false;
    }
  }

  function renderTop10Result(payload, status) {
    if (!nodes.top10Result) return;
    var items = asArray(payload && (payload.items || payload.top10 || payload.result || payload.data || payload.payload));
    var generatedAt = payload && payload.generated_at ? normalizeString(payload.generated_at) : '';
    var statusText = normalizeString(status || 'done');
    if (statusText === 'done' && items.length === 0) {
      nodes.top10Result.innerHTML = '<div class="top10-empty">未返回 Top10 数据</div>';
      return;
    }

    if (statusText !== 'done') {
      if (statusText === 'running') {
        nodes.top10Result.innerHTML = '<div class="top10-placeholder">快照正在执行，请稍候...</div>';
      } else if (statusText === 'queued') {
        nodes.top10Result.innerHTML = '<div class="top10-placeholder">已提交队列，等待执行...</div>';
      } else {
        nodes.top10Result.innerHTML = '';
      }
      return;
    }

    if (items.length === 0) {
      nodes.top10Result.innerHTML = '<div class="top10-empty">暂无临时 Top10</div>';
      return;
    }

    nodes.top10Result.innerHTML = ''
      + '<div class="top10-table-wrap">'
      + '  <div class="top10-list">'
      + '    <div class="top10-list-head">'
      + '      <span class="top10-cell rank">排名</span>'
      + '      <span class="top10-cell code">代码</span>'
      + '      <span class="top10-cell name">名称</span>'
      + '      <span class="top10-cell score">观察排序分</span>'
      + '      <span class="top10-cell action">页面身份</span>'
      + '      <span class="top10-cell reason">研究依据</span>'
      + '      <span class="top10-cell generated">生成时间</span>'
      + '    </div>'
      + asArray(items).map(function (item, index) {
        var rec = item || {};
        var rank = safeNumber(rec.rank, index + 1);
        if (rank === null || rank === undefined) {
          rank = index + 1;
        }
        var code = normalizeString(rec.code || rec.symbol || '');
        var name = normalizeString(rec.name || '');
        var score = safeNumber(rec.score, safeNumber(rec.opportunity_score, safeNumber(rec.total_score, safeNumber(rec.final_score, null))));
        var action = '仅观察';
        var reason = normalizeString(rec.page_action_reason || rec.reason || rec.notes || rec.note || '');
        var itemGeneratedAt = normalizeString(rec.generated_at || generatedAt);
        return ''
          + '<div class="top10-row">'
          + '  <span class="top10-cell rank">' + escapeHtml(String(rank)) + '</span>'
          + '  <span class="top10-cell code">' + escapeHtml(code) + '</span>'
          + '  <span class="top10-cell name">' + escapeHtml(name) + '</span>'
          + '  <span class="top10-cell score">' + (score === null || score === undefined ? '--' : escapeHtml(formatNumber(score, 2))) + '</span>'
          + '  <span class="top10-cell action">' + escapeHtml(action || '--') + '</span>'
          + '  <span class="top10-cell reason" title="' + escapeHtml(reason || '--') + '">' + escapeHtml(reason || '--') + '</span>'
          + '  <span class="top10-cell generated">' + escapeHtml(formatTop10Date(itemGeneratedAt)) + '</span>'
          + '</div>';
      }).join('')
      + '  </div>'
      + '</div>';

    state.top10.items = items;
  }

  function renderTop10Control() {
    var apiBase = getTop10ApiBase();
    if (!nodes.top10RunButton || !nodes.top10Shell) return;
    nodes.top10RunButton.disabled = !apiBase || state.top10.busy || state.top10.polling;
    if (!apiBase) {
      stopTop10Polling();
      renderTop10Status('disabled', 'Top10 接口未配置');
      nodes.top10RunButton.textContent = '暂不可用';
      nodes.top10Shell.classList.add('is-disabled');
      return;
    }
    nodes.top10Shell.classList.remove('is-disabled');
    nodes.top10RunButton.textContent = state.top10.polling ? '刷新中' : '生成 Top10';
    if (!state.top10.polling && !state.top10.busy && state.top10.status !== 'done') {
      renderTop10Status('idle', '未运行');
    }
  }

  function loadLatestTop10Snapshot() {
    if (!nodes.top10Result || !getTop10ApiBase() || !window.fetch) {
      return;
    }
    if (state.top10.busy || state.top10.polling || state.top10.loadingLatest) {
      return;
    }

    state.top10.loadingLatest = true;
    renderTop10Status('running', '加载当天最新快照...');
    var url = getTop10ApiBase() + '/api/top10/latest?date=' + encodeURIComponent(getTop10PageDate());
    window.fetch(url).then(function (resp) {
      if (resp && resp.status === 404) {
        return null;
      }
      if (!resp || !resp.ok) {
        throw new Error('加载最新 Top10 失败：' + (resp && resp.status ? resp.status : '网络异常'));
      }
      return resp.json();
    }).then(function (payload) {
      if (!payload) {
        renderTop10Status('idle', '未运行');
        return;
      }
      var status = normalizeString(payload.status || 'done').toLowerCase();
      renderTop10Status(status, status === 'done' ? '当天最新快照' : getTop10StatusLabel(status));
      renderTop10Result(payload, status);
    }).catch(function () {
      renderTop10Status('failed', '加载最新 Top10 失败');
    }).finally(function () {
      state.top10.loadingLatest = false;
      renderTop10Control();
    });
  }

  function pollTop10Status(jobId) {
    if (!jobId || !state.top10.polling) {
      return;
    }
    if (!getTop10ApiBase()) {
      renderTop10Status('disabled', 'Top10 接口未配置');
      stopTop10Polling();
      renderTop10Control();
      return;
    }
    if (!window.fetch) {
      renderTop10Status('failed', '当前环境不支持 fetch');
      stopTop10Polling();
      renderTop10Control();
      return;
    }
    if (state.top10.pollCount >= TOP10_MAX_POLL_ATTEMPTS) {
      renderTop10Status('failed', '轮询超时，建议稍后重试');
      stopTop10Polling();
      renderTop10Control();
      return;
    }

    state.top10.pollCount += 1;
    var url = getTop10ApiBase() + '/api/top10/status?job_id=' + encodeURIComponent(jobId);
    window.fetch(url).then(function (resp) {
      if (!resp || !resp.ok) {
        throw new Error('查询 Top10 状态失败：' + resp.status);
      }
      return resp.json();
    }).then(function (payload) {
      var status = normalizeString(payload && payload.status).toLowerCase();
      var text = normalizeString(payload && (payload.message || payload.note || payload.status_text || ''));
      renderTop10Status(status, text || getTop10StatusLabel(status));
      renderTop10Result(payload, status);
      if (status === 'done' || status === 'failed' || status === 'error') {
        stopTop10Polling();
        renderTop10Control();
        return;
      }
      renderTop10Status(status || 'running');
      state.top10.timer = window.setTimeout(function () {
        pollTop10Status(jobId);
      }, TOP10_POLL_INTERVAL_MS);
    }).catch(function () {
      renderTop10Status('failed', '查询 Top10 状态失败');
      stopTop10Polling();
      renderTop10Control();
    });
  }

  function startTop10Polling(jobId) {
    state.top10.polling = true;
    state.top10.jobId = jobId;
    state.top10.pollCount = 0;
    renderTop10Status('running', '开始轮询');
    pollTop10Status(jobId);
  }

  function handleTop10Run() {
    if (!nodes.top10RunButton) return;
    if (state.top10.busy || state.top10.polling) return;
    if (!getTop10ApiBase()) {
      renderTop10Status('disabled', 'Top10 接口未配置');
      return;
    }
    if (!window.fetch) {
      renderTop10Status('failed', '当前环境不支持 fetch');
      return;
    }
    var password = '';
    try {
      password = normalizeString(window.prompt('请输入触发口令：')).trim();
    } catch (err) {
      password = '';
    }
    if (!password) {
      return;
    }

    state.top10.busy = true;
    nodes.top10RunButton.disabled = true;
    nodes.top10Shell.classList.add('is-loading');
    renderTop10Status('running', '提交中...');
    nodes.top10Result.innerHTML = '<div class="top10-placeholder">正在提交 Top10 任务...</div>';

    window.fetch(getTop10ApiBase() + '/api/top10/run', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ password: password }),
    }).then(function (resp) {
      if (!resp || !resp.ok) {
        throw new Error('触发 Top10 失败：' + (resp && resp.status ? resp.status : '网络异常'));
      }
      return resp.json();
    }).then(function (payload) {
      var jobId = normalizeString(payload && payload.job_id);
      if (!jobId) {
        throw new Error('Top10 回应缺少 job_id');
      }
      stopTop10Polling();
      startTop10Polling(jobId);
    }).catch(function (err) {
      renderTop10Status('failed', err && err.message ? err.message : '提交失败');
      nodes.top10Shell.classList.remove('is-loading');
      renderTop10Control();
    }).finally(function () {
      state.top10.busy = false;
      nodes.top10Shell.classList.remove('is-loading');
      renderTop10Control();
    });
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
    var h4T3Pool = data.h4_t3_pool;
    state.rawPoolCandidates = {
      picks_fusion: asArray(data.picks_fusion),
      picks_pure: asArray(data.picks_pure),
      startup_watchlist: asArray(data.startup_watchlist),
      observation_watchlist: asArray(data.observation_watchlist),
      next_day_boom: asArray((nextDayBoom && nextDayBoom.candidates) || []),
      luojie_pool: asArray((luojiePool && luojiePool.candidates) || []),
      h4_t3_pool: asArray((h4T3Pool && h4T3Pool.candidates) || []),
    };
    return state.rawPoolCandidates;
  }

  function getWorkspaceDataFromRef(refPool) {
    var pools = getRawPools();
    var key = normalizeString(refPool).toLowerCase().replace(/-/g, '_');
    if (key === 'main') {
      return pools.picks_fusion;
    }
    if (key === 'h4_t3' || key === 'h4_t3_pool') {
      return pools.h4_t3_pool;
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
    if (key === 'observation_top5' || key === 'observation_watchlist') {
      return pools.observation_watchlist;
    }
    if (key === 'baseline') {
      return pools.picks_pure;
    }
    if (key === 'highlights') {
      return [];
    }
    return pools[key] || [];
  }

  function hasChartData(item) {
    if (!item) return false;
    var dates = asArray(item.dates);
    var opens = asArray(item.opens);
    var highs = asArray(item.highs);
    var lows = asArray(item.lows);
    var closes = asArray(item.closes);
    return Math.min(dates.length, opens.length, highs.length, lows.length, closes.length) >= 2;
  }

  function mergeChartCandidate(primary, chartSource) {
    if (!primary) {
      return chartSource || null;
    }
    if (!chartSource || chartSource === primary || !hasChartData(chartSource)) {
      return primary;
    }
    return {
      ...chartSource,
      ...primary,
      dates: chartSource.dates,
      opens: chartSource.opens,
      highs: chartSource.highs,
      lows: chartSource.lows,
      closes: chartSource.closes,
      volumes: chartSource.volumes,
      macd_hist: chartSource.macd_hist,
      chart_annotations: primary.chart_annotations || chartSource.chart_annotations,
      buy_points: primary.buy_points || chartSource.buy_points,
      reference_buy_points: primary.reference_buy_points || chartSource.reference_buy_points,
      blocked_buy_points: primary.blocked_buy_points || chartSource.blocked_buy_points,
    };
  }

  function findChartCandidate(targetCode, excludeItem) {
    var pools = getRawPools();
    var allPools = [
      pools.picks_fusion,
      pools.picks_pure,
      pools.startup_watchlist,
      pools.next_day_boom,
      pools.luojie_pool,
      pools.h4_t3_pool,
    ];

    for (var i = 0; i < allPools.length; i += 1) {
      var candidate = allPools[i].find(function (item) {
        return item !== excludeItem && toCodeKey(item && item.code) === targetCode && hasChartData(item);
      });
      if (candidate) {
        return candidate;
      }
    }
    return null;
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
      return hasChartData(found) ? found : mergeChartCandidate(found, findChartCandidate(targetCode, found));
    }

    var pools = getRawPools();
    var allPools = [
      pools.picks_fusion,
      pools.picks_pure,
      pools.startup_watchlist,
      pools.luojie_pool,
      pools.next_day_boom,
      pools.h4_t3_pool,
    ];

    for (var i = 0; i < allPools.length; i += 1) {
      var candidate = allPools[i].find(function (item) {
        return toCodeKey(item && item.code) === targetCode;
      });
      if (candidate) {
        return hasChartData(candidate) ? candidate : mergeChartCandidate(candidate, findChartCandidate(targetCode, candidate));
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
    var rawViews = workspace.views || {};
    var views = {};
    Object.keys(rawViews).forEach(function (viewKey) {
      views[viewKey] = asArray(rawViews[viewKey]).slice();
    });
    var rawMeta = workspace.view_meta || {};
    var meta = {};
    Object.keys(Object.assign({}, DEFAULT_VIEW_CONTRACTS, rawMeta)).forEach(function (viewKey) {
      var resolved = resolveViewDisplayContract(viewKey, rawMeta[viewKey] || {});
      var blockingReason = getStrategyViewBlockingReason(state.data, viewKey);
      if (blockingReason) {
        views[viewKey] = [];
        resolved.availability = {
          state: 'unavailable',
          reason: blockingReason,
        };
      } else if (!resolved.availability) {
        resolved.availability = resolveLegacyViewAvailability(
          viewKey, asArray(views[viewKey])
        );
      }
      meta[viewKey] = resolved;
    });
    return {
      meta: meta,
      views: views,
      order: workspace.view_order || DEFAULT_VIEW_ORDER,
      navigationGroups: workspace.navigation_groups || null,
      defaultView: workspace.default_view || 'highlights',
      diagnostics: workspace.diagnostics || {},
    };
  }

  function getWorkspaceNavigationGroups() {
    var workspace = state.workspace || {};
    var supplied = workspace.navigation_groups || {};
    var fallback = {
      primary: [
        { key: 'main', label: '主推' },
        { key: 'confirming', label: '待确认' },
        { key: 'observation_top5', label: '观察' },
      ],
      research: [
        { key: 'baseline', label: '基础候选' },
        { key: 'h4_t3', label: 'H4 T+3' },
        { key: 'acceleration', label: '加速池' },
        { key: 'luojie', label: '罗姐池' },
        { key: 'growth_quality', label: '高弹性观察' },
      ],
    };
    return {
      primary: asArray(supplied.primary).length ? asArray(supplied.primary) : fallback.primary,
      research: asArray(supplied.research).length ? asArray(supplied.research) : fallback.research,
    };
  }

  function resolveLegacyViewAvailability(viewKey, rows) {
    var data = state.data || {};
    var blockingReason = getStrategyViewBlockingReason(data, viewKey);
    if (blockingReason) {
      return {
        state: 'unavailable',
        reason: blockingReason,
      };
    }
    if (viewKey === 'h4_t3') {
      var h4 = data.h4_t3_pool;
      if (!h4 || typeof h4 !== 'object') return { state: 'unavailable', reason: 'H4 T+3 运行证明未提供。' };
      if (normalizeString(h4.status) === 'ok'
          && normalizeString(h4.mode || 'production') === 'production') {
        return rows.length
          ? { state: 'available', reason: normalizeString(h4.reason || 'H4 T+3 结果已生成。') }
          : { state: 'verified_empty', reason: normalizeString(h4.reason || 'H4 T+3 正常运行，今日没有过门候选。') };
      }
      return { state: 'unavailable', reason: normalizeString(h4.reason || 'H4 T+3 状态异常。') };
    }
    if (viewKey === 'acceleration' || viewKey === 'luojie') {
      var pool = viewKey === 'acceleration' ? data.next_day_boom : data.luojie_pool;
      var label = viewKey === 'acceleration' ? '加速池' : '罗姐池';
      if (!pool || typeof pool !== 'object') return { state: 'unavailable', reason: label + '未提供。' };
      var mode = normalizeString(pool.mode).toLowerCase();
      var status = normalizeString(pool.status).toLowerCase();
      if (mode === 'disabled') return { state: 'disabled', reason: normalizeString(pool.reason || '今日触发条件未成立。') };
      if (mode === 'partial' || status === 'partial') return { state: 'partial', reason: normalizeString(pool.reason || label + '数据部分可用。') };
      if (mode === 'enabled') {
        return rows.length
          ? { state: 'available', reason: normalizeString(pool.reason || label + '结果已生成。') }
          : { state: 'verified_empty', reason: normalizeString(pool.reason || label + '正常运行，今日没有过门候选。') };
      }
      return { state: 'unavailable', reason: normalizeString(pool.reason || label + '运行状态无效。') };
    }
    var poolPresence = {
      main: 'picks_fusion',
      observation_top5: 'observation_watchlist',
      confirming: 'startup_watchlist',
      baseline: 'picks_pure',
    };
    var poolKey = poolPresence[viewKey];
    if (poolKey) {
      if (!Object.prototype.hasOwnProperty.call(data, poolKey) || !Array.isArray(data[poolKey])) {
        return { state: 'unavailable', reason: poolKey + ' 未提供或合同无效。' };
      }
      return rows.length
        ? { state: 'available', reason: '结果已生成。' }
        : { state: 'verified_empty', reason: '策略运行正常，今日没有符合条件的候选。' };
    }
    return rows.length
      ? { state: 'available', reason: '观察榜已生成。' }
      : { state: 'verified_empty', reason: '上游数据已提供，本视图没有符合条件的标的。' };
  }

  function getCurrentViewItems() {
    var views = getCandidateViews().views;
    return asArray(views[state.currentView]);
  }

  function getCurrentDescription(viewKey) {
    if (DEFAULT_VIEW_DESCRIPTIONS[viewKey]) {
      return DEFAULT_VIEW_DESCRIPTIONS[viewKey];
    }
    var viewDef = getCandidateViews();
    var meta = viewDef.meta[viewKey] || {};
    return meta.description || DEFAULT_VIEW_DESCRIPTIONS[viewKey] || '';
  }

  function getCurrentLabel(viewKey) {
    if (DEFAULT_VIEW_LABELS[viewKey]) {
      return DEFAULT_VIEW_LABELS[viewKey];
    }
    var viewDef = getCandidateViews();
    var meta = viewDef.meta[viewKey] || {};
    return meta.label || DEFAULT_VIEW_LABELS[viewKey] || viewKey;
  }

  function getCurrentShortLabel(viewKey) {
    if (viewKey === 'main' || viewKey === 'baseline') {
      return DEFAULT_VIEW_LABELS[viewKey];
    }
    var viewDef = getCandidateViews();
    var meta = viewDef.meta[viewKey] || {};
    return meta.short_label || getCurrentLabel(viewKey);
  }

  function getViewAvailabilityMessage(meta) {
    var availability = (meta || {}).availability || {};
    var stateName = normalizeString(availability.state || 'unavailable');
    var detail = userFacingEvidenceText(
      availability.reason || '未记录该视图的生成状态',
      false
    );
    var titles = {
      verified_empty: '正常空选',
      disabled: '今日未启用',
      partial: '数据部分可用',
      unavailable: '本期证据不足',
      available: '暂无可展示候选',
    };
    return {
      state: stateName,
      title: titles[stateName] || '数据状态未知',
      detail: detail,
    };
  }

  function buildCandidateEmptyState(viewKey, availability, context) {
    var ctx = context || {};
    if (ctx.filtered) {
      var filterLabel = normalizeString(ctx.filterLabel || '当前筛选');
      return '<div class="candidate-empty is-filtered"><strong>'
        + escapeHtml(filterLabel + ' · 0只')
        + '</strong><span>当前池没有匹配股票，已保留筛选条件。</span></div>';
    }
    if (viewKey === 'main') {
      return '<div class="candidate-empty is-verified-empty"><strong>本期未选出推荐票</strong></div>';
    }
    var message = getViewAvailabilityMessage({ availability: availability || {} });
    return '<div class="candidate-empty is-' + escapeHtml(message.state) + '"><strong>'
      + escapeHtml(message.title) + '</strong><span>' + escapeHtml(message.detail) + '</span></div>';
  }

  function getViewAvailabilityMeta(availability) {
    var stateName = normalizeString((availability || {}).state || 'unavailable');
    var states = {
      available: { label: '数据可用', tone: 'positive' },
      verified_empty: { label: '正常空选', tone: 'neutral' },
      disabled: { label: '今日未启用', tone: 'neutral' },
      partial: { label: '部分可用', tone: 'warning' },
      unavailable: { label: '证据不足', tone: 'danger' },
    };
    return states[stateName] || { label: '状态未知', tone: 'warning' };
  }

  function getViewSourcePoolLabel(sourcePool) {
    var labels = {
      picks_fusion: '融合候选池',
      h4_t3_pool: 'H4 T+3 独立策略池',
      observation_watchlist: '观察门控池',
      next_day_boom: '次日爆发策略池',
      luojie_pool: '罗姐策略池',
      startup_watchlist: '启动确认池',
      picks_pure: '基础候选（共同上游全集）',
    };
    var value = normalizeString(sourcePool);
    if (!value) return '来源池未登记';
    return value.split(' + ').map(function (key) {
      return labels[key] || key;
    }).join(' + ');
  }

  function getViewActionSemanticsLabel(actionSemantics) {
    var labels = {
      formal: '页面可显示策略动作',
      watch_only: '页面只能观察',
      upstream_only: '仅作为策略上游',
    };
    return labels[normalizeString(actionSemantics)] || '页面动作语义未登记';
  }

  function getViewPageActionLabel(actionSemantics, availability) {
    var availabilityState = normalizeString((availability || {}).state);
    if (normalizeString(actionSemantics) === 'formal' && availabilityState === 'unavailable') {
      return '本期未选出推荐票';
    }
    return getViewActionSemanticsLabel(actionSemantics);
  }

  function resolveViewDisplayContract(viewKey, meta) {
    var fallback = DEFAULT_VIEW_CONTRACTS[viewKey] || {};
    var source = meta && typeof meta === 'object' ? meta : {};
    return Object.assign({}, source, {
      role: normalizeString(source.role || fallback.role),
      source_pool: normalizeString(source.source_pool || fallback.source_pool),
      action_semantics: normalizeString(source.action_semantics || fallback.action_semantics),
    });
  }

  function buildAppShell() {
    var app = document.getElementById('app') || document.body;
    app.innerHTML = ''
      + '<a class="skip-link" href="#reportShell">跳到主要内容</a>'
      + '<main class="report-shell" id="reportShell" tabindex="-1">'
      + '  <header class="compact-header report-header market-header">'
      + '    <div class="report-title-wrap">'
      + '      <h1 class="report-title"></h1>'
      + '      <div class="report-subtitle"></div>'
      + '    </div>'
      + '    <div class="header-metrics"></div>'
      + '  </header>'
      + '  <nav class="primary-mode-tabs" role="tablist" aria-label="工作台层级">'
      + '    <button type="button" id="primary-mode-tab-today" data-primary-mode="today" role="tab" aria-controls="todayDecisionView" aria-selected="true" tabindex="0">今日决策</button>'
      + '    <button type="button" id="primary-mode-tab-research" data-primary-mode="research" role="tab" aria-controls="researchValidationView" aria-selected="false" tabindex="-1">研究验证</button>'
      + '  </nav>'
      + '  <section class="primary-view today-decision-view" id="todayDecisionView" role="tabpanel" aria-labelledby="primary-mode-tab-today">'
      + '    <section class="sector-strip" id="sectorStrip" aria-label="资金主线"><strong>资金主线</strong><span>正在整理板块证据…</span></section>'
      + '    <section class="direction-quick" id="directionQuickSummary" aria-label="今日方向摘要"></section>'
      + '    <section class="preclose-advisory hidden" id="precloseAdvisory" aria-labelledby="precloseAdvisoryTitle">'
      + '      <header class="preclose-advisory-head">'
      + '        <span><strong id="precloseAdvisoryTitle">14:45预跑</strong><small>盘中建议 · 不改写盘后正式结果</small></span>'
      + '      </header>'
      + '      <div class="preclose-body" id="precloseBody" aria-live="polite"></div>'
      + '      <div class="preclose-reconciliation hidden" id="precloseReconciliation" aria-live="polite"></div>'
      + '    </section>'
      + '    <section class="historical-reconstruction hidden" id="historicalReconstruction" aria-live="polite"></section>'
      + '    <section class="workspace today-workspace">'
      + '      <nav class="workspace-tabs" id="workspaceTabs" role="tablist" aria-label="候选导航"></nav>'
      + '      <div class="view-description" id="viewDescription"></div>'
      + '      <details class="candidate-evidence-comparison" id="candidateEvidenceComparison">'
      + '        <summary>候选横向比较</summary>'
      + '        <div class="candidate-evidence-comparison-body"></div>'
      + '      </details>'
      + '      <div class="workspace-body">'
      + '        <div class="candidate-list-shell">'
      + '          <div class="candidate-list-tools">'
      + '            <label for="candidateSearch">筛选当前池</label>'
      + '            <input id="candidateSearch" type="search" placeholder="代码 / 名称 / 板块" autocomplete="off">'
      + '            <span id="candidateCount" aria-live="polite"></span>'
      + '          </div>'
      + '          <div class="candidate-list" id="candidateList"></div>'
      + '          <button type="button" class="candidate-more" id="candidateMore">加载更多</button>'
      + '        </div>'
      + '        <aside class="detail-panel workspace-detail" id="detailPanel"></aside>'
      + '      </div>'
      + '    </section>'
      + '    <section class="supporting-decisions-stack" id="supportingDecisionsStack"></section>'
      + '  </section>'
      + '  <section class="primary-view research-validation-view hidden" id="researchValidationView" role="tabpanel" aria-labelledby="primary-mode-tab-research">'
      + '    <div class="market-evidence" id="marketEvidence"></div>'
      + '    <section class="aux-center decision-center">'
      + '      <details id="auxCenter" open>'
      + '        <summary>'
      + '          <span><strong>辅助决策驾驶舱</strong><small>先看方向，再沿证据链定位到板块与重点股</small></span>'
      + '        </summary>'
      + '        <div class="research-validation-stack aux-grid decision-grid" id="auxGrid"></div>'
      + '      </details>'
      + '    </section>'
      + '  </section>'
      + '  <div class="mobile-drawer" id="mobileDrawer" role="dialog" aria-modal="true" aria-hidden="true" aria-labelledby="mobileDrawerTitle">'
      + '    <div class="mobile-drawer-backdrop" id="mobileDrawerBackdrop"></div>'
      + '    <div class="mobile-drawer-panel" id="mobileDrawerPanel" tabindex="-1">'
      + '      <div class="mobile-drawer-toolbar">'
      + '        <span id="mobileDrawerTitle">股票详情</span>'
      + '        <button type="button" class="mobile-drawer-floating-close" id="mobileDrawerClose" aria-label="关闭股票详情">关闭</button>'
      + '      </div>'
      + '      <div id="mobileDrawerContent"></div>'
      + '    </div>'
      + '  </div>'
      + '  <div class="text-empty hidden" id="globalError"></div>'
      + '</main>';

    nodes.app = app;
    nodes.shell = app.querySelector('#reportShell');
    nodes.headerTitle = app.querySelector('.report-title');
    nodes.headerSubtitle = app.querySelector('.report-subtitle');
    nodes.headerMetrics = app.querySelector('.header-metrics');
    nodes.primaryTabs = app.querySelector('.primary-mode-tabs');
    nodes.todayDecisionView = app.querySelector('#todayDecisionView');
    nodes.researchValidationView = app.querySelector('#researchValidationView');
    nodes.marketEvidence = app.querySelector('#marketEvidence');
    nodes.sectorStrip = app.querySelector('#sectorStrip');
    nodes.supportingStack = app.querySelector('#supportingDecisionsStack');
    nodes.researchStack = app.querySelector('#auxGrid');
    nodes.tabs = app.querySelector('#workspaceTabs');
    nodes.description = app.querySelector('#viewDescription');
    nodes.workspaceBody = app.querySelector('.today-workspace .workspace-body');
    nodes.candidateList = app.querySelector('#candidateList');
    nodes.candidateEvidenceComparison = app.querySelector('#candidateEvidenceComparison');
    nodes.detailPanel = app.querySelector('#detailPanel');
    nodes.auxGrid = app.querySelector('#auxGrid');
    nodes.drawer = app.querySelector('#mobileDrawer');
    nodes.drawerBackdrop = app.querySelector('#mobileDrawerBackdrop');
    nodes.drawerPanel = app.querySelector('#mobileDrawerPanel');
    nodes.drawerContent = app.querySelector('#mobileDrawerContent');
    nodes.top10Shell = app.querySelector('#top10Widget');
    nodes.top10RunButton = app.querySelector('#top10RunButton');
    nodes.top10Status = app.querySelector('#top10Status');
    nodes.top10Result = app.querySelector('#top10Result');
    nodes.precloseAdvisory = app.querySelector('#precloseAdvisory');
    nodes.precloseBody = app.querySelector('#precloseBody');
    nodes.precloseReconciliation = app.querySelector('#precloseReconciliation');
    nodes.directionQuick = app.querySelector('#directionQuickSummary');
    nodes.historicalReconstruction = app.querySelector('#historicalReconstruction');
    nodes.candidateSearch = app.querySelector('#candidateSearch');
    nodes.candidateCount = app.querySelector('#candidateCount');
    nodes.candidateMore = app.querySelector('#candidateMore');
    nodes.globalError = app.querySelector('#globalError');
    if (nodes.primaryTabs) {
      nodes.primaryTabs.addEventListener('click', function (event) {
        var button = event.target && event.target.closest
          ? event.target.closest('[data-primary-mode]')
          : null;
        if (!button) return;
        state.primaryMode = button.getAttribute('data-primary-mode') === 'research' ? 'research' : 'today';
        renderPrimaryMode();
      });
      nodes.primaryTabs.addEventListener('keydown', function (event) {
        if (['ArrowRight', 'ArrowLeft', 'Home', 'End'].indexOf(event.key) === -1) return;
        var button = event.target && event.target.closest
          ? event.target.closest('[data-primary-mode]')
          : null;
        if (!button) return;
        var buttons = Array.prototype.slice.call(nodes.primaryTabs.querySelectorAll('[data-primary-mode]'));
        var current = buttons.indexOf(button);
        if (current < 0 || !buttons.length) return;
        event.preventDefault();
        var nextIndex = event.key === 'Home'
          ? 0
          : (event.key === 'End'
            ? buttons.length - 1
            : (current + (event.key === 'ArrowRight' ? 1 : -1) + buttons.length) % buttons.length);
        var next = buttons[nextIndex];
        state.primaryMode = next.getAttribute('data-primary-mode') === 'research' ? 'research' : 'today';
        renderPrimaryMode();
        if (next.focus) next.focus();
      });
    }
    if (nodes.candidateSearch) {
      nodes.candidateSearch.addEventListener('input', function () {
        state.candidateQuery = normalizeString(nodes.candidateSearch.value).trim().toLowerCase();
        state.candidateLimit = 20;
        renderCandidateList();
      });
    }
    if (nodes.candidateMore) {
      nodes.candidateMore.addEventListener('click', function () {
        state.candidateLimit += 20;
        renderCandidateList();
      });
    }
  }

  function renderPrimaryMode() {
    var mode = state.primaryMode === 'research' ? 'research' : 'today';
    state.primaryMode = mode;
    if (nodes.todayDecisionView) nodes.todayDecisionView.classList.toggle('hidden', mode !== 'today');
    if (nodes.researchValidationView) nodes.researchValidationView.classList.toggle('hidden', mode !== 'research');
    if (nodes.primaryTabs) {
      var buttons = nodes.primaryTabs.querySelectorAll('[data-primary-mode]');
      for (var i = 0; i < buttons.length; i += 1) {
        var active = buttons[i].getAttribute('data-primary-mode') === mode;
        buttons[i].classList.toggle('is-active', active);
        buttons[i].setAttribute('aria-selected', active ? 'true' : 'false');
        buttons[i].setAttribute('tabindex', active ? '0' : '-1');
      }
    }
    var resizeCharts = function () {
      if (state.chartInstance) state.chartInstance.resize();
      if (state.sentimentChartInstance) state.sentimentChartInstance.resize();
    };
    if (window.requestAnimationFrame) {
      window.requestAnimationFrame(function () {
        window.requestAnimationFrame(resizeCharts);
      });
    } else {
      setTimeout(resizeCharts, 0);
    }
  }

  function getReportDataStatus(data) {
    var quality = (data || {}).data_quality || {};
    var official = quality.is_official === true
      && normalizeString(quality.bar_state) === 'closed';
    var edition = official ? '正式收盘版' : '非正式数据';
    var asOf = normalizeString(quality.as_of || quality.generated_at);
    var timeMatch = asOf.match(/T(\d{2}:\d{2})/);
    var asOfText = timeMatch ? '截至 ' + timeMatch[1] : '截至时间未记录';
    var warnings = asArray(quality.warnings);
    var degraded = quality.fallback_used === true
      || normalizeString(quality.market_status) && normalizeString(quality.market_status) !== 'verified'
      || warnings.length > 0;
    var selection = (data || {}).selection_input_health;
    var selectionText = '';
    if (!selection || typeof selection !== 'object') {
      selectionText = '策略输入状态未记录，正式动作默认封闭';
    } else {
      var formal = selection.formal || {};
      var formalAny = formal.formal_actions_allowed === true;
      var formalAll = formal.all_formal_actions_allowed;
      if (formalAll === false && formalAny) {
        selectionText = '部分正式策略输入不可用，受影响动作已封闭';
      } else if (!formalAny) {
        selectionText = '选股输入未通过核验，本期未选出推荐票';
      } else if (normalizeString(selection.status) === 'partial') {
        selectionText = '正式策略输入已核验，部分研究池输入缺失';
      } else if (normalizeString(selection.status) === 'verified') {
        selectionText = '行情与选股输入健康';
      } else {
        selectionText = '选股输入状态待确认，正式动作默认封闭';
      }
    }
    return edition + ' · ' + asOfText + ' · '
      + (degraded ? '行情存在降级，详见数据诊断 · ' : '')
      + selectionText;
  }

  function renderHeader() {
    if (!nodes.headerTitle || !state.data) return;
    var data = state.data || {};
    var dateLabel = data.date || getBootstrap().pageDate || formatDateLabel(new Date().toISOString());
    var summary = buildMarketSummary(data.market || {});

    var quality = data.data_quality || {};
    var formal = quality.is_official === true && normalizeString(quality.bar_state) === 'closed';
    var marketStatus = normalizeString(quality.market_status) === 'verified' ? '行情已核验' : '行情待核验';
    var asOf = normalizeString(quality.as_of || quality.generated_at);
    var timeMatch = asOf.match(/T(\d{2}:\d{2})/);
    setTextNode(nodes.headerTitle, '缠论决策工作台');
    setTextNode(nodes.headerSubtitle, '把正式动作放在第一屏，研究证据收进第二层');
    nodes.headerMetrics.innerHTML = '<div class="compact-header-facts">'
      + '<span><small>交易日</small><strong>' + escapeHtml(dateLabel) + '</strong></span>'
      + '<span><small>版本</small><strong>' + escapeHtml(formal ? '正式收盘版' : '盘中预览') + '</strong></span>'
      + '<span><small>更新时间</small><strong>' + escapeHtml(timeMatch ? timeMatch[1] : '--:--') + '</strong></span>'
      + '<span><small>行情</small><strong>' + escapeHtml(marketStatus) + '</strong></span>'
      + '<span><small>节奏</small><strong>' + escapeHtml(normalizeString(summary.regime || summary.label || '待确认')) + '</strong></span>'
      + '</div>';
    if (nodes.marketEvidence) {
      nodes.marketEvidence.innerHTML = '<details class="market-header-details"><summary>大盘证据</summary>'
        + renderMarketRegime(summary) + renderMarketIndexCards(summary.items) + '</details>';
    }
  }

  function getDirectionBriefSourceLabel(brief) {
    var rec = brief || {};
    if (normalizeString(rec.llm_error)) return 'LLM 复核失败·已回退规则';
    if (normalizeString(rec.status) === 'rules_only') return '规则生成';
    if (normalizeString(rec.model) || normalizeString(rec.llm_model)
        || /verified|complete|ok/.test(normalizeString(rec.status))) {
      return '模型复核';
    }
    return '来源未登记';
  }

  function renderDirectionQuickSummary(data) {
    if (!nodes.directionQuick) return;
    var brief = (data || {}).decision_brief || {};
    var theses = asArray(brief.theses).slice(0, 3);
    if (!theses.length) {
      nodes.directionQuick.innerHTML = '<strong>今日方向</strong><span>方向数据未生成，请查看数据诊断。</span>';
      return;
    }
    nodes.directionQuick.innerHTML = '<div><strong>今日方向</strong><small>先看方向，再看候选</small>'
      + '<em class="direction-quick-identity">' + escapeHtml(getDirectionBriefSourceLabel(brief)) + '</em></div>'
      + '<div class="direction-quick-list">' + theses.map(function (thesis) {
        var theme = normalizeString(thesis.theme || thesis.name || '未命名方向');
        var direction = normalizeString(thesis.direction || thesis.stage || '');
        var riskFlags = getRiskReasonFlags(thesis.risk_reasons);
        var riskCount = asArray(thesis.risk_reasons).length;
        var directionMeta = getDirectionMeta(
          direction,
          normalizeString(thesis.stage),
          riskFlags.hasReasons,
          riskFlags.hasVerified
        );
        return '<span class="is-' + escapeHtml(directionMeta.tone) + '"><b>' + escapeHtml(theme) + '</b><em>'
          + escapeHtml(directionMeta.label)
          + (riskCount ? ' · 风险原因 ' + riskCount + ' 条' : '')
          + '</em></span>';
      }).join('') + '</div>'
      + '<button type="button" id="directionQuickMore">查看方向证据</button>';
    var more = nodes.directionQuick.querySelector('#directionQuickMore');
    if (more) {
      more.addEventListener('click', function () {
        var target = document.querySelector('.decision-directions-card');
        if (target && target.scrollIntoView) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
      });
    }
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
        changeCount: 0,
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
      pace = '扩大高收益候选研究';
    } else if (avgChange >= 0.3 && upCount >= downCount) {
      status = '修复';
      tone = 'info';
      pace = '保持候选观察';
    } else if (avgChange <= -0.3 || downCount > upCount) {
      status = '偏弱';
      tone = 'danger';
      pace = '收紧研究门槛';
    }

    return {
      status: status,
      tone: tone,
      pace: pace,
      note: buildMarketStyleHint(best),
      avgChange: avgChange,
      upCount: upCount,
      downCount: downCount,
      changeCount: validChanges.length,
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
    if (score >= 90) return '市场热度较高，重点核验过热和追高风险。';
    if (score >= 75) return '市场偏热，扩大高收益候选研究，同时核验期间回撤。';
    if (score >= 60) return '市场温度偏强，优先研究结构与方向共振候选。';
    if (score >= 45) return '市场温度平衡，精选结构证据完整的候选。';
    if (score >= 30) return '市场偏冷，收紧研究门槛，等待更强信号。';
    return '市场温度较冷，优先提高候选证据完整性。';
  }

  var FORMAL_MARKET_COMPONENT_KEYS = [
    'breadth', 'limit_ecology', 'index', 'turnover', 'trend',
  ];

  function isFormalMarketNumber(value, minimum, maximum) {
    return typeof value === 'number'
      && Number.isFinite(value)
      && value >= minimum
      && value <= maximum;
  }

  function isFormalMarketText(value) {
    return typeof value === 'string' && value.trim().length > 0;
  }

  function hasCompleteFormalMarketComponents(sentiment) {
    var components = sentiment && sentiment.components;
    var evidence = sentiment && sentiment.evidence;
    if (!components || typeof components !== 'object'
        || !evidence || typeof evidence !== 'object') {
      return false;
    }
    return FORMAL_MARKET_COMPONENT_KEYS.every(function (key) {
      if (!Object.prototype.hasOwnProperty.call(components, key)) return false;
      var item = evidence[key];
      if (!item || typeof item !== 'object'
          || typeof item.available !== 'boolean') {
        return false;
      }
      var value = components[key];
      if (value === null) return item.available === false;
      return item.available === true && isFormalMarketNumber(value, 0, 100);
    });
  }

  function isCompleteFormalMarketSentiment(sentiment, expectedDate, dateField, raw) {
    if (!sentiment || typeof sentiment !== 'object') return false;
    if (!isCanonicalIsoDate(expectedDate)
        || normalizeString(sentiment[dateField]).trim() !== expectedDate) {
      return false;
    }
    if (!isFormalMarketNumber(sentiment.score, 0, 100)
        || !isFormalMarketNumber(sentiment.coverage, 0, 1)
        || sentiment.coverage <= 0
        || !isFormalMarketText(sentiment.label)
        || !isFormalMarketText(sentiment.version)
        || (raw && sentiment.insufficient !== false)
        || (!raw
          && Object.prototype.hasOwnProperty.call(sentiment, 'insufficient')
          && sentiment.insufficient !== false)) {
      return false;
    }
    return hasCompleteFormalMarketComponents(sentiment);
  }

  function getFormalMarketSentimentContract(data) {
    data = data || {};
    var bootstrap = getBootstrap();
    var hasProjection = Object.prototype.hasOwnProperty.call(
      bootstrap, 'recommendationEvidence'
    );
    var projection = getRecommendationEvidenceProjection(data);
    if (hasProjection) {
      var market = projection && projection.market_sentiment;
      var formal = market && typeof market === 'object'
        ? market.formal_contract : null;
      var projectionDate = projection
        ? normalizeString(projection.report_date).trim() : '';
      if (!formal || normalizeString(formal.status) !== 'available'
          || !isCompleteFormalMarketSentiment(
            formal, projectionDate, 'as_of', false
          )) {
        return null;
      }
      return formal;
    }

    var reportDate = normalizeString(data.date).trim();
    var pageDate = normalizeString(bootstrap.pageDate).trim();
    if (!isCanonicalIsoDate(reportDate) || pageDate !== reportDate) return null;
    var legacy = data.market_sentiment;
    return isCompleteFormalMarketSentiment(
      legacy, reportDate, 'date', true
    ) ? legacy : null;
  }

  function buildMarketTemperature(data) {
    data = data || {};
    var sentiment = getFormalMarketSentimentContract(data) || {};
    var sentimentScore = safeNumber(sentiment.score, null);
    var sentimentComponents = sentiment.components || {};
    if (!Number.isFinite(sentimentScore)) {
      return {
        score: null,
        label: '数据不足',
        tone: 'neutral',
        insufficient: true,
        coverage: safeNumber(sentiment.coverage, null),
        components: {
          breadth_score: safeNumber(sentimentComponents.breadth, null),
          index_score: safeNumber(sentimentComponents.index, null),
          limit_score: safeNumber(sentimentComponents.limit_ecology, null),
          volume_score: safeNumber(sentimentComponents.turnover, null),
          trend_score: safeNumber(sentimentComponents.trend, null),
        },
        summary: '核心证据覆盖不足，不输出伪精确市场情绪分。',
      };
    }
    sentimentScore = clamp(sentimentScore, 0, 100);
    return {
      score: sentimentScore,
      label: normalizeString(sentiment.label || getMarketTemperatureLabel(sentimentScore)),
      tone: getMarketTemperatureTone(sentimentScore),
      insufficient: false,
      coverage: safeNumber(sentiment.coverage, null),
      components: {
        breadth_score: safeNumber(sentimentComponents.breadth, null),
        index_score: safeNumber(sentimentComponents.index, null),
        limit_score: safeNumber(sentimentComponents.limit_ecology, null),
        volume_score: safeNumber(sentimentComponents.turnover, null),
        trend_score: safeNumber(sentimentComponents.trend, null),
      },
      summary: normalizeString(sentiment.summary || getMarketTemperatureSummary(sentimentScore)),
    };

    /* Legacy formula retained only for source compatibility; formal rendering
       always returns from the evidence-driven V2 branch above. */
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
    var changeCount = safeNumber(summary.changeCount, 0);
    var researchPace = summary.pace;
    if (!isFormalViewActionAllowed(state.data, 'main')
        && !isFormalViewActionAllowed(state.data, 'h4_t3')) {
      researchPace = '仅研究观察，正式动作封闭';
    }
    var widthText = changeCount
      ? summary.upCount + '/' + changeCount
      : '主要指数涨跌数据缺失';
    return ''
      + '<div class="market-regime-row">'
      + '  <div class="market-regime-card">'
      + '    <span class="market-label">市场状态</span>'
      + '    <strong class="market-value is-' + escapeHtml(summary.tone) + '">' + escapeHtml(summary.status) + '</strong>'
      + '    <span class="market-note">' + escapeHtml(summary.note) + '</span>'
      + '  </div>'
      + '  <div class="market-regime-card">'
      + '    <span class="market-label">研究节奏</span>'
      + '    <strong class="market-value">' + escapeHtml(researchPace) + '</strong>'
      + '    <span class="market-note">正式策略包括正式主推与 H4 T+3；研究榜仅作候选研究，风险标签优先过滤。</span>'
      + '  </div>'
      + '  <div class="market-regime-card">'
      + '    <span class="market-label">主要指数上涨数</span>'
      + '    <strong class="market-value">' + escapeHtml(widthText) + '</strong>'
      + '    <span class="market-note">仅基于主要指数 · 平均涨幅 ' + escapeHtml(avgText) + '</span>'
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

  function renderHistoricalReconstruction(data, target) {
    var mount = target || nodes.historicalReconstruction;
    if (!mount) return '';
    var receipt = data && data.historical_reconstruction;
    if (!receipt || typeof receipt !== 'object') {
      mount.className = 'historical-reconstruction hidden';
      mount.innerHTML = '';
      return '';
    }
    var candidates = asArray(receipt.candidates);
    var input = receipt.input || {};
    var original = receipt.original_publication || {};
    var mainCount = safeNumber(original.main_count, 0);
    var affectedCount = safeNumber(original.affected_candidate_count, 0);
    var content = ''
      + '<div class="historical-reconstruction-head">'
      + '  <div><span class="historical-kicker">历史数据修复复盘</span>'
      + '  <h2>' + escapeHtml(receipt.report_date || '') + ' 分钟线已核验补齐</h2></div>'
      + '  <div class="historical-guard"><strong>不属于正式主推</strong><span>评分不生效</span></div>'
      + '</div>'
      + '<p class="historical-explain">原始日报保持不变：当日正式推荐 '
      + escapeHtml(formatNumber(mainCount, 0))
      + ' 只；本次受影响候选 ' + escapeHtml(formatNumber(affectedCount, 0))
      + ' 只因分钟数据未核验而封闭。下列结果为事后使用 15:00 已收盘分钟线重建，仅用于解释数据故障影响。</p>'
      + '<div class="historical-evidence">'
      + '  <span>数据截止 ' + escapeHtml(input.latest_ts || '--') + '</span>'
      + '  <span>状态 ' + escapeHtml(input.status || '--') + '</span>'
      + '  <span>补齐时间 ' + escapeHtml(receipt.acquired_at || '--') + '</span>'
      + '</div>';
    if (candidates.length) {
      content += '<div class="historical-candidates">'
        + candidates.map(function (item) {
          var confirmations = asArray(item.confirmations);
          var referenceClose = safeNumber(item.reference_close, null);
          return ''
            + '<article class="historical-candidate">'
            + '  <div class="historical-candidate-id"><strong>'
            + escapeHtml(item.name || item.code || '--') + '</strong><span>'
            + escapeHtml(item.code || '') + '</span></div>'
            + '  <span class="historical-review-badge">历史重建·仅复盘</span>'
            + '  <p>' + escapeHtml(item.review_reason || '') + '</p>'
            + '  <dl>'
            + '    <div><dt>30分钟确认</dt><dd>'
            + escapeHtml(confirmations.join('、') || '无确认') + '</dd></div>'
            + '    <div><dt>确认时间</dt><dd>'
            + escapeHtml(item.confirm_date || '--') + '</dd></div>'
            + '    <div><dt>当日收盘价</dt><dd>'
            + escapeHtml(referenceClose === null ? '--' : formatNumber(referenceClose, 2))
            + '</dd></div>'
            + '  </dl>'
            + '</article>';
        }).join('')
        + '</div>';
    } else {
      content += '<div class="historical-empty">分钟线已补齐，但事后重建仍未通过确认条件。</div>';
    }
    mount.className = 'historical-reconstruction';
    mount.innerHTML = content;
    return content;
  }

  function activateWorkspaceView(nextView, focusTab) {
    if (!nextView || nextView === state.currentView) return;
    state.currentView = nextView;
    state.candidateQuery = '';
    state.candidateLimit = 20;
    if (nodes.candidateSearch) nodes.candidateSearch.value = '';
    var firstItem = filterCandidatesBySector(
      getCurrentViewItems(), state.sectorFilter, state.sectorFilterCode,
      state.sectorFilterRefs
    )[0] || null;
    state.activeItem = firstItem;
    renderWorkspaceTabs();
    renderViewDescription();
    renderCandidateEvidenceComparisonMount();
    renderCandidateList();
    renderCandidateDetail(firstItem);
    if (focusTab && nodes.tabs) {
      var activeTab = nodes.tabs.querySelector('[data-view="' + nextView + '"]');
      if (activeTab && activeTab.focus) activeTab.focus();
    }
  }

  function buildWorkspaceTabButton(entry, wsInfo, order) {
    var viewKey = normalizeString((entry || {}).key);
    var views = asArray(wsInfo.views[viewKey]);
    var meta = resolveViewDisplayContract(viewKey, (wsInfo.meta || {})[viewKey] || {});
    var rawAvailability = meta.availability || { state: views.length ? 'available' : 'unavailable' };
    var availability = getViewAvailabilityMeta(rawAvailability);
    var label = normalizeString((entry || {}).label || getCurrentLabel(viewKey));
    var button = document.createElement('button');
    button.type = 'button';
    button.className = 'workspace-tab' + (viewKey === state.currentView ? ' is-active' : '');
    button.setAttribute('data-view', viewKey);
    button.setAttribute('id', 'workspace-tab-' + viewKey);
    button.setAttribute('role', 'tab');
    button.setAttribute('aria-selected', viewKey === state.currentView ? 'true' : 'false');
    button.setAttribute('aria-controls', 'candidateList');
    button.setAttribute('tabindex', viewKey === state.currentView ? '0' : '-1');
    button.setAttribute('title', label + ' · ' + views.length + '只');
    button.setAttribute('aria-label', label + '，' + views.length + '只');
    button.innerHTML = ''
      + '<span class="workspace-tab-state is-' + escapeHtml(availability.tone) + '" aria-hidden="true"></span>'
      + '<span class="workspace-tab-label">' + escapeHtml(label) + '</span>'
      + '<span class="workspace-tab-count">(' + views.length + ')</span>';
    button.addEventListener('click', function (event) {
      activateWorkspaceView(event.currentTarget.getAttribute('data-view'), true);
    });
    button.addEventListener('keydown', function (event) {
      if (['ArrowRight', 'ArrowLeft', 'Home', 'End'].indexOf(event.key) === -1) return;
      event.preventDefault();
      var current = order.indexOf(event.currentTarget.getAttribute('data-view'));
      var nextIndex = event.key === 'Home'
        ? 0
        : (event.key === 'End'
          ? order.length - 1
          : (current + (event.key === 'ArrowRight' ? 1 : -1) + order.length) % order.length);
      activateWorkspaceView(order[nextIndex], true);
    });
    return button;
  }

  function renderWorkspaceTabs() {
    if (!nodes.tabs) return;
    nodes.tabs.innerHTML = '';
    nodes.tabs.setAttribute('role', 'tablist');
    nodes.tabs.setAttribute('aria-label', '候选导航');
    var wsInfo = getCandidateViews();
    var groups = getWorkspaceNavigationGroups();
    var entries = groups.primary.concat(groups.research);
    var order = entries.map(function (entry) { return normalizeString(entry.key); });
    for (var i = 0; i < groups.primary.length; i += 1) {
      nodes.tabs.appendChild(buildWorkspaceTabButton(groups.primary[i], wsInfo, order));
    }
    var research = document.createElement('details');
    research.className = 'research-pool-menu';
    if (groups.research.some(function (entry) { return entry.key === state.currentView; })) {
      research.open = true;
    }
    var summary = document.createElement('summary');
    summary.textContent = '研究池';
    research.appendChild(summary);
    var researchTabs = document.createElement('div');
    researchTabs.className = 'research-pool-tabs';
    for (var r = 0; r < groups.research.length; r += 1) {
      researchTabs.appendChild(buildWorkspaceTabButton(groups.research[r], wsInfo, order));
    }
    research.appendChild(researchTabs);
    nodes.tabs.appendChild(research);
    if (nodes.candidateList) {
      nodes.candidateList.setAttribute('role', 'tabpanel');
      nodes.candidateList.setAttribute('aria-labelledby', 'workspace-tab-' + state.currentView);
    }
  }

  function renderViewDescription() {
    if (!nodes.description) return;
    var viewDef = getCandidateViews();
    var meta = resolveViewDisplayContract(
      state.currentView,
      viewDef.meta[state.currentView] || {}
    );
    var text = getCurrentDescription(state.currentView) || '';
    var role = normalizeString(meta.role);
    var roleLabels = {
      formal: state.currentView === 'h4_t3' ? '独立生产策略' : '正式推荐',
      research: '研究观察',
      baseline: '基础全集',
    };
    var roleLabel = roleLabels[role]
      || (state.currentView === 'main' ? '正式推荐' : (state.currentView === 'baseline' ? '基础全集' : '研究观察'));
    var availability = meta.availability || {
      state: getCurrentViewItems().length ? 'available' : 'unavailable',
    };
    var availabilityMeta = getViewAvailabilityMeta(availability);
    var pageActionLabel = getViewPageActionLabel(meta.action_semantics, availability);
    if (state.currentView === 'main') {
      nodes.description.innerHTML = ''
        + '<div class="view-description-copy">正式主推允许真实空池，只展示通过正式门槛的候选。</div>'
        + '<div class="view-description-meta">'
        + '  <span class="status-badge is-info">正式推荐</span>'
        + '  <span>动作：<strong>唯一正式动作</strong></span>'
        + '</div>';
      return;
    }
    nodes.description.innerHTML = ''
      + '<div class="view-description-copy">' + escapeHtml(text) + '</div>'
      + '<div class="view-description-meta">'
      + '  <span class="status-badge is-info">' + escapeHtml(roleLabel) + '</span>'
      + '  <span class="status-badge is-' + escapeHtml(availabilityMeta.tone) + '">' + escapeHtml(availabilityMeta.label) + '</span>'
      + '  <span>来源：<strong>' + escapeHtml(getViewSourcePoolLabel(meta.source_pool)) + '</strong></span>'
      + '  <span>动作：<strong>' + escapeHtml(pageActionLabel) + '</strong></span>'
      + (availability.reason ? '<small>' + escapeHtml(userFacingEvidenceText(availability.reason, false)) + '</small>' : '')
      + '</div>';
  }

  function makeChip(text, className) {
    return '<span class="' + className + '">' + escapeHtml(text) + '</span>';
  }

  function recommendationEvidenceStatus(section, statusContext) {
    var value = section && typeof section === 'object' ? section : {};
    var status = normalizeString(value.status).trim();
    var labels = {
      available: '证据可用',
      partial: '部分证据',
      missing: '未提供证据',
      conflict: '证据冲突',
      stale: '证据已过期',
      unavailable: '证据不可用',
    };
    if (statusContext === 'historical_validation') {
      labels.collecting = '样本采集中';
      labels.waiting_for_maturity = '等待样本成熟';
      labels.data_unavailable = '历史样本暂不可用';
      labels.no_signals = '尚无历史信号样本';
      labels.disabled = '历史验证未启用';
      labels.no_formal_recommendations = '暂无正式推荐样本';
      labels.ready_for_manual_comparison = '达到人工比较门槛';
      labels.contract_missing = '样本合同缺失';
      labels.ambiguous = '合同身份有歧义';
    }
    return labels[status] || '未提供证据';
  }

  function recommendationEvidenceNumber(value, digits) {
    if (!isRecommendationEvidenceFiniteNumber(value)) return '--';
    var number = Number(value);
    return number.toFixed(typeof digits === 'number' ? digits : 0).replace(/\.0+$/, '');
  }

  function isRecommendationEvidenceFiniteNumber(value) {
    return value !== null
      && typeof value !== 'undefined'
      && value !== ''
      && typeof value !== 'boolean'
      && Number.isFinite(Number(value));
  }

  function recommendationEvidenceReason(section) {
    var value = section && typeof section === 'object' ? section : {};
    return normalizeString(value.reason || value.empty_text).trim();
  }

  function recommendationEvidenceList(value) {
    return asArray(value).map(function (item) {
      if (item && typeof item === 'object') return '';
      return normalizeString(item).trim();
    }).filter(Boolean);
  }

  function recommendationEvidenceSectionText(section, keys) {
    var value = section && typeof section === 'object' ? section : {};
    var texts = [];
    asArray(keys).forEach(function (key) {
      var current = value[key];
      if (Array.isArray(current)) {
        texts = texts.concat(recommendationEvidenceList(current));
      } else if (current !== null && typeof current !== 'undefined' && current !== '') {
        texts.push(normalizeString(current).trim());
      }
    });
    texts = texts.filter(Boolean);
    if (texts.length) return texts.join(' · ');
    return recommendationEvidenceReason(value) || recommendationEvidenceStatus(value);
  }

  function recommendationSignalFreshness(daily) {
    var value = daily && typeof daily === 'object' ? daily : {};
    var signal = normalizeString(value.signal).trim();
    var signalDate = normalizeString(value.signal_date).trim();
    var age = isRecommendationEvidenceFiniteNumber(value.signal_age_days)
      ? Number(value.signal_age_days) : null;
    var freshness = '新鲜度未提供';
    if (age !== null && age >= 0 && Math.floor(age) === age) {
      freshness = age === 0 ? '当日' : recommendationEvidenceNumber(age) + ' 个交易日';
    } else if (value.signal_age_days !== null
      && typeof value.signal_age_days !== 'undefined'
      && value.signal_age_days !== '') {
      freshness = '新鲜度异常';
    }
    return {
      primary: [
        signal || '信号类型未提供',
        signalDate ? '信号日 ' + signalDate : '信号日期未提供',
      ].join(' · '),
      secondary: freshness,
    };
  }

  function recommendationDailyDataStatus(daily) {
    var value = daily && typeof daily === 'object' ? daily : {};
    var health = normalizeString(value.health).trim();
    var latestDate = normalizeString(value.latest_date).trim();
    var source = evidenceScalarText(value.data_source);
    var primary = [recommendationEvidenceStatus(value), health].filter(Boolean).join(' · ');
    var metadata = [
      latestDate ? '截至 ' + latestDate : '最后日期未提供',
      value.is_final === true ? '终局' : (value.is_final === false ? '非终局' : '终局状态未提供'),
      value.stale === true ? '已陈旧' : (value.stale === false ? '未陈旧' : '陈旧状态未提供'),
      source ? '来源 ' + source : '来源未提供',
    ];
    return {
      primary: primary || '数据状态未提供',
      secondary: metadata.join(' · '),
    };
  }

  function emptyRecommendationDisplayDerived() {
    return {
      distance_from_reference_pct: null,
      upside_to_pressure_pct: null,
      downside_to_invalidation_pct: null,
      risk_reward_ratio: null,
      distance_state: '',
    };
  }

  function roundRecommendationDisplayDerived(value) {
    return Math.round(Number(value) * 10000) / 10000;
  }

  function recommendationDisplayDerivedMatches(value, expected) {
    return isRecommendationEvidenceFiniteNumber(value)
      && Math.abs(Number(value) - expected) <= 0.0001001;
  }

  function validateRecommendationDisplayDerived(priceEvidence, displayDerived) {
    var prices = priceEvidence && typeof priceEvidence === 'object' ? priceEvidence : {};
    var derived = displayDerived && typeof displayDerived === 'object' ? displayDerived : {};
    var priceStatus = normalizeString(prices.status).trim();
    var derivedStatus = normalizeString(derived.status).trim();
    if (['available', 'partial'].indexOf(priceStatus) === -1
      || ['available', 'partial'].indexOf(derivedStatus) === -1
      || priceStatus === 'conflict') {
      return emptyRecommendationDisplayDerived();
    }
    var auditReasons = prices.audit_reasons && typeof prices.audit_reasons === 'object'
      ? prices.audit_reasons : {};
    var hasBoundaryConflict = function (field) {
      return Boolean(evidenceScalarText(auditReasons[field]));
    };
    var current = evidencePositiveNumber(prices.current_price);
    var reference = evidencePositiveNumber(prices.reference_price);
    var pressure = evidencePositiveNumber(prices.pressure_price);
    var invalidation = evidencePositiveNumber(prices.invalidation_price);
    var distance = current !== null && reference !== null
      && !hasBoundaryConflict('current_price')
      && !hasBoundaryConflict('reference_price')
      ? roundRecommendationDisplayDerived((current - reference) / reference * 100)
      : null;
    var upside = current !== null && pressure !== null && pressure >= current
      && !hasBoundaryConflict('current_price')
      && !hasBoundaryConflict('pressure_price')
      ? roundRecommendationDisplayDerived((pressure - current) / current * 100)
      : null;
    var downside = current !== null && invalidation !== null && invalidation <= current
      && !hasBoundaryConflict('current_price')
      && !hasBoundaryConflict('invalidation_price')
      ? roundRecommendationDisplayDerived((current - invalidation) / current * 100)
      : null;
    var riskReward = upside !== null && downside !== null && downside > 0
      ? roundRecommendationDisplayDerived(upside / downside)
      : null;
    var expectedStatus = [distance, upside, downside, riskReward].every(function (value) {
      return value !== null;
    }) ? 'available' : ([distance, upside, downside, riskReward].some(function (value) {
      return value !== null;
    }) ? 'partial' : 'missing');
    if (derivedStatus !== expectedStatus) return emptyRecommendationDisplayDerived();
    var validated = emptyRecommendationDisplayDerived();
    var distanceValid = distance !== null
      && recommendationDisplayDerivedMatches(derived.distance_from_reference_pct, distance);
    var upsideValid = upside !== null
      && recommendationDisplayDerivedMatches(derived.upside_to_pressure_pct, upside);
    var downsideValid = downside !== null
      && recommendationDisplayDerivedMatches(derived.downside_to_invalidation_pct, downside);
    var riskRewardValid = riskReward !== null
      && recommendationDisplayDerivedMatches(derived.risk_reward_ratio, riskReward);
    if (derivedStatus === 'available'
      && (!distanceValid || !upsideValid || !downsideValid || !riskRewardValid)) {
      return emptyRecommendationDisplayDerived();
    }
    if (distanceValid) {
      validated.distance_from_reference_pct = distance;
      validated.distance_state = evidenceScalarText(
        derived.distance_state || derived.distance_status
      );
    }
    if (upsideValid) validated.upside_to_pressure_pct = upside;
    if (downsideValid) validated.downside_to_invalidation_pct = downside;
    if (riskRewardValid) validated.risk_reward_ratio = riskReward;
    return validated;
  }

  function normalizeCandidateEvidenceRow(row) {
    var source = row && typeof row === 'object' ? row : {};
    var summary = source.summary && typeof source.summary === 'object' ? source.summary : {};
    var decision = source.decision_score && typeof source.decision_score === 'object' ? source.decision_score : {};
    var components = decision.components && typeof decision.components === 'object' ? decision.components : {};
    var rank = source.rank_evidence && typeof source.rank_evidence === 'object' ? source.rank_evidence : {};
    var prices = source.price_evidence && typeof source.price_evidence === 'object' ? source.price_evidence : {};
    var derived = validateRecommendationDisplayDerived(prices, source.display_derived);
    var daily = source.daily_structure && typeof source.daily_structure === 'object' ? source.daily_structure : {};
    var risk = source.risk_and_next && typeof source.risk_and_next === 'object' ? source.risk_and_next : {};
    var mainRise = source.main_rise_clue && typeof source.main_rise_clue === 'object' ? source.main_rise_clue : {};
    var signalFreshness = recommendationSignalFreshness(daily);
    var dailyDataStatus = recommendationDailyDataStatus(daily);
    var componentText = ['structure', 'position', 'sentiment'].map(function (key) {
      var labels = { structure: '结构', position: '位置', sentiment: '情绪' };
      var item = components[key] && typeof components[key] === 'object' ? components[key] : {};
      return isRecommendationEvidenceFiniteNumber(item.score) ? labels[key] + ' ' + recommendationEvidenceNumber(item.score) : '';
    }).filter(Boolean).join(' · ');
    var priceParts = [
      ['现价', prices.current_price],
      ['参考', prices.reference_price],
      ['压力', prices.pressure_price],
      ['失效', prices.invalidation_price],
    ].map(function (entry) {
      return isRecommendationEvidenceFiniteNumber(entry[1]) ? entry[0] + ' ' + recommendationEvidenceNumber(entry[1], 2) : '';
    }).filter(Boolean);
    if (isRecommendationEvidenceFiniteNumber(derived.distance_from_reference_pct)) {
      priceParts.push('距参考 ' + recommendationEvidenceNumber(derived.distance_from_reference_pct, 2) + '%');
    }
    var riskLabels = recommendationEvidenceList(risk.risk_labels);
    return {
      code: normalizeString(source.code || summary.code).trim(),
      name: normalizeString(summary.name).trim(),
      sector: normalizeString(summary.sector).trim(),
      action: normalizeString(summary.formal_action).trim() || '本期未声明正式动作',
      decision: isRecommendationEvidenceFiniteNumber(decision.score) ? '决策分 ' + recommendationEvidenceNumber(decision.score) : recommendationEvidenceStatus(decision),
      decisionCode: normalizeString(decision.decision_code).trim(),
      decisionComponents: componentText,
      rank: isRecommendationEvidenceFiniteNumber(rank.view_rank) ? '#' + recommendationEvidenceNumber(rank.view_rank) : '--',
      rankScore: isRecommendationEvidenceFiniteNumber(rank.opportunity_score) ? '排序分 ' + recommendationEvidenceNumber(rank.opportunity_score) : '排序分 --',
      rankNote: normalizeString(rank.note).trim() || '仅用于当前池内排序',
      signalFreshness: signalFreshness.primary,
      signalFreshnessMeta: signalFreshness.secondary,
      prices: priceParts.join(' · ') || recommendationEvidenceStatus(prices),
      daily: [
        recommendationEvidenceSectionText(daily, ['summary', 'state', 'signal', 'reasons']),
        normalizeString(mainRise.label).trim(),
      ].filter(Boolean).join(' · '),
      sublevel: recommendationEvidenceSectionText(source.sublevel_30m, ['summary', 'state', 'signal', 'reasons']),
      volume: recommendationEvidenceSectionText(source.volume_and_capital, ['summary', 'state', 'signal', 'reasons', 'capital_labels']),
      resonance: recommendationEvidenceSectionText(source.market_and_sector, ['summary', 'state', 'signal', 'reasons', 'sector_labels']),
      risk: riskLabels.join(' · ') || '本期未登记可展示风险标签',
      dataStatus: dailyDataStatus.primary,
      dataStatusMeta: dailyDataStatus.secondary,
      validation: recommendationEvidenceSectionText(source.historical_validation, ['summary', 'sample_gate', 'warning', 'reasons']),
    };
  }

  function renderCandidateEvidenceCell(primary, secondary) {
    return '<strong>' + escapeHtml(primary || '--') + '</strong>'
      + (secondary ? '<small>' + escapeHtml(secondary) + '</small>' : '');
  }

  function renderCandidateEvidenceComparison(viewKey, data) {
    var projection = getRecommendationEvidenceProjection(data);
    var boundary = '<p class="candidate-evidence-boundary">保持正式池原顺序；排序靠前不等于决策门槛更高，正式动作仍以唯一正式合同为准。</p>';
    if (!projection) {
      return boundary + '<div class="candidate-evidence-empty">本期未提供证据展示</div>';
    }
    var rows = getEvidenceRowsForView(viewKey, data).map(normalizeCandidateEvidenceRow);
    if (!rows.length) {
      return boundary + '<div class="candidate-evidence-empty">本期未选出推荐票</div>';
    }
    var headers = [
      '候选', '唯一正式动作', '决策分', '池内排序证据', '信号与新鲜度',
      '价格位置', '日线结构', '30分钟确认', '量价与资金', '市场与板块',
      '风险与下一步', '数据状态', '历史验证',
    ];
    var tableRows = rows.map(function (row) {
      return '<tr>'
        + '<th scope="row">' + renderCandidateEvidenceCell(row.name || row.code, [row.code, row.sector].filter(Boolean).join(' · ')) + '</th>'
        + '<td>' + renderCandidateEvidenceCell(row.action, '') + '</td>'
        + '<td>' + renderCandidateEvidenceCell(row.decision, [row.decisionCode, row.decisionComponents].filter(Boolean).join(' · ')) + '</td>'
        + '<td>' + renderCandidateEvidenceCell(row.rank + ' · ' + row.rankScore, row.rankNote) + '</td>'
        + '<td>' + renderCandidateEvidenceCell(row.signalFreshness, row.signalFreshnessMeta) + '</td>'
        + '<td>' + renderCandidateEvidenceCell(row.prices, '') + '</td>'
        + '<td>' + renderCandidateEvidenceCell(row.daily, '') + '</td>'
        + '<td>' + renderCandidateEvidenceCell(row.sublevel, '') + '</td>'
        + '<td>' + renderCandidateEvidenceCell(row.volume, '') + '</td>'
        + '<td>' + renderCandidateEvidenceCell(row.resonance, '') + '</td>'
        + '<td>' + renderCandidateEvidenceCell(row.risk, '') + '</td>'
        + '<td>' + renderCandidateEvidenceCell(row.dataStatus, row.dataStatusMeta) + '</td>'
        + '<td>' + renderCandidateEvidenceCell(row.validation, '') + '</td>'
        + '</tr>';
    }).join('');
    var tickets = rows.map(function (row) {
      var facts = [
        ['唯一正式动作', row.action],
        ['决策分', [row.decision, row.decisionComponents].filter(Boolean).join(' · ')],
        ['池内排序证据', row.rank + ' · ' + row.rankScore + ' · ' + row.rankNote],
        ['信号与新鲜度', row.signalFreshness + ' · ' + row.signalFreshnessMeta],
        ['价格位置', row.prices],
        ['日线结构', row.daily],
        ['30分钟确认', row.sublevel],
        ['量价与资金', row.volume],
        ['市场与板块', row.resonance],
        ['风险与下一步', row.risk],
        ['数据状态', row.dataStatus + ' · ' + row.dataStatusMeta],
        ['历史验证', row.validation],
      ];
      return '<article class="candidate-evidence-ticket">'
        + '<header><strong>' + escapeHtml(row.name || row.code) + '</strong><small>'
        + escapeHtml([row.code, row.sector].filter(Boolean).join(' · ')) + '</small></header>'
        + '<dl>' + facts.map(function (fact) {
          return '<div><dt>' + escapeHtml(fact[0]) + '</dt><dd>' + escapeHtml(fact[1] || '--') + '</dd></div>';
        }).join('') + '</dl></article>';
    }).join('');
    return boundary
      + '<div class="candidate-evidence-table-wrap" role="region" tabindex="0" aria-label="候选证据比较表"><table class="candidate-evidence-table">'
      + '<thead><tr>' + headers.map(function (header) { return '<th scope="col">' + escapeHtml(header) + '</th>'; }).join('') + '</tr></thead>'
      + '<tbody>' + tableRows + '</tbody></table></div>'
      + '<div class="candidate-evidence-ticket-list">' + tickets + '</div>';
  }

  function renderCandidateEvidenceComparisonMount() {
    if (!nodes.candidateEvidenceComparison) return '';
    var body = nodes.candidateEvidenceComparison.querySelector('.candidate-evidence-comparison-body');
    var html = renderCandidateEvidenceComparison(state.currentView, state.data);
    if (body) body.innerHTML = html;
    return html;
  }

  function selectCandidateRowTags(item, viewKey) {
    var rec = item || {};
    var tags = [];
    var action = resolvePageAction(rec, viewKey);
    if (action) {
      tags.push({ text: '正式动作：' + action, className: getActionClass(action) });
    }
    var evidence = getCandidateRecommendationEvidence(rec, state.data, viewKey);
    var summary = evidence && typeof evidence.summary === 'object' ? evidence.summary : {};
    var horizonStatus = normalizeString(summary.applicable_horizon_status).trim();
    var horizon = horizonStatus === 'available'
      ? normalizeString(summary.applicable_horizon_text).trim() : '';
    if (!horizon && horizonStatus === 'available'
      && isRecommendationEvidenceFiniteNumber(summary.applicable_horizon)) {
      horizon = 'T+' + recommendationEvidenceNumber(summary.applicable_horizon);
    }
    var riskFlags = asArray(rec.risk_flags).filter(function (flag) {
      return normalizeString(flag) && normalizeString(flag) !== '仅观察';
    });
    if (horizon) {
      tags.push({ text: /^T\+/.test(horizon) ? horizon : 'T+' + horizon, className: 'source-chip' });
    } else if (horizonStatus === 'conflict') {
      tags.push({ text: '周期证据冲突', className: 'risk-chip' });
    } else if (riskFlags.length) {
      tags.push({ text: '风险 ' + riskFlags.length + ' 项', className: getRiskClass(riskFlags[0]) });
    } else if (normalizeString(rec.resonance_label)) {
      tags.push({ text: normalizeString(rec.resonance_label), className: getResonanceClass(rec.resonance_label) });
    } else {
      var publicReason = getCandidatePublicReason(rec, summary, viewKey);
      if (publicReason) {
        tags.push({ text: publicReason, className: 'source-chip' });
      } else if (asArray(rec.source_labels).length) {
        tags.push({ text: normalizeString(asArray(rec.source_labels)[0]), className: 'source-chip' });
      }
    }
    return tags.slice(0, 2);
  }

  function getCandidateNavigationIndex(currentIndex, key, total) {
    var count = Math.max(0, Number(total) || 0);
    if (!count) return -1;
    var current = Math.max(0, Math.min(count - 1, Number(currentIndex) || 0));
    if (key === 'ArrowDown') return (current + 1) % count;
    if (key === 'ArrowUp') return (current - 1 + count) % count;
    if (key === 'Home') return 0;
    if (key === 'End') return count - 1;
    return current;
  }

  function renderCandidateList() {
    if (!nodes.candidateList) return;
    nodes.candidateList.innerHTML = '';

    var poolItems = getCurrentViewItems();
    var allItems = filterCandidatesBySector(
      poolItems, state.sectorFilter, state.sectorFilterCode,
      state.sectorFilterRefs
    );
    var query = state.candidateQuery;
    var items = allItems.filter(function (item) {
      if (!query) return true;
      return [
        item && item.code,
        item && item.name,
        item && item.sector,
      ].some(function (value) {
        return normalizeString(value).toLowerCase().indexOf(query) !== -1;
      });
    });
    var visibleItems = items.slice(0, state.candidateLimit);
    var unifiedMainEmpty = state.currentView === 'main'
      && !query
      && !state.sectorFilter
      && items.length === 0;
    if (nodes.workspaceBody && nodes.workspaceBody.classList) {
      nodes.workspaceBody.classList.toggle('is-unified-empty', unifiedMainEmpty);
    }
    var activeVisible = visibleItems.some(function (candidate) {
      return state.activeItem
        && toCodeKey(candidate && candidate.code) === toCodeKey(state.activeItem.code);
    });
    if (visibleItems.length && !activeVisible) {
      state.activeItem = visibleItems[0];
      renderCandidateDetail(state.activeItem);
    }
    if (nodes.candidateCount) {
      nodes.candidateCount.textContent = '显示 ' + visibleItems.length + ' / ' + items.length
        + (query || state.sectorFilter ? '（原池 ' + poolItems.length + '）' : '');
    }
    if (nodes.candidateMore) {
      nodes.candidateMore.hidden = visibleItems.length >= items.length;
    }
    if (!items || items.length === 0) {
      var viewMeta = (getCandidateViews().meta || {})[state.currentView] || {};
      var rawAvailability = viewMeta.availability || {};
      nodes.candidateList.innerHTML = buildCandidateEmptyState(state.currentView, rawAvailability, {
        filtered: Boolean(query || state.sectorFilter),
        filterLabel: state.sectorFilter || normalizeString(nodes.candidateSearch && nodes.candidateSearch.value),
      });
      nodes.detailPanel.innerHTML = unifiedMainEmpty
        ? ''
        : buildCandidateEmptyState(state.currentView, rawAvailability, {
          filtered: Boolean(query || state.sectorFilter),
          filterLabel: state.sectorFilter || normalizeString(nodes.candidateSearch && nodes.candidateSearch.value),
        });
      return;
    }

    for (var i = 0; i < visibleItems.length; i += 1) {
      var item = visibleItems[i] || {};
      var row = document.createElement('button');
      var rankValue = safeNumber(item.view_rank, i + 1);
      var rank = (safeNumber(rankValue, i + 1) || i + 1);
      var code = normalizeString(item.code || '');
      var name = normalizeString(item.name || '');
      var sector = normalizeString(item.sector || '');
      var change = getCandidateChangePct(item);
      var rankClass = getRankClass(rank);
      var changeCls = '';
      if (change === null) {
        changeCls = '';
      } else if (change > 0) {
        changeCls = 'is-up';
      } else if (change < 0) {
        changeCls = 'is-down';
      }

      var selectedTags = selectCandidateRowTags(item, state.currentView);
      var tagHtml = selectedTags.map(function (tag) {
        return makeChip(tag.text, tag.className);
      }).join('');

      row.type = 'button';
      row.className = 'candidate-row';
      row.setAttribute('data-code', code);
      row.setAttribute('data-name', name);
      row.setAttribute(
        'tabindex',
        state.activeItem && state.activeItem.code === code ? '0' : '-1'
      );
      row.innerHTML = ''
        + '<div class="candidate-row-main">'
        + '  <span class="' + escapeHtml(rankClass) + '">' + escapeHtml((rank || i + 1).toString().padStart(2, '0')) + '</span>'
        + '  <div class="candidate-identity">'
        + '    <span class="candidate-name">' + escapeHtml(name || ('未命名 ' + String(code))) + '</span>'
        + '    <span class="candidate-code"> ' + escapeHtml(code) + '</span>'
        + (sector ? ' <span class="candidate-code">· ' + escapeHtml(sector) + '</span>' : '')
        + '  </div>'
        + '</div>'
        + '<div class="candidate-row-meta">'
        + '  <div class="candidate-tags">' + tagHtml + '</div>'
        + '  <div class="candidate-price' + (changeCls ? ' ' + changeCls : '') + '">' + escapeHtml('当日 ' + (change === null ? '--' : formatPct(change, true))) + '</div>'
        + '</div>'
      ;
      if (state.activeItem && state.activeItem.code === code) {
        row.classList.add('is-selected');
      }
      row.addEventListener('click', function (candidate) {
        return function () {
          var returnCode = normalizeString(candidate && candidate.code);
          state.activeItem = candidate;
          renderCandidateDetail(candidate);
          renderCandidateList();
          if (state.isMobile) {
            openMobileDetailDrawer(candidate, returnCode);
          } else {
            var restored = nodes.candidateList.querySelector('[data-code="' + returnCode + '"]');
            if (restored && restored.focus) restored.focus();
          }
        };
      }(item));
      row.addEventListener('keydown', function (candidate, rowIndex) {
        return function (event) {
          var targetIndex = getCandidateNavigationIndex(
            rowIndex, event.key, visibleItems.length
          );
          if (['ArrowDown', 'ArrowUp', 'Home', 'End'].indexOf(event.key) === -1) return;
          event.preventDefault();
          var targetCandidate = visibleItems[targetIndex];
          if (!targetCandidate) return;
          state.activeItem = targetCandidate;
          renderCandidateDetail(targetCandidate);
          var rows = nodes.candidateList.querySelectorAll('.candidate-row');
          for (var rowAt = 0; rowAt < rows.length; rowAt += 1) {
            var selected = rowAt === targetIndex;
            rows[rowAt].setAttribute('tabindex', selected ? '0' : '-1');
            rows[rowAt].classList.toggle('is-selected', selected);
          }
          if (rows[targetIndex] && rows[targetIndex].focus) rows[targetIndex].focus();
        };
      }(item, i));
      nodes.candidateList.appendChild(row);
    }
  }

  function buildDecisionHeader(item, raw) {
    var rec = item || {};
    var source = raw || {};
    var contract = rec.formal_decision_contract || source.formal_decision_contract || {};
    var action = normalizeString(contract.action || resolvePageAction(rec, state.currentView) || '观察');
    var currentPrice = safeNumber(contract.current_price, getCandidateCurrentPrice(rec));
    var referencePrice = safeNumber(contract.reference_price, getCandidateReferencePrice(rec));
    var changePct = safeNumber(contract.change_pct, getCandidateChangePct(rec));
    var facts = [];
    if (currentPrice !== null) facts.push('<span><small>现价</small><strong>' + escapeHtml(formatNumber(currentPrice, 2)) + '</strong></span>');
    if (changePct !== null) facts.push('<span><small>当日</small><strong>' + escapeHtml(formatPct(changePct, true)) + '</strong></span>');
    if (referencePrice !== null) facts.push('<span><small>参考价</small><strong>' + escapeHtml(formatNumber(referencePrice, 2)) + '</strong></span>');
    if (normalizeString(contract.intended_horizon)) {
      facts.push('<span><small>周期</small><strong>' + escapeHtml(normalizeString(contract.intended_horizon)) + '</strong></span>');
    }
    if (normalizeString(contract.position_band)) {
      facts.push('<span><small>仓位</small><strong>' + escapeHtml(normalizeString(contract.position_band)) + '</strong></span>');
    }
    if (safeNumber(contract.invalidation_price, null) !== null) {
      facts.push('<span><small>失效位</small><strong>' + escapeHtml(formatNumber(contract.invalidation_price, 2)) + '</strong></span>');
    }
    if (safeNumber(contract.pressure_price, null) !== null) {
      facts.push('<span><small>压力位</small><strong>' + escapeHtml(formatNumber(contract.pressure_price, 2)) + '</strong></span>');
    }
    var disagreement = buildStrategyDisagreementSummary(rec);
    if (disagreement) facts.push(disagreement);
    return '<div class="detail-header decision-header">'
      + '<div><h2 class="detail-title">' + escapeHtml(normalizeString(rec.name || rec.code || '未命名')) + '</h2>'
      + '<p class="detail-subtitle">' + escapeHtml(normalizeString(rec.code) + (rec.sector ? (' · ' + rec.sector) : '')) + '</p></div>'
      + '<div class="decision-header-action"><span class="formal-action ' + escapeHtml(getActionPillClass(action)) + '">'
      + escapeHtml('正式动作：' + action) + '</span></div>'
      + (facts.length ? '<div class="decision-header-facts">' + facts.join('') + '</div>' : '')
      + '</div>';
  }

  function buildStrategyDisagreementSummary(item) {
    var rec = item || {};
    var summary = rec.strategy_disagreement_summary || {};
    var counts = summary.counts || {};
    if (!summary.counts) {
      counts = { support: 0, reserve: 0, oppose: 0, insufficient_sample: 0 };
      asArray(rec.strategy_stances).forEach(function (stance) {
        var key = normalizeString(stance && stance.stance);
        if (Object.prototype.hasOwnProperty.call(counts, key)) counts[key] += 1;
      });
    }
    var labels = [
      ['support', '支持'],
      ['reserve', '保留'],
      ['oppose', '反对'],
      ['insufficient_sample', '样本不足'],
    ];
    var parts = labels.map(function (entry) {
      var count = safeNumber(counts[entry[0]], 0);
      return count > 0 ? formatNumber(count, 0) + ' ' + entry[1] : '';
    }).filter(Boolean);
    if (!parts.length) return '';
    return '<span class="strategy-disagreement-summary"><small>策略分歧</small><strong>'
      + escapeHtml(parts.join(' / ')) + '</strong></span>';
  }

  function renderStrategyStances(item) {
    var rec = item || {};
    var labels = {
      support: '支持',
      reserve: '保留',
      oppose: '反对',
      insufficient_sample: '样本不足',
    };
    var rows = asArray(rec.strategy_stances).map(function (stance) {
      var key = normalizeString(stance && stance.stance);
      var label = labels[key] || '样本不足';
      var strategy = normalizeString(stance && stance.strategy || '未命名策略');
      var reason = normalizeString(stance && stance.reason);
      var horizon = normalizeString(stance && stance.intended_horizon);
      var version = normalizeString(stance && stance.version);
      var sourcePool = normalizeString(stance && stance.source_pool);
      var metadata = [
        horizon ? '周期 ' + horizon : '',
        version ? '版本 ' + version : '',
        sourcePool ? '来源 ' + sourcePool : '',
      ].filter(Boolean);
      var evidence = asArray(stance && stance.evidence_refs).map(normalizeString).filter(Boolean);
      return '<li><span><strong>' + escapeHtml(strategy) + '</strong><em class="strategy-stance is-'
        + escapeHtml(key || 'insufficient_sample') + '">' + escapeHtml(label) + '</em></span>'
        + (reason ? '<small>' + escapeHtml(reason) + '</small>' : '')
        + (metadata.length ? '<small>' + escapeHtml(metadata.join(' · ')) + '</small>' : '')
        + (evidence.length ? '<div class="strategy-evidence-refs"><small>证据</small>'
          + evidence.map(function (ref) { return '<code>' + escapeHtml(ref) + '</code>'; }).join('')
          + '</div>' : '')
        + '</li>';
    }).join('');
    var ai = rec.ai_research || rec.ai_analysis || {};
    var aiSummary = normalizeString(ai.summary || ai.risk_notice || '');
    var aiEvidence = asArray(ai.evidence_refs).map(normalizeString).filter(Boolean);
    var aiHtml = aiSummary
      ? '<div class="ai-research-boundary"><strong>AI 研究提示</strong><span>'
        + escapeHtml(aiSummary) + '</span><small>仅用于支持、风险提醒或证据不足判断，不改变正式动作。</small>'
        + (aiEvidence.length ? '<div class="strategy-evidence-refs"><small>证据</small>'
          + aiEvidence.map(function (ref) { return '<code>' + escapeHtml(ref) + '</code>'; }).join('')
          + '</div>' : '')
        + '</div>'
      : '';
    return (rows ? '<ul class="strategy-stance-list">' + rows + '</ul>' : '') + aiHtml;
  }

  function renderStrategyDisagreementAudit(data) {
    var workspace = data && data.workspace || {};
    var mainRows = asArray(workspace.views && workspace.views.main);
    var body = mainRows.length ? mainRows.map(function (item) {
      var summary = buildStrategyDisagreementSummary(item);
      var details = renderStrategyStances(item);
      return '<details class="strategy-disagreement-item strategy-scorecard"><summary><span><strong>'
        + escapeHtml(normalizeString(item.name || item.code || '未命名'))
        + '</strong><small>' + escapeHtml(normalizeString(item.code)) + '</small></span>'
        + (summary || '<span><small>策略分歧</small><strong>暂无其他策略立场</strong></span>')
        + '</summary><div class="strategy-disagreement-detail">'
        + (details || '<div class="decision-empty">暂无可审计策略立场</div>')
        + '</div></details>';
    }).join('') : '<div class="decision-empty">本期未选出推荐票</div>';
    return renderDecisionCard({
      title: '策略分歧',
      subtitle: '相对唯一正式动作的立场；展开查看周期、版本和证据',
      badge: { text: mainRows.length ? '可下钻' : '确认空池', tone: mainRows.length ? 'neutral' : 'neutral' },
      className: 'strategy-disagreement-card strategy-scorecards-card',
      bodyHtml: body,
    });
  }

  function collectDecisionSummaryItems(values, limit) {
    var seen = {};
    var rows = [];
    asArray(values).forEach(function (value) {
      var text = value && typeof value === 'object'
        ? normalizeString(value.text || value.reason || value.label || value.summary)
        : normalizeString(value);
      text = text.trim();
      if (!text || seen[text]) return;
      seen[text] = true;
      rows.push(text);
    });
    return rows.slice(0, limit || 3);
  }

  function renderDecisionSummaryColumn(title, items, emptyText) {
    var rows = collectDecisionSummaryItems(items, 3);
    return '<section><h3>' + escapeHtml(title) + '</h3>'
      + (rows.length
        ? '<ul>' + rows.map(function (row) { return '<li>' + escapeHtml(row) + '</li>'; }).join('') + '</ul>'
        : '<p>' + escapeHtml(emptyText) + '</p>')
      + '</section>';
  }

  function buildDecisionSummaryColumns(item, raw) {
    var rec = item || {};
    var source = raw || {};
    var rightSide = source.right_side_startup_evidence
      && typeof source.right_side_startup_evidence === 'object'
      ? source.right_side_startup_evidence
      : (rec.right_side_startup_evidence
        && typeof rec.right_side_startup_evidence === 'object'
        ? rec.right_side_startup_evidence : null);
    if (rightSide) {
      var reference = safeNumber(rightSide.reference_price, null);
      var heading = '<header class="right-side-evidence-head"><strong>'
        + escapeHtml(normalizeString(rightSide.source_label) || '右侧启动')
        + '</strong>'
        + (reference === null ? '' : '<span>参考位 ' + escapeHtml(formatNumber(reference, 2)) + '</span>')
        + '</header>';
      var sections = [];
      [
        ['为何进入', rightSide.why],
        ['关键确认', rightSide.confirmations],
        ['失效条件', rightSide.invalidation]
      ].forEach(function (entry) {
        var rows = collectDecisionSummaryItems(entry[1], 3);
        if (!rows.length) return;
        sections.push('<section><h3>' + escapeHtml(entry[0]) + '</h3><ul>'
          + rows.map(function (row) { return '<li>' + escapeHtml(row) + '</li>'; }).join('')
          + '</ul></section>');
      });
      return '<div class="right-side-evidence">' + heading
        + '<div class="decision-summary-columns">' + sections.join('') + '</div></div>';
    }
    var why = [
      rec.action_reason,
      rec.page_action_reason,
      rec.primary_reason,
      source.action_reason,
    ];
    var next = asArray(rec.upgrade_conditions).concat(asArray(source.upgrade_conditions));
    var invalidation = asArray(rec.cancel_conditions)
      .concat(asArray(source.cancel_conditions))
      .concat(asArray(rec.risk_flags));
    return '<div class="decision-summary-columns">'
      + renderDecisionSummaryColumn('为什么', why, '本期未补充新的结论说明。')
      + renderDecisionSummaryColumn('下一确认', next, '暂无新增确认条件。')
      + renderDecisionSummaryColumn('失效条件', invalidation, '暂无新增失效条件。')
      + '</div>';
  }

  function buildEvidenceAuditDrawer(item, raw) {
    return '<details class="evidence-audit-drawer"><summary>证据与审计</summary>'
      + '<div class="evidence-audit-body">'
      + buildDecisionEngineSection(item, raw)
      + buildReasonSection(item, raw)
      + buildRiskSection(item, raw)
      + buildDetailsSection(item, raw)
      + '</div></details>';
  }

  function buildConclusionSection(item, raw) {
    var sourceLabels = asArray(item.source_labels);
    if (sourceLabels.length === 0 && Array.isArray(item.sources)) {
      sourceLabels = item.sources.map(function (source) {
        return String(source || '');
      });
    }
    var sourceHtml = '';
    for (var i = 0; i < sourceLabels.length; i += 1) {
      if (sourceLabels[i]) {
        sourceHtml += makeChip(sourceLabels[i], 'source-chip');
      }
    }
    if (item.resonance_label) {
      sourceHtml += makeChip(item.resonance_label, 'resonance-chip');
    }
    sourceHtml += renderDataBadges(item);

    var conclusion = item.page_action_reason || (
      normalizeString(item.action_semantics) === 'formal'
        ? item.action_reason
        : item.primary_reason
    ) || '无明确结论说明';
    return ''
      + buildDecisionHeader(item, raw)
      + '<div class="detail-section">'
      + '  <h3 class="detail-section-title">01 结论</h3>'
      + '  <div class="detail-section-body text-item">' + escapeHtml(conclusion) + '</div>'
      + (sourceHtml ? '  <div class="detail-meta">' + sourceHtml + '</div>' : '')
      + '</div>';
  }

  function buildPriceSection(item, raw) {
    var currentPrice = getCandidateCurrentPrice(item);
    var refPrice = getCandidateReferencePrice(item);
    var refPriceLabel = isIncidentReviewItem(item)
      ? '事故前结构参考价（仅追溯）'
      : '结构参考价';

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
      + '    <div class="price-cell"><div class="price-label">信号日收盘</div><div class="price-value">' + escapeHtml(currentPrice === null ? '未核验' : formatNumber(currentPrice, 2)) + '</div></div>'
      + '    <div class="price-cell"><div class="price-label">' + escapeHtml(refPriceLabel) + '</div><div class="price-value">' + escapeHtml(refPrice === null ? '--' : formatNumber(refPrice, 2)) + '</div></div>'
      + '    <div class="price-cell"><div class="price-label">距参考价</div><div class="price-value">' + escapeHtml(dist === null ? '--' : formatPct(dist, true)) + '</div></div>'
      + '    <div class="price-cell"><div class="price-label">止损</div><div class="price-value">' + escapeHtml(stopLoss === null ? '--' : formatNumber(stopLoss, 2)) + '</div></div>'
      + '  </div>'
      + '</div>';
  }

  function buildReasonSection(item, raw) {
    var lines = [];
    if (isIncidentReviewItem(item)) {
      lines.push(normalizeString(item.page_action_reason)
        || '策略输入过期或未核验；本行只用于事故复盘。');
      lines.push('原始分钟级结构理由不作为当前有效证据。');
      return ''
        + '<div class="detail-section">'
        + '  <h3 class="detail-section-title">05 理由</h3>'
        + '  <div class="detail-section-body"><ul>'
        + lines.map(function (line) { return '<li>' + escapeHtml(line) + '</li>'; }).join('')
        + '  </ul></div>'
        + '</div>';
    }
    if (item.primary_reason) {
      lines.push(item.primary_reason);
    }
    if (item.action_reason && normalizeString(item.action_semantics) === 'formal') {
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
      + '  <h3 class="detail-section-title">05 理由</h3>'
      + '  <div class="detail-section-body">'
      + '    <ul>'
      + lines.map(function (line) { return '<li>' + escapeHtml(line) + '</li>'; }).join('')
      + '    </ul>'
      + '  </div>'
      + '</div>';
  }

  function buildRiskSection(item, raw) {
    var risks = asArray(item.risk_flags).filter(function (flag) {
      return normalizeString(flag) !== '仅观察';
    });
    if (risks.length === 0 && raw && Array.isArray(raw.growth_risk_flags)) {
      risks = asArray(raw.growth_risk_flags);
    }
    if (risks.length === 0 && raw && Array.isArray(raw.risk_flags)) {
      risks = asArray(raw.risk_flags);
    }
    var decisionRisks = asArray(
      (raw && raw.decision_engine_v1 && raw.decision_engine_v1.risk_reasons)
      || (item.decision_engine_v1 && item.decision_engine_v1.risk_reasons)
    ).map(function (risk) {
      if (typeof risk === 'string') return normalizeString(risk);
      return normalizeString(risk && (risk.detail || risk.reason || risk.summary));
    }).filter(Boolean);
    decisionRisks.forEach(function (risk) {
      if (risks.indexOf(risk) === -1) risks.push(risk);
    });
    if (risks.length === 0) {
      risks = ['未发现已登记风险；不代表无风险。'];
    }
    return ''
      + '<div class="detail-section">'
      + '  <h3 class="detail-section-title">06 风险</h3>'
      + '  <div class="detail-section-body">'
      + '    <ul>'
      + risks.map(function (line) { return '<li class="risk-chip">' + escapeHtml(line) + '</li>'; }).join('')
      + '    </ul>'
      + '  </div>'
      + '</div>';
  }

  function buildDecisionEngineSection(item, raw) {
    var decision = resolveDecisionEngine(item, raw);
    if (!decision) return '';
    if (isIncidentReviewItem(item)) {
      return ''
        + '<div class="detail-section decision-engine-section">'
        + '  <h3 class="detail-section-title">04 决策</h3>'
        + '  <div class="decision-engine-card">'
        + '    <div class="decision-engine-head">' + renderCandidateDecisionBadge(item, decision) + '</div>'
        + '    <div class="decision-engine-note">策略输入过期或未核验，原始判定和评分不生效；仅保留事故复盘身份。</div>'
        + '  </div>'
        + '</div>';
    }
    if (isString(decision)) {
      return ''
        + '<div class="detail-section decision-engine-section">'
        + '  <h3 class="detail-section-title">04 决策</h3>'
        + '  <div class="decision-engine-card">'
        + '    <div class="decision-engine-head">' + renderDecisionBadge(decision) + '</div>'
        + '    <div class="decision-engine-note">' + escapeHtml(normalizeString(decision)) + '</div>'
        + '  </div>'
        + '</div>';
    }

    var structure = safeNumber(decision.structure && decision.structure.score, null);
    var position = safeNumber(decision.position && decision.position.score, null);
    var sentiment = safeNumber(decision.sentiment && decision.sentiment.score, null);
    var reasons = [];
    ['structure', 'position', 'sentiment'].forEach(function (key) {
      if (decision[key] && Array.isArray(decision[key].reasons)) {
        decision[key].reasons.slice(0, 2).forEach(function (reason) {
          if (reason && reasons.indexOf(reason) === -1) reasons.push(reason);
        });
      }
    });

    return ''
      + '<div class="detail-section decision-engine-section">'
      + '  <h3 class="detail-section-title">04 决策</h3>'
      + '  <div class="decision-engine-card">'
      + '    <div class="decision-engine-head">' + renderDecisionBadge(decision) + '</div>'
      + '    <div class="decision-score-grid">'
      + '      <div><span>结构</span><strong>' + escapeHtml(structure === null ? '--' : formatNumber(structure, 0)) + '</strong></div>'
      + '      <div><span>位置</span><strong>' + escapeHtml(position === null ? '--' : formatNumber(position, 0)) + '</strong></div>'
      + '      <div><span>情绪</span><strong>' + escapeHtml(sentiment === null ? '--' : formatNumber(sentiment, 0)) + '</strong></div>'
      + '    </div>'
      + (reasons.length ? '<div class="decision-engine-reasons">' + reasons.slice(0, 4).map(function (reason) { return '<span>' + escapeHtml(reason) + '</span>'; }).join('') + '</div>' : '')
      + '  </div>'
      + '</div>';
  }

  function buildDetailsSection(item, raw) {
    var details = [];
    if (item.code) details.push('代码：' + item.code);
    if (item.sector) details.push('板块：' + item.sector);
    if (item.distance_from_reference_pct !== undefined) details.push('距参考价：' + formatPct(item.distance_from_reference_pct, true));
    if (isIncidentReviewItem(item)) {
      details.push('事故前评分已失效，仅保留原始载荷供追溯。');
    } else {
      var decisionSummary = getDecisionEngineSummary(item, raw);
      if (decisionSummary) {
        details.push('决策评分摘要：' + decisionSummary);
      }
      var opportunityScore = safeNumber(item.opportunity_score, null);
      var watchScore = safeNumber(item.watch_score, null);
      if (opportunityScore !== null) {
        details.push('页面观察排序分（非仓位、非收益预测）：' + formatNumber(opportunityScore, 0));
      } else if (watchScore !== null) {
        details.push('页面观察排序分（非仓位、非收益预测）：' + formatNumber(watchScore, 0));
      }
    }
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
    if (item.failure_gate) details.push('失败门：' + item.failure_gate);
    if (item.actual_value !== undefined && item.actual_value !== null) {
      details.push('实际值：' + (typeof item.actual_value === 'object' ? JSON.stringify(item.actual_value) : item.actual_value));
    }
    if (Array.isArray(item.upgrade_conditions) && item.upgrade_conditions.length) {
      details.push('升级条件：' + item.upgrade_conditions.join('；'));
    }
    if (Array.isArray(item.cancel_conditions) && item.cancel_conditions.length) {
      details.push('取消条件：' + item.cancel_conditions.join('；'));
    }

    if (details.length === 0) {
      details.push('暂无补充细节。');
    }

    return ''
      + '<div class="detail-section">'
      + '  <h3 class="detail-section-title">07 细节</h3>'
      + '  <div class="detail-section-body">'
      + '    <ul>'
      + details.map(function (line) { return '<li>' + escapeHtml(line) + '</li>'; }).join('')
      + '    </ul>'
      + '  </div>'
      + '</div>';
  }

  function getDecisionEngineSummary(item, raw) {
    var decision = null;
    if (raw && raw.decision_engine_v1) {
      decision = raw.decision_engine_v1;
    } else if (item && item.decision_engine_v1) {
      decision = item.decision_engine_v1;
    }
    if (!decision) {
      return '';
    }
    if (isString(decision)) {
      return normalizeString(decision);
    }
    if (isString(decision.summary)) {
      return normalizeString(decision.summary);
    }

    var score = getDecisionScore(decision);

    var parts = [score === null ? '评分未提供' : '评分 ' + formatNumber(score, 1)];
    if (isString(decision.decision)) {
      parts.push(normalizeString(decision.decision));
    }
    if (decision.structure && safeNumber(decision.structure.score, null) !== null) {
      parts.push('结构 ' + formatNumber(safeNumber(decision.structure.score, 0), 0));
    }
    if (decision.position && safeNumber(decision.position.score, null) !== null) {
      parts.push('位置 ' + formatNumber(safeNumber(decision.position.score, 0), 0));
    }
    if (decision.sentiment && safeNumber(decision.sentiment.score, null) !== null) {
      parts.push('情绪 ' + formatNumber(safeNumber(decision.sentiment.score, 0), 0));
    }
    if (isString(decision.label)) {
      parts.push(normalizeString(decision.label));
    }
    if (isString(decision.reason)) {
      parts.push('结论：' + normalizeString(decision.reason));
    }
    return parts.join('；');
  }

  function getCandidateRecommendationEvidence(item, data, viewKey) {
    var code = toCodeKey(item && item.code);
    if (!code) return null;
    var rows = getEvidenceRowsForView(viewKey || state.currentView, data);
    for (var index = 0; index < rows.length; index += 1) {
      var row = rows[index];
      var summary = row && typeof row.summary === 'object' ? row.summary : {};
      if (toCodeKey(row && (row.code || summary.code)) === code) return row;
    }
    return null;
  }

  function getCandidateChartEvidence(item, data) {
    var evidence = getCandidateRecommendationEvidence(item, data);
    var derived = evidence && evidence.display_derived;
    var chart = derived && derived.chart_evidence;
    return chart && typeof chart === 'object' ? chart : null;
  }

  function getCandidatePublicReason(rec, summary, viewKey) {
    var evidenceSummary = summary && typeof summary === 'object' ? summary : {};
    var record = rec && typeof rec === 'object' ? rec : {};
    var key = normalizeString(viewKey).trim();
    var formalContext = key === 'main' || key === 'h4_t3';
    var candidates = [
      evidenceSummary.formal_action_reason,
      record.page_action_reason,
    ];
    for (var index = 0; index < candidates.length; index += 1) {
      var reason = evidenceScalarText(candidates[index]);
      if (reason) return userFacingEvidenceText(reason, formalContext);
    }
    return '';
  }

  function renderRecommendationEvidenceMeta(section, fallbackDate, statusContext) {
    var value = section && typeof section === 'object' ? section : {};
    var asOf = normalizeString(value.as_of || fallbackDate).trim() || '未随本期提供';
    var source = normalizeString(value.source).trim() || '未随本期提供';
    var reason = recommendationEvidenceReason(value);
    return '<div class="recommendation-evidence-meta">'
      + '<span>状态：<strong>' + escapeHtml(recommendationEvidenceStatus(value, statusContext)) + '</strong></span>'
      + '<span>截至：<strong>' + escapeHtml(asOf) + '</strong></span>'
      + '<span>来源：<strong>' + escapeHtml(source) + '</strong></span>'
      + (reason ? '<small>审计说明：' + escapeHtml(reason) + '</small>' : '')
      + '</div>';
  }

  function renderRecommendationEvidenceModule(number, title, section, body, fallbackDate, statusContext) {
    var titleId = 'evidence-module-' + normalizeString(number).trim();
    return '<section class="detail-section recommendation-evidence-module" data-evidence-module="'
      + escapeHtml(number) + '" aria-labelledby="' + escapeHtml(titleId) + '">'
      + '<h3 id="' + escapeHtml(titleId) + '" class="detail-section-title">' + escapeHtml(number + ' ' + title) + '</h3>'
      + '<div class="detail-section-body">' + body + '</div>'
      + renderRecommendationEvidenceMeta(section, fallbackDate, statusContext)
      + '</section>';
  }

  function evidencePositiveNumber(value) {
    var number = Number(value);
    return Number.isFinite(number) && number > 0 ? number : null;
  }

  function evidenceScalarText(value) {
    if (value === null || typeof value === 'undefined' || value === '') return '';
    if (typeof value === 'boolean') return value ? '是' : '否';
    if (value && typeof value === 'object') return '';
    return normalizeString(value).trim();
  }

  function evidenceBooleanText(value, trueText, falseText, missingText) {
    if (value === true) return trueText;
    if (value === false) return falseText;
    return missingText || '未提供';
  }

  function renderEvidenceRows(rows) {
    var facts = asArray(rows).map(function (row) {
      var label = row && row.length ? normalizeString(row[0]).trim() : '';
      var value = row && row.length > 1 ? evidenceScalarText(row[1]) : '';
      if (!label || !value) return '';
      return '<div><dt>' + escapeHtml(label) + '</dt><dd>' + escapeHtml(value) + '</dd></div>';
    }).filter(Boolean);
    return facts.length ? '<dl class="recommendation-evidence-facts">' + facts.join('') + '</dl>' : '';
  }

  function renderEvidenceMissingEvidence(section) {
    var items = recommendationEvidenceList(section && section.missing_evidence);
    if (!items.length) return '';
    return '<aside class="recommendation-evidence-missing-list"><strong>缺失证据</strong><ul>'
      + items.map(function (item) { return '<li>' + escapeHtml(item) + '</li>'; }).join('')
      + '</ul></aside>';
  }

  function recommendationViewIdentityLabel(viewIdentity) {
    var value = normalizeString(viewIdentity).trim();
    var labels = {
      main: '正式主推',
      h4_t3: 'H4 T+3',
      acceleration: '加速池',
      confirming: '待确认',
    };
    return labels[value] || value || '视图未登记';
  }

  function recommendationSignalAgeText(value) {
    if (!isRecommendationEvidenceFiniteNumber(value)) return '新鲜度未提供';
    var age = Number(value);
    if (age < 0 || Math.floor(age) !== age) return '新鲜度异常';
    return age === 0 ? '当日' : recommendationEvidenceNumber(age) + ' 个交易日';
  }

  function renderRecommendationEvidenceHeader(evidence, incidentReview) {
    var summary = evidence && typeof evidence.summary === 'object' ? evidence.summary : {};
    var code = normalizeString(evidence && (evidence.code || summary.code)).trim();
    var name = normalizeString(summary.name).trim() || code || '未命名';
    var sector = normalizeString(summary.sector).trim();
    var action = incidentReview
      ? '仅追溯 · 评分不生效'
      : (normalizeString(summary.formal_action).trim() || '本期未声明正式动作');
    return '<div class="detail-header recommendation-evidence-header">'
      + '<div><h2 class="detail-title">' + escapeHtml(name) + '</h2>'
      + '<p class="detail-subtitle">' + escapeHtml([code, sector].filter(Boolean).join(' · ')) + '</p></div>'
      + '<div class="decision-header-action"><span class="formal-action '
      + escapeHtml(incidentReview ? 'is-neutral' : getActionPillClass(action)) + '">'
      + escapeHtml(incidentReview ? action : '正式动作：' + action) + '</span></div>'
      + '</div>';
  }

  function renderRecommendationConclusion(evidence, incidentReview) {
    var summary = evidence.summary && typeof evidence.summary === 'object' ? evidence.summary : {};
    var decision = evidence.decision_score && typeof evidence.decision_score === 'object' ? evidence.decision_score : {};
    var components = decision.components && typeof decision.components === 'object' ? decision.components : {};
    var rank = evidence.rank_evidence && typeof evidence.rank_evidence === 'object' ? evidence.rank_evidence : {};
    var componentLabels = { structure: '结构', position: '位置', sentiment: '情绪' };
    var componentHtml = ['structure', 'position', 'sentiment'].map(function (key) {
      var component = components[key] && typeof components[key] === 'object' ? components[key] : {};
      var score = component.score;
      var reasons = recommendationEvidenceList(component.reasons);
      var pillsHtml = reasons.length
        ? '<div class="reason-pills">' + reasons.map(function (reason) {
            return '<span class="reason-pill">' + escapeHtml(reason.trim()) + '</span>';
          }).join('') + '</div>'
        : '<small>无分项原因</small>';
      return '<div><span>' + escapeHtml(componentLabels[key]) + '</span><strong>'
        + escapeHtml(isRecommendationEvidenceFiniteNumber(score) ? recommendationEvidenceNumber(score) : '--') + '</strong>'
        + pillsHtml + '</div>';
    }).join('');
    var decisionScore = decision.score;
    var rankScore = rank.opportunity_score;
    var viewRank = rank.view_rank;
    var summaryRank = isRecommendationEvidenceFiniteNumber(summary.view_rank)
      ? summary.view_rank : viewRank;
    var poolIdentity = [
      getViewSourcePoolLabel(summary.pool_identity),
      recommendationViewIdentityLabel(summary.view_identity),
    ].filter(Boolean).join(' · ');
    var horizonText = normalizeString(summary.applicable_horizon_text).trim();
    if (!horizonText && isRecommendationEvidenceFiniteNumber(summary.applicable_horizon)) {
      horizonText = 'T+' + recommendationEvidenceNumber(summary.applicable_horizon);
    }
    var primaryFactRows = [
      ['信号类型', evidenceScalarText(summary.signal_type) || '未提供'],
      ['信号日期', evidenceScalarText(summary.signal_date) || '未提供'],
      ['信号新鲜度', recommendationSignalAgeText(summary.signal_age_days)],
      ['适用周期', horizonText || '策略未声明统一周期'],
    ];
    var riskRows = [];
    if (summary.data_stale === true) {
      riskRows.push(['陈旧状态', '已陈旧']);
    } else if (summary.data_stale !== false) {
      riskRows.push(['陈旧状态', '陈旧状态未提供']);
    }
    if (summary.data_is_final === false) {
      riskRows.push(['终局状态', '非终局']);
    } else if (summary.data_is_final !== true) {
      riskRows.push(['终局状态', '终局状态未提供']);
    }
    var healthText = evidenceScalarText(summary.data_health);
    var healthIsVerified = ['verified', 'fresh', 'available'].indexOf(
      healthText.toLowerCase()
    ) !== -1;
    if (!healthText) {
      riskRows.push(['数据健康', '数据健康未提供']);
    } else if (!healthIsVerified) {
      riskRows.push(['数据健康', healthText]);
    }
    var primaryFacts = renderEvidenceRows(primaryFactRows);
    var riskFacts = renderEvidenceRows(riskRows);
    var metaFacts = renderEvidenceRows([
      ['池身份', poolIdentity],
      ['池内顺序', isRecommendationEvidenceFiniteNumber(summaryRank) ? '#' + recommendationEvidenceNumber(summaryRank) : '未提供'],
      ['数据日期', evidenceScalarText(summary.data_latest_date) || '未提供'],
      ['数据来源', evidenceScalarText(summary.data_source) || '未提供'],
      ['数据健康', evidenceScalarText(summary.data_health) || '未提供'],
      ['终局状态', evidenceBooleanText(summary.data_is_final, '已终局', '非终局', '终局状态未提供')],
      ['陈旧状态', evidenceBooleanText(summary.data_stale, '已陈旧', '未陈旧', '陈旧状态未提供')],
    ]);
    var metaHtml = '<details class="evidence-meta-details">'
      + '<summary class="evidence-meta-summary">数据存证与审计凭证</summary>'
      + metaFacts
      + '</details>';
    var body = renderRecommendationEvidenceHeader(evidence, incidentReview)
      + (normalizeString(summary.formal_action_reason).trim()
        ? '<p class="recommendation-conclusion-reason">' + escapeHtml(summary.formal_action_reason) + '</p>' : '')
      + '<div class="recommendation-score-split">'
      + '<section><span>决策分</span><strong>'
      + escapeHtml(!incidentReview && isRecommendationEvidenceFiniteNumber(decisionScore) ? recommendationEvidenceNumber(decisionScore) : '本期未提供')
      + '</strong><small>' + escapeHtml(incidentReview ? '事故复盘评分不生效' : (normalizeString(decision.decision_code).trim() || '未提供决策代码')) + '</small>'
      + '<div class="recommendation-component-grid">' + componentHtml + '</div></section>'
      + '<section><span>排序证据</span><strong>'
      + escapeHtml(isRecommendationEvidenceFiniteNumber(viewRank) ? '池内 #' + recommendationEvidenceNumber(viewRank) : '池内名次 --')
      + '</strong><small>'
      + escapeHtml(isRecommendationEvidenceFiniteNumber(rankScore) ? '排序分 ' + recommendationEvidenceNumber(rankScore) : '排序分未提供')
      + '</small><p>' + escapeHtml(normalizeString(rank.note).trim() || '仅用于当前池内排序') + '</p></section>'
      + '</div>'
      + primaryFacts
      + (riskFacts
        ? '<aside class="recommendation-evidence-risk-facts" aria-label="数据风险提示">' + riskFacts + '</aside>'
        : '')
      + metaHtml;
    return body;
  }

  function renderRecommendationPriceEvidence(evidence) {
    var prices = evidence.price_evidence && typeof evidence.price_evidence === 'object' ? evidence.price_evidence : {};
    var derived = validateRecommendationDisplayDerived(prices, evidence.display_derived);
    var fields = [
      ['现价', 'current_price', '本期未形成可验证现价'],
      ['参考价', 'reference_price', '本期未形成可验证参考价'],
      ['压力位', 'pressure_price', '本期未形成可验证压力位'],
      ['失效位', 'invalidation_price', '本期未形成可验证失效位'],
    ];
    var cells = fields.map(function (field) {
      var number = evidencePositiveNumber(prices[field[1]]);
      var isMissing = number === null;
      var cellClass = 'price-cell' + (isMissing ? ' is-missing' : '');
      return '<div class="' + cellClass + '"><div class="price-label">' + escapeHtml(field[0]) + '</div>'
        + '<div class="price-value">' + escapeHtml(isMissing ? field[2] : recommendationEvidenceNumber(number, 2)) + '</div></div>';
    }).join('');
    var targets = asArray(prices.trailing_targets).map(function (target) {
      var source = target && typeof target === 'object' ? target : { price: target };
      var price = evidencePositiveNumber(source.price);
      if (price === null) return '';
      var label = normalizeString(source.label).trim();
      return (label ? label + ' ' : '') + recommendationEvidenceNumber(price, 2);
    }).filter(Boolean);
    var targetContract = prices.trailing_targets_contract && typeof prices.trailing_targets_contract === 'object'
      ? prices.trailing_targets_contract : {};
    var omittedTargets = Math.max(0, Math.floor(safeNumber(targetContract.omitted_count, 0)));
    var maxVisibleTargets = Math.max(0, Math.floor(safeNumber(targetContract.max_visible, 0)));
    var targetText = targets.length ? '分级目标：' + targets.join(' · ') : '本期未形成分级目标';
    if (omittedTargets > 0) {
      targetText += ' · 另有 ' + String(omittedTargets) + ' 个目标未展开'
        + (maxVisibleTargets > 0 ? '（展示上限 ' + String(maxVisibleTargets) + '）' : '');
    }
    var distance = derived.distance_from_reference_pct;
    var distanceState = evidenceScalarText(
      derived.distance_state || derived.distance_status
    );
    var distanceText = isRecommendationEvidenceFiniteNumber(distance)
      ? '距参考价 ' + recommendationEvidenceNumber(distance, 2) + '%'
        + (distanceState ? ' · ' + distanceState : '')
      : '距参考价未形成可验证计算';
    var upside = derived.upside_to_pressure_pct;
    var downside = derived.downside_to_invalidation_pct;
    var riskReward = derived.risk_reward_ratio;
    var derivedNotes = [
      distanceText,
      isRecommendationEvidenceFiniteNumber(upside)
        ? '上行空间 ' + recommendationEvidenceNumber(upside, 2) + '%' : '',
      isRecommendationEvidenceFiniteNumber(downside)
        ? '下行空间 ' + recommendationEvidenceNumber(downside, 2) + '%' : '',
      isRecommendationEvidenceFiniteNumber(riskReward)
        ? '展示风险收益比 ' + recommendationEvidenceNumber(riskReward, 2) : '',
    ].filter(Boolean);
    var structureFields = [
      ['中枢 ZG', 'pivot_zg', 'pivot_zg_source', '本期未形成可验证中枢 ZG'],
      ['中枢 ZD', 'pivot_zd', 'pivot_zd_source', '本期未形成可验证中枢 ZD'],
      ['平台高点', 'platform_high', 'platform_high_source', '本期未形成可验证平台高点'],
      ['买点价格', 'buy_point_price', 'buy_point_price_source', '本期未形成可验证买点价格'],
    ];
    var structureHtml = structureFields.map(function (field) {
      var number = evidencePositiveNumber(prices[field[1]]);
      var source = evidenceScalarText(prices[field[2]]);
      var isMissing = number === null;
      var itemClass = isMissing ? ' class="is-missing"' : '';
      return '<div' + itemClass + '><dt>' + escapeHtml(field[0]) + '</dt><dd><strong>'
        + escapeHtml(isMissing ? field[3] : recommendationEvidenceNumber(number, 2))
        + '</strong>' + (number !== null
          ? '<small>来源：' + escapeHtml(source || '未提供') + '</small>' : '')
        + '</dd></div>';
    }).join('');
    var auditReasons = prices.audit_reasons && typeof prices.audit_reasons === 'object'
      ? prices.audit_reasons : {};
    var hasConflict = normalizeString(prices.status).trim() === 'conflict'
      || Object.keys(auditReasons).some(function (key) {
        return Boolean(evidenceScalarText(auditReasons[key]));
      });
    return '<div class="detail-price-grid">' + cells + '</div>'
      + '<dl class="recommendation-evidence-facts recommendation-structure-price-facts">' + structureHtml + '</dl>'
      + (hasConflict
        ? '<p class="recommendation-evidence-missing">关键价格存在冲突，冲突值已隐藏并进入证据审计。</p>' : '')
      + '<div class="recommendation-price-notes">'
      + derivedNotes.map(function (note) {
        return '<span>' + escapeHtml(note) + '</span>';
      }).join('')
      + '<span>' + escapeHtml(targetText) + '</span>'
      + '</div>';
  }

  function evidenceFact(section, key, label) {
    var value = section && typeof section === 'object' ? section[key] : null;
    if (value === null || typeof value === 'undefined' || value === '') return '';
    if (Array.isArray(value)) {
      value = recommendationEvidenceList(value).join(' · ');
    } else if (value && typeof value === 'object') {
      return '';
    }
    if (value === '') return '';
    return '<div><dt>' + escapeHtml(label) + '</dt><dd>' + escapeHtml(value) + '</dd></div>';
  }

  function renderEvidenceFactGrid(section, specs, missingCopy) {
    var facts = asArray(specs).map(function (spec) {
      return evidenceFact(section, spec[0], spec[1]);
    }).filter(Boolean);
    var reasons = recommendationEvidenceList(section && section.reasons);
    if (reasons.length) {
      facts.push('<div><dt>证据</dt><dd>' + escapeHtml(reasons.join(' · ')) + '</dd></div>');
    }
    return facts.length
      ? '<dl class="recommendation-evidence-facts">' + facts.join('') + '</dl>'
      : '<p class="recommendation-evidence-missing">' + escapeHtml(missingCopy) + '</p>';
  }

  function renderDailyStructureEvidence(section) {
    var value = section && typeof section === 'object' ? section : {};
    var pivots = value.pivots && typeof value.pivots === 'object' ? value.pivots : {};
    var startupSignals = recommendationEvidenceList(value.startup_signals);
    var rows = [
      ['结论', value.summary],
      ['趋势', value.trend],
      ['阶段', value.stage],
      ['信号', value.signal],
      ['信号日期', value.signal_date],
      ['信号新鲜度', recommendationSignalAgeText(value.signal_age_days)],
      ['信号原因', value.signal_reason],
      ['买点价格', isRecommendationEvidenceFiniteNumber(value.buy_point_price) ? recommendationEvidenceNumber(value.buy_point_price, 2) : ''],
      ['中枢数量', isRecommendationEvidenceFiniteNumber(pivots.count) ? recommendationEvidenceNumber(pivots.count) : ''],
      ['最近 ZG', isRecommendationEvidenceFiniteNumber(pivots.ZG) ? recommendationEvidenceNumber(pivots.ZG, 2) : ''],
      ['最近 ZD', isRecommendationEvidenceFiniteNumber(pivots.ZD) ? recommendationEvidenceNumber(pivots.ZD, 2) : ''],
      ['MA5', isRecommendationEvidenceFiniteNumber(value.ma5) ? recommendationEvidenceNumber(value.ma5, 2) : ''],
      ['MA10', isRecommendationEvidenceFiniteNumber(value.ma10) ? recommendationEvidenceNumber(value.ma10, 2) : ''],
      ['MA20', isRecommendationEvidenceFiniteNumber(value.ma20) ? recommendationEvidenceNumber(value.ma20, 2) : ''],
      ['MA50', isRecommendationEvidenceFiniteNumber(value.ma50) ? recommendationEvidenceNumber(value.ma50, 2) : ''],
      ['均线多头', typeof value.ma_bullish === 'boolean' ? evidenceBooleanText(value.ma_bullish, '是', '否') : ''],
      ['MACD', value.macd],
      ['结构信号', startupSignals.join(' · ')],
    ];
    var body = renderEvidenceRows(rows);
    var missing = renderEvidenceMissingEvidence(value);
    return body || missing
      ? body + missing
      : '<p class="recommendation-evidence-missing">本期未提供可验证的日线结构证据</p>';
  }

  function renderSublevelEvidence(section) {
    var value = section && typeof section === 'object' ? section : {};
    var reason = recommendationEvidenceReason(value);
    var missingCopy = reason === 'minute_data_not_serialized'
      ? '30分钟数据未序列化'
      : '本期未提供可验证的30分钟确认证据';
    var reasonText = reason === 'minute_data_not_serialized'
      ? '30分钟数据未序列化'
      : evidenceScalarText(value.reason);
    var rows = [
      ['结论', value.summary],
      ['状态', value.state],
      ['原因', reasonText],
      ['确认状态', value.confirmation_status],
      ['确认时间', value.confirm_date],
      ['确认年龄', isRecommendationEvidenceFiniteNumber(value.confirm_age_days) ? recommendationSignalAgeText(value.confirm_age_days) : ''],
      ['数据日期', value.latest_date],
      ['最新K线', value.latest_ts || value.latest_bar_at],
      ['K线数量', isRecommendationEvidenceFiniteNumber(value.bars) ? recommendationEvidenceNumber(value.bars) : ''],
      ['终局状态', typeof value.is_final === 'boolean' ? evidenceBooleanText(value.is_final, '已终局', '非终局') : ''],
      ['陈旧状态', typeof value.stale === 'boolean' ? evidenceBooleanText(value.stale, '已陈旧', '未陈旧') : ''],
      ['EMA5', isRecommendationEvidenceFiniteNumber(value.ema5) ? recommendationEvidenceNumber(value.ema5, 2) : ''],
      ['EMA10', isRecommendationEvidenceFiniteNumber(value.ema10) ? recommendationEvidenceNumber(value.ema10, 2) : ''],
      ['EMA5方向', value.ema5_direction],
      ['EMA10方向', value.ema10_direction],
      ['均线状态', value.ema_alignment],
      ['最新收盘价', isRecommendationEvidenceFiniteNumber(value.close) ? recommendationEvidenceNumber(value.close, 2) : ''],
      ['收盘与EMA5', typeof value.close_above_ema5 === 'boolean'
        ? evidenceBooleanText(value.close_above_ema5, '收盘价高于 EMA5', '收盘价未高于 EMA5') : ''],
      ['收盘与EMA10', typeof value.close_above_ema10 === 'boolean'
        ? evidenceBooleanText(value.close_above_ema10, '收盘价高于 EMA10', '收盘价未高于 EMA10') : ''],
      ['MACD DIF', isRecommendationEvidenceFiniteNumber(value.macd_dif) ? recommendationEvidenceNumber(value.macd_dif, 4) : ''],
      ['MACD DEA', isRecommendationEvidenceFiniteNumber(value.macd_dea) ? recommendationEvidenceNumber(value.macd_dea, 4) : ''],
      ['MACD', value.macd_state],
      ['突破保持', typeof value.breakout_holds === 'boolean'
        ? evidenceBooleanText(value.breakout_holds, '突破位保持', '突破位未保持') : value.breakout_holds],
      ['回踩量能', value.pullback_volume_state],
      ['确认依据', value.confirmed_by],
    ];
    var body = renderEvidenceRows(rows);
    var confirmations = recommendationEvidenceList(value.confirmations);
    var confirmedHtml = confirmations.length
      ? evidenceListSection('已满足确认项', confirmations, '')
      : '';
    var missing = renderEvidenceMissingEvidence(value);
    if (!body && !confirmedHtml && !missing) {
      return '<p class="recommendation-evidence-missing">' + escapeHtml(missingCopy) + '</p>';
    }
    return body + confirmedHtml + missing;
  }

  function renderVolumeCapitalEvidence(section) {
    var value = section && typeof section === 'object' ? section : {};
    var sectorFlow = value.sector_capital_flow && typeof value.sector_capital_flow === 'object'
      ? value.sector_capital_flow : {};
    var volumeLabels = recommendationEvidenceList(value.volume_labels);
    var sectorFlowText = evidenceScalarText(value.sector_money_flow_text)
      || evidenceScalarText(value.sector_money_flow)
      || evidenceScalarText(value.sector_net_flow);
    var rows = [
      ['结论', value.summary],
      ['当日成交量', value.current_volume],
      ['当日成交额', value.current_amount_text || value.current_amount],
      ['成交额日期', value.current_amount_as_of],
      ['成交额来源', value.current_amount_source_label],
      ['5日平均成交量', value.average_volume_5],
      ['20日平均成交量', value.volume20],
      ['买点量比', value.volume_ratio],
      ['20日量比', value.ratio20],
      ['20日平均成交额', value.money20_text],
      ['换手率', value.turnover_rate],
      ['量价标签', volumeLabels.join(' · ')],
      ['个股净流入', value.stock_net_flow],
      ['连续净流入天数', value.stock_net_inflow_days],
      ['板块净流入', sectorFlowText],
      ['板块资金排名', isRecommendationEvidenceFiniteNumber(sectorFlow.rank) ? recommendationEvidenceNumber(sectorFlow.rank) : ''],
      ['资金边界', value.capital_state],
      ['资金同向性', value.capital_alignment_state],
    ];
    var body = renderEvidenceRows(rows);
    var missing = renderEvidenceMissingEvidence(value);
    return body || missing
      ? body + missing
      : '<p class="recommendation-evidence-missing">本期未提供可验证的量价与资金证据</p>';
  }

  function renderMarketSectorEvidence(section) {
    var value = section && typeof section === 'object' ? section : {};
    var formal = value.formal_market_sentiment && typeof value.formal_market_sentiment === 'object'
      ? value.formal_market_sentiment : {};
    var components = formal.components && typeof formal.components === 'object'
      ? formal.components : {};
    var componentLabels = {
      breadth: '广度',
      limit_ecology: '涨跌停生态',
      index: '指数',
      turnover: '成交额',
      trend: '趋势',
    };
    var componentText = Object.keys(componentLabels).map(function (key) {
      var text = evidenceScalarText(components[key]);
      return text ? componentLabels[key] + ' ' + text : '';
    }).filter(Boolean).join(' · ');
    function layerState(value) {
      var text = evidenceScalarText(value);
      return ['支持', '分歧', '风险', '未知'].indexOf(text) !== -1 ? text : '未知';
    }
    var rows = [
      ['结论', value.summary],
      ['正式市场情绪', value.market],
      ['市场标签', value.market_label],
      ['正式情绪分', value.market_sentiment_score],
      ['正式组件', componentText],
      ['板块', value.sector],
      ['板块涨跌幅', value.sector_change_pct],
      ['上涨家数', value.sector_up_count],
      ['板块总家数', value.sector_total_count],
      ['涨停家数', value.sector_limit_up_count],
      ['板块净流入', value.sector_net_flow],
      ['板块市场排名', value.sector_market_rank],
      ['个股相对强弱', value.stock_relative_strength],
      ['板块说明', value.sector_state],
      ['市场层', layerState(value.market_state)],
      ['板块层', layerState(value.sector_layer_state)],
      ['个股层', layerState(value.stock_state)],
    ];
    var body = renderEvidenceRows(rows);
    var missing = renderEvidenceMissingEvidence(value);
    return body || missing
      ? body + missing
      : '<p class="recommendation-evidence-missing">本期未提供可验证的市场与板块共振证据</p>';
  }

  function conditionItems(section, key, label) {
    var block = section && section[key] && typeof section[key] === 'object' ? section[key] : {};
    var items = recommendationEvidenceList(block.items);
    var empty = normalizeString(block.empty_text).trim();
    return evidenceListSection(label, items, empty || '当前策略未声明该条件');
  }

  function evidenceListSection(label, items, emptyCopy) {
    return '<section><h4>' + escapeHtml(label) + '</h4>'
      + (items.length
        ? '<ul>' + items.map(function (item) { return '<li>' + escapeHtml(item) + '</li>'; }).join('') + '</ul>'
        : '<p>' + escapeHtml(emptyCopy) + '</p>')
      + '</section>';
  }

  function renderEventRiskSection(section) {
    var value = section && typeof section === 'object' ? section : {};
    var status = evidenceScalarText(value.event_risk_status);
    var source = evidenceScalarText(value.event_risk_source);
    var asOf = evidenceScalarText(value.event_risk_as_of);
    var contractValid = status === 'available' && Boolean(source) && Boolean(asOf);
    var statusLabels = {
      available: contractValid ? '已验证' : '验证信息不完整',
      unverified: '未验证',
      missing: '未提供',
    };
    var statusText = statusLabels[status] || '状态不可验证';
    var items = contractValid ? recommendationEvidenceList(value.event_risks) : [];
    var emptyCopy = status === 'unverified'
      ? '本期事件风险未通过正式验证'
      : (status === 'available' && !contractValid
        ? '事件风险验证信息不完整，相关文案已隐藏'
        : '本期未登记经验证的事件风险');
    return '<section class="recommendation-event-risk"><h4>公告与事件风险</h4>'
      + '<p class="recommendation-event-risk-meta">验证状态：<strong>' + escapeHtml(statusText)
      + '</strong> · 来源：<strong>' + escapeHtml(source || '未提供')
      + '</strong> · 截至：<strong>' + escapeHtml(asOf || '未提供') + '</strong></p>'
      + (items.length
        ? '<ul>' + items.map(function (item) { return '<li>' + escapeHtml(item) + '</li>'; }).join('') + '</ul>'
        : '<p>' + escapeHtml(emptyCopy) + '</p>')
      + '</section>';
  }

  function renderRiskAndNextEvidence(section) {
    var risks = recommendationEvidenceList(section && section.risk_labels);
    return '<div class="recommendation-risk-summary">'
      + (risks.length ? '<strong>' + escapeHtml(risks.join(' · ')) + '</strong>' : '<strong>本期未登记可展示风险标签</strong>')
      + '</div><div class="recommendation-condition-grid">'
      + renderEventRiskSection(section)
      + conditionItems(section, 'next_confirmation', '下一确认')
      + conditionItems(section, 'keep_conditions', '继续保持')
      + conditionItems(section, 'retest_conditions', '等待回踩')
      + conditionItems(section, 'cancel_conditions', '取消或降级')
      + conditionItems(section, 'invalidation_conditions', '结构失效')
      + '</div>';
  }

  function renderMainRiseClue(section) {
    var value = section && typeof section === 'object' ? section : {};
    var label = normalizeString(value.label).trim() || '尚未形成主升浪线索';
    var supporting = recommendationEvidenceList(value.supporting_evidence);
    var opposing = recommendationEvidenceList(value.opposing_evidence);
    var guards = recommendationEvidenceList(value.evidence_guards);
    var note = normalizeString(value.note).trim()
      || '只翻译现有证据，不生成策略、分数或正式动作';
    function evidenceSide(title, items, emptyCopy) {
      return '<section><h4>' + escapeHtml(title) + '</h4>'
        + (items.length
          ? '<ul>' + items.map(function (item) { return '<li>' + escapeHtml(item) + '</li>'; }).join('') + '</ul>'
          : '<p>' + escapeHtml(emptyCopy) + '</p>')
        + '</section>';
    }
    return '<aside class="recommendation-main-rise-clue" data-clue-type="'
      + escapeHtml(normalizeString(value.clue_type).trim() || 'none') + '">'
      + '<header><span>主升浪线索</span><strong>' + escapeHtml(label) + '</strong></header>'
      + '<div class="recommendation-main-rise-sides">'
      + evidenceSide('支持证据', supporting, '本期未提供支持证据')
      + evidenceSide('反对证据', opposing, '本期未提供反对证据')
      + (guards.length ? evidenceSide('证据边界', guards, '') : '')
      + '</div><small>' + escapeHtml(note) + '</small>'
      + '</aside>';
  }

  function historicalMetricText(label, value) {
    if (!isRecommendationEvidenceFiniteNumber(value)) return '';
    var number = Number(value).toFixed(2)
      .replace(/(\.\d*?[1-9])0+$/, '$1')
      .replace(/\.0+$/, '');
    return label + ' ' + number + '%';
  }

  function renderHistoricalHorizon(horizonKey, progress, metrics) {
    var horizon = normalizeString(horizonKey).toUpperCase().replace('T', 'T+');
    var gate = progress && typeof progress === 'object' ? progress : {};
    var values = metrics && typeof metrics === 'object' ? metrics : {};
    var mature = isRecommendationEvidenceFiniteNumber(gate.mature_samples) ? Number(gate.mature_samples) : null;
    var requiredMature = isRecommendationEvidenceFiniteNumber(gate.required_mature_samples) ? Number(gate.required_mature_samples) : null;
    var activeDates = isRecommendationEvidenceFiniteNumber(gate.active_dates) ? Number(gate.active_dates) : null;
    var requiredDates = isRecommendationEvidenceFiniteNumber(gate.required_active_dates) ? Number(gate.required_active_dates) : null;
    var activeMonths = isRecommendationEvidenceFiniteNumber(gate.active_months) ? Number(gate.active_months) : null;
    var requiredMonths = isRecommendationEvidenceFiniteNumber(gate.required_calendar_months) ? Number(gate.required_calendar_months) : null;
    var waiting = isRecommendationEvidenceFiniteNumber(gate.waiting_samples) ? Number(gate.waiting_samples) : null;
    var unavailable = isRecommendationEvidenceFiniteNumber(gate.unavailable_samples) ? Number(gate.unavailable_samples) : null;
    var progressParts = [];
    if (mature !== null && requiredMature !== null) {
      progressParts.push(escapeHtml(recommendationEvidenceNumber(mature)) + ' / ' + escapeHtml(recommendationEvidenceNumber(requiredMature)) + ' 成熟样本');
    }
    if (activeDates !== null && requiredDates !== null) {
      progressParts.push(escapeHtml(recommendationEvidenceNumber(activeDates)) + ' / ' + escapeHtml(recommendationEvidenceNumber(requiredDates)) + ' 活跃日');
    }
    if (activeMonths !== null && requiredMonths !== null) {
      progressParts.push(escapeHtml(recommendationEvidenceNumber(activeMonths)) + ' / ' + escapeHtml(recommendationEvidenceNumber(requiredMonths)) + ' 自然月');
    }
    if (waiting !== null && waiting > 0) progressParts.push('等待成熟 ' + escapeHtml(recommendationEvidenceNumber(waiting)));
    if (unavailable !== null && unavailable > 0) progressParts.push('缺少目标日行情 ' + escapeHtml(recommendationEvidenceNumber(unavailable)));

    var ready = normalizeString(gate.status).trim() === 'ready_for_manual_comparison';
    var metricParts = ready ? [
      (normalizeString(values.date_start).trim() && normalizeString(values.date_end).trim())
        ? '样本区间 ' + normalizeString(values.date_start).trim() + ' 至 ' + normalizeString(values.date_end).trim()
        : '',
      historicalMetricText('均值', values.mean),
      historicalMetricText('中位数', values.median),
      historicalMetricText('上涨率', values.win_rate),
      historicalMetricText('基准超额', values.excess_mean),
      historicalMetricText('MFE', values.mean_mfe),
      historicalMetricText('MAE', values.mean_mae),
      historicalMetricText('最差不利波动', values.max_drawdown),
    ].filter(Boolean) : [];
    return '<section class="recommendation-history-horizon" data-history-horizon="'
      + escapeHtml(normalizeString(horizonKey).toLowerCase()) + '">'
      + '<header><strong>' + escapeHtml(horizon) + '</strong><span>'
      + escapeHtml(ready ? '达到人工比较门槛' : '样本进度') + '</span></header>'
      + (progressParts.length
        ? '<p>' + progressParts.join(' · ') + '</p>'
        : '<p>样本门合同未完整提供</p>')
      + (metricParts.length
        ? '<div class="recommendation-history-metrics">' + metricParts.map(function (item) {
          return '<span>' + escapeHtml(item) + '</span>';
        }).join('') + '</div>'
        : '')
      + '</section>';
  }

  function renderSimulationTracking(tracking) {
    var value = tracking && typeof tracking === 'object' ? tracking : {};
    var status = normalizeString(value.status).trim() || 'missing';
    var label = status === 'missing'
      ? '暂无同合同历史跟踪记录'
      : '策略模拟跟踪';
    if (status === 'missing') {
      return '<aside class="recommendation-simulation-tracking is-missing"><strong>'
        + escapeHtml(label) + '</strong></aside>';
    }
    var facts = [];
    var signalDate = normalizeString(value.signal_date).trim();
    var entryMode = normalizeString(value.entry_mode).trim();
    var intendedHorizon = Number(value.intended_horizon);
    var publicationStatus = normalizeString(value.publication_status).trim();
    var decisionCode = normalizeString(value.decision_code).trim();
    var entryPrice = evidencePositiveNumber(value.entry_price);
    var entrySource = normalizeString(value.entry_price_source).trim();
    if (signalDate) facts.push('信号日 ' + signalDate);
    if (entryMode) facts.push('入场方式 ' + entryMode);
    if ([1, 3, 5].indexOf(intendedHorizon) !== -1) facts.push('声明周期 T+' + intendedHorizon);
    if (publicationStatus) facts.push('发布状态 ' + publicationStatus);
    if (decisionCode) facts.push('记录决策 ' + decisionCode);
    if (entryPrice !== null && entrySource) {
      facts.push('规则入场价 ' + recommendationEvidenceNumber(entryPrice, 2));
      facts.push('价格来源 ' + entrySource);
    } else if (status === 'entry_mode_unknown') {
      facts.push('入场方式未通过合同验证，不生成模拟入场价');
    } else {
      facts.push('本期未提供已验证的模拟入场价');
    }
    return '<aside class="recommendation-simulation-tracking"><strong>'
      + escapeHtml(label) + '</strong><p>' + escapeHtml(facts.join(' · ')) + '</p></aside>';
  }

  function renderHistoricalValidation(section) {
    var value = section && typeof section === 'object' ? section : {};
    var summary = normalizeString(value.summary).trim() || '本期未提供历史验证结果';
    var identity = value.comparison_identity && typeof value.comparison_identity === 'object'
      ? value.comparison_identity : {};
    var progress = value.progress_by_horizon && typeof value.progress_by_horizon === 'object'
      ? value.progress_by_horizon : {};
    var metrics = value.metrics_by_horizon && typeof value.metrics_by_horizon === 'object'
      ? value.metrics_by_horizon : {};
    var identityParts = [];
    if (normalizeString(identity.strategy).trim()) identityParts.push('策略 ' + normalizeString(identity.strategy).trim());
    if (normalizeString(identity.version).trim()) identityParts.push('版本 ' + normalizeString(identity.version).trim());
    if (normalizeString(identity.source_pool).trim()) identityParts.push('来源池 ' + normalizeString(identity.source_pool).trim());
    if (normalizeString(identity.entry_mode).trim()) identityParts.push('入场方式 ' + normalizeString(identity.entry_mode).trim());
    if ([1, 3, 5].indexOf(Number(identity.intended_horizon)) !== -1) {
      identityParts.push('声明周期 T+' + Number(identity.intended_horizon));
    } else {
      identityParts.push('策略未声明统一周期');
    }
    if (normalizeString(identity.research_tier).trim()) identityParts.push('研究层级 ' + normalizeString(identity.research_tier).trim());
    return '<div class="recommendation-historical-validation">'
      + '<p class="recommendation-history-summary">' + escapeHtml(summary) + '</p>'
      + (identityParts.length ? '<p class="recommendation-history-identity">' + escapeHtml(identityParts.join(' · ')) + '</p>' : '')
      + '<div class="recommendation-history-horizons">'
      + ['t1', 't3', 't5'].map(function (key) {
        return renderHistoricalHorizon(key, progress[key], metrics[key]);
      }).join('')
      + '</div>'
      + renderSimulationTracking(value.simulation_tracking)
      + '</div>';
  }

  function renderRecommendationEvidenceAudit(evidence, fallbackDate) {
    var keys = [
      'summary', 'decision_score', 'rank_evidence', 'price_evidence', 'daily_structure',
      'sublevel_30m', 'volume_and_capital', 'market_and_sector', 'risk_and_next',
      'main_rise_clue', 'historical_validation', 'display_derived',
    ];
    return '<details class="evidence-audit-drawer"><summary>证据与审计</summary>'
      + '<div class="evidence-audit-body recommendation-evidence-audit">'
      + keys.map(function (key) {
        var section = evidence[key] && typeof evidence[key] === 'object' ? evidence[key] : {};
        return '<div><strong>' + escapeHtml(key) + '</strong>'
          + renderRecommendationEvidenceMeta(
            section,
            fallbackDate,
            key === 'historical_validation' ? 'historical_validation' : null,
          ) + '</div>';
      }).join('') + '</div></details>';
  }

  function buildChartPlaceholder(item) {
    var helpText = isIncidentReviewItem(item)
      ? '图钉、信号与参考线均为事故前原始证据，仅供追溯；信号日收盘仍使用已核验日线。'
      : '图钉为买点/信号标记，虚线为参考价和现价；拖动或滚动底部缩放条查看细节。';
    return ''
      + '<div class="detail-section">'
      + '  <h3 class="detail-section-title">K线图表</h3>'
      + '  <div class="chart-panel">'
      + '    <div class="chart-toolbar"><div class="chart-help">' + escapeHtml(helpText) + '</div>'
      + '      <div class="chart-layer-switcher" id="chartLayerSwitcher" aria-label="K线图层"></div></div>'
      + '    <div class="chart-annotation-lane hidden" id="chartAnnotationLane" aria-live="polite"></div>'
      + '    <div id="chartCanvas" class="chart-canvas"></div>'
      + '  </div>'
      + '</div>';
  }

  function buildMergedCandidateDetail(item, raw) {
    var evidence = getCandidateRecommendationEvidence(item, state.data);
    if (!evidence) {
      return '<div class="detail-empty-wrap merged-candidate-detail">'
        + '<div class="detail-empty"><strong>本期未提供证据展示</strong></div>'
        + buildChartPlaceholder(item)
        + '</div>';
    }
    var projection = getRecommendationEvidenceProjection(state.data) || {};
    var reportDate = normalizeString(projection.report_date).trim();
    var incidentReview = isIncidentReviewItem(item);
    var summary = evidence.summary && typeof evidence.summary === 'object' ? evidence.summary : {};
    var price = evidence.price_evidence && typeof evidence.price_evidence === 'object' ? evidence.price_evidence : {};
    var daily = evidence.daily_structure && typeof evidence.daily_structure === 'object' ? evidence.daily_structure : {};
    var sublevel = evidence.sublevel_30m && typeof evidence.sublevel_30m === 'object' ? evidence.sublevel_30m : {};
    var volume = evidence.volume_and_capital && typeof evidence.volume_and_capital === 'object' ? evidence.volume_and_capital : {};
    var resonance = evidence.market_and_sector && typeof evidence.market_and_sector === 'object' ? evidence.market_and_sector : {};
    var mainRise = evidence.main_rise_clue && typeof evidence.main_rise_clue === 'object' ? evidence.main_rise_clue : {};
    var risk = evidence.risk_and_next && typeof evidence.risk_and_next === 'object' ? evidence.risk_and_next : {};
    var validation = evidence.historical_validation && typeof evidence.historical_validation === 'object' ? evidence.historical_validation : {};
    return '<div class="detail-empty-wrap merged-candidate-detail">'
      + renderRecommendationEvidenceModule('01', '推荐结论', summary, renderRecommendationConclusion(evidence, incidentReview), reportDate)
      + renderRecommendationEvidenceModule('02', '价格与关键位置', price, renderRecommendationPriceEvidence(evidence), reportDate)
      + buildChartPlaceholder(item)
      + renderRecommendationEvidenceModule('03', '日线结构', daily,
        renderDailyStructureEvidence(daily) + renderMainRiseClue(mainRise), reportDate)
      + renderRecommendationEvidenceModule('04', '30分钟确认', sublevel, renderSublevelEvidence(sublevel), reportDate)
      + renderRecommendationEvidenceModule('05', '量价与资金', volume,
        renderVolumeCapitalEvidence(volume), reportDate)
      + renderRecommendationEvidenceModule('06', '市场与板块共振', resonance,
        renderMarketSectorEvidence(resonance), reportDate)
      + renderRecommendationEvidenceModule('07', '风险与下一步', risk, renderRiskAndNextEvidence(risk), reportDate)
      + renderRecommendationEvidenceModule(
        '08',
        '历史验证与回测提醒',
        validation,
        renderHistoricalValidation(validation),
        reportDate,
        'historical_validation',
      )
      + renderRecommendationEvidenceAudit(evidence, reportDate)
      + '</div>';
  }

  function renderCandidateDetail(item, target) {
    target = target || nodes.detailPanel;
    if (!target) return;

    if (!item) {
      var viewMeta = (getCandidateViews().meta || {})[state.currentView] || {};
      target.innerHTML = state.currentView === 'main'
        ? '<div class="detail-empty"><strong>本期未选出推荐票</strong></div>'
        : buildCandidateEmptyState(state.currentView, viewMeta.availability || {}, { filtered: false });
      return;
    }

    var raw = findRawCandidate(item.ref || {});
    target.innerHTML = buildMergedCandidateDetail(item, raw);
    state.chartMount = target.querySelector('#chartCanvas');
    state.chartAnnotationLane = target.querySelector('#chartAnnotationLane');
    renderChart(raw, item);
  }

  function selectPersistentPriceLabels(labels) {
    var priorities = { invalidation: 0, current: 1, reference: 2, pressure: 3, target: 4 };
    var candidates = asArray(labels).map(function (label) {
      var value = safeNumber(label && label.value, null);
      if (value === null || !Number.isFinite(value) || value <= 0) return null;
      return {
        kind: normalizeString(label.kind),
        kinds: [normalizeString(label.kind)],
        value: value,
        values: [value],
        label: normalizeString(label.label),
        entries: [{
          kind: normalizeString(label.kind),
          value: value,
          label: normalizeString(label.label),
        }],
        labelEntries: [],
        labelVisible: true,
        merged: false,
      };
    }).filter(Boolean).sort(function (left, right) {
      return (priorities[left.kind] === undefined ? 99 : priorities[left.kind])
        - (priorities[right.kind] === undefined ? 99 : priorities[right.kind]);
    });
    var selected = [];
    var labelLanes = [];
    for (var i = 0; i < candidates.length; i += 1) {
      var candidate = candidates[i];
      candidate.labelEntries = candidate.entries.slice();
      var closeTo = labelLanes.filter(function (existing) {
        var base = Math.max(Math.abs(existing.value), Math.abs(candidate.value), 0.0001);
        return Math.abs(existing.value - candidate.value) / base < 0.006;
      })[0];
      if (closeTo) {
        closeTo.merged = true;
        closeTo.labelEntries.push(candidate.entries[0]);
        closeTo.label = [closeTo.label, candidate.label].filter(Boolean).join(' / ');
        candidate.merged = true;
        candidate.labelVisible = false;
      } else {
        labelLanes.push(candidate);
      }
      selected.push(candidate);
    }
    var visibleCount = 0;
    selected.forEach(function (candidate) {
      if (candidate.labelVisible === false) return;
      if (visibleCount >= 2) {
        candidate.labelVisible = false;
        return;
      }
      visibleCount += 1;
    });
    return selected;
  }

  function shortChartSignalLabel(name) {
    var normalized = normalizeString(name);
    if (!normalized) return '';
    if (/底背驰/.test(normalized)) return '底背驰';
    if (/趋势延续/.test(normalized)) return '趋势';
    if (/startup|启动日|启动信号/i.test(normalized)) return '启动';
    if (/确认/.test(normalized)) return '确认';
    return normalized.length > 6 ? normalized.slice(0, 6) + '…' : normalized;
  }

  function formatChartSignalTooltip(point) {
    var coord = asArray(point && point.coord);
    var date = normalizeString(coord[0]);
    var price = safeNumber(coord[1], null);
    var name = normalizeString(point && point.name);
    if (!date || price === null || !Number.isFinite(price) || !name) return '';
    return '<strong>' + escapeHtml(name) + '</strong>'
      + '<br><span>' + escapeHtml(date) + '</span>'
      + '<br><span>价格 ' + escapeHtml(formatNumber(price, 2)) + '</span>';
  }

  function selectChartActionMarkers(markPoints, barCount) {
    var selected = asArray(markPoints).map(function (point, sourceIndex) {
      var coord = asArray(point && point.coord).slice();
      var date = normalizeString(coord[0]);
      var price = safeNumber(coord[1], null);
      var name = normalizeString(point && point.name);
      if (!date || price === null || !Number.isFinite(price) || !name) return null;
      var sourceSize = safeNumber(point && point.symbolSize, 16);
      if (!Number.isFinite(sourceSize)) sourceSize = 16;
      var tooltipHtml = formatChartSignalTooltip({ coord: [date, price], name: name });
      return Object.assign({}, point || {}, {
        coord: [date, price],
        name: name,
        symbolSize: Math.max(6, sourceSize),
        label: Object.assign({}, point && point.label || {}, { show: false }),
        tooltip: Object.assign({}, point && point.tooltip || {}, {
          formatter: function () { return tooltipHtml; },
        }),
        _sourceIndex: sourceIndex,
      });
    }).filter(Boolean);
    if (!selected.length) return [];
    var latestIndex = 0;
    for (var i = 1; i < selected.length; i += 1) {
      var currentBar = safeNumber(selected[i].barIndex, selected[i]._sourceIndex);
      var latestBar = safeNumber(selected[latestIndex].barIndex, selected[latestIndex]._sourceIndex);
      if (currentBar >= latestBar) latestIndex = i;
    }
    return selected.map(function (point, index) {
      var isLatest = index === latestIndex;
      var sourceSize = safeNumber(point.symbolSize, 16);
      var marker = Object.assign({}, point, {
        symbolSize: isLatest ? Math.max(16, sourceSize) : Math.min(10, Math.max(6, sourceSize * 0.6)),
        label: Object.assign({}, point.label || {}, isLatest ? {
          show: true,
          formatter: shortChartSignalLabel(point.name),
          position: 'top',
          distance: 7,
        } : { show: false }),
      });
      delete marker._sourceIndex;
      return marker;
    });
  }

  function buildChartSignalLaneModel(markPoints, extraLabels) {
    var signals = asArray(markPoints).map(function (point, sourceIndex) {
      var coord = asArray(point && point.coord);
      var date = normalizeString(coord[0]);
      var price = safeNumber(coord[1], null);
      var name = normalizeString(point && point.name);
      if (!date || price === null || !Number.isFinite(price) || !name) return null;
      return {
        name: name,
        shortLabel: shortChartSignalLabel(name),
        date: date,
        price: price,
        order: safeNumber(point && point.barIndex, sourceIndex),
        sourceIndex: sourceIndex,
      };
    }).filter(Boolean).sort(function (left, right) {
      if (right.order !== left.order) return right.order - left.order;
      return right.sourceIndex - left.sourceIndex;
    }).slice(0, 3);
    var seenNotes = {};
    var notes = asArray(extraLabels).map(function (label) {
      return normalizeString(label);
    }).filter(function (label) {
      if (!label || seenNotes[label]) return false;
      seenNotes[label] = true;
      return true;
    }).slice(0, 3);
    return { signals: signals, notes: notes };
  }

  function renderChartAnnotationLane(markPoints, extraLabels) {
    var lane = state.chartAnnotationLane;
    if (!lane) return;
    var model = buildChartSignalLaneModel(markPoints, extraLabels);
    if (!model.signals.length && !model.notes.length) {
      lane.innerHTML = '';
      if (lane.classList) lane.classList.toggle('hidden', true);
      return;
    }
    var signalHtml = model.signals.length
      ? '<div class="chart-signal-list" aria-label="特殊信号">' + model.signals.map(function (signal, index) {
        return '<div class="chart-signal-item' + (index === 0 ? ' is-latest' : '') + '">'
          + '<span class="chart-signal-type">' + escapeHtml(signal.shortLabel) + '</span>'
          + '<strong>' + escapeHtml(signal.name) + '</strong>'
          + '<time>' + escapeHtml(signal.date) + '</time>'
          + '</div>';
      }).join('') + '</div>'
      : '';
    var noteHtml = model.notes.length
      ? '<div class="chart-signal-notes" aria-label="信号补充说明">' + model.notes.map(function (note) {
        return '<small>' + escapeHtml(note) + '</small>';
      }).join('') + '</div>'
      : '';
    lane.innerHTML = signalHtml + noteHtml;
    if (lane.classList) lane.classList.toggle('hidden', false);
  }

  function isChartPositivePrice(value) {
    var number = safeNumber(value, null);
    return number !== null && Number.isFinite(number) && number > 0;
  }

  function hasRealMacdEvidence(values) {
    return asArray(values).some(function (value) {
      var number = safeNumber(value, null);
      return number !== null && Number.isFinite(number) && Math.abs(number) > 1e-9;
    });
  }

  function hasFreshConfirmedSublevelEvidence(section) {
    var value = section && typeof section === 'object' ? section : {};
    return normalizeString(value.status).trim() === 'available'
      && normalizeString(value.confirmation_status).trim() === 'confirmed'
      && value.confirmed === true
      && value.stale === false
      && value.is_final === true;
  }

  function isSublevelConfirmationChartAnnotation(annotation) {
    var value = annotation && typeof annotation === 'object' ? annotation : {};
    var label = value.label && typeof value.label === 'object' ? value.label : {};
    var text = (annotation && typeof annotation === 'object'
      ? [value.name, value.type, value.kind, value.interval, value.source, label.formatter]
      : [annotation]
    ).map(evidenceScalarText).filter(Boolean).join(' ').toLowerCase().replace(/\s+/g, '');
    if (!text) return false;
    if (/确认日|confirmationdate|confirm_date/.test(text)) return true;
    return /30(?:m|min|分钟)/.test(text)
      && /确认|confirm|ema5|ema10|金叉|结构/.test(text);
  }

  function chartProjectionAllowsPrice(chartEvidence, field, value) {
    if (!isChartPositivePrice(value)) return false;
    var prices = chartEvidence && chartEvidence.prices;
    if (!prices || !Array.isArray(prices.available)) return true;
    return prices.available.indexOf(field) !== -1;
  }

  function formatPersistentPriceLabel(label) {
    var shortLabels = { invalidation: '止', current: '现', reference: '参', pressure: '压', target: '目' };
    var entries = asArray(label && label.labelEntries);
    if (!entries.length) entries = asArray(label && label.entries);
    if (!entries.length) {
      entries = [{ kind: label && label.kind, value: label && label.value, label: label && label.label }];
    }
    return entries.map(function (entry) {
      var kind = normalizeString(entry && entry.kind);
      var prefix = shortLabels[kind] || '价';
      var targetLabel = kind === 'target'
        ? normalizeString(entry && entry.label).replace(/^目标\s*/, '').trim()
        : '';
      return prefix + (targetLabel ? targetLabel : '') + ' ' + formatNumber(entry && entry.value, 2);
    }).join('\n');
  }

  function persistentPriceLineContract(kind) {
    var contracts = {
      current: { lineType: 'solid', symbol: ['none', 'roundRect'] },
      reference: { lineType: 'dashed', symbol: ['none', 'circle'] },
      invalidation: { lineType: 'solid', symbol: ['none', 'arrow'] },
      pressure: { lineType: 'dotted', symbol: ['none', 'diamond'] },
      target: { lineType: 'dashed', symbol: ['none', 'triangle'] },
    };
    return contracts[kind] || { lineType: 'dashed', symbol: ['none', 'none'] };
  }

  function selectStructureChartLines(rawMarkLines, raw, chartEvidence) {
    var projected = chartEvidence && chartEvidence.pivots
      && typeof chartEvidence.pivots === 'object' ? chartEvidence.pivots : null;
    var sourceLines = projected && Array.isArray(projected.available)
      ? projected.available.map(function (name) {
        return { name: name, yAxis: projected[name] };
      })
      : asArray(rawMarkLines).slice();
    var record = raw && typeof raw === 'object' ? raw : {};
    var pivots = record.pivots && typeof record.pivots === 'object' ? record.pivots : {};
    if (!projected) [
      {
        name: 'ZG',
        value: isChartPositivePrice(record.pivot_zg) ? record.pivot_zg : pivots.ZG,
      },
      {
        name: 'ZD',
        value: isChartPositivePrice(record.pivot_zd) ? record.pivot_zd : pivots.ZD,
      },
    ].forEach(function (pivot) {
      if (!isChartPositivePrice(pivot.value)) return;
      var alreadyPresent = sourceLines.some(function (line) {
        return normalizeString(line && line.name).trim().toUpperCase() === pivot.name
          && isChartPositivePrice(line && line.yAxis);
      });
      if (!alreadyPresent) sourceLines.push({ name: pivot.name, yAxis: pivot.value });
    });
    return sourceLines.map(function (line) {
      var name = normalizeString(line && line.name).trim().toUpperCase();
      var value = safeNumber(line && line.yAxis, null);
      if ((name !== 'ZG' && name !== 'ZD') || !isChartPositivePrice(value)) return null;
      var isUpper = name === 'ZG';
      return {
        name: name,
        yAxis: value,
        label: {
          show: true,
          position: 'end',
          formatter: name + ' ' + formatNumber(value, 2),
          color: isUpper ? '#B91C1C' : '#047857',
        },
        lineStyle: {
          color: isUpper ? '#DC2626' : '#059669',
          width: 1,
          type: 'dotted',
        },
      };
    }).filter(Boolean);
  }

  function getAvailableChartLayers(raw, chartEvidence) {
    var source = raw || {};
    var annotations = source.chart_annotations || {};
    var layers = [];
    if (asArray(annotations.markPoints).length || asArray(annotations.markLines).length
        || source.formal_decision_contract) layers.push('decision');
    if (asArray(source.buy_points).length || asArray(source.reference_buy_points).length
        || source.structure_annotations || selectStructureChartLines(annotations.markLines, source, chartEvidence).length) layers.push('structure');
    if ([source.ema5, source.ema20, source.ma5, source.ma20].some(function (values) {
      return asArray(values).filter(function (value) {
        var number = safeNumber(value, null);
        return number !== null && Number.isFinite(number);
      }).length >= 2;
    })) layers.push('trend');
    if (!layers.length) layers.push('decision');
    return layers;
  }

  function renderChartLayerSwitcher(raw, workspaceItem, chartEvidence) {
    var mount = document.getElementById('chartLayerSwitcher');
    if (!mount) return;
    var labels = { decision: '决策位', structure: '结构', trend: '趋势' };
    var layers = getAvailableChartLayers(raw, chartEvidence);
    if (layers.indexOf(state.chartLayer) === -1) state.chartLayer = layers[0];
    var controls = layers.map(function (layer) {
      return '<button type="button" data-chart-layer="' + escapeHtml(layer) + '" class="'
        + (layer === state.chartLayer ? 'is-active' : '') + '" aria-pressed="'
        + (layer === state.chartLayer ? 'true' : 'false') + '" aria-label="切换K线图层：'
        + escapeHtml(labels[layer]) + '">' + escapeHtml(labels[layer]) + '</button>';
    }).join('');
    var missingTrend = layers.indexOf('trend') === -1
      ? '<span class="chart-layer-status" data-chart-layer-unavailable="trend">本期未提供真实均线序列</span>'
      : '';
    mount.innerHTML = controls + missingTrend;
    var buttons = mount.querySelectorAll('[data-chart-layer]');
    for (var i = 0; i < buttons.length; i += 1) {
      buttons[i].addEventListener('click', function (event) {
        state.chartLayer = event.currentTarget.getAttribute('data-chart-layer');
        renderChart(raw, workspaceItem);
      });
    }
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
      renderChartAnnotationLane([]);
      state.chartMount.innerHTML = '<div class="chart-empty">' + escapeHtml(CHART_EMPTY_TEXT) + '</div>';
      return;
    }

    var dates = asArray(raw.dates);
    var opens = asArray(raw.opens);
    var highs = asArray(raw.highs);
    var lows = asArray(raw.lows);
    var closes = asArray(raw.closes);
    var volumes = asArray(raw.volumes);
    var macd = asArray(raw.macd_hist);
    var minLen = Math.min(dates.length, opens.length, highs.length, lows.length, closes.length);
    if (minLen < 2) {
      renderChartAnnotationLane([]);
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

    function tailAlignChartSeries(values, targetLength, missingValue) {
      var source = asArray(values).slice(-targetLength).map(function (value) {
        var number = safeNumber(value, missingValue);
        return number !== null && Number.isFinite(number) ? number : missingValue;
      });
      while (source.length < targetLength) source.unshift(missingValue);
      return source;
    }

    var volumeSlice = tailAlignChartSeries(volumes, minLen, null);
    var recommendationEvidence = getCandidateRecommendationEvidence(workspaceItem, state.data);
    var priceEvidence = recommendationEvidence && recommendationEvidence.price_evidence;
    var allowSublevelConfirmationAnnotations = hasFreshConfirmedSublevelEvidence(
      recommendationEvidence && recommendationEvidence.sublevel_30m
    );
    var chartEvidence = getCandidateChartEvidence(workspaceItem, state.data);
    var projectedMacd = chartEvidence && chartEvidence.macd;
    var macdAvailable = projectedMacd
      ? normalizeString(projectedMacd.status).trim() === 'available'
        && hasRealMacdEvidence(macd)
      : hasRealMacdEvidence(macd);
    var macdSlice = macdAvailable
      ? tailAlignChartSeries(macd, minLen, null)
      : Array(minLen).fill(null);

    var markPoints = [];
    var incidentReview = isIncidentReviewItem(workspaceItem);
    var annotations = raw.chart_annotations || {};
    var availableLayers = getAvailableChartLayers(raw, chartEvidence);
    if (availableLayers.indexOf(state.chartLayer) === -1) state.chartLayer = availableLayers[0];
    renderChartLayerSwitcher(raw, workspaceItem, chartEvidence);
    var rawMarkPoints = asArray(annotations.markPoints).filter(function (point) {
      return allowSublevelConfirmationAnnotations || !isSublevelConfirmationChartAnnotation(point);
    });
    for (var p = 0; p < rawMarkPoints.length; p += 1) {
      var mp = rawMarkPoints[p] || {};
      var coord = mp.coord || [];
      if (coord.length >= 2) {
        markPoints.push({
          coord: [coord[0], coord[1]],
          barIndex: Math.max(0, xAxis.indexOf(coord[0])),
          name: incidentReview
            ? '事故前信号·仅追溯'
            : normalizeString(mp.name),
          value: coord[1],
          itemStyle: mp.itemStyle || {},
          label: incidentReview
            ? Object.assign({}, mp.label || {}, { formatter: '事故前·仅追溯' })
            : (mp.label || {}),
          symbol: mp.symbol || 'pin',
          symbolSize: mp.symbolSize || 16,
        });
      }
    }

    markPoints = selectChartActionMarkers(markPoints, minLen);
    var annotationLabels = asArray(annotations.labels).filter(function (label) {
      return allowSublevelConfirmationAnnotations || !isSublevelConfirmationChartAnnotation(label);
    });
    renderChartAnnotationLane(markPoints, annotationLabels);

    var priceLabelCandidates = [];
    var rawMarkLines = asArray(annotations.markLines);
    var structureLines = selectStructureChartLines(rawMarkLines, raw, chartEvidence);
    var curPrice = getCandidateCurrentPriceFromRecord(workspaceItem);
    if (curPrice === null && raw && raw !== workspaceItem) {
      curPrice = getCandidateCurrentPriceFromRecord(raw);
    }
    if (curPrice === null) {
      curPrice = safeNumber(priceEvidence && priceEvidence.current_price, null);
    }
    var refPrice = getCandidateReferencePriceFromRecord(workspaceItem);
    if (refPrice === null && raw && raw !== workspaceItem) {
      refPrice = getCandidateReferencePriceFromRecord(raw);
    }
    if (refPrice === null && raw && raw.reference_buy_points && raw.reference_buy_points.length > 0) {
      refPrice = safeNumber(raw.reference_buy_points[0].reference_price, null);
    }
    if (refPrice === null) {
      refPrice = safeNumber(priceEvidence && priceEvidence.reference_price, null);
    }
    if (chartProjectionAllowsPrice(chartEvidence, 'reference_price', refPrice)) {
      priceLabelCandidates.push({
        kind: 'reference',
        value: refPrice,
        label: incidentReview ? '事故前参考·仅追溯' : '参考价',
      });
    }
    if (chartProjectionAllowsPrice(chartEvidence, 'current_price', curPrice)) {
      priceLabelCandidates.push({ kind: 'current', value: curPrice, label: '信号日收盘' });
    }
    var formalContract = workspaceItem && workspaceItem.formal_decision_contract || raw.formal_decision_contract || {};
    var invalidationPrice = safeNumber(
      formalContract.invalidation_price,
      safeNumber(priceEvidence && priceEvidence.invalidation_price, null)
    );
    var pressurePrice = safeNumber(
      formalContract.pressure_price,
      safeNumber(priceEvidence && priceEvidence.pressure_price, null)
    );
    if (chartProjectionAllowsPrice(chartEvidence, 'invalidation_price', invalidationPrice)) {
      priceLabelCandidates.push({ kind: 'invalidation', value: invalidationPrice, label: '失效位' });
    }
    if (chartProjectionAllowsPrice(chartEvidence, 'pressure_price', pressurePrice)) {
      priceLabelCandidates.push({ kind: 'pressure', value: pressurePrice, label: '压力位' });
    }
    asArray(priceEvidence && priceEvidence.trailing_targets).forEach(function (target, index) {
      var source = target && typeof target === 'object' ? target : { price: target };
      var targetPrice = safeNumber(source.price, null);
      if (!chartProjectionAllowsPrice(chartEvidence, 'trailing_targets', targetPrice)) return;
      var targetLabel = normalizeString(source.label).trim();
      priceLabelCandidates.push({
        kind: 'target',
        value: targetPrice,
        label: targetLabel ? '目标 ' + targetLabel : '目标 ' + String(index + 1),
      });
    });
    var canonicalPriceKinds = {};
    priceLabelCandidates.forEach(function (candidate) {
      canonicalPriceKinds[candidate.kind] = true;
    });
    var rawPriceCandidates = {};
    for (var l = 0; l < rawMarkLines.length; l += 1) {
      var ml = rawMarkLines[l] || {};
      if (incidentReview || !ml.name || ml.yAxis === undefined) continue;
      var rawLineName = normalizeString(ml.name);
      var rawKind = /失效|止损/.test(rawLineName)
        ? 'invalidation'
        : (/压力/.test(rawLineName)
          ? 'pressure'
          : (/参考|source/i.test(rawLineName)
            ? 'reference'
            : (/现价|收盘|current/i.test(rawLineName) ? 'current' : '')));
      var rawValue = safeNumber(ml.yAxis, null);
      if (!rawKind || canonicalPriceKinds[rawKind]
          || rawValue === null || !Number.isFinite(rawValue) || rawValue <= 0
          || !chartProjectionAllowsPrice(chartEvidence, rawKind + '_price', rawValue)) continue;
      if (!rawPriceCandidates[rawKind]) rawPriceCandidates[rawKind] = [];
      if (!rawPriceCandidates[rawKind].some(function (candidate) { return candidate.value === rawValue; })) {
        rawPriceCandidates[rawKind].push({ kind: rawKind, value: rawValue, label: rawLineName });
      }
    }
    Object.keys(rawPriceCandidates).forEach(function (kind) {
      if (rawPriceCandidates[kind].length === 1) {
        priceLabelCandidates.push(rawPriceCandidates[kind][0]);
      }
    });
    var persistentLabels = selectPersistentPriceLabels(priceLabelCandidates);
    var markLines = persistentLabels.map(function (label) {
      var contract = persistentPriceLineContract(label.kind);
      return {
        kind: label.kind,
        kinds: label.kinds.slice(),
        values: label.values.slice(),
        name: label.label,
        yAxis: label.value,
        symbol: contract.symbol.slice(),
        label: {
          show: label.labelVisible !== false,
          position: 'end',
          formatter: label.labelVisible === false ? '' : formatPersistentPriceLabel(label),
        },
        lineStyle: {
          type: contract.lineType,
        },
      };
    });

    var activeMarkPoints = state.chartLayer === 'decision' || state.chartLayer === 'structure'
      ? markPoints
      : [];
    var activeMarkLines = state.chartLayer === 'decision'
      ? markLines
      : (state.chartLayer === 'structure' ? structureLines : []);
    var trendSeries = [];
    if (state.chartLayer === 'trend') {
      [[['EMA5', raw.ema5], ['MA5', raw.ma5]], [['EMA20', raw.ema20], ['MA20', raw.ma20]]].forEach(function (candidates) {
        var entry = candidates.filter(function (candidate) {
          return asArray(candidate[1]).filter(function (value) {
            var number = safeNumber(value, null);
            return number !== null && Number.isFinite(number);
          }).length >= 2;
        })[0];
        if (!entry) return;
        trendSeries.push({
          name: entry[0],
          type: 'line',
          data: tailAlignChartSeries(entry[1], minLen, null),
          showSymbol: false,
          smooth: true,
        });
      });
    }

    state.chartInstance = window.echarts.init(state.chartMount);
    var defaultStartIndex = Math.max(0, minLen - 20);
    var defaultStartValue = xAxis[defaultStartIndex];
    var defaultEndValue = xAxis[minLen - 1];
    state.chartInstance.setOption({
      animation: false,
      backgroundColor: '#ffffff',
      grid: [
        { left: state.isMobile ? '10%' : '6%', right: state.isMobile ? '96px' : '124px', top: '4%', height: '51%' },
        { left: state.isMobile ? '10%' : '6%', right: state.isMobile ? '96px' : '124px', top: '59%', height: '12%' },
        { left: state.isMobile ? '10%' : '6%', right: state.isMobile ? '96px' : '124px', top: '75%', height: '12%' },
      ],
      xAxis: [
        {
          type: 'category',
          data: xAxis,
          boundaryGap: true,
          axisLine: { lineStyle: { color: '#d1d5db' } },
          axisLabel: { show: false },
          splitLine: { show: false },
        },
        {
          type: 'category',
          data: xAxis,
          gridIndex: 1,
          boundaryGap: true,
          axisLine: { lineStyle: { color: '#d1d5db' } },
          axisLabel: { show: false },
          splitLine: { show: false },
        },
        {
          type: 'category',
          data: xAxis,
          gridIndex: 2,
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
          name: '成交量',
          nameLocation: 'end',
          nameGap: 4,
          nameTextStyle: { color: '#64748b', fontSize: 10, align: 'right' },
          splitLine: { lineStyle: { color: '#f3f4f6' } },
          axisLine: { show: false },
          axisTick: { show: false },
          axisLabel: { show: false },
        },
        {
          scale: true,
          gridIndex: 2,
          name: 'MACD',
          nameLocation: 'end',
          nameGap: 4,
          nameTextStyle: { color: '#64748b', fontSize: 10, align: 'right' },
          splitLine: { lineStyle: { color: '#f3f4f6' } },
          axisLine: { show: false },
          axisTick: { show: false },
          axisLabel: { show: false },
        },
      ],
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
      },
      dataZoom: [
        { type: 'inside', xAxisIndex: [0, 1, 2], startValue: defaultStartValue, endValue: defaultEndValue },
        { xAxisIndex: [0, 1, 2], height: 18, startValue: defaultStartValue, endValue: defaultEndValue },
      ],
      series: [
        {
          name: 'K线',
          type: 'candlestick',
          data: kLines,
          markPoint: {
            data: activeMarkPoints,
          },
          markLine: {
            symbol: 'none',
            data: activeMarkLines.map(function (line) {
              return {
                kind: line.kind,
                kinds: line.kinds,
                values: line.values,
                name: line.name,
                yAxis: line.yAxis,
                symbol: line.symbol,
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
          name: '成交量',
          type: 'bar',
          xAxisIndex: 1,
          yAxisIndex: 1,
          data: volumeSlice,
          itemStyle: {
            color: function (params) {
              var bar = kLines[params && params.dataIndex];
              if (!bar || volumeSlice[params.dataIndex] === null) return '#94a3b8';
              return bar[1] >= bar[0] ? '#EF4444' : '#10B981';
            },
          },
        },
        {
          name: 'MACD',
          type: 'bar',
          xAxisIndex: 2,
          yAxisIndex: 2,
          data: macdSlice,
          itemStyle: {
            color: function (params) {
              if (params && params.value === null) return '#94a3b8';
              return params.value >= 0 ? '#EF4444' : '#10B981';
            },
          },
        },
      ].concat(trendSeries),
    }, true);
    setTimeout(function () {
      if (state.chartInstance) {
        state.chartInstance.resize();
      }
      if (state.sentimentChartInstance) {
        state.sentimentChartInstance.resize();
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
    var scoreText = temperature.score === null ? '--' : temperature.score + ' / 100';
    var gaugeStyle = '--gauge-score: ' + escapeHtml(temperature.score === null ? 0 : temperature.score) + ';';
    var body = ''
      + '<div class="market-temp-layout">'
      + '  <div class="market-temp-snapshot">'
      + '    <div class="market-temp-gauge is-' + escapeHtml(temperature.tone) + '" style="' + gaugeStyle + '">'
      + '      <div class="gauge-meter" aria-hidden="true"></div>'
      + '      <div class="gauge-value">' + escapeHtml(scoreText) + '</div>'
      + '      <div class="gauge-summary">' + escapeHtml(temperature.summary) + '</div>'
      + '    </div>'
      + '    <div class="metric-pair-grid">'
      + renderMetricPair('市场情绪', scoreText, 'is-' + escapeHtml(temperature.tone))
      + renderMetricPair('广度得分', (components.breadth_score === null || components.breadth_score === undefined) ? '--' : components.breadth_score, '')
      + renderMetricPair('指数得分', (components.index_score === null || components.index_score === undefined) ? '--' : components.index_score, '')
      + renderMetricPair('涨跌停生态', (components.limit_score === null || components.limit_score === undefined) ? '--' : components.limit_score, '')
      + renderMetricPair('量能得分', (components.volume_score === null || components.volume_score === undefined) ? '--' : components.volume_score, '')
      + renderMetricPair('趋势结构', (components.trend_score === null || components.trend_score === undefined) ? '--' : components.trend_score, '')
      + renderMetricPair('指标组件覆盖', temperature.coverage === null || temperature.coverage === undefined ? '--' : Math.round(temperature.coverage * 100) + '%', '')
      + '    </div>'
      + '  </div>'
      + '  <div class="market-temp-trend">'
      + '    <div id="marketSentimentChart" class="market-sentiment-chart" aria-label="最近20个交易日市场情绪折线图"></div>'
      + '  </div>'
      + '</div>'
      + renderPsy12ShadowSubpanel(data || {});
    return renderDecisionCard({
      title: '市场情绪',
      subtitle: '全A宽度、涨跌停生态、成交与趋势结构',
      badge: { text: temperature.label, tone: temperature.tone },
      className: 'market-temperature-card',
      bodyHtml: body,
    });
  }

  function psy12UnavailableText(reason, validDays) {
    if (reason === 'insufficient_history') {
      return 'PSY12 数据不足：已有 ' + Math.max(0, safeNumber(validDays, 0)) + ' / 12 个有效交易日。';
    }
    if (reason === 'future_date') return 'PSY12 数据异常：窗口包含报告日之后的证据。';
    if (reason === 'duplicate_date') return 'PSY12 数据异常：窗口包含重复交易日。';
    if (reason === 'unordered_dates') return 'PSY12 数据异常：交易日顺序不可验证。';
    if (reason === 'unverifiable_index_evidence') return 'PSY12 数据异常：指数涨跌证据不可验证。';
    return 'PSY12 数据不足，暂不生成影子分。';
  }

  function getPsy12ShadowAudit(data) {
    var projection = getRecommendationEvidenceProjection(data);
    if (!projection) return null;
    var market = projection.market_sentiment;
    if (!market || typeof market !== 'object') return null;
    var audit = market.psy12_shadow_audit;
    return audit && typeof audit === 'object' ? audit : null;
  }

  function renderPsy12AuditProgress(audit) {
    var boundary = '<div class="psy12-promotion-boundary">'
      + '<code>affects_production=false</code>'
      + '<code>promotion_eligible=false</code>'
      + '<strong>达到 20 个完整交易日也仍需新授权</strong>'
      + '</div>';
    if (!audit || typeof audit !== 'object') {
      return '<div class="psy12-audit-progress is-missing">'
        + '<strong>影子评测进度未随本期报告提供</strong>'
        + '<span>不得用 PSY12 的 12 日窗口推断 20 日审计进度。</span>'
        + '</div>' + boundary;
    }
    var required = isRecommendationEvidenceFiniteNumber(audit.required_days)
      && Number(audit.required_days) > 0 ? Number(audit.required_days) : null;
    var stored = isRecommendationEvidenceFiniteNumber(audit.stored_complete_days)
      && Number(audit.stored_complete_days) >= 0 ? Number(audit.stored_complete_days) : null;
    var recomputable = isRecommendationEvidenceFiniteNumber(audit.recomputable_days)
      ? Number(audit.recomputable_days) : null;
    var complete = isRecommendationEvidenceFiniteNumber(audit.complete_days)
      ? Number(audit.complete_days) : null;
    var missing = isRecommendationEvidenceFiniteNumber(audit.missing_days)
      ? Number(audit.missing_days) : null;
    var mismatch = isRecommendationEvidenceFiniteNumber(audit.mismatch_days)
      ? Number(audit.mismatch_days) : null;
    var status = normalizeString(audit.status).trim() || 'missing';
    var statusText = {
      insufficient_observation_days: '持续收集中',
      ready_for_manual_review: '达到人工复核门槛',
      recalculation_mismatch: '复算存在差异',
      missing: '审计缺失',
    }[status] || status;
    var unsafeContract = audit.affects_production !== false
      || audit.promotion_eligible !== false
      || audit.promotion_requires_new_authorization !== true;
    var reason = normalizeString(audit.reason).trim();
    var asOf = normalizeString(audit.as_of_date).trim();
    if (status === 'missing' || status === 'failed' || status === 'unavailable') {
      return '<div class="psy12-audit-progress is-missing' + (unsafeContract ? ' is-warning' : '') + '">'
        + '<strong>影子评测进度未随本期报告提供</strong>'
        + '<span>不得用 PSY12 的 12 日窗口推断 20 日审计进度。</span>'
        + '<small>状态：' + escapeHtml(statusText)
        + (asOf ? ' · 截至 ' + escapeHtml(asOf) : '')
        + (reason ? ' · ' + escapeHtml(reason) : '') + '</small>'
        + (unsafeContract ? '<em>审计载荷越界，页面已强制保持影子隔离。</em>' : '')
        + '</div>' + boundary;
    }
    var progress = required !== null && stored !== null
      ? '<div class="psy12-audit-progress-value"><span>影子评测进度</span><strong>'
        + escapeHtml(recommendationEvidenceNumber(stored)) + ' / '
        + escapeHtml(recommendationEvidenceNumber(required)) + '</strong></div>'
      : '<strong>影子评测进度未随本期报告提供</strong>';
    var stats = [
      recomputable === null ? '' : '可重算 ' + recommendationEvidenceNumber(recomputable) + ' 日',
      complete === null ? '' : '复算一致 ' + recommendationEvidenceNumber(complete) + ' 日',
      missing === null ? '' : '缺失 ' + recommendationEvidenceNumber(missing) + ' 日',
      mismatch === null ? '' : '差异 ' + recommendationEvidenceNumber(mismatch) + ' 日',
    ].filter(Boolean);
    return '<div class="psy12-audit-progress' + (unsafeContract ? ' is-warning' : '') + '">'
      + progress
      + (stats.length ? '<p>' + escapeHtml(stats.join(' · ')) + '</p>' : '')
      + '<small>状态：' + escapeHtml(statusText)
      + (asOf ? ' · 截至 ' + escapeHtml(asOf) : '')
      + (reason ? ' · ' + escapeHtml(reason) : '') + '</small>'
      + (unsafeContract ? '<em>审计载荷越界，页面已强制保持影子隔离。</em>' : '')
      + '</div>' + boundary;
  }

  function renderPsy12ShadowSubpanel(data) {
    data = data || {};
    var psy12 = data.psy12 || {};
    var shadow = data.psy12_shadow || {};
    var shadowWeights = shadow.weights && typeof shadow.weights === 'object'
      ? shadow.weights : {};
    var rawPsy12Weight = shadowWeights.psy12;
    var psy12Weight = typeof rawPsy12Weight === 'number' && Number.isFinite(rawPsy12Weight)
      ? rawPsy12Weight : null;
    var psy12WeightValid = psy12Weight !== null && Math.abs(psy12Weight - 0.1) < 1e-12;
    var auditProgress = renderPsy12AuditProgress(getPsy12ShadowAudit(data));
    var evidence = getRecommendationEvidenceProjection(data);
    var marketEvidence = evidence && evidence.market_sentiment
      && typeof evidence.market_sentiment === 'object'
      ? evidence.market_sentiment : {};
    var projectedContract = marketEvidence.psy12_shadow_contract
      && typeof marketEvidence.psy12_shadow_contract === 'object'
      ? marketEvidence.psy12_shadow_contract : null;
    var contract = projectedContract || shadow;
    var shadowBoundaryConflict = shadow.promotion_eligible === true
      || shadow.promotion_requires_new_authorization === false;
    var contractValid = shadow.schema_version === 1
      && shadow.mode === 'shadow'
      && shadow.affects_production === false
      && !shadowBoundaryConflict
      && contract.schema_version === 1
      && contract.mode === 'shadow'
      && contract.affects_production === false
      && contract.promotion_eligible === false
      && contract.promotion_requires_new_authorization === true
      && (!projectedContract || projectedContract.status === 'available');
    if (!contractValid) {
      return renderDecisionCard({
        title: 'PSY12 影子情绪',
        subtitle: '最近 12 个有效交易日上涨持续性',
        badge: { text: '合同不可用', tone: 'danger' },
        className: 'psy12-shadow-card psy12-shadow-subpanel',
        bodyHtml: '<div class="psy12-shadow-notice is-error">PSY12 影子合同不可用，正式决策未采用该结果。</div>'
          + auditProgress,
      });
    }

    if (!psy12WeightValid) {
      return renderDecisionCard({
        title: 'PSY12 影子情绪',
        subtitle: '最近 12 个有效交易日上涨持续性',
        badge: { text: '权重不可验证', tone: 'danger' },
        className: 'psy12-shadow-card psy12-shadow-subpanel',
        bodyHtml: '<div class="psy12-shadow-notice is-error">影子权重不可验证，未展示加权后的影子结果；正式决策未采用该结果。</div>'
          + auditProgress,
      });
    }

    var available = psy12.status === 'available'
      && shadow.status === 'available'
      && safeNumber(psy12.score, null) !== null
      && safeNumber(psy12.up_days, null) !== null
      && safeNumber(psy12.valid_days, null) === 12
      && safeNumber(shadow.formal_score, null) !== null
      && safeNumber(shadow.shadow_score_with_psy12, null) !== null;
    if (!available) {
      return renderDecisionCard({
        title: 'PSY12 影子情绪',
        subtitle: '最近 12 个有效交易日上涨持续性',
        badge: { text: '数据不足', tone: 'neutral' },
        className: 'psy12-shadow-card psy12-shadow-subpanel',
        bodyHtml: ''
          + '<div class="psy12-shadow-notice">影子，不影响正式决策</div>'
          + '<div class="decision-empty">'
          + escapeHtml(psy12UnavailableText(psy12.reason || shadow.reason, psy12.valid_days))
          + '</div>'
          + auditProgress,
      });
    }

    var formalScore = safeNumber(shadow.formal_score, null);
    var shadowScore = safeNumber(shadow.shadow_score_with_psy12, null);
    var delta = safeNumber(shadow.delta_vs_formal, shadowScore - formalScore);
    var psy12WeightText = formatNumber(psy12Weight * 100, 0) + '%';
    var formalLabel = normalizeString(shadow.formal_label || '--');
    var shadowLabel = normalizeString(shadow.shadow_label || '--');
    var labelDifference = formalLabel !== shadowLabel
      ? '<div class="psy12-label-difference">正式标签 ' + escapeHtml(formalLabel)
        + ' · 影子标签 ' + escapeHtml(shadowLabel)
        + '；差异只用于研究验证，首屏保持正式标签。</div>'
      : '<div class="psy12-label-difference is-same">正式与影子标签均为 '
        + escapeHtml(formalLabel) + '。</div>';
    var directions = asArray(psy12.daily_directions);
    var audit = directions.length
      ? '<details class="psy12-direction-audit"><summary>查看 12 日方向审计</summary><div>'
        + directions.map(function (item) {
          return '<span><b>' + escapeHtml(normalizeString(item.date || '--')) + '</b>'
            + escapeHtml(item.direction === 'up' ? '上涨' : '非上涨') + '</span>';
        }).join('') + '</div></details>'
      : '';
    var body = ''
      + '<div class="psy12-shadow-notice">影子，不影响正式决策</div>'
      + '<div class="psy12-shadow-grid">'
      + '  <div><span>窗口</span><strong>' + escapeHtml(normalizeString(psy12.start_date)) + ' 至 ' + escapeHtml(normalizeString(psy12.end_date)) + '</strong></div>'
      + '  <div><span>上涨日</span><strong>' + escapeHtml(String(psy12.up_days)) + ' / ' + escapeHtml(String(psy12.valid_days)) + '</strong></div>'
      + '  <div><span>PSY12</span><strong>' + escapeHtml(formatNumber(psy12.score, 0)) + '</strong></div>'
      + '  <div><span>正式分</span><strong>' + escapeHtml(formatNumber(formalScore, 0)) + '</strong></div>'
      + '  <div><span>影子分</span><strong>' + escapeHtml(formatNumber(shadowScore, 0)) + '</strong></div>'
      + '  <div><span>差值</span><strong>' + escapeHtml((delta > 0 ? '+' : '') + formatNumber(delta, 0)) + '</strong></div>'
      + '</div>'
      + '<div class="psy12-shadow-notice">加入 ' + escapeHtml(psy12WeightText) + ' 后：'
      + escapeHtml(formatNumber(shadowScore, 0) + ' · ' + shadowLabel + ' · Δ' + (delta > 0 ? '+' : '') + formatNumber(delta, 0))
      + '</div>'
      + labelDifference
      + audit
      + auditProgress;
    return renderDecisionCard({
      title: 'PSY12 影子情绪',
      subtitle: '最近 12 个有效交易日上涨持续性',
      badge: { text: '影子评测', tone: 'info' },
      className: 'psy12-shadow-card psy12-shadow-subpanel',
      bodyHtml: body,
    });
  }

  function renderPsy12ShadowCard(data) {
    return renderPsy12ShadowSubpanel(data);
  }

  function renderMarketSentimentChart() {
    var mount = document.getElementById('marketSentimentChart');
    if (!mount || !window.echarts) return;
    if (state.sentimentChartInstance) {
      state.sentimentChartInstance.dispose();
      state.sentimentChartInstance = null;
    }
    var history = asArray((state.data || {}).market_sentiment_history).slice(-20);
    if (!history.length) {
      mount.innerHTML = '<div class="decision-empty">暂无可复算的历史情绪证据</div>';
      return;
    }
    var dates = history.map(function (item) { return normalizeString(item.date || ''); });
    var scores = history.map(function (item) { return safeNumber(item.score, null); });
    var averages = history.map(function (item) { return safeNumber(item.ma3, null); });
    var turnPoints = history.reduce(function (result, item, index) {
      if (!item || !item.turning_signal || safeNumber(item.score, null) === null) return result;
      result.push({
        name: item.turning_signal === 'turning_stronger' ? '转强' : '转弱',
        coord: [index, item.score],
        value: item.score,
      });
      return result;
    }, []);
    state.sentimentChartInstance = window.echarts.init(mount);
    state.sentimentChartInstance.setOption({
      animation: false,
      grid: { left: 40, right: 18, top: 32, bottom: 42 },
      legend: { top: 0, data: ['每日情绪', '3日均线'] },
      tooltip: {
        trigger: 'axis',
        formatter: function (params) {
          var index = params && params.length ? params[0].dataIndex : 0;
          var point = history[index] || {};
          var ecology = ((point.evidence || {}).limit_ecology || {});
          var ratio = safeNumber(ecology.limit_ratio, null);
          return [
            escapeHtml(point.date || '--'),
            '情绪：' + escapeHtml(point.score === null || point.score === undefined ? '--' : point.score),
            '涨停：' + escapeHtml(ecology.limit_up_count === undefined ? '--' : ecology.limit_up_count),
            '跌停：' + escapeHtml(ecology.limit_down_count === undefined ? '--' : ecology.limit_down_count),
            '涨跌停比：' + escapeHtml(ratio === null ? '--' : formatNumber(ratio, 2)),
          ].join('<br>');
        },
      },
      xAxis: {
        type: 'category',
        data: dates,
        axisLabel: {
          formatter: function (value) { return value.slice(5); },
        },
      },
      yAxis: { type: 'value', min: 0, max: 100, interval: 20 },
      series: [
        {
          name: '每日情绪',
          type: 'line',
          data: scores,
          connectNulls: false,
          symbolSize: 6,
          lineStyle: { width: 2, color: '#2563EB' },
          itemStyle: { color: '#2563EB' },
          markArea: {
            silent: true,
            data: [
              [{ yAxis: 0, itemStyle: { color: 'rgba(22,163,74,.06)' } }, { yAxis: 30 }],
              [{ yAxis: 30, itemStyle: { color: 'rgba(6,182,212,.05)' } }, { yAxis: 45 }],
              [{ yAxis: 45, itemStyle: { color: 'rgba(100,116,139,.04)' } }, { yAxis: 60 }],
              [{ yAxis: 60, itemStyle: { color: 'rgba(245,158,11,.05)' } }, { yAxis: 75 }],
              [{ yAxis: 75, itemStyle: { color: 'rgba(220,38,38,.05)' } }, { yAxis: 100 }],
            ],
          },
          markPoint: {
            symbolSize: 42,
            data: turnPoints,
          },
        },
        {
          name: '3日均线',
          type: 'line',
          data: averages,
          connectNulls: false,
          showSymbol: false,
          lineStyle: { width: 2, type: 'dashed', color: '#EA580C' },
        },
      ],
    });
  }

  function renderFlowRow(kind, item) {
    var rec = item || {};
    var flow = [rec.flow_str, rec.net_flow_str, rec.amount_str].map(normalizeString).filter(Boolean)[0] || '';
    if (!flow) {
      var numericFlow = null;
      ['flow', 'net_flow', 'amount'].some(function (key) {
        if (!Object.prototype.hasOwnProperty.call(rec, key)) return false;
        var value = safeNumber(rec[key], null);
        if (value === null) return false;
        numericFlow = value;
        return true;
      });
      flow = numericFlow === null ? '--' : formatNumber(numericFlow, 2);
    }
    var tone = kind === '流入' ? 'in' : 'out';
    return ''
      + '<div class="flow-row">'
      + '  <span class="flow-chip is-' + escapeHtml(tone) + '">' + escapeHtml(kind) + '</span>'
      + '  <span class="flow-name">' + escapeHtml(normalizeString(rec.name || rec.sector || '--')) + '</span>'
      + '  <strong class="flow-value ' + (tone === 'in' ? 'is-up' : 'is-down') + '">' + escapeHtml(normalizeString(flow || '--')) + '</strong>'
      + '</div>';
  }

  function normalizeSectorName(value) {
    return normalizeString(value).trim().replace(/\s+/g, ' ');
  }

  function candidateSectorCodes(item) {
    var rec = item || {};
    var codes = [];
    function append(value) {
      var code = normalizeString(value).trim();
      if (code && codes.indexOf(code) === -1) codes.push(code);
    }
    append(rec.sector_code);
    asArray(rec.sector_refs).forEach(function (ref) {
      if (ref && typeof ref === 'object') {
        append(ref.sector_code || ref.code);
      } else {
        append(ref);
      }
    });
    return codes;
  }

  function filterCandidatesBySector(items, sectorName, sectorCode, sectorRefs) {
    var rows = asArray(items);
    var target = normalizeSectorName(sectorName);
    var targetCode = normalizeString(sectorCode).trim();
    var exactRefs = asArray(sectorRefs).map(function (ref) {
      return normalizeString(ref).trim();
    }).filter(Boolean);
    if (!target && !targetCode && !exactRefs.length) return rows.slice();
    return rows.filter(function (item) {
      if (exactRefs.length) {
        return exactRefs.indexOf(normalizeString(item && item.code).trim()) !== -1;
      }
      if (targetCode) {
        return candidateSectorCodes(item).indexOf(targetCode) !== -1;
      }
      return normalizeSectorName(item && (item.sector_name || item.sector)) === target;
    });
  }

  function buildFundingMainlineModel(data) {
    var source = data || {};
    var sectorHeat = source.sector_heat;
    var heatItems = asArray(sectorHeat && sectorHeat.items);
    var verifiedHeat = sectorHeat
      && !Array.isArray(sectorHeat)
      && normalizeString(sectorHeat.status) === 'verified_complete'
      && heatItems.length > 0
      && heatItems.every(function (item) {
        return normalizeString(item && item.status) === 'verified_complete'
          && normalizeSectorName(item && item.sector_name)
          && normalizeString(item && item.sector_code)
          && safeNumber(item && item.change_pct, null) !== null
          && safeNumber(item && item.rank, null) !== null
          && safeNumber(item && item.up_count, null) !== null
          && safeNumber(item && item.total_count, null) !== null
          && safeNumber(item && item.limit_up_count, null) !== null;
      });
    if (verifiedHeat) {
      return {
        title: '热门板块',
        status: { label: '收盘核验', tone: 'positive', detail: '' },
        items: heatItems.slice(0, 5).map(function (item) {
          var changePct = safeNumber(item.change_pct, null);
          return {
            name: normalizeSectorName(item.sector_name),
            sectorCode: normalizeString(item.sector_code),
            sectorRefs: asArray(item.sector_refs).map(normalizeString).filter(Boolean),
            direction: changePct !== null && changePct < 0 ? 'heat-down' : 'heat-up',
            kind: 'heat',
            fact: item,
          };
        }),
      };
    }
    var sectorIn = asArray(source.sector_flow);
    var sectorOut = asArray(source.sector_outflow);
    var status = getSectorFlowStatus(source, sectorIn, sectorOut);
    var seen = {};
    var items = [];
    function append(rows, direction) {
      asArray(rows).slice(0, 5).forEach(function (item) {
        var name = normalizeSectorName(item && (item.name || item.sector));
        if (!name || seen[name]) return;
        seen[name] = true;
        items.push({ name: name, direction: direction, fact: item });
      });
    }
    append(sectorIn, 'in');
    append(sectorOut, 'out');
    return {
      title: '资金主线',
      status: status,
      items: items,
    };
  }

  function renderFundingMainline(model, activeSector, activeSectorCode) {
    var rec = model || { title: '资金主线', status: {}, items: [] };
    var active = normalizeSectorName(activeSector);
    var activeCode = normalizeString(activeSectorCode).trim();
    var status = rec.status || {};
    var tags = asArray(rec.items).map(function (item) {
      var name = normalizeSectorName(item && item.name);
      var sectorCode = normalizeString(item && item.sectorCode).trim();
      var sectorRefs = asArray(item && item.sectorRefs).map(normalizeString).filter(Boolean);
      var selected = activeCode ? sectorCode === activeCode : (!sectorCode && name === active);
      var fact = item && item.fact || {};
      var heatFacts = '';
      if (item && item.kind === 'heat') {
        var change = safeNumber(fact.change_pct, null);
        var flowText = normalizeString(fact.net_flow_text);
        heatFacts = '<small>'
          + (change === null ? '' : escapeHtml(formatPct(change, true)))
          + ' · 涨 ' + escapeHtml(normalizeString(fact.up_count)) + '/' + escapeHtml(normalizeString(fact.total_count))
          + ' · 涨停 ' + escapeHtml(normalizeString(fact.limit_up_count))
          + (flowText ? ' · ' + escapeHtml(flowText) : '')
          + '</small>';
      }
      return '<button type="button" class="funding-mainline-tag is-' + escapeHtml(item.direction || 'in')
        + (selected ? ' is-active' : '') + '" data-sector-filter="' + escapeHtml(name)
        + '" data-sector-code="' + escapeHtml(sectorCode)
        + '" data-sector-refs="' + escapeHtml(sectorRefs.join(',')) + '" aria-pressed="'
        + (selected ? 'true' : 'false') + '"><strong>' + escapeHtml(name) + '</strong>' + heatFacts + '</button>';
    }).join('');
    var body = tags || '<span class="funding-mainline-state is-' + escapeHtml(status.tone || 'neutral') + '">'
      + escapeHtml(status.detail || '板块资金事实尚未生成。') + '</span>';
    return '<div class="funding-mainline-heading"><strong>' + escapeHtml(rec.title || '资金主线') + '</strong>'
      + '<small>' + escapeHtml(status.label || '状态待确认') + '</small></div>'
      + '<div class="funding-mainline-tags">' + body
      + (active || activeCode ? '<button type="button" class="funding-mainline-clear" data-sector-filter="" data-sector-code="" data-sector-refs="">清除筛选</button>' : '')
      + '</div>';
  }

  function renderFundingMainlineStrip() {
    if (!nodes.sectorStrip) return;
    var model = buildFundingMainlineModel(state.data || {});
    nodes.sectorStrip.setAttribute('aria-label', model.title || '资金主线');
    nodes.sectorStrip.innerHTML = renderFundingMainline(
      model,
      state.sectorFilter,
      state.sectorFilterCode,
      state.sectorFilterRefs
    );
    var buttons = nodes.sectorStrip.querySelectorAll('[data-sector-filter]');
    for (var i = 0; i < buttons.length; i += 1) {
      buttons[i].addEventListener('click', function (event) {
        var requested = normalizeSectorName(event.currentTarget.getAttribute('data-sector-filter'));
        var requestedCode = normalizeString(event.currentTarget.getAttribute('data-sector-code')).trim();
        var requestedRefs = normalizeString(event.currentTarget.getAttribute('data-sector-refs'))
          .split(',').map(function (ref) { return ref.trim(); }).filter(Boolean);
        var sameFilter = requestedCode
          ? requestedCode === state.sectorFilterCode
          : (!state.sectorFilterCode && requested === state.sectorFilter);
        state.sectorFilter = sameFilter ? '' : requested;
        state.sectorFilterCode = sameFilter ? '' : requestedCode;
        state.sectorFilterRefs = sameFilter ? [] : requestedRefs;
        state.candidateLimit = 20;
        var filtered = filterCandidatesBySector(
          getCurrentViewItems(), state.sectorFilter, state.sectorFilterCode,
          state.sectorFilterRefs
        );
        state.activeItem = filtered[0] || null;
        renderFundingMainlineStrip();
        renderCandidateList();
        renderCandidateDetail(state.activeItem);
      });
    }
  }

  function getSectorFlowStatus(data, sectorIn, sectorOut) {
    var source = data || {};
    var quality = source.data_quality || {};
    var hasIn = Object.prototype.hasOwnProperty.call(source, 'sector_flow');
    var hasOut = Object.prototype.hasOwnProperty.call(source, 'sector_outflow');
    var trustedSource = normalizeString(quality.sector_source);
    if (!hasIn && !hasOut) {
      return { label: '证据不足', tone: 'danger', detail: '板块资金字段未生成，不等于资金流为空。' };
    }
    if (!hasIn || !hasOut) {
      return { label: '部分可用', tone: 'warning', detail: '流入或流出侧缺失，仅展示已取得部分。' };
    }
    if (!sectorIn.length && !sectorOut.length) {
      return trustedSource
        ? { label: '确认空池', tone: 'neutral', detail: '已连接 ' + trustedSource + '，本次上游返回空列表。' }
        : { label: '证据不足', tone: 'danger', detail: '板块来源未登记，空数组不能作为确认空池。' };
    }
    return { label: '数据可用', tone: 'positive', detail: '' };
  }

  function renderSectorFlowCard(data) {
    var sectorIn = asArray((data || {}).sector_flow).slice(0, 5);
    var sectorOut = asArray((data || {}).sector_outflow).slice(0, 5);
    var allRows = sectorIn.concat(sectorOut);
    var insufficient = allRows.some(function (item) {
      return item && item.hierarchy_dedup_status === 'insufficient_evidence';
    });
    var partial = allRows.some(function (item) {
      return item && item.hierarchy_dedup_status === 'partial_check_only';
    });
    var hierarchyVerified = allRows.length > 0 && allRows.every(function (item) {
      var status = normalizeString(item && item.hierarchy_dedup_status);
      return status === 'checked_unique' || status === 'deduped_representative';
    });
    var hierarchyUnknown = allRows.length > 0 && !insufficient && !partial && !hierarchyVerified;
    var flowStatus = getSectorFlowStatus(data, sectorIn, sectorOut);
    var hierarchyText = insufficient || partial
      ? '层级证据部分不足'
      : (hierarchyVerified
        ? '层级已核验并去重'
        : (hierarchyUnknown ? '层级状态未记录' : '无板块样本可核验'));
    var emptyText = flowStatus.detail || '已验证为空';
    var inHtml = sectorIn.length ? sectorIn.map(function (item) { return renderFlowRow('流入', item); }).join('') : '<div class="decision-empty">' + escapeHtml(emptyText) + '</div>';
    var outHtml = sectorOut.length ? sectorOut.map(function (item) { return renderFlowRow('流出', item); }).join('') : '<div class="decision-empty">' + escapeHtml(emptyText) + '</div>';
    var body = ''
      + '<div class="flow-columns">'
      + '  <div><div class="mini-section-title">流入 Top5</div>' + inHtml + '</div>'
      + '  <div><div class="mini-section-title">流出 Top5</div>' + outHtml + '</div>'
      + '</div>';
    return renderDecisionCard({
      title: '板块资金',
      subtitle: '资金流入与流出方向 · ' + hierarchyText,
      badge: {
        text: flowStatus.label === '数据可用' ? hierarchyText : flowStatus.label,
        tone: insufficient || partial || hierarchyUnknown ? 'warning' : flowStatus.tone,
      },
      className: 'sector-flow-card',
      bodyHtml: body,
    });
  }

  function getLimitUpStatusMeta(status) {
    if (status === 'verified_complete') return { label: '数据完整', tone: 'positive' };
    if (status === 'verified_empty') return { label: '确认空池', tone: 'neutral' };
    if (status === 'partial') return { label: '数据不完整', tone: 'warning' };
    if (status === 'error') return { label: '数据异常', tone: 'danger' };
    return { label: '数据缺失', tone: 'neutral' };
  }

  function renderLimitUpEcologyCard(data) {
    var snapshot = (data || {}).limit_up_snapshot || {};
    var status = normalizeString(snapshot.status || 'missing');
    var meta = getLimitUpStatusMeta(status);
    var total = safeNumber(snapshot.raw_total, null);
    var parsed = safeNumber(snapshot.parsed_count, null);
    var coverage = safeNumber(snapshot.coverage, null);
    var downTotal = safeNumber(snapshot.limit_down_total, null);
    var allGroups = asArray(snapshot.theme_groups);
    var allLeaders = asArray(snapshot.leaders);
    var groups = allGroups.slice(0, 5);
    var leaders = allLeaders.slice(0, 5);
    var groupTitle = allGroups.length > 5
      ? '题材梯队（前5 / 共' + allGroups.length + '）'
      : '题材梯队（共' + allGroups.length + '）';
    var leaderTitle = allLeaders.length > 5
      ? '领涨样本（前5 / 共' + allLeaders.length + '）'
      : '领涨样本（共' + allLeaders.length + '）';
    var stateHtml = '';
    if (status === 'verified_empty') {
      stateHtml = '<div class="decision-empty is-verified">上游明确返回 0 只涨停</div>';
    } else if (status === 'partial') {
      stateHtml = '<div class="decision-empty is-warning">仅展示已解析部分，不能据此判断完整涨停生态</div>';
    } else if (status === 'error') {
      stateHtml = '<div class="decision-empty is-error">涨停数据存在冲突或解析异常</div>';
    } else if (status === 'missing') {
      stateHtml = '<div class="decision-empty">数据缺失，不等于没有涨停</div>';
    }
    var metrics = ''
      + '<div class="metric-pair-grid ecology-metrics">'
      + '  <div class="metric-pair"><span>涨停总数</span><strong>' + escapeHtml(total === null ? '--' : formatNumber(total, 0)) + '</strong></div>'
      + '  <div class="metric-pair"><span>跌停总数</span><strong>' + escapeHtml(downTotal === null ? '--' : formatNumber(downTotal, 0)) + '</strong></div>'
      + '  <div class="metric-pair"><span>成功解析</span><strong>' + escapeHtml(parsed === null ? '--' : formatNumber(parsed, 0)) + '</strong></div>'
      + '  <div class="metric-pair"><span>解析覆盖率</span><strong>' + escapeHtml(coverage === null ? '--' : formatPct(coverage * 100)) + '</strong></div>'
      + '</div>';
    var groupHtml = groups.length ? groups.map(function (group) {
      return '<span class="ecology-theme"><strong>' + escapeHtml(group.name || '--') + '</strong><small>' + escapeHtml(formatNumber(group.count, 0)) + '只</small></span>';
    }).join('') : '<span class="evidence-missing">暂无可验证题材梯队</span>';
    var leaderHtml = leaders.length ? leaders.map(function (leader) {
      var boards = safeNumber(leader.lianban, 0);
      return ''
        + '<div class="ecology-leader">'
        + '  <span><strong>' + escapeHtml(leader.name || '--') + '</strong><small>' + escapeHtml(leader.code || '') + '</small></span>'
        + '  <span>' + escapeHtml(leader.sector || '题材未标注') + '</span>'
        + '  <strong>' + escapeHtml(boards > 1 ? formatNumber(boards, 0) + '连板' : normalizeString(leader.first_time || '首板')) + '</strong>'
        + '</div>';
    }).join('') : '<div class="evidence-missing">暂无已验证领涨样本</div>';
    return renderDecisionCard({
      title: '涨停生态',
      subtitle: '总量、题材梯队与领涨样本放在同一证据面板',
      badge: { text: meta.label, tone: meta.tone },
      className: 'limit-up-ecology-card',
      bodyHtml: stateHtml + metrics
        + '<div class="ecology-section"><span class="mini-section-title">' + escapeHtml(groupTitle) + '</span><div class="ecology-themes">' + groupHtml + '</div></div>'
        + '<div class="ecology-section"><span class="mini-section-title">' + escapeHtml(leaderTitle) + '</span><div class="ecology-leaders">' + leaderHtml + '</div></div>',
    });
  }

  function getDirectionMeta(direction, stage, hasRiskReasons, hasVerifiedRisk) {
    if (direction === 'positive') return { label: '偏多', tone: 'up' };
    if (direction === 'negative') {
      if (stage === 'risk') {
        return hasVerifiedRisk
          ? { label: '风险', tone: 'down' }
          : { label: '风险待核实', tone: 'warning' };
      }
      return { label: '负向待核验', tone: 'warning' };
    }
    if (direction === 'mixed') {
      return hasRiskReasons
        ? { label: hasVerifiedRisk ? '分化含风险' : '分化含风险待核实', tone: 'warning' }
        : { label: '分化', tone: 'warning' };
    }
    return { label: '观察', tone: 'neutral' };
  }

  function getRiskReasonFlags(riskReasons) {
    var reasons = asArray(riskReasons);
    return {
      hasReasons: reasons.some(function (item) {
        if (typeof item === 'string') return Boolean(normalizeString(item).trim());
        return Boolean(normalizeString(item && (item.detail || item.reason || item.summary || item.text)).trim());
      }),
      hasVerified: reasons.some(function (item) {
        return item && typeof item === 'object' && !Array.isArray(item)
          && normalizeString(item.verification_status) === 'verified'
          && Boolean(normalizeString(item.detail || item.reason || item.summary || item.text).trim());
      }),
    };
  }

  function getStageLabel(stage, hasVerifiedRisk) {
    if (stage === 'confirmed') return '盘面已确认';
    if (stage === 'developing') return '催化待确认';
    if (stage === 'risk') return hasVerifiedRisk ? '风险成立' : '风险待核实';
    return '继续观察';
  }

  function resolveDirectionConditions(rec) {
    var row = rec || {};
    var hasExplicitConditionContract = Array.isArray(row.confirmation_conditions)
      || Array.isArray(row.invalidation_conditions);
    var legacyNegativeContract = row.direction === 'negative'
      && !hasExplicitConditionContract;
    return {
      triggerItems: hasExplicitConditionContract
        ? row.confirmation_conditions
        : (legacyNegativeContract ? row.invalidation : row.next_trigger),
      invalidationItems: hasExplicitConditionContract
        ? row.invalidation_conditions
        : (legacyNegativeContract ? row.next_trigger : row.invalidation),
    };
  }

  function renderEvidenceStep(label, value, stateLabel) {
    var text = normalizeString(value);
    return ''
      + '<div class="evidence-step' + (text ? '' : ' is-missing') + '">'
      + '  <span>' + escapeHtml(label) + '</span>'
      + '  <strong>' + escapeHtml(text || stateLabel || '未验证') + '</strong>'
      + '</div>';
  }

  function buildEvidenceRegistryMap(decisionBrief) {
    var registryMap = {};
    asArray((decisionBrief || {}).evidence_registry).forEach(function (evidence) {
      var ref = normalizeString(evidence && evidence.evidence_ref);
      if (ref) registryMap[ref] = evidence;
    });
    return registryMap;
  }

  function renderDirectionRow(row, index, registryMap) {
    var rec = row || {};
    var riskReasons = asArray(rec.risk_reasons);
    var riskFlags = getRiskReasonFlags(riskReasons);
    var hasRiskReasons = riskFlags.hasReasons;
    var hasVerifiedRisk = riskFlags.hasVerified;
    var meta = getDirectionMeta(rec.direction, rec.stage, hasRiskReasons, hasVerifiedRisk);
    var eventRefs = asArray(rec.evidence_refs).filter(function (ref) {
      return normalizeString(ref).indexOf('event:') === 0;
    });
    var eventEvidence = eventRefs.map(function (ref) {
      return registryMap[normalizeString(ref)] || null;
    }).filter(Boolean);
    var eventTitles = eventEvidence.map(function (evidence) {
      var score = safeNumber(evidence.impact_score, null);
      return normalizeString(evidence.title || '事件标题缺失')
        + (score === null ? '' : ' · 影响' + formatNumber(score, 0));
    });
    var sectors = asArray(rec.sector_links).map(function (link) {
      var evidence = registryMap[normalizeString(link && link.evidence_ref)] || {};
      var linkType = normalizeString(link && link.link_type);
      if (linkType !== 'sector_flow' && normalizeString(evidence.kind) !== 'sector_flow') {
        return '';
      }
      var change = safeNumber(evidence.change_pct, null);
      return normalizeString(link && link.name)
        + (change === null ? '' : ' ' + formatPct(change, true));
    }).filter(Boolean);
    var limitEvidence = asArray(rec.evidence_refs).map(function (ref) {
      var evidence = registryMap[normalizeString(ref)] || null;
      return evidence && evidence.kind === 'limit_up_theme' ? evidence : null;
    }).filter(Boolean);
    var limitLabels = limitEvidence.map(function (evidence) {
      var count = safeNumber(evidence.count, null);
      return normalizeString(evidence.name || '涨停题材')
        + (count === null ? '' : ' ' + formatNumber(count, 0) + '只');
    });
    var stocks = asArray(rec.stock_links);
    var stockRoleLabels = {
      candidate_intersection: '候选池交集',
      watchlist_intersection: '重点池',
      limit_up_leader: '领涨样本',
      news_named: '事件点名',
    };
    var stockNames = stocks.map(function (link) {
      var linkType = normalizeString(link && link.link_type);
      var role = stockRoleLabels[linkType] || '关联类型未登记';
      return normalizeString(link && link.name) + '·' + role;
    }).filter(Boolean);
    var isEstablishedRisk = rec.direction === 'negative'
      && rec.stage === 'risk'
      && hasVerifiedRisk;
    var isNegativePending = rec.direction === 'negative' && !isEstablishedRisk;
    var riskReasonHtml = riskReasons.map(function (item) {
      var structured = item && typeof item === 'object' && !Array.isArray(item);
      var reason = structured
        ? normalizeString(item.detail || item.reason || item.summary || item.text)
        : normalizeString(item);
      if (!reason) return '';
      var verification = structured
        ? normalizeString(item.verification_status)
        : '';
      var verificationLabel = verification === 'verified'
        ? '规则核实'
        : (verification === 'model_extracted' || verification === 'model_grounded'
          ? '模型提取待核实'
          : '核实状态未标注');
      var refs = structured ? asArray(item.evidence_refs).map(normalizeString).filter(Boolean) : [];
      return '<li><span>' + escapeHtml(reason) + '</span><small>'
        + escapeHtml(verificationLabel)
        + (refs.length ? ' · ' + escapeHtml(refs.join(' / ')) : '')
        + '</small></li>';
    }).filter(Boolean).join('');
    var riskReasonBlock = hasRiskReasons
      ? '<div><span>风险原因</span><ul>'
        + riskReasonHtml
        + '</ul></div>'
      : '';
    var triggerLabel = isEstablishedRisk
      ? '风险升级条件'
      : (isNegativePending ? '负向确认条件' : '下一确认');
    var invalidationLabel = isEstablishedRisk
      ? '风险解除条件'
      : (isNegativePending ? '负向解除条件' : '失效条件');
    var summary = normalizeString(rec.llm_summary || rec.rule_summary || '暂无方向解释');
    var conditions = resolveDirectionConditions(rec);
    var triggerItems = conditions.triggerItems;
    var invalidationItems = conditions.invalidationItems;
    var triggerHtml = asArray(triggerItems).map(function (item) {
      return '<li>' + escapeHtml(item) + '</li>';
    }).join('');
    var invalidationHtml = asArray(invalidationItems).map(function (item) {
      return '<li>' + escapeHtml(item) + '</li>';
    }).join('');
    var refHtml = asArray(rec.evidence_refs).slice(0, 8).map(function (ref) {
      return '<code>' + escapeHtml(ref) + '</code>';
    }).join('');
    return ''
      + '<details class="decision-direction"' + (index === 0 ? ' open' : '') + '>'
      + '  <summary>'
      + '    <span class="direction-rank">' + escapeHtml(String(index + 1)) + '</span>'
      + '    <span class="direction-heading"><strong>' + escapeHtml(rec.theme || '--') + '</strong><small>' + escapeHtml(summary) + '</small></span>'
      + '    <span class="status-badge is-' + escapeHtml(meta.tone) + '">' + escapeHtml(meta.label) + '</span>'
      + '    <span class="direction-stage">' + escapeHtml(getStageLabel(rec.stage, hasVerifiedRisk)) + '</span>'
      + '  </summary>'
      + '  <div class="evidence-chain">'
      + renderEvidenceStep('事件', eventTitles.join(' / '), eventRefs.length ? '事件标题缺失' : '无事件证据')
      + renderEvidenceStep('板块', sectors.join(' / '), '资金未验证')
      + renderEvidenceStep('盘面', limitLabels.length ? limitLabels.join(' / ') + ' · ' + getStageLabel(rec.stage, hasVerifiedRisk) : getStageLabel(rec.stage, hasVerifiedRisk), '待盘面确认')
      + renderEvidenceStep('个股', stockNames.join(' / '), '未映射到个股')
      + '  </div>'
      + '  <div class="direction-detail-grid">'
      + riskReasonBlock
      + '    <div><span>' + escapeHtml(triggerLabel) + '</span><ul>' + (triggerHtml || '<li>暂无新增确认条件</li>') + '</ul></div>'
      + '    <div><span>' + escapeHtml(invalidationLabel) + '</span><ul>' + (invalidationHtml || '<li>暂无新增失效条件</li>') + '</ul></div>'
      + '  </div>'
      + '  <div class="evidence-refs"><span>证据编号</span>' + (refHtml || '<small>暂无</small>') + '</div>'
      + '</details>';
  }

  function renderDecisionDirections(data) {
    var decisionBrief = (data || {}).decision_brief || {};
    var rows = asArray(decisionBrief.theses).slice(0, 3);
    var registryMap = buildEvidenceRegistryMap(decisionBrief);
    var status = normalizeString(decisionBrief.status || 'missing');
    var statusText = status === 'ok' ? 'LLM 已审计' : (status === 'rules_only' ? '规则生成，未经过 LLM 复核' : '暂无方向');
    var body = rows.length ? rows.map(function (row, index) {
      return renderDirectionRow(row, index, registryMap);
    }).join('') : ''
      + '<div class="decision-empty">今天没有通过证据门的方向，不为凑数生成结论。</div>';
    if (decisionBrief.llm_error) body += '<div class="decision-source-note">模型复核未完成；技术错误已列入数据诊断。</div>';
    return renderDecisionCard({
      title: '今日方向',
      subtitle: '事件 → 板块 → 盘面 → 个股，最多三条且不凑数',
      badge: { text: statusText, tone: rows.length ? 'info' : 'neutral' },
      className: 'decision-directions-card',
      bodyHtml: body,
    });
  }

  function getWatchDirectionRows(decisionBrief, code) {
    return asArray((decisionBrief || {}).theses).filter(function (thesis) {
      return asArray(thesis && thesis.watchlist_impacts).map(normalizeString).indexOf(code) !== -1;
    });
  }

  function getWatchPoolLabel(pool) {
    var labels = {
      pure: '基础候选池（原始缠论结构）',
      fusion: '融合候选全集',
      observation: '观察池',
      next_day_boom: '次日爆发策略池',
      luojie: '罗姐策略池',
      h4_t3_pool: 'H4 T+3 策略池',
      sector: '板块池',
      event: '事件池',
    };
    return labels[normalizeString(pool)] || normalizeString(pool || '候选池');
  }

  function renderWatchPriceLevels(priceLevels) {
    var labels = {
      support: '支撑',
      resistance: '压力',
      range_low_20d: '20日区间低',
      range_high_20d: '20日区间高',
    };
    var rows = Object.keys(priceLevels || {}).slice(0, 4).map(function (key) {
      var value = safeNumber(priceLevels[key], null);
      if (value === null) return '';
      return '<span>' + escapeHtml(labels[key] || key) + ' <strong>' + escapeHtml(formatNumber(value, 2)) + '</strong></span>';
    }).filter(Boolean);
    return rows.length ? rows.join('') : '<span class="is-muted">关键价位待确认</span>';
  }

  function renderWatchDirectionAnalysis(directionRows, registryMap) {
    if (!directionRows.length) {
      return '<div class="watch-direction-empty">今日暂无方向级证据关联；这不是个股独立结论。</div>';
    }
    return directionRows.map(function (thesis) {
      var thesisRiskFlags = getRiskReasonFlags(thesis.risk_reasons);
      var meta = getDirectionMeta(
        thesis.direction,
        thesis.stage,
        thesisRiskFlags.hasReasons,
        thesisRiskFlags.hasVerified
      );
      var eventTitles = asArray(thesis.evidence_refs).map(function (ref) {
        var evidence = registryMap[normalizeString(ref)] || null;
        return evidence && evidence.kind === 'event' ? normalizeString(evidence.title) : '';
      }).filter(Boolean);
      var sectors = asArray(thesis.sector_links).map(function (link) {
        var evidence = registryMap[normalizeString(link && link.evidence_ref)] || {};
        var linkType = normalizeString(link && link.link_type);
        if (linkType !== 'sector_flow' && normalizeString(evidence.kind) !== 'sector_flow') {
          return '';
        }
        return normalizeString(link && link.name);
      }).filter(Boolean);
      var stockRoleLabels = {
        leader: '方向龙头',
        beneficiary: '受益关联',
        candidate_intersection: '候选池交集',
        watchlist_intersection: '重点池',
        limit_up_leader: '领涨样本',
        news_named: '事件点名',
      };
      var stockLinks = asArray(thesis.stock_links).map(function (link) {
        var roleKey = normalizeString(link && (link.role || link.link_type));
        var role = stockRoleLabels[roleKey] || '关联角色未登记';
        var identity = [
          normalizeString(link && link.name),
          normalizeString(link && link.code),
        ].filter(Boolean).join(' ');
        if (!identity) return '';
        return '<span><strong>' + escapeHtml(identity) + '</strong><small>'
          + escapeHtml(role) + '</small></span>';
      }).filter(Boolean).join('');
      var hasLlm = Boolean(normalizeString(thesis.llm_summary));
      var sourceLabel = hasLlm ? '方向级 LLM 关联' : '方向级规则关联';
      var summary = normalizeString(thesis.llm_summary || thesis.rule_summary || '暂无方向解释');
      var conditions = resolveDirectionConditions(thesis);
      var trigger = asArray(conditions.triggerItems).map(normalizeString).filter(Boolean).join('；') || '暂无新增确认条件';
      var invalidation = asArray(conditions.invalidationItems).map(normalizeString).filter(Boolean).join('；') || '暂无新增失效条件';
      var establishedRisk = thesis.direction === 'negative'
        && thesis.stage === 'risk'
        && thesisRiskFlags.hasVerified;
      var negativePending = thesis.direction === 'negative' && !establishedRisk;
      var triggerLabel = establishedRisk
        ? '风险升级条件'
        : (negativePending ? '负向确认条件' : '下一确认');
      var invalidationLabel = establishedRisk
        ? '风险解除条件'
        : (negativePending ? '负向解除条件' : '失效条件');
      var riskHtml = asArray(thesis.risk_reasons).map(function (item) {
        var structured = item && typeof item === 'object' && !Array.isArray(item);
        var reason = structured
          ? normalizeString(item.detail || item.reason || item.summary || item.text)
          : normalizeString(item);
        if (!reason) return '';
        var verification = structured ? normalizeString(item.verification_status) : '';
        var verificationLabel = verification === 'verified'
          ? '规则核实'
          : (verification === 'model_extracted' || verification === 'model_grounded'
            ? '模型提取待核实'
            : '核实状态未标注');
        var refs = structured
          ? asArray(item.evidence_refs).map(normalizeString).filter(Boolean)
          : [];
        return '<li><span>' + escapeHtml(reason) + '</span><small>'
          + escapeHtml(verificationLabel)
          + (refs.length ? ' · ' + escapeHtml(refs.join(' / ')) : '')
          + '</small></li>';
      }).filter(Boolean).join('');
      return ''
        + '<div class="watch-direction-analysis">'
        + '  <div class="watch-direction-heading">'
        + '    <span><strong>' + escapeHtml(thesis.theme || '--') + '</strong><small>' + escapeHtml(sourceLabel) + '</small></span>'
        + '    <span class="status-badge is-' + escapeHtml(meta.tone) + '">' + escapeHtml(meta.label) + '</span>'
        + '  </div>'
        + '  <div class="watch-direction-links">'
        + '    <span>事件 <strong>' + escapeHtml(eventTitles.join(' / ') || '未关联事件') + '</strong></span>'
      + '    <span>板块 <strong>' + escapeHtml(sectors.join(' / ') || '未关联板块') + '</strong></span>'
      + '  </div>'
      + (stockLinks
        ? '  <div class="watch-direction-stocks"><span>关联个股</span><div>' + stockLinks + '</div></div>'
        : '')
      + '  <p>' + escapeHtml(summary) + '</p>'
        + (riskHtml ? '<div class="watch-direction-risks"><span>风险原因</span><ul>' + riskHtml + '</ul></div>' : '')
        + '  <div class="watch-direction-gates">'
        + '    <span>' + escapeHtml(triggerLabel) + ' <strong>' + escapeHtml(trigger) + '</strong></span>'
        + '    <span>' + escapeHtml(invalidationLabel) + ' <strong>' + escapeHtml(invalidation) + '</strong></span>'
        + '  </div>'
        + '  <small class="watch-direction-disclaimer">方向证据关联，不是个股独立结论。</small>'
        + '</div>';
    }).join('');
  }

  function watchlistManagerState() {
    state.watchlistManager = state.watchlistManager || {};
    return state.watchlistManager;
  }

  function confirmDiscardWatchlistChanges() {
    var manager = watchlistManagerState();
    if (!manager.dirty) return true;
    if (typeof window.confirm !== 'function') return false;
    return window.confirm('重点观察池有未保存修改。确定放弃这些修改并重新载入吗？');
  }

  function normalizeWatchlistManagerConfig(payload, personalWatchlist) {
    var source = payload && Array.isArray(payload.items) ? payload : null;
    var items = source ? payload.items : asArray((personalWatchlist || {}).items);
    return {
      revision: normalizeString(
        (source && source.revision)
        || (personalWatchlist || {}).config_revision
        || 'snapshot-unknown'
      ),
      updated_at: normalizeString((source && source.updated_at) || ''),
      items: items.map(function (item, index) {
        var rec = item || {};
        return {
          code: normalizeString(rec.code).trim(),
          note: normalizeString(rec.note || rec.name || rec.code).trim(),
          role: normalizeString(rec.role || 'strong_watch'),
          enabled: rec.enabled !== false,
          priority: index + 1,
          tags: asArray(rec.tags).slice(0, 5),
          thesis: normalizeString(rec.thesis || ''),
        };
      }),
    };
  }

  function setWatchlistManagerMessage(message, tone) {
    var manager = watchlistManagerState();
    manager.message = normalizeString(message);
    manager.tone = normalizeString(tone || 'neutral');
  }

  function addWatchlistManagerItem(code, note) {
    var manager = watchlistManagerState();
    var normalizedCode = normalizeString(code).trim();
    if (!/^(?:6\d{5}|(?:000|001|002|003|300|301)\d{3}|[48]\d{5}|92\d{4})$/.test(normalizedCode)) {
      setWatchlistManagerMessage('股票代码格式不正确', 'danger');
      return false;
    }
    manager.config = manager.config || { revision: 'snapshot-unknown', items: [] };
    if (manager.config.items.some(function (item) { return item.code === normalizedCode; })) {
      setWatchlistManagerMessage('该股票已在重点观察池', 'warning');
      return false;
    }
    if (manager.config.items.length >= 20) {
      setWatchlistManagerMessage('重点观察池最多 20 只', 'warning');
      return false;
    }
    manager.config.items.push({
      code: normalizedCode,
      note: normalizeString(note || normalizedCode).trim(),
      role: 'strong_watch',
      enabled: true,
      priority: manager.config.items.length + 1,
      tags: ['用户重点观察'],
      thesis: '',
    });
    manager.dirty = true;
    setWatchlistManagerMessage('已加入待保存列表', 'info');
    return true;
  }

  function removeWatchlistManagerItem(index) {
    var manager = watchlistManagerState();
    if (!manager.config || !manager.config.items[index]) return false;
    manager.config.items.splice(index, 1);
    manager.config.items.forEach(function (item, itemIndex) {
      item.priority = itemIndex + 1;
    });
    manager.dirty = true;
    setWatchlistManagerMessage('已移除，保存后生效', 'info');
    return true;
  }

  function moveWatchlistManagerItem(index, direction) {
    var manager = watchlistManagerState();
    if (!manager.config) return false;
    var target = index + direction;
    if (index < 0 || target < 0 || index >= manager.config.items.length || target >= manager.config.items.length) return false;
    var moved = manager.config.items.splice(index, 1)[0];
    manager.config.items.splice(target, 0, moved);
    manager.config.items.forEach(function (item, itemIndex) {
      item.priority = itemIndex + 1;
    });
    manager.dirty = true;
    setWatchlistManagerMessage('顺序已调整，保存后生效', 'info');
    return true;
  }

  function toggleWatchlistManagerItem(index, enabled) {
    var manager = watchlistManagerState();
    if (!manager.config || !manager.config.items[index]) return false;
    manager.config.items[index].enabled = Boolean(enabled);
    manager.dirty = true;
    setWatchlistManagerMessage('启用状态已修改，保存后生效', 'info');
    return true;
  }

  function renderWatchlistManager(personalWatchlist) {
    var manager = watchlistManagerState();
    var apiBase = getDecisionWatchlistUrl();
    var config = manager.config || normalizeWatchlistManagerConfig(null, personalWatchlist);
    var liveRevision = normalizeString(config.revision || '--');
    var snapshotRevision = normalizeString((personalWatchlist || {}).config_revision || '--');
    var rows = asArray(config.items).map(function (item, index) {
      var rec = item || {};
      return ''
        + '<div class="watchlist-manager-row" data-watch-index="' + index + '">'
        + '  <label class="watchlist-manager-enabled"><input type="checkbox" data-watch-field="enabled"' + (rec.enabled === false ? '' : ' checked') + '>启用</label>'
        + '  <input class="watchlist-manager-code" data-watch-field="code" value="' + escapeHtml(rec.code || '') + '" maxlength="6" inputmode="numeric" aria-label="股票代码">'
        + '  <input class="watchlist-manager-name" data-watch-field="note" value="' + escapeHtml(rec.note || '') + '" maxlength="24" aria-label="备注（名称自动识别）" placeholder="备注（名称自动识别）">'
        + '  <select data-watch-field="role" aria-label="观察角色">'
        + '    <option value="strong_watch"' + (rec.role === 'strong_watch' ? ' selected' : '') + '>强观察</option>'
        + '    <option value="watch"' + (rec.role === 'watch' ? ' selected' : '') + '>普通观察</option>'
        + '    <option value="research"' + (rec.role === 'research' ? ' selected' : '') + '>研究</option>'
        + '    <option value="risk_watch"' + (rec.role === 'risk_watch' ? ' selected' : '') + '>风险观察</option>'
        + '  </select>'
        + '  <textarea data-watch-field="thesis" maxlength="240" aria-label="个人观察逻辑" placeholder="写下你关注它的逻辑">' + escapeHtml(rec.thesis || '') + '</textarea>'
        + '  <div class="watchlist-manager-actions">'
        + '    <button type="button" data-watch-action="up" aria-label="上移"' + (index === 0 ? ' disabled' : '') + '>↑</button>'
        + '    <button type="button" data-watch-action="down" aria-label="下移"' + (index === config.items.length - 1 ? ' disabled' : '') + '>↓</button>'
        + '    <button type="button" data-watch-action="remove">移除</button>'
        + '  </div>'
        + '</div>';
    }).join('');
    var statusText = manager.message || (manager.loading ? '正在载入线上配置…' : '线上配置与当前日报分析快照彼此独立');
    var disabled = !apiBase || manager.loading || manager.saving;
    return ''
      + '<details class="watchlist-manager"' + (manager.open ? ' open' : '') + '>'
      + '  <summary><span><strong>管理重点观察池</strong><small>增删、排序、停用</small></span><span>当前 ' + escapeHtml(String(config.items.length)) + ' 只</span></summary>'
      + '  <div class="watchlist-manager-panel">'
      + '    <div class="watchlist-manager-revisions"><span>线上配置 <strong>' + escapeHtml(liveRevision) + '</strong></span><span>本日报快照 <strong>' + escapeHtml(snapshotRevision) + '</strong></span></div>'
      + '    <p class="watchlist-manager-snapshot-note">保存只更新后续配置；当前日报快照及其中的 LLM 分析不会被改写。</p>'
      + '    <div class="watchlist-manager-list">' + (rows || '<div class="decision-empty">观察池为空，可在下方新增</div>') + '</div>'
      + '    <div class="watchlist-manager-add"><input data-watch-add-code maxlength="6" inputmode="numeric" aria-label="新增股票代码" placeholder="股票代码"><input data-watch-add-note maxlength="24" aria-label="备注（名称自动识别）" placeholder="备注（名称自动识别）"><button type="button" data-watch-action="add">加入</button></div>'
      + '    <div class="watchlist-manager-save"><label>管理密码<input type="password" data-watch-password autocomplete="current-password" placeholder="仅本次保存使用"></label><button type="button" data-watch-action="save"' + (disabled ? ' disabled' : '') + '>' + (manager.saving ? '保存中…' : '保存配置') + '</button><button type="button" data-watch-action="reload"' + (!apiBase || manager.loading ? ' disabled' : '') + '>重新载入线上配置</button></div>'
      + '    <p class="watchlist-manager-status is-' + escapeHtml(manager.tone || 'neutral') + '">' + escapeHtml(statusText) + '</p>'
      + (!apiBase ? '<p class="watchlist-manager-status is-warning">管理接口未配置；本日报仍显示内嵌快照。</p>' : '')
      + '  </div>'
      + '</details>';
  }

  function loadWatchlistManagerConfig(force) {
    var manager = watchlistManagerState();
    var apiBase = getDecisionWatchlistUrl();
    if (!apiBase || !window.fetch || manager.loading || (manager.loaded && !force)) return;
    manager.loading = true;
    manager.message = '正在载入线上配置…';
    window.fetch(apiBase, { method: 'GET', cache: 'no-store' }).then(function (resp) {
      if (!resp || !resp.ok) throw new Error('线上配置加载失败');
      manager.etag = normalizeString(resp.headers && resp.headers.get ? resp.headers.get('ETag') : '');
      return resp.json();
    }).then(function (payload) {
      manager.config = normalizeWatchlistManagerConfig(payload, {});
      manager.loaded = true;
      manager.dirty = false;
      manager.conflict = false;
      setWatchlistManagerMessage('线上配置已载入；当前日报快照保持不变', 'positive');
    }).catch(function () {
      manager.loaded = true;
      setWatchlistManagerMessage('线上配置加载失败，仍保留当前日报快照', 'danger');
    }).finally(function () {
      manager.loading = false;
      renderAuxiliaryCenter();
    });
  }

  function syncWatchlistManagerForm(root) {
    var manager = watchlistManagerState();
    if (!manager.config || !root) return;
    Array.prototype.forEach.call(root.querySelectorAll('[data-watch-index]'), function (row) {
      var index = Number(row.getAttribute('data-watch-index'));
      var item = manager.config.items[index];
      if (!item) return;
      Array.prototype.forEach.call(row.querySelectorAll('[data-watch-field]'), function (field) {
        var key = field.getAttribute('data-watch-field');
        item[key] = key === 'enabled' ? Boolean(field.checked) : normalizeString(field.value).trim();
      });
    });
  }

  function saveWatchlistManagerConfig(root) {
    var manager = watchlistManagerState();
    var apiBase = getDecisionWatchlistUrl();
    if (!apiBase || !window.fetch || manager.saving) return;
    syncWatchlistManagerForm(root);
    var passwordInput = root && root.querySelector('[data-watch-password]');
    var password = normalizeString(passwordInput && passwordInput.value).trim();
    if (passwordInput) passwordInput.value = '';
    if (!password) {
      setWatchlistManagerMessage('请输入管理密码后再保存', 'warning');
      renderAuxiliaryCenter();
      return;
    }
    if (!manager.etag) {
      setWatchlistManagerMessage('缺少线上版本，请先重新载入线上配置', 'warning');
      renderAuxiliaryCenter();
      return;
    }
    manager.saving = true;
    manager.open = true;
    setWatchlistManagerMessage('正在保存配置…', 'info');
    window.fetch(apiBase, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + password,
        'If-Match': manager.etag,
      },
      body: JSON.stringify({ items: asArray(manager.config && manager.config.items) }),
    }).then(function (resp) {
      return resp.json().catch(function () { return {}; }).then(function (payload) {
        if (resp.status === 412 || payload.error === 'watchlist revision conflict') {
          manager.conflict = true;
          throw new Error('配置版本冲突；请重新载入线上配置后再合并修改');
        }
        if (!resp.ok) throw new Error(payload.error || '保存失败');
        manager.etag = normalizeString(resp.headers && resp.headers.get ? resp.headers.get('ETag') : '');
        manager.config = normalizeWatchlistManagerConfig(payload, {});
        manager.dirty = false;
        manager.conflict = false;
        setWatchlistManagerMessage('配置已保存，等待下次日报分析；当前日报快照保持不变', 'positive');
      });
    }).catch(function (error) {
      var message = normalizeString(error && error.message);
      setWatchlistManagerMessage(message.indexOf('配置版本冲突') !== -1 ? message : '保存失败：' + (message || '网络异常'), 'danger');
    }).finally(function () {
      manager.saving = false;
      renderAuxiliaryCenter();
    });
  }

  function bindWatchlistManager() {
    var owner = nodes.supportingStack || nodes.auxGrid;
    if (!owner) return;
    var root = owner.querySelector('.watchlist-manager');
    if (!root) return;
    var manager = watchlistManagerState();
    if (!manager.config) {
      manager.config = normalizeWatchlistManagerConfig(null, (state.data || {}).personal_watchlist || {});
    }
    root.addEventListener('toggle', function () {
      manager.open = root.open;
    });
    root.addEventListener('input', function () {
      syncWatchlistManagerForm(root);
      manager.dirty = true;
    });
    root.addEventListener('change', function (event) {
      var field = event.target && event.target.getAttribute('data-watch-field');
      if (field === 'enabled') {
        var row = event.target.closest('[data-watch-index]');
        toggleWatchlistManagerItem(Number(row.getAttribute('data-watch-index')), event.target.checked);
      } else {
        syncWatchlistManagerForm(root);
        manager.dirty = true;
      }
    });
    root.addEventListener('click', function (event) {
      var button = event.target && event.target.closest('[data-watch-action]');
      if (!button) return;
      var action = button.getAttribute('data-watch-action');
      var row = button.closest('[data-watch-index]');
      var index = row ? Number(row.getAttribute('data-watch-index')) : -1;
      syncWatchlistManagerForm(root);
      if (action === 'add') {
        var codeInput = root.querySelector('[data-watch-add-code]');
        var noteInput = root.querySelector('[data-watch-add-note]');
        if (addWatchlistManagerItem(codeInput && codeInput.value, noteInput && noteInput.value)) {
          manager.open = true;
          renderAuxiliaryCenter();
        }
      } else if (action === 'remove' && removeWatchlistManagerItem(index)) {
        manager.open = true;
        renderAuxiliaryCenter();
      } else if (action === 'up' && moveWatchlistManagerItem(index, -1)) {
        manager.open = true;
        renderAuxiliaryCenter();
      } else if (action === 'down' && moveWatchlistManagerItem(index, 1)) {
        manager.open = true;
        renderAuxiliaryCenter();
      } else if (action === 'save') {
        saveWatchlistManagerConfig(root);
      } else if (action === 'reload') {
        if (!confirmDiscardWatchlistChanges()) {
          setWatchlistManagerMessage('已保留未保存修改', 'warning');
          manager.open = true;
          renderAuxiliaryCenter();
          return;
        }
        manager.open = true;
        manager.loaded = false;
        loadWatchlistManagerConfig(true);
      }
    });
    loadWatchlistManagerConfig(false);
  }

  function renderPersonalWatchlist(data) {
    var personalWatchlist = (data || {}).personal_watchlist || {};
    var decisionBrief = (data || {}).decision_brief || {};
    var evidenceRegistry = asArray(decisionBrief.evidence_registry);
    var registryMap = buildEvidenceRegistryMap({ evidence_registry: evidenceRegistry });
    var rows = asArray(personalWatchlist.items).filter(function (item) {
      return item && item.enabled !== false;
    });
    var body = rows.length ? rows.map(function (item) {
      var rec = item || {};
      var current = rec.current || {};
      var factStatus = normalizeString(rec.fact_status || 'missing');
      var statusLabel = factStatus === 'fresh' ? '当日事实' : (factStatus === 'stale' ? '数据过期' : '事实缺失');
      var statusTone = factStatus === 'fresh' ? 'positive' : (factStatus === 'stale' ? 'warning' : 'neutral');
      var price = factStatus === 'fresh' ? safeNumber(current.current_price, null) : null;
      var change = factStatus === 'fresh' ? safeNumber(current.change_pct, null) : null;
      var evidenceDate = normalizeString(rec.evidence_date || '--');
      var changeStatus = normalizeString(rec.change_status) === 'new' ? '今日加入' : '持续跟踪';
      var actionStatus = normalizeString(rec.action_status) === 'awaiting_confirmation' ? '等待触发确认' : '事实不足';
      var priceLevels = factStatus === 'fresh' && rec.price_levels && typeof rec.price_levels === 'object' ? rec.price_levels : {};
      var candidateIntersections = factStatus === 'fresh' ? asArray(rec.candidate_intersections) : [];
      var poolHtml = candidateIntersections.length ? candidateIntersections.map(function (intersection) {
        return '<span class="watch-relation">' + escapeHtml(getWatchPoolLabel(intersection && intersection.pool)) + '</span>';
      }).join('') : '<span class="watch-relation is-muted">未进入候选池</span>';
      var directionRows = getWatchDirectionRows(decisionBrief, normalizeString(rec.code));
      return ''
        + '<article class="personal-watch-row is-' + escapeHtml(factStatus) + '">'
        + '  <div class="personal-watch-heading">'
        + '    <span><strong>' + escapeHtml(rec.name || '--') + '</strong><small>' + escapeHtml(rec.code || '') + '</small></span>'
        + '    <span class="status-badge is-' + escapeHtml(statusTone) + '">' + escapeHtml(statusLabel) + '</span>'
        + '  </div>'
        + '  <div class="watch-user-thesis"><span>个人观察逻辑</span><p>' + escapeHtml(rec.thesis || rec.note || '尚未填写个人观察逻辑') + '</p></div>'
        + '  <div class="watch-facts">'
        + '    <span>现价 <strong>' + escapeHtml(price === null ? '--' : formatNumber(price, 2)) + '</strong></span>'
        + '    <span>当日 <strong class="' + (change !== null && change >= 0 ? 'is-up' : (change !== null ? 'is-down' : '')) + '">' + escapeHtml(change === null ? '--' : formatPct(change, true)) + '</strong></span>'
        + '    <span>结构 <strong>' + escapeHtml(factStatus === 'fresh' ? normalizeString(current.trend_type || '待确认') : '不提供旧结论') + '</strong></span>'
        + '    <span>事实日期 <strong>' + escapeHtml(evidenceDate) + '</strong></span>'
        + '    <span>跟踪状态 <strong>' + escapeHtml(changeStatus) + '</strong></span>'
        + '    <span>动作状态 <strong>' + escapeHtml(actionStatus) + '</strong></span>'
        + '  </div>'
        + '  <div class="watch-price-levels">' + renderWatchPriceLevels(priceLevels) + '</div>'
        + '  <div class="watch-relations">' + poolHtml + '</div>'
        + '  <div class="watch-direction-list">' + renderWatchDirectionAnalysis(directionRows, registryMap) + '</div>'
        + '</article>';
    }).join('') : '<div class="decision-empty">重点观察池尚未配置</div>';
    var freshCount = safeNumber(personalWatchlist.fresh_count, 0);
    return renderDecisionCard({
      title: '我的重点观察',
      subtitle: '个人逻辑与当日事实分开保存；过期数据不输出动作',
      badge: { text: rows.length ? formatNumber(freshCount, 0) + '/' + rows.length + ' 当日' : '未配置', tone: freshCount === rows.length && rows.length ? 'positive' : 'warning' },
      className: 'personal-watchlist-card',
      bodyHtml: '<div class="personal-watch-list">' + body + '</div>' + renderWatchlistManager(personalWatchlist),
    });
  }

  function renderHoldingRiskSection(data) {
    var source = (data || {}).holding_risks;
    var rows = Array.isArray(source) ? source : asArray(source && source.items);
    var positionBook = (((data || {}).diagnostics || {}).position_book || {});
    var positionStatus = normalizeString(positionBook.status || 'missing');
    var positionMeta = {
      explicit_opt_in: { label: '当前未触发', tone: 'positive' },
      private: { label: '详情隐藏', tone: 'info' },
      unconfigured: { label: '未配置', tone: 'warning' },
      empty: { label: '已确认空仓', tone: 'neutral' },
      stale: { label: '快照过期', tone: 'warning' },
      unconfirmed: { label: '尚未确认', tone: 'warning' },
      error: { label: '配置异常', tone: 'danger' },
      missing: { label: '状态未知', tone: 'neutral' },
    }[positionStatus] || { label: positionStatus || '状态未知', tone: 'neutral' };
    if (!rows.length) {
      var positionMessage = normalizeString(
        positionBook.message || '持仓配置状态未记录；不显示卖出动作'
      );
      return renderDecisionCard({
        title: '持仓风险',
        subtitle: '明确区分未配置、空仓、详情隐藏与当前未触发',
        badge: { text: positionMeta.label, tone: positionMeta.tone },
        className: 'holding-risk-card',
        bodyHtml: '<div class="decision-empty">' + escapeHtml(positionMessage) + '</div>',
      });
    }
    var body = rows.map(function (item) {
      var rec = item || {};
      var sourceLabel = normalizeString(rec.position_source || '来源未标注');
      var positionAsOf = normalizeString(rec.position_as_of || '--');
      var confirmedAt = normalizeString(rec.confirmed_at || '--');
      return ''
        + '<div class="holding-risk-row">'
        + '  <div class="holding-risk-position">'
        + '    <strong>' + escapeHtml(rec.name || '--') + '</strong><small>' + escapeHtml(rec.code || '') + '</small>'
        + '  </div>'
        + '  <div class="holding-risk-evidence"><span>风险证据</span><p>' + escapeHtml(rec.reason || '持仓风险已触发') + '</p>'
        + '    <small>持仓来源 ' + escapeHtml(sourceLabel) + ' · 快照 ' + escapeHtml(positionAsOf) + ' · 确认 ' + escapeHtml(confirmedAt) + '</small>'
        + '  </div>'
        + '  <strong class="holding-risk-action">' + escapeHtml(rec.action || '核对持仓风险') + '</strong>'
        + '</div>';
    }).join('');
    return renderDecisionCard({
      title: '持仓风险',
      subtitle: '仅在显式允许公开股票标识后，展示确认持仓与风险信号的交集',
      badge: { text: rows.length + '项', tone: 'danger' },
      className: 'holding-risk-card',
      bodyHtml: body,
    });
  }

  function renderStrategySampleReturns(sample) {
    var returns = (sample || {}).returns || {};
    return ['t1', 't3', 't5'].map(function (key) {
      var value = safeNumber(returns[key], null);
      return key.toUpperCase().replace('T', 'T+') + ' ' + (value === null ? '--' : formatPct(value, true));
    }).join(' · ');
  }

  function resolveStrategyEntryMode(data, scorecard) {
    var rec = scorecard || {};
    var direct = normalizeString(rec.entry_mode);
    if (direct) return direct;
    var strategy = normalizeString(rec.strategy);
    var version = normalizeString(rec.version);
    var modes = [];
    asArray((data || {}).recommendation_ledger).forEach(function (entry) {
      asArray((entry || {}).strategy_contributions).forEach(function (contribution) {
        var row = contribution || {};
        if (normalizeString(row.strategy_name) !== strategy) return;
        var contributionVersion = normalizeString(row.strategy_version);
        if (version && contributionVersion && contributionVersion !== version) return;
        var mode = normalizeString(row.entry_mode);
        if (mode && modes.indexOf(mode) === -1) modes.push(mode);
      });
    });
    if (modes.length === 1) return modes[0];
    return modes.length > 1 ? 'mixed' : 'unknown';
  }

  function getStrategyEntryModeLabel(entryMode) {
    if (entryMode === 'delay1_open') return 'T+1开盘';
    if (entryMode === 'immediate_close') return '信号日收盘';
    if (entryMode === 'mixed') return '多种口径，禁止合并解读';
    return '未知';
  }

  function getScorecardStatusMeta(status) {
    var labels = {
      ready_for_manual_comparison: { label: '达到人工比较门槛', tone: 'positive' },
      collecting: { label: '样本积累中', tone: 'info' },
      waiting_for_maturity: { label: '等待到期', tone: 'warning' },
      data_unavailable: { label: '本期证据不足', tone: 'danger' },
      contract_missing: { label: '评测合同缺失', tone: 'danger' },
      no_formal_recommendations: { label: '本期无正式推荐', tone: 'neutral' },
      running: { label: '门控运行正常', tone: 'positive' },
      normal_empty: { label: '本期无门控记录', tone: 'neutral' },
      no_signals: { label: '正常空选', tone: 'neutral' },
      disabled: { label: '今日未启用', tone: 'neutral' },
    };
    return labels[normalizeString(status)] || { label: '状态未知', tone: 'neutral' };
  }

  function getScorecardBlockingReasonLabel(reason) {
    var labels = {
      no_signals: '没有产生策略信号',
      no_eligible_signals: '没有符合评测合同的信号',
      reference_close_missing: '参考收盘价缺失',
      market_data_unavailable: '目标交易日行情证据不足',
      strategy_input_stale_or_unverified: '策略输入日期过期或未核验，禁止评分',
      strategy_upstream_contract_mismatch: '策略上游池不符合 picks_pure 共同全集合同，禁止评分',
    };
    return labels[normalizeString(reason)]
      || userFacingEvidenceText(reason || '原因未登记', false);
  }

  function getScorecardSourceLabel(sourcePool) {
    var labels = {
      picks_fusion: '融合候选',
      picks_pure: '基础候选（共同上游全集）',
      h4_t3_pool: 'H4 T+3 独立策略池',
      next_day_boom: '次日爆发策略池',
      luojie_pool: '罗姐策略池',
      observation_watchlist: '观察门控池',
    };
    return labels[normalizeString(sourcePool)] || normalizeString(sourcePool || '来源池未知');
  }

  function getStrategyResearchTierLabel(value) {
    var labels = {
      prospective_ledger: '上线后前瞻账本',
      prospective_oot: '上线后前瞻样本',
      historical_replay: '历史回放样本',
      legacy_unclassified: '旧账本未分类',
      production_formal: '生产正式层',
      production_baseline: '生产基线层',
      production_research: '生产研究层',
    };
    return labels[normalizeString(value)] || normalizeString(value || '研究层级未知');
  }

  function getStrategyLatestRunLabel(item) {
    var rec = item || {};
    var status = normalizeString(rec.latest_run_status);
    var count = safeNumber(rec.latest_signal_count, null);
    var labels = {
      ran: '今日已运行' + (count === null ? '' : '，产生 ' + formatNumber(count, 0) + ' 个信号'),
      verified_empty: '今日运行正常，0 个信号',
      disabled: '今日条件未触发，策略未启用',
      unavailable: '今日运行或生产证明不可用',
      unrecorded: '当日运行状态未记录',
    };
    return labels[status] || '当日运行状态未记录';
  }

  function getStrategyDisplayName(item) {
    var rec = item || {};
    var names = {
      daily_fusion: '日线融合策略',
      daily_pure: '日线基础候选基线',
      next_day_boom: '次日爆发策略',
      luojie_pool: '罗姐主题策略',
      observation_gate: '观察池门控',
      h4_t3: 'H4 T+3 策略',
    };
    return names[normalizeString(rec.strategy)]
      || normalizeString(rec.name || rec.strategy || '未命名策略');
  }

  function renderStrategyMetric(label, value, denominator, options) {
    var number = safeNumber(value, null);
    var n = safeNumber(denominator, null);
    var opts = options || {};
    var formatted = number === null
      ? '--'
      : (opts.rate ? formatPct(number) : formatPct(number, true));
    var tone = opts.rate || number === null ? '' : (number >= 0 ? ' is-up' : ' is-down');
    return ''
      + '<span class="strategy-metric">'
      + '  <small>' + escapeHtml(label) + '</small>'
      + '  <strong class="' + tone.trim() + '">' + escapeHtml(formatted) + '</strong>'
      + '  <em>n=' + escapeHtml(formatNumber(n, 0)) + '</em>'
      + '</span>';
  }

  function renderStrategyPlainMetric(label, value, denominator) {
    var text = normalizeString(value) || '--';
    var n = safeNumber(denominator, null);
    return ''
      + '<span class="strategy-metric">'
      + '  <small>' + escapeHtml(label) + '</small>'
      + '  <strong>' + escapeHtml(text) + '</strong>'
      + (n === null ? '' : '  <em>n=' + escapeHtml(formatNumber(n, 0)) + '</em>')
      + '</span>';
  }

  function renderStrategyHorizon(horizonKey, metrics, maturity, publishable, blockers, evaluationStatus, progress, readiness) {
    var horizon = horizonKey.toUpperCase().replace('T', 'T+');
    var rec = metrics || {};
    var state = maturity || {};
    var gate = progress && typeof progress === 'object' ? progress : {};
    var mature = safeNumber(state.mature, null);
    var waiting = safeNumber(state.waiting, null);
    var unavailable = safeNumber(state.unavailable, null);
    var evaluation = normalizeString(evaluationStatus);
    var gateStatus = normalizeString(gate.status || readiness);
    var statusHtml = '';
    var metricsHtml = '';
    if (['no_signals', 'no_formal_recommendations', 'normal_empty'].indexOf(evaluation) !== -1) {
      statusHtml = '<div class="strategy-horizon-state"><strong>本期无信号</strong><small>正常空选，不计算收益</small></div>';
    } else if (evaluation === 'disabled') {
      statusHtml = '<div class="strategy-horizon-state"><strong>今日未启用</strong><small>策略未运行，不计算收益</small></div>';
    } else if (!publishable) {
      statusHtml = '<div class="strategy-horizon-state is-danger"><strong>本期证据不足</strong><small>'
        + escapeHtml(asArray(blockers).map(getScorecardBlockingReasonLabel).join('；') || '评测条件不成立')
        + '</small></div>';
    } else if (mature === null || waiting === null || unavailable === null) {
      statusHtml = '<div class="strategy-horizon-state is-danger"><strong>合同字段缺失</strong><small>成熟、等待或不可用分母未完整记录</small></div>';
    } else if (mature === 0 && waiting > 0) {
      statusHtml = '<div class="strategy-horizon-state is-waiting"><strong>等待到期</strong><small>'
        + escapeHtml(formatNumber(waiting, 0)) + ' 个回合尚未走完 ' + escapeHtml(horizon)
        + '</small></div>';
    } else if (mature === 0) {
      statusHtml = '<div class="strategy-horizon-state"><strong>证据不足</strong><small>'
        + (unavailable ? escapeHtml(formatNumber(unavailable, 0)) + ' 个回合缺少目标日行情' : '暂无成熟回合')
        + '</small></div>';
    } else if (gateStatus !== 'ready_for_manual_comparison') {
      var matureProgress = safeNumber(gate.mature_samples, null);
      var requiredMature = safeNumber(gate.required_mature_samples, null);
      var activeDates = safeNumber(gate.active_dates, null);
      var requiredDates = safeNumber(gate.required_active_dates, null);
      var activeMonths = safeNumber(gate.active_months, null);
      var requiredMonths = safeNumber(gate.required_calendar_months, null);
      if ([matureProgress, requiredMature, activeDates, requiredDates, activeMonths, requiredMonths].some(function (value) { return value === null; })) {
        statusHtml = '<div class="strategy-horizon-state is-danger"><strong>样本门合同缺失</strong><small>成熟样本、活跃日或自然月进度未完整记录</small></div>';
      } else {
        statusHtml = '<div class="strategy-horizon-state is-waiting strategy-comparison-progress"><strong>样本采集中</strong><small>'
          + escapeHtml(formatNumber(matureProgress, 0) + '/' + formatNumber(requiredMature, 0) + ' 成熟样本')
          + ' · ' + escapeHtml(formatNumber(activeDates, 0) + '/' + formatNumber(requiredDates, 0) + ' 活跃日')
          + ' · ' + escapeHtml(formatNumber(activeMonths, 0) + '/' + formatNumber(requiredMonths, 0) + ' 自然月')
          + '</small></div>';
      }
    } else {
      metricsHtml = ''
        + '<div class="strategy-metric-grid">'
        + renderStrategyPlainMetric('样本数', formatNumber(rec.n, 0))
        + renderStrategyPlainMetric('样本区间', (normalizeString(rec.date_start) && normalizeString(rec.date_end)) ? normalizeString(rec.date_start) + ' 至 ' + normalizeString(rec.date_end) : '--')
        + renderStrategyMetric('中位收益', rec.median, rec.n)
        + renderStrategyMetric('平均收益', rec.mean, rec.n)
        + renderStrategyMetric('基准超额', rec.excess_mean, rec.excess_n)
        + renderStrategyMetric('最大回撤', rec.max_drawdown, rec.mae_n)
        + renderStrategyMetric('MFE', rec.mean_mfe, rec.mfe_n)
        + renderStrategyMetric('MAE', rec.mean_mae, rec.mae_n)
        + '</div>';
      statusHtml = '<div class="strategy-horizon-state is-ready"><strong>'
        + escapeHtml(formatNumber(mature, 0)) + ' 个成熟回合</strong><small>'
        + (waiting ? escapeHtml(formatNumber(waiting, 0)) + ' 个等待到期' : '无等待回合')
        + (unavailable ? ' · ' + escapeHtml(formatNumber(unavailable, 0)) + ' 个缺数' : '')
        + '</small></div>';
    }
    return ''
      + '<section class="strategy-horizon">'
      + '  <div class="strategy-horizon-title"><strong>' + escapeHtml(horizon) + ' 收盘</strong><small>信号日收盘入场后的第 ' + escapeHtml(horizon.replace('T+', '')) + ' 个交易日</small></div>'
      + statusHtml
      + metricsHtml
      + '</section>';
  }

  function getStrategyEvidenceTierLabel(value) {
    var labels = {
      prospective_ledger: '账本显式身份',
      legacy_inferred: '旧账本兼容推断',
      mixed_identity: '显式身份与兼容推断混合',
      run_manifest: '当日运行合同',
    };
    return labels[normalizeString(value)] || '身份证据未声明';
  }

  function getStrategyReasonLabel(role) {
    if (role === 'formal') return '正式推荐原因';
    if (role === 'baseline') return '上游候选原因';
    if (role === 'research') return '研究信号原因';
    return '信号原因';
  }

  function renderStrategyPublicationMeta(rec, gateOutcomes, publicationOutcomes) {
    var role = normalizeString(rec.evaluation_role);
    if (role === 'formal') {
      return '页面正式动作 推荐 / 仅观察：'
        + escapeHtml(formatNumber(publicationOutcomes.recommendation, 0)) + ' / '
        + escapeHtml(formatNumber(publicationOutcomes.watch, 0));
    }
    if (role === 'baseline') {
      return '页面身份：共同上游候选，不计作正式推荐；规则命中 推荐 / 观察：'
        + escapeHtml(formatNumber(gateOutcomes.recommend, 0)) + ' / '
        + escapeHtml(formatNumber(gateOutcomes.observe, 0));
    }
    if (role === 'research') {
      return '页面身份：研究信号，不计作正式推荐；研究动作 命中 / 仅观察：'
        + escapeHtml(formatNumber(publicationOutcomes.recommendation, 0)) + ' / '
        + escapeHtml(formatNumber(publicationOutcomes.watch, 0));
    }
    return '页面动作不适用';
  }

  function renderStrategySamples(samples, role) {
    var rows = asArray(samples).slice(0, 3);
    if (!rows.length) return '<li><span>暂无可展示的已到期样本</span><strong>--</strong></li>';
    var reasonLabel = getStrategyReasonLabel(role);
    return rows.map(function (sample) {
      return ''
        + '<li class="strategy-sample-row">'
        + '  <div><span>' + escapeHtml(sample.name || sample.code || '--') + '</span><small>'
        + escapeHtml((sample.rec_date || '--') + ' 信号 · ' + (sample.entry_date || '--') + ' 信号日收盘入场') + '</small></div>'
        + '  <div><strong>' + escapeHtml(sample.outcome_label || renderStrategySampleReturns(sample)) + '</strong><small>' + escapeHtml(renderStrategySampleReturns(sample)) + '</small><small>' + escapeHtml(reasonLabel) + '：' + escapeHtml(sample.reason_summary || '理由快照未知') + '</small></div>'
        + '  <code>' + escapeHtml(sample.recommendation_id || '--') + '</code>'
        + '</li>';
    }).join('');
  }

  function getStrategyLedgerWindowLabel(item) {
    var rec = item || {};
    var count = safeNumber(rec.ledger_active_dates, 0);
    var start = normalizeString(rec.ledger_date_start);
    var end = normalizeString(rec.ledger_date_end);
    if (!count || !start || !end) return '尚未形成账本累计窗口';
    return start + ' 至 ' + end + ' · ' + formatNumber(count, 0) + ' 个交易日';
  }

  function renderScorecardV2Card(data, item) {
    var rec = item || {};
    var status = getScorecardStatusMeta(rec.evaluation_status);
    var entryMode = resolveStrategyEntryMode(data, rec);
    var maturity = rec.maturity_by_horizon || {};
    var metrics = rec.metrics_by_horizon || {};
    var gateOutcomes = rec.gate_outcomes || {};
    var publicationOutcomes = rec.publication_outcomes || {};
    var blockers = asArray(rec.metrics_blocking_reasons);
    var signalCount = safeNumber(rec.signal_count, null);
    var eligibleCount = safeNumber(rec.eligible_signal_count, null);
    var excludedCount = safeNumber(rec.excluded_signal_count, 0);
    var contractCount = safeNumber(
      rec.evaluation_contract_signal_count,
      Math.max(0, (eligibleCount || 0) + excludedCount)
    );
    var nonEvaluationCount = safeNumber(
      rec.non_evaluation_signal_count,
      Math.max(0, (signalCount || 0) - contractCount)
    );
    var sampleExclusions = asArray(rec.sample_exclusions);
    var episodeCount = safeNumber(rec.episode_count, null);
    var intended = [1, 3, 5].indexOf(Number(rec.intended_horizon)) !== -1
      ? '策略声明 T+' + Number(rec.intended_horizon)
      : '未声明单一主周期';
    var primaryKey = [1, 3, 5].indexOf(Number(rec.intended_horizon)) !== -1
      ? 't' + Number(rec.intended_horizon)
      : '';
    var primaryReady = primaryKey
      && normalizeString((rec.horizon_readiness || {})[primaryKey]) === 'ready_for_manual_comparison';
    return ''
      + '<details class="strategy-scorecard">'
      + '  <summary>'
      + '    <span><strong>' + escapeHtml(getStrategyDisplayName(rec)) + '</strong><small>' + escapeHtml((rec.version || '版本未知') + ' · ' + getScorecardSourceLabel(rec.source_pool)) + '</small></span>'
      + '    <span><strong>' + escapeHtml(formatNumber(episodeCount, 0)) + '</strong><small>收益评测去重回合</small></span>'
      + '    <span class="status-badge is-' + escapeHtml(status.tone) + '">' + escapeHtml(status.label) + '</span>'
      + '  </summary>'
      + '  <div class="strategy-attribution-meta">'
      + '    <span>入场口径：' + escapeHtml(getStrategyEntryModeLabel(entryMode)) + '</span>'
      + '    <span>' + escapeHtml(intended) + '；页面逐周期独立展示</span>'
      + '    <span>研究层级：' + escapeHtml(getStrategyResearchTierLabel(rec.research_tier)) + '</span>'
      + '    <span class="strategy-universe-line">今日运行：' + escapeHtml(getStrategyLatestRunLabel(rec)) + (rec.latest_run_reason ? '；' + escapeHtml(rec.latest_run_reason) : '') + '</span>'
      + '    <span class="strategy-universe-line">账本累计：' + escapeHtml(getStrategyLedgerWindowLabel(rec))
      + '；累计信号 ' + escapeHtml(formatNumber(signalCount, 0))
      + '；规则判定 推荐 / 观察 / 拒绝 ' + escapeHtml(formatNumber(gateOutcomes.recommend, 0)) + ' / ' + escapeHtml(formatNumber(gateOutcomes.observe, 0)) + ' / ' + escapeHtml(formatNumber(gateOutcomes.reject, 0))
      + '；' + renderStrategyPublicationMeta(rec, gateOutcomes, publicationOutcomes) + '</span>'
      + '    <span class="strategy-universe-line">收益评测：可评 ' + escapeHtml(formatNumber(eligibleCount, 0))
      + ' / 合同样本 ' + escapeHtml(formatNumber(contractCount, 0))
      + ' / 事故排除 ' + escapeHtml(formatNumber(excludedCount, 0))
      + ' / 非收益样本 ' + escapeHtml(formatNumber(nonEvaluationCount, 0))
      + ' / 去重回合 ' + escapeHtml(formatNumber(episodeCount, 0))
      + '；覆盖 ' + escapeHtml(formatNumber(rec.active_dates, 0)) + ' 个可评交易日 / ' + escapeHtml(formatNumber(rec.active_months, 0)) + ' 个自然月</span>'
      + (sampleExclusions.length
        ? '    <span class="strategy-input-exclusions">排除依据：' + sampleExclusions.map(function (incident) {
          return escapeHtml(incident.incident_id || '未登记事故')
            + '（' + escapeHtml(getScorecardBlockingReasonLabel(incident.reason))
            + '，' + escapeHtml(formatNumber(incident.count, 0)) + ' 个信号）';
        }).join('；') + '</span>'
        : '')
      + '    <span>身份证据：' + escapeHtml(getStrategyEvidenceTierLabel(rec.evidence_tier)) + '</span>'
      + '  </div>'
      + '  <div class="strategy-returns">'
      + renderStrategyHorizon('t1', metrics.t1, maturity.t1, rec.metrics_publishable !== false, blockers, rec.evaluation_status, (rec.comparison_progress_by_horizon || {}).t1, (rec.horizon_readiness || {}).t1)
      + renderStrategyHorizon('t3', metrics.t3, maturity.t3, rec.metrics_publishable !== false, blockers, rec.evaluation_status, (rec.comparison_progress_by_horizon || {}).t3, (rec.horizon_readiness || {}).t3)
      + renderStrategyHorizon('t5', metrics.t5, maturity.t5, rec.metrics_publishable !== false, blockers, rec.evaluation_status, (rec.comparison_progress_by_horizon || {}).t5, (rec.horizon_readiness || {}).t5)
      + '  </div>'
      + (primaryReady ? '  <ul class="strategy-samples">' + renderStrategySamples(rec.representative_samples, rec.evaluation_role) + '</ul>' : '')
      + '</details>';
  }

  function renderGateScorecard(item) {
    var rec = item || {};
    var status = getScorecardStatusMeta(rec.evaluation_status);
    var gateOutcomes = rec.gate_outcomes || {};
    var publicationOutcomes = rec.publication_outcomes || {};
    return ''
      + '<article class="strategy-gate-card">'
      + '  <div><strong>' + escapeHtml(getStrategyDisplayName(rec)) + '</strong><small>' + escapeHtml((rec.version || '版本未知') + ' · ' + getScorecardSourceLabel(rec.source_pool)) + '</small></div>'
      + '  <span class="status-badge is-' + escapeHtml(status.tone) + '">' + escapeHtml(status.label) + '</span>'
      + '  <p>当日运行：' + escapeHtml(getStrategyLatestRunLabel(rec)) + (rec.latest_run_reason ? '；' + escapeHtml(rec.latest_run_reason) : '') + '</p>'
      + '  <p>账本累计（' + escapeHtml(getStrategyLedgerWindowLabel(rec)) + '）规则判定 推荐 / 观察 / 拒绝：' + escapeHtml(formatNumber(gateOutcomes.recommend, 0)) + ' / ' + escapeHtml(formatNumber(gateOutcomes.observe, 0)) + ' / ' + escapeHtml(formatNumber(gateOutcomes.reject, 0)) + '</p>'
      + '  <p>账本累计页面动作 仅观察：' + escapeHtml(formatNumber(publicationOutcomes.watch, 0)) + '</p>'
      + '  <small class="strategy-gate-note">该门控不计算收益，只回答运行与分流是否正常。</small>'
      + '</article>';
  }

  function renderScorecardSection(data, title, description, rows, kind) {
    var items = asArray(rows);
    var body = items.length
      ? items.map(function (item) {
        return kind === 'gate' ? renderGateScorecard(item) : renderScorecardV2Card(data, item);
      }).join('')
      : '<div class="decision-empty">本区暂无已登记分组；这是空分组，不是 0% 收益。</div>';
    return ''
      + '<section class="strategy-scorecard-section is-' + escapeHtml(kind || 'returns') + '">'
      + '  <div class="strategy-scorecard-section-title"><span><strong>' + escapeHtml(title) + '</strong><small>' + escapeHtml(description) + '</small></span><em>' + escapeHtml(formatNumber(items.length, 0)) + ' 个评测分组</em></div>'
      + body
      + '</section>';
  }

  function renderLegacyScorecards(data, rows) {
    var items = asArray(rows);
    return ''
      + '<div class="strategy-scorecard-legacy-warning"><strong>历史旧口径，不作为成绩</strong><small>此快照没有正式 / 基线 / 研究 / 门控分区，也没有逐周期分母。只保留策略身份供追溯。</small></div>'
      + (items.length ? items.map(function (item) {
        var rec = item || {};
        return '<div class="strategy-scorecard-legacy-row"><strong>'
          + escapeHtml(getStrategyDisplayName(rec))
          + '</strong><small>' + escapeHtml((rec.version || '版本未知') + ' · 入场口径：' + getStrategyEntryModeLabel(resolveStrategyEntryMode(data, rec))) + '</small></div>';
      }).join('') : '<div class="decision-empty">策略归因账本尚无记录。</div>');
  }

  function renderStrategyScorecards(data) {
    var scorecards = (data || {}).strategy_scorecards || {};
    var isV2 = !Array.isArray(scorecards) && Number(scorecards.schema_version) === 2;
    var rows = isV2
      ? asArray(scorecards.formal).concat(asArray(scorecards.baselines), asArray(scorecards.research), asArray(scorecards.gates))
      : (Array.isArray(scorecards) ? scorecards : asArray(scorecards.items || scorecards.scorecards));
    var classificationFailures = isV2 ? asArray(scorecards.classification_failures) : [];
    var classificationWarning = classificationFailures.length
      ? '<div class="strategy-scorecard-contract-warning"><strong>'
        + escapeHtml(formatNumber(classificationFailures.length, 0))
        + ' 条账本身份无法安全分类</strong><small>这些记录已停止计入任何收益；请在数据诊断中修复策略、版本与来源池映射。</small></div>'
      : '';
    var body = isV2
      ? ''
        + renderScorecardSection(data, '正式推荐收益', '只统计真正对用户生效的正式推荐；基础候选和研究池不混入。', scorecards.formal, 'formal')
        + renderScorecardSection(data, '基础候选基线', 'picks_pure 是各策略共同上游全集，用来回答筛选是否带来增益。', scorecards.baselines, 'baseline')
        + renderScorecardSection(data, '研究策略回看', '独立策略各用自己的筛选结果；研究成绩不影响正式推荐。', scorecards.research, 'research')
        + renderScorecardSection(data, '门控运行诊断', '只检查观察与拒绝分流，不计算收益。', scorecards.gates, 'gate')
      : renderLegacyScorecards(data, rows);
    var reviewDiagnostics = (((data || {}).diagnostics || {}).strategy_review || {});
    var benchmarkReady = normalizeString(reviewDiagnostics.benchmark_status) === 'ok';
    var benchmarkNote = benchmarkReady
      ? '<div class="strategy-benchmark-status is-ok">沪深300基准已对齐，超额收益可用。</div>'
      : '<div class="strategy-benchmark-status is-warning">沪深300基准历史暂不可用，超额收益显示 --，绝不以 0 代替。</div>';
    return renderDecisionCard({
      title: '策略收益回看（记分牌）',
      subtitle: '先按完整比较身份分组，再逐周期核算；成熟前只展示采集进度，达到门槛后展示可解释统计',
      badge: isV2
        ? { text: rows.length ? rows.length + '个评测分组' : '待积累', tone: rows.length ? 'info' : 'neutral' }
        : { text: rows.length ? '旧口径，仅追溯' : '旧口径，无记录', tone: 'neutral' },
      className: 'strategy-scorecards-card',
      bodyHtml: ''
        + '<div class="strategy-scorecard-guide"><strong>读数说明</strong><span><b>0.00%</b> 是真实零收益</span><span><b>等待到期</b> 是目标交易日未到</span><span><b>证据不足</b> 是评测条件不完整</span><span><b>正常空选</b> 是策略当天没有信号</span><span><b>研究回看</b> 不影响正式推荐</span></div>'
        + benchmarkNote + classificationWarning + body,
    });
  }

  function renderShadowEvaluations(data) {
    var rawShadow = (data || {}).shadow_evaluations;
    var hasContract = !!rawShadow && typeof rawShadow === 'object' && !Array.isArray(rawShadow);
    var shadow = hasContract ? rawShadow : {};
    var mode = normalizeString(shadow.mode);
    var status = normalizeString(shadow.status);
    var guard = shadow.production_guard || {};
    var productionReference = shadow.production_reference || {};
    var experiments = asArray(shadow.experiments);
    var scorecards = asArray(shadow.scorecards);
    var todayEntries = asArray(shadow.today_entries);
    var pending = shadow.pending || {};
    var startedAt = normalizeString(shadow.started_at);
    var collectionHealth = shadow.collection_health || {};
    var outcomeMaturity = shadow.outcome_maturity || {};
    var comparisonReadiness = shadow.comparison_readiness || {};
    var poolLabels = {
      picks_pure: 'picks_pure → 原始缠论结构候选 / 共同上游全集',
      picks_fusion: 'picks_fusion → 融合候选全集',
      h4_t3_pool: 'h4_t3_pool → H4 T+3 策略池',
      next_day_boom: 'next_day_boom → 次日爆发策略池',
      luojie_pool: 'luojie_pool → 罗姐策略池',
    };
    var hardGateLabels = {
      mature_samples_below_100: '成熟样本少于 100 个',
      active_dates_below_20: '活跃交易日少于 20 天',
      active_months_below_2: '覆盖月份少于 2 个月',
      shadow_mode_never_auto_promotes: '影子模式不会自动晋级正式主推',
      candidate_reference_unproven: '信号日收盘价尚未证明',
      canonical_kline_missing: '权威行情尚未到位',
      canonical_adjustment_mismatch: '行情复权口径不一致',
      canonical_kline_invalid: '权威行情结构无效',
      canonical_report_date_missing: '行情缺少信号日收盘',
      canonical_report_bar_not_final: '信号日 K 线尚未收盘确认',
      canonical_report_volume_invalid: '信号日成交量无效',
      canonical_reference_close_mismatch: '候选收盘价与权威行情不一致',
    };
    var comparisonStatusLabels = {
      collecting: '样本积累中',
      ready_for_manual_comparison: '可进入人工比较',
      ready_for_manual_review: '可进入人工验收',
      maturing: '样本成长中',
      insufficient: '样本不足',
      unavailable: '暂不可比较',
    };
    var researchTierLabels = {
      oot_shadow: '上线后样本 / 前瞻影子',
      historical_shadow: '历史样本 / 回放影子',
    };

    function shadowIdentityPart(value) {
      return typeof value + ':' + normalizeString(value);
    }

    function shadowIdentity(item) {
      var row = item || {};
      return [
        shadowIdentityPart(row.experiment_id),
        shadowIdentityPart(row.version),
        shadowIdentityPart(row.upstream_pool),
        shadowIdentityPart(row.source_pool),
        shadowIdentityPart(row.intended_horizon),
        shadowIdentityPart(row.entry_mode),
      ].join('|');
    }

    function shadowRequiredString(value) {
      return typeof value === 'string' && value.trim().length > 0;
    }

    function shadowPoolLabel(value) {
      var key = normalizeString(value);
      return poolLabels[key] || (key ? key + ' → 未登记池定义' : '未声明');
    }

    function shadowGateLabel(value) {
      var key = normalizeString(value);
      return hardGateLabels[key] || key || '原因未记录';
    }

    function shadowComparisonLabel(value) {
      var key = normalizeString(value);
      return comparisonStatusLabels[key] || key || '结论状态未声明';
    }

    function shadowResearchTierLabel(value) {
      var key = normalizeString(value);
      return researchTierLabels[key] || key || '研究层级未声明';
    }

    function shadowShortSha(value) {
      var sha = normalizeString(value);
      return sha ? sha.substring(0, 10) : '--';
    }

    function renderShadowMetric(label, value, tone) {
      return ''
        + '<div class="shadow-metric' + (tone ? ' ' + escapeHtml(tone) : '') + '">'
        + '  <small>' + escapeHtml(label) + '</small>'
        + '  <strong>' + escapeHtml(value) + '</strong>'
        + '</div>';
    }

    function renderShadowMaturity(maturity) {
      var value = maturity && typeof maturity === 'object' ? maturity : {};
      var horizons = [
        { key: 't1', label: 'T+1 已到期' },
        { key: 't3', label: 'T+3 已到期' },
        { key: 't5', label: 'T+5 已到期' },
      ];
      return '<div class="shadow-metric-grid shadow-maturity-grid">'
        + horizons.map(function (horizon) {
          var counts = value[horizon.key] || {};
          var mature = safeNumber(counts.mature, null);
          var waiting = safeNumber(counts.right_censored, null);
          var unavailableCount = safeNumber(counts.unavailable, null);
          if (mature === null || waiting === null || unavailableCount === null) {
            return ''
              + '<div class="shadow-metric is-warning">'
              + '  <small>' + escapeHtml(horizon.label) + '</small>'
              + '  <strong>合同字段缺失</strong>'
              + '  <small>成熟、等待或不可用分母未完整记录</small>'
              + '</div>';
          }
          return ''
            + '<div class="shadow-metric">'
            + '  <small>' + escapeHtml(horizon.label) + '</small>'
            + '  <strong>' + escapeHtml(formatNumber(mature, 0)) + '</strong>'
            + '  <small>等待 ' + escapeHtml(formatNumber(waiting, 0))
            + ' · 不可用 ' + escapeHtml(formatNumber(unavailableCount, 0))
            + '</small>'
            + '</div>';
        }).join('')
        + '</div>';
    }

    function renderShadowSamples(metrics) {
      var samples = asArray((metrics || {}).representative_samples);
      if (!samples.length) {
        return '<div class="shadow-empty-line">等待首个收盘样本</div>';
      }
      return '<div class="shadow-sample-list">' + samples.map(function (sample) {
        var row = sample || {};
        return ''
          + '<div class="shadow-sample-row">'
          + '  <div><strong>' + escapeHtml(row.name || row.code || '--') + '</strong><small>' + escapeHtml(row.code || '--') + '</small></div>'
          + '  <div><strong>' + escapeHtml(formatPct(row.close_return, true)) + '</strong><small>' + escapeHtml((row.rec_date || '--') + ' → ' + (row.target_date || '--')) + '</small></div>'
          + '  <div><strong>' + escapeHtml(formatPct(row.mfe, true) + ' / ' + formatPct(row.mae, true)) + '</strong><small>MFE / MAE</small></div>'
          + '  <code>' + escapeHtml(row.shadow_evaluation_id || '--') + '</code>'
          + '</div>';
      }).join('') + '</div>';
    }

    function renderShadowCandidates(experiment) {
      var candidates = asArray((((experiment || {}).today || {}).candidates));
      if (!candidates.length) {
        return '<div class="shadow-empty-line">今日没有进入该实验的影子候选；等待后续收盘样本。</div>';
      }
      return '<div class="shadow-candidate-list">' + candidates.map(function (candidate) {
        var row = candidate || {};
        var eligible = row.evaluation_eligible === true;
        var reasons = asArray(row.evaluation_ineligible_reasons).map(shadowGateLabel);
        var evidence = reasons.length
          ? reasons.join('；')
          : (eligible ? '收盘证据已校验' : '等待收盘证据校验');
        return ''
          + '<div class="shadow-candidate-row">'
          + '  <div><strong>' + escapeHtml(row.name || row.code || '--') + '</strong><small>' + escapeHtml(row.code || '--') + '</small></div>'
          + '  <div><strong>' + escapeHtml(row.reference_close == null ? '--' : formatNumber(row.reference_close, 2)) + '</strong><small>信号日收盘</small></div>'
          + '  <div><strong>影子候选 · 不是推荐</strong><small>' + escapeHtml(evidence) + '</small></div>'
          + '</div>';
      }).join('') + '</div>';
    }

    var scorecardByIdentity = {};
    scorecards.forEach(function (item) {
      scorecardByIdentity[shadowIdentity(item)] = item;
    });
    var schemaValid = hasContract && shadow.schema_version === 1;
    var isolated = schemaValid && shadow.affects_production === false;
    var beforeSha = normalizeString(guard.before_sha256);
    var afterSha = normalizeString(guard.after_sha256);
    var digestPattern = /^[0-9a-f]{64}$/i;
    var guardValid = isolated
      && shadow.mode === 'shadow'
      && (shadow.status === 'collecting' || shadow.status === 'partial')
      && guard.unchanged === true
      && digestPattern.test(beforeSha)
      && digestPattern.test(afterSha)
      && beforeSha === afterSha;
    var collectionStatus = normalizeString(collectionHealth.status);
    var disabled = isolated && (mode === 'off' || status === 'disabled');
    var collectionFailed = isolated && (
      collectionStatus === 'collection_failed'
      || shadow.data_gap === true
      || (status === 'unavailable' && shadow.data_gap !== false)
    );
    function shadowCountRecorded(value) {
      var number = safeNumber(value, null);
      return number !== null && number >= 0;
    }
    var collectionContractValid = (
      collectionStatus === 'ok' || collectionStatus === 'partial'
    )
      && shadowCountRecorded(collectionHealth.candidate_count)
      && shadowCountRecorded(collectionHealth.eligible_count)
      && shadowCountRecorded(collectionHealth.staged_count);
    var maturityContractValid = ['t1', 't3', 't5'].every(function (key) {
      var counts = outcomeMaturity[key];
      return !!counts
        && shadowCountRecorded(counts.mature)
        && shadowCountRecorded(counts.right_censored)
        && shadowCountRecorded(counts.unavailable);
    });
    var pendingContractValid = shadowCountRecorded(pending.entries);
    var experimentProgressContractValid = experiments.every(function (item) {
      var rec = item || {};
      var metrics = scorecardByIdentity[shadowIdentity(rec)] || rec;
      return shadowCountRecorded(metrics.sample_size)
        && shadowCountRecorded(metrics.active_dates)
        && shadowCountRecorded(metrics.active_months)
        && shadowCountRecorded(metrics.excursion_sample_size);
    });
    var nestedContractValid = collectionContractValid
      && maturityContractValid
      && pendingContractValid
      && experimentProgressContractValid;
    var collecting = isolated && guardValid && nestedContractValid;
    var unavailable = !isolated || (!disabled && !collecting);
    var statusText = collectionFailed
      ? '影子采集失败'
      : (collecting ? '影子评测中' : (disabled ? '影子模式已关闭' : '影子评测暂不可用'));
    var statusTone = collectionFailed
      ? 'warning'
      : (collecting ? 'info' : (disabled ? 'neutral' : 'warning'));
    var body = '';

    if (disabled) {
      body = '<div class="shadow-state"><strong>影子模式已关闭</strong><span>未采集新的影子样本；正式主推不受影响。</span></div>';
    } else if (collectionFailed) {
      var failureStage = normalizeString(collectionHealth.failure_stage || shadow.failure_stage) || 'unknown';
      var errorCode = normalizeString(collectionHealth.error_code || shadow.error_code) || 'unknown';
      var collectionError = normalizeString(shadow.error) || '影子采集链路未完成';
      body = ''
        + '<div class="shadow-state is-warning"><strong>影子采集失败</strong>'
        + '<span>本日形成数据缺口，不纳入 OOT 样本；正式主推不受影响。失败阶段：'
        + escapeHtml(failureStage) + '；错误码：' + escapeHtml(errorCode)
        + '；' + escapeHtml(collectionError) + '</span></div>';
    } else if (unavailable) {
      var unavailableReason = normalizeString(shadow.error);
      if (!schemaValid && hasContract) {
        unavailableReason = '影子合同 schema_version 不受支持';
      } else if (!isolated && hasContract) {
        unavailableReason = '隔离声明缺失或不合法（affects_production 必须显式为 false）';
      } else if (!nestedContractValid) {
        unavailableReason = '影子合同字段缺失：采集、批次、样本进度或 T+1 / T+3 / T+5 成熟度分母未完整记录';
      } else if (!unavailableReason && !guardValid) {
        unavailableReason = '影子合同或正式输出摘要未通过严格校验（'
          + shadowShortSha(beforeSha) + ' → '
          + shadowShortSha(afterSha) + '）';
      }
      body = ''
        + '<div class="shadow-state is-warning"><strong>影子评测暂不可用</strong>'
        + '<span>' + escapeHtml(unavailableReason || '影子合同未生成') + '；研究结论已隐藏。</span></div>';
    } else {
      var guardOk = guard.unchanged === true;
      var guardLabel = guardOk ? '正式输出保护通过' : '正式输出保护未通过';
      var formalCount = safeNumber(productionReference.today_count, null);
      var workspace = (data || {}).workspace || {};
      var workspaceViews = workspace.views || {};
      var mainView = workspaceViews.main;
      var pageMainCount = Array.isArray(mainView)
        ? mainView.length
        : safeNumber((workspace.counts || {}).main, null);
      var pendingCount = safeNumber(pending.entries, null);
      var candidateCount = safeNumber(collectionHealth.candidate_count, null);
      var eligibleCount = safeNumber(collectionHealth.eligible_count, null);
      var stagedCount = safeNumber(collectionHealth.staged_count, null);
      var collectionLabel = collectionStatus === 'partial'
        ? '采集部分成功，今日 ' + formatNumber(candidateCount, 0) + ' 只'
        : (collectionStatus === 'ok'
          ? '采集成功，今日 ' + formatNumber(candidateCount, 0) + ' 只'
          : '旧版合同：采集状态未细分');
      var collectionDetail = collectionStatus === 'ok' || collectionStatus === 'partial'
        ? '有效 ' + formatNumber(eligibleCount, 0)
          + ' · 暂存 ' + formatNumber(stagedCount, 0)
        : '以正式摘要保护结果兼容展示';
      body += ''
        + '<div class="shadow-guard-rail' + (guardOk ? ' is-ok' : ' is-warning') + '">'
        + '  <div><strong>' + escapeHtml(guardLabel) + '</strong><small>不影响正式主推</small></div>'
        + '  <div><span>正式 SHA</span><code>' + escapeHtml(shadowShortSha(guard.before_sha256) + ' → ' + shadowShortSha(guard.after_sha256)) + '</code></div>'
        + '  <div><span>受保护融合候选全集</span><strong>' + escapeHtml(shadowPoolLabel(productionReference.pool)) + '</strong><small>' + escapeHtml(formalCount === null ? '数量未记录' : formatNumber(formalCount, 0) + ' 只') + '</small></div>'
        + '  <div><span>正式推荐</span><strong>' + escapeHtml(pageMainCount === null ? '数量未记录' : formatNumber(pageMainCount, 0) + ' 只') + '</strong><small>workspace.views.main</small></div>'
        + '  <div><span>影子批次</span><strong>' + escapeHtml(formatNumber(pendingCount, 0) + ' 条') + '</strong><small>' + escapeHtml(startedAt || '启动时间未记录') + '</small></div>'
        + '  <div><span>采集健康</span><strong>' + escapeHtml(collectionLabel) + '</strong><small>' + escapeHtml(collectionDetail) + '</small></div>'
        + '</div>';

      body += experiments.length ? experiments.map(function (experiment) {
        var rec = experiment || {};
        var metrics = scorecardByIdentity[shadowIdentity(rec)] || rec;
        var experimentStatus = rec.status;
        var horizon = rec.intended_horizon;
        var entryMode = rec.entry_mode;
        var sampleSize = safeNumber(metrics.sample_size, null);
        var activeDates = safeNumber(metrics.active_dates, null);
        var activeMonths = safeNumber(metrics.active_months, null);
        var excursionSize = safeNumber(metrics.excursion_sample_size, null);
        var hardReasons = asArray(metrics.hard_gate_reasons);
        var maturity = metrics.outcome_maturity || outcomeMaturity;
        var readiness = metrics.comparison_readiness || comparisonReadiness;
        var comparisonLabel = shadowComparisonLabel(readiness.status || metrics.comparison_status);
        var researchTierLabel = shadowResearchTierLabel(metrics.research_tier || rec.research_tier);
        var promotionBoundaryValid = rec.promotion_eligible === false
          && metrics.promotion_eligible === false;
        var horizonValid = Number.isInteger(horizon) && [1, 3, 5].indexOf(horizon) !== -1;
        var identityValid = shadowRequiredString(rec.experiment_id)
          && shadowRequiredString(rec.version)
          && shadowRequiredString(rec.upstream_pool)
          && shadowRequiredString(rec.source_pool);
        var experimentContractValid = experimentStatus === 'available'
          && rec.affects_production === false
          && promotionBoundaryValid
          && entryMode === 'immediate_close'
          && horizonValid
          && identityValid;
        var promotionLabel = promotionBoundaryValid ? '不可自动晋级' : '晋级边界异常';
        var reasonHtml = hardReasons.length
          ? hardReasons.map(function (reason) {
              return '<li>' + escapeHtml(shadowGateLabel(reason)) + '</li>';
            }).join('')
          : '<li>尚未记录晋级门槛</li>';
        var experimentTrusted = experimentContractValid;
        var experimentWarning = '';
        if (experimentStatus !== 'available') {
          experimentWarning = ''
            + '<div class="shadow-state is-warning"><strong>单项实验暂不可用</strong><span>'
            + escapeHtml(rec.error || '实验输出未生成') + '；正式主推不受影响。</span></div>';
        } else if (!promotionBoundaryValid) {
          experimentWarning = '<div class="shadow-state is-warning"><strong>晋级边界异常</strong><span>promotion_eligible 必须显式为 false；研究指标与候选已隐藏。</span></div>';
        } else if (!experimentContractValid) {
          experimentWarning = '<div class="shadow-state is-warning"><strong>实验合同异常</strong><span>实验身份、隔离、周期或入场口径未通过校验；研究指标与候选已隐藏。</span></div>';
        }
        var experimentResearch = experimentTrusted ? ''
          + '  <div class="shadow-progress"><strong>样本进度</strong><span>' + escapeHtml(formatNumber(sampleSize, 0) + '/100 成熟样本 · ' + formatNumber(activeDates, 0) + '/20 活跃日 · ' + formatNumber(activeMonths, 0) + '/2 月') + '</span></div>'
          + renderShadowMaturity(maturity)
          + '  <div class="shadow-metric-grid">'
          + renderShadowMetric('成熟样本', formatNumber(sampleSize, 0), '')
          + renderShadowMetric('活跃日 / 月', formatNumber(activeDates, 0) + ' / ' + formatNumber(activeMonths, 0), '')
          + renderShadowMetric('平均收盘收益', formatPct(metrics.mean_close_return, true), 'is-primary')
          + renderShadowMetric('中位收盘收益', formatPct(metrics.median_close_return, true), '')
          + renderShadowMetric('上涨率', formatPct(metrics.up_rate), '')
          + renderShadowMetric('收益 ≥5%', formatPct(metrics.hit_rate_ge_5), '')
          + renderShadowMetric('平均期间最高收益（MFE）', formatPct(metrics.mean_mfe, true), '')
          + renderShadowMetric('平均期间最低收益（MAE）', formatPct(metrics.mean_mae, true), '')
          + renderShadowMetric('最差收盘收益', formatPct(metrics.worst_close_return, true), '')
          + renderShadowMetric('盘中轨迹样本', formatNumber(excursionSize, 0), '')
          + '  </div>'
          + '  <section class="shadow-subsection"><h5>尚未晋级原因</h5><ul class="shadow-gate-list">' + reasonHtml + '</ul></section>'
          + '  <section class="shadow-subsection"><h5>代表样本</h5>' + renderShadowSamples(metrics) + '</section>'
          + '  <section class="shadow-subsection"><h5>今日影子候选</h5>' + renderShadowCandidates(rec) + '</section>'
          : experimentWarning;
        return ''
          + '<article class="shadow-experiment">'
          + '  <header class="shadow-experiment-head">'
          + '    <div><h4>' + escapeHtml(rec.display_name || rec.experiment_id || '未命名影子实验') + '</h4><small>' + escapeHtml((rec.version || rec.strategy_version || '版本未知') + ' · ' + (rec.experiment_id || '--')) + '</small></div>'
          + '    <div class="shadow-contract-tags"><span>' + escapeHtml(horizonValid ? 'T+' + formatNumber(horizon, 0) : '周期合同异常') + '</span><span>' + escapeHtml(entryMode === 'immediate_close' ? '入场 = 信号日收盘' : '入场口径异常') + '</span></div>'
          + '  </header>'
          + '  <div class="shadow-pool-map"><span>共同上游：' + escapeHtml(shadowPoolLabel(rec.upstream_pool)) + '</span><span>策略来源：' + escapeHtml(shadowPoolLabel(rec.source_pool)) + '</span></div>'
          + '  <div class="shadow-conclusion-grid">'
          + '    <div><small>当前结论</small><strong>' + escapeHtml(comparisonLabel) + '</strong></div>'
          + '    <div><small>研究层级</small><strong>' + escapeHtml(researchTierLabel) + '</strong></div>'
          + '    <div class="' + (promotionBoundaryValid ? 'is-safe' : 'is-warning') + '"><small>晋级边界</small><strong>' + escapeHtml(promotionLabel) + '</strong></div>'
          + '  </div>'
          + experimentResearch
          + '</article>';
      }).join('') : '<div class="shadow-state"><strong>等待首个收盘样本</strong><span>影子评测已启用，当前没有可展示的实验；正式主推不受影响。</span></div>';
    }

    return renderDecisionCard({
      title: '影子评测',
      subtitle: isolated
        ? '收盘价研究区：独立记录候选、收益与盘中最高/最低轨迹，不改变正式选股结果'
        : '影子合同未通过隔离校验，不展示研究结论',
      badge: { text: statusText, tone: statusTone },
      className: 'shadow-card',
      bodyHtml: body,
    });
  }

  function renderDiagnosticsCard(data) {
    var source = data || {};
    var rawDiagnostics = source.diagnostics || {};
    var diagnostics = {};
    Object.keys(rawDiagnostics).forEach(function (key) {
      diagnostics[key] = rawDiagnostics[key];
    });
    var decisionLlmError = normalizeString((source.decision_brief || {}).llm_error);
    if (decisionLlmError) {
      var existingDecisionDiagnostic = diagnostics.decision_brief;
      var decisionDiagnostic = existingDecisionDiagnostic && typeof existingDecisionDiagnostic === 'object'
        ? Object.assign({}, existingDecisionDiagnostic)
        : {};
      decisionDiagnostic.status = 'error';
      decisionDiagnostic.error = normalizeString(decisionDiagnostic.error) || decisionLlmError;
      diagnostics.decision_brief = decisionDiagnostic;
    }
    if (source.selection_input_health && typeof source.selection_input_health === 'object') {
      diagnostics.selection_input_health = source.selection_input_health;
    } else {
      diagnostics.selection_input_health = {
        status: 'unavailable',
        formal: {
          formal_actions_allowed: false,
          all_formal_actions_allowed: false,
          invalid_codes: [],
        },
        synthetic_missing: true,
      };
    }
    var allKeys = Object.keys(diagnostics);
    var priorityKeys = ['selection_input_health', 'decision_brief', 'data_quality', 'recommendation_ledger', 'strategy_review', 'position_book'];
    function diagnosticStatusText(key, value) {
      if (!value || typeof value !== 'object') return normalizeString(value);
      if (key === 'selection_input_health') {
        var formalInput = value.formal || {};
        var blockedNames = asArray(formalInput.blocked_strategies).map(function (strategy) {
          var labels = { daily_fusion: '正式主推', h4_t3: 'H4 T+3' };
          return labels[normalizeString(strategy)] || normalizeString(strategy);
        }).filter(Boolean);
        if (formalInput.all_formal_actions_allowed === false
            && formalInput.formal_actions_allowed === true) {
          return '部分正式策略输入过期或未核验，受影响动作已封闭：'
            + (blockedNames.join('、') || '策略名称未登记')
            + '；受影响代码 '
            + (asArray(formalInput.invalid_codes).join('、') || '未登记');
        }
        if (formalInput.formal_actions_allowed !== true) {
          return '正式策略输入过期、未核验或未记录；本期未选出推荐票。受影响代码 '
            + (asArray(formalInput.invalid_codes).join('、') || '未登记');
        }
        if (normalizeString(value.status) === 'partial') {
          return '正式策略输入已核验；部分研究池分钟级输入缺失。';
        }
        return '正式策略与研究池输入已核验。';
      }
      if (key === 'decision_brief' && normalizeString(value.error)) {
        var formalAllowed = (((source.selection_input_health || {}).formal || {}).formal_actions_allowed);
        return 'LLM 方向复核失败，已回退规则结果；正式动作'
          + (formalAllowed === false ? '已因策略输入问题封闭。' : '未被该模型异常直接改写。');
      }
      if (key === 'data_quality') {
        var qualityWarnings = asArray(value.warnings).map(normalizeString).filter(Boolean);
        var official = value.is_official === true && normalizeString(value.bar_state) === 'closed';
        var scope = normalizeString(value.official_pool_scope);
        var scopeText = scope === 'active_retrieval_pool' ? '活跃发布池' : (scope || '范围未标注');
        var fallbackText = value.fallback_used === true ? '，存在回退' : '，无回退';
        var listScopeText = (asArray(value.missing_daily_codes).length || asArray(value.stale_daily_codes).length)
          ? '；代码列表为全量刷新诊断，与活跃发布池计数不是同一分母'
          : '';
        var qualitySummary = (official ? '正式收盘数据' : '非正式或未收盘数据')
          + '；计数范围：' + scopeText + fallbackText + listScopeText;
        return qualityWarnings.length ? qualityWarnings.join('；') + '；' + qualitySummary : qualitySummary;
      }
      var explicit = normalizeString(
        value.error
        || asArray(value.errors).join('；')
        || value.warning
        || asArray(value.warnings).join('；')
        || value.message
        || value.summary
      );
      if (explicit) return userFacingEvidenceText(explicit, false);
      var status = normalizeString(value.status).toLowerCase();
      var labels = {
        ok: '检查通过',
        complete: '数据完整',
        pending_report_validation: '等待日报校验完成后入正式账本',
        unconfigured: '未配置',
        missing: '数据缺失',
        partial: '数据部分可用',
        unavailable: '本期证据不足',
        error: '生成异常',
        finalization_incomplete: '账本终结不完整',
      };
      if (labels[status]) return labels[status];
      return status ? '状态：' + status : '有诊断记录，未提供结论';
    }
    function diagnosticPriority(key, value) {
      if (!value || typeof value !== 'object') return 0;
      var status = normalizeString(value.status).toLowerCase();
      var hasErrors = Boolean(normalizeString(value.error))
        || asArray(value.errors).length > 0;
      var hasWarnings = Boolean(normalizeString(value.warning))
        || asArray(value.warnings).length > 0;
      if (key === 'selection_input_health') {
        var formalInput = value.formal || {};
        if (formalInput.formal_actions_allowed !== true) return 4;
        if (formalInput.all_formal_actions_allowed === false) return 3;
      }
      if (hasErrors) return 4;
      if (/error|failed|invalid|conflict|finalization_incomplete/.test(status)) return 3;
      if (hasWarnings) return 2;
      if (/partial|stale|unconfigured|unconfirmed|missing|fallback|private|pending|waiting/.test(status)) return 1;
      return 0;
    }
    var orderedKeys = allKeys.slice().sort(function (left, right) {
      var priorityDiff = diagnosticPriority(right, diagnostics[right])
        - diagnosticPriority(left, diagnostics[left]);
      if (priorityDiff) return priorityDiff;
      var leftPriority = priorityKeys.indexOf(left);
      var rightPriority = priorityKeys.indexOf(right);
      if (leftPriority !== -1 || rightPriority !== -1) {
        if (leftPriority === -1) return 1;
        if (rightPriority === -1) return -1;
        return leftPriority - rightPriority;
      }
      return allKeys.indexOf(left) - allKeys.indexOf(right);
    });
    var pinnedKeys = priorityKeys.filter(function (key) {
      return allKeys.indexOf(key) !== -1;
    });
    var keys = orderedKeys.slice(0, 8);
    pinnedKeys.forEach(function (key) {
      if (keys.indexOf(key) !== -1) return;
      for (var index = keys.length - 1; index >= 0; index -= 1) {
        if (pinnedKeys.indexOf(keys[index]) === -1) {
          keys.splice(index, 1);
          break;
        }
      }
      keys.push(key);
    });
    var highestPriority = orderedKeys.reduce(function (highest, key) {
      return Math.max(highest, diagnosticPriority(key, diagnostics[key]));
    }, 0);
    var badgeMeta = highestPriority >= 3
      ? { text: '异常', tone: 'danger' }
      : (highestPriority >= 1
        ? { text: '有提醒', tone: 'warning' }
        : { text: '正常', tone: 'positive' });
    var keyLabels = {
      decision_brief: '今日方向模型复核',
      selection_input_health: '选股输入健康',
      position_book: '持仓配置',
      data_quality: '数据质量',
      strategy_review: '策略回看',
      recommendation_ledger: '推荐归因账本',
    };
    var rowsHtml = keys.length ? keys.map(function (key) {
      var value = diagnostics[key];
      var text = diagnosticStatusText(key, value);
      var technicalDetails = key === 'decision_brief' && normalizeString(value && value.error)
        ? '<details class="diagnostic-technical"><summary>技术详情</summary><code>'
          + escapeHtml(normalizeString(value.error).slice(0, 500))
          + (normalizeString(value.error).length >= 500 ? '…（已截断）' : '（原始异常可能已由上游截断）')
          + '</code></details>'
        : '';
      return ''
        + '<div class="diagnostic-row">'
        + '  <strong>' + escapeHtml(keyLabels[key] || key) + '</strong>'
        + '  <span>' + escapeHtml(text || '有诊断记录，未提供结论') + '</span>'
        + technicalDetails
        + '</div>';
    }).join('') : '<div class="decision-empty">暂无诊断信息</div>';
    var summaryText = keys.length
      ? '展示 ' + keys.length + ' / ' + allKeys.length + ' 项，优先显示异常和提醒，点击展开'
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
      badge: keys.length ? badgeMeta : { text: '暂无', tone: 'neutral' },
      className: 'diagnostics-card',
      bodyHtml: body,
    });
  }

  function bindSingleOpenDetailsWithin(containerSelector, detailSelector) {
    var roots = [nodes.supportingStack, nodes.auxGrid].filter(Boolean);
    roots.forEach(function (root) {
      var containers = root.querySelectorAll(containerSelector);
      Array.prototype.forEach.call(containers, function (container) {
        var details = container.querySelectorAll(detailSelector);
        Array.prototype.forEach.call(details, function (current) {
          current.addEventListener('toggle', function () {
            if (!current.open) return;
            Array.prototype.forEach.call(details, function (detail) {
              if (detail !== current) detail.open = false;
            });
          });
        });
      });
    });
  }

  function bindSingleOpenDecisionDetails() {
    bindSingleOpenDetailsWithin('.decision-directions-card', '.decision-direction');
    bindSingleOpenDetailsWithin('.strategy-scorecards-card', '.strategy-scorecard');
  }

  function buildAuxiliaryStacks(data) {
    var source = data || {};
    return {
      today: ''
        + renderDecisionDirections(source)
        + renderPersonalWatchlist(source)
        + renderHoldingRiskSection(source),
      research: ''
        + renderMarketTemperatureCard(source)
        + renderSectorFlowCard(source)
        + renderLimitUpEcologyCard(source)
        + renderStrategyDisagreementAudit(source)
        + renderStrategyScorecards(source)
        + renderShadowEvaluations(source)
        + renderDiagnosticsCard(source),
    };
  }

  function renderAuxiliaryCenter() {
    if (!nodes.auxGrid || !nodes.supportingStack) return;
    var stacks = buildAuxiliaryStacks(state.data || {});
    nodes.supportingStack.innerHTML = stacks.today;
    nodes.auxGrid.innerHTML = stacks.research;
    bindSingleOpenDecisionDetails();
    bindWatchlistManager();
    setTimeout(renderMarketSentimentChart, 0);
  }

  function setDrawerBackgroundInert(inert) {
    if (!nodes.shell || !nodes.drawer) return;
    if (inert) {
      if (state.drawerBackgroundState.length) return;
      var siblings = Array.prototype.filter.call(nodes.shell.children || [], function (region) {
        return region !== nodes.drawer;
      });
      state.drawerBackgroundState = siblings.map(function (region) {
        var snapshot = {
          region: region,
          hadAriaHidden: region.hasAttribute('aria-hidden'),
          ariaHidden: region.getAttribute('aria-hidden'),
          hadInertAttribute: region.hasAttribute('inert'),
          inertAttribute: region.getAttribute('inert'),
          inertSupported: 'inert' in region,
          inertValue: 'inert' in region ? Boolean(region.inert) : false,
        };
        region.setAttribute('aria-hidden', 'true');
        region.setAttribute('inert', '');
        if (snapshot.inertSupported) region.inert = true;
        return snapshot;
      });
      return;
    }
    state.drawerBackgroundState.forEach(function (snapshot) {
      var region = snapshot.region;
      if (snapshot.hadAriaHidden) region.setAttribute('aria-hidden', snapshot.ariaHidden);
      else region.removeAttribute('aria-hidden');
      if (snapshot.hadInertAttribute) region.setAttribute('inert', snapshot.inertAttribute);
      else region.removeAttribute('inert');
      if (snapshot.inertSupported) region.inert = snapshot.inertValue;
    });
    state.drawerBackgroundState = [];
  }

  function trapDrawerFocus(event) {
    if (!nodes.drawer || !nodes.drawer.classList.contains('is-open')) return;
    if (event.key === 'Escape') {
      event.preventDefault();
      closeMobileDetailDrawer();
      return;
    }
    if (event.key !== 'Tab') return;
    var focusable = Array.prototype.slice.call(nodes.drawer.querySelectorAll(
      'button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
    )).filter(function (element) {
      return !element.hidden && element.getAttribute('aria-hidden') !== 'true';
    });
    if (!focusable.length) {
      event.preventDefault();
      if (nodes.drawerPanel && nodes.drawerPanel.focus) nodes.drawerPanel.focus();
      return;
    }
    var first = focusable[0];
    var last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  function openMobileDetailDrawer(item, returnCode) {
    if (!state.isMobile || !nodes.drawer) return;
    if (item) {
      state.activeItem = item;
    }
    if (!state.activeItem) return;
    syncMobileDrawerViewport();
    nodes.drawerContent.innerHTML = '';
    renderCandidateDetail(state.activeItem, nodes.drawerContent);
    state.drawerReturnFocus = document.activeElement || null;
    state.drawerReturnCode = normalizeString(returnCode || (item && item.code));
    nodes.drawer.classList.add('is-open');
    nodes.drawer.setAttribute('aria-hidden', 'false');
    setDrawerBackgroundInert(true);
    document.body.style.overflow = 'hidden';
    if (nodes.drawerPanel) {
      nodes.drawerPanel.scrollTop = 0;
      if (nodes.drawerPanel.focus) nodes.drawerPanel.focus();
    }
    setTimeout(function () {
      if (state.chartInstance) {
        state.chartInstance.resize();
      }
      if (state.sentimentChartInstance) {
        state.sentimentChartInstance.resize();
      }
    }, 40);
  }

  function syncMobileDrawerViewport() {
    if (!state.isMobile) return;
    var bottomOffset = 16;
    if (window.visualViewport) {
      bottomOffset = Math.max(
        16,
        window.innerHeight - window.visualViewport.height - window.visualViewport.offsetTop + 16
      );
    }
    document.documentElement.style.setProperty('--mobile-drawer-bottom-offset', bottomOffset + 'px');
  }

  function closeMobileDetailDrawer() {
    if (!nodes.drawer) return;
    nodes.drawer.classList.remove('is-open');
    nodes.drawer.setAttribute('aria-hidden', 'true');
    setDrawerBackgroundInert(false);
    document.body.style.overflow = '';
    var restored = state.drawerReturnCode && nodes.candidateList
      ? nodes.candidateList.querySelector('[data-code="' + state.drawerReturnCode + '"]')
      : null;
    if (restored && restored.focus) {
      restored.focus();
    } else if (state.drawerReturnFocus && state.drawerReturnFocus.focus) {
      state.drawerReturnFocus.focus();
    }
    state.drawerReturnFocus = null;
    state.drawerReturnCode = '';
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
    var date = bootstrap.pageDate || getPreclosePageDate();
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
        default_view: 'main',
        view_order: DEFAULT_VIEW_ORDER,
        view_meta: {},
        views: {},
      };
      return;
    }

    state.workspace = ws;
    state.currentView = ws.default_view || state.currentView;
    if (!state.currentView) state.currentView = 'main';
  }

  function initReportV2() {
    syncViewport();
    state.isMobile = isMobileViewport();
    buildAppShell();
    renderPrimaryMode();
    loadPrecloseAdvisory();
    state.rawPoolCandidates = null;
    resetTop10State();
    renderTop10Control();
    loadLatestTop10Snapshot();
    if (nodes.top10RunButton) {
      nodes.top10RunButton.addEventListener('click', handleTop10Run);
    }

    resolveGranted().then(function (granted) {
      state.granted = granted;
      return resolveInitialData();
    }).then(function (data) {
      state.data = data || {};
      window.REPORT_DATA = state.data;
      normalizeWorkspace(state.data);
      state.currentView = state.workspace && state.workspace.default_view ? state.workspace.default_view : 'main';
      renderHeader();
      renderFundingMainlineStrip();
      renderDirectionQuickSummary(state.data);
      renderHistoricalReconstruction(state.data);
      renderWorkspaceTabs();
      renderViewDescription();
      renderCandidateEvidenceComparisonMount();
      var first = filterCandidatesBySector(
        getCurrentViewItems(), state.sectorFilter, state.sectorFilterCode,
        state.sectorFilterRefs
      )[0] || null;
      state.activeItem = first;
      renderCandidateList();
      renderCandidateDetail(first);
      renderAuxiliaryCenter();
      initComparisonSummary();
      renderTop10Control();
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
    if (nodes.drawer) {
      nodes.drawer.addEventListener('keydown', trapDrawerFocus);
    }

    window.addEventListener('resize', function () {
      syncViewport();
      syncMobileDrawerViewport();
      if (state.chartInstance) {
        state.chartInstance.resize();
      }
      if (state.sentimentChartInstance) {
        state.sentimentChartInstance.resize();
      }
    });
    if (window.visualViewport) {
      window.visualViewport.addEventListener('resize', syncMobileDrawerViewport);
      window.visualViewport.addEventListener('scroll', syncMobileDrawerViewport);
    }
    window.addEventListener('beforeunload', function (event) {
      if (!watchlistManagerState().dirty) return;
      event.preventDefault();
      event.returnValue = '';
    });
  }

  window.initReportV2 = initReportV2;
  window.renderHeader = renderHeader;
  window.renderWorkspaceTabs = renderWorkspaceTabs;
  window.renderHistoricalReconstruction = renderHistoricalReconstruction;
  window.renderViewDescription = renderViewDescription;
  window.renderCandidateList = renderCandidateList;
  window.renderCandidateDetail = renderCandidateDetail;
  window.openMobileDetailDrawer = openMobileDetailDrawer;
  window.closeMobileDetailDrawer = closeMobileDetailDrawer;
  window.findRawCandidate = findRawCandidate;
  window.renderChart = renderChart;
  window.renderAuxiliaryCenter = renderAuxiliaryCenter;
  window.renderMarketSentimentChart = renderMarketSentimentChart;
  window.resolveGranted = resolveGranted;

  function comparisonNumber(value) {
    var number = safeNumber(value, null);
    return number === null || number === 0 ? null : number;
  }

  function comparisonReturn(sourcePrice, targetPrice) {
    var source = comparisonNumber(sourcePrice);
    var target = comparisonNumber(targetPrice);
    return source === null || target === null ? null : ((target - source) / source) * 100;
  }

  function comparisonMedian(values) {
    var sorted = values.filter(function (value) { return value !== null; }).slice().sort(function (a, b) { return a - b; });
    if (!sorted.length) return null;
    var middle = Math.floor(sorted.length / 2);
    return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
  }

  function comparisonMean(values) {
    var valid = values.filter(function (value) { return value !== null; });
    if (!valid.length) return null;
    return valid.reduce(function (total, value) { return total + value; }, 0) / valid.length;
  }

  function isArchiveReportPath(pathname) {
    var path = normalizeString(pathname).replace(/\/+$/, '');
    return /\/\d{4}-\d{2}-\d{2}(?:\/index\.html)?$/.test(path);
  }

  function getComparisonIndexUrl() {
    if (isComparisonPage()) return '../data/comparison-index.json';
    return isArchiveReportPath(window.location && window.location.pathname)
      ? '../data/comparison-index.json'
      : 'data/comparison-index.json';
  }

  function comparisonViewLabel(view) {
    return DEFAULT_VIEW_LABELS[view] || normalizeString(view);
  }

  function isComparablePerformanceView(view) {
    return view === 'main' || view === 'h4_t3';
  }

  function comparisonDateLabel(index, date) {
    var report = index && index.reports && index.reports[date];
    var quality = report && report.quality || {};
    return date + (quality.is_official === false ? ' · 历史质量不足' : '');
  }

  function comparisonQualityWarning(index, sourceDate, targetDate) {
    var dates = [sourceDate];
    if (targetDate && targetDate !== 'current' && targetDate !== sourceDate) dates.push(targetDate);
    var warnings = dates.map(function (date) {
      var quality = index && index.reports && index.reports[date] && index.reports[date].quality || {};
      if (quality.is_official !== false) return '';
      return date + ' 原报告存在日线缺失 ' + safeNumber(quality.missing_daily_count, 0)
        + '、过期股票 ' + safeNumber(quality.stale_stock_count, 0);
    }).filter(Boolean);
    if (!warnings.length) return '';
    return '<div class="comparison-quality-warning"><strong>历史质量不足</strong><span>'
      + escapeHtml(warnings.join('；')) + '。收益价格仍使用本地正式收盘数据。</span></div>';
  }

  function comparisonSummary(view, rows) {
    var values = rows.map(function (row) { return row.actual; }).filter(function (value) { return value !== null; });
    var wins = values.filter(function (value) { return value > 0; }).length;
    return {
      view: view, rows: rows, average: comparisonMean(values), median: comparisonMedian(values),
      winRate: values.length ? wins / values.length * 100 : null,
      maximum: values.length ? Math.max.apply(Math, values) : null,
      minimum: values.length ? Math.min.apply(Math, values) : null,
      evaluable: values.length, missing: rows.length - values.length,
    };
  }

  var COMPARISON_SORT_OPTIONS = [
    { key: 'rank', label: '当时排名', defaultDirection: 'asc' },
    { key: 'sourcePrice', label: '源收盘', defaultDirection: 'desc' },
    { key: 'targetPrice', label: '对比价', defaultDirection: 'desc' },
    { key: 'actual', label: '实际涨跌', defaultDirection: 'desc' },
    { key: 'excess', label: '超额收益', defaultDirection: 'desc' },
  ];

  function comparisonSortOption(key) {
    return COMPARISON_SORT_OPTIONS.filter(function (option) { return option.key === key; })[0]
      || COMPARISON_SORT_OPTIONS[0];
  }

  function comparisonSortValue(row, key) {
    var item = row && row.item || {};
    var value = key === 'rank' ? item.rank : row && row[key];
    return safeNumber(value, null);
  }

  function comparisonSortRows(rows, key, direction) {
    var option = comparisonSortOption(key);
    var order = direction === 'desc' ? -1 : 1;
    return asArray(rows).map(function (row, index) {
      return { row: row, index: index, value: comparisonSortValue(row, option.key) };
    }).sort(function (left, right) {
      if (left.value === null && right.value === null) return left.index - right.index;
      if (left.value === null) return 1;
      if (right.value === null) return -1;
      if (left.value === right.value) return left.index - right.index;
      return (left.value < right.value ? -1 : 1) * order;
    }).map(function (entry) { return entry.row; });
  }

  function comparisonSortDirection(key) {
    return comparisonSortOption(key).defaultDirection;
  }

  function comparisonSortHeader(label, key, sortState) {
    var active = sortState && sortState.key === key;
    var direction = active ? sortState.direction : '';
    var ariaSort = active ? (direction === 'desc' ? 'descending' : 'ascending') : 'none';
    return '<th class="comparison-sort-header" aria-sort="' + ariaSort + '"><button type="button" class="comparison-sort-button" data-comparison-sort="' + key + '" aria-label="按' + label + '排序" title="按' + label + '排序">'
      + label + (active ? '<span class="comparison-sort-indicator ' + direction + '" aria-hidden="true"></span>' : '')
      + '</button></th>';
  }

  function comparisonSortMobileControls(sortState) {
    var selectedKey = sortState && sortState.key || 'rank';
    var direction = sortState && sortState.direction || 'asc';
    return '<div class="comparison-sort-mobile" aria-label="榜单排序，缺失值排在最后">'
      + '<label>排序<select data-comparison-sort-select>'
      + COMPARISON_SORT_OPTIONS.map(function (option) {
        return '<option value="' + option.key + '"' + (option.key === selectedKey ? ' selected' : '') + '>' + option.label + '</option>';
      }).join('')
      + '</select></label>'
      + '<button type="button" data-comparison-sort-direction aria-label="切换排序方向">' + (direction === 'desc' ? '降序' : '升序') + '</button>'
      + '<span>缺失值排在最后</span></div>';
  }

  function comparisonScale(value, minimum, maximum) {
    if (value === null || maximum === minimum) return 50;
    return (value - minimum) / (maximum - minimum) * 100;
  }

  function comparisonBenchmarkPosition(value, minimum, maximum) {
    return comparisonScale(value, minimum, maximum);
  }

  function renderComparisonPage(index, root) {
    var dates = asArray(index && index.dates).slice(-26);
    var latestDate = normalizeString(index && index.latest_date) || dates[dates.length - 1] || '';
    var sourceDate = dates.length > 1 ? dates[dates.length - 2] : latestDate;
    var targetDate = 'current';
    root.innerHTML = ''
      + '<header class="comparison-header"><div><p class="comparison-eyebrow">报告复盘</p><h1>榜单表现比对</h1><p>实际涨跌为主指标；沪深300与超额收益用于辅助判断。</p></div><a class="comparison-back" href="../index.html">返回最新日报</a></header>'
      + '<section class="comparison-controls" aria-label="比对条件">'
      + '<label>源报告日<select id="comparisonSource">' + dates.map(function (date) { return '<option value="' + escapeHtml(date) + '"' + (date === sourceDate ? ' selected' : '') + '>' + escapeHtml(comparisonDateLabel(index, date)) + '</option>'; }).join('') + '</select></label>'
      + '<label>对比日<select id="comparisonTarget"><option value="current">当前</option>' + dates.map(function (date) { return '<option value="' + escapeHtml(date) + '">' + escapeHtml(comparisonDateLabel(index, date)) + '</option>'; }).join('') + '</select></label>'
      + '<button id="comparisonRefresh" type="button">刷新对比价</button><span id="comparisonQuoteStatus" class="comparison-status">尚未刷新当前行情</span>'
      + '</section><div id="comparisonContent"></div>';

    var quoteData = null;
    var quoteSourceDate = '';
    function clearComparisonQuotes() {
      quoteData = null;
      quoteSourceDate = '';
    }
    function syncComparisonControls() {
      var targetDate = root.querySelector('#comparisonTarget').value;
      var button = root.querySelector('#comparisonRefresh');
      var status = root.querySelector('#comparisonQuoteStatus');
      button.textContent = targetDate === 'current' ? '刷新对比价' : '开始比对';
      status.textContent = targetDate === 'current' ? '尚未刷新当前行情' : '使用历史报告收盘价';
    }
    function render() {
      var source = root.querySelector('#comparisonSource').value;
      var target = root.querySelector('#comparisonTarget').value;
      var sourceDate = source;
      var targetDate = target;
      if (targetDate !== 'current' && sourceDate > targetDate) {
        root.querySelector('#comparisonContent').innerHTML = '<div class="comparison-empty">对比日不能早于源报告日。</div>';
        return;
      }
      if (targetDate === 'current' && (!quoteData || quoteSourceDate !== sourceDate)) {
        root.querySelector('#comparisonContent').innerHTML = '<div class="comparison-empty">尚未刷新当前行情。点击“刷新对比价”后计算实际涨跌。</div>';
        return;
      }
      renderComparisonResult(index, source, target, quoteData, root.querySelector('#comparisonContent'));
    }
    function handleConditionChange() {
      clearComparisonQuotes();
      syncComparisonControls();
      root.querySelector('#comparisonContent').innerHTML = '<div class="comparison-empty">请选择条件后点击“' + (root.querySelector('#comparisonTarget').value === 'current' ? '刷新对比价' : '开始比对') + '”。</div>';
    }
    root.querySelector('#comparisonSource').addEventListener('change', handleConditionChange);
    root.querySelector('#comparisonTarget').addEventListener('change', handleConditionChange);
    root.querySelector('#comparisonRefresh').addEventListener('click', requestCurrentQuotes);
    function requestCurrentQuotes() {
      var source = root.querySelector('#comparisonSource').value;
      var targetDate = root.querySelector('#comparisonTarget').value;
      if (targetDate !== 'current') { clearComparisonQuotes(); render(); return; }
      var sourceReport = (index.reports || {})[source] || {};
      var codeMap = {};
      Object.keys(sourceReport.views || {}).forEach(function (view) {
        asArray(sourceReport.views[view]).forEach(function (item) { if (item && item.code) codeMap[item.code] = true; });
      });
      var codes = Object.keys(codeMap);
      var status = root.querySelector('#comparisonQuoteStatus');
      var apiBase = getTop10ApiBase();
      if (!apiBase || !window.fetch) { status.textContent = '当前行情接口未配置'; return; }
      status.textContent = '正在刷新当前行情…';
      window.fetch(apiBase + '/api/quotes/current', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ codes: codes }),
      }).then(function (resp) {
        if (!resp || !resp.ok) throw new Error('行情请求失败');
        return resp.json();
      }).then(function (payload) {
        quoteData = payload || {};
        quoteSourceDate = source;
        status.textContent = '当前行情已刷新：' + formatTop10Date(quoteData.quoted_at || '');
        render();
      }).catch(function () { status.textContent = '当前行情刷新失败'; });
    }
    syncComparisonControls();
    render();
  }

  function renderComparisonResult(index, sourceDate, targetDate, quoteData, mount) {
    var reports = index.reports || {};
    var source = reports[sourceDate] || {};
    var target = targetDate === 'current' ? {} : (reports[targetDate] || {});
    var quoteMap = {};
    var quoteStatusMap = {};
    asArray(quoteData && (quoteData.quotes || quoteData.items || [])).forEach(function (quote) {
      if (!quote || !quote.code) return;
      quoteMap[quote.code] = quote.current_price;
      quoteStatusMap[quote.code] = quote.status;
    });
    var useCurrent = targetDate === 'current' && !!quoteData;
    var benchmarkSource = comparisonNumber(source.benchmark && source.benchmark.close);
    var benchmarkTarget = useCurrent ? comparisonNumber(quoteData.benchmark && quoteData.benchmark.current_price) : comparisonNumber(target.benchmark && target.benchmark.close);
    var benchmarkReturn = comparisonReturn(benchmarkSource, benchmarkTarget);
    var views = source.views || {};
    var summaries = Object.keys(views).filter(isComparablePerformanceView).map(function (view) {
      var rows = asArray(views[view]).map(function (item) {
        var sourcePrice = source.prices && source.prices[item.code];
        var targetPrice = useCurrent ? quoteMap[item.code] : target.prices && target.prices[item.code];
        var actual = comparisonReturn(sourcePrice, targetPrice);
        var missingReason = '';
        if (comparisonNumber(sourcePrice) === null) missingReason = '缺少榜单日收盘价';
        else if (comparisonNumber(targetPrice) === null) {
          missingReason = useCurrent
            ? (quoteStatusMap[item.code] === 'upstream_error' ? '当前价获取失败' : '当前价缺失')
            : '缺少历史对比价';
        }
        return { item: item || {}, sourcePrice: sourcePrice, targetPrice: targetPrice, actual: actual, excess: actual === null || benchmarkReturn === null ? null : actual - benchmarkReturn, missingReason: missingReason };
      });
      return comparisonSummary(view, rows);
    });
    var chartSummaries = summaries;
    var scaleValues = chartSummaries.map(function (summary) { return summary.average; }).filter(function (value) { return value !== null; });
    if (benchmarkReturn !== null) scaleValues.push(benchmarkReturn);
    scaleValues.push(0);
    var scaleMin = Math.min.apply(Math, scaleValues);
    var scaleMax = Math.max.apply(Math, scaleValues);
    if (scaleMin === scaleMax) { scaleMin -= 1; scaleMax += 1; }
    var zeroPosition = comparisonScale(0, scaleMin, scaleMax);
    var benchmarkText = benchmarkReturn === null ? '指数数据缺失' : '沪深300：' + formatPct(benchmarkReturn, true);
    mount.innerHTML = comparisonQualityWarning(index, sourceDate, targetDate)
      + '<section class="comparison-workspace"><aside class="comparison-master"><h2>榜单实际表现</h2><p class="comparison-benchmark">' + benchmarkText + '</p>'
      + '<div class="comparison-chart"><i class="comparison-chart-zero" style="left:' + zeroPosition + '%"></i>'
      + '<i class="comparison-chart-benchmark' + (benchmarkReturn === null ? ' is-missing' : '') + '" style="left:' + comparisonBenchmarkPosition(benchmarkReturn, scaleMin, scaleMax) + '%"></i>'
      + chartSummaries.map(function (summary) {
        var position = comparisonScale(summary.average, scaleMin, scaleMax);
        var left = Math.min(zeroPosition, position);
        var width = Math.abs(position - zeroPosition);
        var tone = summary.average !== null && summary.average >= 0 ? 'is-up' : 'is-down';
        return '<div class="comparison-chart-row"><span>' + escapeHtml(comparisonViewLabel(summary.view)) + '</span><div><b class="' + tone + '" style="left:' + left + '%;width:' + width + '%"></b></div><strong>' + formatPct(summary.average, true) + '</strong></div>';
      }).join('') + '</div>'
      + summaries.map(function (summary) {
        var tone = summary.average !== null && summary.average >= 0 ? 'is-up' : 'is-down';
        return '<button type="button" class="comparison-view-card" data-comparison-view="' + escapeHtml(summary.view) + '" aria-pressed="false"><span>' + escapeHtml(comparisonViewLabel(summary.view)) + '</span><strong class="' + tone + '">' + formatPct(summary.average, true) + '</strong><small>中位数 ' + formatPct(summary.median, true) + ' · 上涨率 ' + formatPct(summary.winRate) + ' · 有效 ' + summary.evaluable + ' / 缺失 ' + summary.missing + '</small></button>';
      }).join('') + '</aside><section class="comparison-detail"><div id="comparisonDetail"></div></section></section>';
    var buttons = mount.querySelectorAll('[data-comparison-view]');
    var sortState = { key: 'rank', direction: 'asc' };
    function showDetail(view) {
      var summary = summaries.filter(function (entry) { return entry.view === view; })[0] || summaries[0];
      if (!summary) { mount.querySelector('#comparisonDetail').innerHTML = '<div class="comparison-empty">源报告日没有可比对的榜单。</div>'; return; }
      Array.prototype.forEach.call(buttons, function (button) {
        var active = button.getAttribute('data-comparison-view') === summary.view;
        button.classList.toggle('is-active', active);
        button.setAttribute('aria-pressed', active ? 'true' : 'false');
      });
      var missing = summary.rows.filter(function (row) { return row.actual === null; });
      var rows = summary.rows.filter(function (row) { return row.actual !== null; });
      mount.querySelector('#comparisonDetail').innerHTML = '<header class="comparison-detail-head"><h2>' + escapeHtml(comparisonViewLabel(summary.view)) + '</h2><div><span>实际平均涨跌 <strong>' + formatPct(summary.average, true) + '</strong></span><span>中位数 <strong>' + formatPct(summary.median, true) + '</strong></span><span>上涨率 <strong>' + formatPct(summary.winRate) + '</strong></span><span>最大涨幅 <strong>' + formatPct(summary.maximum, true) + '</strong></span><span>最大跌幅 <strong>' + formatPct(summary.minimum, true) + '</strong></span><span>有效 / 缺失 <strong>' + summary.evaluable + ' / ' + summary.missing + '</strong></span><span>超额收益 <strong>' + formatPct(summary.average === null || benchmarkReturn === null ? null : summary.average - benchmarkReturn, true) + '</strong></span></div></header>'
        + renderComparisonTable(rows, benchmarkReturn, false, sortState) + (missing.length ? '<h3>缺失数据</h3>' + renderComparisonTable(missing, benchmarkReturn, true, sortState) : '');
      var detail = mount.querySelector('#comparisonDetail');
      Array.prototype.forEach.call(detail.querySelectorAll('[data-comparison-sort]'), function (button) {
        button.addEventListener('click', function () {
          var key = button.getAttribute('data-comparison-sort');
          if (sortState.key === key) {
            sortState.direction = sortState.direction === 'desc' ? 'asc' : 'desc';
          } else {
            sortState.key = key;
            sortState.direction = comparisonSortDirection(key);
          }
          showDetail(summary.view);
        });
      });
      var sortSelect = detail.querySelector('[data-comparison-sort-select]');
      if (sortSelect) {
        sortSelect.addEventListener('change', function () {
          sortState.key = sortSelect.value;
          sortState.direction = comparisonSortDirection(sortState.key);
          showDetail(summary.view);
        });
      }
      var directionButton = detail.querySelector('[data-comparison-sort-direction]');
      if (directionButton) {
        directionButton.addEventListener('click', function () {
          sortState.direction = sortState.direction === 'desc' ? 'asc' : 'desc';
          showDetail(summary.view);
        });
      }
    }
    Array.prototype.forEach.call(buttons, function (button) { button.addEventListener('click', function () { showDetail(button.getAttribute('data-comparison-view')); }); });
    showDetail(summaries[0] && summaries[0].view);
  }

  function renderComparisonTable(rows, benchmarkReturn, missing, sortState) {
    var displayRows = missing ? rows : comparisonSortRows(rows, sortState && sortState.key, sortState && sortState.direction);
    var sortableHeaders = missing ? '<th>当时排名/决策</th><th>源收盘</th><th>对比价</th><th>实际涨跌</th>'
      : comparisonSortHeader('当时排名/决策', 'rank', sortState)
        + comparisonSortHeader('源收盘', 'sourcePrice', sortState)
        + comparisonSortHeader('对比价', 'targetPrice', sortState)
        + comparisonSortHeader('实际涨跌', 'actual', sortState);
    var excessHeader = missing ? '<th>超额收益</th>' : comparisonSortHeader('超额收益', 'excess', sortState);
    return (missing ? '' : comparisonSortMobileControls(sortState)) + '<div class="comparison-table-wrap"><table class="comparison-table"><thead><tr><th>股票</th><th>行业</th>' + sortableHeaders + '<th>沪深300</th>' + excessHeader + '</tr></thead><tbody>' + displayRows.map(function (row) {
      var item = row.item || {};
      return '<tr><td data-label="股票">' + escapeHtml(item.name || item.code || '--') + '<small>' + escapeHtml(item.code || '') + '</small></td><td data-label="行业">' + escapeHtml(item.industry || '--') + '</td><td data-label="当时排名/决策">' + escapeHtml((item.rank || '--') + ' / ' + (item.decision || item.decision_code || '--')) + '</td><td data-label="源收盘">' + formatNumber(row.sourcePrice) + '</td><td data-label="对比价">' + formatNumber(row.targetPrice) + '</td><td data-label="实际涨跌" class="' + (row.actual !== null && row.actual >= 0 ? 'is-up' : 'is-down') + '">' + (row.missingReason ? '<span class="comparison-missing-reason">' + escapeHtml(row.missingReason) + '</span>' : formatPct(row.actual, true)) + '</td><td data-label="沪深300">' + formatPct(benchmarkReturn, true) + '</td><td data-label="超额收益">' + formatPct(row.excess, true) + '</td></tr>';
    }).join('') + (displayRows.length ? '' : '<tr><td colspan="8">' + (missing ? '缺少源收盘或对比价' : '暂无可比对数据') + '</td></tr>') + '</tbody></table></div>';
  }

  function initComparisonSummary() {
    if (!nodes.shell || !window.fetch || document.getElementById('comparisonSummary')) return;
    var auxCenter = nodes.shell.querySelector('.aux-center');
    var section = document.createElement('section');
    section.id = 'comparisonSummary';
    section.className = 'report-comparison-summary';
    section.innerHTML = '<header><div><h2>历史正式策略盘中追踪</h2><p>仅对正式策略刷新当前行情；这是盘中追踪，不是 T+N 收盘评价。</p></div><a href="' + (isArchiveReportPath(window.location.pathname) ? '../compare/' : 'compare/') + '">进入完整比对</a></header><div class="comparison-summary-body" role="status" aria-live="polite" aria-atomic="true">正在读取历史报告索引…</div>';
    if (auxCenter && auxCenter.parentNode) {
      auxCenter.parentNode.insertBefore(section, auxCenter);
    } else {
      nodes.shell.appendChild(section);
    }
    var body = section.querySelector('.comparison-summary-body');
    window.fetch(getComparisonIndexUrl()).then(function (resp) {
      if (!resp || !resp.ok) throw new Error('索引加载失败');
      return resp.json();
    }).then(function (index) {
      var dates = asArray(index && index.dates).slice(-26);
      var pageDate = normalizeString(state.data && state.data.date);
      var pageIndex = dates.indexOf(pageDate);
      var sourceDate = pageIndex > 0 ? dates[pageIndex - 1] : (dates.length > 1 ? dates[dates.length - 2] : dates[dates.length - 1]);
      var report = index.reports && index.reports[sourceDate];
      if (!report) throw new Error('缺少昨日报告');
      body.innerHTML = '<div class="comparison-summary-toolbar"><span>源报告日 ' + escapeHtml(comparisonDateLabel(index, sourceDate)) + '</span><button id="comparisonSummaryRefresh" type="button">刷新对比价</button><small>尚未刷新当前行情</small></div><div class="comparison-summary-results"><div class="comparison-summary-wait">点击“刷新对比价”后计算。</div></div>';
      var button = body.querySelector('#comparisonSummaryRefresh');
      var status = body.querySelector('small');
      var results = body.querySelector('.comparison-summary-results');
      button.addEventListener('click', function () {
        var codeMap = {};
        Object.keys(report.views || {}).forEach(function (view) {
          asArray(report.views[view]).forEach(function (item) { if (item && item.code) codeMap[item.code] = true; });
        });
        var codes = Object.keys(codeMap);
        var apiBase = getTop10ApiBase();
        if (!apiBase) { status.textContent = '当前行情接口未配置'; return; }
        button.disabled = true;
        status.textContent = '正在刷新当前行情…';
        window.fetch(apiBase + '/api/quotes/current', {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ codes: codes }),
        }).then(function (resp) {
          if (!resp || !resp.ok) throw new Error('行情请求失败');
          return resp.json();
        }).then(function (payload) {
          renderComparisonSummaryResults(report, payload || {}, results);
          status.textContent = '已刷新：' + formatTop10Date(payload && payload.quoted_at || '');
        }).catch(function () { status.textContent = '当前行情刷新失败'; }).finally(function () { button.disabled = false; });
      });
    }).catch(function () { body.innerHTML = '<div class="comparison-summary-wait">暂无可用的历史榜单索引。</div>'; });
  }

  function renderComparisonSummaryResults(report, quoteData, mount) {
    var quoteMap = {};
    asArray(quoteData.quotes || quoteData.items || []).forEach(function (quote) { if (quote && quote.code) quoteMap[quote.code] = quote.current_price; });
    var benchmarkReturn = comparisonReturn(report.benchmark && report.benchmark.close, quoteData.benchmark && quoteData.benchmark.current_price);
    var summaries = Object.keys(report.views || {}).filter(isComparablePerformanceView).map(function (view) {
      var rows = asArray(report.views[view]).map(function (item) {
        var actual = comparisonReturn(report.prices && report.prices[item.code], quoteMap[item.code]);
        return { item: item, actual: actual };
      });
      return comparisonSummary(view, rows);
    });
    mount.innerHTML = '<div class="comparison-summary-benchmark">' + (benchmarkReturn === null ? '指数数据缺失' : '沪深300 ' + formatPct(benchmarkReturn, true)) + '</div><div class="comparison-summary-grid">' + summaries.map(function (summary) {
      var excess = summary.average === null || benchmarkReturn === null ? null : summary.average - benchmarkReturn;
      return '<article><span>' + escapeHtml(comparisonViewLabel(summary.view)) + '</span><strong class="' + (summary.average !== null && summary.average >= 0 ? 'is-up' : 'is-down') + '">' + formatPct(summary.average, true) + '</strong><small>超额 ' + formatPct(excess, true) + ' · 有效 ' + summary.evaluable + ' / 缺失 ' + summary.missing + '</small></article>';
    }).join('') + '</div>';
  }

  function initComparisonPage() {
    var root = document.getElementById('comparisonApp');
    if (!root) return;
    if (!window.fetch) { root.innerHTML = '<div class="comparison-empty">当前环境不支持加载历史索引。</div>'; return; }
    window.fetch(getComparisonIndexUrl()).then(function (resp) {
      if (!resp || !resp.ok) throw new Error('索引加载失败');
      return resp.json();
    }).then(function (index) { renderComparisonPage(index || {}, root); }).catch(function () {
      root.innerHTML = '<div class="comparison-empty">暂无可用的历史报告索引。</div>';
    });
  }

  function isComparisonPage() {
    var bootstrap = getBootstrap();
    var path = normalizeString(window.location && window.location.pathname);
    return bootstrap.pageMode === 'comparison' || /\/compare\/?$/.test(path) || !!document.getElementById('comparisonApp');
  }

  window.initComparisonSummary = initComparisonSummary;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      if (isComparisonPage()) initComparisonPage(); else initReportV2();
    });
  } else if (isComparisonPage()) {
    initComparisonPage();
  } else {
    initReportV2();
  }
})();
