const DEFAULT_LOCK_TTL_SECONDS = 600;
const DEFAULT_JOB_TIMEOUT_SECONDS = 600;
const MAX_QUOTE_CODES = 200;
const QUOTE_BATCH_SIZE = 100;
const EASTMONEY_QUOTE_URL = "https://push2.eastmoney.com/api/qt/ulist.np/get";
const TENCENT_QUOTE_URL = "https://qt.gtimg.cn/q=";
const ASHARE_CODE_PATTERN = /^(?:6\d{5}|(?:000|001|002|003|300|301)\d{3}|[48]\d{5}|92\d{4})$/;
const WATCHLIST_KEY = "decision:watchlist:current";
const WATCHLIST_MAX_ITEMS = 20;
const WATCHLIST_ROLES = new Set(["strong_watch", "watch", "research", "risk_watch"]);
const DEFAULT_DECISION_WATCHLIST = {
  schema_version: "1",
  revision: "watchlist-20260820-01",
  updated_at: "2026-08-20T16:00:00+08:00",
  updated_by: "user",
  items: [
    { code: "300139", note: "晓程科技", role: "strong_watch", enabled: true, priority: 1, tags: ["用户重点观察", "黄金科技"], thesis: "跟踪贵金属、芯片设计与公司自身催化是否形成盘面共振。" },
    { code: "002281", note: "光迅科技", role: "strong_watch", enabled: true, priority: 2, tags: ["用户重点观察", "光通信"], thesis: "跟踪光模块与通信设备方向的事件、板块资金和个股结构共振。" },
    { code: "300308", note: "中际旭创", role: "strong_watch", enabled: true, priority: 3, tags: ["用户重点观察", "光通信"], thesis: "跟踪海外算力和高速光模块催化能否被板块与个股强度确认。" },
    { code: "688041", note: "海光信息", role: "strong_watch", enabled: true, priority: 4, tags: ["用户重点观察", "国产算力"], thesis: "跟踪国产算力、服务器和先进计算产业链的持续性与结构位置。" },
    { code: "688525", note: "佰维存储", role: "strong_watch", enabled: true, priority: 5, tags: ["用户重点观察", "存储"], thesis: "跟踪存储涨价、端侧 AI 和半导体资金方向能否形成有效共振。" },
  ],
};

function parseAllowedOrigins(rawOrigins) {
  if (!rawOrigins) {
    return ["*"];
  }

  const list = rawOrigins
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);

  return list.length > 0 ? list : ["*"];
}

function getCorsOrigin(requestOrigin, env) {
  const allowed = parseAllowedOrigins(env?.ALLOWED_ORIGINS);

  if (allowed.includes("*")) {
    return "*";
  }

  if (!requestOrigin) {
    return null;
  }

  return allowed.includes(requestOrigin) ? requestOrigin : null;
}

function makeCorsHeaders(requestOrigin, env, extra = {}) {
  const headers = {
    "Access-Control-Allow-Methods": "GET,POST,PUT,OPTIONS",
    "Access-Control-Allow-Headers": "authorization,content-type,if-match,x-callback-token",
    "Access-Control-Expose-Headers": "ETag",
    "Access-Control-Max-Age": "86400",
    ...extra,
  };
  const origin = getCorsOrigin(requestOrigin, env);
  if (origin) {
    headers["Access-Control-Allow-Origin"] = origin;
    if (origin !== "*") {
      headers["Access-Control-Allow-Credentials"] = "true";
    }
  }
  return headers;
}

function jsonResponse(status, body, requestOrigin, env, extraHeaders = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      ...makeCorsHeaders(requestOrigin, env, extraHeaders),
    },
  });
}

function nowMs() {
  return Date.now();
}

function parseJsonBody(request) {
  return request
    .json()
    .catch(() => ({}))
    .then((body) => body || {});
}

function parseJson(raw, fallback = null) {
  if (raw == null) {
    return fallback;
  }

  if (typeof raw === "object") {
    return raw;
  }

  if (typeof raw !== "string") {
    return fallback;
  }

  try {
    return JSON.parse(raw);
  } catch {
    return fallback;
  }
}

