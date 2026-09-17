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
    highlights: '看点 Top10：跨池混合优先观察榜，保留原名次。研究阅读顺序，不代表次日收益排名；请结合身份标签、共振标签和操作状态判断。',
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
  var CHART_EMPTY_TEXT = '无法展示可验证 K 线：本期未提供真实日 K 数据；推荐原因和来源仍保留。';
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
    chartLayerSwitcher: null,
    detailCandidateKey: '',
    detailTarget: null,
    detailRenderToken: 0,
    candidateSelectionVersion: 0,
    activeCandidateKey: '',
    reviewHistoryRequestToken: 0,
    sentimentChartInstance: null,
    chartLayer: 'decision',
    chartOverlays: { decision: false, structure: false, trend: false },
    chartWindowMode: '20',
    chartScopeKey: '',
    chartZoomWindow: null,
    chartZoomMode: '',
    rawPoolCandidates: null,
    drawerReturnFocus: null,
    drawerReturnCode: '',
    drawerBackgroundState: [],
    candidateQuery: '',
    decisionStatusFilter: '',
    sectorFilter: '',
    sectorFilterCode: '',
    sectorFilterRefs: [],
    candidateLimit: 20,
    quickComparison: {
      selectedKeys: [],
      selectedItems: {},
      message: '',
      max: 3,
    },
    hotspot: {
      model: null,
      mode: 'map',
      sortMode: 'count',
      query: '',
      theme: '',
      onlySystem: false,
      visibleLimit: 30,
      showAllGroups: false,
      expandedGroups: {},
      returnFocus: null,
    },
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
    nextdayResearch: {
      requestToken: 0,
      reportDate: '',
      controller: null,
      timeoutTimer: null,
      hashListenerBound: false,
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
    watchlistSelectedCode: '',
  };

  var nodes = {
    shell: null,
    headerTitle: null,
    headerSubtitle: null,
    headerMetrics: null,
    primaryTabs: null,
    todayDecisionView: null,
    researchValidationView: null,
    nextdayResearchSection: null,
    nextdayResearch: null,
    marketEvidence: null,
    marketDecisionBar: null,
    marketDecisionSummary: null,
    sectorStrip: null,
    supportingStack: null,
    personalWatchlistStack: null,
    researchStack: null,
    tabs: null,
    description: null,
    workspaceBody: null,
    candidateList: null,
    candidateEvidenceComparison: null,
    decisionChanges: null,
    candidateQuickComparison: null,
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
    marketHotspot: null,
    hotspotDialog: null,
    hotspotDialogContent: null,
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

  function getCandidateReferencePriceForCalculation(rec) {
    var record = rec || {};
    var contract = getCandidateReferenceContract(record);
    var contractReference = safeNumber(contract.reference_price, null);
    var status = referencePurposeStatus(record, contract);
    var basis = contract.price_basis || contract.priceBasis;
    var basisText = basis && typeof basis === 'object'
      ? (basis.adjustment || basis.basis || basis.id || '') : normalizeString(basis).trim().toLowerCase();
    var basisBlocked = ['unknown', 'unverified', 'missing', 'conflict'].indexOf(
      normalizeString(basisText).trim().toLowerCase()
    ) !== -1;
    if (contractReference !== null) {
      if (!isReferencePurposeVerified(status) || basisBlocked) return null;
      return contractReference;
    }
    // A declared contract without a reference is incomplete.  Its purpose
    // metadata must not authorize the record-level raw reference as a proxy.
    if (Object.keys(contract).length > 0) return null;
    if (status !== 'verified' && status !== 'formal') return null;
    return getCandidateReferencePriceFromRecord(record);
  }

  function getCandidateReferenceContract(rec) {
    var record = rec && typeof rec === 'object' ? rec : {};
    var workbench = record.workbench_item && typeof record.workbench_item === 'object'
      ? record.workbench_item : record;
    return (workbench.formal_decision_contract && typeof workbench.formal_decision_contract === 'object'
      ? workbench.formal_decision_contract
      : (workbench.contract && typeof workbench.contract === 'object'
        ? workbench.contract
        : (record.formal_decision_contract && typeof record.formal_decision_contract === 'object'
          ? record.formal_decision_contract
          : (record.contract && typeof record.contract === 'object' ? record.contract : {}))));
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

  function candidateSnapshotIdentity(dataOrId) {
    if (isString(dataOrId)) return normalizeString(dataOrId).trim();
    var source = dataOrId && typeof dataOrId === 'object'
      ? dataOrId : (state.data || {});
    var bootstrap = getBootstrap();
    return normalizeString(
      source.snapshot_id || source.content_hash || bootstrap.snapshotId
        || source.date || bootstrap.pageDate
    ).trim() || 'snapshot-unknown';
  }

  function candidateIdentityKey(item, viewKey, snapshotId) {
    return [
      candidateSnapshotIdentity(snapshotId || state.data),
      normalizeString(viewKey || state.currentView).trim(),
      toCodeKey(item && item.code),
    ].join('::');
  }

  function beginCandidateSelection(item, snapshotId) {
    state.candidateSelectionVersion = Number(state.candidateSelectionVersion || 0) + 1;
    state.activeItem = item || null;
    state.activeCandidateKey = candidateIdentityKey(item, state.currentView, snapshotId);
    return {
      version: state.candidateSelectionVersion,
      key: state.activeCandidateKey,
      code: toCodeKey(item && item.code),
      snapshot_id: candidateSnapshotIdentity(snapshotId || state.data),
    };
  }

  function isCurrentCandidateSelection(token, item, snapshotId) {
    if (!token || token.version !== state.candidateSelectionVersion) return false;
    var key = candidateIdentityKey(item, state.currentView, snapshotId);
    return token.key === key && state.activeCandidateKey === key;
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
    var value = decision && decision.total_score;
    if (!isRecommendationEvidenceFiniteNumber(value)) return null;
    var score = Number(value);
    return score >= 0 && score <= 100 ? score : null;
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
    var length = Math.min(dates.length, opens.length, highs.length, lows.length, closes.length);
    if (length < 2) return false;
    for (var index = 0; index < length; index += 1) {
      var date = dates[index];
      var values = [opens[index], highs[index], lows[index], closes[index]];
      if (typeof date !== 'string' || !date.trim()) return false;
      if (!values.every(function (value) {
        return isRecommendationEvidenceFiniteNumber(value) && Number(value) > 0;
      })) return false;
      if (Number(highs[index]) < Number(lows[index])) return false;
    }
    return true;
  }

  function getChartScopeKey(raw, workspaceItem) {
    var source = raw && typeof raw === 'object' ? raw : {};
    var item = workspaceItem && typeof workspaceItem === 'object' ? workspaceItem : {};
    var bootstrap = getBootstrap();
    var decisionWorkbench = bootstrap.decisionWorkbench && typeof bootstrap.decisionWorkbench === 'object'
      ? bootstrap.decisionWorkbench : {};
    var identitySources = [
      item,
      item.workbench_item,
      item.candidate,
      source,
      source.workbench_item,
      decisionWorkbench,
      bootstrap.recommendationEvidence,
    ].filter(function (value) { return value && typeof value === 'object'; });
    var identityParts = [];
    identitySources.forEach(function (value) {
      ['snapshot_id', 'payload_hash', 'phase', 'version'].forEach(function (field) {
        var fieldValue = normalizeString(value[field]).trim();
        if (fieldValue) identityParts.push(field + ':' + fieldValue);
      });
      if (value.snapshot && typeof value.snapshot === 'object') {
        ['id', 'snapshot_id', 'payload_hash', 'phase', 'version'].forEach(function (field) {
          var nestedValue = normalizeString(value.snapshot[field]).trim();
          if (nestedValue) identityParts.push('snapshot.' + field + ':' + nestedValue);
        });
      }
    });
    var dates = asArray(source.dates);
    var reportDate = item.report_date || item.reportDate || (item.workbench_item || {}).report_date
      || source.report_date || source.reportDate || decisionWorkbench.report_date || '';
    if (!reportDate && state.data && typeof state.data === 'object') {
      reportDate = state.data.date || state.data.report_date || '';
    }
    return [
      toCodeKey(item.code || (item.workbench_item || {}).code || source.code || ''),
      identityParts.filter(function (value, index, values) {
        return values.indexOf(value) === index;
      }).join(','),
      normalizeString(reportDate),
      dates.length,
      dates.length ? normalizeString(dates[0]) : '',
      dates.length ? normalizeString(dates[dates.length - 1]) : '',
    ].join('|');
  }

  function normalizeChartWindowMode(mode) {
    var value = normalizeString(mode).trim().toLowerCase();
    return ['20', '60', 'all', 'signal'].indexOf(value) === -1 ? '20' : value;
  }

  function readChartZoomWindow(instance) {
    if (!instance || typeof instance.getOption !== 'function') {
      return state.chartZoomWindow && typeof state.chartZoomWindow === 'object'
        ? Object.assign({}, state.chartZoomWindow) : null;
    }
    try {
      var option = instance.getOption() || {};
      var zooms = asArray(option.dataZoom);
      var zoom = zooms.find(function (entry) {
        return entry && (entry.startValue !== undefined || entry.endValue !== undefined);
      });
      if (!zoom) return null;
      return {
        startValue: zoom.startValue,
        endValue: zoom.endValue,
      };
    } catch (error) {
      return state.chartZoomWindow && typeof state.chartZoomWindow === 'object'
        ? Object.assign({}, state.chartZoomWindow) : null;
    }
  }

  function chartInstanceMatchesMount(instance, mount) {
    if (!instance || !mount) return false;
    if (mount.isConnected === false) return false;
    if (typeof instance.getDom !== 'function') return true;
    try {
      return instance.getDom() === mount;
    } catch (error) {
      return false;
    }
  }

  function chartWindowValues(xAxis, mode, markPoints) {
    var dates = asArray(xAxis);
    if (!dates.length) return { startValue: undefined, endValue: undefined };
    var normalizedMode = normalizeChartWindowMode(mode);
    var startIndex = 0;
    var endIndex = dates.length - 1;
    if (normalizedMode === '20' || normalizedMode === '60') {
      var count = Number(normalizedMode);
      startIndex = Math.max(0, dates.length - count);
    } else if (normalizedMode === 'signal') {
      var latestSignalIndex = -1;
      asArray(markPoints).forEach(function (point) {
        var coord = asArray(point && point.coord);
        var index = dates.indexOf(coord[0]);
        if (index >= latestSignalIndex && index >= 0) latestSignalIndex = index;
      });
      if (latestSignalIndex >= 0) {
        startIndex = Math.max(0, latestSignalIndex - 10);
        endIndex = Math.min(dates.length - 1, latestSignalIndex + 10);
      } else {
        startIndex = Math.max(0, dates.length - 20);
      }
    }
    return { startValue: dates[startIndex], endValue: dates[endIndex] };
  }

  function chartVolumeMetadata(record) {
    var source = record && typeof record === 'object' ? record : {};
    var volumes = asArray(source.volumes);
    var units = asArray(source.volume_units);
    var rawUnits = asArray(source.volume_raw_units);
    var sources = asArray(source.volume_sources);
    var uniqueValues = function (values) {
      return values.map(function (value) { return normalizeString(value).trim(); })
        .filter(function (value, index, all) { return value && all.indexOf(value) === index; });
    };
    var unitValues = uniqueValues(units);
    var rawUnitValues = uniqueValues(rawUnits);
    var sourceValues = uniqueValues(sources);
    var unit = normalizeString(source.volume_unit || source.volume_display_unit || '').trim();
    var rawUnit = normalizeString(source.volume_raw_unit || '').trim();
    var provenance = normalizeString(source.volume_source || '').trim();
    var reasons = [];
    if (!volumes.length) reasons.push('本期未输出成交量序列');
    if (volumes.length && (units.length !== volumes.length
      || rawUnits.length !== volumes.length || sources.length !== volumes.length)) {
      reasons.push('成交量序列、单位或来源长度不一致');
    }
    if (unitValues.length > 1) {
      unit = '混合：' + unitValues.join(' / ');
      reasons.push('单位混用');
    } else if (!unit && unitValues.length) {
      unit = unitValues[0];
    }
    if (rawUnitValues.length > 1) {
      rawUnit = '混合：' + rawUnitValues.join(' / ');
      reasons.push('原单位冲突');
    } else if (!rawUnit && rawUnitValues.length) {
      rawUnit = rawUnitValues[0];
    }
    if (sourceValues.length > 1) {
      provenance = '混合：' + sourceValues.join(' / ');
      reasons.push('来源冲突');
    } else if (!provenance && sourceValues.length) {
      provenance = sourceValues[0];
    }
    var quality = source.volume_quality && typeof source.volume_quality === 'object'
      ? source.volume_quality : {};
    var dataStatus = source._data_status && typeof source._data_status === 'object'
      ? source._data_status : {};
    var status = normalizeString(
      source.volume_status || source.volume_evidence_status || quality.status || dataStatus.volume_status || ''
    ).trim().toLowerCase();
    var explicitReason = normalizeString(
      source.volume_reason || source.volume_unavailable_reason || source.volume_conflict_reason
      || quality.reason || dataStatus.reason || ''
    ).trim();
    if (explicitReason) reasons.push(explicitReason);
    if (source.volume_stale === true || source.volume_expired === true || quality.stale === true
        || quality.expired === true || dataStatus.stale === true || status === 'stale') {
      reasons.push('成交量数据已过期');
    }
    if (source.volume_conflict === true || quality.conflict === true
        || ['conflict', 'mixed'].indexOf(status) !== -1
        || /^(mixed|conflict)$/i.test(unit) || /^(mixed|conflict)$/i.test(rawUnit)
        || /^(mixed|conflict)$/i.test(provenance)) {
      reasons.push('成交量单位或来源冲突');
    }
    return {
      unit: unit,
      rawUnit: rawUnit,
      source: provenance,
      reasons: reasons.filter(function (value, index, values) {
        return value && values.indexOf(value) === index;
      }),
    };
  }

  function chartVolumeStatusHtml(record, projection) {
    var metadata = chartVolumeMetadata(record);
    var status = projection && projection.status;
    var summary = status === 'partial'
      ? '部分成交量口径未核验，缺口已留空'
      : '成交量证据未核验，价格图保持可用';
    var criticalReasons = metadata.reasons.filter(function (reason) {
      return /过期|冲突|混用/.test(reason);
    });
    if (criticalReasons.length) summary += ' · ' + criticalReasons.join('；');
    var sequence = status === 'partial'
      ? '部分序列可用，其他行保留缺口'
      : '未提供可核验序列';
    var rawUnitDetail = metadata.rawUnit && metadata.rawUnit !== metadata.unit
      ? ['原单位：', metadata.rawUnit].join('') : '';
    var details = [
      '单位：' + (metadata.unit || metadata.rawUnit || '未核验'),
      rawUnitDetail,
      '来源：' + (metadata.source || '未提供'),
      '序列：' + sequence,
    ].filter(Boolean).concat(metadata.reasons.map(function (reason) { return '原因：' + reason; }));
    return '<details class="chart-layer-status" data-chart-quantity-status="'
      + escapeHtml(status || 'missing') + '"><summary>' + escapeHtml(summary)
      + '</summary><span>' + details.map(function (detail) {
        return escapeHtml(detail);
      }).join(' · ') + '</span></details>';
  }

  function chartMaDeclaration(record, key) {
    var source = record && typeof record === 'object' ? record : {};
    var declarations = source.chart_ma && typeof source.chart_ma === 'object'
      ? source.chart_ma : {};
    var value = declarations[key];
    if (!value && declarations.fields && typeof declarations.fields === 'object') {
      value = declarations.fields[key];
    }
    if (!value && declarations.series && typeof declarations.series === 'object') {
      value = declarations.series[key];
    }
    if (!value && Array.isArray(declarations)) {
      value = declarations.find(function (item) {
        return item && (item.key === key || item.name === key);
      });
    }
    return value && typeof value === 'object' ? value : null;
  }

  function chartMaDeclarationText(record, key) {
    var declaration = chartMaDeclaration(record, key);
    if (!declaration) return '';
    var parts = [];
    if (declaration.derived === true || normalizeString(declaration.source).trim() === 'derived') {
      parts.push('展示计算');
    } else if (normalizeString(declaration.source).trim()) {
      parts.push(normalizeString(declaration.source).trim());
    }
    if (normalizeString(declaration.algorithm).trim()) {
      parts.push(normalizeString(declaration.algorithm).trim());
    }
    if (declaration.window !== undefined && declaration.window !== null && declaration.window !== '') {
      parts.push('窗口 ' + normalizeString(declaration.window).trim());
    }
    var basis = declaration.price_basis || declaration.priceBasis;
    if (normalizeString(basis).trim()) parts.push('价基 ' + normalizeString(basis).trim());
    var asOf = declaration.as_of || declaration.asOf || declaration.latest_date;
    if (normalizeString(asOf).trim()) parts.push('截至 ' + normalizeString(asOf).trim());
    return parts.length ? key.toUpperCase() + '：' + parts.join(' · ') : '';
  }

  function chartMaStatusHtml(record) {
    var keys = ['ema5', 'ma5', 'ma10', 'ema20', 'ma20'];
    var text = keys.map(function (key) {
      return chartMaDeclarationText(record, key);
    }).filter(Boolean);
    return text.length
      ? '<span class="chart-layer-status" data-chart-ma-status="declared">均线：'
        + escapeHtml(text.join('；')) + '</span>' : '';
  }

  function mergeChartCandidate(primary, chartSource) {
    // A ref identifies one report source.  Do not splice another pool's
    // OHLC/quantity data into it, even when the dates happen to match.
    return primary || null;
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
    var pool = normalizeString(ref.pool || ref.source_pool || '').trim();
    if (!pool) return null;
    var explicit = getWorkspaceDataFromRef(pool);
    if (!explicit || !explicit.length) return null;
    return explicit.find(function (item) {
      return toCodeKey(item && item.code) === targetCode;
    }) || null;
  }

  function setTextNode(el, value) {
    if (!el) return;
    el.innerHTML = escapeHtml(value);
  }

  function getDecisionWorkbench(data) {
    var report = data || state.data || {};
    var bootstrap = getBootstrap();
    var value = bootstrap.decisionWorkbench;
    var expected = normalizeString(report.date || bootstrap.pageDate);
    return value && value.schema_version === 'decision-workbench-v1'
      && value.phase === 'formal' && value.report_date === expected
      && Array.isArray(value.items) ? value : null;
  }

  function isDecisionView(key) {
    return normalizeString(key).indexOf('decision_') === 0;
  }

  function primaryDisplaySecurityIdentity(item) {
    var value = item && typeof item === 'object' ? item : {};
    var candidate = value.candidate && typeof value.candidate === 'object'
      ? value.candidate : {};
    var direct = normalizeString(
      value.instrument_id || value.security_id
        || candidate.instrument_id || candidate.security_id
    ).trim().toUpperCase().replace(/[^A-Z0-9]/g, '');
    if (/^(SH|SZ|BJ)\d{6}$/.test(direct)) return direct;
    var rawCode = normalizeString(value.code || candidate.code).trim().toUpperCase();
    var prefixed = rawCode.replace(/[^A-Z0-9]/g, '');
    if (/^(SH|SZ|BJ)\d{6}$/.test(prefixed)) return prefixed;
    var codeMatch = rawCode.match(/(\d{6})$/);
    var code = codeMatch ? codeMatch[1] : '';
    var exchange = normalizeString(
      value.exchange || value.market || candidate.exchange || candidate.market
    ).trim().toUpperCase();
    if (exchange.indexOf('SH') === 0) exchange = 'SH';
    else if (exchange.indexOf('SZ') === 0) exchange = 'SZ';
    else if (exchange.indexOf('BJ') === 0) exchange = 'BJ';
    else exchange = '';
    if (!exchange && code) {
      if (/^6/.test(code)) exchange = 'SH';
      else if (/^(0|3)/.test(code)) exchange = 'SZ';
      else if (/^(4|8|92)/.test(code)) exchange = 'BJ';
    }
    if (code) return (exchange || 'CODE') + code;
    var id = normalizeString(value.id).trim();
    return id ? 'ID:' + id : '';
  }

  function poolHitSourceDescriptor(identifier) {
    var raw = identifier && typeof identifier === 'object'
      ? identifier.strategy_id || identifier.view || identifier.pool
        || identifier.source || identifier.id
      : identifier;
    raw = normalizeString(raw).trim();
    if (!raw) return null;
    var key = raw.toLowerCase();
    if (key.indexOf('decision_') === 0) return { type: 'ignored', raw: raw };
    var pools = {
      main: 'main',
      picks_fusion: 'main',
      h4_t3: 'h4',
      h4_t3_pool: 'h4',
      acceleration: 'acceleration',
      next_day_boom: 'acceleration',
      luojie: 'luojie',
      luojie_pool: 'luojie',
      confirming: 'confirming',
      startup_watchlist: 'confirming',
      baseline: 'baseline',
      picks_pure: 'baseline',
    };
    var collections = {
      highlights: { key: 'highlights', label: '看点榜' },
      observation_top5: { key: 'observation-top5', label: '观察Top5' },
      observation_watchlist: { key: 'observation-top5', label: '观察Top5' },
      growth_quality: { key: 'growth-quality', label: '高弹性观察' },
    };
    if (Object.prototype.hasOwnProperty.call(pools, key)) {
      return { type: 'pool', key: pools[key], raw: raw };
    }
    if (Object.prototype.hasOwnProperty.call(collections, key)) {
      return { type: 'collection', key: collections[key].key,
        label: collections[key].label, raw: raw };
    }
    return { type: 'unknown', raw: raw };
  }

  function poolHitIdentity(item) {
    var value = item && typeof item === 'object' ? item : {};
    var identity = primaryDisplaySecurityIdentity(value);
    if (identity) return identity;
    var summary = value.summary && typeof value.summary === 'object'
      ? value.summary : {};
    return primaryDisplaySecurityIdentity({
      instrument_id: summary.instrument_id,
      security_id: summary.security_id,
      code: value.code || summary.code,
      exchange: value.exchange || summary.exchange,
      market: value.market || summary.market,
    });
  }

  function poolHitCurrentSnapshotRecord(item) {
    var outer = item && typeof item === 'object' ? item : {};
    var direct = outer.workbench_item && typeof outer.workbench_item === 'object'
      ? outer.workbench_item
      : (outer.__workbench_item && typeof outer.__workbench_item === 'object'
        ? outer.__workbench_item : outer);
    var projection = getDecisionWorkbench();
    if (!projection) return direct;
    var values = direct === outer ? [outer] : [outer, direct];
    var mismatch = values.some(function (value) {
      var reportDate = normalizeString(value.report_date || value.date).trim();
      var phase = normalizeString(value.phase).trim();
      var snapshotId = normalizeString(value.snapshot_id).trim();
      return (reportDate && reportDate !== normalizeString(projection.report_date).trim())
        || (phase && phase !== normalizeString(projection.phase).trim())
        || (snapshotId && projection.snapshot_id
          && snapshotId !== normalizeString(projection.snapshot_id).trim());
    });
    if (mismatch) return direct;
    var identity = poolHitIdentity(direct) || poolHitIdentity(outer);
    if (!identity) return direct;
    return asArray(projection.items).find(function (candidate) {
      return poolHitIdentity(candidate) === identity;
    }) || direct;
  }

  function getPoolHitSummary(item) {
    try {
      var record = poolHitCurrentSnapshotRecord(item);
      var pools = [];
      var collections = [];
      var unknown = [];
      var poolSeen = Object.create(null);
      var collectionSeen = Object.create(null);
      var unknownSeen = Object.create(null);
      function appendIdentifier(identifier) {
        var descriptor = poolHitSourceDescriptor(identifier);
        if (!descriptor || descriptor.type === 'ignored') return;
        if (descriptor.type === 'pool') {
          if (Object.prototype.hasOwnProperty.call(poolSeen, descriptor.key)) return;
          poolSeen[descriptor.key] = true;
          pools.push({ key: descriptor.key, label: descriptor.key });
          return;
        }
        if (descriptor.type === 'collection') {
          if (Object.prototype.hasOwnProperty.call(collectionSeen, descriptor.key)) return;
          collectionSeen[descriptor.key] = true;
          collections.push({ key: descriptor.key, label: descriptor.label });
          return;
        }
        if (!Object.prototype.hasOwnProperty.call(unknownSeen, descriptor.raw)) {
          unknownSeen[descriptor.raw] = true;
          unknown.push(descriptor.raw);
        }
      }
      function appendRef(ref) {
        var value = ref && typeof ref === 'object' ? ref : {};
        appendIdentifier(value.pool || value.source_pool || value.view);
      }
      var strategies = asArray(record && record.strategy_results);
      strategies.forEach(function (strategy) {
        var value = strategy && typeof strategy === 'object' ? strategy : {};
        appendIdentifier(value.strategy_id || value.view || value.source);
        appendRef(value.ref);
        appendRef(value.candidate_ref);
        appendRef(value.candidate && value.candidate.ref);
      });
      asArray(record && record.source_refs).forEach(function (sourceRef) {
        if (!sourceRef || typeof sourceRef !== 'object') {
          appendIdentifier(sourceRef);
          return;
        }
        appendIdentifier(sourceRef.view || sourceRef.strategy_id || sourceRef.source);
        appendRef(sourceRef.ref);
      });
      asArray(record && record.sources).forEach(function (source) {
        appendIdentifier(source);
        if (source && typeof source === 'object') appendRef(source.ref);
      });
      appendRef(record && record.ref);
      appendRef(record && record.candidate && record.candidate.ref);

      var formalMain = strategies.some(function (strategy) {
        var value = strategy && typeof strategy === 'object' ? strategy : {};
        var identifiers = [
          value.strategy_id,
          value.ref && value.ref.pool,
          value.candidate_ref && value.candidate_ref.pool,
          value.candidate && value.candidate.ref && value.candidate.ref.pool,
        ];
        return identifiers.some(function (identifier) {
          var descriptor = poolHitSourceDescriptor(identifier);
          return descriptor && descriptor.type === 'pool' && descriptor.key === 'main';
        }) && isFormalStrategyResult(value);
      });
      if (!formalMain) {
        var directRefs = [
          record && record.ref && record.ref.pool,
          record && record.candidate && record.candidate.ref
            && record.candidate.ref.pool,
        ];
        var directMain = directRefs.some(function (identifier) {
          var descriptor = poolHitSourceDescriptor(identifier);
          return descriptor && descriptor.type === 'pool' && descriptor.key === 'main';
        });
        var role = normalizeString(record && record.role).trim();
        var semantics = normalizeString(record && record.action_semantics).trim();
        var explicitlyResearch = role === 'research' || role === 'baseline'
          || semantics === 'watch_only' || semantics === 'upstream_only'
          || (record && record.is_formal_recommendation === false);
        formalMain = directMain && !explicitlyResearch
          && isFormalWorkbenchItem(record);
      }
      var labels = {
        main: formalMain ? '主推策略' : '融合候选',
        h4: 'H4',
        acceleration: '加速池',
        luojie: '罗姐池',
        confirming: '等确认',
        baseline: '基础候选·上游',
      };
      pools.forEach(function (pool) { pool.label = labels[pool.key] || pool.key; });
      var count = pools.length;
      var badgeText;
      var badgeTone;
      if (unknown.length && count) {
        badgeText = '已知命中' + count + '池 · 有来源待识别';
        badgeTone = 'partial';
      } else if (unknown.length) {
        badgeText = '有来源待识别';
        badgeTone = 'unknown';
      } else if (!count) {
        badgeText = '来源待补';
        badgeTone = 'missing';
      } else {
        badgeText = '命中' + count + '池';
        badgeTone = count >= 3 ? 'many' : (count === 2 ? 'two' : 'one');
      }
      return {
        count: count,
        badgeText: badgeText,
        badgeTone: badgeTone,
        status: badgeTone === 'partial' ? 'partial'
          : (badgeTone === 'unknown' ? 'unknown'
            : (badgeTone === 'missing' ? 'missing' : 'available')),
        reasonCode: '',
        pools: pools,
        collections: collections,
        unknown: unknown,
      };
    } catch (error) {
      return {
        count: 0,
        badgeText: '来源待补',
        badgeTone: 'missing',
        status: 'degraded',
        reasonCode: 'source_summary_unavailable',
        pools: [],
        collections: [],
        unknown: [],
      };
    }
  }

  function renderPoolHitSummaryValue(summary, placement) {
    var value = summary && typeof summary === 'object' ? summary : {
      badgeText: '来源待补', badgeTone: 'missing',
      status: 'missing', reasonCode: '',
      pools: [], collections: [], unknown: [],
    };
    var context = ['list', 'detail', 'comparison'].indexOf(placement) !== -1
      ? placement : 'list';
    var tags = asArray(value.pools).map(function (pool) {
      return '<span class="pool-hit-tag is-' + escapeHtml(pool.key) + '">'
        + escapeHtml(pool.label) + '</span>';
    }).concat(asArray(value.collections).map(function (entry) {
      return '<span class="pool-hit-tag is-collection">收录：'
        + escapeHtml(entry.label) + '</span>';
    })).concat(asArray(value.unknown).map(function (raw) {
      return '<span class="pool-hit-tag is-unknown">未识别：'
        + escapeHtml(raw) + '</span>';
    })).join('');
    var status = ['available', 'partial', 'unknown', 'missing', 'degraded']
      .indexOf(normalizeString(value.status).trim()) !== -1
      ? normalizeString(value.status).trim() : 'missing';
    var reasonCode = status === 'degraded'
      && value.reasonCode === 'source_summary_unavailable'
      ? 'source_summary_unavailable' : '';
    return '<div class="pool-hit-summary is-' + context + '" aria-label="来源池摘要"'
      + ' data-source-summary-status="' + escapeHtml(status) + '"'
      + (reasonCode ? ' data-source-summary-reason="' + reasonCode + '"' : '') + '>'
      + '<span class="pool-hit-badge is-' + escapeHtml(value.badgeTone || 'missing')
      + '">' + escapeHtml(value.badgeText || '来源待补') + '</span>'
      + (tags ? '<span class="pool-hit-tags">' + tags + '</span>' : '')
      + '</div>';
  }

  function renderPoolHitSummary(item, placement) {
    return renderPoolHitSummaryValue(getPoolHitSummary(item), placement);
  }

  function hotspotCode(value) {
    var raw = normalizeString(value).trim().toUpperCase();
    var match = raw.match(/(?:^|[^0-9])(\d{6})(?:[^0-9]|$)/);
    return match ? match[1] : (/^\d{6}$/.test(raw) ? raw : '');
  }

  function hotspotExchange(code) {
    if (/^6/.test(code)) return 'SH';
    if (/^(0|3)/.test(code)) return 'SZ';
    if (/^(4|8|92)/.test(code)) return 'BJ';
    return '';
  }

  function hotspotNormalizeExchange(value) {
    var raw = normalizeString(value).trim().toUpperCase();
    if (!raw) return '';
    if (/^(SH|SSE|XSHG|上海)/.test(raw)) return 'SH';
    if (/^(SZ|SZSE|XSHE|深圳)/.test(raw)) return 'SZ';
    if (/^(BJ|BSE|XBSE|北京)/.test(raw)) return 'BJ';
    return '';
  }

  function hotspotSecurityIdentity(item) {
    var value = item && typeof item === 'object' ? item : {};
    var candidate = value.candidate && typeof value.candidate === 'object'
      ? value.candidate : {};
    var identities = [];
    var invalidMetadata = false;
    function appendIdentity(identity) {
      if (identity && identities.indexOf(identity) === -1) identities.push(identity);
    }
    [value.instrument_id, value.security_id,
      candidate.instrument_id, candidate.security_id].forEach(function (rawValue) {
      var declared = normalizeString(rawValue).trim();
      if (!declared) return;
      var normalized = declared.toUpperCase().replace(/[^A-Z0-9]/g, '');
      if (!/^(SH|SZ|BJ)\d{6}$/.test(normalized)) {
        invalidMetadata = true;
        return;
      }
      appendIdentity(normalized);
    });
    function appendCodeIdentity(record) {
      var rawCode = record && record.code;
      var code = hotspotCode(rawCode);
      if (!normalizeString(rawCode).trim()) return;
      if (!code) {
        invalidMetadata = true;
        return;
      }
      var declaredExchangeRaw = record.exchange || record.market;
      var declaredExchange = hotspotNormalizeExchange(declaredExchangeRaw);
      if (normalizeString(declaredExchangeRaw).trim() && !declaredExchange) {
        invalidMetadata = true;
        return;
      }
      var derivedExchange = hotspotExchange(code);
      if (declaredExchange && derivedExchange && declaredExchange !== derivedExchange) {
        appendIdentity(declaredExchange + code);
        appendIdentity(derivedExchange + code);
        return;
      }
      appendIdentity((declaredExchange || derivedExchange) + code);
    }
    appendCodeIdentity(value);
    appendCodeIdentity(candidate);
    var code = hotspotCode(value.code || candidate.code);
    var conflict = invalidMetadata || identities.length > 1;
    if (conflict) {
      return {
        identity: '',
        code: code,
        conflict: true,
        quarantineIdentity: identities[0] || '',
        quarantineIdentities: identities,
      };
    }
    return {
      identity: identities[0] || '',
      code: code || (identities[0] ? identities[0].slice(-6) : ''),
      conflict: false,
      quarantineIdentity: '',
      quarantineIdentities: [],
    };
  }

  function hotspotFiniteNumber(value) {
    var number = safeNumber(value, null);
    return number !== null && Number.isFinite(number) ? number : null;
  }

  function hotspotIsoDate(value) {
    var match = normalizeString(value).trim().match(/^(\d{4}-\d{2}-\d{2})/);
    return match ? match[1] : '';
  }

  function hotspotQuoteDateContract(record, reportDate, snapshotDate, snapshotAsOf) {
    var value = record && typeof record === 'object' ? record : {};
    var declarations = [
      { field: 'quote_date', value: value.quote_date },
      { field: 'date', value: value.date },
      { field: 'report_date', value: value.report_date },
      { field: 'as_of', value: value.as_of },
    ].filter(function (entry) {
      return entry.value !== null && entry.value !== undefined
        && normalizeString(entry.value).trim() !== '';
    });
    var dates = [];
    var invalid = false;
    declarations.forEach(function (entry) {
      var date = hotspotIsoDate(entry.value);
      if (!date) {
        invalid = true;
        return;
      }
      if (dates.indexOf(date) === -1) dates.push(date);
    });
    if (invalid || dates.length > 1
        || (dates.length && dates[0] !== snapshotDate)
        || (dates.length && reportDate && dates[0] !== reportDate)) {
      return {
        status: 'date_conflict',
        date: declarations.length ? normalizeString(declarations[0].value).trim() : '',
      };
    }
    var rowAsOf = normalizeString(value.as_of).trim();
    var rowDate = normalizeString(
      value.quote_date || value.date || value.report_date
    ).trim();
    return {
      status: 'available',
      date: rowAsOf || rowDate || snapshotAsOf || snapshotDate,
    };
  }

  function hotspotQuoteTone(value) {
    if (value === null) return 'missing';
    if (value > 0) return 'up';
    if (value < 0) return 'down';
    return 'flat';
  }

  function emptyHotspotPoolSummary() {
    return {
      count: 0,
      badgeText: '来源待补',
      badgeTone: 'missing',
      status: 'missing',
      reasonCode: '',
      pools: [],
      collections: [],
      unknown: [],
    };
  }

  function marketHotspotPoolSummaryBadge(summary) {
    var value = summary && typeof summary === 'object' ? summary : emptyHotspotPoolSummary();
    var count = asArray(value.pools).length;
    var unknown = asArray(value.unknown);
    var badgeText;
    var badgeTone;
    if (unknown.length && count) {
      badgeText = '已知命中' + count + '池 · 有来源待识别';
      badgeTone = 'partial';
    } else if (unknown.length) {
      badgeText = '有来源待识别';
      badgeTone = 'unknown';
    } else if (!count) {
      badgeText = '来源待补';
      badgeTone = 'missing';
    } else {
      badgeText = '命中' + count + '池';
      badgeTone = count >= 3 ? 'many' : (count === 2 ? 'two' : 'one');
    }
    return Object.assign({}, value, {
      count: count,
      badgeText: badgeText,
      badgeTone: badgeTone,
      status: badgeTone === 'partial' ? 'partial'
        : (badgeTone === 'unknown' ? 'unknown'
          : (badgeTone === 'missing' ? 'missing' : 'available')),
    });
  }

  function marketHotspotBlockedSources(health) {
    var aliases = {
      daily_fusion: 'main',
      daily_pure: 'baseline',
    };
    var poolKeys = Object.create(null);
    var rawKeys = Object.create(null);
    asArray((health || {}).blocked_strategies).forEach(function (identifier) {
      var raw = normalizeString(identifier).trim();
      if (!raw) return;
      rawKeys[raw.toLowerCase()] = true;
      var descriptor = poolHitSourceDescriptor(raw);
      var key = descriptor && descriptor.type === 'pool'
        ? descriptor.key : aliases[raw.toLowerCase()];
      if (key) poolKeys[key] = true;
    });
    return { poolKeys: poolKeys, rawKeys: rawKeys };
  }

  function marketHotspotRecordSourceContract(item, blockedSources) {
    var summary = getPoolHitSummary(item);
    var blocked = blockedSources || { poolKeys: {}, rawKeys: {} };
    var originalPools = asArray(summary.pools);
    var pools = originalPools.filter(function (pool) {
      return !blocked.poolKeys[pool && pool.key];
    });
    var blockedKnownCount = originalPools.length - pools.length;
    var blockedUnknownCount = asArray(summary.unknown).filter(function (raw) {
      return blocked.rawKeys[normalizeString(raw).trim().toLowerCase()];
    }).length;
    return {
      allKnownSourcesBlocked: Boolean(
        (originalPools.length && !pools.length)
        || (!originalPools.length && blockedUnknownCount)
      ),
      summary: marketHotspotPoolSummaryBadge(Object.assign({}, summary, {
        pools: pools,
        unknown: asArray(summary.unknown).filter(function (raw) {
          return !blocked.rawKeys[normalizeString(raw).trim().toLowerCase()];
        }),
        blockedSourceCount: blockedKnownCount + blockedUnknownCount,
      })),
    };
  }

  function hotspotWorkbenchRecordMismatch(item, projection) {
    var value = item && typeof item === 'object' ? item : {};
    var candidate = value.candidate && typeof value.candidate === 'object'
      ? value.candidate : {};
    return [value, candidate].some(function (record) {
      var date = normalizeString(record.report_date || record.date).trim();
      var phase = normalizeString(record.phase).trim();
      var snapshotId = normalizeString(record.snapshot_id).trim();
      return (date && date !== normalizeString(projection.report_date).trim())
        || (phase && phase !== normalizeString(projection.phase).trim())
        || (snapshotId && snapshotId !== normalizeString(projection.snapshot_id).trim());
    });
  }

  function marketHotspotScopeContract(report, snapshot) {
    var source = report && typeof report === 'object' ? report : {};
    var limitSnapshot = snapshot && typeof snapshot === 'object' ? snapshot : {};
    var phases = [source.phase, limitSnapshot.phase].map(function (value) {
      return normalizeString(value).trim().toLowerCase();
    }).filter(function (value, index, values) {
      return value && values.indexOf(value) === index;
    });
    var snapshotIds = [source.snapshot_id, limitSnapshot.snapshot_id].map(function (value) {
      return normalizeString(value).trim();
    }).filter(function (value, index, values) {
      return value && values.indexOf(value) === index;
    });
    return {
      phase: phases.length === 1 ? phases[0] : '',
      snapshotId: snapshotIds.length === 1 ? snapshotIds[0] : '',
      conflict: phases.length > 1 || snapshotIds.length > 1,
    };
  }

  function marketHotspotRowScopeMismatch(item, projection) {
    if (!projection || !item || typeof item !== 'object') return false;
    var phase = normalizeString(item.phase).trim().toLowerCase();
    var snapshotId = normalizeString(item.snapshot_id).trim();
    var reportDate = normalizeString(item.report_date).trim();
    return (phase && phase !== normalizeString(projection.phase).trim().toLowerCase())
      || (snapshotId && snapshotId !== normalizeString(projection.snapshot_id).trim())
      || (reportDate && reportDate !== normalizeString(projection.report_date).trim());
  }

  function marketHotspotDeclaredTotalContract(projection) {
    var summary = projection && projection.summary;
    if (!summary || typeof summary !== 'object'
        || !Object.prototype.hasOwnProperty.call(summary, 'total_items')) {
      return { declared: false, valid: true };
    }
    var value = summary.total_items;
    var validNumber = typeof value === 'number' && Number.isFinite(value)
      && value >= 0 && Math.floor(value) === value;
    return {
      declared: true,
      valid: validNumber && value === asArray(projection.items).length,
    };
  }

  function getMarketHotspotWorkbenchContract(reportDate, marketScope) {
    var bootstrap = getBootstrap();
    var projection = bootstrap.decisionWorkbench;
    var requestedScope = marketScope && typeof marketScope === 'object'
      ? marketScope : { phase: '', snapshotId: '', conflict: false };
    var health = projection && projection.health && typeof projection.health === 'object'
      ? projection.health : {};
    var scopeValid = Boolean(
      projection && projection.schema_version === 'decision-workbench-v1'
      && normalizeString(projection.report_date).trim() === reportDate
      && projection.phase === 'formal'
      && normalizeString(projection.snapshot_id).trim()
      && normalizeString(projection.payload_hash).trim()
      && Array.isArray(projection.items)
      && ['verified', 'partial'].indexOf(normalizeString(health.status).trim()) !== -1
      && requestedScope.conflict !== true
      && (!requestedScope.phase
        || requestedScope.phase === normalizeString(projection.phase).trim().toLowerCase())
      && (!requestedScope.snapshotId
        || requestedScope.snapshotId === normalizeString(projection.snapshot_id).trim())
    );
    var complete = Boolean(scopeValid
      && normalizeString(health.status).trim() === 'verified'
      && !asArray(health.blocking_reasons).length
      && !asArray(health.fact_blocking_reasons).length
      && !asArray(health.blocked_strategies).length);
    var records = Object.create(null);
    var summaries = Object.create(null);
    var quarantined = Object.create(null);
    if (!scopeValid) {
      return { scopeValid: false, complete: false, projection: null,
        records: records, summaries: summaries, quarantined: quarantined };
    }
    var blockedSources = marketHotspotBlockedSources(health);
    var declaredTotal = marketHotspotDeclaredTotalContract(projection);
    var negativeProofInvalid = !declaredTotal.valid;
    asArray(projection.items).forEach(function (item) {
      var identity = hotspotSecurityIdentity(item);
      if (identity.conflict) {
        negativeProofInvalid = true;
        asArray(identity.quarantineIdentities).forEach(function (value) {
          if (value) quarantined[value] = true;
        });
        return;
      }
      if (!identity.identity) {
        negativeProofInvalid = true;
        return;
      }
      if (hotspotWorkbenchRecordMismatch(item, projection)) {
        negativeProofInvalid = true;
        quarantined[identity.identity] = true;
        delete records[identity.identity];
        return;
      }
      if (records[identity.identity]) {
        negativeProofInvalid = true;
        quarantined[identity.identity] = true;
        delete records[identity.identity];
        return;
      }
      var sourceContract = marketHotspotRecordSourceContract(item, blockedSources);
      if (sourceContract.allKnownSourcesBlocked) {
        quarantined[identity.identity] = true;
        delete records[identity.identity];
        delete summaries[identity.identity];
        return;
      }
      if (!quarantined[identity.identity]) {
        records[identity.identity] = item;
        summaries[identity.identity] = sourceContract.summary;
      }
    });
    complete = complete && !negativeProofInvalid;
    return {
      scopeValid: true,
      complete: complete,
      projection: projection,
      records: records,
      summaries: summaries,
      quarantined: quarantined,
      negativeCoverageComplete: complete,
    };
  }

  function safeMarketHotspotSectorOverview(data) {
    try {
      return buildFundingMainlineModel(data || {});
    } catch (error) {
      return {
        title: '板块摘要',
        status: { label: '状态待确认', tone: 'neutral', detail: '板块摘要暂不可用。' },
        items: [],
      };
    }
  }

  function marketHotspotEvidence(data, code) {
    var source = data || {};
    var decisionBrief = source.decision_brief && typeof source.decision_brief === 'object'
      ? source.decision_brief : {};
    var registry = Object.create(null);
    asArray(decisionBrief.evidence_registry).forEach(function (entry) {
      var ref = normalizeString(entry && entry.evidence_ref).trim();
      if (ref) registry[ref] = entry;
    });
    var events = [];
    var modelSummaries = [];
    var eventSeen = Object.create(null);
    var summarySeen = Object.create(null);
    function appendEvent(entry) {
      if (!entry || typeof entry !== 'object') return;
      var title = normalizeString(entry.title || entry.display_title).trim();
      if (!title) return;
      var url = normalizeString(entry.url || entry.source_url || entry.link).trim();
      var key = title + '|' + url;
      if (eventSeen[key]) return;
      eventSeen[key] = true;
      events.push({
        title: title,
        date: normalizeString(entry.date || entry.publish_date || entry.ctime).trim(),
        source: normalizeString(entry.source || entry.publisher).trim(),
        url: url,
      });
    }
    asArray(source.events).forEach(function (event) {
      var linked = asArray(event && event.stock_list).some(function (stock) {
        return hotspotCode(stock && typeof stock === 'object'
          ? stock.code || stock.instrument_id : stock) === code;
      });
      if (linked) appendEvent(event);
    });
    asArray(decisionBrief.theses).forEach(function (thesis) {
      var linked = asArray(thesis && thesis.stock_links).some(function (link) {
        return hotspotCode(link && (link.code || link.instrument_id)) === code;
      });
      if (!linked) return;
      asArray(thesis.evidence_refs).forEach(function (ref) {
        var evidence = registry[normalizeString(ref).trim()];
        if (evidence && normalizeString(evidence.kind).trim() === 'event') appendEvent(evidence);
      });
      var summary = normalizeString(thesis.llm_summary || thesis.rule_summary).trim();
      if (summary && !summarySeen[summary]) {
        summarySeen[summary] = true;
        modelSummaries.push({
          text: summary,
          kind: thesis.llm_summary ? 'model' : 'rule',
        });
      }
    });
    return { events: events, modelSummaries: modelSummaries };
  }

  function marketHotspotFirstTimeOrder(value) {
    var raw = normalizeString(value).trim();
    var match = raw.match(/^(\d{2}):(\d{2})(?::(\d{2}))?$/)
      || raw.match(/^(\d{2})(\d{2})(\d{2})?$/);
    if (!match) return null;
    var hour = Number(match[1]);
    var minute = Number(match[2]);
    var second = Number(match[3] || 0);
    if (hour > 23 || minute > 59 || second > 59) return null;
    return hour * 3600 + minute * 60 + second;
  }

  function compareMarketHotspotNullableDesc(left, right) {
    var leftKnown = typeof left === 'number' && Number.isFinite(left);
    var rightKnown = typeof right === 'number' && Number.isFinite(right);
    if (leftKnown && rightKnown && left !== right) return right - left;
    if (leftKnown !== rightKnown) return leftKnown ? -1 : 1;
    return 0;
  }

  function compareMarketHotspotItems(left, right) {
    var heightOrder = compareMarketHotspotNullableDesc(left.lianban, right.lianban);
    if (heightOrder) return heightOrder;
    var leftTime = marketHotspotFirstTimeOrder(left.firstTime);
    var rightTime = marketHotspotFirstTimeOrder(right.firstTime);
    var leftTimeKnown = leftTime !== null;
    var rightTimeKnown = rightTime !== null;
    if (leftTimeKnown && rightTimeKnown && leftTime !== rightTime) return leftTime - rightTime;
    if (leftTimeKnown !== rightTimeKnown) return leftTimeKnown ? -1 : 1;
    var leftCode = normalizeString(left.code || left.key).trim();
    var rightCode = normalizeString(right.code || right.key).trim();
    if (leftCode !== rightCode) return leftCode < rightCode ? -1 : 1;
    return Number(left.sourceOrder || 0) - Number(right.sourceOrder || 0);
  }

  function marketHotspotGroupWithStats(group) {
    var value = group && typeof group === 'object' ? group : {};
    var items = asArray(value.items).slice().sort(compareMarketHotspotItems);
    var valid = items.filter(function (item) {
      return item.isDeterminedSecurity && item.quoteStatus === 'available';
    });
    var heights = valid.map(function (item) { return item.lianban; }).filter(function (height) {
      return typeof height === 'number' && Number.isFinite(height);
    });
    return Object.assign({}, value, {
      items: items,
      totalCount: valid.length ? valid.length : null,
      totalItemCount: items.length,
      maxLianban: heights.length ? Math.max.apply(Math, heights) : null,
      systemHitCount: valid.filter(function (item) {
        return item.membership === 'in';
      }).length,
      systemUnknownCount: valid.filter(function (item) {
        return item.membership === 'unknown';
      }).length,
    });
  }

  function marketHotspotSystemCountText(hitCount, unknownCount) {
    var hits = Number(hitCount) || 0;
    var unknown = Number(unknownCount) || 0;
    if (!unknown) return '系统命中' + hits + '只';
    if (hits) return '已知命中' + hits + '只 · 待关联' + unknown + '只';
    return '系统命中待核验 · 待关联' + unknown + '只';
  }

  function marketHotspotSortMode(value) {
    return ['count', 'height', 'system'].indexOf(normalizeString(value).trim()) !== -1
      ? normalizeString(value).trim() : 'count';
  }

  function compareMarketHotspotGroups(left, right, mode) {
    var selected = marketHotspotSortMode(mode);
    var order = 0;
    if (selected === 'height') {
      order = compareMarketHotspotNullableDesc(left.maxLianban, right.maxLianban)
        || compareMarketHotspotNullableDesc(left.totalCount, right.totalCount);
    } else if (selected === 'system') {
      order = compareMarketHotspotNullableDesc(left.systemHitCount, right.systemHitCount)
        || compareMarketHotspotNullableDesc(left.totalCount, right.totalCount)
        || compareMarketHotspotNullableDesc(left.maxLianban, right.maxLianban);
    } else {
      order = compareMarketHotspotNullableDesc(left.totalCount, right.totalCount)
        || compareMarketHotspotNullableDesc(left.maxLianban, right.maxLianban);
    }
    return order || Number(left.sourceOrder || 0) - Number(right.sourceOrder || 0);
  }

  function sortMarketHotspotGroups(groups, mode) {
    return asArray(groups).slice().sort(function (left, right) {
      return compareMarketHotspotGroups(left, right, mode);
    }).map(function (group, index) {
      return Object.assign({}, group, { rank: index + 1 });
    });
  }

  function buildMarketHotspotModel(data) {
    var source = data || {};
    var sectorOverview = safeMarketHotspotSectorOverview(source);
    var reportDate = normalizeString(source.date || source.report_date || getBootstrap().pageDate).trim();
    var base = {
      status: 'missing',
      reasonCode: '',
      reportDate: reportDate,
      snapshotDate: '',
      asOf: '',
      source: '',
      snapshotStatus: 'missing',
      items: [],
      groups: [],
      totalSecurityCount: 0,
      totalAppearanceCount: 0,
      quoteCount: 0,
      systemHitCount: 0,
      systemOutCount: 0,
      systemUnknownCount: 0,
      systemListComplete: false,
      countsKnown: false,
      sectorOverview: sectorOverview,
    };
    try {
      var snapshot = source.limit_up_snapshot && typeof source.limit_up_snapshot === 'object'
        ? source.limit_up_snapshot : {};
      var snapshotStatus = normalizeString(snapshot.status || 'missing').trim();
      var declaredSnapshotDate = normalizeString(snapshot.date || snapshot.report_date).trim();
      var snapshotAsOf = normalizeString(snapshot.as_of || snapshot.generated_at).trim();
      var asOfMatch = snapshotAsOf.match(/^(\d{4}-\d{2}-\d{2})/);
      var asOfDate = asOfMatch ? asOfMatch[1] : '';
      var snapshotDate = declaredSnapshotDate || asOfDate;
      base.snapshotDate = snapshotDate;
      base.asOf = snapshotAsOf;
      base.source = normalizeString(snapshot.source).trim();
      base.snapshotStatus = snapshotStatus;
      if ((declaredSnapshotDate && asOfDate && declaredSnapshotDate !== asOfDate)
          || (snapshotDate && reportDate && snapshotDate !== reportDate)) {
        base.status = 'date_mismatch';
        base.reasonCode = 'hotspot_date_mismatch';
        return base;
      }
      if (!snapshotDate) {
        base.status = 'date_unknown';
        base.reasonCode = 'hotspot_date_unknown';
        return base;
      }
      if (snapshotStatus === 'verified_empty') {
        base.status = 'empty';
        base.countsKnown = true;
        return base;
      }
      if (['verified_complete', 'partial'].indexOf(snapshotStatus) === -1) {
        base.status = snapshotStatus === 'error' ? 'error' : 'missing';
        base.reasonCode = snapshotStatus === 'error'
          ? 'hotspot_snapshot_error' : 'hotspot_snapshot_missing';
        return base;
      }

      if (!Array.isArray(snapshot.items)) {
        base.status = 'unavailable';
        base.reasonCode = 'hotspot_items_invalid';
        return base;
      }
      var rawSnapshotItems = snapshot.items;
      var usableSnapshotItems = rawSnapshotItems.filter(function (record) {
        if (!record || typeof record !== 'object' || Array.isArray(record)) return false;
        return Boolean(normalizeString(
          record.name || record.code || record.instrument_id || record.security_id
        ).trim());
      });
      if (!usableSnapshotItems.length) {
        base.status = 'unavailable';
        base.reasonCode = 'hotspot_items_unavailable';
        return base;
      }
      var rawTotal = hotspotFiniteNumber(snapshot.raw_total);
      var itemsPartial = usableSnapshotItems.length !== rawSnapshotItems.length
        || (rawTotal !== null && rawTotal !== rawSnapshotItems.length);

      var marketScope = marketHotspotScopeContract(source, snapshot);
      var workbench = getMarketHotspotWorkbenchContract(reportDate, marketScope);
      base.systemListComplete = workbench.complete;
      var items = [];
      var determinedByIdentity = Object.create(null);
      var rawOrder = 0;
      usableSnapshotItems.forEach(function (record) {
        var raw = record && typeof record === 'object' ? record : {};
        var identity = hotspotSecurityIdentity(raw);
        if (identity.identity && determinedByIdentity[identity.identity]) return;
        var quoteDate = hotspotQuoteDateContract(
          raw, reportDate, snapshotDate, snapshotAsOf
        );
        var quoteStatus = identity.conflict ? 'identity_conflict' : quoteDate.status;
        var quoteAvailable = quoteStatus === 'available';
        var changePct = quoteAvailable ? hotspotFiniteNumber(raw.change_pct) : null;
        var price = quoteAvailable ? hotspotFiniteNumber(raw.price) : null;
        if (price !== null && price <= 0) price = null;
        var lianban = quoteAvailable ? hotspotFiniteNumber(raw.lianban) : null;
        if (lianban !== null && lianban < 1) lianban = null;
        var item = {
          key: identity.identity || 'name:' + rawOrder + ':' + normalizeString(raw.name).trim(),
          identity: identity.identity,
          code: identity.code,
          name: normalizeString(raw.name).trim() || identity.code || '名称待补',
          sector: normalizeString(raw.sector || raw.industry).trim() || '题材待补',
          isDeterminedSecurity: Boolean(identity.identity) && !identity.conflict,
          identityConflict: identity.conflict,
          associationScopeConflict: marketHotspotRowScopeMismatch(
            raw, workbench.projection
          ),
          price: price,
          changePct: changePct,
          quoteTone: hotspotQuoteTone(changePct),
          quoteStatus: quoteStatus,
          quoteDate: quoteDate.date,
          lianban: lianban === null ? null : Math.floor(lianban),
          firstTime: quoteAvailable ? normalizeString(raw.first_time).trim() : '',
          fund: quoteAvailable ? hotspotFiniteNumber(raw.fund) : null,
          zhaban: quoteAvailable ? hotspotFiniteNumber(raw.zhaban) : null,
          reportDate: reportDate,
          asOf: base.asOf,
          quoteSource: base.source,
          themes: [],
          membership: 'unknown',
          membershipReason: '',
          workbenchItem: null,
          poolSummary: emptyHotspotPoolSummary(),
          events: [],
          modelSummaries: [],
          raw: raw,
          sourceOrder: rawOrder,
        };
        rawOrder += 1;
        if (identity.identity) determinedByIdentity[identity.identity] = item;
        items.push(item);
      });

      var byCode = Object.create(null);
      items.forEach(function (item) {
        if (item.code && !byCode[item.code]) byCode[item.code] = item;
      });
      var groups = [];
      var groupByName = Object.create(null);
      var groupItemSeen = Object.create(null);
      function ensureGroup(name) {
        var normalized = normalizeString(name).trim() || '题材待补';
        if (!groupByName[normalized]) {
          groupByName[normalized] = {
            key: 'theme-' + groups.length,
            name: normalized,
            colorIndex: groups.length % 8,
            sourceOrder: groups.length,
            items: [],
          };
          groups.push(groupByName[normalized]);
        }
        return groupByName[normalized];
      }
      asArray(snapshot.theme_groups).forEach(function (group) {
        var target = ensureGroup(group && group.name);
        var seen = groupItemSeen[target.key] || Object.create(null);
        groupItemSeen[target.key] = seen;
        asArray(group && group.codes).forEach(function (value) {
          var item = byCode[hotspotCode(value)];
          if (!item || seen[item.key]) return;
          seen[item.key] = true;
          target.items.push(item);
          if (item.themes.indexOf(target.name) === -1) item.themes.push(target.name);
        });
      });
      items.forEach(function (item) {
        if (item.themes.length) return;
        var fallback = ensureGroup(item.sector || '题材待补');
        if (!fallback.items.some(function (entry) { return entry.key === item.key; })) {
          fallback.items.push(item);
        }
        item.themes.push(fallback.name);
      });

      items.forEach(function (item) {
        if (item.isDeterminedSecurity && workbench.scopeValid) {
          if (item.associationScopeConflict) {
            item.membershipReason = '该热点记录的报告阶段或快照与系统清单冲突';
          } else if (workbench.quarantined[item.identity]) {
            item.membership = 'unknown';
            item.membershipReason = '证券身份、日期、阶段或快照冲突';
          } else if (workbench.records[item.identity]) {
            item.membership = 'in';
            item.workbenchItem = workbench.records[item.identity];
            item.poolSummary = workbench.summaries[item.identity]
              || getPoolHitSummary(item.workbenchItem);
          } else if (workbench.complete) {
            item.membership = 'out';
            item.membershipReason = '完整同日报告系统清单未收录';
          } else {
            item.membershipReason = '当前系统清单覆盖不完整，不能证明未入选';
          }
        } else if (item.identityConflict) {
          item.membershipReason = '证券身份冲突';
        } else if (!workbench.scopeValid) {
          item.membershipReason = '系统清单日期、阶段、快照或完整性待核验';
        } else {
          item.membershipReason = '证券身份待关联';
        }
        if (item.code && item.isDeterminedSecurity) {
          var evidence = marketHotspotEvidence(source, item.code);
          item.events = evidence.events;
          item.modelSummaries = evidence.modelSummaries;
        }
      });

      base.items = items;
      base.groups = sortMarketHotspotGroups(groups.filter(function (group) {
        return group.items.length;
      }).map(marketHotspotGroupWithStats), 'count');
      base.totalSecurityCount = items.filter(function (item) {
        return item.isDeterminedSecurity;
      }).length;
      base.totalAppearanceCount = base.groups.reduce(function (total, group) {
        return total + group.items.filter(function (item) {
          return item.isDeterminedSecurity;
        }).length;
      }, 0);
      base.quoteCount = items.filter(function (item) { return item.changePct !== null; }).length;
      base.systemHitCount = items.filter(function (item) { return item.membership === 'in'; }).length;
      base.systemOutCount = items.filter(function (item) { return item.membership === 'out'; }).length;
      base.systemUnknownCount = items.filter(function (item) {
        return item.membership === 'unknown';
      }).length;
      base.countsKnown = true;
      base.status = snapshotStatus === 'partial' || itemsPartial ? 'partial'
        : (items.length ? 'available' : 'empty');
      return base;
    } catch (error) {
      base.status = 'degraded';
      base.reasonCode = 'hotspot_model_unavailable';
      return base;
    }
  }

  function filterMarketHotspotItems(model, filters) {
    var value = model && typeof model === 'object' ? model : { items: [], groups: [] };
    var options = filters && typeof filters === 'object' ? filters : {};
    var query = normalizeString(options.query).trim().toLowerCase();
    var theme = normalizeString(options.theme).trim();
    var onlySystem = options.onlySystem === true;
    function itemMatches(item) {
      if (onlySystem && item.membership !== 'in') return false;
      if (!query) return true;
      return [item.name, item.code, item.sector].concat(asArray(item.themes))
        .some(function (part) {
          return normalizeString(part).toLowerCase().indexOf(query) !== -1;
        });
    }
    var groups = sortMarketHotspotGroups(value.groups, options.sortMode).filter(function (group) {
      return !theme || group.name === theme;
    }).map(function (group) {
      var matched = asArray(group.items).filter(itemMatches);
      return Object.assign({}, group, {
        items: matched,
        matchedCount: matched.length,
      });
    }).filter(function (group) { return group.items.length; });
    var seen = Object.create(null);
    var items = [];
    groups.forEach(function (group) {
      group.items.forEach(function (item) {
        if (seen[item.key]) return;
        seen[item.key] = true;
        items.push(item);
      });
    });
    return { items: items, groups: groups, matchedSecurityCount: items.length };
  }

  function safeMarketHotspotUrl(value) {
    var url = normalizeString(value).trim();
    return /^https?:\/\//i.test(url) ? url : '';
  }

  function marketHotspotMembershipHtml(item) {
    if (item.membership === 'in') {
      var summary = renderPoolHitSummaryValue(item.poolSummary, 'list');
      return summary.replace(/^<div/, '<span').replace(/<\/div>$/, '</span>');
    }
    if (item.membership === 'out') {
      return '<span class="hotspot-membership is-out">本期系统清单未入选</span>';
    }
    return '<span class="hotspot-membership is-unknown">关联未知</span>';
  }

  function marketHotspotQuoteHtml(item, compact) {
    var pct = item.changePct === null ? '报价暂缺' : formatPct(item.changePct, true);
    var board = item.lianban === null ? ''
      : (item.lianban > 1 ? item.lianban + '连板' : '首板');
    return '<span class="hotspot-quote is-' + escapeHtml(item.quoteTone) + '"><strong>'
      + escapeHtml(pct) + '</strong>'
      + (!compact && item.price !== null ? '<small>价 ' + escapeHtml(formatNumber(item.price, 2)) + '</small>' : '')
      + (board ? '<small>' + escapeHtml(board) + '</small>' : '')
      + '</span>';
  }

  function marketHotspotIdentityLabel(item) {
    var value = item && typeof item === 'object' ? item : {};
    if (value.identityConflict) {
      return value.code ? '原记录 ' + value.code + ' · 身份冲突' : '证券身份冲突';
    }
    return value.code || '身份待关联';
  }

  function renderMarketHotspotCard(item) {
    return '<button type="button" class="hotspot-stock-card is-' + escapeHtml(item.quoteTone)
      + '" data-hotspot-open="' + escapeHtml(item.key) + '" data-hotspot-code="'
      + escapeHtml(item.isDeterminedSecurity ? item.code : '') + '"><span class="hotspot-stock-title"><strong>'
      + escapeHtml(item.name) + '</strong><small>' + escapeHtml(marketHotspotIdentityLabel(item))
      + '</small></span>' + marketHotspotQuoteHtml(item, true)
      + marketHotspotMembershipHtml(item) + '</button>';
  }

  function renderMarketHotspotListRow(item) {
    var eventText = item.events.length
      ? item.events[0].title + '（关联事件，非已证实涨停原因）' : '原因未补';
    return '<button type="button" class="hotspot-list-row" data-hotspot-open="'
      + escapeHtml(item.key) + '" data-hotspot-code="'
      + escapeHtml(item.isDeterminedSecurity ? item.code : '') + '">'
      + '<span><strong>' + escapeHtml(item.name) + '</strong><small>'
      + escapeHtml(marketHotspotIdentityLabel(item)) + '</small></span><span>'
      + escapeHtml(asArray(item.themes).join(' / ') || item.sector) + '</span>'
      + marketHotspotQuoteHtml(item, false) + '<span class="hotspot-list-event">'
      + escapeHtml(eventText) + '</span><span>' + marketHotspotMembershipHtml(item)
      + '</span></button>';
  }

  function renderMarketHotspotSectorFallback(model) {
    var overview = model && model.sectorOverview || {};
    var items = asArray(overview.items);
    if (!items.length) return '';
    return '<div class="hotspot-sector-fallback"><strong>'
      + escapeHtml(overview.title || '板块摘要') + '</strong><div>'
      + items.map(function (item) {
        return '<span>' + escapeHtml(item.name || '板块待补') + '</span>';
      }).join('') + '</div></div>';
  }

  function renderMarketHotspotSection(model, uiState) {
    var value = model && typeof model === 'object' ? model : buildMarketHotspotModel({});
    var options = uiState && typeof uiState === 'object' ? uiState : {};
    var mode = options.mode === 'list' ? 'list' : 'map';
    var sortMode = marketHotspotSortMode(options.sortMode);
    var visibleLimit = Math.max(1, Number(options.visibleLimit) || 30);
    var filtered = filterMarketHotspotItems(value, Object.assign({}, options, {
      sortMode: sortMode,
    }));
    var orderedGroups = sortMarketHotspotGroups(value.groups, sortMode);
    var quickGroups = orderedGroups.slice(0, 6);
    var quickNames = Object.create(null);
    quickGroups.forEach(function (group) { quickNames[group.name] = true; });
    var themeButtons = quickGroups.map(function (group) {
      var active = normalizeString(options.theme) === group.name;
      return '<button type="button" data-hotspot-theme="' + escapeHtml(group.name)
        + '" aria-pressed="' + (active ? 'true' : 'false') + '" class="'
        + (active ? 'is-active' : '') + '">' + escapeHtml(group.name) + '</button>';
    }).join('');
    var remainingGroups = orderedGroups.filter(function (group) {
      return !quickNames[group.name];
    });
    var themeSelectOptions = remainingGroups.map(function (group) {
      return '<option value="' + escapeHtml(group.name) + '"'
        + (normalizeString(options.theme) === group.name ? ' selected' : '') + '>'
        + escapeHtml(group.name) + '</option>';
    }).join('');
    var statusCopy = value.status === 'partial'
      ? '当前为部分有效样本，未取得部分不解释为没有热点。'
      : (value.status === 'date_mismatch'
        ? '热点快照日期与报告日不一致，个股行情已隔离。'
        : (value.status === 'date_unknown'
          ? '热点快照日期未核验，个股行情已隔离。'
        : (value.status === 'degraded'
          ? '热点个股暂不可用，其他日报内容不受影响。'
          : (value.status === 'unavailable'
            ? '热点样本暂不可用，不能据此判断今日为空。'
          : (value.status === 'empty'
            ? '本期热点个股确认空池，保留已有板块摘要。'
            : (value.status === 'available'
              ? '热点是市场背景，不是新的推荐池。' : '热点个股数据尚未生成。'))))));
    var content = '';
    var showing = 0;
    if (filtered.items.length && mode === 'map') {
      var mapGroups = options.showAllGroups === true
        ? filtered.groups : filtered.groups.slice(0, 6);
      var mapSeen = Object.create(null);
      content = '<div class="hotspot-group-grid">' + mapGroups.map(function (group) {
        var expandedGroups = options.expandedGroups && typeof options.expandedGroups === 'object'
          ? options.expandedGroups : {};
        var expanded = expandedGroups[group.key] === true;
        var groupItems = expanded ? group.items : group.items.slice(0, 6);
        groupItems.forEach(function (item) { mapSeen[item.key] = true; });
        var totalText = group.totalCount === null
          ? '涨停家数待核验'
          : (value.status === 'partial'
            ? '已取得涨停' + group.totalCount + '家' : '涨停' + group.totalCount + '家');
        var heightText = group.maxLianban === null
          ? '连板高度待核验' : '最高' + group.maxLianban + '连板';
        var currentText = groupItems.length !== group.totalItemCount
          ? '<small class="hotspot-group-current">当前显示'
            + escapeHtml(String(groupItems.length)) + '/' + escapeHtml(String(group.totalItemCount))
            + '只</small>' : '';
        var rank = Number(group.rank || 0);
        var rankText = '#' + (rank > 0 && rank < 10 ? '0' : '') + (rank || '—');
        var systemText = group.totalCount === null
          ? '系统关联待核验'
          : marketHotspotSystemCountText(group.systemHitCount, group.systemUnknownCount);
        return '<article class="hotspot-group is-theme-' + escapeHtml(group.colorIndex)
          + '"><header><span></span><div class="hotspot-group-heading"><strong>'
          + escapeHtml(rankText + ' ' + group.name) + '</strong><small class="hotspot-group-stats">'
          + escapeHtml(totalText + ' · ' + heightText + ' · ' + systemText)
          + '</small>' + currentText + '</div><small class="hotspot-group-count">'
          + escapeHtml(totalText) + '</small></header>'
          + '<div class="hotspot-stock-grid">' + groupItems.map(renderMarketHotspotCard).join('')
          + '</div>'
          + (!expanded && group.items.length > groupItems.length
            ? '<button type="button" class="hotspot-more hotspot-group-more" data-hotspot-group-more="'
              + escapeHtml(group.key) + '">查看本组全部' + escapeHtml(String(group.items.length)) + '只</button>'
            : '') + '</article>';
      }).join('') + '</div>';
      showing = Object.keys(mapSeen).length;
      if (filtered.groups.length > mapGroups.length) {
        content += '<button type="button" class="hotspot-more" data-hotspot-more-groups>更多行业（余下'
          + escapeHtml(String(filtered.groups.length - mapGroups.length)) + '组）</button>';
      }
    } else if (filtered.items.length) {
      var visibleItems = filtered.items.slice(0, visibleLimit);
      showing = visibleItems.length;
      content = '<div class="hotspot-list"><header><span>股票</span><span>方向</span><span>行情</span><span>事件/说明</span><span>系统关系</span></header>'
        + visibleItems.map(renderMarketHotspotListRow).join('') + '</div>';
    } else {
      content = '<div class="hotspot-empty"><strong>当前筛选没有可显示个股</strong><span>'
        + escapeHtml(statusCopy) + '</span></div>' + renderMarketHotspotSectorFallback(value);
    }
    var countsKnown = value.countsKnown === true;
    var sampleCountText = countsKnown ? String(value.totalSecurityCount) : '暂不可用';
    var groupCountText = countsKnown ? String(value.groups.length) : '暂不可用';
    var quoteCountText = countsKnown ? String(value.quoteCount) : '暂不可用';
    var systemUnknownCount = countsKnown ? Number(value.systemUnknownCount) || 0 : 0;
    var hitCountText = countsKnown
      ? (systemUnknownCount && !value.systemHitCount ? '待核验' : String(value.systemHitCount))
      : '暂不可用';
    var hitCountLabel = !countsKnown
      ? '系统命中只数（证券去重）'
      : (systemUnknownCount
        ? (value.systemHitCount
          ? '已知系统命中 · 另有' + systemUnknownCount + '只待关联'
          : '系统命中待核验 · ' + systemUnknownCount + '只待关联')
        : '系统命中只数（证券去重）');
    var displayCountHtml = countsKnown
      ? '匹配 ' + escapeHtml(String(filtered.items.length)) + '只 · 当前显示 '
        + escapeHtml(String(showing)) + '只'
      : '匹配/显示 暂不可用';
    var totalCountText = countsKnown
      ? '行业总数 ' + String(value.groups.length) + '组 · 全量证券 '
        + String(value.totalSecurityCount) + '只 · '
        + marketHotspotSystemCountText(value.systemHitCount, systemUnknownCount)
        + (systemUnknownCount
          ? '；系统命中排序按已知命中只数，不累加每股池数'
          : '，按不同证券计，不累加每股池数')
      : '样本数量暂不可用；现有板块事实仍可独立阅读';
    return '<section class="market-hotspot-section" id="marketHotspotSection" aria-labelledby="marketHotspotTitle">'
      + '<header class="hotspot-heading"><div><span class="hotspot-eyebrow">市场背景</span><h2 id="marketHotspotTitle">今日热点地图</h2><p>'
      + escapeHtml(statusCopy) + '</p></div><div class="hotspot-snapshot"><strong>'
      + escapeHtml(value.reportDate || '日期待补') + '</strong><small>'
      + escapeHtml(value.asOf ? '快照 ' + value.asOf : '快照时间待补') + '</small><small>'
      + escapeHtml(value.source ? '来源 ' + value.source : '来源待补') + '</small></div></header>'
      + '<div class="hotspot-metrics"><span><strong>' + escapeHtml(sampleCountText)
      + '</strong><small>已取得样本</small></span><span><strong>'
      + escapeHtml(groupCountText) + '</strong><small>已取得题材/行业</small></span><span><strong>'
      + escapeHtml(quoteCountText) + '</strong><small>有行情</small></span><span><strong>'
      + escapeHtml(hitCountText) + '</strong><small>' + escapeHtml(hitCountLabel) + '</small></span></div>'
      + '<div class="hotspot-tools"><div class="hotspot-mode" role="group" aria-label="热点阅读模式">'
      + '<button type="button" data-hotspot-mode="map" aria-pressed="' + (mode === 'map') + '">主题地图</button>'
      + '<button type="button" data-hotspot-mode="list" aria-pressed="' + (mode === 'list') + '">详细清单</button></div>'
      + '<label class="hotspot-sort"><span>板块排序</span><select data-hotspot-sort>'
      + '<option value="count"' + (sortMode === 'count' ? ' selected' : '') + '>涨停家数</option>'
      + '<option value="height"' + (sortMode === 'height' ? ' selected' : '') + '>连板高度</option>'
      + '<option value="system"' + (sortMode === 'system' ? ' selected' : '') + '>系统命中</option>'
      + '</select></label>'
      + '<div class="hotspot-themes"><button type="button" data-hotspot-theme="" aria-pressed="'
      + (!options.theme) + '" class="' + (!options.theme ? 'is-active' : '') + '">全部题材</button>'
      + themeButtons + '<label class="hotspot-theme-more"><span>更多行业</span><select data-hotspot-theme-select'
      + (remainingGroups.length ? '' : ' disabled') + '><option value="">更多行业选择</option>'
      + themeSelectOptions + '</select></label></div><label class="hotspot-search"><span>搜索</span><input id="marketHotspotSearch" type="search" value="'
      + escapeHtml(options.query || '') + '" placeholder="搜索名称或代码"></label>'
      + '<label class="hotspot-only-system"><input id="marketHotspotOnlySystem" type="checkbox"'
      + (options.onlySystem ? ' checked' : '') + '>只看系统命中</label>'
      + '<button type="button" class="hotspot-clear" data-hotspot-clear>清空</button></div>'
      + '<div class="hotspot-result-meta" aria-live="polite"><span>'
      + displayCountHtml + '</span><small>' + escapeHtml(totalCountText) + '</small></div>'
      + content
      + (mode === 'list' && filtered.items.length > showing
        ? '<button type="button" class="hotspot-more" data-hotspot-more>加载更多</button>' : '')
      + '<p class="hotspot-boundary">按来源池计数，含上游基础池；榜单重复收录不叠加。行情取自本热点快照，不用候选报价替换。</p>'
      + '</section>';
  }

  function renderMarketHotspotReadOnlyDetail(item) {
    var value = item && typeof item === 'object' ? item : {};
    var membership = value.membership === 'out' ? '本期系统清单未入选'
      : (value.membership === 'in' ? '本期系统清单已命中' : '系统清单关联未知');
    var eventHtml = asArray(value.events).map(function (event) {
      var url = safeMarketHotspotUrl(event && event.url);
      return '<li><strong>' + escapeHtml(event && event.title || '事件标题待补') + '</strong>'
        + (event && event.date ? '<small>' + escapeHtml(event.date) + '</small>' : '')
        + (url ? '<a href="' + escapeHtml(url) + '" target="_blank" rel="noopener noreferrer">查看来源</a>' : '')
        + '</li>';
    }).join('');
    var summaryHtml = asArray(value.modelSummaries).map(function (summary) {
      return '<li>' + escapeHtml(summary && summary.text) + '</li>';
    }).join('');
    var quoteEvidence = value.quoteStatus === 'date_conflict'
      ? '行情日期冲突，报价已隔离'
      : (value.quoteStatus === 'identity_conflict'
        ? '证券身份冲突，报价已隔离'
        : (value.quoteDate ? '行情时点 ' + value.quoteDate : '行情时点待核验'));
    return '<article class="hotspot-readonly-detail"><header><div><h2 id="hotspotReadonlyTitle">'
      + escapeHtml(value.name || '热点详情') + '</h2><p>'
      + escapeHtml(marketHotspotIdentityLabel(value))
      + ' · ' + escapeHtml(asArray(value.themes).join(' / ') || value.sector || '题材待补')
      + '</p></div><button type="button" data-hotspot-close aria-label="关闭热点详情">关闭</button></header>'
      + '<div class="hotspot-readonly-body"><section><h3>已记录盘面</h3><p><strong class="is-'
      + escapeHtml(value.quoteTone || 'missing') + '">'
      + escapeHtml(value.changePct === null ? '报价暂缺' : formatPct(value.changePct, true))
      + (value.price === null ? '' : ' · ¥ ' + escapeHtml(formatNumber(value.price, 2)))
      + '</strong></p><p>报告日 ' + escapeHtml(value.reportDate || '待补') + ' · '
      + escapeHtml(quoteEvidence) + ' · ' + escapeHtml(value.quoteSource || '来源待补')
      + '</p></section><section><h3>系统关系</h3><p>' + escapeHtml(membership)
      + '</p><p>未入池热点保持只读，不加入主推、全部或观察。</p></section>'
      + '<section><h3>关联事件，不代表已证实涨停原因</h3>'
      + (eventHtml ? '<ul>' + eventHtml + '</ul>' : '<p>原因未补</p>') + '</section>'
      + (summaryHtml ? '<section><h3>模型归纳</h3><ul>' + summaryHtml + '</ul></section>' : '')
      + '<p class="hotspot-chart-missing">没有可靠 K 线；本详情不跨来源借图。</p></div></article>';
  }

  function showMarketHotspotReadOnlyDetail(item) {
    if (!nodes.hotspotDialog || !nodes.hotspotDialogContent) return false;
    nodes.hotspotDialogContent.innerHTML = renderMarketHotspotReadOnlyDetail(item);
    var close = nodes.hotspotDialogContent.querySelector('[data-hotspot-close]');
    if (close) close.addEventListener('click', function () {
      if (typeof nodes.hotspotDialog.close === 'function') nodes.hotspotDialog.close();
      else nodes.hotspotDialog.removeAttribute('open');
    });
    if (typeof nodes.hotspotDialog.showModal === 'function') nodes.hotspotDialog.showModal();
    else nodes.hotspotDialog.setAttribute('open', '');
    return true;
  }

  function openMarketHotspotDetail(item, handlers) {
    var value = item && typeof item === 'object' ? item : {};
    var callbacks = handlers && typeof handlers === 'object' ? handlers : {};
    if (value.membership === 'in' && value.workbenchItem) {
      var openCandidate = callbacks.openCandidate || openCurrentCandidateDetail;
      if (openCandidate(value.code, value.workbenchItem.evidence_view || state.currentView)) {
        return 'candidate';
      }
    }
    var openReadonly = callbacks.openReadonly || showMarketHotspotReadOnlyDetail;
    openReadonly(value);
    return 'readonly';
  }

  function marketHotspotState() {
    if (!state.hotspot || typeof state.hotspot !== 'object') {
      state.hotspot = { model: null, mode: 'map', sortMode: 'count', query: '', theme: '',
        onlySystem: false, visibleLimit: 30, showAllGroups: false,
        expandedGroups: {}, returnFocus: null };
    }
    state.hotspot.sortMode = marketHotspotSortMode(state.hotspot.sortMode);
    if (!state.hotspot.expandedGroups || typeof state.hotspot.expandedGroups !== 'object') {
      state.hotspot.expandedGroups = {};
    }
    if (typeof state.hotspot.showAllGroups !== 'boolean') state.hotspot.showAllGroups = false;
    return state.hotspot;
  }

  function clearMarketHotspotFilters(store) {
    var value = store && typeof store === 'object' ? store : {};
    value.query = '';
    value.theme = '';
    value.onlySystem = false;
    return value;
  }

  function bindMarketHotspotControls() {
    if (!nodes.marketHotspot) return;
    var store = marketHotspotState();
    Array.prototype.forEach.call(nodes.marketHotspot.querySelectorAll('[data-hotspot-mode]'), function (button) {
      button.addEventListener('click', function () {
        store.mode = button.getAttribute('data-hotspot-mode') === 'list' ? 'list' : 'map';
        renderMarketHotspot();
      });
    });
    var sort = nodes.marketHotspot.querySelector('[data-hotspot-sort]');
    if (sort) sort.addEventListener('change', function () {
      store.sortMode = marketHotspotSortMode(sort.value);
      renderMarketHotspot();
    });
    Array.prototype.forEach.call(nodes.marketHotspot.querySelectorAll('[data-hotspot-theme]'), function (button) {
      button.addEventListener('click', function () {
        store.theme = button.getAttribute('data-hotspot-theme') || '';
        renderMarketHotspot();
      });
    });
    var themeSelect = nodes.marketHotspot.querySelector('[data-hotspot-theme-select]');
    if (themeSelect) themeSelect.addEventListener('change', function () {
      store.theme = themeSelect.value || '';
      renderMarketHotspot();
    });
    var search = nodes.marketHotspot.querySelector('#marketHotspotSearch');
    if (search) search.addEventListener('input', function () {
      store.query = search.value || '';
      renderMarketHotspot();
      var next = nodes.marketHotspot.querySelector('#marketHotspotSearch');
      if (next && next.focus) {
        next.focus();
        if (typeof next.setSelectionRange === 'function') {
          next.setSelectionRange(next.value.length, next.value.length);
        }
      }
    });
    var onlySystem = nodes.marketHotspot.querySelector('#marketHotspotOnlySystem');
    if (onlySystem) onlySystem.addEventListener('change', function () {
      store.onlySystem = onlySystem.checked === true;
      renderMarketHotspot();
    });
    var clear = nodes.marketHotspot.querySelector('[data-hotspot-clear]');
    if (clear) clear.addEventListener('click', function () {
      clearMarketHotspotFilters(store);
      renderMarketHotspot();
    });
    var moreGroups = nodes.marketHotspot.querySelector('[data-hotspot-more-groups]');
    if (moreGroups) moreGroups.addEventListener('click', function () {
      store.showAllGroups = true;
      renderMarketHotspot();
    });
    Array.prototype.forEach.call(nodes.marketHotspot.querySelectorAll('[data-hotspot-group-more]'), function (button) {
      button.addEventListener('click', function () {
        store.expandedGroups[button.getAttribute('data-hotspot-group-more')] = true;
        renderMarketHotspot();
      });
    });
    var more = nodes.marketHotspot.querySelector('[data-hotspot-more]');
    if (more) more.addEventListener('click', function () {
      store.visibleLimit += 30;
      renderMarketHotspot();
    });
    Array.prototype.forEach.call(nodes.marketHotspot.querySelectorAll('[data-hotspot-open]'), function (button) {
      button.addEventListener('click', function () {
        var key = button.getAttribute('data-hotspot-open');
        var item = asArray(store.model && store.model.items).find(function (entry) {
          return entry.key === key;
        });
        if (!item) return;
        store.returnFocus = button;
        openMarketHotspotDetail(item);
      });
    });
  }

  function renderMarketHotspot() {
    if (!nodes.marketHotspot) return;
    var store = marketHotspotState();
    try {
      store.model = buildMarketHotspotModel(state.data || {});
      nodes.marketHotspot.outerHTML = renderMarketHotspotSection(store.model, store);
      nodes.marketHotspot = document.getElementById('marketHotspotSection');
      bindMarketHotspotControls();
    } catch (error) {
      nodes.marketHotspot.innerHTML = '<div class="hotspot-empty"><strong>热点个股暂不可用</strong>'
        + '<span>其他日报内容继续可用。</span></div>';
    }
  }

  function primaryDisplayMainRows(viewContext) {
    var views = viewContext && typeof viewContext === 'object'
      ? viewContext : ((state.workspace || {}).views || {});
    var rows = asArray(views.main);
    if (!viewContext && getStrategyViewBlockingReason(state.data || {}, 'main')) return [];
    return rows;
  }

  function selectPrimaryDisplayItems(projection, mainRows) {
    var value = projection && typeof projection === 'object' ? projection : {};
    var canonical = asArray(value.items);
    var featured = {};
    asArray(value.featured_ids).forEach(function (id) {
      id = normalizeString(id).trim();
      if (id) featured[id] = true;
    });
    var main = asArray(mainRows);
    var mainIdentities = {};
    main.forEach(function (item) {
      var identity = primaryDisplaySecurityIdentity(item);
      if (identity) mainIdentities[identity] = true;
    });
    var selected = [];
    var seen = {};
    function append(item) {
      var identity = primaryDisplaySecurityIdentity(item);
      if (!identity || seen[identity]) return;
      seen[identity] = true;
      selected.push(item);
    }
    canonical.forEach(function (item) {
      var identity = primaryDisplaySecurityIdentity(item);
      if (isFormalWorkbenchItem(item)
          || featured[normalizeString(item && item.id).trim()]
          || (identity && mainIdentities[identity])) append(item);
    });
    main.forEach(append);
    return selected;
  }

  function resolvePrimaryNavigationState(viewKey, projectionAvailable) {
    var key = normalizeString(viewKey).trim();
    var enabled = projectionAvailable === undefined
      ? Boolean(getDecisionWorkbench()) : Boolean(projectionAvailable);
    if (!enabled) return { viewKey: key, statusFilter: '' };
    if (key === 'decision_wait') {
      return { viewKey: 'decision_formal', statusFilter: 'formal_incomplete' };
    }
    if (key === 'decision_focus' || key === 'main' || key === 'decision_formal') {
      return { viewKey: 'decision_formal', statusFilter: '' };
    }
    return { viewKey: key, statusFilter: '' };
  }

  function primaryDisplayStatus(item) {
    var value = item && item.workbench_item ? item.workbench_item : (item || {});
    return normalizeString(value.page_status).trim();
  }

  function primaryDisplayMatchesStatus(item, statusFilter) {
    var value = item && item.workbench_item ? item.workbench_item : (item || {});
    var status = normalizeString(statusFilter).trim();
    if (!status) return true;
    if (status === 'formal_incomplete') {
      return primaryDisplayStatus(value) === status && isFormalWorkbenchItem(value);
    }
    return primaryDisplayStatus(value) === status;
  }

  function decisionRows(projection, key, viewContext) {
    var value = projection && typeof projection === 'object' ? projection : {};
    var canonical = asArray(value.items);
    var resolved = resolvePrimaryNavigationState(key, true);
    var rows;
    if (resolved.viewKey === 'decision_formal') {
      rows = selectPrimaryDisplayItems(value, primaryDisplayMainRows(viewContext));
      if (resolved.statusFilter) {
        rows = rows.filter(function (item) {
          return primaryDisplayMatchesStatus(item, resolved.statusFilter);
        });
      }
    } else {
      rows = canonical.filter(function (item) {
        if (resolved.viewKey === 'decision_blocked') {
          return ['evidence_blocked', 'strategy_disagreement', 'invalidated'].indexOf(item.page_status) !== -1
            || asArray(item.risk_flags).length > 0;
        }
        return true;
      });
    }
    return rows.map(function (item, index) {
      if (canonical.indexOf(item) === -1) {
        return Object.assign({}, item, {
          view_rank: index + 1,
          evidence_view: item.evidence_view || 'main',
        });
      }
      return Object.assign({}, item.candidate || {}, {
        code: item.code, name: item.name, view_rank: index + 1,
        evidence_view: item.evidence_view, workbench_item: item,
      });
    });
  }

  function decisionNavigation() {
    return [{ key: 'decision_formal', label: '主推' }, { key: 'decision_all', label: '全部' },
      { key: 'decision_blocked', label: '待核验 / 风险' }];
  }

  function decisionOverviewCounts() {
    var projection = getDecisionWorkbench();
    var primary = null;
    var formal = 0;
    var research = 0;
    var seen = {};
    if (projection) {
      primary = selectPrimaryDisplayItems(
        projection, primaryDisplayMainRows()
      ).length;
      formal = asArray(projection.items).filter(isFormalWorkbenchItem).length;
      asArray(projection.items).forEach(function (item) {
        var rec = item || {};
        if (isFormalWorkbenchItem(rec)) return;
        var code = toCodeKey(rec.code || (rec.candidate || {}).code || rec.id);
        var key = code || normalizeString(rec.id);
        if (key && !seen[key]) {
          seen[key] = true;
          research += 1;
        }
      });
    }
    if (!projection) {
      var workspace = state.workspace && typeof state.workspace === 'object' ? state.workspace : null;
      var rawViews = workspace && workspace.views && typeof workspace.views === 'object'
        ? workspace.views : null;
      var formalKeys = ['main', 'h4_t3'].filter(function (key) {
        return rawViews && Array.isArray(rawViews[key]);
      });
      var researchKeys = ['highlights', 'observation_top5', 'acceleration', 'luojie', 'confirming', 'growth_quality'].filter(function (key) {
        return rawViews && Array.isArray(rawViews[key]);
      });
      if (!formalKeys.length && !researchKeys.length) {
        return { primary: null, formal: null, research: null, capability: 'unavailable' };
      }
      var formalSeen = {};
      formalKeys.forEach(function (key) {
        rawViews[key].forEach(function (item) {
          var rec = item || {};
          var identifier = toCodeKey(rec.code || rec.id || (rec.candidate || {}).code);
          if (!identifier || formalSeen[identifier]) return;
          if (isFormalWorkbenchItem(rec) || normalizeString(rec.action_semantics) === 'formal' || key === 'main' || key === 'h4_t3') {
            formalSeen[identifier] = true;
            formal += 1;
          }
        });
      });
      if (!researchKeys.length) {
        research = null;
      } else {
        researchKeys.forEach(function (key) {
          rawViews[key].forEach(function (item) {
            var rec = item || {};
            var identifier = toCodeKey(rec.code || rec.id || (rec.candidate || {}).code);
            if (identifier && !seen[identifier] && !isFormalWorkbenchItem(rec)) {
              seen[identifier] = true;
              research += 1;
            }
          });
        });
      }
      return { primary: formal, formal: formal, research: research, capability: 'available' };
    }
    return { primary: primary, formal: formal, research: research, capability: 'available' };
  }

  function decisionOverviewCountText(value) {
    return value === null || value === undefined ? '未提供' : String(value);
  }

  function legacyObservationViewKey() {
    var workspace = state.workspace && typeof state.workspace === 'object' ? state.workspace : null;
    var views = workspace && workspace.views && typeof workspace.views === 'object'
      ? workspace.views : null;
    if (!views) return '';
    return ['highlights', 'observation_top5', 'confirming', 'acceleration', 'luojie', 'growth_quality'].find(function (key) {
      return Array.isArray(views[key]);
    }) || '';
  }

  function decisionOverviewGaps(summary) {
    var value = summary && typeof summary === 'object' ? summary : {};
    var coverage = value.coverage && typeof value.coverage === 'object' ? value.coverage : {};
    var gaps = [];
    if (normalizeString(coverage.status) && normalizeString(coverage.status) !== 'verified') {
      gaps.push(normalizeString(coverage.status) === 'partial' ? '部分数据缺口' : '正式输入待核验');
    }
    var quantity = coverage.quantity && typeof coverage.quantity === 'object' ? coverage.quantity : {};
    if (['partial', 'unavailable'].indexOf(normalizeString(quantity.status)) !== -1) {
      gaps.push('量能' + (normalizeString(quantity.status) === 'partial' ? '部分缺失' : '不可用'));
    }
    var minute = coverage.minute30 && typeof coverage.minute30 === 'object' ? coverage.minute30 : {};
    if (safeNumber(minute.missing, 0) > 0 || normalizeString(minute.status) === 'partial') {
      gaps.push('短周期确认有缺口');
    }
    var quality = (state.data || {}).data_quality || {};
    asArray(quality.warnings).slice(0, 2).forEach(function (warning) {
      var text = normalizeString(warning).trim();
      if (text && gaps.indexOf(text) === -1) gaps.push(text);
    });
    return gaps.slice(0, 3);
  }

  function renderDecisionOverviewLinks() {
    return '<nav class="decision-overview-links" aria-label="本页快捷入口">'
      + '<a href="#marketDecisionBar">大盘依据</a>'
      + '<a href="#candidateWorkspace">候选工作台</a>'
      + '<a href="#marketHotspotSection">热点地图</a>'
      + '<a href="#personalWatchlistSection">我的关注</a>'
      + '<a href="#reportChanges">本期变化</a>'
      + '</nav>';
  }

  function renderDecisionOverview() {
    var projection = getDecisionWorkbench();
    var mount = document.getElementById('decisionOverview');
    if (!mount) return;
    mount.hidden = false;
    if (!projection) {
      var legacyCounts = decisionOverviewCounts();
      mount.innerHTML = '<div class="decision-overview-main"><h2>本期选股结论</h2>'
        + '<p>本期未生成统一清单，按原始策略视图展示；证据能力以本期记录为准。</p>'
        + '<div class="decision-overview-counts"><span><small>主推</small><strong>' + escapeHtml(decisionOverviewCountText(legacyCounts.primary)) + '</strong></span>'
        + '<span><small>研究观察</small><strong>' + escapeHtml(decisionOverviewCountText(legacyCounts.research)) + '</strong></span>'
        + '<span class="decision-overview-gap"><small>关键缺口</small><strong>'
        + escapeHtml(legacyCounts.capability === 'available' ? '统一清单未提供；旧版视图可部分汇总' : '旧版汇总能力未提供')
        + '</strong></span></div>'
        + renderDecisionOverviewLinks() + '</div>'
        + '<small class="decision-overview-note">旧版报告能力边界</small>';
      renderMobileDecisionSummary(null);
      return;
    }
    var summary = projection.summary || {};
    var changes = projection.changes || {};
    var changesText = renderDecisionChangesSummary(changes, false);
    var coverage = summary.coverage || {};
    var coverageText = renderCoverageSummary(coverage);
    var counts = decisionOverviewCounts();
    var gaps = decisionOverviewGaps(summary);
    var gapText = gaps.length ? gaps.join(' · ') : '关键数据缺口：未记录';
    mount.innerHTML = '<div class="decision-overview-main"><h2>' + escapeHtml(summary.title) + '</h2><p>'
      + escapeHtml(summary.reason) + '</p>' + buildFormalOutcomeExplanation(summary, state.data || {})
      + '<div class="decision-overview-counts"><span><small>主推</small><strong>' + escapeHtml(decisionOverviewCountText(counts.primary)) + '</strong></span>'
      + '<span><small>研究观察</small><strong>' + escapeHtml(decisionOverviewCountText(counts.research)) + '</strong></span>'
      + '<span class="decision-overview-gap"><small>关键缺口</small><strong>' + escapeHtml(gapText) + '</strong></span></div>'
      + '<p class="decision-overview-coverage">' + escapeHtml(coverageText) + '</p>'
      + renderDecisionOverviewLinks()
      + '</div><small class="decision-overview-note">' + escapeHtml(changesText) + '</small>';
    renderMobileDecisionSummary(projection);
  }

  function renderMobileDecisionSummary(projection) {
    var mount = nodes.mobileDecisionSummary;
    if (!mount) return;
    mount.hidden = false;
    if (!projection) {
      mount.innerHTML = '<strong>旧版报告</strong><span>本期未生成统一清单</span>';
      return;
    }
    var summary = projection.summary || {};
    var changes = projection.changes || {};
    var coverageText = renderCoverageSummary(summary.coverage || {});
    var changesText = renderDecisionChangesSummary(changes, true);
    mount.innerHTML = '<div class="mobile-decision-summary-copy"><strong>' + escapeHtml(summary.title || '本期结论未提供') + '</strong>'
      + '<span>' + escapeHtml(summary.reason || '结论说明未提供') + '</span>'
      + '<small>' + escapeHtml(coverageText + ' · ' + changesText) + '</small></div>'
      + '<a href="#decisionOverview">查看完整结论与策略拆解 ↓</a>';
  }

  function renderDecisionChangesSummary(changes, compact) {
    var value = changes && typeof changes === 'object' ? changes : {};
    var status = normalizeString(value.status).trim();
    var counts = '新增 ' + asArray(value.added).length + ' · 移出 '
      + asArray(value.removed).length + ' · 条件变化 ' + asArray(value.changed).length;
    if (status === 'available') return '较前期：' + counts;
    if (status === 'partial') {
      var suffix = value.value_comparison_status === 'unavailable_price_basis_missing'
        ? '；部分标的价基缺失或换基，相关数值未比较' : '；部分项目不可比较';
      return (compact ? '较前期（成员级）：' : '较前期（部分可比）：') + counts + suffix;
    }
    var reasons = {
      comparison_identity_changed: '策略身份变化，未比较',
      price_basis_changed: '价基变化，未比较',
      price_basis_invalid: '价基声明无效，未比较',
      previous_comparison_contract_unavailable: '前期身份合同缺失，未比较',
      comparison_contract_unavailable_or_changed: '身份合同缺失，未比较',
      comparison_health_unavailable: '事实健康度不足，未比较',
    };
    return reasons[normalizeString(value.reason).trim()] || '跨期暂无同口径结论';
  }

  function decisionChangeCode(entry) {
    if (entry && typeof entry === 'object') {
      return normalizeString(entry.code || entry.stock_code || entry.symbol
        || entry.candidate_code || entry.id).trim();
    }
    return normalizeString(entry).trim();
  }

  function decisionIdentityToken(value) {
    var text = normalizeString(value).trim();
    if (text.length <= 24) return text;
    return text.slice(0, 12) + '…' + text.slice(-8);
  }

  function decisionChangeFieldText(entry) {
    if (!entry || typeof entry !== 'object') return '';
    var fields = entry.changed_fields || entry.fields || entry.changes || entry.changed;
    if (Array.isArray(fields)) return fields.map(normalizeString).filter(Boolean).join('、');
    if (fields && typeof fields === 'object') return Object.keys(fields).join('、');
    return normalizeString(fields).trim();
  }

  function decisionChangeReason(entry, changes, code) {
    var value = entry && typeof entry === 'object' ? entry : {};
    var reasons = changes && changes.value_unavailable_reasons
      && typeof changes.value_unavailable_reasons === 'object'
      ? changes.value_unavailable_reasons : {};
    var reason = normalizeString(value.reason || value.change_reason || value.why
      || value.status_reason || reasons[code]
      || (changes && (changes.value_comparison_reason || changes.reason))).trim();
    var labels = {
      price_basis_missing: '价基缺失，价格数值不可比',
      price_basis_changed: '价基变化，价格数值不可比',
      price_basis_invalid: '价基声明无效，价格数值不可比',
      version_conflict: '版本冲突，仅展示可比字段',
      comparison_identity_changed: '策略身份变化，不能作同口径比较',
      comparison_contract_unavailable_or_changed: '前期身份合同缺失，不能作同口径比较',
      comparison_health_unavailable: '事实健康度不足，不能作完整比较',
    };
    if (labels[reason]) return labels[reason];
    if (reason) return reason;
    var fields = decisionChangeFieldText(entry);
    return fields ? '变化字段：' + fields : '';
  }

  function decisionChangeName(entry, projection) {
    var code = decisionChangeCode(entry);
    var direct = entry && typeof entry === 'object'
      ? normalizeString(entry.name || entry.stock_name).trim() : '';
    if (direct) return direct;
    var items = projection && Array.isArray(projection.items) ? projection.items : [];
    var found = items.find(function (item) {
      return decisionChangeCode(item) === code;
    });
    if (found) return normalizeString(found.name || (found.candidate || {}).name).trim();
    return code;
  }

  function decisionChangeSource(entry, projection) {
    var value = entry && typeof entry === 'object' ? entry : {};
    var source = normalizeString(value.source_strategy || value.strategy_id
      || value.source || value.view).trim();
    if (source) return comparisonStrategyLabel(source);
    var identities = projection && projection.comparison_contract
      && Array.isArray(projection.comparison_contract.strategy_identities)
      ? projection.comparison_contract.strategy_identities : [];
    if (identities.length === 1) return comparisonStrategyLabel(identities[0].strategy_id);
    return '来源策略未单独记录';
  }

  function findCurrentCandidateForCode(code, requestedView) {
    var targetCode = toCodeKey(code);
    if (!targetCode) return null;
    var projection = getDecisionWorkbench();
    if (projection) {
      var projected = asArray(projection.items).find(function (item) {
        return toCodeKey(item && item.code) === targetCode;
      });
      if (projected) {
        return Object.assign({}, projected.candidate || {}, {
          code: projected.code,
          name: projected.name || (projected.candidate || {}).name,
          evidence_view: projected.evidence_view,
          workbench_item: projected,
        });
      }
    }
    var views = getCandidateViews().views || {};
    var order = [requestedView, state.currentView, 'decision_all', 'main', 'h4_t3',
      'confirming', 'observation_top5', 'growth_quality', 'highlights', 'baseline'];
    var seen = {};
    for (var index = 0; index < order.length; index += 1) {
      var key = normalizeString(order[index]).trim();
      if (!key || seen[key]) continue;
      seen[key] = true;
      var found = asArray(views[key]).find(function (item) {
        return toCodeKey(item && item.code) === targetCode;
      });
      if (found) return found;
    }
    return null;
  }

  function openCurrentCandidateDetail(code, requestedView) {
    var targetCode = toCodeKey(code);
    var candidate = findCurrentCandidateForCode(targetCode, requestedView);
    if (!candidate) return false;
    var views = getCandidateViews().views || {};
    var destination = normalizeString(requestedView).trim();
    if (!destination || !views[destination]
        || !asArray(views[destination]).some(function (item) {
          return toCodeKey(item && item.code) === targetCode;
        })) {
      destination = state.currentView;
    }
    if (destination && destination !== state.currentView && views[destination]) {
      activateWorkspaceView(destination, false);
      candidate = findCurrentCandidateForCode(targetCode, destination) || candidate;
    }
    state.candidateQuery = '';
    state.candidateLimit = Math.max(Number(state.candidateLimit) || 20, 20);
    if (nodes.candidateSearch) nodes.candidateSearch.value = '';
    beginCandidateSelection(candidate);
    refreshCandidateWorkspace();
    renderCandidateDetail(candidate);
    if (state.isMobile) {
      openMobileDetailDrawer(candidate, targetCode);
    } else {
      if (nodes.detailPanel && typeof nodes.detailPanel.scrollIntoView === 'function') {
        nodes.detailPanel.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
      if (nodes.candidateList && typeof nodes.candidateList.querySelector === 'function') {
        var row = nodes.candidateList.querySelector('[data-code="' + targetCode + '"]');
        if (row && typeof row.focus === 'function') row.focus();
      }
    }
    return true;
  }

  function openDecisionChangeCurrentChart(code, requestedView) {
    return openCurrentCandidateDetail(code, requestedView);
  }

  function decisionChangeEntryText(kind, entry, projection, changes) {
    var code = decisionChangeCode(entry) || '未提供股票代码';
    var name = decisionChangeName(entry, projection) || code;
    var source = decisionChangeSource(entry, projection);
    var value = entry && typeof entry === 'object' ? entry : {};
    var date = normalizeString(value.report_date || value.date || projection.report_date).trim();
    var phase = normalizeString(value.phase || projection.phase).trim();
    var reason = decisionChangeReason(entry, changes, code);
    var label = kind === 'added' ? '本期加入当前集合'
      : (kind === 'removed' ? '移出本期集合（不等于破位）'
        : (kind === 'unavailable' ? '部分字段不可比较' : '状态或条件变化'));
    var previousIdentity = decisionHistoryPreviousIdentity(changes);
    var previousDate = kind === 'removed' && previousIdentity.date
      ? '上一有效快照 ' + previousIdentity.date : '';
    var details = [source, date ? '当前 ' + date : '', previousDate,
      phase ? '阶段 ' + phase : '', reason].filter(Boolean).join(' · ');
    var view = normalizeString(value.view || value.source_strategy || value.strategy_id).trim();
    var currentCandidate = findCurrentCandidateForCode(code, view);
    var currentAction = currentCandidate
      ? '<button type="button" class="decision-change-current-button" data-change-current="'
        + escapeHtml(code) + '" data-change-current-view="' + escapeHtml(view)
        + '">查看当前图表</button>' : '';
    return '<li><div class="decision-change-entry"><button type="button" class="decision-change-item" data-change-drill="'
      + escapeHtml(code) + '" data-change-kind="' + escapeHtml(kind)
      + '" data-change-code="' + escapeHtml(code)
      + '" data-change-view="' + escapeHtml(view) + '"><strong>'
      + escapeHtml(name) + '</strong><span>' + escapeHtml(code) + '</span><small>'
      + escapeHtml(label + (details ? ' · ' + details : ''))
      + '</small></button>' + currentAction + '<button type="button" class="decision-change-history-button" data-change-history="'
      + escapeHtml(code) + '">查看已有快照</button></div></li>';
  }

  function decisionHistoryDataUrl(dateStr) {
    var date = normalizeString(dateStr).trim();
    if (!date) return '';
    var path = normalizeString(window.location && window.location.pathname).replace(/\/+$/, '');
    var prefix = /\/\d{4}-\d{2}-\d{2}(?:\/index\.html)?$/.test(path) ? '../' : '';
    return prefix + 'data/' + date + '.json';
  }

  function decisionHistoryPreviousIdentity(source) {
    var value = source && source.changes && typeof source.changes === 'object'
      ? source.changes : (source || {});
    var nested = value.previous_snapshot && typeof value.previous_snapshot === 'object'
      ? value.previous_snapshot : {};
    return {
      date: normalizeString(value.previous_report_date || nested.report_date || nested.date).trim(),
      phase: normalizeString(value.previous_phase || nested.phase).trim(),
      snapshot: normalizeString(value.previous_snapshot_id || nested.snapshot_id || nested.id).trim(),
      version: normalizeString(value.previous_version || nested.version).trim(),
      priceBasis: nested.price_basis || value.previous_price_basis || value.previous_price_basis_id || '',
    };
  }

  function decisionHistoryPayloadIdentity(payload) {
    var value = payload && typeof payload === 'object' ? payload : {};
    var nested = value.snapshot && typeof value.snapshot === 'object' ? value.snapshot : {};
    var workbench = value.decisionWorkbench && typeof value.decisionWorkbench === 'object'
      ? value.decisionWorkbench : {};
    var quality = value.data_quality && typeof value.data_quality === 'object'
      ? value.data_quality : {};
    var phase = normalizeString(value.phase || value.report_phase || workbench.phase).trim();
    if (!phase && quality.is_official === true && normalizeString(quality.bar_state).trim() === 'closed') {
      phase = 'formal';
    }
    return {
      date: normalizeString(value.report_date || value.date || quality.date).trim(),
      phase: phase,
      snapshot: normalizeString(value.snapshot_id || value.payload_hash || nested.snapshot_id || nested.id).trim(),
      version: normalizeString(value.version || value.snapshot_version || nested.version).trim(),
      priceBasis: value.price_basis || value.priceBasis || nested.price_basis || quality.price_basis || '',
    };
  }

  function decisionHistoryBasisKey(value) {
    if (value && typeof value === 'object') {
      return normalizeString(value.adjustment || value.basis || value.id).trim();
    }
    return normalizeString(value).trim();
  }

  function decisionHistoryDateKey(value) {
    var match = normalizeString(value).trim().match(/^\d{4}-\d{2}-\d{2}/);
    return match ? match[0] : normalizeString(value).trim();
  }

  function decisionHistoryRowFields(row) {
    var value = row && typeof row === 'object' ? row : {};
    var nested = value.snapshot && typeof value.snapshot === 'object' ? value.snapshot : {};
    return {
      date: normalizeString(value.report_date || value.date).trim(),
      phase: normalizeString(value.phase).trim(),
      version: normalizeString(value.version || nested.version).trim(),
      strategyVersion: normalizeString(value.strategy_version).trim(),
      snapshot: normalizeString(value.snapshot_id || nested.snapshot_id || nested.id).trim(),
      priceBasis: value.price_basis || '',
    };
  }

  function validateDecisionHistoryRow(row, expected) {
    var target = expected && typeof expected === 'object' ? expected : {};
    var actual = decisionHistoryRowFields(row);
    function compare(expectedValue, actualValue, normalize) {
      var wanted = normalize(expectedValue);
      var found = normalize(actualValue);
      if (!wanted) return { status: 'not_declared', wanted: '', found: found };
      if (!found) return { status: 'unverified', wanted: wanted, found: '' };
      return { status: wanted === found ? 'verified' : 'conflict', wanted: wanted, found: found };
    }
    var date = compare(target.date, actual.date, decisionHistoryDateKey);
    var phase = compare(target.phase, actual.phase, function (value) {
      return normalizeString(value).trim().toLowerCase();
    });
    var version = compare(target.version, actual.version, normalizeString);
    var snapshot = compare(target.snapshot, actual.snapshot, normalizeString);
    var priceBasis = compare(target.priceBasis, actual.priceBasis, decisionHistoryBasisKey);
    var reasons = [];
    if (date.status === 'conflict') reasons.push('来源日期冲突');
    else if (date.status === 'unverified') reasons.push('来源日期未核验');
    if (phase.status === 'conflict') reasons.push('来源阶段冲突');
    else if (phase.status === 'unverified') reasons.push('来源阶段未核验');
    if (version.status === 'conflict') reasons.push('来源版本冲突');
    else if (version.status === 'unverified') reasons.push('来源版本未核验');
    if (snapshot.status === 'conflict') reasons.push('来源快照标识冲突');
    else if (snapshot.status === 'unverified') reasons.push('来源快照标识未核验');
    if (priceBasis.status === 'conflict') reasons.push('来源价基冲突');
    else if (priceBasis.status === 'unverified') reasons.push('来源价基未核验');
    var identityFields = [date, phase, version, snapshot];
    var identityDeclared = identityFields.some(function (item) { return item.status !== 'not_declared'; });
    return {
      identityComparable: identityDeclared && identityFields.every(function (item) { return item.status === 'verified'; }),
      priceComparable: priceBasis.status === 'verified',
      dateStatus: date.status,
      phaseStatus: phase.status,
      versionStatus: version.status,
      snapshotStatus: snapshot.status,
      priceBasisStatus: priceBasis.status,
      reasons: reasons,
    };
  }

  function validateDecisionHistoryPayload(payload, expected) {
    var target = expected && typeof expected === 'object' ? expected : {};
    var actual = decisionHistoryPayloadIdentity(payload);
    function compare(expectedValue, actualValue, normalize) {
      var wanted = normalize(expectedValue);
      var found = normalize(actualValue);
      if (!wanted) return { status: 'not_declared', wanted: '', found: found };
      if (!found) return { status: 'unverified', wanted: wanted, found: '' };
      return { status: wanted === found ? 'verified' : 'conflict', wanted: wanted, found: found };
    }
    var date = compare(target.date, actual.date, decisionHistoryDateKey);
    var phase = compare(target.phase, actual.phase, function (value) {
      return normalizeString(value).trim().toLowerCase();
    });
    var version = compare(target.version, actual.version, normalizeString);
    var snapshot = compare(target.snapshot, actual.snapshot, normalizeString);
    var priceBasis = compare(target.priceBasis, actual.priceBasis, decisionHistoryBasisKey);
    var reasons = [];
    if (date.status === 'conflict') reasons.push('历史快照日期不一致');
    else if (date.status === 'unverified') reasons.push('历史快照日期未核验');
    if (phase.status === 'conflict') reasons.push('历史快照阶段冲突');
    else if (phase.status === 'unverified') reasons.push('历史快照阶段未核验');
    if (version.status === 'conflict') reasons.push('历史快照版本冲突');
    else if (version.status === 'unverified') reasons.push('历史快照版本未核验');
    if (snapshot.status === 'conflict') reasons.push('历史快照标识冲突');
    else if (snapshot.status === 'unverified') reasons.push('历史快照标识未核验');
    if (priceBasis.status === 'conflict') reasons.push('历史快照价基冲突');
    else if (priceBasis.status === 'unverified') reasons.push('历史快照价基未核验');
    var datePhaseValid = date.status === 'verified' && phase.status !== 'conflict';
    return {
      ok: datePhaseValid,
      dateStatus: date.status,
      phaseStatus: phase.status,
      versionStatus: version.status,
      snapshotStatus: snapshot.status,
      priceBasisStatus: priceBasis.status,
      priceComparable: priceBasis.status === 'verified',
      identityComparable: datePhaseValid
        && phase.status === 'verified'
        && ['conflict', 'unverified', 'not_declared'].indexOf(version.status) === -1
        && ['conflict', 'unverified', 'not_declared'].indexOf(snapshot.status) === -1,
      reasons: reasons,
    };
  }

  function decisionHistoryRowIdentity(row, sourceKey) {
    var value = row && typeof row === 'object' ? row : {};
    var nested = value.snapshot && typeof value.snapshot === 'object' ? value.snapshot : {};
    var fields = decisionHistoryRowFields(value);
    var strategies = asArray(value.strategy_results).map(function (strategy) {
      return normalizeString(strategy && (strategy.strategy_id || strategy.strategy_version || strategy.version)).trim();
    }).filter(Boolean).join('+');
    return [sourceKey, fields.snapshot, fields.version, fields.phase, strategies,
      decisionHistoryBasisKey(fields.priceBasis)].join('|');
  }

  function decisionHistoryEntries(payload, code, projection, expectedIdentity) {
    var source = payload && typeof payload === 'object' ? payload : {};
    var targetCode = toCodeKey(code);
    var entries = [];
    var identity = expectedIdentity && typeof expectedIdentity === 'object' ? expectedIdentity : {};
    var hasExpectedIdentity = [identity.date, identity.phase, identity.version,
      identity.snapshot, identity.priceBasis].some(function (value) { return normalizeString(value).trim(); });
    function append(row, sourceKey) {
      if (!row || toCodeKey(row.code) !== targetCode) return;
      entries.push({ record: row, source: sourceKey, identity: decisionHistoryRowIdentity(row, sourceKey),
        validation: hasExpectedIdentity ? validateDecisionHistoryRow(row, identity) : null });
    }
    if (projection && Array.isArray(projection.items)) {
      projection.items.forEach(function (row) { append(row, '统一决策清单'); });
    }
    var views = source.workspace && source.workspace.views && typeof source.workspace.views === 'object'
      ? source.workspace.views : {};
    Object.keys(views).forEach(function (viewKey) {
      asArray(views[viewKey]).forEach(function (row) {
        append(row, comparisonStrategyLabel(viewKey));
      });
    });
    // Keep raw pools as an attached provenance source even when projection or
    // workspace rows exist.  Identity validation belongs to each row; a
    // preferred version must not erase a conflicting source record.
    ['picks_fusion', 'picks_pure', 'startup_watchlist', 'observation_watchlist',
      'next_day_boom', 'luojie_pool', 'h4_t3_pool'].forEach(function (poolKey) {
      var value = source[poolKey];
      var rows = value && typeof value === 'object' && !Array.isArray(value)
        ? value.candidates : value;
      asArray(rows).forEach(function (row) { append(row, comparisonStrategyLabel(poolKey)); });
    });
    return entries;
  }

  function decisionHistoryIdentityText(identity) {
    var value = identity && typeof identity === 'object' ? identity : {};
    return [
      value.date ? '日期 ' + value.date : '日期未记录',
      value.phase ? '阶段 ' + value.phase : '阶段未记录',
      value.version ? '版本 ' + value.version : '版本未记录',
      value.snapshot ? '快照标识 ' + decisionIdentityToken(value.snapshot) : '',
    ].filter(Boolean).join(' · ');
  }

  function decisionHistorySourceRows(entry) {
    var row = entry && entry.record ? entry.record : {};
    var defaultSource = entry && entry.source ? entry.source : '来源策略未记录';
    var workbench = row.workbench_item && typeof row.workbench_item === 'object'
      ? row.workbench_item : row;
    var strategies = asArray(workbench.strategy_results);
    if (!strategies.length) strategies = [row];
    return strategies.map(function (strategy) {
      var value = strategy && typeof strategy === 'object' ? strategy : {};
      var sourceId = value.strategy_id || (defaultSource === '统一决策清单' ? 'main' : defaultSource);
      var source = comparisonStrategySource(value);
      var evidence = value.evidence && typeof value.evidence === 'object' ? value.evidence : {};
      var daily = evidence.daily_structure && typeof evidence.daily_structure === 'object'
        ? evidence.daily_structure : {};
      var risk = evidence.risk_and_next && typeof evidence.risk_and_next === 'object'
        ? evidence.risk_and_next : {};
      var contract = value.contract && typeof value.contract === 'object'
        ? value.contract : (value.formal_decision_contract || {});
      var contractReference = isRecommendationEvidenceFiniteNumber(contract.reference_price)
        ? Number(contract.reference_price) : null;
      var rawReference = safeNumber(value.reference_price, null);
      if (rawReference === null) rawReference = safeNumber(row.reference_price, null);
      var purposeStatus = referencePurposeStatus(value) || referencePurposeStatus(row);
      var reference = contractReference;
      if (reference === null && rawReference !== null && purposeStatus !== 'unverified'
          && purposeStatus !== 'raw_reference') reference = rawReference;
      var invalidation = contract.invalidation_price;
      if (!isRecommendationEvidenceFiniteNumber(reference) && purposeStatus !== 'unverified'
          && purposeStatus !== 'raw_reference') reference = row.reference_price;
      if (!isRecommendationEvidenceFiniteNumber(invalidation)) invalidation = row.invalidation_price;
      var priceBasisValue = row.price_basis || contract.price_basis;
      var priceBasis = priceBasisValue && typeof priceBasisValue === 'object'
        ? (priceBasisValue.adjustment || priceBasisValue.basis || '') : priceBasisValue;
      var riskValues = asArray(row.risk_flags).map(normalizeString).filter(Boolean)
        .concat(recommendationEvidenceList(risk.risk_labels));
      var roleValue = normalizeString(value.role || row.role || row.action_semantics).trim() || '身份未记录';
      var roleLabels = { formal: '正式', research: '研究', baseline: '基础候选', diagnostic: '事故复盘' };
      var nextBlock = risk.next_confirmation && typeof risk.next_confirmation === 'object'
        ? risk.next_confirmation : {};
      var cancelBlock = risk.invalidation_conditions && typeof risk.invalidation_conditions === 'object'
        ? risk.invalidation_conditions
        : (risk.cancel_conditions && typeof risk.cancel_conditions === 'object'
          ? risk.cancel_conditions : {});
      var nextValues = recommendationEvidenceList(nextBlock.items);
      var cancelValues = recommendationEvidenceList(cancelBlock.items);
      return {
        source: value.strategy_id ? comparisonStrategyLabel(value.strategy_id) : comparisonStrategyLabel(sourceId),
        sourceId: normalizeString(value.strategy_id || sourceId).trim(),
        sourceRef: normalizeString(value.source || (evidence.summary || {}).source || defaultSource).trim(),
        role: roleLabels[roleValue] || roleValue,
        action: source.action,
        horizon: source.horizon,
        score: source.score,
        reference: reference,
        invalidation: invalidation,
        rawReference: rawReferenceText(row, contractReference),
        priceBasis: normalizeString(priceBasis).trim(),
        contractId: source.contractId,
        condition: normalizeString(value.page_status || row.page_status || row.status).trim() || '条件未声明',
        structure: quickEvidenceText(daily) || normalizeString(row.primary_reason).trim() || '结构依据未声明',
        unmet: asArray(value.blocking_reasons || value.blocked_reasons || row.blocking_reasons || row.blocked_reasons)
          .map(normalizeString).filter(Boolean).join('、') || '未满足条件未声明',
        risk: riskValues.filter(function (item, index, all) {
          return item && all.indexOf(item) === index;
        }).join('、') || '风险未登记',
        next: nextValues,
        cancel: cancelValues,
        freshness: normalizeString((evidence.summary || {}).as_of
          || (row.data_status || {}).latest_date).trim() || '数据时效未记录',
        evidence: source.evidenceStatus,
        reportVersion: normalizeString(row.version || (row.snapshot || {}).version).trim() || '版本未记录',
        strategyVersion: normalizeString(value.strategy_version || value.version).trim() || '策略版本未记录',
      };
    });
  }

  function renderDecisionHistorySource(entry, validation) {
    var rows = decisionHistorySourceRows(entry);
    var rowValidation = entry && entry.validation ? entry.validation : null;
    var effectiveValidation = rowValidation || validation;
    return rows.map(function (row) {
      var prices = [
        isRecommendationEvidenceFiniteNumber(row.reference) ? '参考价 ' + recommendationEvidenceNumber(row.reference, 2) : '',
        isRecommendationEvidenceFiniteNumber(row.invalidation) ? '失效位 ' + recommendationEvidenceNumber(row.invalidation, 2) : '',
        row.priceBasis ? '价基 ' + row.priceBasis : '',
        row.contractId ? '合同 ' + row.contractId : '',
        row.rawReference,
      ].filter(Boolean).join(' · ') || '价格合同未记录';
      if (effectiveValidation && effectiveValidation.priceComparable === false) {
        prices = '价格合同未核验，数值不可比 · ' + prices;
      }
      var score = row.score === null || row.score === undefined ? '分数未记录' : '分数 ' + recommendationEvidenceNumber(row.score);
      var condition = row.condition;
      if (effectiveValidation && effectiveValidation.identityComparable !== true) {
        condition += ' · 来源身份未核验，不作价格/升级可比';
      }
      var conditionDetails = [
        row.next.length ? '下一核验：' + row.next.join('、') : '',
        row.cancel.length ? '取消条件：' + row.cancel.join('、') : '',
      ].filter(Boolean).join(' · ');
      if (conditionDetails) condition += ' · ' + conditionDetails;
      return '<article class="decision-history-source" data-source="' + escapeHtml(row.sourceId)
        + '" data-source-ref="' + escapeHtml(row.sourceRef) + '"><header><strong>' + escapeHtml(row.source)
        + '</strong><span>' + escapeHtml(row.role) + '</span></header><dl>'
        + '<div><dt>动作与周期</dt><dd>' + escapeHtml(row.action + ' · ' + row.horizon) + '</dd></div>'
        + '<div><dt>结构依据</dt><dd>' + escapeHtml(row.structure) + '</dd></div>'
        + '<div><dt>未满足条件</dt><dd>' + escapeHtml(row.unmet) + '</dd></div>'
        + '<div><dt>关键价位与分数</dt><dd>' + escapeHtml(prices + ' · ' + score) + '</dd></div>'
        + '<div><dt>条件/风险</dt><dd>' + escapeHtml(condition + ' · ' + row.risk) + '</dd></div>'
        + '<div><dt>证据时效/版本</dt><dd>' + escapeHtml(row.evidence + ' · ' + row.freshness + ' · 报告版本 ' + row.reportVersion + ' · 策略版本 ' + row.strategyVersion) + '</dd></div>'
        + '</dl></article>';
    }).join('');
  }

  function renderDecisionHistorySnapshot(label, identity, entries, missingText, validation) {
    var list = asArray(entries);
    return '<section class="decision-history-snapshot"><header><h4>' + escapeHtml(label)
      + '</h4><small>' + escapeHtml(decisionHistoryIdentityText(identity)) + '</small></header>'
      + (list.length ? list.map(function (entry) { return renderDecisionHistorySource(entry, validation); }).join('')
        : '<p class="decision-history-missing">' + escapeHtml(missingText) + '</p>') + '</section>';
  }

  function renderDecisionHistoryValidationNote(validation) {
    if (!validation) return '';
    if (!validation.ok) {
      return '<p class="decision-history-missing">历史身份未核验：'
        + escapeHtml(validation.reasons.join('；') || '日期或阶段未通过核验')
        + '，不把该文件当作上一有效交易快照。</p>';
    }
    if (!validation.identityComparable || validation.priceComparable === false) {
      return '<p class="decision-history-missing">版本、快照标识或价基未完整核验；保留成员与来源事实，价格和升级变化不作已验证可比结论。</p>';
    }
    return '';
  }

  function renderDecisionChangeHistory(code, currentEntries, previousEntries, context) {
    var value = context && typeof context === 'object' ? context : {};
    var currentIdentity = value.current || {};
    var previousIdentity = value.previous || {};
    var currentText = renderDecisionHistorySnapshot('当前有效快照', currentIdentity,
      currentEntries, '当前快照没有该股票记录，不能据此认定失效或破位。');
    var previousText = renderDecisionHistorySnapshot('上一有效交易快照', previousIdentity,
      previousEntries, '上一有效交易快照未找到该股票记录；这是已有历史缺口，不等于破位或失效。', value.previous && value.previous.validation);
    return '<section class="decision-history-timeline" data-history-code="' + escapeHtml(code)
      + '"><header><h3>' + escapeHtml(code) + ' · 已有快照复盘</h3><p>仅读取当前与上一有效交易快照；跨期计算暂不可用，仅并列原记录，不输出未变化或数值变化结论。</p></header>'
      + currentText + previousText + renderDecisionHistoryValidationNote(value.previous && value.previous.validation) + '</section>';
  }

  function loadDecisionChangeHistory(code, target) {
    target = target || nodes.decisionChanges;
    if (!target || typeof target.querySelector !== 'function') return;
    var panel = target.querySelector('.decision-change-history');
    if (!panel) return;
    var projection = getDecisionWorkbench();
    var changes = projection && projection.changes && typeof projection.changes === 'object'
      ? projection.changes : {};
    var previousIdentity = decisionHistoryPreviousIdentity(changes);
    var currentDate = projection && projection.report_date || (state.data || {}).date || '';
    var previousDate = previousIdentity.date;
    var currentEntries = decisionHistoryEntries(state.data, code, projection);
    var context = {
      current: { date: currentDate, phase: projection && projection.phase,
        version: projection && projection.version,
        snapshot: projection && (projection.snapshot_id || projection.payload_hash) },
      previous: previousIdentity,
    };
    panel.innerHTML = renderDecisionChangeHistory(code, currentEntries, [], context)
      + '<p class="decision-history-loading">正在读取上一有效交易快照…</p>';
    if (!previousDate) {
      panel.innerHTML = renderDecisionChangeHistory(code, currentEntries, [], context);
      return;
    }
    if (!window.fetch) {
      panel.innerHTML = renderDecisionChangeHistory(code, currentEntries, [], context)
        + '<p class="decision-history-missing">当前环境未提供历史快照读取能力，已保留当前记录与历史缺口。</p>';
      return;
    }
    var token = Number(state.reviewHistoryRequestToken || 0) + 1;
    state.reviewHistoryRequestToken = token;
    window.fetch(decisionHistoryDataUrl(previousDate)).then(function (response) {
      if (!response || !response.ok) throw new Error('历史快照读取失败');
      return response.json();
    }).then(function (payload) {
      if (token !== state.reviewHistoryRequestToken) return;
      var validation = validateDecisionHistoryPayload(payload, previousIdentity);
      context.previous.validation = validation;
      if (!validation.ok) {
        panel.innerHTML = renderDecisionChangeHistory(code, currentEntries, [], context)
          + '<p class="decision-history-missing">' + escapeHtml(validation.reasons.join('；') || '上一有效交易快照身份未核验')
          + '，未将该文件当作上一快照。</p>';
        return;
      }
      var previousEntries = decisionHistoryEntries(payload, code, null, previousIdentity);
      panel.innerHTML = renderDecisionChangeHistory(code, currentEntries, previousEntries, context);
    }).catch(function () {
      if (token !== state.reviewHistoryRequestToken) return;
      panel.innerHTML = renderDecisionChangeHistory(code, currentEntries, [], context)
        + '<p class="decision-history-missing">上一有效交易快照读取失败；当前记录保留，历史缺口未补齐。</p>';
    });
  }

  function bindDecisionChangeDrilldowns(target) {
    if (!target || typeof target.querySelectorAll !== 'function') return;
    var buttons = target.querySelectorAll('[data-change-drill]');
    for (var index = 0; index < buttons.length; index += 1) {
      buttons[index].addEventListener('click', function (event) {
        var button = event.currentTarget;
        var code = normalizeString(button.getAttribute('data-change-code')).trim();
        var requestedView = normalizeString(button.getAttribute('data-change-view')).trim();
        var views = getCandidateViews().views || {};
        var destination = requestedView && views[requestedView] ? requestedView : 'decision_all';
        if (!views[destination]) return;
        if (destination !== state.currentView) activateWorkspaceView(destination, false);
        state.candidateQuery = code;
        if (nodes.candidateSearch) nodes.candidateSearch.value = code;
        refreshCandidateWorkspace();
      });
    }
    var historyButtons = target.querySelectorAll('[data-change-history]');
    for (var historyIndex = 0; historyIndex < historyButtons.length; historyIndex += 1) {
      historyButtons[historyIndex].addEventListener('click', function (event) {
        loadDecisionChangeHistory(event.currentTarget.getAttribute('data-change-history'), target);
      });
    }
    var currentButtons = target.querySelectorAll('[data-change-current]');
    for (var currentIndex = 0; currentIndex < currentButtons.length; currentIndex += 1) {
      currentButtons[currentIndex].addEventListener('click', function (event) {
        var button = event.currentTarget;
        openDecisionChangeCurrentChart(
          button.getAttribute('data-change-current'),
          button.getAttribute('data-change-current-view')
        );
      });
    }
    var groupToggles = target.querySelectorAll('[data-change-group-toggle]');
    for (var groupIndex = 0; groupIndex < groupToggles.length; groupIndex += 1) {
      groupToggles[groupIndex].addEventListener('click', function (event) {
        var group = normalizeString(event.currentTarget.getAttribute('data-change-group-toggle')).trim();
        var section = target.querySelector('[data-change-group="' + group + '"]');
        if (!section) return;
        if (section.classList && typeof section.classList.add === 'function') section.classList.add('is-focused');
        if (typeof section.scrollIntoView === 'function') section.scrollIntoView({ block: 'nearest' });
      });
    }
  }

  function renderDecisionChangesPanel(target) {
    target = target || nodes.decisionChanges;
    if (!target) return '';
    var projection = getDecisionWorkbench();
    if (!projection) {
      var legacyHtml = '<section class="decision-changes-panel is-unavailable">'
        + '<h3>变化复盘</h3><p>本期没有统一清单，已有历史变化记录未提供。</p></section>';
      target.innerHTML = legacyHtml;
      return legacyHtml;
    }
    var changes = projection.changes && typeof projection.changes === 'object'
      ? projection.changes : {};
    var previousIdentity = decisionHistoryPreviousIdentity(changes);
    var previousDate = previousIdentity.date;
    var previousPhase = previousIdentity.phase;
    var previousSnapshot = previousIdentity.snapshot;
    var previousVersion = previousIdentity.version;
    var currentSnapshot = normalizeString(projection.snapshot_id || projection.payload_hash
      || (projection.snapshot || {}).snapshot_id || (projection.snapshot || {}).id).trim();
    var currentVersion = normalizeString(projection.version || projection.snapshot_version
      || (projection.snapshot || {}).version).trim();
    var identity = [
      previousDate ? '上一有效交易快照 ' + previousDate : '上一有效交易快照未记录',
      previousPhase ? '上一阶段 ' + previousPhase : '',
      previousSnapshot ? '上一快照标识 ' + decisionIdentityToken(previousSnapshot) : '',
      previousVersion ? '上一版本 ' + previousVersion : '',
      currentSnapshot ? '当前快照标识 ' + decisionIdentityToken(currentSnapshot) : '',
      currentVersion ? '当前版本 ' + currentVersion : '',
    ].filter(Boolean).join(' · ');
    var status = normalizeString(changes.status).trim();
    var statusText;
    if (status === 'available' && previousDate) {
      statusText = '已有上一有效交易快照，可按成员与已登记字段下钻；仅呈现已有记录，不补写更早时间线。';
    } else if (status === 'available') {
      statusText = '已有比较记录，但上一有效交易快照时间未记录；不能补写首次出现或完整时间线。';
    } else if (status === 'partial') {
      statusText = '已有记录可部分比较；缺价基、换基或版本冲突的字段只展示可比部分。';
    } else {
      statusText = '跨期比较未完整，不能确认跨期是否变化；保留当前记录与历史缺口。';
    }
    var reason = decisionChangeReason({}, changes, '');
    if (status !== 'available' && reason) statusText += ' 原因：' + reason + '。';
    var groups = [
      ['added', '加入当前集合', '本期没有新增记录'],
      ['removed', '移出当前集合', '本期没有移出记录'],
      ['changed', '状态/条件变化', '本期没有已登记的状态或条件变化'],
    ];
    var changedCodes = asArray(changes.changed).map(decisionChangeCode);
    var unavailableCodes = asArray(changes.value_unavailable_codes || changes.unavailable_codes)
      .filter(function (code) { return changedCodes.indexOf(decisionChangeCode(code)) === -1; });
    if (unavailableCodes.length) {
      groups.push(['unavailable', '部分字段不可比较', '本期没有单股不可比较记录']);
    }
    var lists = groups.map(function (group) {
      var entries = group[0] === 'unavailable'
        ? unavailableCodes.map(function (code) { return { code: code }; })
        : asArray(changes[group[0]]);
      return '<section class="decision-change-group" id="decision-change-group-' + escapeHtml(group[0])
        + '" data-change-group="' + group[0] + '">'
        + '<h4><button type="button" class="decision-change-count" data-change-group-toggle="'
        + escapeHtml(group[0]) + '" aria-controls="decision-change-group-' + escapeHtml(group[0]) + '">'
        + escapeHtml(group[1]) + ' <span>' + entries.length + '</span></button></h4>'
        + (entries.length
          ? '<ul>' + entries.map(function (entry) {
            return decisionChangeEntryText(group[0], entry, projection, changes);
          }).join('') + '</ul>'
          : '<p>' + escapeHtml(group[2]) + '</p>') + '</section>';
    }).join('');
    var html = '<section class="decision-changes-panel" aria-label="跨期变化复盘">'
      + '<header><div><h3>变化复盘</h3><p>' + escapeHtml(statusText) + '</p></div>'
      + '<small>' + escapeHtml(identity) + '</small></header>'
      + '<p class="decision-changes-boundary">新增/移出只表示集合成员变化，不等于首次出现、破位或正式升级；跨期计算暂不可用，无完整比较时不得把状态写成未变化。</p>'
      + '<div class="decision-change-groups">' + lists + '</div>'
      + '<div class="decision-change-history"><p>打开个股的“查看已有快照”后读取当前与上一有效交易快照。</p></div></section>';
    target.innerHTML = html;
    bindDecisionChangeDrilldowns(target);
    return html;
  }

  function renderCoverageSummary(coverage) {
    var value = coverage && typeof coverage === 'object' ? coverage : {};
    var status = normalizeString(value.status).trim();
    var statusLabel = {
      verified: '覆盖已核验',
      partial: '覆盖部分缺失',
      blocked: '正式输入已阻断',
      unknown: '覆盖记录未提供',
    }[status] || '覆盖记录未提供';
    function isCoverageCount(count) {
      return isFormalMarketNumber(count, 0, Infinity) && Number.isInteger(count);
    }
    var projectedFacts = [];
    var snapshot = value.market_close_snapshot && typeof value.market_close_snapshot === 'object'
      ? value.market_close_snapshot : {};
    var snapshotStatus = normalizeString(snapshot.status).trim();
    var snapshotHasCounts = isCoverageCount(snapshot.available) && isCoverageCount(snapshot.required);
    if (snapshotHasCounts) {
      projectedFacts.push('收盘核验 ' + snapshot.available + '/' + snapshot.required);
    } else if (snapshotStatus === 'partial') {
      projectedFacts.push('收盘核验部分缺失');
    } else if (snapshotStatus && snapshotStatus !== 'complete' && snapshotStatus !== 'unknown') {
      projectedFacts.push('收盘核验不可用');
    }
    if (isCoverageCount(snapshot.pending) && snapshot.pending > 0) {
      projectedFacts.push('身份待核验 ' + snapshot.pending);
    }
    var quantity = value.quantity && typeof value.quantity === 'object' ? value.quantity : {};
    var quantityStatus = normalizeString(quantity.status).trim();
    if (quantityStatus === 'partial' || quantityStatus === 'unavailable') {
      var quantityText = quantityStatus === 'partial' ? '量能部分核验' : '量能不可用';
      if (isCoverageCount(quantity.available) && isCoverageCount(quantity.required)) {
        quantityText += ' ' + quantity.available + '/' + quantity.required;
      }
      projectedFacts.push(quantityText);
      if (isCoverageCount(quantity.pending) && quantity.pending > 0) {
        projectedFacts.push('待核验 ' + quantity.pending);
      }
    }
    var minute = value.minute30 && typeof value.minute30 === 'object' ? value.minute30 : {};
    var minuteText = (isFormalMarketNumber(minute.requested, 0, Infinity)
      && isFormalMarketNumber(minute.verified, 0, Infinity))
      ? '30分钟已核验 ' + minute.verified + '/请求 ' + minute.requested
        + (isFormalMarketNumber(minute.missing, 0, Infinity)
          && minute.missing > 0 ? ' · 缺 ' + minute.missing : '')
      : '30分钟未记录';
    var retrieval = value.retrieval && typeof value.retrieval === 'object' ? value.retrieval : {};
    var retrievalMode = normalizeString(retrieval.mode).trim();
    var retrievalText = (isFormalMarketNumber(retrieval.full_a, 0, Infinity)
      && isFormalMarketNumber(retrieval.retrieval, 0, Infinity))
      ? (retrievalMode === 'base_plus_overlay'
        ? '日线检索 ' + retrieval.retrieval + '/登记候选 ' + retrieval.full_a
        : '日线检索记录 ' + retrieval.retrieval + '/登记候选 ' + retrieval.full_a)
        + (isFormalMarketNumber(retrieval.first_failure, 0, Infinity)
          ? (retrievalMode === 'base_plus_overlay'
            ? '；检索筛选未入 ' + retrieval.first_failure
            : '；前置筛选未入 ' + retrieval.first_failure) : '')
      : '日线检索未记录';
    var eligibility = value.eligibility && typeof value.eligibility === 'object' ? value.eligibility : {};
    var excluded = eligibility.excluded && typeof eligibility.excluded === 'object' ? eligibility.excluded : {};
    var excludedText = (isFormalMarketNumber(excluded.nonfinal_bars, 0, Infinity)
      || isFormalMarketNumber(excluded.stale_latest_bar, 0, Infinity))
      ? '日线未定稿 ' + (isFormalMarketNumber(excluded.nonfinal_bars, 0, Infinity) ? excluded.nonfinal_bars : '--')
        + ' · 历史过期 ' + (isFormalMarketNumber(excluded.stale_latest_bar, 0, Infinity) ? excluded.stale_latest_bar : '--')
      : '日线定稿/过期未记录';
    return [statusLabel].concat(projectedFacts, [retrievalText, minuteText, excludedText]).join(' · ');
  }

  function buildFormalOutcomeExplanation(summary, data) {
    var admission = ((data || {}).diagnostics || {}).fusion_admission || {};
    return '<dl class="formal-outcome-explanation">' + [['main', '正式主推'], ['h4_t3', 'H4 T+3']].map(function (entry) {
      var result = (summary || {})[entry[0]];
      if (!result) return '';
      var reason;
      if (result.state === 'verified_empty') {
        reason = entry[0] === 'main' ? '本期没有通过全部条件的正式结果。' : '本期没有候选通过 H4 T+3 全部门槛。';
        if (entry[0] === 'main' && admission.kept_formal === 0
            && isFormalMarketNumber(admission.kept_candidate, 1, Infinity)) {
          reason = '留下的 ' + admission.kept_candidate + ' 只仍处于候选阶段，尚未形成正式买点；继续观察个股确认条件。';
        }
      } else if (result.state === 'unavailable') {
        reason = normalizeString(result.reason) || '本期数据未通过核验，暂不能判断。';
      } else {
        reason = '本期 ' + (isFormalMarketNumber(result.count, 0, Infinity) ? result.count : '--') + ' 只正式结果，执行条件见个股详情。';
      }
      return '<div><dt>' + escapeHtml(entry[1]) + '</dt><dd>' + escapeHtml(reason) + '</dd></div>';
    }).join('') + '</dl>';
  }

  function luojieContractCodes(values) {
    if (!Array.isArray(values)) return null;
    var codes = values.map(function (value) {
      return toCodeKey(value && typeof value === 'object' ? value.code : value);
    });
    if (codes.some(function (code) { return !/^\d{6}$/.test(code); })) return null;
    var unique = {};
    if (codes.some(function (code) {
      if (unique[code]) return true;
      unique[code] = true;
      return false;
    })) return null;
    return codes;
  }

  function sameLuojieCodeSet(left, right) {
    var leftCodes = luojieContractCodes(left);
    var rightCodes = luojieContractCodes(right);
    return Boolean(leftCodes && rightCodes && leftCodes.length === rightCodes.length
      && leftCodes.slice().sort().join(',') === rightCodes.slice().sort().join(','));
  }

  function validLuojiePartialHealth(health, reportDate) {
    var value = health && typeof health === 'object' ? health : {};
    function count(name, codesName) {
      var number = value[name];
      var codes = luojieContractCodes(value[codesName]);
      return typeof number === 'number' && Number.isFinite(number)
        && number >= 0 && Math.floor(number) === number
        && codes && number === codes.length;
    }
    var requested = value.requested_count;
    var verifiedCodes = luojieContractCodes(value.verified_codes);
    var missingCodes = luojieContractCodes(value.missing_codes);
    var budgetExcludedCodes = luojieContractCodes(value.budget_excluded_codes);
    return normalizeString(value.status).trim() === 'partial'
      && normalizeString(value.required_date).trim() === reportDate
      && normalizeString(value.blocking_reason).trim() === 'strategy_input_stale_or_unverified'
      && value.formal_actions_allowed === false
      && value.research_output_trusted === false
      && value.research_candidate_output_allowed === true
      && typeof requested === 'number' && Number.isFinite(requested)
      && requested >= 0 && Math.floor(requested) === requested
      && count('verified_count', 'verified_codes')
      && count('missing_count', 'missing_codes')
      && count('budget_excluded_count', 'budget_excluded_codes')
      && requested === value.verified_count + value.missing_count
      && value.invalid_count === 0
      && Array.isArray(value.invalid_codes)
      && value.invalid_codes.length === 0
      && verifiedCodes && missingCodes && budgetExcludedCodes
      && verifiedCodes.every(function (code) {
        return missingCodes.indexOf(code) === -1 && budgetExcludedCodes.indexOf(code) === -1;
      })
      && missingCodes.every(function (code) {
        return budgetExcludedCodes.indexOf(code) === -1;
      });
  }

  function sameLuojiePartialHealth(left, right) {
    var scalarFields = [
      'status', 'required_date', 'requested_count', 'verified_count',
      'missing_count', 'budget_excluded_count', 'invalid_count',
      'formal_actions_allowed', 'research_candidate_output_allowed',
      'research_output_trusted', 'blocking_reason',
    ];
    return scalarFields.every(function (field) { return left[field] === right[field]; })
      && sameLuojieCodeSet(left.verified_codes, right.verified_codes)
      && sameLuojieCodeSet(left.missing_codes, right.missing_codes)
      && sameLuojieCodeSet(left.budget_excluded_codes, right.budget_excluded_codes)
      && sameLuojieCodeSet(left.invalid_codes, right.invalid_codes);
  }

  function isLegacyLuojieCommonUpstreamClosure(data, reportDate, finalUpstream) {
    var selection = data.selection_input_health || {};
    var byView = selection.by_view && selection.by_view.luojie;
    var workspace = data.workspace || {};
    var meta = workspace.view_meta && workspace.view_meta.luojie;
    var upstream = meta && meta.upstream_contract;
    function isExpected(value) {
      var invalidCodes = luojieContractCodes(value && value.invalid_codes);
      return Boolean(value && typeof value === 'object' && invalidCodes
        && normalizeString(value.status).trim() === 'unavailable'
        && normalizeString(value.required_date).trim() === reportDate
        && normalizeString(value.blocking_reason).trim() === 'strategy_upstream_contract_mismatch'
        && value.output_hidden === true
        && value.invalid_count === invalidCodes.length
        && sameLuojieCodeSet(value.invalid_codes, finalUpstream.excluded_codes));
    }
    var availabilityReason = normalizeString(
      meta && meta.availability && meta.availability.reason
    ).trim();
    return asArray(workspace.views && workspace.views.luojie).length === 0
      && isExpected(byView) && isExpected(upstream)
      && meta.availability && normalizeString(meta.availability.state).trim() === 'unavailable'
      && availabilityReason.indexOf('picks_pure') !== -1
      && availabilityReason.indexOf('共同上游') !== -1;
  }

  function getLuojieIndependentSourceProjection(data) {
    var report = data && typeof data === 'object' ? data : {};
    var reportDate = normalizeString(report.date).trim();
    var workbench = getDecisionWorkbench(report);
    var pool = report.luojie_pool && typeof report.luojie_pool === 'object'
      ? report.luojie_pool : null;
    var selection = report.selection_input_health || {};
    var strategyHealth = selection.by_strategy && selection.by_strategy.luojie_pool;
    var poolHealth = pool && pool.input_health;
    var diagnostics = pool && pool.diagnostics && typeof pool.diagnostics === 'object'
      ? pool.diagnostics : {};
    var finalUpstream = diagnostics.final_common_upstream;
    if (!reportDate || !workbench || workbench.report_date !== reportDate
        || Number(selection.schema_version) !== 2 || !pool
        || normalizeString(selection.required_date).trim() !== reportDate
        || normalizeString(pool.mode).trim() !== 'partial'
        || normalizeString(pool.status).trim() !== 'partial'
        || !normalizeString(pool.strategy_version).trim()
        || !validLuojiePartialHealth(strategyHealth, reportDate)
        || !validLuojiePartialHealth(poolHealth, reportDate)
        || !sameLuojiePartialHealth(strategyHealth, poolHealth)
        || diagnostics.partial_candidate_output_allowed !== true
        || diagnostics.requested_count !== strategyHealth.requested_count
        || diagnostics.verified_count !== strategyHealth.verified_count
        || !sameLuojieCodeSet(diagnostics.missing_codes, strategyHealth.missing_codes)
        || diagnostics.budget_excluded_count !== strategyHealth.budget_excluded_count
        || !sameLuojieCodeSet(
          diagnostics.budget_excluded_codes, strategyHealth.budget_excluded_codes
        )
        || !finalUpstream || finalUpstream.enforced !== false
        || normalizeString(finalUpstream.reason).trim() !== 'research_independent_candidate_set'
        || normalizeString(finalUpstream.upstream_pool).trim() !== 'picks_pure'
        || !isLegacyLuojieCommonUpstreamClosure(report, reportDate, finalUpstream)) {
      return null;
    }

    var rawCandidates = asArray(pool.candidates);
    var rawCodes = luojieContractCodes(rawCandidates);
    var verifiedCodes = luojieContractCodes(strategyHealth.verified_codes);
    var missingCodes = luojieContractCodes(strategyHealth.missing_codes);
    var budgetExcludedCodes = luojieContractCodes(strategyHealth.budget_excluded_codes);
    var evidenceRows = getEvidenceRowsForView('luojie', report);
    var evidenceCodes = luojieContractCodes(evidenceRows);
    var finalExcludedCodes = luojieContractCodes(finalUpstream.excluded_codes);
    if (!rawCodes || !rawCodes.length || !verifiedCodes || !missingCodes || !budgetExcludedCodes
        || !evidenceCodes || !finalExcludedCodes
        || finalUpstream.candidate_count !== rawCodes.length
        || finalUpstream.input_count !== rawCodes.length
        || finalUpstream.excluded_count !== finalExcludedCodes.length
        || diagnostics.candidates !== rawCodes.length
        || !sameLuojieCodeSet(evidenceRows, rawCandidates)
        || rawCodes.some(function (code) {
          return verifiedCodes.indexOf(code) === -1
            || missingCodes.indexOf(code) !== -1
            || budgetExcludedCodes.indexOf(code) !== -1;
        })) return null;

    var invalid = false;
    var sourceRows = [];
    asArray(workbench.items).forEach(function (item) {
      var strategies = asArray(item && item.strategy_results).filter(function (strategy) {
        return normalizeString(strategy && strategy.strategy_id).trim() === 'luojie';
      });
      if (!strategies.length) return;
      if (strategies.length !== 1) {
        invalid = true;
        return;
      }
      var strategy = strategies[0];
      var candidate = strategy.candidate && typeof strategy.candidate === 'object'
        ? strategy.candidate : null;
      var ref = candidate && candidate.ref && typeof candidate.ref === 'object'
        ? candidate.ref : {};
      var code = toCodeKey(candidate && candidate.code);
      var evidence = strategy.evidence && typeof strategy.evidence === 'object'
        ? strategy.evidence : {};
      var evidenceSummary = evidence.summary && typeof evidence.summary === 'object'
        ? evidence.summary : {};
      var sourceRefs = asArray(item && item.source_refs).filter(function (sourceRef) {
        return normalizeString(sourceRef && sourceRef.view).trim() === 'luojie';
      });
      var viewRank = strategy.view_rank;
      if (!candidate || toCodeKey(item && item.code) !== code
          || normalizeString(strategy.role).trim() !== 'research'
          || normalizeString(strategy.action_semantics).trim() !== 'watch_only'
          || normalizeString(strategy.page_status).trim() !== 'watch_only'
          || normalizeString(strategy.formal_action).trim()
          || (strategy.score !== null && typeof strategy.score !== 'undefined')
          || normalizeString(candidate.action_semantics).trim() !== 'watch_only'
          || candidate.is_formal_recommendation !== false
          || asArray(candidate.sources).length !== 1
          || normalizeString(candidate.sources[0]).trim() !== 'luojie'
          || (candidate.evidence_view
            && normalizeString(candidate.evidence_view).trim() !== 'luojie')
          || candidate.workbench_item
          || normalizeString(ref.pool || ref.source_pool).trim() !== 'luojie_pool'
          || toCodeKey(ref.code) !== code
          || sourceRefs.length !== 1
          || !sameCandidateSourceRef(ref, sourceRefs[0].ref)
          || normalizeString(evidence.view).trim() !== 'luojie'
          || toCodeKey(evidence.code || evidenceSummary.code) !== code
          || normalizeString(evidenceSummary.pool_identity).trim() !== 'luojie_pool'
          || typeof viewRank !== 'number' || !Number.isFinite(viewRank)
          || viewRank < 1 || Math.floor(viewRank) !== viewRank
          || candidate.view_rank !== viewRank) {
        invalid = true;
        return;
      }
      sourceRows.push({ rank: viewRank, candidate: candidate, evidence: evidence });
    });
    sourceRows.sort(function (left, right) { return left.rank - right.rank; });
    var evidenceByCode = {};
    evidenceRows.forEach(function (evidence) {
      evidenceByCode[toCodeKey(evidence && evidence.code)] = evidence;
    });
    if (invalid || sourceRows.length !== rawCodes.length
        || sourceRows.some(function (row, index) {
          var detailEvidence = evidenceByCode[toCodeKey(row.candidate && row.candidate.code)];
          return (index > 0 && row.rank === sourceRows[index - 1].rank)
            || !detailEvidence
            || JSON.stringify(detailEvidence) !== JSON.stringify(row.evidence);
        })
        || !sameLuojieCodeSet(sourceRows.map(function (row) {
          return row.candidate;
        }), rawCandidates)) return null;

    var reason = normalizeString(pool.reason).trim() || '15分钟研究输入部分核验';
    return {
      rows: sourceRows.map(function (row) { return row.candidate; }),
      availability: {
        state: 'partial',
        reason: reason + '；专用视图显示 ' + sourceRows.length + ' 只；核验 '
          + strategyHealth.verified_count + ' / 请求 ' + strategyHealth.requested_count
          + '；缺失 ' + strategyHealth.missing_count
          + '；预算外 ' + strategyHealth.budget_excluded_count + '。',
      },
    };
  }

  function getCandidateViews() {
    var workspace = state.workspace || {};
    var rawViews = workspace.views || {};
    var views = {};
    Object.keys(rawViews).forEach(function (viewKey) {
      views[viewKey] = asArray(rawViews[viewKey]).slice();
    });
    var luojieSourceProjection = getLuojieIndependentSourceProjection(state.data || {});
    if (luojieSourceProjection) {
      views.luojie = luojieSourceProjection.rows.slice();
    }
    var rawMeta = workspace.view_meta || {};
    var meta = {};
    Object.keys(Object.assign({}, DEFAULT_VIEW_CONTRACTS, rawMeta)).forEach(function (viewKey) {
      var resolved = resolveViewDisplayContract(viewKey, rawMeta[viewKey] || {});
      var blockingReason = getStrategyViewBlockingReason(state.data, viewKey);
      if (viewKey === 'luojie' && luojieSourceProjection) {
        resolved.availability = luojieSourceProjection.availability;
      } else if (blockingReason) {
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
    var projection = getDecisionWorkbench();
    if (projection) decisionNavigation().forEach(function (entry) {
      views[entry.key] = decisionRows(projection, entry.key, views);
      meta[entry.key] = { label: entry.label, role: 'presentation', action_semantics: 'mixed',
        availability: { state: views[entry.key].length ? 'available' : 'verified_empty' } };
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
      primary: getDecisionWorkbench() ? decisionNavigation() : (asArray(supplied.primary).length ? asArray(supplied.primary) : fallback.primary),
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

  function getCandidateSelection(viewKey, options) {
    var opts = options || {};
    var key = normalizeString(viewKey || state.currentView).trim();
    var viewInfo = getCandidateViews();
    var poolItems = asArray(viewInfo.views[key]);
    var statusFilter = key === 'decision_formal'
      ? normalizeString(opts.statusFilter === undefined
        ? state.decisionStatusFilter : opts.statusFilter).trim()
      : '';
    var statusItems = statusFilter
      ? poolItems.filter(function (item) {
        return primaryDisplayMatchesStatus(item, statusFilter);
      })
      : poolItems;
    var sectorName = opts.sectorName === undefined ? state.sectorFilter : opts.sectorName;
    var sectorCode = opts.sectorCode === undefined ? state.sectorFilterCode : opts.sectorCode;
    var sectorRefs = opts.sectorRefs === undefined ? state.sectorFilterRefs : opts.sectorRefs;
    var sectorItems = filterCandidatesBySector(statusItems, sectorName, sectorCode, sectorRefs);
    var query = opts.query === undefined ? state.candidateQuery : opts.query;
    query = normalizeString(query).trim().toLowerCase();
    var items = sectorItems.filter(function (item) {
      if (!query) return true;
      return [item && item.code, item && item.name, item && item.sector,
        item && item.sector_name].some(function (value) {
        return normalizeString(value).toLowerCase().indexOf(query) !== -1;
      });
    });
    var limit = opts.limit === undefined ? state.candidateLimit : opts.limit;
    limit = Math.max(0, Number(limit) || 0);
    var visibleItems = opts.limit === undefined
      ? items.slice(0, state.candidateLimit)
      : items.slice(0, limit);
    return {
      viewKey: key,
      poolItems: poolItems,
      statusItems: statusItems,
      statusFilter: statusFilter,
      sectorItems: sectorItems,
      items: items,
      visibleItems: visibleItems,
      query: query,
      sectorName: normalizeSectorName(sectorName),
      sectorCode: normalizeString(sectorCode).trim(),
      sectorRefs: asArray(sectorRefs),
    };
  }

  function isFormalWorkbenchItem(item) {
    var rec = item && item.workbench_item ? item.workbench_item : (item || {});
    if (asArray(rec.strategy_results).some(function (strategy) {
      return strategy && (strategy.role === 'formal'
        || normalizeString(strategy.action_semantics) === 'formal');
    })) return true;
    return normalizeString(rec.action_semantics) === 'formal'
      || Boolean(rec.formal_action && (rec.formal_decision_contract || rec.contracts));
  }

  function getWorkbenchCurrentDecision(item) {
    var outer = item && typeof item === 'object' ? item : {};
    var rec = outer.workbench_item && typeof outer.workbench_item === 'object'
      ? outer.workbench_item : outer;
    var pageStatus = normalizeString(rec.page_status).trim();
    var formal = isFormalWorkbenchItem(rec);
    var incident = isIncidentReviewItem(outer) || isIncidentReviewItem(rec);
    var executable = formal && !incident
      && pageStatus === 'formal_ready' && rec.is_executable === true;
    var statusLabels = {
      formal_ready: '正式条件完整',
      formal_incomplete: '正式待确认',
      strategy_disagreement: '正式策略分歧',
      evidence_blocked: '暂无法判断',
      invalidated: '已失效',
      waiting_trigger: formal ? '正式待确认' : '研究待条件',
      watch_only: '研究观察',
    };
    var statusLabel = incident
      ? '仅追溯'
      : (normalizeString(rec.status_label).trim() || statusLabels[pageStatus]
        || (formal ? '状态未声明' : '研究观察'));
    if (!incident && formal && !executable && pageStatus === 'formal_ready') {
      statusLabel = '可执行性未核验';
    }
    var currentDominates = incident || (formal && !executable);
    return {
      formal: formal,
      incident: incident,
      executable: executable,
      currentDominates: currentDominates,
      statusLabel: statusLabel,
      prompt: currentDominates
        ? '当前提示：' + statusLabel + '；当前不可执行'
        : normalizeString(rec.primary_reason).trim(),
    };
  }

  function evidenceStatusForCandidate(item, viewKey) {
    var sourceItem = item || {};
    var rec = sourceItem.workbench_item ? sourceItem.workbench_item : sourceItem;
    var strategies = asArray(rec.strategy_results);
    var sections = [];
    if (strategies.length) {
      strategies.forEach(function (strategy) {
        var evidence = strategy && strategy.evidence && typeof strategy.evidence === 'object'
          ? strategy.evidence : {};
        if (evidence.summary && typeof evidence.summary === 'object') sections.push(evidence.summary);
        ['daily_structure', 'sublevel_30m', 'volume_and_capital', 'price_evidence',
          'market_and_sector', 'risk_and_next'].forEach(function (key) {
          if (evidence[key] && typeof evidence[key] === 'object') sections.push(evidence[key]);
        });
      });
    } else {
      var evidence = getCandidateRecommendationEvidence(sourceItem, state.data, viewKey);
      if (evidence) {
        sections.push(evidence.summary && typeof evidence.summary === 'object' ? evidence.summary : {});
        ['daily_structure', 'sublevel_30m', 'volume_and_capital', 'price_evidence',
          'market_and_sector', 'risk_and_next'].forEach(function (key) {
          if (evidence[key] && typeof evidence[key] === 'object') sections.push(evidence[key]);
        });
      }
    }
    var statuses = sections.map(function (section) {
      return normalizeString(section && section.status).trim().toLowerCase();
    }).filter(Boolean);
    if (!statuses.length) return '证据未声明';
    if (statuses.indexOf('conflict') !== -1) return '证据冲突';
    if (statuses.indexOf('stale') !== -1 || statuses.indexOf('unavailable') !== -1) return '证据不可用';
    if (statuses.indexOf('missing') !== -1 || statuses.indexOf('partial') !== -1) return '证据未完整';
    return statuses.every(function (status) { return status === 'available'; })
      ? '证据可用' : '证据未核验';
  }

  function getCandidateStatusSummary(item, viewKey) {
    var rec = item && item.workbench_item ? item.workbench_item : (item || {});
    var currentDecision = getWorkbenchCurrentDecision(item);
    var key = normalizeString(viewKey || state.currentView).trim();
    var strategies = asArray(rec.strategy_results);
    var formal = strategies.filter(function (strategy) {
      return strategy && (strategy.role === 'formal'
        || normalizeString(strategy.action_semantics) === 'formal');
    });
    var formalIdentity = formal.map(function (strategy) {
      var strategyId = normalizeString(strategy.strategy_id).trim();
      return getCurrentLabel(strategyId) || strategyId;
    }).filter(Boolean);
    var contract = resolveViewDisplayContract(key, {});
    var formalViewIdentity = key === 'h4_t3' ? 'H4 T+3' : '正式主推';
    var itemSemantics = normalizeString(rec.action_semantics).trim();
    var formalIdentityDeclared = formalIdentity.length
      || itemSemantics === 'formal'
      || (!itemSemantics && contract.role === 'formal');
    var identity = formalIdentity.length
      ? '正式：' + formalIdentity.join(' / ')
      : (formalIdentityDeclared
        ? formalViewIdentity
        : (contract.role === 'baseline' ? '基础候选' : '研究观察'));
    var pageStatus = normalizeString(rec.page_status).trim();
    var condition;
    if (currentDecision.incident
        || (pageStatus === 'formal_ready' && !currentDecision.executable)) {
      condition = currentDecision.statusLabel;
    } else if (pageStatus === 'formal_ready') condition = '正式条件完整';
    else if (pageStatus === 'formal_incomplete') condition = '正式待确认';
    else if (pageStatus === 'strategy_disagreement') condition = '正式策略分歧';
    else if (pageStatus === 'evidence_blocked') condition = '条件不可核验';
    else if (pageStatus === 'invalidated') condition = '已失效';
    else if (pageStatus === 'waiting_trigger') condition = formal.length ? '正式待确认' : '研究待条件';
    else condition = '条件未声明';
    var riskFlags = asArray(rec.risk_flags).map(normalizeString).filter(Boolean);
    return {
      identity: identity,
      condition: condition,
      evidence: evidenceStatusForCandidate(item, key),
      risk: riskFlags.length ? riskFlags.join('、') : '风险标签未登记',
      pageStatus: pageStatus || 'unknown',
    };
  }

  function renderCandidateStatusSummary(item, viewKey) {
    var status = getCandidateStatusSummary(item, viewKey);
    return '<div class="candidate-row-statuses" role="group" aria-label="身份、条件、证据与风险状态">'
      + '<span class="tag tag-baseline">身份：' + escapeHtml(status.identity) + '</span>'
      + '<span class="tag tag-baseline">条件：' + escapeHtml(status.condition) + '</span>'
      + '<span class="tag tag-baseline">证据：' + escapeHtml(status.evidence) + '</span>'
      + '<span class="tag tag-baseline">风险：' + escapeHtml(status.risk) + '</span>'
      + '</div>';
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
    if (viewKey === 'decision_formal' && !ctx.filtered) {
      var primaryRows = decisionRows(
        getDecisionWorkbench() || {},
        'decision_formal',
        ((state.workspace || {}).views || {})
      );
      if (state.decisionStatusFilter === 'formal_incomplete' && primaryRows.length) {
        return '<div class="candidate-empty decision-empty"><strong>主推中暂无正式待确认</strong>'
          + '<span>当前筛选没有匹配对象；主推完整集合与原状态均已保留。</span></div>';
      }
      return '<div class="candidate-empty decision-empty"><strong>本期暂无主推</strong>'
        + '<span>原正式推荐、正式结果与优先关注的有效阅读集合均为空；不从研究池自动补票。</span></div>';
    }
    if (isDecisionView(viewKey) && !ctx.filtered) {
      var projection = getDecisionWorkbench() || {};
      var total = asArray(projection.items).length;
      return '<div class="candidate-empty decision-empty"><strong>此状态下暂无候选</strong><span>'
        + (total ? '其余标的保留在完整清单，可查看观察理由和待核验条件。' : '本期没有可展示的标的，等待下一次报告更新。')
        + '</span>' + (total && viewKey !== 'decision_all'
          ? '<button type="button" class="candidate-empty-action" data-workbench-open-all>'
            + '查看全部 ' + total + ' 只'
            + '</button>' : '') + '</div>';
    }
    if (ctx.filtered) {
      var filterLabel = normalizeString(ctx.filterLabel || '当前筛选');
      return '<div class="candidate-empty is-filtered"><strong>'
        + escapeHtml(filterLabel + ' · 0只')
        + '</strong><span>当前池没有匹配股票，已保留筛选条件。</span></div>';
    }
    if (viewKey === 'main') {
      if (!state.data) {
        return '<div class="candidate-empty is-verified-empty"><strong>本期未选出推荐票</strong></div>';
      }
      var counts = decisionOverviewCounts();
      var researchCopy = counts.research === null
        ? '研究观察数量未提供，保持原有顺序。'
        : '本期仍有 ' + String(counts.research) + ' 只研究观察对象，保持原有顺序。';
      return '<div class="candidate-empty is-verified-empty"><strong>本期没有正式推荐</strong><span>正式池为空；'
        + escapeHtml(researchCopy) + '</span>'
        + ((getDecisionWorkbench() || legacyObservationViewKey())
          ? '<button type="button" class="candidate-empty-action" data-open-research-observation>进入全部研究观察</button>' : '')
        + '</div>';
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
      + '    <details class="header-version-details" id="reportDataDetails"></details>'
      + '  </header>'
      + '  <nav class="primary-mode-tabs" role="tablist" aria-label="工作台层级">'
      + '    <button type="button" id="primary-mode-tab-today" data-primary-mode="today" role="tab" aria-controls="todayDecisionView" aria-selected="true" tabindex="0">今日决策</button>'
      + '    <button type="button" id="primary-mode-tab-research" data-primary-mode="research" role="tab" aria-controls="researchValidationView" aria-selected="false" tabindex="-1">研究验证</button>'
      + '  </nav>'
      + '  <section class="primary-view today-decision-view" id="todayDecisionView" role="tabpanel" aria-labelledby="primary-mode-tab-today">'
      + '    <section class="historical-reconstruction hidden" id="historicalReconstruction" aria-live="polite"></section>'
      + '    <section class="workspace today-workspace">'
      + '      <section id="mobileDecisionSummary" class="mobile-decision-summary" aria-label="手机首屏结论" hidden></section>'
      + '      <section id="decisionOverview" class="decision-overview" aria-label="本期结论" tabindex="-1" hidden></section>'
      + '      <section class="market-decision-bar" id="marketDecisionBar" aria-label="大盘正式证据">'
      + '        <header class="market-evidence-heading"><div><h2>大盘证据</h2><p>先看市场环境，再核对个股条件</p></div><a href="#decisionOverview">看本期选股结论 ↓</a></header>'
      + '        <div class="market-decision-summary" id="marketDecisionSummary"></div>'
      + '        <div class="market-evidence" id="marketEvidence"></div>'
      + '      </section>'
      + '      <!-- id="directionQuickSummary" is mounted after 我的关注 with the other supplemental facts. -->'
      + '      <section class="sector-strip" id="sectorStrip" aria-label="资金主线"><strong>资金主线</strong><span>正在整理板块证据…</span></section>'
      + '      <section class="candidate-workspace" id="candidateWorkspace" aria-label="候选工作台">'
      + '        <div class="workspace-tabs" id="workspaceTabs" role="group" aria-label="候选视图"></div>'
      + '        <div class="workspace-body">'
      + '        <div class="candidate-list-shell">'
      + '          <div class="candidate-list-tools">'
      + '            <label for="candidateSearch">筛选当前池</label>'
      + '            <input id="candidateSearch" name="candidateSearch" type="search" placeholder="代码、名称或板块…" autocomplete="off" spellcheck="false">'
      + '            <span id="candidateCount" aria-live="polite"></span>'
      + '          </div>'
      + '          <div class="candidate-list" id="candidateList"></div>'
      + '          <button type="button" class="candidate-more" id="candidateMore">加载更多</button>'
      + '        </div>'
      + '        <aside class="detail-panel workspace-detail" id="detailPanel"></aside>'
      + '        </div>'
      + '        <section class="candidate-quick-comparison" id="candidateQuickComparison" aria-label="候选快速比较"></section>'
      + '        <div class="view-description" id="viewDescription"></div>'
      + '        <details class="candidate-evidence-comparison" id="candidateEvidenceComparison">'
      + '          <summary>候选横向比较</summary>'
      + '          <div class="candidate-evidence-comparison-body"></div>'
      + '        </details>'
      + '      </section>'
      + '    </section>'
      + '    <section class="preclose-advisory hidden" id="precloseAdvisory" aria-labelledby="precloseAdvisoryTitle">'
      + '      <header class="preclose-advisory-head">'
      + '        <span><strong id="precloseAdvisoryTitle">14:45预跑</strong><small>盘中建议 · 不改写盘后正式结果</small></span>'
      + '      </header>'
      + '      <div class="preclose-body" id="precloseBody" aria-live="polite"></div>'
      + '      <div class="preclose-reconciliation hidden" id="precloseReconciliation" aria-live="polite"></div>'
      + '    </section>'
      + '    <section class="personal-watchlist-anchor" id="personalWatchlistSection" aria-label="我的关注">'
      + '      <div id="personalWatchlistStack"></div>'
      + '    </section>'
      + '    <section class="direction-quick supplemental-fact-anchor" id="directionQuickSummary" aria-label="今日方向摘要"></section>'
      + '    <section class="market-hotspot-section" id="marketHotspotSection" aria-label="今日热点地图"><div class="hotspot-empty"><span>正在整理热点样本…</span></div></section>'
      + '    <section class="supporting-decisions-stack" id="supportingDecisionsStack" aria-label="今日补充事实"></section>'
      + '    <section class="report-changes-placeholder" id="reportChanges" aria-label="本期变化及复盘入口"><div id="decisionChanges"></div></section>'
      + '  </section>'
      + '  <section class="primary-view research-validation-view hidden" id="researchValidationView" role="tabpanel" aria-labelledby="primary-mode-tab-research">'
      + '    <section class="l1-nextday-research" id="nextday-research" aria-labelledby="nextdayResearchTitle" tabindex="-1">'
      + '      <header class="l1-nextday-header"><div><h2 id="nextdayResearchTitle">L1 次日强势研究候选</h2><p>按当日报告生成的研究名单与次日价格路径记录。</p></div><span class="l1-nextday-research-badge">研究观察 · 不构成正式推荐</span></header>'
      + '      <div class="l1-nextday-content" id="nextdayResearchContent" role="status" aria-live="polite" aria-atomic="true">等待日报数据…</div>'
      + '    </section>'
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
      + '  <dialog class="hotspot-readonly-dialog" id="hotspotReadonlyDialog" aria-labelledby="hotspotReadonlyTitle">'
      + '    <div id="hotspotReadonlyDialogContent"></div>'
      + '  </dialog>'
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
    nodes.nextdayResearchSection = app.querySelector('#nextday-research');
    nodes.nextdayResearch = app.querySelector('#nextdayResearchContent');
    nodes.marketEvidence = app.querySelector('#marketEvidence');
    nodes.mobileDecisionSummary = app.querySelector('#mobileDecisionSummary');
    nodes.marketDecisionBar = app.querySelector('#marketDecisionBar');
    nodes.marketDecisionSummary = app.querySelector('#marketDecisionSummary');
    nodes.sectorStrip = app.querySelector('#sectorStrip');
    nodes.supportingStack = app.querySelector('#supportingDecisionsStack');
    nodes.personalWatchlistStack = app.querySelector('#personalWatchlistStack');
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
    nodes.marketHotspot = app.querySelector('#marketHotspotSection');
    nodes.hotspotDialog = app.querySelector('#hotspotReadonlyDialog');
    nodes.hotspotDialogContent = app.querySelector('#hotspotReadonlyDialogContent');
    nodes.historicalReconstruction = app.querySelector('#historicalReconstruction');
    nodes.candidateSearch = app.querySelector('#candidateSearch');
    nodes.candidateTools = app.querySelector('.candidate-list-tools');
    nodes.candidateCount = app.querySelector('#candidateCount');
    nodes.candidateMore = app.querySelector('#candidateMore');
    nodes.globalError = app.querySelector('#globalError');
    if (nodes.nextdayResearch) {
      nodes.nextdayResearch.addEventListener('click', function (event) {
        var target = event.target && event.target.closest
          ? event.target.closest('[data-nextday-research-retry]')
          : null;
        if (!target) return;
        event.preventDefault();
        loadNextdayResearch();
      });
    }
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
    bindCandidateFilterEvents();
  }

  function refreshReviewToolsMounts() {
    if (typeof document === 'undefined' || typeof document.getElementById !== 'function') return;
    if (!nodes.decisionChanges) nodes.decisionChanges = document.getElementById('decisionChanges');
    if (!nodes.candidateQuickComparison) {
      nodes.candidateQuickComparison = document.getElementById('candidateQuickComparison');
    }
  }

  function renderReviewToolPanels() {
    refreshReviewToolsMounts();
    renderDecisionChangesPanel();
    renderQuickComparison();
  }

  function refreshCandidateWorkspace() {
    renderCandidateList();
    renderCandidateEvidenceComparisonMount();
    renderQuickComparison();
  }

  function renderCurrentCandidateSelection() {
    var firstItem = getCandidateSelection(state.currentView).visibleItems[0] || null;
    beginCandidateSelection(firstItem);
    refreshCandidateWorkspace();
    renderCandidateDetail(state.activeItem);
    return firstItem;
  }

  function bindCandidateFilterEvents() {
    if (nodes.candidateSearch) {
      nodes.candidateSearch.addEventListener('input', function () {
        state.candidateQuery = normalizeString(nodes.candidateSearch.value).trim().toLowerCase();
        state.candidateLimit = 20;
        refreshCandidateWorkspace();
      });
    }
    if (nodes.candidateMore) {
      nodes.candidateMore.addEventListener('click', function () {
        state.candidateLimit += 20;
        refreshCandidateWorkspace();
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
        var byStrategy = selection.by_strategy || {};
        var dailyQuantity = (byStrategy.daily_fusion || {}).quantity || {};
        if (normalizeString(dailyQuantity.status) === 'partial') {
          var quantityAvailable = safeNumber(dailyQuantity.available_count, null);
          var quantityRequired = safeNumber(dailyQuantity.required_count, null);
          var quantityCount = quantityAvailable !== null && quantityRequired !== null
            ? ' ' + formatNumber(quantityAvailable, 0) + '/' + formatNumber(quantityRequired, 0)
            : '';
          selectionText = '正式策略数量输入部分核验' + quantityCount
            + '，保留已核验标的，其余待数据核验';
        } else {
          selectionText = '正式策略输入已核验，部分研究池输入缺失';
        }
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
    var cutoffText = asOf ? asOf.replace('T', ' ') : '未提供';
    var snapshotId = normalizeString(data.snapshot_id || getBootstrap().snapshotId || '本期快照未登记');
    setTextNode(nodes.headerTitle, '缠论决策工作台');
    setTextNode(nodes.headerSubtitle, '大盘证据 → 本期选股结论 → 个股条件与K线');
    nodes.headerMetrics.innerHTML = '<div class="compact-header-facts">'
      + '<span><small>交易日</small><strong>' + escapeHtml(dateLabel) + '</strong></span>'
      + '<span><small>版本</small><strong>' + escapeHtml(formal ? '正式收盘版' : '盘中预览') + '</strong></span>'
      + '<span><small>数据截止</small><strong title="' + escapeHtml(cutoffText) + '">' + escapeHtml(cutoffText) + '</strong></span>'
      + '<span><small>行情</small><strong>' + escapeHtml(marketStatus) + '</strong></span>'
      + '</div>';
    var detail = document.getElementById('reportDataDetails');
    if (detail) detail.innerHTML = '<summary>版本详情</summary><span>报告日 ' + escapeHtml(dateLabel)
      + ' · ' + escapeHtml(formal ? '正式收盘版' : '盘中预览') + ' · 数据截止 ' + escapeHtml(cutoffText)
      + ' · 快照 ' + escapeHtml(snapshotId) + '</span>';
    if (nodes.marketEvidence) {
      nodes.marketEvidence.innerHTML = buildExpandedMarketEvidence(data);
    }
    renderDecisionMarketBar(data);
  }

  function buildDecisionMarketSummary(data) {
    var source = data || {};
    var temperature = buildMarketTemperature(source);
    var quality = source.data_quality || {};
    var reportDate = normalizeString(source.date || getBootstrap().pageDate).trim() || '日期未提供';
    var asOf = normalizeString(quality.as_of || quality.generated_at).trim();
    var timeMatch = asOf.match(/(?:T|\s)(\d{2}:\d{2})/);
    var versionText = quality.is_official === true && normalizeString(quality.bar_state) === 'closed'
      ? '正式收盘版' : '盘中预览';
    var marketStatus = normalizeString(quality.market_status) === 'verified'
      ? '行情已核验' : '行情待核验';
    var degraded = quality.fallback_used === true || asArray(quality.warnings).length > 0;
    var scoreText = isRecommendationEvidenceFiniteNumber(temperature.score)
      ? recommendationEvidenceNumber(temperature.score) : '--';
    return '<div class="market-decision-state is-' + escapeHtml(temperature.tone || 'neutral') + '">'
      + '<span>综合情绪 / 100</span><strong>' + escapeHtml(temperature.label || '数据不足') + '</strong>'
      + '<em>' + escapeHtml(scoreText) + '</em></div>'
      + '<p class="market-score-explanation">由全 A 广度、涨跌停生态、指数、成交与趋势共同衡量。市场状态不等于个股满足买入条件。</p>'
      + '<div class="market-decision-quality"><span>' + escapeHtml(reportDate) + '</span>'
      + '<strong>' + escapeHtml(timeMatch ? timeMatch[1] : '--:--') + '</strong>'
      + '<small>' + escapeHtml(
        versionText + ' · ' + marketStatus + (degraded ? ' · 数据降级' : '')
      ) + '</small></div>';
  }

  function renderDecisionMarketBar(data) {
    var html = buildDecisionMarketSummary(data);
    if (nodes.marketDecisionSummary) nodes.marketDecisionSummary.innerHTML = html;
    return html;
  }

  function buildExpandedMarketEvidence(data) {
    var source = data || {};
    // Use the same dated, validated formal contract as the headline score.
    var contract = getFormalMarketSentimentContract(source);
    var evidence = contract ? contract.evidence : {};
    function value(key, field, decimals, scale, suffix) {
      var item = evidence[key] || {};
      var number = item[field];
      if (item.available !== true || !isRecommendationEvidenceFiniteNumber(number)) return '--';
      return formatNumber(number * (scale || 1), decimals) + (suffix || '');
    }
    var rows = [
      ['breadth', '全 A 广度', '上涨 ' + value('breadth', 'advance_count', 0) + ' · 下跌 ' + value('breadth', 'decline_count', 0)
        + ' · 平盘 ' + value('breadth', 'flat_count', 0), '上涨占比 ' + value('breadth', 'advance_ratio', 2, 1, '%')],
      ['limit_ecology', '涨跌停生态', '涨停 ' + value('limit_ecology', 'limit_up_count', 0) + ' · 跌停 ' + value('limit_ecology', 'limit_down_count', 0), '采用正式情绪统计口径'],
      ['index', '主要指数', value('index', 'valid_count', 0) + ' 个指数平均涨跌 ' + value('index', 'average_change_pct', 2, 1, '%'), '指数明细见上方'],
      ['turnover', '成交量能', '较 5 日均量 ' + value('turnover', 'ratio_to_ma5', 2, 1, ' 倍') + ' · 较 20 日均量 ' + value('turnover', 'ratio_to_ma20', 2, 1, ' 倍'), '1 倍表示与对应均量持平'],
      ['trend', '趋势结构', '站上 20 日均线占比 ' + value('trend', 'above_ma20_ratio', 2, 100, '%'), '用于观察上涨结构的覆盖范围'],
    ];
    var facts = rows.map(function (row) {
      var score = contract ? contract.components[row[0]] : null;
      return '<div class="market-fact-row"><dt>' + escapeHtml(row[1]) + '</dt><dd><strong>' + escapeHtml(row[2])
        + '</strong><span>' + escapeHtml(row[3]) + '</span></dd><dd class="market-fact-score"><small>分项得分</small><b>'
        + escapeHtml(isRecommendationEvidenceFiniteNumber(score) ? formatNumber(score, 2) : '--') + '</b></dd></div>';
    }).join('');
    var reading = contract
      ? '综合情绪' + contract.label + '（' + contract.score + '分）；全 A 上涨占比 ' + value('breadth', 'advance_ratio', 2, 1, '%')
        + '，主要指数平均涨跌 ' + value('index', 'average_change_pct', 2, 1, '%') + '。两者统计范围不同，请结合下方依据阅读。'
      : '综合情绪数据不足：本期正式证据未通过完整性与日期核验，不显示替代分数。';
    return '<p class="market-evidence-reading">' + escapeHtml(reading) + '</p>'
      + renderMarketIndexCards(getMarketItems(source.market || {}))
      + '<div class="market-evidence-body"><section aria-labelledby="marketFactsTitle"><h3 id="marketFactsTitle">判断依据</h3><dl class="market-facts">' + facts + '</dl></section>'
      + '<section class="market-evidence-trend" aria-labelledby="marketTrendTitle"><h3 id="marketTrendTitle">最近 20 个交易日情绪</h3>'
      + '<p>每日情绪与 3 日均线，观察强弱变化。</p><div id="marketSentimentChart" class="market-sentiment-chart" role="img" aria-label="最近20个交易日市场情绪折线图"></div>'
      + '<p class="market-evidence-coverage">正式组件覆盖 ' + escapeHtml(contract ? formatNumber(contract.coverage * 100, 0) + '%' : '--') + ' · 分数仅描述市场环境</p></section></div>';
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
    var resolved = resolvePrimaryNavigationState(nextView);
    var resolvedView = resolved.viewKey;
    var filterChanged = normalizeString(state.decisionStatusFilter)
      !== normalizeString(resolved.statusFilter);
    if (!resolvedView || (resolvedView === state.currentView && !filterChanged)) return;
    state.currentView = resolvedView;
    state.decisionStatusFilter = resolved.statusFilter;
    state.candidateQuery = '';
    state.candidateLimit = 20;
    if (nodes.candidateSearch) nodes.candidateSearch.value = '';
    renderWorkspaceTabs();
    renderViewDescription();
    renderCurrentCandidateSelection();
    if (focusTab && nodes.tabs) {
      var activeTab = nodes.tabs.querySelector('[data-view="' + resolvedView + '"]');
      if (activeTab && activeTab.focus) activeTab.focus();
    }
  }

  function renderPrimaryStatusFilters() {
    var items = asArray((getCandidateViews().views || {}).decision_formal);
    var formal = items.filter(function (item) {
      return isFormalWorkbenchItem(item && item.workbench_item ? item.workbench_item : item);
    }).length;
    var research = items.length - formal;
    var pending = items.filter(function (item) {
      return primaryDisplayMatchesStatus(item, 'formal_incomplete');
    }).length;
    var current = normalizeString(state.decisionStatusFilter).trim();
    return '<small class="decision-primary-composition">主推构成：正式 '
      + escapeHtml(String(formal)) + ' · 研究 ' + escapeHtml(String(research))
      + '；研究对象不升级正式</small>'
      + '<div class="decision-status-filters" role="group" aria-label="主推状态筛选">'
      + '<button type="button" data-decision-status-filter="" aria-pressed="'
      + (current ? 'false' : 'true') + '" class="' + (current ? '' : 'is-active')
      + '">全部状态 <span>' + escapeHtml(String(items.length)) + '</span></button>'
      + '<button type="button" data-decision-status-filter="formal_incomplete" aria-pressed="'
      + (current === 'formal_incomplete' ? 'true' : 'false') + '" class="'
      + (current === 'formal_incomplete' ? 'is-active' : '')
      + '">正式待确认 <span>' + escapeHtml(String(pending)) + '</span></button></div>';
  }

  function bindPrimaryStatusFilters() {
    if (!nodes.description || typeof nodes.description.querySelectorAll !== 'function') return;
    var buttons = nodes.description.querySelectorAll('[data-decision-status-filter]');
    for (var index = 0; index < buttons.length; index += 1) {
      buttons[index].addEventListener('click', function (event) {
        var filter = normalizeString(
          event.currentTarget.getAttribute('data-decision-status-filter')
        ).trim();
        activateWorkspaceView(
          filter === 'formal_incomplete' ? 'decision_wait' : 'decision_formal',
          false
        );
      });
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
    nodes.tabs.setAttribute('role', 'group');
    nodes.tabs.setAttribute('aria-label', '候选视图');
    var wsInfo = getCandidateViews();
    var groups = getWorkspaceNavigationGroups();
    var entries = groups.primary.concat(groups.research);
    var order = entries.map(function (entry) { return normalizeString(entry.key); });
    var primaryTabs = document.createElement('div');
    primaryTabs.className = 'workspace-tab-list';
    primaryTabs.setAttribute('role', 'tablist');
    primaryTabs.setAttribute('aria-label', '候选导航');
    for (var i = 0; i < groups.primary.length; i += 1) {
      primaryTabs.appendChild(buildWorkspaceTabButton(groups.primary[i], wsInfo, order));
    }
    nodes.tabs.appendChild(primaryTabs);
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
    researchTabs.setAttribute('role', 'tablist');
    researchTabs.setAttribute('aria-label', '研究来源');
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
    if (isDecisionView(state.currentView)) {
      if (state.currentView === 'decision_formal') {
        nodes.description.innerHTML = '<div class="view-description-copy">'
          + '主推合并原正式推荐、正式结果与优先关注的有效阅读集合；保留原顺序、角色、分数和执行条件。'
          + '原优先关注中的研究对象仍是研究待条件，不升级为正式或可执行。'
          + '</div>' + renderPrimaryStatusFilters();
        bindPrimaryStatusFilters();
        return;
      }
      var decisionCopy = {
        decision_all: '统一清单保留本期全部规范对象及原相对顺序。',
        decision_blocked: '集中查看待核验、策略分歧、失效或已有风险的对象。',
      }[state.currentView] || '';
      nodes.description.innerHTML = decisionCopy
        ? '<div class="view-description-copy">' + escapeHtml(decisionCopy) + '</div>'
        : '';
      return;
    }
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
      not_applicable: '本期不适用',
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
      if (item && typeof item === 'object') {
        return normalizeString(item.text || item.label || item.condition
          || item.reason || item.summary || item.value).trim();
      }
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

  function comparisonStrategyLabel(strategyId) {
    var value = normalizeString(strategyId).trim();
    var labels = {
      daily_fusion: '正式主推',
      main: '正式主推',
      h4_t3: 'H4 T+3',
      daily_pure: '基础候选',
      confirming: '等确认',
      startup_watchlist: '启动观察',
      next_day_boom: '加速池',
      luojie_pool: '罗姐池',
      observation_watchlist: '观察 Top5',
      growth_quality: '高弹性观察',
    };
    if (labels[value]) return labels[value];
    return getCurrentLabel(value) || value || '未命名策略';
  }

  function referencePurposeStatus(record) {
    var value = record && typeof record === 'object' ? record : {};
    var selectedContract = arguments.length > 1 ? arguments[1] : null;
    var contract = selectedContract && typeof selectedContract === 'object'
      ? selectedContract : getCandidateReferenceContract(value);
    return normalizeString(contract.purpose_status
      || contract.reference_price_purpose_status
      || contract.purpose
      || value.reference_price_purpose_status
      || value.reference_purpose_status
      || value.reference_price_status).trim().toLowerCase();
  }

  function rawReferencePurposeStatus(record) {
    var value = record && typeof record === 'object' ? record : {};
    return normalizeString(value.reference_price_purpose_status
      || value.reference_purpose_status
      || value.reference_price_status
      || value.reference_price_purpose).trim().toLowerCase();
  }

  function isReferencePurposeVerified(status) {
    var value = normalizeString(status).trim().toLowerCase();
    return value === 'verified' || value === 'formal';
  }

  function referencePurposeLabel(record) {
    var status = rawReferencePurposeStatus(record);
    if (status === 'verified' || status === 'formal') return '用途已核验';
    if (status === 'not_applicable') return '本期不适用';
    if (status === 'conflict') return '用途冲突，待核验';
    return '用途未核验';
  }

  function referencePurposeCopy(record, selectedContract) {
    var status = referencePurposeStatus(record, selectedContract);
    return status === 'verified' || status === 'formal'
      ? '' : '（用途未核验，仅原始记录）';
  }

  function referenceNumberText(value) {
    return isRecommendationEvidenceFiniteNumber(value)
      ? recommendationEvidenceNumber(value, 2) : '';
  }

  function rawReferenceText(record, formalReference) {
    var value = record && typeof record === 'object' ? record : {};
    var raw = safeNumber(value.reference_price, null);
    if (raw === null) return '';
    return '原始记录参考 ' + referenceNumberText(raw) + '（' + referencePurposeLabel(value) + '）';
  }

  function comparisonStrategySource(strategy) {
    var value = strategy && typeof strategy === 'object' ? strategy : {};
    var contract = value.contract && typeof value.contract === 'object' ? value.contract
      : (value.formal_decision_contract && typeof value.formal_decision_contract === 'object'
        ? value.formal_decision_contract
        : (value.decision_contract && typeof value.decision_contract === 'object'
          ? value.decision_contract : {}));
    var role = normalizeString(value.role).trim();
    var action = normalizeString(value.formal_action).trim()
      || normalizeString(value.action || value.page_action).trim()
      || (role === 'research' ? '仅观察' : '本期未声明正式动作');
    var evidence = value.evidence && typeof value.evidence === 'object' ? value.evidence : {};
    var summary = evidence.summary && typeof evidence.summary === 'object' ? evidence.summary : {};
    var statuses = Object.keys(evidence).map(function (key) {
      var section = evidence[key];
      return section && typeof section === 'object'
        ? normalizeString(section.status).trim().toLowerCase() : '';
    }).filter(Boolean);
    var evidenceStatus = statuses.length === 0 ? '证据未声明'
      : statuses.indexOf('conflict') !== -1 ? '证据冲突'
        : (statuses.indexOf('stale') !== -1 || statuses.indexOf('unavailable') !== -1)
          ? '证据不可用'
          : (statuses.indexOf('missing') !== -1 || statuses.indexOf('partial') !== -1)
            ? '证据未完整'
            : statuses.every(function (status) { return status === 'available'; })
              ? '证据可用' : '证据未核验';
    var referenceCopy = isRecommendationEvidenceFiniteNumber(contract.reference_price)
      ? referencePurposeCopy(value, contract) : '';
    var priceParts = [['参考价', contract.reference_price, referenceCopy], ['失效位', contract.invalidation_price, '']]
      .map(function (entry) {
        return isRecommendationEvidenceFiniteNumber(entry[1])
          ? entry[0] + ' ' + recommendationEvidenceNumber(entry[1], 2) + entry[2] : '';
      }).filter(Boolean);
    var priceBasis = contract.price_basis || value.price_basis;
    if (priceBasis && typeof priceBasis === 'object') {
      priceBasis = priceBasis.adjustment || priceBasis.basis || priceBasis.id;
    }
    if (normalizeString(priceBasis).trim()) priceParts.push('价基 ' + normalizeString(priceBasis).trim());
    return {
      source: comparisonStrategyLabel(value.strategy_id),
      sourceId: normalizeString(value.strategy_id).trim(),
      role: role || 'unknown',
      action: action,
      horizon: normalizeString(contract.intended_horizon || value.intended_horizon).trim() || '周期未声明',
      score: isRecommendationEvidenceFiniteNumber(value.score) ? Number(value.score) : null,
      prices: priceParts.join(' · ') || '价格合同未提供',
      strategyVersion: normalizeString(value.strategy_version || value.version).trim(),
      contractId: normalizeString(value.contract_id || value.plan_id
        || contract.contract_id || contract.plan_id).trim(),
      evidenceStatus: evidenceStatus,
    };
  }

  function comparisonStrategySourceText(source) {
    var value = source || {};
    var parts = [value.source + '：' + value.action];
    if (value.horizon && value.horizon !== '周期未声明') {
      parts.push('周期 ' + value.horizon);
    } else if (value.horizon === '周期未声明') {
      parts.push(value.horizon);
    }
    if (value.prices && value.prices !== '价格合同未提供') parts.push(value.prices);
    if (value.strategyVersion) parts.push('版本 ' + value.strategyVersion);
    if (value.contractId) parts.push('合同 ' + value.contractId);
    if (value.score !== null && value.score !== undefined) parts.push('分数 ' + recommendationEvidenceNumber(value.score));
    parts.push(value.evidenceStatus || '证据未声明');
    return parts.join(' · ');
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
    var sourceEvidence = asArray(source.__strategy_results).map(comparisonStrategySource);
    var currentDecision = source.__workbench_item
      ? getWorkbenchCurrentDecision(source.__workbench_item) : null;
    var sourceActionDisplay = sourceEvidence.map(function (strategy) {
      var text = comparisonStrategySourceText(strategy);
      if (!currentDecision || !currentDecision.currentDominates) return text;
      return (strategy.role === 'formal' ? '原策略结论：' : '研究结论：') + text;
    }).join('；');
    if (currentDecision && currentDecision.currentDominates) {
      sourceActionDisplay = [currentDecision.prompt, sourceActionDisplay].filter(Boolean).join('；');
    }
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
      poolHitSummary: getPoolHitSummary(source.__workbench_item || source),
      action: currentDecision && currentDecision.currentDominates
        ? currentDecision.statusLabel
        : (normalizeString(summary.formal_action).trim()
          || (sourceEvidence.length === 1 ? sourceEvidence[0].action : '本期未声明正式动作')),
      actionDisplay: sourceActionDisplay,
      sourceEvidence: sourceEvidence,
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

  function getCandidateComparisonEvidenceRows(viewKey, data) {
    var selection = getCandidateSelection(viewKey);
    return selection.items.map(function (item) {
      var unified = item && item.workbench_item ? item.workbench_item : null;
      var strategies = unified ? asArray(unified.strategy_results) : [];
      var selectedStrategy = strategies.find(function (strategy) {
        return strategy && strategy.strategy_id === unified.evidence_view;
      }) || strategies[0] || null;
      var selectedEvidence = selectedStrategy && selectedStrategy.evidence
        && typeof selectedStrategy.evidence === 'object'
        ? selectedStrategy.evidence : getCandidateRecommendationEvidence(item, data, viewKey);
      var evidence = selectedEvidence && typeof selectedEvidence === 'object'
        ? Object.assign({}, selectedEvidence) : {};
      var summary = evidence.summary && typeof evidence.summary === 'object'
        ? evidence.summary : {};
      var itemName = normalizeString(item && item.name).trim();
      var itemCode = normalizeString(item && item.code).trim();
      evidence.code = normalizeString(evidence.code || itemCode).trim() || itemCode;
      evidence.summary = Object.assign({}, summary, {
        code: normalizeString(summary.code || itemCode).trim() || itemCode,
        name: normalizeString(summary.name || itemName).trim() || itemName,
        sector: normalizeString(summary.sector || (item && item.sector)).trim(),
      });
      if (!evidence.summary.status) evidence.summary.status = 'missing';
      if (unified) {
        evidence.__strategy_results = strategies;
        evidence.__workbench_item = unified;
        if (!evidence.summary.formal_action && strategies.length === 1
            && selectedStrategy && selectedStrategy.role === 'research') {
          evidence.summary.formal_action = '仅观察';
        }
      }
      return evidence;
    });
  }

  function hasWorkspaceCandidateContract() {
    var workspace = state.workspace || {};
    var views = workspace.views;
    return Boolean(views && typeof views === 'object' && Object.keys(views).length);
  }

  function filterLegacyComparisonRows(rows, selection) {
    var value = selection || {};
    return asArray(rows).filter(function (row) {
      var source = row && typeof row === 'object' ? row : {};
      var summary = source.summary && typeof source.summary === 'object' ? source.summary : {};
      var candidate = Object.assign({}, source, {
        code: source.code || summary.code,
        name: source.name || summary.name,
        sector: source.sector || summary.sector,
        sector_name: source.sector_name || summary.sector,
        sector_code: source.sector_code || summary.sector_code,
      });
      if (filterCandidatesBySector(
        [candidate], value.sectorName, value.sectorCode, value.sectorRefs
      ).length === 0) return false;
      if (!value.query) return true;
      return [candidate.code, candidate.name, candidate.sector,
        candidate.sector_name].some(function (field) {
        return normalizeString(field).toLowerCase().indexOf(value.query) !== -1;
      });
    });
  }

  function renderCandidateEvidenceComparison(viewKey, data) {
    var projection = getRecommendationEvidenceProjection(data);
    var boundary = '<p class="candidate-evidence-boundary">保持正式池原顺序与当前匹配集合原始顺序；同股来源策略独立展示，正式动作仍以各自合同为准。身份、条件、证据与风险标签可重叠，标签数量不相加。</p>';
    var selection = getCandidateSelection(viewKey);
    var legacyRows = !hasWorkspaceCandidateContract() && !isDecisionView(viewKey)
      ? filterLegacyComparisonRows(getEvidenceRowsForView(viewKey, data), selection)
      : [];
    if (!projection && !selection.items.length && !legacyRows.length) {
      return boundary + '<div class="candidate-evidence-empty">本期未提供证据展示</div>';
    }
    var sourceRows = getCandidateComparisonEvidenceRows(viewKey, data);
    if (!sourceRows.length) sourceRows = legacyRows;
    var rows = sourceRows.map(normalizeCandidateEvidenceRow);
    if (!rows.length) {
      return boundary + '<div class="candidate-evidence-empty">当前集合没有匹配对象</div>';
    }
    var headers = [
      '候选', '来源策略与合同', '决策分', '池内排序证据', '信号与新鲜度',
      '价格位置', '日线结构', '30分钟确认', '量价与资金', '市场与板块',
      '风险与下一步', '数据状态', '历史验证',
    ];
    var tableRows = rows.map(function (row) {
      return '<tr>'
        + '<th scope="row"><div class="pool-hit-title">'
        + renderCandidateEvidenceCell(row.name || row.code, [row.code, row.sector].filter(Boolean).join(' · '))
        + renderPoolHitSummaryValue(row.poolHitSummary, 'comparison') + '</div></th>'
        + '<td>' + renderCandidateEvidenceCell(row.actionDisplay || row.action, '') + '</td>'
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
        ['来源策略与合同', row.actionDisplay || row.action],
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
        + escapeHtml([row.code, row.sector].filter(Boolean).join(' · ')) + '</small>'
        + renderPoolHitSummaryValue(row.poolHitSummary, 'comparison') + '</header>'
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

  function ensureQuickComparisonState() {
    if (!state.quickComparison || typeof state.quickComparison !== 'object') {
      state.quickComparison = { selectedKeys: [], selectedItems: {}, message: '', max: 3 };
    }
    if (!Array.isArray(state.quickComparison.selectedKeys)) state.quickComparison.selectedKeys = [];
    if (!state.quickComparison.selectedItems || typeof state.quickComparison.selectedItems !== 'object') {
      state.quickComparison.selectedItems = {};
    }
    state.quickComparison.max = Number(state.quickComparison.max) > 0
      ? Number(state.quickComparison.max) : 3;
    return state.quickComparison;
  }

  function quickComparisonKey(item, viewKey) {
    return candidateIdentityKey(item, viewKey || state.currentView);
  }

  function getQuickComparisonPool(viewKey) {
    return getCandidateSelection(viewKey || state.currentView, {
      query: '', sectorName: '', sectorCode: '', sectorRefs: [], limit: 0,
    }).items;
  }

  function getQuickComparisonRecords() {
    var store = ensureQuickComparisonState();
    var allItems = getQuickComparisonPool(state.currentView);
    var filteredItems = getCandidateSelection(state.currentView).items;
    return store.selectedKeys.map(function (key) {
      var item = store.selectedItems[key] || allItems.find(function (candidate) {
        return quickComparisonKey(candidate, state.currentView) === key;
      });
      if (!item) return null;
      var inCurrent = filteredItems.some(function (candidate) {
        return quickComparisonKey(candidate, state.currentView) === key;
      });
      return { key: key, item: item, inCurrent: inCurrent };
    }).filter(Boolean);
  }

  function findQuickComparisonItem(candidate) {
    var code = candidate && typeof candidate === 'object'
      ? toCodeKey(candidate.code) : toCodeKey(candidate);
    if (!code) return null;
    return getQuickComparisonPool(state.currentView).find(function (item) {
      return toCodeKey(item && item.code) === code;
    }) || null;
  }

  function toggleQuickComparisonSelection(candidate) {
    var store = ensureQuickComparisonState();
    if (typeof candidate === 'string' && store.selectedKeys.indexOf(candidate) !== -1) {
      return removeQuickComparisonSelection(candidate);
    }
    var item = candidate && typeof candidate === 'object'
      ? candidate : findQuickComparisonItem(candidate);
    if (!item) {
      store.message = '当前视图没有这只股票的已有记录。';
      return false;
    }
    var key = quickComparisonKey(item, state.currentView);
    var currentIndex = store.selectedKeys.indexOf(key);
    if (currentIndex !== -1) {
      store.selectedKeys.splice(currentIndex, 1);
      delete store.selectedItems[key];
      store.message = '';
      renderQuickComparison();
      return true;
    }
    if (store.selectedKeys.length >= store.max) {
      store.message = '最多比较 ' + store.max + ' 只，请先移除一只再加入。';
      renderQuickComparison();
      return false;
    }
    store.selectedKeys.push(key);
    store.selectedItems[key] = item;
    store.message = '';
    renderQuickComparison();
    return true;
  }

  function removeQuickComparisonSelection(key) {
    var store = ensureQuickComparisonState();
    var normalizedKey = normalizeString(key).trim();
    var currentIndex = store.selectedKeys.indexOf(normalizedKey);
    if (currentIndex === -1) return false;
    store.selectedKeys.splice(currentIndex, 1);
    delete store.selectedItems[normalizedKey];
    store.message = '';
    renderQuickComparison();
    return true;
  }

  function quickComparisonSourceEvidence(item) {
    var rec = item && item.workbench_item ? item.workbench_item : (item || {});
    var strategies = asArray(rec.strategy_results);
    if (strategies.length) return strategies;
    var evidence = getCandidateRecommendationEvidence(item, state.data, state.currentView) || {};
    var summary = evidence.summary && typeof evidence.summary === 'object' ? evidence.summary : {};
    var declaredContract = rec.formal_decision_contract && typeof rec.formal_decision_contract === 'object'
      ? rec.formal_decision_contract
      : (rec.decision_contract && typeof rec.decision_contract === 'object'
        ? rec.decision_contract : (rec.contract && typeof rec.contract === 'object' ? rec.contract : {}));
    var contract = Object.assign({}, declaredContract);
    ['invalidation_price', 'intended_horizon', 'price_basis'].forEach(function (field) {
      if (contract[field] === undefined && rec[field] !== undefined) contract[field] = rec[field];
    });
    var action = normalizeString(rec.formal_action || rec.effective_action || rec.page_action
      || rec.action || summary.formal_action).trim();
    var scoreCandidates = [rec.score, rec.decision_score && rec.decision_score.score,
      rec.decision_engine_v1 && rec.decision_engine_v1.total_score,
      rec.scoring_decision && rec.scoring_decision.total_score,
      rec.opportunity_score, rec.watch_score];
    var score = scoreCandidates.find(function (value) {
      return isRecommendationEvidenceFiniteNumber(value);
    });
    return [{
      strategy_id: rec.strategy_id || rec.source_strategy || state.currentView,
      role: rec.role || resolveViewDisplayContract(state.currentView, {}).role,
      formal_action: action || resolvePageAction(item, state.currentView),
      score: score,
      contract: contract,
      evidence: evidence,
    }];
  }

  function quickEvidenceText(section, fields) {
    if (!section || typeof section !== 'object') return '';
    return recommendationEvidenceSectionText(section, fields || ['summary', 'state', 'signal', 'reasons']);
  }

  function quickConditionTexts(strategies, key) {
    var values = [];
    asArray(strategies).forEach(function (strategy) {
      var evidence = strategy && strategy.evidence && typeof strategy.evidence === 'object'
        ? strategy.evidence : {};
      var risk = evidence.risk_and_next && typeof evidence.risk_and_next === 'object'
        ? evidence.risk_and_next : {};
      var block = risk[key] && typeof risk[key] === 'object' ? risk[key] : {};
      var items = recommendationEvidenceList(block.items);
      if (items.length) {
        if (normalizeString(block.status).trim() === 'conflict') {
          items = ['条件来源冲突，待核验：' + items.join('、')];
        }
        values = values.concat(items);
      } else if (normalizeString(block.status).trim() === 'not_applicable') {
        values.push(normalizeString(block.empty_text).trim() || '本期不适用，未进行观测');
      }
    });
    return values.filter(function (value, index, all) {
      return value && all.indexOf(value) === index;
    });
  }

  function quickConditionState(strategies, key) {
    var blocks = asArray(strategies).map(function (strategy) {
      var evidence = strategy && strategy.evidence && typeof strategy.evidence === 'object'
        ? strategy.evidence : {};
      var risk = evidence.risk_and_next && typeof evidence.risk_and_next === 'object'
        ? evidence.risk_and_next : {};
      return risk[key] && typeof risk[key] === 'object' ? risk[key] : null;
    }).filter(Boolean);
    if (!blocks.length) return 'missing';
    if (blocks.some(function (block) {
      return normalizeString(block.status).trim() !== 'available'
        || !recommendationEvidenceList(block.items).length;
    })) return 'missing';
    return 'available';
  }

  function quickComparisonRawReference(rec, strategies) {
    var formalReferences = asArray(strategies).map(function (strategy) {
      var contract = strategy && strategy.contract && typeof strategy.contract === 'object'
        ? strategy.contract : {};
      return safeNumber(contract.reference_price, null);
    }).filter(function (value) { return value !== null; });
    return rawReferenceText(rec, formalReferences.length ? formalReferences[0] : null);
  }

  function quickComparisonDimensionState(item, label) {
    var rec = item && item.workbench_item ? item.workbench_item : (item || {});
    var strategies = quickComparisonSourceEvidence(item);
    if (label === '下一核验') return quickConditionState(strategies, 'next_confirmation');
    if (label === '取消或降级') {
      var cancelStates = strategies.map(function (strategy) {
        var evidence = strategy && strategy.evidence && typeof strategy.evidence === 'object'
          ? strategy.evidence : {};
        var risk = evidence.risk_and_next && typeof evidence.risk_and_next === 'object'
          ? evidence.risk_and_next : {};
        return risk.invalidation_conditions && typeof risk.invalidation_conditions === 'object'
          ? 'invalidation_conditions' : 'cancel_conditions';
      });
      var key = cancelStates.some(function (value) { return value === 'invalidation_conditions'; })
        ? 'invalidation_conditions' : 'cancel_conditions';
      return quickConditionState(strategies, key);
    }
    if (label === '身份与来源动作') return strategies.length ? 'available' : 'missing';
    if (label === '结构依据') {
      return strategies.some(function (strategy) {
        var daily = strategy && strategy.evidence && strategy.evidence.daily_structure;
        return daily && normalizeString(daily.status).trim() === 'available'
          && quickEvidenceText(daily);
      }) ? 'available' : 'missing';
    }
    if (label === '未满足条件') {
      return asArray(rec.unmet_conditions || rec.missing_conditions
        || rec.blocking_reasons || rec.blocked_reasons).length || rec.is_executable === false
        ? 'available' : 'missing';
    }
    if (label === '关键价位') {
      return strategies.some(function (strategy) {
        var contract = strategy && strategy.contract && typeof strategy.contract === 'object'
          ? strategy.contract : {};
        return isRecommendationEvidenceFiniteNumber(contract.reference_price)
          || isRecommendationEvidenceFiniteNumber(contract.invalidation_price);
      }) ? 'available' : 'missing';
    }
    if (label === '主要风险') {
      if (asArray(rec.risk_flags).length) return 'available';
      return strategies.some(function (strategy) {
        var risk = strategy && strategy.evidence && strategy.evidence.risk_and_next;
        return risk && normalizeString(risk.status).trim() === 'available'
          && recommendationEvidenceList(risk.risk_labels).length;
      }) ? 'available' : 'missing';
    }
    if (label === '数据时效') {
      if (normalizeString((rec.data_status || {}).latest_date).trim()) return 'available';
      return strategies.some(function (strategy) {
        var summary = strategy && strategy.evidence && strategy.evidence.summary;
        return normalizeString(summary && (summary.as_of || summary.data_latest_date)).trim();
      }) ? 'available' : 'missing';
    }
    return 'missing';
  }

  function quickComparisonDimensionValues(item) {
    var rec = item && item.workbench_item ? item.workbench_item : (item || {});
    var strategies = quickComparisonSourceEvidence(item);
    var currentDecision = item && item.workbench_item
      ? getWorkbenchCurrentDecision(item) : null;
    var sourceFacts = strategies.map(function (strategy) {
      var source = comparisonStrategySource(strategy);
      var text = comparisonStrategySourceText(source);
      if (!currentDecision || !currentDecision.currentDominates) return text;
      return (source.role === 'formal' ? '原策略结论：' : '研究结论：') + text;
    }).filter(Boolean);
    if (currentDecision && currentDecision.currentDominates) {
      sourceFacts.unshift(currentDecision.prompt);
    }
    var structure = strategies.map(function (strategy) {
      var evidenceText = quickEvidenceText(
        (strategy || {}).evidence && (strategy || {}).evidence.daily_structure
      );
      var strategyReason = normalizeString(strategy && strategy.primary_reason).trim();
      var text = currentDecision && currentDecision.currentDominates
        ? [strategyReason, evidenceText].filter(function (value, index, values) {
          return value && values.indexOf(value) === index;
        }).join(' · ')
        : (evidenceText || strategyReason);
      return text && currentDecision && currentDecision.currentDominates
        ? (isFormalStrategyResult(strategy) ? '原策略依据：' : '研究依据：') + text
        : text;
    }).filter(Boolean);
    var unmet = asArray(rec.unmet_conditions || rec.missing_conditions || rec.blocking_reasons || rec.blocked_reasons)
      .map(normalizeString).filter(Boolean);
    var explicitFormalIdentity = isFormalWorkbenchItem(item);
    var explicitResearchIdentity = normalizeString(rec.action_semantics).trim() === 'watch_only'
      || strategies.some(function (strategy) {
        var role = normalizeString(strategy && strategy.role).trim();
        var semantics = normalizeString(strategy && strategy.action_semantics).trim();
        return role === 'research' || role === 'watch_only' || semantics === 'watch_only';
      });
    if (!unmet.length && rec.is_executable === false) {
      unmet.push(explicitFormalIdentity
        ? '正式条件尚未完整'
        : (explicitResearchIdentity ? '仅观察；后续核验见下方' : '未记录具体阻碍'));
    }
    var prices = strategies.map(function (strategy) {
      var source = comparisonStrategySource(strategy);
      return source.source + '：' + source.prices;
    }).filter(Boolean);
    if (!prices.length) prices.push('关键价位合同未声明');
    var rawReference = quickComparisonRawReference(rec, strategies);
    if (rawReference) prices.push(rawReference);
    var risks = asArray(rec.risk_flags).map(normalizeString).filter(Boolean);
    strategies.forEach(function (strategy) {
      var risk = strategy && strategy.evidence && strategy.evidence.risk_and_next;
      risks = risks.concat(recommendationEvidenceList(risk && risk.risk_labels));
    });
    risks = risks.filter(function (value, index, values) {
      return value && values.indexOf(value) === index;
    });
    var status = rec.data_status && typeof rec.data_status === 'object' ? rec.data_status : {};
    var freshness = [];
    if (normalizeString(status.latest_date).trim()) freshness.push('截至 ' + normalizeString(status.latest_date).trim());
    if (status.stale === true) freshness.push('数据陈旧');
    if (status.is_final === false) freshness.push('非终局');
    strategies.forEach(function (strategy) {
      var summary = strategy && strategy.evidence && strategy.evidence.summary;
      var asOf = normalizeString(summary && (summary.as_of || summary.data_latest_date)).trim();
      if (asOf) freshness.push(comparisonStrategyLabel(strategy.strategy_id) + '截至 ' + asOf);
    });
    return {
      '身份与来源动作': sourceFacts.join('；') || '来源策略未声明',
      '结构依据': structure.join('；')
        || (normalizeString(rec.primary_reason).trim()
          ? ((currentDecision && currentDecision.currentDominates ? '原策略依据：' : '')
            + normalizeString(rec.primary_reason).trim())
          : '结构依据未声明'),
      '未满足条件': unmet.join('、') || '未满足条件未声明',
      '关键价位': prices.join('；'),
      '主要风险': risks.join('、') || '主要风险未登记',
      '下一核验': quickConditionTexts(strategies, 'next_confirmation').join('；') || '下一核验未声明',
      '取消或降级': (quickConditionTexts(strategies, 'invalidation_conditions').concat(
        quickConditionTexts(strategies, 'cancel_conditions')
      ).filter(function (value, index, all) { return value && all.indexOf(value) === index; })).join('；') || '取消条件未声明',
      '数据时效': freshness.filter(function (value, index, values) {
        return value && values.indexOf(value) === index;
      }).join('；') || '数据时效未声明',
    };
  }

  function quickComparisonDimensionHtml(label, records, index) {
    var values = records.map(function (record) {
      return quickComparisonDimensionValues(record.item)[label];
    });
    var normalized = values.map(function (value) { return normalizeString(value).trim(); });
    var states = records.map(function (record) {
      return quickComparisonDimensionState(record.item, label);
    });
    var status = states.length && states.every(function (value) { return value === 'available'; })
      ? 'available' : 'missing';
    var value = values[index] || '--';
    return '<div class="quick-comparison-dimension'
      + '" data-quick-dimension="' + escapeHtml(label) + '" data-quick-status="'
      + status + '"><dt>' + escapeHtml(label)
      + '</dt><dd>' + escapeHtml(value) + '</dd></div>';
  }

  function bindQuickComparisonControls(target) {
    if (!target || typeof target.querySelectorAll !== 'function') return;
    var selectors = target.querySelectorAll('[data-quick-select]');
    for (var index = 0; index < selectors.length; index += 1) {
      selectors[index].addEventListener('change', function (event) {
        toggleQuickComparisonSelection(event.currentTarget.getAttribute('data-quick-select'));
      });
    }
    var removals = target.querySelectorAll('[data-quick-remove]');
    for (var removeIndex = 0; removeIndex < removals.length; removeIndex += 1) {
      removals[removeIndex].addEventListener('click', function (event) {
        var button = event.currentTarget;
        var storedKey = button.getAttribute('data-quick-key');
        if (storedKey) removeQuickComparisonSelection(storedKey);
        else toggleQuickComparisonSelection(button.getAttribute('data-quick-remove'));
      });
    }
    var detailButtons = target.querySelectorAll('[data-quick-detail]');
    for (var detailIndex = 0; detailIndex < detailButtons.length; detailIndex += 1) {
      detailButtons[detailIndex].addEventListener('click', function (event) {
        var button = event.currentTarget;
        openCurrentCandidateDetail(
          button.getAttribute('data-quick-detail'),
          button.getAttribute('data-quick-view')
        );
      });
    }
  }

  function renderQuickComparison(target) {
    target = target || nodes.candidateQuickComparison;
    if (!target) return '';
    var store = ensureQuickComparisonState();
    var records = getQuickComparisonRecords();
    var controls = getQuickComparisonPool(state.currentView).map(function (item) {
      var code = toCodeKey(item && item.code);
      var key = quickComparisonKey(item, state.currentView);
      var checked = store.selectedKeys.indexOf(key) !== -1;
      return '<label class="quick-comparison-select"><input type="checkbox" data-quick-select="'
        + escapeHtml(code) + '"' + (checked ? ' checked' : '') + '><span>'
        + escapeHtml((item && item.name) || code) + ' ' + escapeHtml(code) + '</span></label>';
    }).join('');
    var dimensions = ['身份与来源动作', '结构依据', '未满足条件', '下一核验', '取消或降级', '关键价位', '主要风险', '数据时效'];
    var columns = records.map(function (record, index) {
      var item = record.item || {};
      var code = toCodeKey(item.code);
      var status = record.inCurrent ? '' : '<small class="quick-comparison-outside">不在当前集合，可移除</small>';
      var currentCandidate = findCurrentCandidateForCode(code, state.currentView);
      var detailButton = currentCandidate
        ? '<button type="button" class="quick-comparison-detail" data-quick-detail="'
          + escapeHtml(code) + '" data-quick-view="' + escapeHtml(state.currentView)
          + '">查看当前图表</button>' : '';
      return '<article class="quick-comparison-column" data-quick-code="' + escapeHtml(code) + '">'
        + '<header><strong>' + escapeHtml(item.name || code) + '</strong><span>' + escapeHtml(code)
        + '</span><button type="button" data-quick-remove="' + escapeHtml(code)
        + '" data-quick-key="' + escapeHtml(record.key) + '">移除</button>'
        + detailButton + status + renderPoolHitSummary(item, 'comparison')
        + '</header><dl>' + dimensions.map(function (label) {
          return quickComparisonDimensionHtml(label, records, index);
        }).join('') + '</dl></article>';
    }).join('');
    var message = store.message ? '<p class="quick-comparison-message" role="status">'
      + escapeHtml(store.message) + '</p>' : '';
    var html = '<section class="quick-comparison" aria-label="轻量候选比较">'
      + '<header><div><h3>轻量比较</h3><p>最多选择 ' + store.max + ' 只；完整来源证据仍在下方多列比较。</p></div>'
      + '<small>比较字段来自已有当前快照</small></header>'
      + '<fieldset class="quick-comparison-selection"><legend>选择比较对象</legend>' + controls + '</fieldset>'
      + message + (columns ? '<div class="quick-comparison-grid">' + columns + '</div>'
        : '<p class="quick-comparison-empty">请选择当前集合中的股票。</p>') + '</section>';
    target.innerHTML = html;
    bindQuickComparisonControls(target);
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

  function buildCandidateRowSummary(item, viewKey) {
    var rec = item && typeof item === 'object' ? item : {};
    if (rec.workbench_item) {
      var unified = rec.workbench_item;
      var currentDecision = getWorkbenchCurrentDecision(rec);
      return { action: currentDecision.statusLabel,
        reason: currentDecision.currentDominates
          ? currentDecision.prompt : normalizeString(unified.primary_reason),
        scoreText: unified.formal_action && isRecommendationEvidenceFiniteNumber(unified.score)
          ? '决策分 ' + formatNumber(unified.score, 0) : '' };
    }
    var key = normalizeString(viewKey || state.currentView).trim();
    var evidence = getCandidateRecommendationEvidence(rec, state.data, key);
    var evidenceSummary = evidence && typeof evidence.summary === 'object'
      ? evidence.summary : {};
    var decision = resolveDecisionEngine(rec, null);
    var score = getDecisionScore(decision);
    var viewContract = resolveViewDisplayContract(key, {});
    var actionSemantics = normalizeString(viewContract.action_semantics).trim();
    var formalContext = actionSemantics === 'formal';
    var rowAction = resolvePageAction(
      Object.assign({}, rec, { action_semantics: actionSemantics }),
      key,
    );
    if (isIncidentReviewItem(rec)) {
      return {
        action: '仅追溯',
        reason: userFacingEvidenceText(
          evidenceScalarText(rec.page_action_reason) || '策略输入过期或未核验，仅供事故复盘。',
          true,
        ),
        scoreText: '暂无正式决策分',
      };
    }
    return {
      action: rowAction,
      reason: formalContext
        ? getCandidatePublicReason(rec, evidenceSummary, key)
        : userFacingEvidenceText(evidenceScalarText(rec.page_action_reason), false),
      scoreText: score === null
        ? '暂无正式决策分'
        : '决策分 ' + formatNumber(score, 0),
    };
  }

  function formalDecisionScoreValue(value) {
    if (typeof value !== 'number' && typeof value !== 'string') return null;
    if (typeof value === 'string' && !value.trim()) return null;
    var score = Number(value);
    return Number.isFinite(score) && score >= 0 && score <= 100 ? score : null;
  }

  function isFormalStrategyResult(strategy) {
    var value = strategy && typeof strategy === 'object' ? strategy : {};
    var role = normalizeString(value.role).trim();
    return role ? role === 'formal'
      : normalizeString(value.action_semantics).trim() === 'formal';
  }

  function candidateFormalScoreEntries(item, viewKey) {
    var rec = item && typeof item === 'object' ? item : {};
    if (isIncidentReviewItem(rec)) return [];
    var unified = rec.workbench_item && typeof rec.workbench_item === 'object'
      ? rec.workbench_item : null;
    if (unified) {
      return asArray(unified.strategy_results).map(function (strategy) {
        if (!isFormalStrategyResult(strategy)
            || isIncidentReviewItem(strategy && strategy.candidate)) return null;
        var sourceId = normalizeString(strategy.strategy_id).trim();
        if (!sourceId) return null;
        var score = formalDecisionScoreValue(strategy && strategy.score);
        if (score === null) return null;
        return {
          sourceId: sourceId,
          label: getCurrentLabel(sourceId) || sourceId || '正式来源',
          score: score,
        };
      }).filter(Boolean);
    }
    var key = normalizeString(viewKey || state.currentView).trim();
    if (resolveViewDisplayContract(key, {}).action_semantics !== 'formal') return [];
    var explicitSemantics = normalizeString(rec.action_semantics).trim();
    var explicitRole = normalizeString(rec.role).trim();
    if ((explicitSemantics && explicitSemantics !== 'formal')
        || (explicitRole && explicitRole !== 'formal')) return [];
    var legacyDecision = resolveDecisionEngine(rec, null);
    var legacyScore = formalDecisionScoreValue(
      legacyDecision && legacyDecision.total_score
    );
    return legacyScore === null ? [] : [{
      sourceId: key,
      label: getCurrentLabel(key) || '正式来源',
      score: legacyScore,
    }];
  }

  function renderCandidateFormalScores(item, viewKey) {
    var scores = candidateFormalScoreEntries(item, viewKey);
    if (!scores.length) return '';
    return '<span class="candidate-row-source-scores" aria-label="正式来源原决策分">'
      + scores.map(function (entry) {
        return '<span class="candidate-row-score" data-source-score="'
          + escapeHtml(entry.sourceId) + '">' + escapeHtml(entry.label)
          + ' 决策分 ' + escapeHtml(formatNumber(entry.score, 0)) + '</span>';
      }).join('') + '</span>';
  }

  function stockFactNumber(value) {
    return typeof value === 'number' && Number.isFinite(value) ? value : null;
  }

  function hasVerifiedBasicFacts(record) {
    var status = record.data_status;
    if (status && (status.daily || status.latest_date)) {
      return status.daily === 'verified' && status.is_final === true && status.stale === false
        && !!(state.data || {}).date && status.latest_date === state.data.date;
    }
    return hasVerifiedSignalCloseEvidence(record);
  }

  function stockPriceBasis(record) {
    var basis = record.price_basis;
    if (basis && typeof basis === 'object') basis = basis.adjustment;
    basis = normalizeString(basis || (record.data_status || {}).adjustment).toLowerCase();
    return ['raw', 'qfq', 'hfq'].indexOf(basis) >= 0 ? basis : '';
  }

  function stockCurrentPrice(record) {
    // Legacy startup.close is a structure anchor, not the latest daily close.
    return [record.current_price, asArray(record.closes).slice(-1)[0],
      (record.best_buy_point || {}).current_price].map(stockFactNumber)
      .find(function (v) { return v !== null && v > 0; });
  }

  function candidateBasicFacts(item) {
    var rec = item || {};
    var raw = findRawCandidate(rec.ref || {}) || {};
    var quote = [rec, raw].find(function (record) {
      return hasVerifiedBasicFacts(record);
    }) || {};
    var verified = hasVerifiedBasicFacts(quote);
    var bp = quote.best_buy_point || {};
    var price = stockCurrentPrice(quote);
    var changes = [quote.change_pct, bp.change_pct].map(stockFactNumber);
    var change = changes.find(function (v) { return v !== null; });
    var health = quote.data_status || quote.reference_close_evidence || rec.data_status || {};
    var basis = stockPriceBasis(quote);
    // The compact workspace drops adjustment; recover only from the same verified price.
    var rawPrice = stockCurrentPrice(raw);
    if (!basis && hasVerifiedBasicFacts(raw)
        && rawPrice !== undefined && rawPrice === price) {
      basis = stockPriceBasis(raw);
    }
    return {
      sector: normalizeString(rec.sector || (rec.workbench_item || {}).sector || raw.sector || raw.industry).trim(),
      quote: quote, raw: raw, verified: verified,
      price: verified && price !== undefined ? price : null,
      change: verified && change !== undefined ? change : null,
      date: normalizeString(health.latest_date || health.reference_date || health.date),
      priceLabel: basis === 'raw' ? '收盘价' : '图表价',
      basisLabel: { raw: '不复权', qfq: '前复权', hfq: '后复权' }[basis] || '价格口径未提供',
    };
  }

  function renderCandidateBasicInfo(item, detail) {
    var facts = candidateBasicFacts(item);
    var changeClass = facts.change > 0 ? 'is-up' : facts.change < 0 ? 'is-down' : '';
    var priceText = facts.price === null ? '未提供' : formatNumber(facts.price, 2);
    var changeText = facts.change === null ? '未提供' : formatPct(facts.change, true);
    return '<div class="candidate-basic-info' + (detail ? ' is-detail' : '') + '">'
      + '<span class="candidate-sector">' + escapeHtml(facts.sector || '板块未提供') + '</span>'
      + '<div class="candidate-quote-line">'
      + '<span><small>' + escapeHtml(facts.priceLabel) + '</small><strong>' + escapeHtml(priceText) + '</strong></span>'
      + '<span class="' + changeClass + '"><small>当日涨跌</small><strong>' + escapeHtml(changeText) + '</strong></span>'
      + '</div>'
      + (detail ? '<p class="candidate-quote-note">数据日期 ' + escapeHtml(facts.date || '未提供')
        + ' · ' + (facts.verified ? '已核验收盘数据' : '数据未核验')
        + ' · ' + escapeHtml(facts.basisLabel) + '；非实时行情</p>'
        : (!facts.verified ? '<small class="candidate-quote-note">数据未核验</small>' : ''))
      + '</div>';
  }

  function sameCandidateSourceRef(left, right) {
    var leftRef = left && typeof left === 'object' ? left : {};
    var rightRef = right && typeof right === 'object' ? right : {};
    var leftPool = normalizeString(leftRef.pool || leftRef.source_pool).trim();
    var rightPool = normalizeString(rightRef.pool || rightRef.source_pool).trim();
    var leftCode = toCodeKey(leftRef.code);
    var rightCode = toCodeKey(rightRef.code);
    return Boolean(leftPool && rightPool && leftCode && rightCode
      && leftPool === rightPool && leftCode === rightCode);
  }

  function candidateFactEvidenceTarget(item, facts, evidenceKey, moduleNumber) {
    var rec = item && typeof item === 'object' ? item : {};
    var ref = rec.ref && typeof rec.ref === 'object' ? rec.ref : {};
    var raw = facts && facts.raw && typeof facts.raw === 'object' ? facts.raw : null;
    if (!raw || !sameCandidateSourceRef(ref, {
      pool: ref.pool || ref.source_pool,
      code: raw.code,
    })) return '';
    var unified = rec.workbench_item && typeof rec.workbench_item === 'object'
      ? rec.workbench_item : null;
    if (unified) {
      var strategies = asArray(unified.strategy_results);
      var sourceRefs = asArray(unified.source_refs).filter(function (sourceRef) {
        return sourceRef && typeof sourceRef === 'object';
      });
      var sourceView = normalizeString(rec.evidence_view).trim();
      var matches = [];
      function findStrategyMatches(view) {
        var found = [];
        strategies.forEach(function (strategy, index) {
          if (normalizeString(strategy && strategy.strategy_id).trim() === view) {
            found.push({ strategy: strategy, index: index });
          }
        });
        return found;
      }
      if (sourceView) {
        matches = findStrategyMatches(sourceView);
        if (matches.length !== 1) return '';
        var selectedCandidate = matches[0].strategy.candidate;
        var selectedCandidateRef = selectedCandidate && typeof selectedCandidate === 'object'
          && selectedCandidate.ref && typeof selectedCandidate.ref === 'object'
          ? selectedCandidate.ref : null;
        var selectedSourceRefs = sourceRefs.filter(function (sourceRef) {
          return normalizeString(sourceRef.view).trim() === sourceView;
        });
        if (selectedSourceRefs.some(function (sourceRef) {
          return !sameCandidateSourceRef(ref, sourceRef.ref);
        })) return '';
        if (selectedCandidateRef) {
          if (!sameCandidateSourceRef(ref, selectedCandidateRef)) return '';
        } else if (selectedSourceRefs.length !== 1
            || !sameCandidateSourceRef(ref, selectedSourceRefs[0].ref)) {
          return '';
        }
        var hasSourceConflict = sourceRefs.some(function (sourceRef) {
          if (!sameCandidateSourceRef(ref, sourceRef.ref)) return false;
          var mapped = findStrategyMatches(normalizeString(sourceRef.view).trim());
          if (mapped.length !== 1) return true;
          var mappedCandidate = mapped[0].strategy.candidate;
          var mappedRef = mappedCandidate && typeof mappedCandidate === 'object'
            && mappedCandidate.ref && typeof mappedCandidate.ref === 'object'
            ? mappedCandidate.ref : null;
          return Boolean(mappedRef && !sameCandidateSourceRef(sourceRef.ref, mappedRef));
        });
        if (hasSourceConflict) return '';
      } else {
        var matchingSourceRefs = sourceRefs.filter(function (sourceRef) {
          return sameCandidateSourceRef(ref, sourceRef.ref);
        });
        if (matchingSourceRefs.length !== 1) return '';
        sourceView = normalizeString(matchingSourceRefs[0].view).trim();
        matches = findStrategyMatches(sourceView);
        if (!sourceView || matches.length !== 1) return '';
        var fallbackCandidate = matches[0].strategy.candidate;
        var fallbackRef = fallbackCandidate && typeof fallbackCandidate === 'object'
          && fallbackCandidate.ref && typeof fallbackCandidate.ref === 'object'
          ? fallbackCandidate.ref : null;
        if (fallbackRef && !sameCandidateSourceRef(ref, fallbackRef)) return '';
      }
      var evidence = matches[0].strategy.evidence;
      if (!evidence || typeof evidence !== 'object'
          || !evidence[evidenceKey] || typeof evidence[evidenceKey] !== 'object'
          || normalizeString(evidence[evidenceKey].status).trim().toLowerCase() === 'missing') return '';
      return 'evidence-module-' + strategyEvidencePrefix(matches[0].strategy, matches[0].index)
        + '-' + moduleNumber;
    }
    var evidenceView = normalizeString(rec.evidence_view || state.currentView).trim();
    var viewContract = resolveViewDisplayContract(evidenceView, {});
    var sourcePool = normalizeString(viewContract.source_pool).trim();
    var refPool = normalizeString(ref.pool || ref.source_pool).trim();
    var legacyEvidence = sourcePool && sourcePool === refPool
      ? getCandidateRecommendationEvidence(rec, state.data, evidenceView) : null;
    if (!legacyEvidence || typeof legacyEvidence[evidenceKey] !== 'object'
        || normalizeString(legacyEvidence[evidenceKey].status).trim().toLowerCase() === 'missing') return '';
    return moduleNumber === '05' ? 'volume' : 'price';
  }

  function renderCandidateFactPanel(item) {
    var rec = item || {};
    var facts = candidateBasicFacts(rec);
    var quality = hasVerifiedBasicFacts(rec) ? (rec.pool_quality || {}) : {};
    var raw = facts.verified ? facts.raw : {};
    var rows = [];
    var priceTarget = candidateFactEvidenceTarget(rec, facts, 'price_evidence', '02');
    var volumeTarget = candidateFactEvidenceTarget(rec, facts, 'volume_and_capital', '05');
    function add(label, value, suffix, divisor, target) {
      var number = stockFactNumber(value);
      if (number !== null && number >= 0) {
        rows.push([label, formatNumber(number / (divisor || 1), 2) + (suffix || ''), target || '']);
      }
    }
    function canonicalVolumeWindow(record, length) {
      var units = asArray(record && record.volume_units);
      var rawUnits = asArray(record && record.volume_raw_units);
      var sources = asArray(record && record.volume_sources);
      if (units.length < length || rawUnits.length < length || sources.length < length) return false;
      units = units.slice(-length);
      rawUnits = rawUnits.slice(-length);
      sources = sources.slice(-length);
      return units.every(function (unit) {
        return normalizeString(unit).trim().toLowerCase() === 'hands';
      }) && rawUnits.every(function (unit) {
        unit = normalizeString(unit).trim().toLowerCase();
        return unit === 'hands' || unit === 'shares';
      }) && sources.every(function (source) {
        return normalizeString(source).trim() !== '';
      });
    }
    // Upstream volume_ratio20 can contain a 5-day ratio. Use exactly 20 prior bars.
    var volumeRecord = [facts.quote, raw].find(function (record) {
      return hasVerifiedBasicFacts(record)
        && asArray(record.volumes).length >= 21
        && canonicalVolumeWindow(record, 21);
    });
    var volumes = asArray((volumeRecord || {}).volumes).slice(-21).map(stockFactNumber);
    if (volumes.length === 21
        && canonicalVolumeWindow(volumeRecord || {}, 21)
        && volumes.every(function (v) { return v !== null && v >= 0; })) {
      var mean = volumes.slice(0, 20).reduce(function (sum, v) { return sum + v; }, 0) / 20;
      if (mean > 0) add('较20日均量', volumes[20] / mean, '倍', 1, volumeTarget);
    }
    var money20 = quality.money20 === undefined ? raw.money20 : quality.money20;
    var money20Number = stockFactNumber(money20);
    var liquiditySource = normalizeString(
      quality.liquidity_source === undefined ? raw.liquidity_source : quality.liquidity_source
    ).trim();
    var liquidityWindow = stockFactNumber(
      quality.liquidity_window_bars === undefined
        ? raw.liquidity_window_bars
        : quality.liquidity_window_bars
    );
    if (money20Number !== null && money20Number > 0) {
      if (liquidityWindow === 20 && liquiditySource === 'amounts') {
        add('20日均成交额', money20Number, '亿', 100000000, volumeTarget);
      } else if (liquidityWindow === 20 && liquiditySource === 'volume_price_proxy') {
        add('估算20日均成交额', money20Number, '亿', 100000000, volumeTarget);
      } else {
        rows.push(['20日均成交额', '成交额来源未核验', volumeTarget]);
      }
    }
    add('总市值', quality.market_cap, '亿');
    add('流通市值', quality.circulating_market_cap, '亿');
    // Keep each reference with its original role; a research anchor is not a stop.
    var reference = hasVerifiedBasicFacts(rec) ? stockFactNumber(rec.reference_price) : null;
    if (reference !== null && reference > 0) {
      var rawPurposeStatus = rawReferencePurposeStatus(rec);
      var referenceUsable = rawPurposeStatus === 'verified' || rawPurposeStatus === 'formal';
      rows.push(['结构参考', formatNumber(reference, 2) + (referenceUsable
        ? '（非失效位）' : '（用途未核验，仅原始记录）'), priceTarget]);
      var distance = referenceUsable ? stockFactNumber(rec.distance_from_reference_pct) : null;
      if (distance !== null) rows.push(['距结构参考', formatPct(distance, true), priceTarget]);
    }
    var value = rec.workbench_item || {};
    var contract = value.contracts || rec.formal_decision_contract || {};
    if (value.formal_action || rec.action_semantics === 'formal') {
      [['正式参考价', 'reference_price'], ['失效位', 'invalidation_price']].forEach(function (field) {
        var price = stockFactNumber(contract[field[1]]);
        rows.push([field[0], price !== null && price > 0 ? formatNumber(price, 2) : '未提供',
          price !== null && price > 0 ? priceTarget : '']);
      });
    }
    return '<section class="candidate-fact-panel" aria-label="量能与参考位">'
      + (rows.length ? '<dl>' + rows.map(function (row) {
        var content = escapeHtml(row[1]);
        if (row[2]) {
          content = '<button type="button" class="candidate-fact-jump" data-evidence-target="'
            + escapeHtml(row[2]) + '">' + content + '</button>';
        }
        return '<div class="candidate-fact-row"><dt>'
          + escapeHtml(row[0]) + '</dt><dd>' + content + '</dd></div>';
      }).join('') + '</dl>' : '<p class="candidate-quote-note">量能与参考位数据未提供</p>')
      + '<p class="candidate-quote-note">仅展示本期已有数据；未提供的成交额、换手率或市值不作推算。</p></section>';
  }

  function renderCandidateRowIdentity(item, viewKey, rowSummary) {
    var status = getCandidateStatusSummary(item, viewKey);
    var action = normalizeString(rowSummary && rowSummary.action).trim() || status.condition;
    var identity = status.identity || '身份未声明';
    return '<div class="candidate-row-identity">'
      + '<div class="candidate-identity"><strong class="candidate-name">'
      + escapeHtml(normalizeString(item && item.name) || ('未命名 ' + normalizeString(item && item.code)))
      + '</strong><span class="candidate-code">' + escapeHtml(normalizeString(item && item.code)) + '</span></div>'
      + '<div class="candidate-row-identity-status"><span class="candidate-row-action">'
      + escapeHtml(action) + '</span><span class="candidate-row-identity-label">'
      + escapeHtml(identity) + '</span>' + renderCandidateFormalScores(item, viewKey)
      + '</div></div>' + renderPoolHitSummary(item, 'list');
  }

  function buildCandidateMarketContext(items) {
    var facts = asArray(items).map(function (item) {
      return candidateBasicFacts(item || {});
    });
    if (!facts.length) return null;
    var first = facts[0];
    if (!first.date || !first.basisLabel) return null;
    var same = facts.every(function (item) {
      return item.date === first.date
        && item.basisLabel === first.basisLabel
        && item.verified === first.verified;
    });
    if (!same) return null;
    return {
      date: first.date,
      basisLabel: first.basisLabel,
      verified: first.verified,
      text: '列表行情共同口径：数据日期 ' + first.date + ' · ' + first.basisLabel
        + ' · 非实时 · ' + (first.verified ? '已核验收盘数据' : '数据未核验'),
    };
  }

  function renderCandidateRowMarket(item, commonContext) {
    var facts = candidateBasicFacts(item || {});
    var changeClass = facts.change > 0 ? 'is-up' : facts.change < 0 ? 'is-down' : '';
    var price = facts.price === null ? '未提供' : formatNumber(facts.price, 2);
    var change = facts.change === null ? '未提供' : formatPct(facts.change, true);
    var date = facts.date || '未提供';
    var marketMeta = '数据日期 ' + date + ' · ' + facts.basisLabel + ' · 非实时';
    var sameAsContext = commonContext
      && facts.date === commonContext.date
      && facts.basisLabel === commonContext.basisLabel
      && facts.verified === commonContext.verified;
    var marketLabel = [facts.sector || '板块未提供', facts.priceLabel + ' ' + price,
      '当日 ' + change, marketMeta].join(' · ');
    var exceptionMeta = sameAsContext ? ''
      : '<span class="candidate-row-market-meta">' + escapeHtml(marketMeta) + '</span>';
    return '<div class="candidate-row-market" aria-label="' + escapeHtml(marketLabel)
      + '" title="' + escapeHtml(marketMeta) + '">'
      + '<span class="candidate-row-sector">' + escapeHtml(facts.sector || '板块未提供') + '</span>'
      + '<span class="candidate-row-price"><small>' + escapeHtml(facts.priceLabel) + '</small><strong>' + escapeHtml(price) + '</strong></span>'
      + '<span class="candidate-row-change ' + changeClass + '"><small>当日</small><strong>' + escapeHtml(change) + '</strong></span>'
      + exceptionMeta
      + '</div>';
  }

  function candidateSourceRiskLabels(item, viewKey) {
    var rec = item && typeof item === 'object' ? item : {};
    var evidence = getCandidateRecommendationEvidence(rec, state.data, viewKey);
    var risk = evidence && evidence.risk_and_next
      && typeof evidence.risk_and_next === 'object' ? evidence.risk_and_next : {};
    var risks = recommendationEvidenceList(risk.risk_labels);
    if (!risks.length && rec.workbench_item) {
      var workbench = rec.workbench_item;
      var sourceView = normalizeString(rec.evidence_view || workbench.evidence_view).trim();
      var selected = asArray(workbench.strategy_results).filter(function (strategy) {
        return normalizeString(strategy && strategy.strategy_id).trim() === sourceView;
      });
      if (selected.length === 1) {
        risks = asArray((selected[0].candidate || {}).risk_flags)
          .map(normalizeString).filter(Boolean);
      }
    } else if (!risks.length) {
      risks = asArray(rec.risk_flags).map(normalizeString).filter(Boolean);
    }
    return risks.filter(function (value, index, values) {
      return value && values.indexOf(value) === index;
    });
  }

  function renderCandidateRowReason(item, viewKey, rowSummary) {
    var rec = item || {};
    var blockers = asArray((rec.workbench_item || rec).blocking_reasons || (rec.workbench_item || rec).blocked_reasons);
    var riskFlags = candidateSourceRiskLabels(rec, viewKey);
    var status = getCandidateStatusSummary(rec, viewKey);
    var parts = [];
    var reason = normalizeString(rowSummary && rowSummary.reason).trim();
    if (reason) parts.push(reason);
    blockers.forEach(function (blocker) {
      blocker = normalizeString(blocker).trim();
      if (blocker && parts.join('；').indexOf(blocker) === -1) parts.push(blocker);
    });
    var riskText = '风险：' + (riskFlags.length ? riskFlags.join('、') : '未登记');
    if (parts.join('；').indexOf(riskText) === -1) parts.push(riskText);
    if (status.evidence && status.evidence !== '证据可用') {
      var evidenceText = '证据：' + status.evidence;
      if (parts.join('；').indexOf(evidenceText) === -1) parts.push(evidenceText);
    }
    if (!parts.length) parts.push('本期未提供核心理由或阻碍说明');
    reason = parts.join(' · ');
    return '<p class="candidate-row-reason"><span>核心判断</span>' + escapeHtml(reason) + '</p>';
  }

  function renderCandidateList() {
    if (!nodes.candidateList) return;
    nodes.candidateList.innerHTML = '';

    var selection = getCandidateSelection(state.currentView);
    var poolItems = selection.poolItems;
    var items = selection.items;
    var visibleItems = selection.visibleItems;
    var query = selection.query;
    var unifiedMainEmpty = isDecisionView(state.currentView)
      ? items.length === 0
      : state.currentView === 'main' && !query && !state.sectorFilter && items.length === 0;
    if (nodes.workspaceBody && nodes.workspaceBody.classList) {
      nodes.workspaceBody.classList.toggle('is-unified-empty', unifiedMainEmpty);
    }
    if (nodes.candidateTools) {
      nodes.candidateTools.hidden = isDecisionView(state.currentView) && poolItems.length === 0;
    }
    var activeVisible = visibleItems.some(function (candidate) {
      return state.activeItem
        && toCodeKey(candidate && candidate.code) === toCodeKey(state.activeItem.code);
    });
    if (visibleItems.length && !activeVisible) {
      beginCandidateSelection(visibleItems[0]);
    } else if (!visibleItems.length && !query && !state.sectorFilter) {
      beginCandidateSelection(null);
    }
    if (visibleItems.length) {
      var detailTarget = getCandidateDetailTarget();
      if (!isCandidateDetailMounted(state.activeItem, detailTarget)) {
        renderCandidateDetail(state.activeItem, detailTarget);
      }
    }
    if (nodes.candidateCount) {
      nodes.candidateCount.textContent = '显示 ' + visibleItems.length + ' / ' + items.length
        + (query || state.sectorFilter || selection.statusFilter
          ? '（原池 ' + poolItems.length + '）' : '');
    }
    if (nodes.candidateMore) {
      nodes.candidateMore.hidden = visibleItems.length >= items.length;
    }
    if (!items || items.length === 0) {
      clearCandidateDetailLifecycle(nodes.detailPanel);
      if (nodes.drawerContent && nodes.drawerContent !== nodes.detailPanel) {
        clearCandidateDetailLifecycle(nodes.drawerContent);
      }
      var viewMeta = (getCandidateViews().meta || {})[state.currentView] || {};
      var rawAvailability = viewMeta.availability || {};
      var filteredEmpty = Boolean(query || state.sectorFilter);
      var traceSuppressed = filteredEmpty || Boolean(selection.statusFilter);
      nodes.candidateList.innerHTML = buildCandidateEmptyState(state.currentView, rawAvailability, {
        filtered: filteredEmpty,
        filterLabel: state.sectorFilter || normalizeString(nodes.candidateSearch && nodes.candidateSearch.value),
      }) + (traceSuppressed ? '' : renderLegacyRawConditionTrace(state.currentView));
      var openAll = nodes.candidateList.querySelector('[data-workbench-open-all]');
      if (openAll) openAll.addEventListener('click', function () { activateWorkspaceView('decision_all', true); });
      var openResearch = nodes.candidateList.querySelector('[data-open-research-observation]');
      if (openResearch) openResearch.addEventListener('click', function () {
        var targetView = getDecisionWorkbench() ? 'decision_all' : legacyObservationViewKey();
        if (!targetView) return;
        activateWorkspaceView(targetView, true);
        var target = document.getElementById('candidateWorkspace');
        if (target && target.scrollIntoView) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
      });
      nodes.detailPanel.innerHTML = unifiedMainEmpty
        ? ''
        : buildCandidateEmptyState(state.currentView, rawAvailability, {
          filtered: filteredEmpty,
          filterLabel: state.sectorFilter || normalizeString(nodes.candidateSearch && nodes.candidateSearch.value),
        });
      return;
    }

    var poolHitNote = document.createElement('p');
    poolHitNote.className = 'pool-hit-note';
    poolHitNote.textContent = '按来源池计数，含上游基础池；榜单重复收录不叠加';
    nodes.candidateList.appendChild(poolHitNote);

    var marketContext = buildCandidateMarketContext(visibleItems);
    if (marketContext) {
      var contextNode = document.createElement('p');
      contextNode.className = 'candidate-list-market-context';
      contextNode.textContent = marketContext.text;
      nodes.candidateList.appendChild(contextNode);
    }

    for (var i = 0; i < visibleItems.length; i += 1) {
      var item = visibleItems[i] || {};
      var row = document.createElement('button');
      var code = normalizeString(item.code || '');
      var name = normalizeString(item.name || '');
      var rowSummary = buildCandidateRowSummary(item, state.currentView);

      row.type = 'button';
      row.className = 'candidate-row';
      row.setAttribute('data-code', code);
      row.setAttribute('data-name', name);
      row.setAttribute('data-status', (item.workbench_item || {}).page_status || '');
      row.setAttribute(
        'tabindex',
        state.activeItem && state.activeItem.code === code ? '0' : '-1'
      );
      row.innerHTML = ''
        + '<div class="candidate-row-main">'
        + renderCandidateRowIdentity(item, state.currentView, rowSummary)
        + renderCandidateRowMarket(item, marketContext)
        + renderCandidateRowReason(item, state.currentView, rowSummary)
        + '</div>'
      ;
      if (state.activeItem && state.activeItem.code === code) {
        row.classList.add('is-selected');
      }
      row.addEventListener('click', function (candidate) {
        return function () {
          var returnCode = normalizeString(candidate && candidate.code);
          beginCandidateSelection(candidate);
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
          beginCandidateSelection(targetCandidate);
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
    var contract = getCandidateReferenceContract(rec);
    var action = normalizeString(contract.action || resolvePageAction(rec, state.currentView) || '观察');
    var currentPrice = safeNumber(contract.current_price, getCandidateCurrentPrice(rec));
    var referencePrice = safeNumber(contract.reference_price, getCandidateReferencePrice(rec));
    var referenceCopy = referencePrice === null ? '' : referencePurposeCopy(rec, contract);
    var changePct = safeNumber(contract.change_pct, getCandidateChangePct(rec));
    var facts = [];
    if (currentPrice !== null) facts.push('<span><small>现价</small><strong>' + escapeHtml(formatNumber(currentPrice, 2)) + '</strong></span>');
    if (changePct !== null) facts.push('<span><small>当日</small><strong>' + escapeHtml(formatPct(changePct, true)) + '</strong></span>');
    if (referencePrice !== null) facts.push('<span><small>参考价' + escapeHtml(referenceCopy) + '</small><strong>' + escapeHtml(formatNumber(referencePrice, 2)) + '</strong></span>');
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
      + renderPoolHitSummary(item, 'detail')
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
    var selectedContract = getCandidateReferenceContract(item);
    var contractReference = safeNumber(selectedContract.reference_price, null);
    var refPrice = contractReference === null
      ? getCandidateReferencePrice(item) : contractReference;
    var calculationReference = getCandidateReferencePriceForCalculation(item);
    var refPriceLabel = isIncidentReviewItem(item)
      ? '事故前结构参考价（仅追溯）'
      : '结构参考价';
    if (!isIncidentReviewItem(item) && refPrice !== null && calculationReference === null) {
      refPriceLabel += '（用途未核验，仅原始记录）';
    }

    var dist = calculationReference !== null
      ? safeNumber(item.distance_from_reference_pct, null) : null;
    if (dist === null && calculationReference !== null && currentPrice !== null
        && calculationReference !== 0) {
      dist = ((currentPrice - calculationReference) / calculationReference) * 100;
    }

    var stopLoss = safeNumber(item.stop_loss, null);
    if (stopLoss === null && raw) {
      stopLoss = safeNumber(raw.stop_loss, null);
    }

    var rawReferenceNote = safeNumber(item && item.reference_price, null) !== null
      && contractReference !== null
      ? rawReferenceText(item, contractReference) : '';

    return ''
      + '<div class="detail-section">'
      + '  <h3 class="detail-section-title">02 价格</h3>'
      + '  <div class="detail-price-grid">'
      + '    <div class="price-cell"><div class="price-label">信号日收盘</div><div class="price-value">' + escapeHtml(currentPrice === null ? '未核验' : formatNumber(currentPrice, 2)) + '</div></div>'
      + '    <div class="price-cell"><div class="price-label">' + escapeHtml(refPriceLabel) + '</div><div class="price-value">' + escapeHtml(refPrice === null ? '--' : formatNumber(refPrice, 2)) + '</div></div>'
      + '    <div class="price-cell"><div class="price-label">距参考价</div><div class="price-value">' + escapeHtml(dist === null ? '--' : formatPct(dist, true)) + '</div></div>'
      + '    <div class="price-cell"><div class="price-label">止损</div><div class="price-value">' + escapeHtml(stopLoss === null ? '--' : formatNumber(stopLoss, 2)) + '</div></div>'
      + '  </div>'
      + (rawReferenceNote ? '<p class="detail-price-note">' + escapeHtml(rawReferenceNote) + '</p>' : '')
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
    if (item && item.workbench_item) {
      var selected = asArray(item.workbench_item.strategy_results).find(function (result) {
        return result.strategy_id === item.workbench_item.evidence_view;
      });
      if (selected && selected.evidence) return selected.evidence;
    }
    var rows = getEvidenceRowsForView((item && item.evidence_view) || viewKey || state.currentView, data);
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

  function renderRecommendationEvidenceModule(number, title, section, body, fallbackDate, statusContext, hideMeta, idPrefix) {
    var titleId = 'evidence-module-' + (idPrefix ? normalizeString(idPrefix) + '-' : '') + normalizeString(number).trim();
    return '<section class="detail-section recommendation-evidence-module" data-evidence-module="'
      + escapeHtml(number) + '" aria-labelledby="' + escapeHtml(titleId) + '">'
      + '<h3 id="' + escapeHtml(titleId) + '" class="detail-section-title">' + escapeHtml(number + ' ' + title) + '</h3>'
      + '<div class="detail-section-body">' + body + '</div>'
      + (hideMeta ? '' : renderRecommendationEvidenceMeta(section, fallbackDate, statusContext))
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

  function renderRecommendationEvidenceHeader(evidence, incidentReview, actionSemantics, sourceItem) {
    var summary = evidence && typeof evidence.summary === 'object' ? evidence.summary : {};
    var code = normalizeString(evidence && (evidence.code || summary.code)).trim();
    var name = normalizeString(summary.name).trim() || code || '未命名';
    var sector = normalizeString(summary.sector).trim();
    var semantics = normalizeString(actionSemantics || 'formal').trim();
    var action = incidentReview
      ? '仅追溯 · 评分不生效'
      : (semantics === 'watch_only'
        ? '仅观察'
        : (semantics === 'upstream_only'
          ? '仅作为上游候选'
          : (normalizeString(summary.formal_action).trim() || '本期未声明正式动作')));
    var actionPrefix = semantics === 'formal'
      ? '正式动作：'
      : (semantics === 'upstream_only' ? '页面身份：' : '页面动作：');
    return '<div class="detail-header recommendation-evidence-header">'
      + '<div><h2 class="detail-title">' + escapeHtml(name) + '</h2>'
      + '<p class="detail-subtitle">' + escapeHtml([code, sector].filter(Boolean).join(' · ')) + '</p></div>'
      + '<div class="decision-header-action"><span class="formal-action '
      + escapeHtml(incidentReview ? 'is-neutral' : getActionPillClass(action)) + '">'
      + escapeHtml(incidentReview ? action : actionPrefix + action) + '</span></div>'
      + renderPoolHitSummary(sourceItem || evidence, 'detail')
      + '</div>';
  }

  function renderRecommendationConclusion(evidence, incidentReview) {
    var displayMode = normalizeString(arguments[2]).trim();
    var actionSemantics = normalizeString(arguments[3]).trim();
    var sourceItem = arguments[4];
    var formalScoreDisplay = actionSemantics === 'formal' && !incidentReview;
    var summary = evidence.summary && typeof evidence.summary === 'object' ? evidence.summary : {};
    var decision = evidence.decision_score && typeof evidence.decision_score === 'object' ? evidence.decision_score : {};
    var components = decision.components && typeof decision.components === 'object' ? decision.components : {};
    var rank = evidence.rank_evidence && typeof evidence.rank_evidence === 'object' ? evidence.rank_evidence : {};
    var componentLabels = { structure: '结构', position: '位置', sentiment: '情绪' };
    var componentHtml = formalScoreDisplay ? ['structure', 'position', 'sentiment'].map(function (key) {
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
    }).join('') : '';
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
    var primaryReasonPills = formalScoreDisplay ? ['structure', 'position', 'sentiment'].reduce(function (result, key) {
      var component = components[key] && typeof components[key] === 'object' ? components[key] : {};
      recommendationEvidenceList(component.reasons).forEach(function (reason) {
        if (result.indexOf(reason) === -1 && result.length < 3) result.push(reason);
      });
      return result;
    }, []) : [];
    var primaryReasonHtml = primaryReasonPills.length
      ? '<div class="reason-pills recommendation-primary-reasons">'
        + primaryReasonPills.map(function (reason) {
          return '<span class="reason-pill">' + escapeHtml(reason.trim()) + '</span>';
        }).join('') + '</div>'
      : '';
    var inactiveScoreText = incidentReview
      ? '事故复盘评分不生效' : '本页不启用正式决策分';
    var scoreAuditHtml = '<div class="decision-score-audit">'
      + '<div class="recommendation-score-split">'
      + '<section><span>' + escapeHtml(formalScoreDisplay ? '决策分' : '评分状态') + '</span><strong>'
      + escapeHtml(formalScoreDisplay && isRecommendationEvidenceFiniteNumber(decisionScore)
        ? recommendationEvidenceNumber(decisionScore)
        : (formalScoreDisplay ? '本期未提供' : inactiveScoreText))
      + '</strong><small>' + escapeHtml(formalScoreDisplay
        ? (normalizeString(decision.decision_code).trim() || '未提供决策代码')
        : '仅保留来源事实、排序证据与原始审计记录') + '</small>'
      + (formalScoreDisplay
        ? '<div class="recommendation-component-grid">' + componentHtml + '</div>' : '') + '</section>'
      + '<section><span>排序证据</span><strong>'
      + escapeHtml(isRecommendationEvidenceFiniteNumber(viewRank) ? '池内 #' + recommendationEvidenceNumber(viewRank) : '池内名次 --')
      + '</strong><small>'
      + escapeHtml(isRecommendationEvidenceFiniteNumber(rankScore) ? '排序分 ' + recommendationEvidenceNumber(rankScore) : '排序分未提供')
      + '</small><p>' + escapeHtml(normalizeString(rank.note).trim() || '仅用于当前池内排序') + '</p></section>'
      + '</div>' + primaryFacts + '</div>';
    var metaHtml = '<details class="evidence-meta-details">'
      + '<summary class="evidence-meta-summary">'
      + escapeHtml(formalScoreDisplay
        ? '决策分构成与数据审计'
        : (incidentReview ? '历史记录与数据审计' : '研究排序与数据审计'))
      + '</summary>'
      + scoreAuditHtml + metaFacts
      + '</details>';
    var headerHtml = renderRecommendationEvidenceHeader(
      evidence, incidentReview, actionSemantics, sourceItem
    );
    var riskHtml = riskFacts
      ? '<aside class="recommendation-evidence-risk-facts" aria-label="数据风险提示">' + riskFacts + '</aside>'
      : '';
    if (displayMode === 'primary') return headerHtml + riskHtml;
    var body = (displayMode === 'audit' ? '' : headerHtml)
      + (normalizeString(summary.formal_action_reason).trim()
        ? '<p class="recommendation-conclusion-reason">' + escapeHtml(summary.formal_action_reason) + '</p>' : '')
      + primaryReasonHtml
      + '<div class="decision-score-inline"><span>'
      + escapeHtml(formalScoreDisplay ? '决策分' : '评分状态') + '</span><strong>'
      + escapeHtml(formalScoreDisplay && isRecommendationEvidenceFiniteNumber(decisionScore)
        ? recommendationEvidenceNumber(decisionScore)
        : (formalScoreDisplay ? '本期未提供' : inactiveScoreText))
      + '</strong></div>'
      + (displayMode === 'audit' ? '' : riskHtml)
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
    if (normalizeString(block.status).trim() === 'conflict' && items.length) {
      items = ['条件来源冲突，待核验：' + items.join('、')];
    }
    var empty = normalizeString(block.empty_text).trim();
    if (!items.length && normalizeString(block.status).trim() === 'not_applicable') {
      empty = empty || '本期不适用，未进行观测';
    }
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
    var immature = isRecommendationEvidenceFiniteNumber(gate.immature_samples)
      ? Number(gate.immature_samples)
      : (isRecommendationEvidenceFiniteNumber(gate.unmatured_samples)
        ? Number(gate.unmatured_samples) : null);
    var missing = isRecommendationEvidenceFiniteNumber(gate.missing_samples)
      ? Number(gate.missing_samples) : null;
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
    if (waiting !== null && waiting > 0) progressParts.push('等待成熟 ' + escapeHtml(recommendationEvidenceNumber(waiting)) + '（未成熟）');
    if (immature !== null && immature > 0) progressParts.push('未成熟 ' + escapeHtml(recommendationEvidenceNumber(immature)));
    if (missing !== null && missing > 0) progressParts.push('缺失样本 ' + escapeHtml(recommendationEvidenceNumber(missing)));
    if (unavailable !== null && unavailable > 0) progressParts.push('缺失目标日行情 ' + escapeHtml(recommendationEvidenceNumber(unavailable)));

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
      return '<aside class="recommendation-simulation-tracking is-missing" data-evidence-node="simulation-tracking"><strong>'
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
    return '<aside class="recommendation-simulation-tracking" data-evidence-node="simulation-tracking"><strong>'
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
    if (normalizeString(identity.role).trim()) identityParts.push('样本身份 ' + normalizeString(identity.role).trim());
    if (normalizeString(identity.sample_scope).trim()) identityParts.push('样本范围 ' + normalizeString(identity.sample_scope).trim());
    if (identity.incident_review_only === true) identityParts.push('事故样本·仅复盘');
    return '<div class="recommendation-historical-validation">'
      + '<p class="recommendation-history-summary">' + escapeHtml(summary) + '</p>'
      + (identityParts.length ? '<p class="recommendation-history-identity">' + escapeHtml(identityParts.join(' · ')) + '</p>' : '')
      + '<p class="recommendation-history-boundary">只读取已有 historical_validation、榜单表现与模拟验证记录；榜单涨跌不等于成交收益，个股最差不利波动不等于组合回撤。</p>'
      + '<div class="recommendation-history-horizons">'
      + ['t1', 't3', 't5'].map(function (key) {
        return renderHistoricalHorizon(key, progress[key], metrics[key]);
      }).join('')
      + '</div>'
      + renderSimulationTracking(value.simulation_tracking)
      + '</div>';
  }

  function renderHistoricalValidationLink(item, evidence) {
    var value = evidence && typeof evidence === 'object' ? evidence : {};
    var validation = value.historical_validation && typeof value.historical_validation === 'object'
      ? value.historical_validation : {};
    var status = normalizeString(validation.status).trim() || 'missing';
    var simulation = validation.simulation_tracking && typeof validation.simulation_tracking === 'object'
      ? validation.simulation_tracking : (value.simulation_tracking && typeof value.simulation_tracking === 'object'
        ? value.simulation_tracking : {});
    var simulationStatus = normalizeString(simulation.status).trim();
    var comparisonHref = isArchiveReportPath(window.location && window.location.pathname)
      ? '../compare/' : 'compare/';
    var simulationEntry = simulationStatus && simulationStatus !== 'missing'
      ? '<button type="button" class="historical-evidence-link" data-evidence-target="simulation-tracking">查看模拟验证</button>'
      : '<span class="historical-evidence-gap">模拟验证：暂无同合同历史跟踪记录</span>';
    return '<aside class="historical-evidence-links" aria-label="历史证据入口">'
      + '<strong>历史证据</strong>'
      + '<button type="button" class="historical-evidence-link" data-evidence-target="historical-validation">查看历史验证</button>'
      + '<a class="historical-evidence-link" href="' + comparisonHref + '">查看榜单表现</a>'
      + simulationEntry
      + '</aside>';
  }

  function bindHistoricalEvidenceLinks(target) {
    if (!target || typeof target.querySelectorAll !== 'function') return;
    var links = target.querySelectorAll('[data-evidence-target]');
    for (var index = 0; index < links.length; index += 1) {
      var targetKey = normalizeString(links[index].getAttribute('data-evidence-target')).trim();
      if (['historical-validation', 'simulation-tracking'].indexOf(targetKey) === -1) continue;
      if (links[index].getAttribute('data-evidence-bound') === 'true') continue;
      if (typeof links[index].setAttribute === 'function') links[index].setAttribute('data-evidence-bound', 'true');
      links[index].addEventListener('click', function (event) {
        var button = event.currentTarget;
        var evidenceTarget = normalizeString(button.getAttribute('data-evidence-target')).trim();
        var evidence = evidenceTarget === 'simulation-tracking'
          ? target.querySelector('[data-evidence-node="simulation-tracking"]')
          : target.querySelector('[data-evidence-module="08"]');
        if (!evidence) return;
        var ancestor = evidence.parentNode;
        while (ancestor) {
          if (ancestor.tagName && ancestor.tagName.toLowerCase() === 'details') ancestor.open = true;
          ancestor = ancestor.parentNode;
        }
        if (typeof evidence.scrollIntoView === 'function') evidence.scrollIntoView({ block: 'nearest' });
        if (typeof evidence.focus === 'function') evidence.focus();
      });
    }
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

  function renderDecisionWorkbenchBrief(evidence, incidentReview, actionSemantics, item, part) {
    var value = evidence && typeof evidence === 'object' ? evidence : {};
    var summary = value.summary && typeof value.summary === 'object' ? value.summary : {};
    var prices = value.price_evidence && typeof value.price_evidence === 'object'
      ? value.price_evidence : {};
    var daily = value.daily_structure && typeof value.daily_structure === 'object'
      ? value.daily_structure : {};
    var sublevel = value.sublevel_30m && typeof value.sublevel_30m === 'object'
      ? value.sublevel_30m : {};
    var market = value.market_and_sector && typeof value.market_and_sector === 'object'
      ? value.market_and_sector : {};
    var risk = value.risk_and_next && typeof value.risk_and_next === 'object'
      ? value.risk_and_next : {};
    var semantics = normalizeString(actionSemantics || 'formal').trim();
    var detailItem = item && typeof item === 'object' ? item : {};
    var action = incidentReview
      ? '仅追溯'
      : (semantics === 'watch_only'
        ? '仅观察'
        : (semantics === 'upstream_only'
          ? '仅作为上游候选'
          : (evidenceScalarText(summary.formal_action) || '本期未声明正式动作')));
    var isRecommendation = semantics === 'formal'
      && /推荐|可上车|买入/.test(action) && !/不推荐|拒绝/.test(action);
    var isRejection = semantics === 'formal' && (/不推荐|拒绝|排除/.test(action)
      || normalizeString(action).toLowerCase() === 'reject');
    var why = [];
    function addWhy(label, text, target) {
      var normalized = evidenceScalarText(text);
      if (!normalized || why.some(function (item) { return item.text === normalized; })) return;
      why.push({ label: label, text: normalized, target: target });
    }
    if (semantics === 'formal') {
      addWhy('正式理由', summary.formal_action_reason, 'formal-action');
    } else {
      addWhy('研究说明', detailItem.page_action_reason, 'page-action');
    }
    addWhy('日线', daily.summary, 'daily-chart');
    addWhy('30分钟', sublevel.reason || sublevel.summary, 'sublevel-summary');
    var marketLayerText = [
      evidenceScalarText(market.summary),
      evidenceScalarText(market.market_state) ? '市场层 ' + evidenceScalarText(market.market_state) : '',
      evidenceScalarText(market.sector_layer_state) ? '板块层 ' + evidenceScalarText(market.sector_layer_state) : '',
      evidenceScalarText(market.stock_state) ? '个股层 ' + evidenceScalarText(market.stock_state) : '',
    ].filter(Boolean).join(' · ');
    addWhy('大盘/板块', marketLayerText, 'market-decision-bar');
    why = why.slice(0, 3);
    if (incidentReview) {
      why = [{
        label: '事故复盘',
        text: '原始判定和评分不生效，仅用于追溯数据故障影响。',
        target: 'formal-action',
      }];
    }
    if (!why.length && isRejection) {
      why.push({ label: '正式理由', text: '拒绝原因待核验', target: 'formal-action' });
    }

    var missingPrices = [];
    if (evidencePositiveNumber(prices.reference_price) === null) missingPrices.push('参考价');
    if (evidencePositiveNumber(prices.invalidation_price) === null) missingPrices.push('失效位');
    var dataRisks = [];
    var summaryStatus = evidenceScalarText(summary.status).toLowerCase();
    if (!summaryStatus) dataRisks.push('证据状态未提供');
    else if (summaryStatus !== 'available') dataRisks.push('证据状态异常：' + summaryStatus);
    if (summary.data_stale === true) dataRisks.push('数据陈旧');
    else if (summary.data_stale !== false) dataRisks.push('陈旧状态未提供');
    if (summary.data_is_final === false) dataRisks.push('非终局');
    else if (summary.data_is_final !== true) dataRisks.push('终局状态未提供');
    var health = evidenceScalarText(summary.data_health);
    if (!health) {
      dataRisks.push('数据健康未提供');
    } else if (['verified', 'fresh', 'available'].indexOf(health.toLowerCase()) === -1) {
      dataRisks.push('数据健康异常：' + health);
    }
    var executionText = '';
    if (incidentReview) {
      executionText = '事故复盘不形成当前执行边界';
    } else if (semantics === 'watch_only') {
      executionText = '研究观察，不形成正式执行边界';
    } else if (semantics === 'upstream_only') {
      executionText = '上游候选身份，不形成正式执行边界';
    } else if (dataRisks.length) {
      executionText = '当前不可作为正式可执行结果：' + dataRisks.join('、');
    } else if (isRecommendation && missingPrices.length) {
      executionText = '关键价格待确认：缺少' + missingPrices.join('、');
    } else if (isRecommendation) {
      executionText = '关键价格完整，可按正式动作核验执行';
    } else if (isRejection) {
      executionText = '正式动作为不推荐，不形成上车边界';
    } else {
      executionText = '等待正式确认，不按推荐动作执行';
    }

    var nextItems = recommendationEvidenceList(
      risk.next_confirmation && risk.next_confirmation.items
    ).slice(0, 3);
    var invalidationItems = recommendationEvidenceList(
      risk.invalidation_conditions && risk.invalidation_conditions.items
    ).slice(0, 3);
    function renderItems(items, emptyText, target) {
      return items.length
        ? '<ul>' + items.map(function (item) {
          return '<li><button type="button" class="decision-brief-jump" data-evidence-target="'
            + escapeHtml(target || 'risk-next') + '">' + escapeHtml(item) + '</button></li>';
        }).join('') + '</ul>'
        : '<p>' + escapeHtml(emptyText) + '</p>';
    }
    function renderWhyItems(items) {
      return items.length
      ? '<ul>' + items.map(function (item) {
        return '<li><button type="button" class="decision-brief-jump" data-evidence-target="' + escapeHtml(item.target) + '"><b>'
          + escapeHtml(item.label) + '</b><span>' + escapeHtml(item.text) + '</span></button></li>';
      }).join('') + '</ul>'
      : '<p>本期未提供可核验的推荐理由</p>';
    }
    var whyCoreHtml = renderWhyItems(why.slice(0, 1));
    var whySupplementHtml = why.length > 1 ? renderWhyItems(why.slice(1)) : '';
    var signalDate = evidenceScalarText(summary.signal_date)
      || evidenceScalarText(daily.signal_date) || '未提供';
    var confirmDate = evidenceScalarText(sublevel.confirm_date)
      || evidenceScalarText(sublevel.confirmation_date) || '未提供';
    var dataCutoff = evidenceScalarText(summary.data_latest_date)
      || evidenceScalarText(sublevel.latest_date)
      || normalizeString((state.data || {}).data_quality && ((state.data || {}).data_quality.as_of || (state.data || {}).data_quality.generated_at)).trim()
      || '未提供';
    var actionPrefix = semantics === 'formal'
      ? '正式动作：'
      : (semantics === 'upstream_only' ? '页面身份：' : '页面动作：');
    var alertText = incidentReview
      ? '事故复盘：原始判定和评分不生效，仅供追溯。'
      : (dataRisks.length ? '数据异常常驻：' + dataRisks.join('、') : '');
    var coreHtml = '<section class="decision-brief decision-workbench-brief decision-brief-core" aria-label="图前核心判断">'
      + '<section><span class="decision-workbench-brief-label">为什么</span>' + whyCoreHtml
      + (alertText ? '<aside class="decision-brief-alert" aria-label="重要异常">' + escapeHtml(alertText) + '</aside>' : '')
      + '</section></section>';
    var afterHtml = '<section class="decision-brief decision-workbench-brief decision-brief-after-chart" aria-label="图后短判断">'
      + (whySupplementHtml ? '<section><span class="decision-workbench-brief-label">补充判断</span>' + whySupplementHtml + '</section>' : '')
      + '<section><span class="decision-workbench-brief-label">主要阻碍 / 可执行性</span>'
      + '<strong>' + escapeHtml(actionPrefix + action) + '</strong><p>'
      + escapeHtml(executionText) + '</p></section>'
      + '<section><span class="decision-workbench-brief-label">下一确认</span>'
      + renderItems(nextItems, '下一确认待补充', 'risk-next') + '</section>'
      + '<section><span class="decision-workbench-brief-label">失效</span>'
      + renderItems(invalidationItems, '失效条件待补充', 'risk-invalidation') + '</section>'
      + '<div class="decision-brief-provenance"><span>信号日 <strong>' + escapeHtml(signalDate)
      + '</strong></span><span>确认日 <strong>' + escapeHtml(confirmDate)
      + '</strong></span><span>数据截止 <strong>' + escapeHtml(dataCutoff)
      + '</strong></span></div>'
      + '</section>';
    if (part === 'core') return coreHtml;
    if (part === 'after') return afterHtml;
    return coreHtml + afterHtml;
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
      + '      <div class="chart-layer-switcher" data-chart-layer-switcher role="group" aria-label="K线图层"></div></div>'
      + '    <div class="chart-annotation-lane hidden" id="chartAnnotationLane" aria-live="polite"></div>'
      + '    <div id="chartCanvas" class="chart-canvas"></div>'
      + '  </div>'
      + '</div>';
  }

  function getSublevelEvidenceTitle(section) {
    var value = section && typeof section === 'object' ? section : {};
    var interval = normalizeString(value.interval || value.frequency || value.bar_interval || value.timeframe).trim().toLowerCase();
    if (/15(?:m|min|分钟)/.test(interval)) return '15分钟证据（频率错配，单独核对）';
    if (/30(?:m|min|分钟)/.test(interval)) return '30分钟确认';
    return '短周期确认证据（频率未提供）';
  }

  function strategyEvidencePrefix(strategy, index) {
    return 'strategy-' + normalizeString(strategy && strategy.strategy_id)
      .replace(/[^a-zA-Z0-9_-]/g, '') + '-' + (index || 0);
  }

  function renderStrategyEvidence(strategy, index) {
    var evidence = strategy.evidence || {};
    var reportDate = getBootstrap().pageDate;
    var prefix = strategyEvidencePrefix(strategy, index);
    var body = renderRecommendationEvidenceModule('01', '决策与数据审计', evidence.summary || {},
      renderRecommendationConclusion(evidence, !!(strategy.candidate || {}).incident_review_only, 'audit', strategy.action_semantics), reportDate, undefined, false, prefix);
    var modules = [
      ['02', '价格与关键位置', 'price_evidence', function () { return renderRecommendationPriceEvidence(evidence); }],
      ['03', '日线结构', 'daily_structure', renderDailyStructureEvidence],
      ['04', getSublevelEvidenceTitle(evidence.sublevel_30m), 'sublevel_30m', renderSublevelEvidence],
      ['05', '量价与资金', 'volume_and_capital', renderVolumeCapitalEvidence],
      ['06', '市场与板块共振', 'market_and_sector', renderMarketSectorEvidence],
      ['07', '风险与下一步', 'risk_and_next', renderRiskAndNextEvidence],
      ['08', '历史验证与回测提醒', 'historical_validation', renderHistoricalValidation],
    ];
    modules.forEach(function (module) {
      var section = evidence[module[2]] || {};
      body += renderRecommendationEvidenceModule(module[0], module[1], section, module[3](section), reportDate,
        module[2] === 'historical_validation' ? 'historical_validation' : undefined, false, prefix);
    });
    return '<details class="candidate-research-details"><summary>查看本策略完整证据</summary>'
      + body + renderMainRiseClue(evidence.main_rise_clue || {})
      + renderRecommendationEvidenceAudit(evidence, reportDate) + '</details>';
  }

  function buildUnifiedShortJudgment(item, evidence, part) {
    var rec = item && item.workbench_item ? item.workbench_item : (item || {});
    var source = evidence && typeof evidence === 'object' ? evidence : {};
    var daily = source.daily_structure && typeof source.daily_structure === 'object' ? source.daily_structure : {};
    var sublevel = source.sublevel_30m && typeof source.sublevel_30m === 'object' ? source.sublevel_30m : {};
    var risk = source.risk_and_next && typeof source.risk_and_next === 'object' ? source.risk_and_next : {};
    var blockers = asArray(rec.blocking_reasons || rec.blocked_reasons);
    var currentDecision = getWorkbenchCurrentDecision(item);
    var next = asArray(rec.next_confirmation);
    var invalidation = asArray(rec.invalidation);
    function conditionItems(block, fallback) {
      var value = block && typeof block === 'object' ? block : {};
      var items = recommendationEvidenceList(value.items);
      var status = normalizeString(value.status).trim();
      if (status === 'conflict' && items.length) {
        return ['条件来源冲突，待核验：' + items.join('、')];
      }
      if (!items.length && status === 'not_applicable') {
        return [normalizeString(value.empty_text).trim() || '本期不适用，未进行观测'];
      }
      if (!items.length && normalizeString(value.empty_text).trim() && status !== 'missing') {
        return [normalizeString(value.empty_text).trim()];
      }
      return items.length ? items : (fallback ? [fallback] : []);
    }
    function chooseConditionBlock(primary, fallback) {
      var first = primary && typeof primary === 'object' ? primary : {};
      if (normalizeString(first.status).trim() || recommendationEvidenceList(first.items).length) return first;
      return fallback && typeof fallback === 'object' ? fallback : {};
    }
    if (!next.length) next = conditionItems(risk.next_confirmation, '');
    if (!invalidation.length) {
      invalidation = conditionItems(chooseConditionBlock(
        risk.invalidation_conditions, risk.cancel_conditions
      ), '');
    }
    function actionList(items, empty, target) {
      return items.length ? '<ul>' + items.slice(0, 3).map(function (row) {
        return '<li><button type="button" class="decision-brief-jump" data-evidence-target="' + escapeHtml(target) + '">' + escapeHtml(row) + '</button></li>';
      }).join('') + '</ul>' : '<p>' + escapeHtml(empty) + '</p>';
    }
    var signalDate = normalizeString(rec.signal_date || daily.signal_date || (source.summary || {}).signal_date || '未提供');
    var confirmDate = normalizeString(rec.confirm_date || sublevel.confirm_date || '未提供');
    var dataCutoff = normalizeString(rec.data_latest_date || (source.summary || {}).data_latest_date || sublevel.latest_date || '未提供');
    var currentReason = currentDecision.currentDominates
      ? currentDecision.prompt
      : normalizeString(rec.primary_reason || (daily.summary || source.primary_reason) || '本期未提供核心关注理由');
    var coreHtml = '<section class="decision-workbench-brief unified-short-judgment decision-brief-core" aria-label="图前核心判断">'
      + '<section><span class="decision-workbench-brief-label">'
      + escapeHtml(currentDecision.currentDominates ? '当前提示' : '为什么关注')
      + '</span><button type="button" class="decision-brief-jump" data-evidence-target="daily-chart">'
      + escapeHtml(currentReason) + '</button>'
      + (blockers.length ? '<aside class="decision-brief-alert" aria-label="重要异常">主要阻碍：'
        + escapeHtml(blockers.slice(0, 2).join('；')) + '</aside>' : '')
      + '</section></section>';
    var afterHtml = '<section class="decision-workbench-brief unified-short-judgment decision-brief-after-chart" aria-label="图后短判断">'
      + '<section><span class="decision-workbench-brief-label">主要阻碍</span>'
      + actionList(blockers, '本期未声明主要阻碍', 'risk-invalidation') + '</section>'
      + '<section><span class="decision-workbench-brief-label">下一确认</span>'
      + actionList(next, '具体确认条件待补充', 'risk-next') + '</section>'
      + '<section><span class="decision-workbench-brief-label">失效 / 取消</span>'
      + actionList(invalidation, '具体失效条件待补充', 'risk-invalidation') + '</section>'
      + '<div class="decision-brief-provenance"><span>信号日 <strong>' + escapeHtml(signalDate)
      + '</strong></span><span>确认日 <strong>' + escapeHtml(confirmDate)
      + '</strong></span><span>数据截止 <strong>' + escapeHtml(dataCutoff)
      + '</strong></span></div></section>';
    if (part === 'core') return coreHtml;
    if (part === 'after') return afterHtml;
    return coreHtml + afterHtml;
  }

  function buildUnifiedCandidateDetail(item) {
    var value = item.workbench_item;
    var currentDecision = getWorkbenchCurrentDecision(item);
    function list(values, fallback) {
      return asArray(values).length ? '<ul>' + values.slice(0, 3).map(function (v) {
        return '<li>' + escapeHtml(v) + '</li>';
      }).join('') + '</ul>' : '<p>' + escapeHtml(fallback) + '</p>';
    }
    var blockers = asArray(value.blocking_reasons || value.blocked_reasons);
    var execution = value.is_executable
      ? '本期条件已完整；盘后仅供后续核验，交易前需重新确认有效性。'
      : (blockers.length ? blockers.join('、') : '仅作观察，等待明确条件。');
    var watchAnchor = value.watch_anchor && typeof value.watch_anchor === 'object'
      ? value.watch_anchor : null;
    if (watchAnchor && watchAnchor.status === 'verified') {
      var anchorBasis = watchAnchor.price_basis && typeof watchAnchor.price_basis === 'object'
        ? watchAnchor.price_basis : {};
      execution += ' 观察锚点：' + watchAnchor.value + '（'
        + (watchAnchor.purpose || '用途未提供') + '；来源 '
        + (watchAnchor.source || '未提供') + '；日期 '
        + (watchAnchor.reference_date || '未提供') + '；价基 '
        + (anchorBasis.adjustment || '未提供') + '）';
    } else if (watchAnchor && watchAnchor.reason) {
      execution += ' ' + watchAnchor.reason;
    }
    var strategies = asArray(value.strategy_results).map(function (strategy, index) {
      var contract = strategy.contract || {};
      var referenceStatus = referencePurposeStatus(strategy, contract);
      var hasReference = isRecommendationEvidenceFiniteNumber(contract.reference_price);
      var reference = hasReference ? recommendationEvidenceNumber(contract.reference_price, 2) : '待补充';
      var referencePurpose = hasReference
        ? (referenceStatus === 'verified' || referenceStatus === 'formal'
          ? '（用途已核验）' : '（用途未核验，仅原始记录）') : '';
      var referenceLine = strategy.role === 'formal'
        ? '参考价 ' + reference + referencePurpose
          + ' · 失效位 ' + (contract.invalidation_price || '待补充')
          + ' · 周期 ' + (contract.intended_horizon || '未声明')
        : (hasReference ? '原始记录参考价 ' + reference + referencePurpose : '');
      var sourceScore = isFormalStrategyResult(strategy)
        && !currentDecision.incident
        && !isIncidentReviewItem(strategy && strategy.candidate)
        && normalizeString(strategy && strategy.strategy_id).trim()
        ? formalDecisionScoreValue(strategy.score) : null;
      var sourceAction = strategy.formal_action || '研究观察';
      var sourceActionPrefix = currentDecision.currentDominates
        ? (isFormalStrategyResult(strategy) ? '原策略结论：' : '研究结论：') : '';
      var sourceReasonPrefix = currentDecision.currentDominates && strategy.primary_reason
        ? (isFormalStrategyResult(strategy) ? '原策略依据：' : '研究依据：') : '';
      return '<section><header class="candidate-source-title"><strong>'
        + escapeHtml(getCurrentLabel(strategy.strategy_id) || strategy.strategy_id)
        + ' · ' + escapeHtml(sourceActionPrefix + sourceAction) + '</strong>'
        + (sourceScore === null ? '' : '<span class="candidate-source-score" data-source-score="'
          + escapeHtml(normalizeString(strategy.strategy_id).trim()) + '">决策分 '
          + escapeHtml(formatNumber(sourceScore, 0)) + '</span>') + '</header>'
        + '<p>' + escapeHtml(sourceReasonPrefix + (strategy.primary_reason || '')) + '</p>'
        + (referenceLine ? '<p>' + escapeHtml(referenceLine) + '</p>' : '')
        + renderStrategyEvidence(strategy, index) + '</section>';
    }).join('');
    var evidence = getCandidateRecommendationEvidence(item, state.data) || {};
    return '<div class="merged-candidate-detail unified-candidate-detail"><header class="unified-stock-head">'
      + '<h2>' + escapeHtml(value.name) + ' <small>' + escapeHtml(value.code) + '</small></h2>'
      + '<strong>' + escapeHtml(currentDecision.statusLabel) + '</strong>'
      + renderCandidateFormalScores(item, state.currentView)
      + (currentDecision.currentDominates
        ? '<span>' + escapeHtml(currentDecision.prompt.replace('；', ' · ')) + '</span>'
        : (value.formal_action ? '<span>正式动作：' + escapeHtml(value.formal_action) + '</span>' : ''))
      + renderPoolHitSummary(item, 'detail')
      + (blockers.length ? '<p class="unified-blocker">' + escapeHtml(blockers.slice(0, 3).join('、')) + '</p>' : '')
      + '</header>' + renderCandidateStatusSummary(item, state.currentView)
      + renderCandidateBasicInfo(item, true) + buildUnifiedShortJudgment(item, evidence, 'core')
      + buildChartPlaceholder(item) + buildUnifiedShortJudgment(item, evidence, 'after')
      + renderCandidateFactPanel(item)
      + renderHistoricalValidationLink(value, evidence)
      + '<details class="candidate-research-details"><summary>来源策略与完整证据</summary>'
      + strategies + renderRecommendationEvidenceAudit(evidence, getBootstrap().pageDate) + '</details></div>';
  }

  function renderNoEvidenceReference(item, raw) {
    var reference = getCandidateReferencePrice(item);
    if (reference === null && raw) reference = getCandidateReferencePrice(raw);
    if (reference === null) return '';
    var label = isIncidentReviewItem(item)
      ? '事故前结构参考价（仅追溯）'
      : '原始记录参考价（用途未核验）';
    return '<p class="detail-raw-reference" data-reference-purpose="unverified">'
      + '<strong>' + escapeHtml(label) + '</strong>：'
      + escapeHtml(formatNumber(reference, 2))
      + '；不进入正式参考线、止损或收益计算。</p>';
  }

  function noEvidenceHistoricalConditionTexts(value) {
    var seen = Object.create(null);
    return asArray(value).map(function (condition) {
      return typeof condition === 'string' ? condition.trim() : '';
    }).filter(function (condition) {
      if (!condition || seen[condition]) return false;
      seen[condition] = true;
      return true;
    });
  }

  function resolveNoEvidenceRawConditionRecord(item, raw) {
    var ref = item && item.ref && typeof item.ref === 'object' ? item.ref : {};
    var pool = normalizeString(ref.pool || ref.source_pool).trim();
    var code = toCodeKey(ref.code);
    var itemCode = toCodeKey(item && item.code);
    if (!pool || !code || !itemCode || code !== itemCode || !raw) {
      return { record: null, ambiguous: false };
    }
    var matches = asArray(getWorkspaceDataFromRef(pool)).filter(function (candidate) {
      return toCodeKey(candidate && candidate.code) === code;
    });
    if (matches.length > 1) return { record: null, ambiguous: true };
    return {
      record: matches.length === 1 && matches[0] === raw ? raw : null,
      ambiguous: false,
    };
  }

  function renderNoEvidenceHistoricalConditions(item, raw) {
    var value = item && typeof item === 'object' ? item : {};
    var rawResolution = resolveNoEvidenceRawConditionRecord(value, raw);
    var rawRecord = rawResolution.record || {};
    var definitions = [
      ['next_day_conditions', 'next_day', '次日条件'],
      ['upgrade_conditions', 'upgrade', '升级条件'],
      ['cancel_conditions', 'cancel', '取消条件'],
    ];
    var groups = definitions.map(function (definition) {
      var itemConditions = noEvidenceHistoricalConditionTexts(value[definition[0]]);
      var rawConditions = itemConditions.length
        ? [] : noEvidenceHistoricalConditionTexts(rawRecord[definition[0]]);
      var conditions = itemConditions.length ? itemConditions : rawConditions;
      if (!conditions.length) return '';
      return '<section class="detail-raw-condition-group" data-condition-kind="'
        + escapeHtml(definition[1]) + '" data-condition-source="'
        + (itemConditions.length ? 'item' : 'raw') + '">'
        + '<h4>' + escapeHtml(definition[2]) + '</h4><ul>'
        + conditions.map(function (condition) {
          return '<li>' + escapeHtml(condition) + '</li>';
        }).join('') + '</ul></section>';
    }).filter(Boolean);
    if (!groups.length && !rawResolution.ambiguous) return '';
    var ambiguity = rawResolution.ambiguous
      ? '<p class="detail-raw-condition-note">同一来源有多条同代码记录，未自动补充其他记录的条件。</p>'
      : '';
    return '<section class="detail-raw-conditions" data-condition-status="historical-unconfirmed">'
      + '<h3>历史原始条件（未重新确认）</h3>'
      + '<p>以下仅转录本条历史原始记录，不对当前满足状态、有效性或可执行性作推断。</p>'
      + ambiguity + groups.join('') + '</section>';
  }

  function renderLegacyRawConditionTrace(viewKey) {
    var key = normalizeString(viewKey).trim();
    var report = state.data || {};
    var selection = report.selection_input_health;
    if ((selection !== null && typeof selection !== 'undefined')
        || !getStrategyViewBlockingReason(report, key)) return '';
    var workspace = state.workspace || {};
    var rows = asArray((workspace.views || {})[key]);
    var records = rows.map(function (item, index) {
      var ref = item && item.ref && typeof item.ref === 'object' ? item.ref : {};
      var refPool = normalizeString(ref.pool || ref.source_pool).trim();
      var refCode = toCodeKey(ref.code);
      var raw = asArray(getWorkspaceDataFromRef(refPool)).find(function (candidate) {
        return toCodeKey(candidate && candidate.code) === refCode;
      }) || null;
      var conditions = renderNoEvidenceHistoricalConditions(item, raw);
      if (conditions.indexOf('detail-raw-condition-group') === -1) return '';
      var sourcePool = normalizeString(ref.pool || ref.source_pool).trim();
      var knownSourcePool = Object.prototype.hasOwnProperty.call(getRawPools(), sourcePool);
      var sourceLabel = knownSourcePool ? getViewSourcePoolLabel(sourcePool) : '';
      var publicSource = knownSourcePool && sourceLabel && sourceLabel !== sourcePool
        ? '来源 ' + sourceLabel : '来源未登记';
      var name = normalizeString(item && (item.name || item.code)).trim() || '未命名';
      var code = toCodeKey(item && item.code);
      return '<article class="legacy-raw-condition-record" data-raw-condition-index="'
        + escapeHtml(index + 1) + '" data-raw-condition-code="' + escapeHtml(code) + '">'
        + '<header><h4>' + escapeHtml(name) + (code ? ' <small>' + escapeHtml(code) + '</small>' : '')
        + '</h4><span>' + escapeHtml(publicSource)
        + ' · 原顺序 #' + escapeHtml(index + 1) + '</span></header>'
        + conditions + '</article>';
    }).filter(Boolean);
    if (!records.length) return '';
    return '<details class="legacy-raw-condition-trace">'
      + '<summary>原始条件追溯（' + escapeHtml(records.length) + '条）</summary>'
      + '<p class="legacy-raw-condition-boundary">这些是历史原始记录，未重新确认；'
      + '不生成当前动作，不进入当前候选或比较，也不判断条件现在是否成立。</p>'
      + '<div class="legacy-raw-condition-records">' + records.join('') + '</div></details>';
  }

  function buildMergedCandidateDetail(item, raw) {
    if (item && item.workbench_item) return buildUnifiedCandidateDetail(item);
    var evidence = getCandidateRecommendationEvidence(item, state.data);
    if (!evidence) {
      return '<div class="detail-empty-wrap merged-candidate-detail">'
        + '<div class="detail-header recommendation-evidence-header pool-hit-fallback-header">'
        + '<div><h2 class="detail-title">'
        + escapeHtml(normalizeString(item && (item.name || item.code)) || '未命名')
        + '</h2><p class="detail-subtitle">'
        + escapeHtml(normalizeString(item && item.code)) + '</p></div>'
        + renderPoolHitSummary(item, 'detail') + '</div>'
        + '<div class="detail-empty"><strong>本期未提供证据展示</strong></div>'
        + renderNoEvidenceReference(item, raw)
        + renderNoEvidenceHistoricalConditions(item, raw)
        + buildChartPlaceholder(item)
        + '</div>';
    }
    var projection = getRecommendationEvidenceProjection(state.data) || {};
    var reportDate = normalizeString(projection.report_date).trim();
    var incidentReview = isIncidentReviewItem(item);
    var actionSemantics = resolveViewDisplayContract(
      state.currentView, {}
    ).action_semantics;
    var decisionAuditTitle = incidentReview
      ? '历史记录与数据审计'
      : (normalizeString(actionSemantics).trim() === 'formal'
        ? '决策分与数据审计' : '研究排序与数据审计');
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
      + renderRecommendationEvidenceModule(
        '01', '推荐结论', summary,
        renderRecommendationConclusion(
          evidence, incidentReview, 'primary', actionSemantics, item
        ), reportDate,
        null, true,
      )
      + renderCandidateBasicInfo(item, true)
      + renderDecisionWorkbenchBrief(
        evidence, incidentReview, actionSemantics, item, 'core'
      )
      + buildChartPlaceholder(item)
      + renderDecisionWorkbenchBrief(
        evidence, incidentReview, actionSemantics, item, 'after'
      )
      + renderHistoricalValidationLink(item, evidence)
      + '<span class="decision-workbench-brief" data-layout-compat="post-chart" aria-hidden="true" hidden>为什么 可执行性 下一确认 失效</span>'
      + '<details class="candidate-research-details">'
      + '<summary><span>完整证据与审计</span><small>价格、结构、30分钟、量价、市场、风险与历史验证</small></summary>'
      + '<div class="candidate-research-details-body">'
      + renderRecommendationEvidenceModule(
        '01A', decisionAuditTitle, summary,
        renderRecommendationConclusion(
          evidence, incidentReview, 'audit', actionSemantics, item
        ), reportDate,
        null, true,
      )
      + renderRecommendationEvidenceModule('02', '价格与关键位置', price, renderRecommendationPriceEvidence(evidence), reportDate)
      + renderRecommendationEvidenceModule('03', '日线结构', daily,
        renderDailyStructureEvidence(daily) + renderMainRiseClue(mainRise), reportDate)
      + renderRecommendationEvidenceModule('04', getSublevelEvidenceTitle(sublevel), sublevel, renderSublevelEvidence(sublevel), reportDate)
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
      + '</div></details>'
      + '</div>';
  }

  function getCandidateDetailTarget() {
    var drawerOpen = state.isMobile && nodes.drawer && nodes.drawer.classList
      && nodes.drawer.classList.contains('is-open');
    return drawerOpen && nodes.drawerContent ? nodes.drawerContent : nodes.detailPanel;
  }

  function clearCandidateDetailLifecycle(target) {
    if (state.chartInstance && typeof state.chartInstance.dispose === 'function') {
      state.chartInstance.dispose();
    }
    state.chartInstance = null;
    state.chartMount = null;
    state.chartAnnotationLane = null;
    state.chartLayerSwitcher = null;
    state.detailCandidateKey = '';
    state.detailTarget = null;
    state.detailRenderToken = Number(state.detailRenderToken || 0) + 1;
    if (target && typeof target.innerHTML !== 'undefined') target.innerHTML = '';
  }

  function isCandidateDetailMounted(item, target) {
    if (!item || !target || !state.detailCandidateKey) return false;
    var key = candidateIdentityKey(item, state.currentView);
    var marker = target.getAttribute ? target.getAttribute('data-candidate-key') : '';
    return state.detailCandidateKey === key
      && state.detailTarget === target
      && marker === key
      && normalizeString(target.innerHTML).trim() !== '';
  }

  function renderCandidateDetail(item, target) {
    target = target || nodes.detailPanel;
    if (!target) return;

    if (!item) {
      clearCandidateDetailLifecycle(target);
      var viewMeta = (getCandidateViews().meta || {})[state.currentView] || {};
      target.innerHTML = state.currentView === 'main'
        ? '<div class="detail-empty"><strong>本期未选出推荐票</strong></div>'
        : buildCandidateEmptyState(state.currentView, viewMeta.availability || {}, { filtered: false });
      return;
    }

    if (!state.activeCandidateKey
        || state.activeCandidateKey !== candidateIdentityKey(item, state.currentView)) {
      beginCandidateSelection(item);
    }
    if (isCandidateDetailMounted(item, target)) return;
    clearCandidateDetailLifecycle(target);
    var renderToken = Number(state.detailRenderToken || 0) + 1;
    state.detailRenderToken = renderToken;
    var detailKey = candidateIdentityKey(item, state.currentView);
    var raw = findRawCandidate(item.ref || {});
    target.innerHTML = buildMergedCandidateDetail(item, raw);
    bindHistoricalEvidenceLinks(target);
    if (target.setAttribute) target.setAttribute('data-candidate-key', detailKey);
    state.detailCandidateKey = detailKey;
    state.detailTarget = target;
    state.chartMount = target.querySelector('#chartCanvas');
    state.chartAnnotationLane = target.querySelector('#chartAnnotationLane');
    state.chartLayerSwitcher = target.querySelector('[data-chart-layer-switcher]');
    // The chart renderer is synchronous today; the token is kept as the
    // lifecycle boundary for any delayed chart/data callback.
    if (renderToken !== state.detailRenderToken
        || !isCurrentCandidateSelection({
          version: state.candidateSelectionVersion,
          key: state.activeCandidateKey,
        }, item)) return;
    renderChart(raw, item);
    bindEvidenceJumps(target);
  }

  function openEvidenceAncestorDetails(element) {
    var current = element;
    while (current && current !== document.body) {
      if (current.tagName && current.tagName.toLowerCase() === 'details') current.open = true;
      current = current.parentNode;
    }
  }

  function locateDetailEvidence(target, root, date) {
    var targetName = normalizeString(target).trim();
    if (root && state.detailTarget && root !== state.detailTarget) return null;
    if (root && state.chartMount && typeof root.contains === 'function'
        && !root.contains(state.chartMount)) return null;
    var globalTarget = targetName === 'market-decision-bar'
      ? document.getElementById('marketDecisionBar') : null;
    if (globalTarget) {
      if (globalTarget.scrollIntoView) globalTarget.scrollIntoView({ behavior: 'smooth', block: 'start' });
      return globalTarget;
    }
    var moduleNumber = {
      'daily-chart': '03',
      'sublevel-summary': '04',
      'price': '02',
      'price-evidence': '02',
      'volume': '05',
      'volume-capital': '05',
      'risk-next': '07',
      'risk-invalidation': '07',
      'formal-action': '01A',
      'page-action': '01A',
      'historical-validation': '08',
    }[targetName];
    var destination = null;
    var sourceModuleTarget = /^evidence-module-strategy-[a-zA-Z0-9_-]+-\d+-(?:02|05)$/.test(targetName);
    if (targetName === 'simulation-tracking' && root && root.querySelector) {
      destination = root.querySelector('.recommendation-simulation-tracking');
      if (!destination) destination = root.querySelector('[data-evidence-module="08"]');
    } else if (sourceModuleTarget && root && root.querySelector) {
      destination = root.querySelector('[aria-labelledby="' + targetName + '"]');
    } else if (moduleNumber && root && root.querySelector) {
      destination = root.querySelector('[data-evidence-module="' + moduleNumber + '"]');
      if (!destination && moduleNumber === '01A') {
        destination = root.querySelector('[data-evidence-module="01"]');
      }
    }
    if (!destination && root && root.querySelector && !sourceModuleTarget) {
      destination = root.querySelector('[data-evidence-node="' + targetName + '"]');
    }
    if (destination) {
      openEvidenceAncestorDetails(destination);
      destination.classList.add('is-evidence-target');
      if (destination.scrollIntoView) destination.scrollIntoView({ behavior: 'smooth', block: 'center' });
      window.setTimeout(function () { destination.classList.remove('is-evidence-target'); }, 1500);
    }
    var chartDate = normalizeString(date).trim();
    if (chartDate && state.chartInstance
        && typeof state.chartInstance.dispatchAction === 'function'
        && typeof state.chartInstance.getOption === 'function') {
      var option = null;
      try {
        option = state.chartInstance.getOption();
      } catch (err) {
        option = null;
      }
      var xAxis = asArray(option && option.xAxis)[0] || {};
      var chartDates = asArray(xAxis.data).map(function (value) {
        return normalizeString(value).trim();
      });
      var index = chartDates.indexOf(chartDate);
      if (index >= 0) {
        state.chartInstance.dispatchAction({ type: 'showTip', seriesIndex: 0, dataIndex: index });
      }
    }
    return destination;
  }

  function bindEvidenceJumps(root) {
    if (!root || !root.querySelectorAll) return;
    Array.prototype.forEach.call(root.querySelectorAll('[data-evidence-target]'), function (element) {
      if (element.getAttribute('data-evidence-bound') === 'true') return;
      element.setAttribute('data-evidence-bound', 'true');
      var activate = function () {
        locateDetailEvidence(element.getAttribute('data-evidence-target'), root, element.getAttribute('data-chart-date'));
      };
      element.addEventListener('click', activate);
      element.addEventListener('keydown', function (event) {
        if (event.key !== 'Enter' && event.key !== ' ') return;
        event.preventDefault();
        activate();
      });
    });
  }

  function selectPersistentPriceLabels(labels) {
    var priorities = { invalidation: 0, current: 1, reference: 2, watch_anchor: 3, pressure: 4, target: 5 };
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
      ? '<div class="chart-signal-list" role="group" aria-label="特殊信号">' + model.signals.map(function (signal, index) {
        var repeatsLabel = signal.name === signal.shortLabel || signal.name.toLowerCase() === 'startup';
        return '<button type="button" class="chart-signal-item' + (index === 0 ? ' is-latest' : '') + '" data-evidence-target="daily-chart" data-chart-date="' + escapeHtml(signal.date) + '" aria-label="定位' + escapeHtml(signal.name) + ' ' + escapeHtml(signal.date) + '">'
          + '<span class="chart-signal-type">' + escapeHtml(signal.shortLabel) + '</span>'
          + (repeatsLabel ? '' : '<strong>' + escapeHtml(signal.name) + '</strong>')
          + '<time>' + escapeHtml(signal.date) + '</time>'
          + '</button>';
      }).join('') + '</div>'
      : '';
    var noteHtml = model.notes.length
      ? '<div class="chart-signal-notes" role="group" aria-label="信号补充说明">' + model.notes.map(function (note) {
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
    var shortLabels = { invalidation: '止', current: '现', reference: '参', watch_anchor: '观', pressure: '压', target: '目' };
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
      watch_anchor: { lineType: 'dotted', symbol: ['none', 'circle'] },
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

  function structureAnnotationSource(raw, chartEvidence) {
    var source = raw && typeof raw === 'object' ? raw : {};
    var annotations = source.structure_annotations && typeof source.structure_annotations === 'object'
      ? source.structure_annotations : {};
    var projected = chartEvidence && chartEvidence.structure && typeof chartEvidence.structure === 'object'
      ? chartEvidence.structure : {};
    var pivotProjection = chartEvidence && chartEvidence.pivots && typeof chartEvidence.pivots === 'object'
      ? chartEvidence.pivots : null;
    var pivotProjectionBlocked = !!(pivotProjection
      && normalizeString(pivotProjection.status).trim()
      && normalizeString(pivotProjection.status).trim() !== 'available');
    return {
      source: source,
      annotations: annotations,
      projected: projected,
      pivotProjection: pivotProjection,
      pivotProjectionBlocked: pivotProjectionBlocked,
    };
  }

  function firstStructureValue(record, keys) {
    var source = record && typeof record === 'object' ? record : {};
    for (var i = 0; i < keys.length; i += 1) {
      var value = source[keys[i]];
      if (value !== undefined && value !== null && value !== '') return value;
    }
    return null;
  }

  function structureDateValue(record, keys, xAxis) {
    var rawValue = firstStructureValue(record, keys);
    var text = normalizeString(rawValue).trim();
    if (text && asArray(xAxis).indexOf(text) !== -1) return text;
    return '';
  }

  function selectStructureChartAreas(raw, chartEvidence, xAxis) {
    var sources = structureAnnotationSource(raw, chartEvidence);
    if (sources.pivotProjectionBlocked) return [];
    var candidates = [];
    asArray(sources.annotations.pivots).forEach(function (value) { candidates.push(value); });
    return candidates.map(function (pivot) {
      var item = pivot && typeof pivot === 'object' ? pivot : {};
      var zg = safeNumber(firstStructureValue(item, ['ZG']), null);
      var zd = safeNumber(firstStructureValue(item, ['ZD']), null);
      var start = structureDateValue(item, ['start_date', 'startDate', 'from_date'], xAxis);
      var end = structureDateValue(item, ['end_date', 'endDate', 'to_date'], xAxis);
      if (!isChartPositivePrice(zg) || !isChartPositivePrice(zd) || !start || !end
          || xAxis.indexOf(start) > xAxis.indexOf(end)) return null;
      var area = [
        { xAxis: start, yAxis: zg },
        { xAxis: end, yAxis: zd },
      ];
      area.name = '中枢';
      area.itemStyle = { color: 'rgba(49, 81, 244, 0.10)' };
      area.label = { show: false };
      return area;
    }).filter(Boolean);
  }

  function selectStructureChartSegments(raw, chartEvidence, xAxis) {
    var sources = structureAnnotationSource(raw, chartEvidence);
    var candidates = [];
    [
      sources.annotations.segments,
      sources.annotations.strokes,
      sources.projected.segments,
      sources.projected.strokes,
      sources.source.segments,
      sources.source.strokes,
    ].forEach(function (values) {
      asArray(values).forEach(function (value) { candidates.push(value); });
    });
    return candidates.map(function (segment) {
      var item = segment && typeof segment === 'object' ? segment : {};
      var start = structureDateValue(item, ['start_date', 'startDate', 'from_date'], xAxis);
      var end = structureDateValue(item, ['end_date', 'endDate', 'to_date'], xAxis);
      var startPrice = safeNumber(firstStructureValue(item, ['start_price', 'startPrice', 'from_price', 'from_value']), null);
      var endPrice = safeNumber(firstStructureValue(item, ['end_price', 'endPrice', 'to_price', 'to_value']), null);
      if (!startPrice && item.start && typeof item.start === 'object') {
        startPrice = safeNumber(firstStructureValue(item.start, ['price', 'value', 'y']), null);
      }
      if (!endPrice && item.end && typeof item.end === 'object') {
        endPrice = safeNumber(firstStructureValue(item.end, ['price', 'value', 'y']), null);
      }
      if (!start || !end || !isChartPositivePrice(startPrice) || !isChartPositivePrice(endPrice)) return null;
      return [
        { coord: [start, startPrice] },
        { coord: [end, endPrice] },
      ];
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
    if ([source.ema5, source.ema20, source.ma5, source.ma10, source.ma20].some(function (values) {
      return asArray(values).filter(function (value) {
        var number = safeNumber(value, null);
        return number !== null && Number.isFinite(number);
      }).length >= 2;
    })) layers.push('trend');
    if (!layers.length) layers.push('decision');
    return layers;
  }

  function renderChartLayerSwitcher(raw, workspaceItem, chartEvidence, quantityProjection) {
    var mount = state.chartLayerSwitcher;
    if (!mount) return;
    var labels = { decision: '决策位', structure: '结构', trend: '趋势' };
    var layers = getAvailableChartLayers(raw, chartEvidence);
    if (layers.indexOf(state.chartLayer) === -1) state.chartLayer = layers[0];
    var overlays = state.chartOverlays && typeof state.chartOverlays === 'object'
      ? state.chartOverlays : (state.chartOverlays = { decision: false, structure: false, trend: false });
    var controls = '<div class="chart-layer-presets" role="group" aria-label="K线预设图层">'
      + layers.map(function (layer) {
      return '<button type="button" data-chart-layer="' + escapeHtml(layer) + '" class="'
        + (layer === state.chartLayer ? 'is-active' : '') + '" aria-pressed="'
        + (layer === state.chartLayer ? 'true' : 'false') + '" aria-label="切换K线图层：'
        + escapeHtml(labels[layer]) + '">' + escapeHtml(labels[layer]) + '</button>';
      }).join('') + '</div>';
    var overlayLabels = { decision: '关键位', structure: '结构', trend: '均线' };
    var overlayControls = ['decision', 'structure', 'trend'].filter(function (layer) {
      return layers.indexOf(layer) !== -1;
    }).map(function (layer) {
      return '<label class="chart-overlay-toggle"><input type="checkbox" data-chart-overlay="'
        + escapeHtml(layer) + '"' + (overlays[layer] ? ' checked' : '') + '>叠加'
        + escapeHtml(overlayLabels[layer]) + '</label>';
    }).join('');
    var overlayHtml = overlayControls
      ? '<div class="chart-layer-overlays" role="group" aria-label="独立叠加图层">'
        + overlayControls + '</div>' : '';
    var windowMode = normalizeChartWindowMode(state.chartWindowMode);
    var windowLabels = { '20': '最近20根', '60': '最近60根', all: '全部', signal: '定位信号' };
    var windowControls = '<div class="chart-window-tools" role="group" aria-label="图表阅读工具">'
      + Object.keys(windowLabels).map(function (mode) {
        return '<button type="button" data-chart-window="' + mode + '" class="'
          + (windowMode === mode ? 'is-active' : '') + '" aria-pressed="'
          + (windowMode === mode ? 'true' : 'false') + '">' + windowLabels[mode] + '</button>';
      }).join('')
      + '<button type="button" data-chart-window="reset" aria-label="重置图表视图">重置</button></div>';
    var missingTrend = layers.indexOf('trend') === -1
      ? '<span class="chart-layer-status" data-chart-layer-unavailable="trend">本期未提供真实均线序列</span>'
      : '';
    var trendDeclaration = chartMaStatusHtml(raw);
    var quantityStatus = '';
    if (quantityProjection && quantityProjection.status !== 'available') {
      quantityStatus = chartVolumeStatusHtml(raw, quantityProjection);
    }
    mount.innerHTML = controls + overlayHtml + windowControls + missingTrend + trendDeclaration + quantityStatus;
    if (typeof mount.querySelectorAll !== 'function') return;
    var buttons = mount.querySelectorAll('[data-chart-layer]');
    for (var i = 0; i < buttons.length; i += 1) {
      buttons[i].addEventListener('click', function (event) {
        state.chartLayer = event.currentTarget.getAttribute('data-chart-layer');
        renderChart(raw, workspaceItem);
      });
    }
    var overlayButtons = mount.querySelectorAll('[data-chart-overlay]');
    for (var o = 0; o < overlayButtons.length; o += 1) {
      overlayButtons[o].addEventListener('change', function (event) {
        var layer = event.currentTarget.getAttribute('data-chart-overlay');
        state.chartOverlays[layer] = !!event.currentTarget.checked;
        renderChart(raw, workspaceItem);
      });
    }
    var windowButtons = mount.querySelectorAll('[data-chart-window]');
    for (var w = 0; w < windowButtons.length; w += 1) {
      windowButtons[w].addEventListener('click', function (event) {
        var mode = event.currentTarget.getAttribute('data-chart-window');
        if (mode === 'reset') {
          state.chartLayer = 'decision';
          state.chartOverlays = { decision: false, structure: false, trend: false };
          state.chartWindowMode = '20';
          state.chartZoomWindow = null;
          state.chartZoomMode = '';
        } else {
          state.chartWindowMode = normalizeChartWindowMode(mode);
          state.chartZoomWindow = null;
        }
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

    var scopeKey = raw ? getChartScopeKey(raw, workspaceItem) : '';
    var sameIdentity = !!(scopeKey && state.chartScopeKey === scopeKey);
    var mountMatches = chartInstanceMatchesMount(state.chartInstance, state.chartMount);
    var sameScope = sameIdentity && mountMatches;
    var previousZoom = sameIdentity ? readChartZoomWindow(state.chartInstance) : null;
    if (!sameScope && state.chartInstance) {
      state.chartInstance.dispose();
      state.chartInstance = null;
      if (!sameIdentity) {
        state.chartZoomWindow = null;
        state.chartZoomMode = '';
      } else if (previousZoom) {
        state.chartZoomWindow = previousZoom;
      }
    }

    if (!raw) {
      renderChartAnnotationLane([]);
      state.chartMount.innerHTML = '<div class="chart-empty">' + escapeHtml(CHART_EMPTY_TEXT) + '</div>';
      state.chartScopeKey = '';
      state.chartZoomWindow = null;
      state.chartZoomMode = '';
      return;
    }

    var dates = asArray(raw.dates);
    var opens = asArray(raw.opens);
    var highs = asArray(raw.highs);
    var lows = asArray(raw.lows);
    var closes = asArray(raw.closes);
    var macd = asArray(raw.macd_hist);
    var minLen = Math.min(dates.length, opens.length, highs.length, lows.length, closes.length);
    if (!hasChartData(raw)) {
      renderChartAnnotationLane([]);
      state.chartMount.innerHTML = '<div class="chart-empty">' + escapeHtml(CHART_EMPTY_TEXT) + '</div>';
      state.chartScopeKey = '';
      state.chartZoomWindow = null;
      state.chartZoomMode = '';
      return;
    }

    state.chartScopeKey = scopeKey;

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

    function projectChartVolumes(record, targetLength) {
      var rawChartVolumes = asArray(record && record.volumes);
      var rawUnits = asArray(record && record.volume_units);
      var rawRawUnits = asArray(record && record.volume_raw_units);
      var rawSources = asArray(record && record.volume_sources);
      if (!rawChartVolumes.length
          || rawUnits.length !== rawChartVolumes.length
          || rawRawUnits.length !== rawChartVolumes.length
          || rawSources.length !== rawChartVolumes.length) {
        return {
          data: Array(targetLength).fill(null),
          available: 0,
          total: targetLength,
          status: 'missing',
          metadata: chartVolumeMetadata(record),
        };
      }
      var alignedVolumes = tailAlignChartSeries(rawChartVolumes, targetLength, null);
      function tailAlignMetadata(values) {
        var aligned = asArray(values).slice(-targetLength);
        while (aligned.length < targetLength) aligned.unshift(null);
        return aligned;
      }
      var units = tailAlignMetadata(rawUnits);
      var rawUnitsAligned = tailAlignMetadata(rawRawUnits);
      var sources = tailAlignMetadata(rawSources);
      var available = 0;
      var data = alignedVolumes.map(function (value, index) {
        var unit = normalizeString(units[index]).trim().toLowerCase();
        var rawUnit = normalizeString(rawUnitsAligned[index]).trim().toLowerCase();
        var source = normalizeString(sources[index]).trim();
        if (value === null || unit !== 'hands'
            || ['hands', 'shares'].indexOf(rawUnit) === -1 || !source) return null;
        available += 1;
        return value;
      });
      return {
        data: data,
        available: available,
        total: targetLength,
        status: available === 0 ? 'missing' : (available === targetLength ? 'available' : 'partial'),
        metadata: chartVolumeMetadata(record),
      };
    }

    var quantityProjection = projectChartVolumes(raw, minLen);
    var volumeSlice = quantityProjection.data;
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
    renderChartLayerSwitcher(raw, workspaceItem, chartEvidence, quantityProjection);
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
    var structureAreas = selectStructureChartAreas(raw, chartEvidence, xAxis);
    var structureSegments = selectStructureChartSegments(raw, chartEvidence, xAxis);
    var curPrice = getCandidateCurrentPriceFromRecord(workspaceItem);
    if (curPrice === null && raw && raw !== workspaceItem) {
      curPrice = getCandidateCurrentPriceFromRecord(raw);
    }
    if (curPrice === null) {
      curPrice = safeNumber(priceEvidence && priceEvidence.current_price, null);
    }
    var referencePurposeBlocked = [workspaceItem, raw].some(function (record) {
      var contract = getCandidateReferenceContract(record);
      var contractReference = safeNumber(contract.reference_price, null);
      var rawStatus = rawReferencePurposeStatus(record);
      var contractBlocked = contractReference !== null
        && !isReferencePurposeVerified(referencePurposeStatus(record, contract));
      var rawValue = safeNumber(record && record.reference_price, null);
      var rawBlocked = contractReference === null && rawValue !== null
        && !isReferencePurposeVerified(rawStatus);
      return contractBlocked || rawBlocked;
    });
    var refPrice = getCandidateReferencePriceForCalculation(workspaceItem);
    if (refPrice === null && raw && raw !== workspaceItem) {
      refPrice = getCandidateReferencePriceForCalculation(raw);
    }
    if (refPrice === null && !referencePurposeBlocked && raw
        && raw.reference_buy_points && raw.reference_buy_points.length > 0) {
      var referencePoint = raw.reference_buy_points[0] || {};
      var pointStatus = normalizeString(referencePoint.status || referencePoint.purpose_status).trim().toLowerCase();
      if (pointStatus === 'verified' || pointStatus === 'formal') {
        refPrice = safeNumber(referencePoint.reference_price, null);
      }
    }
    if (refPrice === null && !referencePurposeBlocked) {
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
    var watchAnchor = workspaceItem && workspaceItem.watch_anchor && typeof workspaceItem.watch_anchor === 'object'
      ? workspaceItem.watch_anchor : (raw.watch_anchor && typeof raw.watch_anchor === 'object' ? raw.watch_anchor : null);
    var watchAnchorValue = watchAnchor && normalizeString(watchAnchor.status).trim() === 'verified'
      ? safeNumber(watchAnchor.value || watchAnchor.price, null) : null;
    if (chartProjectionAllowsPrice(chartEvidence, 'watch_anchor_price', watchAnchorValue)) {
      priceLabelCandidates.push({ kind: 'watch_anchor', value: watchAnchorValue, label: '观察锚点' });
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
            : (/观察锚点|watch[_ -]?anchor/i.test(rawLineName)
              ? 'watch_anchor'
              : (/现价|收盘|current/i.test(rawLineName) ? 'current' : ''))));
      if (rawKind === 'reference' && referencePurposeBlocked) continue;
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

    var overlays = state.chartOverlays && typeof state.chartOverlays === 'object'
      ? state.chartOverlays : (state.chartOverlays = { decision: false, structure: false, trend: false });
    var decisionVisible = state.chartLayer === 'decision' || overlays.decision === true;
    var structureVisible = state.chartLayer === 'structure' || overlays.structure === true;
    var trendVisible = state.chartLayer === 'trend' || overlays.trend === true;
    var activeMarkPoints = decisionVisible || structureVisible ? markPoints : [];
    var activeMarkLines = [];
    if (decisionVisible) activeMarkLines = activeMarkLines.concat(markLines);
    if (structureVisible) activeMarkLines = activeMarkLines.concat(structureLines);
    var trendSeries = [];
    if (trendVisible) {
      [
        ['EMA5', 'ema5'],
        ['MA5', 'ma5'],
        ['MA10', 'ma10'],
        ['EMA20', 'ema20'],
        ['MA20', 'ma20'],
      ].forEach(function (entry) {
        var values = asArray(raw[entry[1]]);
        if (values.filter(function (value) {
          var number = safeNumber(value, null);
          return number !== null && Number.isFinite(number);
        }).length < 2) return;
        trendSeries.push({
          name: entry[0],
          type: 'line',
          data: tailAlignChartSeries(values, minLen, null),
          showSymbol: false,
          smooth: true,
          chartMa: chartMaDeclaration(raw, entry[1]),
        });
      });
    }

    var volumeVisible = quantityProjection.available > 0;
    var macdGridIndex = volumeVisible ? 2 : 1;
    var labelTexts = persistentLabels.map(formatPersistentPriceLabel).concat(structureLines.map(function (line) {
      return normalizeString(line.name) + ' ' + formatNumber(line.yAxis, 2);
    }));
    var labelChars = labelTexts.reduce(function (max, text) {
      return Math.max(max, normalizeString(text).split('\n').reduce(function (inner, value) {
        return Math.max(inner, normalizeString(value).length);
      }, 0));
    }, 0);
    var mobileLabelWidth = Math.max(96, Math.min(180, labelChars * 8 + 24));
    var legacyGridDefaults = { right: state.isMobile ? '96px' : '124px' };
    var defaultChartRight = legacyGridDefaults.right;
    var defaultChartRightPixels = Number.parseInt(defaultChartRight, 10) || 96;
    var chartRight = state.isMobile
      ? Math.max(defaultChartRightPixels, mobileLabelWidth) + 'px'
      : Math.max(defaultChartRightPixels, mobileLabelWidth + 28) + 'px';
    var axisBase = {
      type: 'category',
      data: xAxis,
      boundaryGap: true,
      axisLine: { lineStyle: { color: '#d1d5db' } },
      axisLabel: { show: false },
      splitLine: { show: false },
    };
    var grids = [
      { left: state.isMobile ? '10%' : '6%', right: chartRight, top: '4%', height: volumeVisible ? '51%' : '58%' },
    ];
    var xAxes = [Object.assign({}, axisBase)];
    var yAxes = [{
      scale: true,
      splitLine: { lineStyle: { color: '#f3f4f6' } },
      axisLine: { lineStyle: { color: '#d1d5db' } },
    }];
    if (volumeVisible) {
      grids.push({ left: state.isMobile ? '10%' : '6%', right: chartRight, top: '59%', height: '12%' });
      xAxes.push(Object.assign({}, axisBase, { gridIndex: 1 }));
      yAxes.push({
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
      });
    }
    grids.push({ left: state.isMobile ? '10%' : '6%', right: chartRight,
      top: volumeVisible ? '75%' : '66%', height: volumeVisible ? '12%' : '24%' });
    xAxes.push(Object.assign({}, axisBase, { gridIndex: macdGridIndex, axisLabel: { show: true } }));
    yAxes.push({
      scale: true,
      gridIndex: macdGridIndex,
      name: 'MACD',
      nameLocation: 'end',
      nameGap: 4,
      nameTextStyle: { color: '#64748b', fontSize: 10, align: 'right' },
      splitLine: { lineStyle: { color: '#f3f4f6' } },
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { show: false },
    });

    var requestedWindowMode = normalizeChartWindowMode(state.chartWindowMode);
    var zoomWindow = sameIdentity && state.chartZoomMode === requestedWindowMode
      ? (previousZoom || state.chartZoomWindow) : null;
    if (!zoomWindow || zoomWindow.startValue === undefined || zoomWindow.endValue === undefined) {
      zoomWindow = chartWindowValues(xAxis, requestedWindowMode, rawMarkPoints);
    }
    state.chartZoomWindow = Object.assign({}, zoomWindow);
    state.chartZoomMode = requestedWindowMode;
    state.chartInstance = state.chartInstance || window.echarts.init(state.chartMount);
    var zoomIndexes = xAxes.map(function (_axis, index) { return index; });
    var volumeSeries = {
      name: '成交量',
      type: 'bar',
      data: volumeSlice,
      show: volumeVisible,
      silent: !volumeVisible,
      itemStyle: {
        opacity: volumeVisible ? 1 : 0,
        color: function (params) {
          var bar = kLines[params && params.dataIndex];
          if (!bar || volumeSlice[params.dataIndex] === null) return '#94a3b8';
          return bar[1] >= bar[0] ? '#EF4444' : '#10B981';
        },
      },
    };
    if (volumeVisible) {
      volumeSeries.xAxisIndex = 1;
      volumeSeries.yAxisIndex = 1;
    }
    var macdSeries = {
      name: 'MACD',
      type: 'bar',
      xAxisIndex: macdGridIndex,
      yAxisIndex: macdGridIndex,
      data: macdSlice,
      itemStyle: {
        color: function (params) {
          if (params && params.value === null) return '#94a3b8';
          return params.value >= 0 ? '#EF4444' : '#10B981';
        },
      },
    };
    state.chartInstance.setOption({
      animation: false,
      backgroundColor: '#ffffff',
      grid: grids,
      xAxis: xAxes,
      yAxis: yAxes,
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
      },
      dataZoom: [
        { type: 'inside', xAxisIndex: zoomIndexes, startValue: zoomWindow.startValue, endValue: zoomWindow.endValue },
        { xAxisIndex: zoomIndexes, height: 18, startValue: zoomWindow.startValue, endValue: zoomWindow.endValue },
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
            }).concat(structureVisible ? structureSegments : []),
          },
          markArea: {
            silent: true,
            data: structureVisible ? structureAreas : [],
          },
          itemStyle: {
            color: '#EF4444',
            color0: '#10B981',
            borderColor: '#EF4444',
            borderColor0: '#10B981',
          },
        },
        volumeSeries,
        macdSeries,
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
    var id = normalizeString(config.id || '').trim();
    return ''
      + '<section' + (id ? ' id="' + escapeHtml(id) + '"' : '') + ' class="decision-card ' + escapeHtml(className) + '">'
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
      + '    <div id="marketSentimentChart" class="market-sentiment-chart" role="img" aria-label="最近20个交易日市场情绪折线图"></div>'
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

  function renderFundingMainline(model, activeSector, activeSectorCode, activeSectorRefs, counts) {
    var rec = model || { title: '资金主线', status: {}, items: [] };
    var active = normalizeSectorName(activeSector);
    var activeCode = normalizeString(activeSectorCode).trim();
    var activeRefs = asArray(activeSectorRefs).map(normalizeString).filter(Boolean);
    var metrics = counts && typeof counts === 'object' ? counts : {};
    var status = rec.status || {};
    var tags = asArray(rec.items).map(function (item) {
      var name = normalizeSectorName(item && item.name);
      var sectorCode = normalizeString(item && item.sectorCode).trim();
      var sectorRefs = asArray(item && item.sectorRefs).map(normalizeString).filter(Boolean);
      var selected = activeRefs.length
        ? activeRefs.indexOf(name) !== -1
        : (activeCode ? sectorCode === activeCode : (!sectorCode && name === active));
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
    var feedback = active || activeCode || activeRefs.length
      ? '<div class="funding-mainline-feedback" aria-live="polite">已选板块：<strong>' + escapeHtml(active || activeCode || activeRefs.join('、'))
        + '</strong> · 原池 ' + escapeHtml(String(metrics.originalCount === undefined ? '--' : metrics.originalCount))
        + ' · 匹配 ' + escapeHtml(String(metrics.matchedCount === undefined ? '--' : metrics.matchedCount)) + ' 只</div>'
      : '<div class="funding-mainline-feedback" aria-live="polite">未选择板块 · 原池 ' + escapeHtml(String(metrics.originalCount === undefined ? '--' : metrics.originalCount)) + ' 只</div>';
    return '<div class="funding-mainline-heading"><strong>' + escapeHtml(rec.title || '资金主线') + '</strong>'
      + '<small>' + escapeHtml(status.label || '状态待确认') + '</small></div>'
      + feedback
      + '<div class="funding-mainline-tags">' + body
      + (active || activeCode ? '<button type="button" class="funding-mainline-clear" data-sector-filter="" data-sector-code="" data-sector-refs="">清除筛选</button>' : '')
      + '</div>';
  }

  function renderFundingMainlineStrip() {
    if (!nodes.sectorStrip) return;
    var model = buildFundingMainlineModel(state.data || {});
    nodes.sectorStrip.setAttribute('aria-label', model.title || '资金主线');
    var poolItems = getCurrentViewItems();
    var matchedItems = filterCandidatesBySector(
      poolItems, state.sectorFilter, state.sectorFilterCode, state.sectorFilterRefs
    );
    nodes.sectorStrip.innerHTML = renderFundingMainline(
      model,
      state.sectorFilter,
      state.sectorFilterCode,
      state.sectorFilterRefs,
      { originalCount: poolItems.length, matchedCount: matchedItems.length }
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
        beginCandidateSelection(filtered[0] || null);
        renderFundingMainlineStrip();
        refreshCandidateWorkspace();
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

  function renderWatchDirectionAnalysis(directionRows, registryMap, compact) {
    var compactMode = compact === true;
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
        + '<div class="watch-direction-analysis' + (compactMode ? ' watch-direction-compact' : '') + '">'
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
      + (compactMode ? '' : '  <p>' + escapeHtml(summary) + '</p>')
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

  function renderWatchSharedDirectionSummary(decisionBrief) {
    var rows = asArray((decisionBrief || {}).theses).slice(0, 3);
    if (!rows.length) return '<div class="watch-shared-directions is-empty">今日没有可复用的方向级摘要。</div>';
    return '<div class="watch-shared-directions"><strong>共享方向摘要</strong><span>方向事实只展示一次；下方个股保留自身关联。</span>'
      + '<div>' + rows.map(function (thesis) {
        var riskFlags = getRiskReasonFlags(thesis && thesis.risk_reasons);
        var meta = getDirectionMeta(thesis && thesis.direction, thesis && thesis.stage, riskFlags.hasReasons, riskFlags.hasVerified);
        return '<article><span><strong>' + escapeHtml(thesis && thesis.theme || '--') + '</strong>'
          + '<em class="status-badge is-' + escapeHtml(meta.tone) + '">' + escapeHtml(meta.label) + '</em></span>'
          + '<p>' + escapeHtml(thesis && (thesis.llm_summary || thesis.rule_summary) || '暂无方向解释') + '</p></article>';
      }).join('') + '</div></div>';
  }

  function bindPersonalWatchlist() {
    var owner = nodes.personalWatchlistStack;
    if (!owner || !owner.querySelectorAll) return;
    Array.prototype.forEach.call(owner.querySelectorAll('[data-watch-select]'), function (button) {
      button.addEventListener('click', function () {
        var code = normalizeString(button.getAttribute('data-watch-select')).trim();
        state.watchlistSelectedCode = state.watchlistSelectedCode === code ? '' : code;
        renderAuxiliaryCenter();
        var selected = owner.querySelector('[data-watch-select="' + code + '"]');
        if (selected && selected.focus) selected.focus();
      });
    });
  }

  function renderPersonalWatchlist(data) {
    var personalWatchlist = (data || {}).personal_watchlist || {};
    var decisionBrief = (data || {}).decision_brief || {};
    var evidenceRegistry = asArray(decisionBrief.evidence_registry);
    var registryMap = buildEvidenceRegistryMap({ evidence_registry: evidenceRegistry });
    var rows = asArray(personalWatchlist.items).filter(function (item) {
      return item && item.enabled !== false;
    });
    var selectedCode = normalizeString(state.watchlistSelectedCode).trim();
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
      var hasCandidateEvidence = candidateIntersections.length > 0;
      var selected = selectedCode && selectedCode === normalizeString(rec.code).trim();
      return ''
        + '<article class="personal-watch-row is-' + escapeHtml(factStatus) + '">'
        + '  <button type="button" class="personal-watch-select" data-watch-select="' + escapeHtml(rec.code || '') + '" aria-expanded="' + (selected ? 'true' : 'false') + '">'
        + '    <div class="personal-watch-heading">'
        + '      <span><strong>' + escapeHtml(rec.name || '--') + '</strong><small>' + escapeHtml(rec.code || '') + '</small><em>自选</em></span>'
        + '      <span class="status-badge is-' + escapeHtml(statusTone) + '">' + escapeHtml(statusLabel) + '</span>'
        + '    </div>'
        + '    <div class="watch-facts watch-facts-compact">'
        + '    <span>现价 <strong>' + escapeHtml(price === null ? '--' : formatNumber(price, 2)) + '</strong></span>'
        + '    <span>当日 <strong class="' + (change !== null && change >= 0 ? 'is-up' : (change !== null ? 'is-down' : '')) + '">' + escapeHtml(change === null ? '--' : formatPct(change, true)) + '</strong></span>'
        + '    <span>事实日期 <strong>' + escapeHtml(evidenceDate) + '</strong></span>'
        + '    <span>跟踪状态 <strong>' + escapeHtml(changeStatus) + '</strong></span>'
        + '    </div>'
        + '    <span class="personal-watch-expand-hint">' + (selected ? '收起个人逻辑与关联证据' : '查看个人逻辑与关联证据') + '</span>'
        + '  </button>'
        + '  <div class="personal-watch-detail"' + (selected ? '' : ' hidden') + '>'
        + '    <div class="watch-user-thesis"><span>个人观察逻辑</span><p>' + escapeHtml(rec.thesis || rec.note || '尚未填写个人观察逻辑') + '</p></div>'
        + '    <div class="watch-extra-facts"><span>结构 <strong>' + escapeHtml(factStatus === 'fresh' ? normalizeString(current.trend_type || '待确认') : '不提供旧结论') + '</strong></span><span>动作状态 <strong>' + escapeHtml(actionStatus) + '</strong></span></div>'
        + '    <div class="watch-price-levels">' + renderWatchPriceLevels(priceLevels) + '</div>'
        + '    <div class="watch-relations">' + poolHtml + '</div>'
        + (hasCandidateEvidence
          ? '    <div class="watch-direction-list">' + renderWatchDirectionAnalysis(directionRows, registryMap, true) + '</div>'
          : '    <p class="watch-no-candidate-evidence">未提供本期策略分析</p>')
        + '  </div>'
        + '</article>';
    }).join('') : '<div class="decision-empty">重点观察池尚未配置</div>';
    var freshCount = safeNumber(personalWatchlist.fresh_count, 0);
    return renderDecisionCard({
      title: '我的重点观察',
      subtitle: '个人逻辑与当日事实分开保存；过期数据不输出动作',
      badge: { text: rows.length ? formatNumber(freshCount, 0) + '/' + rows.length + ' 当日' : '未配置', tone: freshCount === rows.length && rows.length ? 'positive' : 'warning' },
      className: 'personal-watchlist-card',
      bodyHtml: renderWatchSharedDirectionSummary(decisionBrief)
        + '<div class="personal-watch-list">' + body + '</div>' + renderWatchlistManager(personalWatchlist),
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
        + '    <strong><span class="holding-role-label">持仓</span>' + escapeHtml(rec.name || '--') + '</strong><small>' + escapeHtml(rec.code || '') + '</small>'
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
    var directions = renderDecisionDirections(source);
    var sectorFlow = renderSectorFlowCard(source);
    var limitUp = renderLimitUpEcologyCard(source);
    var holding = renderHoldingRiskSection(source);
    var watchlist = renderPersonalWatchlist(source);
    var todaySupplement = directions + sectorFlow + limitUp + holding;
    return {
      watchlist: watchlist,
      todaySupplement: todaySupplement,
      // Compatibility view for existing renderer contracts; the shell mounts
      // watchlist and factual supplements in separate ordered anchors.
      today: directions + sectorFlow + limitUp + watchlist + holding,
      research: ''
        + renderDecisionCard({ title: 'PSY12 影子验证', subtitle: '独立观察，不参与正式市场评分与推荐', className: 'psy12-research-card', bodyHtml: renderPsy12ShadowSubpanel(source) })
        + renderStrategyDisagreementAudit(source)
        + renderStrategyScorecards(source)
        + renderShadowEvaluations(source)
        + renderDiagnosticsCard(source),
    };
  }

  function renderAuxiliaryCenter() {
    if (!nodes.auxGrid || !nodes.supportingStack || !nodes.personalWatchlistStack) return;
    var stacks = buildAuxiliaryStacks(state.data || {});
    nodes.personalWatchlistStack.innerHTML = stacks.watchlist;
    nodes.supportingStack.innerHTML = stacks.todaySupplement;
    nodes.auxGrid.innerHTML = stacks.research;
    bindSingleOpenDecisionDetails();
    bindPersonalWatchlist();
    bindWatchlistManager();
    setTimeout(renderMarketSentimentChart, 0);
  }

  var NEXTDAY_RESEARCH_METRICS = [
    { key: 'cc1', label: '信号日收盘→次日收盘', shortLabel: 'CC1' },
    { key: 'gap1', label: '信号日收盘→次日开盘', shortLabel: 'GAP1' },
    { key: 'oc1', label: '次日开盘→次日收盘', shortLabel: 'OC1' },
    { key: 'oc2', label: '次日开盘→T+2收盘', shortLabel: 'OC2' },
    { key: 'oc3', label: '次日开盘→T+3收盘', shortLabel: 'OC3' },
  ];

  var NEXTDAY_PATH_STATUS_LABELS = {
    observed: '已观测',
    pending: '待目标日',
    calendar_unavailable: '交易日历不可用',
    basis_unverified: '价基未核验',
    data_unavailable: '行情不可用',
    signal_bar_unavailable: '信号日行情不可用',
    missing: '数据缺失',
    nonfinal: '行情未最终确认',
    invalid_status: '行情状态无效',
    invalid_ohlc: '价格数据无效',
    duplicate_inconsistent: '重复行情冲突',
    unavailable: '暂不可用',
    unknown: '状态未识别',
  };

  var NEXTDAY_BASIS_STATUS_LABELS = {
    pending: '待目标日',
    not_matured: '尚未到期',
    calendar_unavailable: '交易日历不可用',
    raw_comparable: '原始价可比',
    qfq_comparable: '复权价可比',
    within_bar_invariant: '同一根 K 线内计算',
    price_basis_unverified: '价基未核验',
    data_unavailable: '行情不可用',
    signal_bar_unavailable: '信号日行情不可用',
    unknown: '价基状态未识别',
  };

  function isNextdayRecord(value) {
    return !!value && typeof value === 'object' && !Array.isArray(value);
  }

  function nextdayStrictCount(value) {
    return typeof value === 'number' && isFinite(value) && value >= 0 && Math.floor(value) === value
      ? value : null;
  }

  function nextdayStrictPercent(value) {
    return typeof value === 'number' && isFinite(value) ? value : null;
  }

  function validateNextdayResearchPayload(payload, reportDate) {
    var expectedDate = normalizeString(reportDate).trim();
    if (!isCanonicalIsoDate(expectedDate) || !isNextdayRecord(payload)) return null;
    if (payload.schema_version !== 'nextday-research-public-v1'
        || normalizeString(payload.report_date).trim() !== expectedDate
        || ['available', 'partial'].indexOf(normalizeString(payload.status).trim()) === -1
        || !isNextdayRecord(payload.summary)
        || !isNextdayRecord(payload.l1)
        || !isNextdayRecord(payload.b0)
        || !isNextdayRecord(payload.outcomes)) return null;
    var selectionGroups = [payload.l1, payload.b0];
    if (!selectionGroups.every(function (group) {
      return ['evaluated', 'not_evaluated'].indexOf(normalizeString(group.status).trim()) !== -1
        && Array.isArray(group.selected);
    })) return null;
    var outcomeGroups = [payload.outcomes.l1, payload.outcomes.b0];
    if (!outcomeGroups.every(function (group) {
      return isNextdayRecord(group)
        && ['evaluated', 'not_evaluated'].indexOf(normalizeString(group.status).trim()) !== -1
        && Array.isArray(group.outcome_rows);
    })) return null;
    return payload;
  }

  function nextdayResearchNoticeHtml(message, retryable) {
    return '<div class="l1-nextday-notice" role="status"><span>' + escapeHtml(message)
      + '</span>' + (retryable
        ? '<button type="button" data-nextday-research-retry>重新读取</button>' : '') + '</div>';
  }

  function getNextdayResearchUrl(reportDate) {
    var date = normalizeString(reportDate).trim();
    if (!isCanonicalIsoDate(date)) return '';
    var prefix = normalizeString(getBootstrap().dataBasePrefix).trim();
    if (prefix && prefix !== './' && !/^(\.\.\/){1,2}$/.test(prefix)) return '';
    return prefix + 'research/nextday/' + date + '.json';
  }

  function getVisibleNextdayResearchDate() {
    var bootstrapDate = normalizeString(getBootstrap().pageDate).trim();
    var data = state.data || {};
    var dataDate = normalizeString(data.date || data.report_date).trim();
    if (!isCanonicalIsoDate(bootstrapDate) || !isCanonicalIsoDate(dataDate)
        || bootstrapDate !== dataDate) return '';
    return bootstrapDate;
  }

  function getNextdayResearchSourceLabel(sourcePool) {
    return getViewSourcePoolLabel(sourcePool);
  }

  function nextdayResearchTextList(value) {
    if (!Array.isArray(value)) return [];
    return value.map(function (item) { return normalizeString(item).trim(); }).filter(Boolean);
  }

  function nextdayResearchListText(value, fallback) {
    var values = nextdayResearchTextList(value);
    return values.length ? values.join('、') : (fallback || '未登记');
  }

  function nextdayResearchMetricStatus(metric) {
    var value = isNextdayRecord(metric) ? metric : {};
    var status = normalizeString(value.status).trim();
    var basis = normalizeString(value.price_basis_status).trim();
    var percent = nextdayStrictPercent(value.value_pct);
    if (status === 'observed') {
      if (percent === null) return { text: '结果数值未提供', observed: false, value: null };
      if (basis === 'raw_comparable' || basis === 'qfq_comparable' || basis === 'within_bar_invariant') {
        return { text: formatPct(percent, true), observed: true, value: percent };
      }
      if (basis === 'price_basis_unverified') {
        return { text: '价基未核验', observed: false, value: null };
      }
      return { text: NEXTDAY_BASIS_STATUS_LABELS[basis] || '价基状态未识别', observed: false, value: null };
    }
    if (status === 'basis_unverified' || basis === 'price_basis_unverified') {
      return { text: '价基未核验', observed: false, value: null };
    }
    return {
      text: NEXTDAY_PATH_STATUS_LABELS[status] || '结果未提供',
      observed: false,
      value: null,
    };
  }

  function nextdayOutcomeRowsByIdentity(outcomeGroup) {
    var map = Object.create(null);
    asArray(outcomeGroup && outcomeGroup.outcome_rows).forEach(function (row) {
      var identity = normalizeString(row && row.stock_identity).trim();
      if (!identity) return;
      if (Object.prototype.hasOwnProperty.call(map, identity)) {
        map[identity] = null;
      } else {
        map[identity] = row;
      }
    });
    return map;
  }

  function renderNextdayCandidateOutcome(row) {
    if (!isNextdayRecord(row) || !isNextdayRecord(row.path_metrics)) {
      return '<div class="l1-nextday-outcome-empty">路径结果未登记</div>';
    }
    return (row.entry_one_price === true
      ? '<p class="l1-nextday-entry-warning">一字日，成交不确定</p>' : '')
      + '<div class="l1-nextday-row-metrics" aria-label="次日价格路径状态">'
      + NEXTDAY_RESEARCH_METRICS.map(function (entry) {
        var result = nextdayResearchMetricStatus(row.path_metrics[entry.key]);
        return '<span class="l1-nextday-row-metric' + (result.observed ? ' is-observed' : '') + '"><small>'
          + escapeHtml(entry.label) + ' <em>(' + entry.shortLabel + ')</em></small><strong>'
          + escapeHtml(result.text) + '</strong></span>';
      }).join('') + '</div>';
  }

  function nextdayOutcomeStatusCounts(outcomeGroup, metricKey) {
    var counts = Object.create(null);
    asArray(outcomeGroup && outcomeGroup.outcome_rows).forEach(function (row) {
      var metric = (row && row.path_metrics && row.path_metrics[metricKey]) || {};
      var stateName = normalizeString(metric.status).trim() || 'unknown';
      if (stateName === 'observed' && !nextdayResearchMetricStatus(metric).observed) {
        stateName = normalizeString(metric.price_basis_status).trim() === 'price_basis_unverified'
          ? 'basis_unverified' : 'unknown';
      }
      counts[stateName] = (counts[stateName] || 0) + 1;
    });
    return counts;
  }

  function nextdayOutcomeGroupMetricText(outcomeGroup, key) {
    var group = isNextdayRecord(outcomeGroup) ? outcomeGroup : {};
    if (normalizeString(group.status).trim() !== 'evaluated') return '结果未评估';
    var metric = isNextdayRecord(group.metrics && group.metrics[key]) ? group.metrics[key] : {};
    var observed = nextdayStrictCount(metric.observed);
    var mean = nextdayStrictPercent(metric.mean_pct);
    var rows = asArray(group.outcome_rows);
    var observedRows = rows.filter(function (row) {
      return nextdayResearchMetricStatus((row && row.path_metrics || {})[key]).observed;
    }).length;
    if (observed !== null && observed > 0 && observed === observedRows && mean !== null) {
      var text = '均值 ' + formatPct(mean, true) + ' · 已观测 ' + observed;
      var median = nextdayStrictPercent(metric.median_pct);
      if (median !== null) text += ' · 中位数 ' + formatPct(median, true);
      var selected = nextdayStrictCount(group.metrics.selected);
      if (selected !== null && selected > observed) text += ' / ' + selected + '只';
      var gainField = key === 'oc1' ? 'gain_ge_3' : (key === 'cc1' ? 'gain_ge_5' : '');
      var gain = gainField ? nextdayStrictCount(metric[gainField]) : null;
      var loss = nextdayStrictCount(metric.loss_le_minus5);
      if (gain !== null) text += ' · ' + (key === 'oc1' ? '≥3% ' : '≥5% ') + gain + '/' + observed;
      if (loss !== null) text += ' · ≤−5% ' + loss + '/' + observed;
      return text;
    }
    if (observed !== null && observed > 0) return '统计与逐项结果不一致，暂不汇总';
    var counts = nextdayOutcomeStatusCounts(group, key);
    var labels = [
      ['pending', '待目标日'],
      ['basis_unverified', '价基未核验'],
      ['missing', '数据缺失'],
      ['data_unavailable', '行情不可用'],
      ['calendar_unavailable', '交易日历不可用'],
      ['nonfinal', '行情未最终确认'],
      ['invalid_status', '行情状态无效'],
      ['invalid_ohlc', '价格数据无效'],
      ['signal_bar_unavailable', '信号日行情不可用'],
      ['duplicate_inconsistent', '重复行情冲突'],
    ];
    var summaries = labels.filter(function (entry) { return counts[entry[0]]; }).map(function (entry) {
      return entry[1] + ' ' + counts[entry[0]];
    });
    return summaries.length ? summaries.join(' · ') : '暂无可验证结果';
  }

  function renderNextdayOutcomeSummary(outcomeGroup, reportDate) {
    var group = isNextdayRecord(outcomeGroup) ? outcomeGroup : {};
    var asOf = normalizeString(group.as_of_date).trim() || normalizeString(reportDate).trim();
    var metrics = NEXTDAY_RESEARCH_METRICS.map(function (entry) {
      return '<div class="l1-nextday-group-metric"><span>' + escapeHtml(entry.label)
        + ' <em>(' + entry.shortLabel + ')</em></span><strong>'
        + escapeHtml(nextdayOutcomeGroupMetricText(group, entry.key)) + '</strong></div>';
    }).join('');
    var reason = normalizeString(group.reason).trim();
    return '<section class="l1-nextday-outcome-summary" aria-label="分组价格路径统计">'
      + '<header><strong>价格路径跟踪</strong><span>截至 ' + escapeHtml(isCanonicalIsoDate(asOf) ? asOf : '日期未提供') + '</span></header>'
      + (normalizeString(group.status).trim() === 'not_evaluated'
        ? '<p class="l1-nextday-outcome-reason">结果未评估' + (reason ? '：' + escapeHtml(reason) : '') + '</p>'
        : '<div class="l1-nextday-group-metrics">' + metrics + '</div>')
      + '<p class="l1-nextday-outcome-boundary">行情路径观察，不代表可成交结果或实盘收益；费用、滑点、排队与成交均未模拟。</p>'
      + '</section>';
  }

  function nextdayResearchIdentity(item) {
    return normalizeString(item && item.stock_identity).trim();
  }

  function nextdayResearchOverlap(l1, b0) {
    if (normalizeString(l1 && l1.status).trim() !== 'evaluated'
        || normalizeString(b0 && b0.status).trim() !== 'evaluated') return null;
    var l1Map = Object.create(null);
    asArray(l1.selected).forEach(function (item) {
      var identity = nextdayResearchIdentity(item);
      if (identity) l1Map[identity] = item;
    });
    return asArray(b0.selected).map(function (item) {
      var identity = nextdayResearchIdentity(item);
      return identity && l1Map[identity]
        ? { identity: identity, name: normalizeString(item.name || l1Map[identity].name).trim() }
        : null;
    }).filter(Boolean);
  }

  function nextdayResearchCandidateHtml(item, index, groupKind, overlapMap, outcomeMap) {
    var value = isNextdayRecord(item) ? item : {};
    var identity = nextdayResearchIdentity(value);
    var name = normalizeString(value.name).trim() || '名称未提供';
    var exchange = normalizeString(value.exchange).trim();
    var code = normalizeString(value.code).trim();
    var displayCode = identity || (exchange && code ? exchange + code : code || '代码未提供');
    var rank = nextdayStrictCount(value.rank);
    var sourcePools = nextdayResearchTextList(value.source_pools).map(getNextdayResearchSourceLabel);
    var riskFlags = nextdayResearchTextList(value.risk_flags);
    var avoidChase = value.avoid_chase === true ? '避免追高'
      : (value.avoid_chase === false ? '未标记避免追高' : '追高限制未登记');
    var overlap = identity && overlapMap && overlapMap[identity];
    var industry = normalizeString(value.industry).trim();
    var limitSector = normalizeString(value.limit_sector).trim();
    var industryCount = nextdayStrictCount(value.industry_count);
    var boardCount = nextdayStrictCount(value.board_n);
    var sealTime = normalizeString(value.first_limit_time).trim();
    var topic = limitSector
      ? '涨停题材 ' + limitSector + (industryCount === null ? ' · 家数未记录' : ' · ' + industryCount + '家')
      : '涨停题材未登记';
    var industryText = industry ? '行业 ' + industry : '行业未登记';
    var poolText = sourcePools.length ? sourcePools.join(' · ') : '来源池未登记';
    var rowOutcome = outcomeMap && identity ? outcomeMap[identity] : null;
    var nextDayConditions = nextdayResearchTextList(value.next_day_conditions);
    if (!nextDayConditions.length) nextDayConditions = nextdayResearchTextList(value.next_confirmation);
    var cancelConditions = nextdayResearchTextList(value.cancel_conditions);
    nextdayResearchTextList(value.invalidation).forEach(function (condition) {
      if (cancelConditions.indexOf(condition) === -1) cancelConditions.push(condition);
    });
    var candidateClass = groupKind === 'l1' ? 'is-l1' : 'is-b0';
    return '<li class="l1-nextday-candidate ' + candidateClass + '"><article>'
      + '<header class="l1-nextday-candidate-head"><span class="l1-nextday-rank">'
      + escapeHtml(rank === null ? '顺序 ' + (index + 1) : '#' + rank) + '</span>'
      + '<span class="l1-nextday-name">' + escapeHtml(name) + '</span>'
      + '<span class="l1-nextday-code">' + escapeHtml(displayCode) + '</span>'
      + (overlap ? '<span class="l1-nextday-overlap">与 ' + (groupKind === 'l1' ? 'B0' : 'L1') + ' 重叠</span>' : '')
      + '</header>'
      + '<div class="l1-nextday-source-pools">' + sourcePools.map(function (pool) {
        return '<span>' + escapeHtml(pool) + '</span>';
      }).join('') + '</div>'
      + '<p class="l1-nextday-sector">' + escapeHtml(industryText) + ' · ' + escapeHtml(topic)
      + ' · ' + escapeHtml(boardCount === null ? '连板数未记录' : boardCount + '板')
      + ' · ' + escapeHtml(sealTime ? '首封 ' + sealTime : '首封时间未记录') + '</p>'
      + '<p class="l1-nextday-risk"><strong>' + escapeHtml(avoidChase) + '</strong> · '
      + escapeHtml(riskFlags.length ? riskFlags.join('、') : '风险标签未列出，不代表无风险') + '</p>'
      + '<p class="l1-nextday-watch-reason"><strong>观察依据</strong> '
      + escapeHtml(normalizeString(value.watch_reason || value.startup_reason).trim() || '未登记') + '</p>'
      + '<div class="l1-nextday-condition-list">'
      + '<p><strong>次日条件</strong> ' + escapeHtml(nextDayConditions.length ? nextDayConditions.join('；') : '未登记') + '</p>'
      + '<p><strong>升级条件</strong> ' + escapeHtml(nextdayResearchListText(value.upgrade_conditions)) + '</p>'
      + '<p><strong>取消条件</strong> ' + escapeHtml(cancelConditions.length ? cancelConditions.join('；') : '未登记') + '</p>'
      + '</div>' + renderNextdayCandidateOutcome(rowOutcome) + '</article></li>';
  }

  function renderNextdaySelectionGroup(title, kind, group, opposite, outcomes, asOfDate, overlapRows) {
    var selection = isNextdayRecord(group) ? group : {};
    var groupStatus = normalizeString(selection.status).trim();
    var selected = Array.isArray(selection.selected) ? selection.selected : [];
    var countText = groupStatus === 'evaluated' ? selected.length + '只' : '未评估';
    var identityMap = Object.create(null);
    asArray(overlapRows).forEach(function (row) { identityMap[row.identity] = true; });
    var outcomeGroup = outcomes && outcomes[kind] && typeof outcomes[kind] === 'object'
      ? outcomes[kind] : {};
    var outcomeMap = nextdayOutcomeRowsByIdentity(outcomeGroup);
    var subtitle = kind === 'l1'
      ? '排序：行业涨停家数降序 → 连板数降序 → 首封时间升序 → 证券身份；保持源顺序，最多五只，不补位。'
      : '日报原看点顺序对照；仅展示原有数量。';
    var registrationStatus = normalizeString(selection.registration_status).trim();
    if (registrationStatus === 'historical' || registrationStatus === 'retrospective') {
      var groupFrozenAt = normalizeString(selection.frozen_at).trim();
      subtitle += ' · 回溯登记 · 冻结 ' + (groupFrozenAt || '时间未记录');
    }
    var body = '';
    if (groupStatus === 'not_evaluated') {
      body = '<div class="l1-nextday-group-empty is-not-evaluated"><strong>'
        + (kind === 'l1' ? 'L1 未评估' : 'B0 未评估') + '</strong><span>'
        + escapeHtml(normalizeString(selection.reason).trim() || '输入证据不足，未判断为空选。') + '</span></div>';
    } else if (!selected.length) {
      body = '<div class="l1-nextday-group-empty is-evaluated-empty"><strong>'
        + (kind === 'l1' ? 'L1 已评估，未选出候选' : 'B0 已评估，当前没有原看点条目')
        + '</strong></div>';
    } else {
      body = '<ol class="l1-nextday-candidate-list">' + selected.map(function (item, index) {
        return renderNextdayResearchCandidateForGroup(item, index, kind, identityMap, outcomeMap);
      }).join('') + '</ol>';
    }
    return '<section class="l1-nextday-group ' + (kind === 'l1' ? 'is-l1' : 'is-b0') + '">'
      + '<header class="l1-nextday-group-head"><div><h3>' + escapeHtml(title) + '</h3><p>'
      + escapeHtml(subtitle) + '</p></div><span class="l1-nextday-group-count">' + escapeHtml(countText) + '</span></header>'
      + body + renderNextdayOutcomeSummary(outcomeGroup, asOfDate) + '</section>';
  }

  function renderNextdayResearchCandidateForGroup(item, index, kind, overlapMap, outcomeMap) {
    return nextdayResearchCandidateHtml(item, index, kind, overlapMap, outcomeMap);
  }

  function renderNextdayResearchProjection(payload, reportDate) {
    var projection = validateNextdayResearchPayload(payload, reportDate);
    if (!projection) return nextdayResearchNoticeHtml('本期研究结果不可用', true);
    var overlapRows = nextdayResearchOverlap(projection.l1, projection.b0);
    var overlapText = overlapRows === null
      ? 'L1 / B0 重叠关系未评估'
      : (overlapRows.length
        ? 'L1 / B0 重叠：' + overlapRows.map(function (row) { return row.name + '（' + row.identity + '）'; }).join('、')
        : 'L1 / B0 无重复标的');
    var summary = projection.summary || {};
    var statusText = projection.status === 'partial' ? '研究结果部分可用' : '研究结果已生成';
    var snapshotLabel = projection.l1.status === 'evaluated' ? '完整涨停快照' : '涨停快照样本';
    var topReason = normalizeString(projection.reason).trim();
    var asOfDate = normalizeString(projection.outcomes && projection.outcomes.as_of_date).trim();
    var l1Count = projection.l1.status === 'evaluated' ? projection.l1.selected.length : null;
    var b0Count = projection.b0.status === 'evaluated' ? projection.b0.selected.length : null;
    var l1OverlapMap = Object.create(null);
    var b0OverlapMap = Object.create(null);
    asArray(overlapRows).forEach(function (row) {
      l1OverlapMap[row.identity] = true;
      b0OverlapMap[row.identity] = true;
    });
    var l1OutcomeMap = nextdayOutcomeRowsByIdentity(projection.outcomes.l1);
    var b0OutcomeMap = nextdayOutcomeRowsByIdentity(projection.outcomes.b0);
    var metaParts = [];
    var algorithm = normalizeString(projection.algorithm_version).trim();
    var runId = normalizeString(projection.source_run_id).trim();
    var frozenAt = normalizeString(projection.frozen_at).trim();
    if (algorithm) metaParts.push('算法 ' + algorithm);
    if (runId) metaParts.push('运行 ' + runId);
    if (frozenAt) metaParts.push('冻结 ' + frozenAt);
    return '<div class="l1-nextday-projection" data-report-date="' + escapeHtml(reportDate) + '">'
      + '<div class="l1-nextday-status-line"><strong>' + escapeHtml(statusText) + '</strong>'
      + '<span>报告日 ' + escapeHtml(reportDate) + '</span></div>'
      + '<p class="l1-nextday-coverage">系统候选 ' + escapeHtml(nextdayStrictCount(summary.candidate_count) === null ? '—' : String(summary.candidate_count))
      + ' · ' + escapeHtml(snapshotLabel) + ' ' + escapeHtml(nextdayStrictCount(summary.snapshot_unique_count) === null ? '—' : String(summary.snapshot_unique_count))
      + ' · 交集 ' + escapeHtml(nextdayStrictCount(summary.candidate_snapshot_intersection) === null ? '—' : String(summary.candidate_snapshot_intersection))
      + '</p><p class="l1-nextday-overlap-summary">' + escapeHtml(overlapText) + '</p>'
      + (topReason ? '<p class="l1-nextday-top-reason">' + escapeHtml(topReason) + '</p>' : '')
      + (metaParts.length ? '<p class="l1-nextday-meta">' + escapeHtml(metaParts.join(' · ')) + '</p>' : '')
      + '<div class="l1-nextday-groups">'
      + renderNextdaySelectionGroup('L1 次日强势候选', 'l1', projection.l1, projection.b0,
        projection.outcomes, asOfDate, overlapRows)
      + renderNextdaySelectionGroup('B0 原看点对照', 'b0', projection.b0, projection.l1,
        projection.outcomes, asOfDate, overlapRows)
      + '</div><p class="l1-nextday-boundary">研究观察，不构成正式推荐；价格路径记录不进入正式候选、排序或操作建议。</p></div>';
  }

  function cancelNextdayResearchRequest() {
    var request = state.nextdayResearch || {};
    if (request.timeoutTimer) clearTimeout(request.timeoutTimer);
    if (request.controller && typeof request.controller.abort === 'function') {
      try { request.controller.abort(); } catch (err) {}
    }
    request.timeoutTimer = null;
    request.controller = null;
  }

  function isCurrentNextdayResearchRequest(requestToken, reportDate, mount) {
    return !!mount
      && requestToken === state.nextdayResearch.requestToken
      && state.nextdayResearch.reportDate === reportDate
      && getVisibleNextdayResearchDate() === reportDate;
  }

  function loadNextdayResearch() {
    var mount = nodes.nextdayResearch;
    if (!mount) return Promise.resolve(false);
    cancelNextdayResearchRequest();
    state.nextdayResearch.requestToken += 1;
    var requestToken = state.nextdayResearch.requestToken;
    state.nextdayResearch.reportDate = '';
    var reportDate = getVisibleNextdayResearchDate();
    if (!reportDate) {
      mount.innerHTML = nextdayResearchNoticeHtml('报告日期无法匹配，未加载研究结果。', false);
      return Promise.resolve(false);
    }
    if (!state.granted) {
      mount.innerHTML = nextdayResearchNoticeHtml('日报访问尚未授权，未读取研究结果。', false);
      return Promise.resolve(false);
    }
    var url = getNextdayResearchUrl(reportDate);
    if (!url) {
      mount.innerHTML = nextdayResearchNoticeHtml('研究结果路径配置不可用。', false);
      return Promise.resolve(false);
    }
    state.nextdayResearch.reportDate = reportDate;
    mount.innerHTML = '<div class="l1-nextday-notice is-loading" role="status">正在读取 ' + escapeHtml(reportDate) + ' 研究结果…</div>';
    var controller = null;
    var Controller = window.AbortController
      || (typeof AbortController !== 'undefined' ? AbortController : null);
    if (Controller) {
      try { controller = new Controller(); } catch (err) { controller = null; }
    }
    state.nextdayResearch.controller = controller;
    var fetchOptions = { method: 'GET', credentials: 'same-origin' };
    if (controller) fetchOptions.signal = controller.signal;
    var timeoutPromise = new Promise(function (resolve, reject) {
      state.nextdayResearch.timeoutTimer = setTimeout(function () {
        if (controller && typeof controller.abort === 'function') {
          try { controller.abort(); } catch (err) {}
        }
        var error = new Error('nextday research request timed out');
        error.code = 'timeout';
        reject(error);
      }, 8000);
    });
    var fetchPromise;
    try {
      fetchPromise = window.fetch(url, fetchOptions);
    } catch (error) {
      fetchPromise = Promise.reject(error);
    }
    return Promise.race([Promise.resolve(fetchPromise), timeoutPromise]).then(function (response) {
      if (!response || !response.ok) {
        var fetchError = new Error('nextday research sidecar unavailable');
        fetchError.status = response && response.status;
        throw fetchError;
      }
      if (typeof response.json !== 'function') throw new Error('invalid JSON response');
      return response.json();
    }).then(function (payload) {
      if (!isCurrentNextdayResearchRequest(requestToken, reportDate, mount)) return false;
      var projection = validateNextdayResearchPayload(payload, reportDate);
      if (!projection) {
        mount.innerHTML = nextdayResearchNoticeHtml('本期研究结果不可用', true);
        return false;
      }
      mount.innerHTML = renderNextdayResearchProjection(projection, reportDate);
      return true;
    }).catch(function (error) {
      if (!isCurrentNextdayResearchRequest(requestToken, reportDate, mount)) return false;
      if (error && error.status === 404) {
        mount.innerHTML = nextdayResearchNoticeHtml('本日研究结果尚未发布', true);
      } else {
        mount.innerHTML = nextdayResearchNoticeHtml('本期研究结果暂不可用，可重新读取。', true);
      }
      return false;
    }).finally(function () {
      if (requestToken !== state.nextdayResearch.requestToken) return;
      if (state.nextdayResearch.timeoutTimer) clearTimeout(state.nextdayResearch.timeoutTimer);
      state.nextdayResearch.timeoutTimer = null;
      state.nextdayResearch.controller = null;
    });
  }

  function openNextdayResearchFromHash() {
    if (!window.location || normalizeString(window.location.hash) !== '#nextday-research') return false;
    state.primaryMode = 'research';
    renderPrimaryMode();
    var focusSection = function () {
      if (!nodes.nextdayResearchSection) return;
      if (nodes.nextdayResearchSection.scrollIntoView) {
        nodes.nextdayResearchSection.scrollIntoView({ block: 'start' });
      }
      if (nodes.nextdayResearchSection.focus) {
        try { nodes.nextdayResearchSection.focus({ preventScroll: true }); }
        catch (err) { nodes.nextdayResearchSection.focus(); }
      }
    };
    if (window.requestAnimationFrame) window.requestAnimationFrame(focusSection);
    else setTimeout(focusSection, 0);
    return true;
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
      beginCandidateSelection(item);
    }
    if (!state.activeItem) return;
    syncMobileDrawerViewport();
    if (nodes.detailPanel) nodes.detailPanel.innerHTML = '';
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
    if (nodes.drawerContent) {
      var chartInDrawer = Boolean(
        state.detailTarget === nodes.drawerContent
        || (state.chartMount
          && typeof nodes.drawerContent.contains === 'function'
          && nodes.drawerContent.contains(state.chartMount))
      );
      if (chartInDrawer && state.chartInstance) {
        var savedZoom = readChartZoomWindow(state.chartInstance);
        if (savedZoom) state.chartZoomWindow = savedZoom;
      }
      if (chartInDrawer) {
        clearCandidateDetailLifecycle(nodes.drawerContent);
      } else {
        // The drawer can already be hidden while the desktop detail owns the chart.
        nodes.drawerContent.innerHTML = '';
      }
    }
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
    var wasMobile = state.isMobile;
    state.isMobile = isMobileViewport();
    if (wasMobile && !state.isMobile && nodes.detailPanel && state.activeItem) {
      closeMobileDetailDrawer();
      renderCandidateDetail(state.activeItem);
    }
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
      var projectionWithoutWorkspace = getDecisionWorkbench(data);
      state.workspace = {
        default_view: projectionWithoutWorkspace ? 'decision_formal' : 'main',
        view_order: DEFAULT_VIEW_ORDER,
        view_meta: {},
        views: {},
      };
      state.decisionStatusFilter = '';
      state.currentView = state.workspace.default_view;
      return;
    }

    state.workspace = Object.assign({}, ws);
    var projection = getDecisionWorkbench(data);
    var resolved = resolvePrimaryNavigationState(
      ws.default_view || state.currentView,
      Boolean(projection)
    );
    if (projection) state.workspace.default_view = resolved.viewKey;
    state.decisionStatusFilter = resolved.statusFilter;
    state.currentView = resolved.viewKey || state.currentView;
    if (!state.currentView) state.currentView = 'main';
  }

  function initReportV2() {
    syncViewport();
    state.isMobile = isMobileViewport();
    buildAppShell();
    refreshReviewToolsMounts();
    renderPrimaryMode();
    openNextdayResearchFromHash();
    if (window.addEventListener && !state.nextdayResearch.hashListenerBound) {
      window.addEventListener('hashchange', openNextdayResearchFromHash);
      state.nextdayResearch.hashListenerBound = true;
    }
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
      renderDecisionOverview();
      renderReviewToolPanels();
      renderFundingMainlineStrip();
      renderDirectionQuickSummary(state.data);
      renderMarketHotspot();
      renderHistoricalReconstruction(state.data);
      renderWorkspaceTabs();
      renderViewDescription();
      var first = renderCurrentCandidateSelection();
      renderAuxiliaryCenter();
      loadNextdayResearch();
      initComparisonSummary();
      renderTop10Control();
      if (state.isMobile && first) {
        clearCandidateDetailLifecycle(nodes.detailPanel);
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
  window.renderDecisionChangesPanel = renderDecisionChangesPanel;
  window.renderDecisionChangeHistory = renderDecisionChangeHistory;
  window.loadDecisionChangeHistory = loadDecisionChangeHistory;
  window.validateDecisionHistoryPayload = validateDecisionHistoryPayload;
  window.validateDecisionHistoryRow = validateDecisionHistoryRow;
  window.decisionHistoryEntries = decisionHistoryEntries;
  window.renderQuickComparison = renderQuickComparison;
  window.toggleQuickComparisonSelection = toggleQuickComparisonSelection;
  window.renderHistoricalValidationLink = renderHistoricalValidationLink;
  window.bindHistoricalEvidenceLinks = bindHistoricalEvidenceLinks;
  window.renderCandidateDetail = renderCandidateDetail;
  window.openMobileDetailDrawer = openMobileDetailDrawer;
  window.closeMobileDetailDrawer = closeMobileDetailDrawer;
  window.findRawCandidate = findRawCandidate;
  window.renderChart = renderChart;
  window.renderAuxiliaryCenter = renderAuxiliaryCenter;
  window.renderMarketHotspot = renderMarketHotspot;
  window.openMarketHotspotDetail = openMarketHotspotDetail;
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

  function getReviewRegistry(index) {
    var registry = index && index.review_registry;
    return registry && Number(registry.schema_version) === 1
      && Array.isArray(registry.entries) ? registry : null;
  }

  function reviewRegistryNumber(value) {
    var number = Number(value);
    return value === null || value === undefined || value === ''
      || !Number.isFinite(number) ? null : number;
  }

  function reviewRegistryMetricNumber(value) {
    return typeof value === 'number' && Number.isFinite(value) ? value : null;
  }

  function reviewRegistryHorizonMetric(horizon) {
    var value = horizon && typeof horizon === 'object' ? horizon : {};
    var status = normalizeString(value.status).trim();
    var basis = normalizeString(value.price_basis_status).trim();
    var verifiedStatuses = ['calculated', 'calculated_verified'];
    var verifiedBases = [
      'canonical_raw_verified',
      'canonical_qfq_verified',
      'canonical_hfq_verified',
    ];
    var legacyInternalBases = [
      'legacy_same_index_raw_metadata_incomplete',
      'legacy_same_index_qfq_metadata_incomplete',
      'legacy_same_index_hfq_metadata_incomplete',
    ];
    var result = reviewRegistryMetricNumber(value.return_pct);
    var base = reviewRegistryMetricNumber(value.base_price);
    var endpoint = reviewRegistryMetricNumber(value.endpoint_price);
    if (value.matured !== true || base === null || base <= 0
        || endpoint === null || endpoint <= 0 || result === null) return null;
    if (verifiedStatuses.indexOf(status) !== -1
        && verifiedBases.indexOf(basis) !== -1) {
      return { kind: 'verified', value: result };
    }
    if (status === 'calculated_legacy_internal'
        && legacyInternalBases.indexOf(basis) !== -1) {
      return { kind: 'internal', value: result };
    }
    return null;
  }

  function reviewRegistryHorizonKind(horizon) {
    var value = horizon && typeof horizon === 'object' ? horizon : {};
    var status = normalizeString(value.status).trim();
    var metric = reviewRegistryHorizonMetric(value);
    if (metric) return metric.kind === 'internal' ? 'internal' : 'calculable';
    if (status === 'missing') return 'missing';
    if (status === 'pending') return 'pending';
    return 'unknown';
  }

  function reviewRegistryHorizonStatus(horizon) {
    var value = horizon && typeof horizon === 'object' ? horizon : {};
    var status = normalizeString(value.status).trim();
    var metric = reviewRegistryHorizonMetric(value);
    if (metric && metric.kind === 'internal') return '价格变化（内部口径）';
    if (metric) return '可计算';
    if (status === 'missing') return '缺价';
    if (status === 'pending') return '待到期';
    if (status === 'maturity_unknown') return '交易日历未知';
    if (status === 'identity_conflict') return '证券身份冲突，不计收益';
    if (status === 'invalid_price') return '价格异常，不计收益';
    if (status === 'price_basis_unverified') return '价基未核验，不计收益';
    if ([
      'calculated', 'calculated_verified', 'calculated_internal',
      'calculated_legacy_internal',
    ].indexOf(status) !== -1) {
      return '价基元数据未完整，仅保留原值';
    }
    return status
      ? '状态原值 ' + status + '（未识别，不计收益）'
      : '状态未登记，不计收益';
  }

  function reviewRegistrySourceStatus(value) {
    var status = normalizeString(value).trim();
    var labels = {
      formal_eligible: '正式样本可追溯',
      review_only: '仅复盘',
      incident_excluded: '事故排除',
      formal_input_blocked: '正式输入阻断',
    };
    return labels[status] || (status ? '状态原值 ' + status : '状态未登记');
  }

  function reviewRegistryExecutionStatus(value) {
    var status = normalizeString(value).trim();
    var labels = {
      waiting: '等待条件',
      ready: '条件完整',
      executable: '可执行',
      blocked: '不可执行',
      unavailable: '不可用',
    };
    if (!status) return '该快照执行状态未登记';
    return labels[status]
      ? '该快照执行状态 ' + labels[status] + '（原值 ' + status + '）'
      : '该快照执行状态原值 ' + status + '（未识别）';
  }

  function reviewRegistryPageStatus(value) {
    var status = normalizeString(value).trim();
    var labels = {
      formal_ready: '正式条件完整',
      formal_incomplete: '正式待确认',
      strategy_disagreement: '正式策略分歧',
      evidence_blocked: '暂无法判断',
      invalidated: '已失效',
      waiting_trigger: '等待触发',
      watch_only: '研究观察',
    };
    if (!status) return '页面状态未登记';
    return labels[status]
      ? '页面状态 ' + labels[status] + '（原值 ' + status + '）'
      : '页面状态原值 ' + status + '（未识别）';
  }

  function reviewRegistryCoverageText(entry) {
    var value = entry && typeof entry === 'object' ? entry : {};
    var coverage = normalizeString(value.coverage_status).trim();
    var snapshotKind = normalizeString(value.snapshot_kind).trim();
    if (coverage === 'confirmed_display_snapshot') return '';
    if (coverage === 'unconfirmed_legacy_workspace'
        || snapshotKind === 'legacy_workspace_fallback') {
      return '旧视图口径，覆盖未确认';
    }
    if (coverage === 'unconfirmed_report_identity'
        || snapshotKind === 'postprocessed_html_bootstrap'
        || snapshotKind === 'mixed_same_day_snapshots') {
      return '另版展示快照，报告身份待核验';
    }
    if (coverage) return '覆盖状态原值 ' + coverage + '（未识别）';
    return snapshotKind
      ? '覆盖状态未登记（快照类型原值 ' + snapshotKind + '）'
      : '覆盖状态未登记';
  }

  function reviewRegistryCounts(entries) {
    var counts = {
      registered: asArray(entries).length,
      matured: 0,
      calculable: 0,
      internal: 0,
      missing: 0,
      pending: 0,
      unknown: 0,
    };
    asArray(entries).forEach(function (entry) {
      var horizons = entry && typeof entry.horizons === 'object' ? entry.horizons : {};
      ['T+1', 'T+3', 'T+5'].forEach(function (key) {
        var horizon = horizons[key] && typeof horizons[key] === 'object'
          ? horizons[key] : {};
        if (horizon.matured === true) counts.matured += 1;
        var kind = reviewRegistryHorizonKind(horizon);
        if (kind === 'internal') {
          counts.internal += 1;
          counts.calculable += 1;
        } else {
          counts[kind] += 1;
        }
      });
    });
    return counts;
  }

  function renderReviewRegistrySource(source) {
    var value = source && typeof source === 'object' ? source : {};
    var roleKey = normalizeString(value.role).trim();
    var role = { formal: '正式', research: '研究', baseline: '基础' }[roleKey]
      || roleKey || '角色未登记';
    var view = normalizeString(value.view).trim();
    var rank = reviewRegistryNumber(value.rank);
    var score = reviewRegistryNumber(value.score);
    var versions = [];
    if (normalizeString(value.strategy_version).trim()) {
      versions.push('策略版本 ' + normalizeString(value.strategy_version).trim());
    }
    if (normalizeString(value.decision_version).trim()) {
      versions.push('决策版本 ' + normalizeString(value.decision_version).trim());
    }
    if (normalizeString(value.policy_version).trim()) {
      versions.push('政策版本 ' + normalizeString(value.policy_version).trim());
    }
    if (!versions.length) versions.push('版本未登记');
    return '<li class="review-registry-source"><strong>'
      + escapeHtml(view ? comparisonViewLabel(view) : '来源未登记')
      + ' · ' + escapeHtml(role) + ' · 原名次 ' + escapeHtml(rank === null ? '--' : '#' + rank)
      + '</strong><span>原动作 ' + escapeHtml(normalizeString(value.action).trim() || '未登记')
      + ' · 原分 ' + escapeHtml(score === null ? '--' : formatNumber(score, 0))
      + ' · ' + escapeHtml(versions.join(' · '))
      + ' · ' + escapeHtml(reviewRegistrySourceStatus(value.formal_performance_status))
      + '</span>'
      + (roleKey === 'research' ? '<small class="review-registry-rank-note">'
        + '研究阅读顺序，不代表次日收益排名</small>' : '')
      + '</li>';
  }

  function renderReviewRegistryHorizon(key, horizon) {
    var value = horizon && typeof horizon === 'object' ? horizon : {};
    var metric = reviewRegistryHorizonMetric(value);
    var base = reviewRegistryNumber(value.base_price);
    var endpoint = reviewRegistryNumber(value.endpoint_price);
    var target = normalizeString(value.target_trading_date).trim();
    return '<article class="review-registry-horizon is-'
      + escapeHtml(reviewRegistryHorizonKind(value)) + '">'
      + '<header><strong>' + escapeHtml(key) + '</strong><span>'
      + escapeHtml(reviewRegistryHorizonStatus(value)) + '</span></header>'
      + '<p>' + escapeHtml(target ? '目标日 ' + target : '目标日未确定') + '</p>'
      + '<p>源值 ' + escapeHtml(base === null ? '--' : formatNumber(base, 2))
      + ' → ' + escapeHtml(endpoint === null ? '--' : formatNumber(endpoint, 2)) + '</p>'
      + (!metric ? '' : '<strong class="'
        + (metric.kind === 'internal'
          ? 'review-registry-internal-change' : 'review-registry-return') + '">'
        + escapeHtml(formatPct(metric.value, true)) + '</strong>')
      + (metric && metric.kind === 'internal'
        ? '<p class="review-registry-basis-note">价基元数据未完整；不等于策略/成交收益</p>' : '')
      + '</article>';
  }

  function renderReviewRegistryEntry(entry) {
    var value = entry && typeof entry === 'object' ? entry : {};
    var occurrence = reviewRegistryNumber(value.occurrence_in_window);
    var occurrenceText = occurrence === null
      ? '窗口出现次数未登记'
      : '窗口第' + formatNumber(occurrence, 0) + '次（非首次信号）';
    var firstSeen = normalizeString(value.first_seen_in_window).trim();
    var risks = asArray(value.risk_flags).map(normalizeString).filter(Boolean);
    var reportDate = normalizeString(value.report_date).trim();
    var coverageText = reviewRegistryCoverageText(value);
    var horizons = value.horizons && typeof value.horizons === 'object'
      ? value.horizons : {};
    return '<details class="review-registry-entry" data-review-code="'
      + escapeHtml(normalizeString(value.code).trim()) + '"><summary><span><strong>'
      + escapeHtml(normalizeString(value.name).trim() || normalizeString(value.code).trim() || '未命名')
      + '</strong><small>' + escapeHtml(normalizeString(value.code).trim())
      + '</small></span><span>' + escapeHtml(occurrenceText) + '</span></summary>'
      + '<div class="review-registry-entry-body">'
      + '<p class="review-registry-state">'
      + escapeHtml(reportDate ? '源报告日 ' + reportDate : '源报告日未登记')
      + ' · ' + escapeHtml(reviewRegistryExecutionStatus(value.current_execution_status))
      + ' · ' + escapeHtml(reviewRegistryPageStatus(value.current_page_status))
      + (firstSeen ? ' · 窗口内首次登记 ' + escapeHtml(firstSeen) : '') + '</p>'
      + (coverageText ? '<p class="review-registry-coverage">'
        + escapeHtml(coverageText) + '</p>' : '')
      + '<p class="review-registry-risk">'
      + escapeHtml(risks.length ? '已有风险：' + risks.join('、') : '风险未登记') + '</p>'
      + '<ul class="review-registry-sources">'
      + (asArray(value.sources).length
        ? asArray(value.sources).map(renderReviewRegistrySource).join('')
        : '<li class="review-registry-source"><strong>来源未登记</strong></li>')
      + '</ul><div class="review-registry-horizons">'
      + ['T+1', 'T+3', 'T+5'].map(function (key) {
        return renderReviewRegistryHorizon(key, horizons[key]);
      }).join('') + '</div></div></details>';
  }

  function renderReviewRegistry(index, sourceDate) {
    var registry = getReviewRegistry(index);
    var latestDate = normalizeString(index && index.latest_date).trim();
    if (!registry) {
      return '<section class="comparison-review-registry is-unavailable"><header><div>'
        + '<p class="comparison-eyebrow">只读登记</p><h2>展示对象复盘</h2></div>'
        + (latestDate ? '<small>当前索引覆盖截至 ' + escapeHtml(latestDate) + '</small>' : '')
        + '</header><p>展示对象登记暂未提供；原正式/研究比较仍可使用。</p></section>';
    }
    var windowStart = normalizeString(registry.window_start).trim();
    var windowEnd = normalizeString(registry.window_end).trim();
    var priceCutoff = normalizeString(registry.price_data_cutoff).trim();
    var registryStatus = normalizeString(registry.status).trim();
    if (registryStatus === 'unavailable') {
      var unavailableReasonCode = normalizeString(registry.unavailable_reason).trim();
      var unavailableReason = unavailableReasonCode === 'review_task_failed'
        ? '复盘任务失败（原值 review_task_failed）'
        : (unavailableReasonCode
          ? '暂不可用原因原值 ' + unavailableReasonCode + '（未识别）'
          : normalizeString(registry.reason || registry.status_reason).trim());
      return '<section class="comparison-review-registry is-unavailable"><header><div>'
        + '<p class="comparison-eyebrow">只读登记</p><h2>展示对象复盘暂不可用</h2>'
        + '<p>复盘模块状态原值 unavailable，不记为 0 个对象。</p></div>'
        + '<small>登记覆盖截至 ' + escapeHtml(windowEnd || '未提供') + '</small></header>'
        + '<div class="review-registry-meta"><span>登记窗口 '
        + escapeHtml(windowStart || '未提供') + ' — ' + escapeHtml(windowEnd || '未提供')
        + '</span><span>价格数据截止 ' + escapeHtml(priceCutoff || '未提供')
        + '</span><span>当前索引覆盖截至 ' + escapeHtml(latestDate || '未提供') + '</span></div>'
        + '<p>' + escapeHtml(unavailableReason || '暂未提供原因')
        + '；原正式/研究比较仍可使用。</p></section>';
    }
    var entries = asArray(registry.entries).filter(function (entry) {
      return normalizeString(entry && entry.report_date).trim() === normalizeString(sourceDate).trim();
    });
    var counts = reviewRegistryCounts(entries);
    var confirmedCoverageCount = entries.filter(function (entry) {
      return normalizeString(entry && entry.coverage_status).trim()
        === 'confirmed_display_snapshot';
    }).length;
    var countItems = [
      ['登记对象', counts.registered],
      ['已到期端点', counts.matured],
      ['可计算端点（含内部诊断）', counts.calculable],
      ['内部诊断端点', counts.internal],
      ['缺价端点', counts.missing],
      ['待到期端点', counts.pending],
      ['未知/不兼容', counts.unknown],
    ];
    var empty = entries.length ? '' : '<p class="review-registry-empty">该源报告日没有登记对象；登记覆盖截至 '
      + escapeHtml(windowEnd || '未提供') + '。</p>';
    return '<section class="comparison-review-registry"><header><div>'
      + '<p class="comparison-eyebrow">只读登记</p><h2>展示对象复盘</h2>'
      + '<p>原分仅作来源追溯，不代表当前可执行分或胜率。</p></div>'
      + '<small>登记覆盖截至 ' + escapeHtml(windowEnd || '未提供') + '</small></header>'
      + '<div class="review-registry-meta"><span>登记窗口 '
      + escapeHtml(windowStart || '未提供') + ' — ' + escapeHtml(windowEnd || '未提供')
      + '</span><span>价格数据截止 ' + escapeHtml(priceCutoff || '未提供')
      + '</span><span>当前索引覆盖截至 ' + escapeHtml(latestDate || '未提供') + '</span></div>'
      + '<div class="review-registry-counts">' + countItems.map(function (item) {
        return '<span>' + escapeHtml(item[0]) + '</span><strong>' + escapeHtml(String(item[1])) + '</strong>';
      }).join('') + '</div>'
      + '<p class="review-registry-boundary">正式与研究来源逐条追溯，不跨角色/版本合并收益；缺价、待到期和未知状态保留在登记中。</p>'
      + '<p class="review-registry-boundary">覆盖已确认 ' + escapeHtml(String(confirmedCoverageCount))
      + ' · 覆盖待核验 ' + escapeHtml(String(entries.length - confirmedCoverageCount)) + '</p>'
      + empty
      + (entries.length ? '<details class="review-registry-list"><summary>完整登记（'
        + escapeHtml(String(entries.length)) + '）</summary><div>'
        + entries.map(renderReviewRegistryEntry).join('') + '</div></details>' : '')
      + '</section>';
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
      + '</section><div id="comparisonReviewRegistry"></div><div id="comparisonContent"></div>';

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
      root.querySelector('#comparisonReviewRegistry').innerHTML = renderReviewRegistry(index, sourceDate);
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
      var sourceDate = root.querySelector('#comparisonSource').value;
      root.querySelector('#comparisonReviewRegistry').innerHTML = renderReviewRegistry(index, sourceDate);
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
