(function () {
  'use strict';

  var DEFAULT_VIEW_ORDER = ['main', 'highlights', 'h4_t3', 'observation_top5', 'acceleration', 'luojie', 'confirming', 'growth_quality', 'baseline'];
  var DEFAULT_VIEW_LABELS = {
    highlights: '看点 Top10',
    main: '主推',
    h4_t3: 'H4 T+3',
    observation_top5: '观察 Top5',
    acceleration: '加速',
    luojie: '罗姐池',
    confirming: '等确认',
    growth_quality: '高弹性观察 Top10',
    baseline: '基准',
  };
  var DEFAULT_VIEW_DESCRIPTIONS = {
    highlights: '看点 Top10：跨池混合优先观察榜。用于快速扫今天最值得看的标的，不等于全部可立即买入；请结合身份标签、共振标签和操作状态判断。',
    main: '主推：融合推荐池，可执行优先。来自纯净缠论结构 + 30min 确认 + 市场状态 / MA 多头 / admission 门槛过滤。',
    h4_t3: 'H4 T+3 生产池：展示全部过门候选，按现有统一分排序，可空选、不回填。',
    observation_top5: '观察 Top5：近失样本观察榜，不计入主推荐；显示失败门、升级条件和取消条件。',
    acceleration: '加速：强市场下的情绪加速榜。用于从强势启动类候选中二次排序，不是常规主推荐池。',
    luojie: '罗姐池：硬方向 + 15min 生命线观察，不等同于主推。',
    confirming: '等确认：日线已有启动线索，但等待 30min 或次日确认，观察为主，不直接追高。',
    growth_quality: '高弹性观察 Top10：仅展示有真实行业归属与完整交易证据的观察标的，非正式推荐；同一行业最多两只。',
    baseline: '基准：纯净缠论结构参考池，用于看原始结构信号和主推来源参考。',
  };
  var CHART_EMPTY_TEXT = '暂无图表数据，但保留推荐原因和来源。请检查原始池子数据或 K 线数据。';
  var TOP10_POLL_INTERVAL_MS = 2200;
  var TOP10_MAX_POLL_ATTEMPTS = 52;

  var state = {
    data: null,
    workspace: null,
    currentView: 'main',
    activeItem: null,
    isMobile: false,
    chartInstance: null,
    chartMount: null,
    sentimentChartInstance: null,
    rawPoolCandidates: null,
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
    top10Shell: null,
    top10RunButton: null,
    top10Status: null,
    top10Result: null,
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

  function getCandidateChangePctFromRecord(rec) {
    var record = rec || {};
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

  function getRiskClass(risk) {
    var label = normalizeString(risk);
    if (label.indexOf('过热') !== -1) return 'tag tag-risk is-hot';
    if (label.indexOf('过期') !== -1) return 'tag tag-risk is-expiry';
    return 'tag tag-risk';
  }

  function getDecisionTone(decision) {
    var label = normalizeString(decision && decision.decision ? decision.decision : '');
    var code = normalizeString(decision && decision.decision_code ? decision.decision_code : '');
    if (label.indexOf('推荐') !== -1 || code === 'recommend') return 'is-recommend';
    if (label.indexOf('不推荐') !== -1 || code === 'reject') return 'is-reject';
    return 'is-observe';
  }

  function resolveDecisionEngine(item, raw) {
    if (raw && raw.decision_engine_v1) return raw.decision_engine_v1;
    if (item && item.decision_engine_v1) return item.decision_engine_v1;
    return null;
  }

  function getDecisionScore(decision) {
    var score = safeNumber(decision && decision.total_score, null);
    if (score === null) score = safeNumber(decision && decision.score, null);
    if (score === null) score = safeNumber(decision && decision.final_score, null);
    if (score === null) score = safeNumber(decision && decision.opportunity_score, null);
    return score;
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
      + '  <span class="decision-badge-label">' + escapeHtml(label) + '</span>'
      + (score === null ? '' : '<span class="decision-badge-score">决策 ' + escapeHtml(formatNumber(score, 0)) + '</span>')
      + '</span>';
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

  function getTop10ApiBase() {
    return normalizeString(getBootstrap().top10ApiBase);
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
      + '      <span class="top10-cell rank">Rank</span>'
      + '      <span class="top10-cell code">Code</span>'
      + '      <span class="top10-cell name">Name</span>'
      + '      <span class="top10-cell score">Score</span>'
      + '      <span class="top10-cell action">Action</span>'
      + '      <span class="top10-cell reason">Reason</span>'
      + '      <span class="top10-cell generated">Generated</span>'
      + '    </div>'
      + asArray(items).map(function (item, index) {
        var rec = item || {};
        var rank = safeNumber(rec.rank, index + 1);
        if (rank === null || rank === undefined) {
          rank = index + 1;
        }
        var code = normalizeString(rec.code || rec.symbol || '');
        var name = normalizeString(rec.name || '');
        var score = safeNumber(rec.score, safeNumber(rec.opportunity_score, safeNumber(rec.total_score, safeNumber(rec.final_score, 0))));
        var action = normalizeString(rec.action || rec.recommendation || '');
        var reason = normalizeString(rec.reason || rec.notes || rec.note || '');
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
      + '    <section class="top10-widget" id="top10Widget">'
      + '      <div class="top10-widget-head">'
      + '        <span class="top10-widget-title">临时 Top10 快照</span>'
      + '        <button type="button" class="top10-run-btn" id="top10RunButton">生成 Top10</button>'
      + '      </div>'
      + '      <div class="top10-status" id="top10Status">Top10 接口未配置</div>'
      + '      <div class="top10-result" id="top10Result"></div>'
      + '    </section>'
      + '  </header>'
      + '  <section class="workspace">'
      + '    <nav class="workspace-tabs" id="workspaceTabs"></nav>'
      + '    <div class="view-description" id="viewDescription"></div>'
      + '    <div class="workspace-body">'
      + '      <div class="candidate-list-shell">'
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
      + '    <button class="mobile-drawer-floating-close" id="mobileDrawerClose">关闭</button>'
      + '    <div class="mobile-drawer-panel" id="mobileDrawerPanel">'
      + '      <div class="mobile-drawer-toolbar">'
      + '        <span>股票详情</span>'
      + '      </div>'
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
    nodes.top10Shell = app.querySelector('#top10Widget');
    nodes.top10RunButton = app.querySelector('#top10RunButton');
    nodes.top10Status = app.querySelector('#top10Status');
    nodes.top10Result = app.querySelector('#top10Result');
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
    var sentiment = data.market_sentiment || {};
    var sentimentScore = safeNumber(sentiment.score, null);
    var sentimentComponents = sentiment.components || {};
    if (!Number.isFinite(sentimentScore)) {
      return {
        score: null,
        label: '数据不足',
        tone: 'neutral',
        insufficient: true,
        coverage: safeNumber(sentiment.coverage, 0),
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
      coverage: safeNumber(sentiment.coverage, 0),
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

      var sourceLabels = asArray(item.source_labels);
      if (sourceLabels.length === 0 && Array.isArray(item.sources)) {
        sourceLabels = item.sources.map(function (source) {
          return String(source || '');
        });
      }

      var resonance = normalizeString(item.resonance_label || '');
      var action = normalizeString(item.action || '待判定');
      var riskFlags = asArray(item.risk_flags).filter(function (flag) {
        return normalizeString(flag) !== '仅观察';
      });
      var raw = findRawCandidate(item.ref || {});
      var decision = resolveDecisionEngine(item, raw);

      var tagHtml = '';
      tagHtml += renderDecisionBadge(decision);
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
    var currentPrice = getCandidateCurrentPrice(item);
    var refPrice = getCandidateReferencePrice(item);

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
    if (risks.length === 0) {
      risks = ['暂无标记风险标签。'];
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
    var decisionSummary = getDecisionEngineSummary(item, raw);
    if (decisionSummary) {
      details.push('决策评分摘要：' + decisionSummary);
    }
    var opportunityScore = safeNumber(item.opportunity_score, null);
    var watchScore = safeNumber(item.watch_score, null);
    if (opportunityScore !== null) {
      details.push('权重：' + formatNumber(opportunityScore, 0));
    } else if (watchScore !== null) {
      details.push('权重：' + formatNumber(watchScore, 0));
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

    var score = safeNumber(decision.total_score, null);
    if (score === null) {
      score = safeNumber(decision.score, null);
    }
    if (score === null) {
      score = safeNumber(decision.final_score, null);
    }
    if (score === null) {
      score = safeNumber(decision.opportunity_score, null);
    }

    var parts = [];
    if (score !== null) {
      parts.push('评分 ' + formatNumber(score, 1));
    }
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

  function buildChartPlaceholder() {
    return ''
      + '<div class="detail-section">'
      + '  <h3 class="detail-section-title">03 图表</h3>'
      + '  <div class="chart-panel">'
      + '    <div class="chart-help">图钉为买点/信号标记，虚线为参考价和现价；拖动或滚动底部缩放条查看细节。</div>'
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
      + buildDecisionEngineSection(item, raw)
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

    var curPrice = getCandidateCurrentPriceFromRecord(workspaceItem);
    if (curPrice === null && raw && raw !== workspaceItem) {
      curPrice = getCandidateCurrentPriceFromRecord(raw);
    }
    var refPrice = getCandidateReferencePriceFromRecord(workspaceItem);
    if (refPrice === null && raw && raw !== workspaceItem) {
      refPrice = getCandidateReferencePriceFromRecord(raw);
    }
    if (refPrice === null && raw && raw.reference_buy_points && raw.reference_buy_points.length > 0) {
      refPrice = safeNumber(raw.reference_buy_points[0].reference_price, null);
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
      + renderMetricPair('证据覆盖', Math.round((temperature.coverage || 0) * 100) + '%', '')
      + '    </div>'
      + '  </div>'
      + '  <div class="market-temp-trend">'
      + '    <div id="marketSentimentChart" class="market-sentiment-chart" aria-label="最近20个交易日市场情绪折线图"></div>'
      + '  </div>'
      + '</div>';
    return renderDecisionCard({
      title: '市场情绪',
      subtitle: '全A宽度、涨跌停生态、成交与趋势结构',
      badge: { text: temperature.label, tone: temperature.tone },
      className: 'market-temperature-card',
      bodyHtml: body,
    });
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
    var allRows = sectorIn.concat(sectorOut);
    var insufficient = allRows.some(function (item) {
      return item && item.hierarchy_dedup_status === 'insufficient_evidence';
    });
    var partial = allRows.some(function (item) {
      return item && item.hierarchy_dedup_status === 'partial_check_only';
    });
    var hierarchyText = insufficient || partial ? '层级证据部分不足' : '层级已去重';
    var inHtml = sectorIn.length ? sectorIn.map(function (item) { return renderFlowRow('流入', item); }).join('') : '<div class="decision-empty">暂无流入数据</div>';
    var outHtml = sectorOut.length ? sectorOut.map(function (item) { return renderFlowRow('流出', item); }).join('') : '<div class="decision-empty">暂无流出数据</div>';
    var body = ''
      + '<div class="flow-columns">'
      + '  <div><div class="mini-section-title">流入 Top5</div>' + inHtml + '</div>'
      + '  <div><div class="mini-section-title">流出 Top5</div>' + outHtml + '</div>'
      + '</div>';
    return renderDecisionCard({
      title: '板块资金',
      subtitle: '资金流入与流出方向 · ' + hierarchyText,
      badge: { text: sectorIn.length || sectorOut.length ? hierarchyText : '暂无', tone: insufficient || partial ? 'warning' : (sectorIn.length ? 'positive' : 'neutral') },
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
    var rows = asArray((data || {}).recent_reviews);
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
    if (rows.length) {
      body = '<div class="review-list">' + body + '</div>';
    }
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
    setTimeout(renderMarketSentimentChart, 0);
  }

  function openMobileDetailDrawer(item) {
    if (!state.isMobile || !nodes.drawer) return;
    if (item) {
      state.activeItem = item;
    }
    if (!state.activeItem) return;
    syncMobileDrawerViewport();
    nodes.drawerContent.innerHTML = '';
    renderCandidateDetail(state.activeItem, nodes.drawerContent);
    nodes.drawer.classList.add('is-open');
    document.body.style.overflow = 'hidden';
    if (nodes.drawerPanel) {
      nodes.drawerPanel.scrollTop = 0;
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
      renderWorkspaceTabs();
      renderViewDescription();
      renderCandidateList();
      var first = getCurrentViewItems()[0] || null;
      renderCandidateDetail(first);
      state.activeItem = first;
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
    if (view === 'all') return '全部榜单（去重）';
    return DEFAULT_VIEW_LABELS[view] || normalizeString(view);
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

  function dedupeComparisonRows(rows) {
    var seen = {};
    return rows.filter(function (row) {
      var code = normalizeString(row && row.item && row.item.code);
      if (!code || seen[code]) return false;
      seen[code] = true;
      return true;
    });
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
    var summaries = Object.keys(views).map(function (view) {
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
    var allRows = dedupeComparisonRows([].concat.apply([], summaries.map(function (summary) { return summary.rows; })));
    summaries.unshift(comparisonSummary('all', allRows));
    var chartSummaries = summaries.filter(function (summary) { return summary.view !== 'all'; });
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
        return '<button class="comparison-view-card" data-comparison-view="' + escapeHtml(summary.view) + '"><span>' + escapeHtml(comparisonViewLabel(summary.view)) + '</span><strong class="' + tone + '">' + formatPct(summary.average, true) + '</strong><small>中位数 ' + formatPct(summary.median, true) + ' · 上涨率 ' + formatPct(summary.winRate) + ' · 有效 ' + summary.evaluable + ' / 缺失 ' + summary.missing + '</small></button>';
      }).join('') + '</aside><section class="comparison-detail"><div id="comparisonDetail"></div></section></section>';
    var buttons = mount.querySelectorAll('[data-comparison-view]');
    var sortState = { key: 'rank', direction: 'asc' };
    function showDetail(view) {
      var summary = summaries.filter(function (entry) { return entry.view === view; })[0] || summaries[0];
      if (!summary) { mount.querySelector('#comparisonDetail').innerHTML = '<div class="comparison-empty">源报告日没有可比对的榜单。</div>'; return; }
      Array.prototype.forEach.call(buttons, function (button) { button.classList.toggle('is-active', button.getAttribute('data-comparison-view') === summary.view); });
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
    section.innerHTML = '<header><div><h2>昨日榜单表现</h2><p>实际涨跌为主，沪深300与超额收益为辅助。</p></div><a href="' + (isArchiveReportPath(window.location.pathname) ? '../compare/' : 'compare/') + '">进入完整比对</a></header><div class="comparison-summary-body">正在读取历史报告索引…</div>';
    nodes.shell.insertBefore(section, auxCenter || null);
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
    var summaries = Object.keys(report.views || {}).map(function (view) {
      var rows = asArray(report.views[view]).map(function (item) {
        var actual = comparisonReturn(report.prices && report.prices[item.code], quoteMap[item.code]);
        return { item: item, actual: actual };
      });
      return comparisonSummary(view, rows);
    });
    var allRows = dedupeComparisonRows([].concat.apply([], summaries.map(function (summary) { return summary.rows; })));
    summaries.unshift(comparisonSummary('all', allRows));
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