function normalizeQuoteCodes(codes) {
  if (!Array.isArray(codes) || codes.length === 0) {
    return { error: "codes must be a non-empty array" };
  }

  const normalized = [];
  const invalidCodes = [];
  for (const value of codes) {
    const code = typeof value === "string" ? value.trim() : "";
    if (!ASHARE_CODE_PATTERN.test(code)) {
      invalidCodes.push(value);
    } else if (!normalized.includes(code)) {
      normalized.push(code);
    }
  }

  if (invalidCodes.length > 0) {
    return { error: "invalid stock codes", invalid_codes: invalidCodes };
  }
  if (normalized.length > MAX_QUOTE_CODES) {
    return { error: `too many codes (maximum ${MAX_QUOTE_CODES})` };
  }
  return { codes: normalized };
}

function quoteSecId(code) {
  return `${code.startsWith("6") ? "1" : "0"}.${code}`;
}

function quoteUrl(codes, fixedSecIds = null) {
  const params = new URLSearchParams({
    fltt: "2",
    fields: "f12,f2",
    secids: (fixedSecIds || codes.map(quoteSecId)).join(","),
  });
  return `${EASTMONEY_QUOTE_URL}?${params}`;
}

function parseQuotePrice(value) {
  if (typeof value === "number") {
    return Number.isFinite(value) ? value : null;
  }
  if (typeof value !== "string") {
    return null;
  }
  const text = value.trim();
  if (!text || text === "-") {
    return null;
  }
  const parsed = Number(text);
  return Number.isFinite(parsed) ? parsed : null;
}

async function fetchQuoteBatch(codes, fixedSecIds = null) {
  try {
    const response = await fetch(quoteUrl(codes, fixedSecIds));
    if (!response.ok) {
      throw new Error(`upstream status ${response.status}`);
    }
    const payload = await response.json();
    const rows = Array.isArray(payload?.data?.diff) ? payload.data.diff : [];
    const prices = new Map();
    for (const row of rows) {
      const code = typeof row?.f12 === "string" ? row.f12 : String(row?.f12 || "");
      const price = parseQuotePrice(row?.f2);
      if (/^\d{6}$/.test(code) && price !== null) {
        prices.set(code, price);
      }
    }
    return { prices };
  } catch {
    return { error: true };
  }
}

function tencentQuoteSymbol(code) {
  if (code.startsWith("6")) return `sh${code}`;
  if (/^(?:[48]|92)/.test(code)) return `bj${code}`;
  return `sz${code}`;
}

function parseTencentQuotes(raw) {
  const prices = new Map();
  for (const match of String(raw || "").matchAll(/v_(?:sh|sz|bj)(\d{6})="([^"]*)"/g)) {
    const price = parseQuotePrice(match[2].split("~")[3]);
    if (price !== null) prices.set(match[1], price);
  }
  return prices;
}

async function fetchTencentQuoteBatch(codes, fixedSymbols = null) {
  try {
    const symbols = fixedSymbols || codes.map(tencentQuoteSymbol);
    const response = await fetch(`${TENCENT_QUOTE_URL}${symbols.join(",")}`, {
      headers: { Referer: "https://gu.qq.com/" },
    });
    if (!response.ok) throw new Error(`upstream status ${response.status}`);
    return { prices: parseTencentQuotes(await response.text()) };
  } catch {
    return { error: true };
  }
}

async function fetchQuoteBatchWithFallback(codes, fixedSecIds = null, fixedTencentSymbols = null) {
  const primary = await fetchQuoteBatch(codes, fixedSecIds);
  if (!primary.error) return primary;
  return fetchTencentQuoteBatch(codes, fixedTencentSymbols);
}

function batches(items, size) {
  const result = [];
  for (let index = 0; index < items.length; index += size) {
    result.push(items.slice(index, index + size));
  }
  return result;
}

