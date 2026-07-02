const DEFAULT_LOCK_TTL_SECONDS = 600;
const DEFAULT_JOB_TIMEOUT_SECONDS = 600;

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
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
    "Access-Control-Allow-Headers": "authorization,content-type,x-callback-token",
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

function sanitizeToken(value) {
  return typeof value === "string" ? value.trim() : "";
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

  await Promise.all([
    env.TOP10_KV.put(`top10:job:${jobId}`, JSON.stringify(state)),
    env.TOP10_KV.put("top10:latest", JSON.stringify(state)),
  ]);
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
  if (url.pathname === "/api/top10/callback" && request.method === "POST") {
    return handleCallback(request, env, requestOrigin);
  }

  return jsonResponse(404, { error: "not found" }, requestOrigin, env);
}

export default {
  fetch: handleRequest,
};