async function handleCurrentQuotes(request, env, requestOrigin) {
  const body = await parseJsonBody(request);
  const normalized = normalizeQuoteCodes(body?.codes);
  if (normalized.error) {
    return jsonResponse(400, normalized, requestOrigin, env);
  }

  const stockBatches = batches(normalized.codes, QUOTE_BATCH_SIZE);
  const stockResults = await Promise.all(stockBatches.map((batch) => fetchQuoteBatchWithFallback(batch)));
  const benchmarkResult = await fetchQuoteBatchWithFallback(["000300"], ["1.000300"], ["sh000300"]);
  const batchResultByCode = new Map();
  stockBatches.forEach((batch, index) => {
    batch.forEach((code) => batchResultByCode.set(code, stockResults[index]));
  });
  const allStockBatchesFailed = stockResults.every((result) => result.error);
  const benchmarkFailed = Boolean(benchmarkResult.error);

  if (allStockBatchesFailed && benchmarkFailed) {
    return jsonResponse(502, { error: "quote upstream unavailable" }, requestOrigin, env);
  }

  const items = normalized.codes.map((code) => {
    const batchResult = batchResultByCode.get(code);
    const price = batchResult?.prices?.get(code);
    if (price !== undefined) {
      return { code, current_price: price, status: "ok" };
    }
    return { code, current_price: null, status: batchResult?.error ? "upstream_error" : "not_found" };
  });
  const benchmarkPrice = benchmarkResult.prices?.get("000300");
  const benchmark = benchmarkPrice !== undefined
    ? { code: "000300", current_price: benchmarkPrice, status: "ok" }
    : { code: "000300", current_price: null, status: benchmarkFailed ? "upstream_error" : "not_found" };
  const hasFailures = items.some((item) => item.status !== "ok") || benchmark.status !== "ok";

  return jsonResponse(200, {
    status: hasFailures ? "partial" : "ok",
    quotes: items,
    items,
    benchmark,
    quoted_at: new Date().toISOString(),
  }, requestOrigin, env);
}

function sanitizeToken(value) {
  return typeof value === "string" ? value.trim() : "";
}

function sanitizeDate(value) {
  const text = sanitizeToken(value);
  return /^\d{4}-\d{2}-\d{2}$/.test(text) ? text : "";
}

function watchlistEtag(revision) {
  return `"${sanitizeToken(revision)}"`;
}

function cloneDefaultWatchlist() {
  return JSON.parse(JSON.stringify(DEFAULT_DECISION_WATCHLIST));
}

async function loadDecisionWatchlist(storage) {
  const raw = await storage.get(WATCHLIST_KEY);
  if (!raw) return cloneDefaultWatchlist();
  const current = typeof raw === "string" ? parseJson(raw, null) : raw;
  if (!current || !sanitizeToken(current.revision) || !Array.isArray(current.items)) {
    throw new Error("invalid watchlist state");
  }
  return current;
}

function limitedText(value, maximum, fallback = "") {
  const text = typeof value === "string" ? value.trim() : fallback;
  return text.slice(0, maximum);
}

function normalizeWatchlistItems(items) {
  if (!Array.isArray(items)) return { error: "watchlist items must be an array" };
  if (items.length > WATCHLIST_MAX_ITEMS) {
    return { error: `watchlist maximum is ${WATCHLIST_MAX_ITEMS} items` };
  }
  const seen = new Set();
  const normalized = [];
  for (let index = 0; index < items.length; index += 1) {
    const source = items[index];
    if (!source || typeof source !== "object" || Array.isArray(source)) {
      return { error: "invalid watchlist item", index };
    }
    const code = sanitizeToken(source.code);
    const role = sanitizeToken(source.role || "strong_watch");
    if (!ASHARE_CODE_PATTERN.test(code)) {
      return { error: "invalid watchlist stock code", index, code };
    }
    if (seen.has(code)) {
      return { error: "duplicate watchlist stock code", index, code };
    }
    if (!WATCHLIST_ROLES.has(role)) {
      return { error: "invalid watchlist role", index, role };
    }
    seen.add(code);
    const tags = Array.isArray(source.tags)
      ? source.tags.map((tag) => limitedText(tag, 20)).filter(Boolean).slice(0, 5)
      : [];
    normalized.push({
      code,
      note: limitedText(source.note, 24, code) || code,
      role,
      enabled: source.enabled !== false,
      priority: index + 1,
      tags,
      thesis: limitedText(source.thesis, 240),
    });
  }
  return { items: normalized };
}

function watchlistAdminAuthorized(request, env) {
  const expected = sanitizeToken(env.WATCHLIST_ADMIN_PASSWORD);
  const header = sanitizeToken(request.headers.get("authorization"));
  const supplied = header.toLowerCase().startsWith("bearer ")
    ? sanitizeToken(header.slice(7))
    : "";
  return Boolean(expected && supplied && supplied === expected);
}

async function handleDecisionWatchlistGet(storage, env, requestOrigin) {
  try {
    const current = await loadDecisionWatchlist(storage);
    return jsonResponse(200, current, requestOrigin, env, {
      ETag: watchlistEtag(current.revision),
      "Cache-Control": "no-store",
    });
  } catch {
    return jsonResponse(500, { error: "invalid watchlist state" }, requestOrigin, env);
  }
}

async function handleDecisionWatchlistPut(request, state, env, requestOrigin) {
  if (!sanitizeToken(env.WATCHLIST_ADMIN_PASSWORD)) {
    return jsonResponse(503, { error: "watchlist writes are disabled" }, requestOrigin, env);
  }
  if (!watchlistAdminAuthorized(request, env)) {
    return jsonResponse(401, { error: "invalid watchlist credentials" }, requestOrigin, env);
  }
  const ifMatch = sanitizeToken(request.headers.get("if-match"));
  if (!ifMatch) {
    return jsonResponse(428, { error: "If-Match is required" }, requestOrigin, env);
  }
  const body = await parseJsonBody(request);
  const normalized = normalizeWatchlistItems(body?.items);
  if (normalized.error) {
    return jsonResponse(400, normalized, requestOrigin, env);
  }

  let outcome;
  try {
    outcome = await state.storage.transaction(async (txn) => {
      const current = await loadDecisionWatchlist(txn);
      const currentEtag = watchlistEtag(current.revision);
      if (ifMatch !== currentEtag) {
        return { status: "conflict", current, currentEtag };
      }
      const updatedAt = new Date().toISOString();
      const revision = `watchlist-${Date.now()}-${crypto.randomUUID().slice(0, 8)}`;
      const next = {
        schema_version: "1",
        revision,
        updated_at: updatedAt,
        updated_by: "web_admin",
        items: normalized.items,
        analysis_effect: "next_report",
        analysis_message: "配置已保存，等待下次日报分析；当前日报快照不会改变。",
      };
      const audit = {
        revision,
        previous_revision: current.revision,
        updated_at: updatedAt,
        updated_by: "web_admin",
        previous_config: current,
        next_config: next,
      };
      await txn.put(WATCHLIST_KEY, next);
      await txn.put(`decision:watchlist:revision:${current.revision}`, current);
      await txn.put(`decision:watchlist:revision:${revision}`, next);
      await txn.put(`decision:watchlist:audit:${revision}`, audit);
      return { status: "saved", next };
    });
  } catch {
    return jsonResponse(500, { error: "watchlist transaction failed" }, requestOrigin, env);
  }

  if (outcome.status === "conflict") {
    return jsonResponse(412, {
      error: "watchlist revision conflict",
      current: outcome.current,
    }, requestOrigin, env, {
      ETag: outcome.currentEtag,
      "Cache-Control": "no-store",
    });
  }
  return jsonResponse(200, outcome.next, requestOrigin, env, {
    ETag: watchlistEtag(outcome.next.revision),
    "Cache-Control": "no-store",
  });
}

export class DecisionWatchlist {
  constructor(state, env) {
    this.state = state;
    this.env = env;
  }

  async fetch(request) {
    const requestOrigin = request.headers.get("origin");
    if (request.method === "GET") {
      return handleDecisionWatchlistGet(
        this.state.storage,
        this.env,
        requestOrigin,
      );
    }
    if (request.method === "PUT") {
      return handleDecisionWatchlistPut(
        request,
        this.state,
        this.env,
        requestOrigin,
      );
    }
    return jsonResponse(405, { error: "method not allowed" }, requestOrigin, this.env);
  }
}

async function forwardDecisionWatchlist(request, env, requestOrigin) {
  if (!env.DECISION_WATCHLIST) {
    return jsonResponse(503, {
      error: "decision watchlist durable object is not configured",
    }, requestOrigin, env);
  }
  const id = env.DECISION_WATCHLIST.idFromName("global");
  return env.DECISION_WATCHLIST.get(id).fetch(request);
}

function getTimeoutMs(state, env) {
  const configured = Number(
    state?.timeout_seconds ?? env?.TOP10_JOB_TIMEOUT_SECONDS ?? DEFAULT_JOB_TIMEOUT_SECONDS,
  );
  return Number.isFinite(configured) && configured > 0 ? configured * 1000 : DEFAULT_JOB_TIMEOUT_SECONDS * 1000;
}

function shouldTimeoutRunning(state, env) {
  if (state?.status !== "running" && state?.status !== "queued") {
    return false;
  }

  const startedAt = Number(state.updated_at || state.created_at || 0);
  if (!startedAt || !Number.isFinite(startedAt)) {
    return false;
  }

  return nowMs() - startedAt > getTimeoutMs(state, env);
}

async function markJobTimeout(jobId, currentState, env) {
  const timedOut = {
    ...currentState,
    status: "failed",
    reason: "timeout",
    updated_at: nowMs(),
  };

  await env.TOP10_KV.put(`top10:job:${jobId}`, JSON.stringify(timedOut));
  const lock = parseJson(await env.TOP10_KV.get("top10:lock"), null);
  if (lock && lock.job_id === jobId) {
    await env.TOP10_KV.delete("top10:lock");
  }

  return timedOut;
}

async function safeDeleteLockIfOwnsJob(env, jobId) {
  const lock = parseJson(await env.TOP10_KV.get("top10:lock"), null);
  if (lock && lock.job_id === jobId) {
    await env.TOP10_KV.delete("top10:lock");
  }
}

function buildDispatchPayload(env, jobId) {
  return {
    ref: sanitizeToken(env.GITHUB_REF || "main"),
    inputs: { job_id: String(jobId) },
  };
}

function buildDispatchHeaders(token) {
  const authToken = sanitizeToken(token);
  return {
    "User-Agent": "cloudflare-top10-worker",
    "Content-Type": "application/json",
    Authorization: `Bearer ${authToken}`,
    Accept: "application/vnd.github+json",
  };
}

async function dispatchWorkflow(jobId, env) {
  const owner = sanitizeToken(env.GITHUB_OWNER);
  const repo = sanitizeToken(env.GITHUB_REPO);
  const workflowId = sanitizeToken(env.GITHUB_WORKFLOW_ID);
  const token = sanitizeToken(env.GITHUB_TOKEN);

  if (!owner || !repo || !workflowId || !token) {
    throw new Error("Missing GitHub workflow dispatch configuration");
  }

  const url = `https://api.github.com/repos/${owner}/${repo}/actions/workflows/${workflowId}/dispatches`;
  const response = await fetch(url, {
    method: "POST",
    headers: buildDispatchHeaders(token),
    body: JSON.stringify(buildDispatchPayload(env, jobId)),
  });

  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new Error(`GitHub dispatch failed: ${response.status} ${text}`);
  }
}

function createJobState(jobId, env, status = "running") {
  const timeoutSeconds = Number(env?.TOP10_JOB_TIMEOUT_SECONDS || DEFAULT_JOB_TIMEOUT_SECONDS);
  const now = nowMs();
  return {
    job_id: String(jobId),
    status,
    created_at: now,
    updated_at: now,
    timeout_seconds: Number.isFinite(timeoutSeconds) && timeoutSeconds > 0 ? timeoutSeconds : DEFAULT_JOB_TIMEOUT_SECONDS,
  };
}

async function handleRun(request, env, requestOrigin) {
  const body = await parseJsonBody(request);
  const password = sanitizeToken(body?.password);

  if (sanitizeToken(env.TRIGGER_PASSWORD) !== password) {
    return jsonResponse(401, { error: "invalid password" }, requestOrigin, env);
  }

  const lockTtlSeconds = Number(env?.TOP10_LOCK_TTL_SECONDS || DEFAULT_LOCK_TTL_SECONDS);
  const lockTtlMs = Number.isFinite(lockTtlSeconds) && lockTtlSeconds > 0 ? lockTtlSeconds * 1000 : DEFAULT_LOCK_TTL_SECONDS * 1000;

  const lockRaw = await env.TOP10_KV.get("top10:lock");
  const lock = parseJson(lockRaw, null);
  const now = nowMs();

  if (lock && Number(lock?.expires_at || 0) > now) {
    return jsonResponse(
      409,
      {
        error: "job in progress",
        job_id: String(lock.job_id || ""),
        expires_at: lock.expires_at,
      },
      requestOrigin,
      env,
    );
  }

  if (lock && Number(lock?.expires_at || 0) <= now) {
    await env.TOP10_KV.delete("top10:lock");
  }

  const jobId = `${now}`;
  const jobState = createJobState(jobId, env, "running");
  const lockState = {
    job_id: jobId,
    created_at: now,
    expires_at: now + lockTtlMs,
    timeout_seconds: jobState.timeout_seconds,
    status: "locked",
  };

  await Promise.all([
    env.TOP10_KV.put("top10:lock", JSON.stringify(lockState)),
    env.TOP10_KV.put(`top10:job:${jobId}`, JSON.stringify(jobState)),
  ]);

  try {
    await dispatchWorkflow(jobId, env);
  } catch (error) {
    const failedState = {
      ...jobState,
      status: "failed",
      reason: "dispatch_failed",
      updated_at: nowMs(),
      error: String(error?.message || "dispatch failed"),
    };
    await env.TOP10_KV.put(`top10:job:${jobId}`, JSON.stringify(failedState));
    await env.TOP10_KV.delete("top10:lock");
    return jsonResponse(502, { error: "dispatch_failed", details: failedState.error }, requestOrigin, env);
  }

  return jsonResponse(200, { job_id: jobId, status: "queued" }, requestOrigin, env);
}

async function handleStatus(request, env, requestOrigin) {
  const url = new URL(request.url);
  const jobId = sanitizeToken(url.searchParams.get("job_id"));

  if (!jobId) {
    return jsonResponse(400, { error: "missing job_id" }, requestOrigin, env);
  }

  const stateRaw = await env.TOP10_KV.get(`top10:job:${jobId}`);
  if (!stateRaw) {
    return jsonResponse(404, { error: "job not found" }, requestOrigin, env);
  }

  const state = parseJson(stateRaw, null);
  if (!state || typeof state !== "object") {
    return jsonResponse(500, { error: "invalid job state" }, requestOrigin, env);
  }

  if (shouldTimeoutRunning(state, env)) {
    const timedOut = await markJobTimeout(jobId, state, env);
    return jsonResponse(200, timedOut, requestOrigin, env);
  }

  return jsonResponse(200, state, requestOrigin, env);
}

async function handleLatest(request, env, requestOrigin) {
  const url = new URL(request.url);
  const snapshotDate = sanitizeDate(url.searchParams.get("date"));
  const key = snapshotDate ? `top10:latest:${snapshotDate}` : "top10:latest";
  let stateRaw = await env.TOP10_KV.get(key);
  if (!stateRaw && snapshotDate) {
    const fallbackRaw = await env.TOP10_KV.get("top10:latest");
    const fallbackState = parseJson(fallbackRaw, null);
    if (fallbackState && sanitizeDate(fallbackState.snapshot_date) === snapshotDate) {
      stateRaw = JSON.stringify(fallbackState);
    }
  }

  if (!stateRaw) {
    return jsonResponse(404, { error: "latest snapshot not found", snapshot_date: snapshotDate || null }, requestOrigin, env);
  }

  const state = parseJson(stateRaw, null);
  if (!state || typeof state !== "object") {
    return jsonResponse(500, { error: "invalid latest snapshot" }, requestOrigin, env);
  }

  return jsonResponse(200, state, requestOrigin, env);
}

async function handleCallback(request, env, requestOrigin) {
  const callbackToken = sanitizeToken(env.CALLBACK_TOKEN);
  const authHeader = sanitizeToken(request.headers.get("authorization"));
  const xCallbackToken = sanitizeToken(request.headers.get("x-callback-token"));

  let token = "";
  if (authHeader.toLowerCase().startsWith("bearer ")) {
    token = sanitizeToken(authHeader.slice(7));
  } else if (xCallbackToken) {
    token = xCallbackToken;
  }

  if (!callbackToken || token !== callbackToken) {
    return jsonResponse(401, { error: "invalid callback token" }, requestOrigin, env);
  }

  const body = await parseJsonBody(request);
  const jobId = sanitizeToken(body?.job_id);
  if (!jobId) {
    return jsonResponse(400, { error: "missing job_id" }, requestOrigin, env);
  }

  const now = nowMs();
  const result = parseJson(body?.result, null);
  const state = {
    ...(parseJson(body, null) || {}),
    job_id: jobId,
    status: sanitizeToken(body?.status || "done") || "done",
    updated_at: now,
  };
  if (result && typeof result === "object") {
    if (!Array.isArray(state.items) && Array.isArray(result.items)) {
      state.items = result.items;
    }
    if (!state.generated_at && result.generated_at) {
      state.generated_at = result.generated_at;
    }
    if (!state.snapshot_date && result.snapshot_date) {
      state.snapshot_date = result.snapshot_date;
    }
  }

  const writes = [
    env.TOP10_KV.put(`top10:job:${jobId}`, JSON.stringify(state)),
    env.TOP10_KV.put("top10:latest", JSON.stringify(state)),
  ];
  const snapshotDate = sanitizeDate(state.snapshot_date);
  if (snapshotDate) {
    writes.push(env.TOP10_KV.put(`top10:latest:${snapshotDate}`, JSON.stringify(state)));
  }

  await Promise.all(writes);
  await safeDeleteLockIfOwnsJob(env, jobId);

  return jsonResponse(200, { status: "ok", job_id: jobId }, requestOrigin, env);
}

export async function handleRequest(request, env, ctx) {
  const requestOrigin = request.headers.get("origin");
  const allowedOrigin = getCorsOrigin(requestOrigin, env);
  if (requestOrigin && !allowedOrigin) {
    return jsonResponse(403, { error: "origin not allowed" }, requestOrigin, env);
  }

  if (request.method === "OPTIONS") {
    const corsHeaders = {
      ...makeCorsHeaders(requestOrigin, env),
      "Access-Control-Allow-Origin": allowedOrigin || "*",
    };
    return new Response(null, { status: 204, headers: corsHeaders });
  }

  const url = new URL(request.url);
  if (url.pathname === "/api/top10/run" && request.method === "POST") {
    return handleRun(request, env, requestOrigin);
  }
  if (url.pathname === "/api/top10/status" && request.method === "GET") {
    return handleStatus(request, env, requestOrigin);
  }
  if (url.pathname === "/api/top10/latest" && request.method === "GET") {
    return handleLatest(request, env, requestOrigin);
  }
  if (url.pathname === "/api/top10/callback" && request.method === "POST") {
    return handleCallback(request, env, requestOrigin);
  }
  if (url.pathname === "/api/quotes/current" && request.method === "POST") {
    return handleCurrentQuotes(request, env, requestOrigin);
  }
  if (url.pathname === "/api/decision-watchlist" && request.method === "GET") {
    return forwardDecisionWatchlist(request, env, requestOrigin);
  }
  if (url.pathname === "/api/decision-watchlist" && request.method === "PUT") {
    return forwardDecisionWatchlist(request, env, requestOrigin);
  }

  return jsonResponse(404, { error: "not found" }, requestOrigin, env);
}

export default {
  fetch: handleRequest,
};
