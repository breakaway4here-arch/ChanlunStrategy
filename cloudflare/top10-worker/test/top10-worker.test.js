import assert from "node:assert/strict";

import { DecisionWatchlist, handleRequest } from "../src/index.js";

class MemoryKV {
  constructor() {
    this.store = new Map();
  }

  async get(key, options = {}) {
    const value = this.store.get(key);
    if (value === undefined) {
      return null;
    }
    if (options.type === "json") {
      return value;
    }
    return typeof value === "string" ? value : JSON.stringify(value);
  }

  async put(key, value) {
    this.store.set(key, value);
  }

  async delete(key) {
    this.store.delete(key);
  }
}

class MemoryDurableStorage {
  constructor() {
    this.store = new Map();
    this.queue = Promise.resolve();
  }

  async get(key) {
    return this.store.get(key);
  }

  async put(key, value) {
    this.store.set(key, structuredClone(value));
  }

  async transaction(callback) {
    const run = this.queue.then(() => callback(this));
    this.queue = run.catch(() => undefined);
    return run;
  }
}

class MemoryDurableNamespace {
  constructor(env) {
    this.storage = new MemoryDurableStorage();
    this.object = new DecisionWatchlist({ storage: this.storage }, env);
  }

  idFromName(name) {
    return name;
  }

  get() {
    return { fetch: (request) => this.object.fetch(request) };
  }
}

function createBaseEnv() {
  const env = {
    TRIGGER_PASSWORD: "secret-1",
    CALLBACK_TOKEN: "callback-1",
    GITHUB_TOKEN: "ghp_mock_token",
    GITHUB_OWNER: "owner-1",
    GITHUB_REPO: "repo-1",
    GITHUB_WORKFLOW_ID: "workflow.yml",
    GITHUB_REF: "main",
    WATCHLIST_ADMIN_PASSWORD: "watch-secret-1",
    TOP10_KV: new MemoryKV(),
  };
  env.DECISION_WATCHLIST = new MemoryDurableNamespace(env);
  return env;
}

function parseJsonFromResponse(response) {
  return response.json();
}

function createRequest(path, options) {
  return new Request(`https://example.test${path}`, options);
}

async function testWrongPassword() {
  const kv = new MemoryKV();
  const env = createBaseEnv();
  env.TOP10_KV = kv;

  const response = await handleRequest(
    createRequest("/api/top10/run", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ password: "wrong" }),
    }),
    env,
  );

  assert.equal(response.status, 401);
  const data = await parseJsonFromResponse(response);
  assert.equal(data.error, "invalid password");
}

async function testRunDispatchSuccess() {
  const kv = new MemoryKV();
  const env = createBaseEnv();
  env.TOP10_KV = kv;
  const origFetch = globalThis.fetch;
  let githubCall = null;

  globalThis.fetch = async (url, options) => {
    githubCall = { url, options };
    return {
      ok: true,
      status: 204,
      async text() {
        return "ok";
      },
      async json() {
        return {};
      },
    };
  };

  try {
    const response = await handleRequest(
      createRequest("/api/top10/run", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ password: "secret-1" }),
      }),
      env,
    );

    assert.equal(response.status, 200);
    const data = await parseJsonFromResponse(response);
    assert.ok(data.job_id);
    assert.equal(data.status, "queued");

    const lockRaw = await kv.get("top10:lock");
    assert.equal(typeof lockRaw, "string");
    const lockState = JSON.parse(lockRaw);
    assert.equal(lockState.job_id, data.job_id);

    const jobRaw = await kv.get(`top10:job:${data.job_id}`);
    assert.equal(typeof jobRaw, "string");
    const jobState = JSON.parse(jobRaw);
    assert.equal(jobState.status, "running");
    assert.equal(jobState.job_id, data.job_id);

    assert.ok(githubCall);
    assert.equal(githubCall.url, "https://api.github.com/repos/owner-1/repo-1/actions/workflows/workflow.yml/dispatches");
    assert.equal(githubCall.options.method, "POST");
    assert.equal(githubCall.options.headers.Authorization, "Bearer ghp_mock_token");

    const githubBody = JSON.parse(githubCall.options.body);
    assert.equal(githubBody.ref, "main");
    assert.equal(githubBody.inputs.job_id, data.job_id);
  } finally {
    globalThis.fetch = origFetch;
  }
}

async function testLockConflict() {
  const kv = new MemoryKV();
  const env = createBaseEnv();
  env.TOP10_KV = kv;
  const future = Date.now() + 60_000;
  await kv.put(
    "top10:lock",
    JSON.stringify({
      job_id: "job-running",
      expires_at: future,
      status: "locked",
    }),
  );

  const response = await handleRequest(
    createRequest("/api/top10/run", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ password: "secret-1" }),
    }),
    env,
  );

  assert.equal(response.status, 409);
  const data = await parseJsonFromResponse(response);
  assert.equal(data.error, "job in progress");
  assert.equal(data.job_id, "job-running");
}

async function testCallbackTokenFailure() {
  const kv = new MemoryKV();
  const env = createBaseEnv();
  env.TOP10_KV = kv;

  const response = await handleRequest(
    createRequest("/api/top10/callback", {
      method: "POST",
      headers: { "content-type": "application/json", "x-callback-token": "wrong-token" },
      body: JSON.stringify({ job_id: "job-1", status: "done" }),
    }),
    env,
  );

  assert.equal(response.status, 401);
  const data = await parseJsonFromResponse(response);
  assert.equal(data.error, "invalid callback token");
}

async function testCallbackSuccess() {
  const kv = new MemoryKV();
  const env = createBaseEnv();
  env.TOP10_KV = kv;

  await kv.put("top10:lock", JSON.stringify({ job_id: "job-1", created_at: 1, expires_at: Date.now() + 60000 }));

  const response = await handleRequest(
    createRequest("/api/top10/callback", {
      method: "POST",
      headers: { "content-type": "application/json", Authorization: "Bearer callback-1" },
      body: JSON.stringify({
        job_id: "job-1",
        status: "done",
        snapshot_date: "2026-07-02",
        result: { items: [{ code: "000001", score: 99 }] },
      }),
    }),
    env,
  );

  assert.equal(response.status, 200);
  const body = await parseJsonFromResponse(response);
  assert.equal(body.status, "ok");

  const lockRaw = await kv.get("top10:lock");
  assert.equal(lockRaw, null);

  const latestRaw = await kv.get("top10:latest");
  assert.ok(latestRaw && latestRaw.includes(`"status":"done"`));
  assert.ok(latestRaw.includes('"job_id":"job-1"'));

  const datedLatestRaw = await kv.get("top10:latest:2026-07-02");
  assert.ok(datedLatestRaw && datedLatestRaw.includes(`"status":"done"`));
  assert.ok(datedLatestRaw.includes('"snapshot_date":"2026-07-02"'));

  const jobRaw = await kv.get("top10:job:job-1");
  assert.ok(jobRaw && jobRaw.includes(`"status":"done"`));
}

async function testLatestByDate() {
  const kv = new MemoryKV();
  const env = createBaseEnv();
  env.TOP10_KV = kv;
  await kv.put(
    "top10:latest:2026-07-02",
    JSON.stringify({ job_id: "job-dated", status: "done", snapshot_date: "2026-07-02", items: [{ code: "000001" }] }),
  );

  const response = await handleRequest(
    createRequest("/api/top10/latest?date=2026-07-02", { method: "GET" }),
    env,
  );

  assert.equal(response.status, 200);
  const data = await parseJsonFromResponse(response);
  assert.equal(data.job_id, "job-dated");
  assert.equal(data.status, "done");
  assert.equal(data.snapshot_date, "2026-07-02");
}

async function testLatestMissing() {
  const kv = new MemoryKV();
  const env = createBaseEnv();
  env.TOP10_KV = kv;

  const response = await handleRequest(
    createRequest("/api/top10/latest?date=2026-07-03", { method: "GET" }),
    env,
  );

  assert.equal(response.status, 404);
  const data = await parseJsonFromResponse(response);
  assert.equal(data.error, "latest snapshot not found");
  assert.equal(data.snapshot_date, "2026-07-03");
}

async function testLatestByDateFallsBackToGenericLatest() {
  const kv = new MemoryKV();
  const env = createBaseEnv();
  env.TOP10_KV = kv;
  await kv.put(
    "top10:latest",
    JSON.stringify({ job_id: "job-generic", status: "done", snapshot_date: "2026-07-02", items: [{ code: "000002" }] }),
  );

  const response = await handleRequest(
    createRequest("/api/top10/latest?date=2026-07-02", { method: "GET" }),
    env,
  );

  assert.equal(response.status, 200);
  const data = await parseJsonFromResponse(response);
  assert.equal(data.job_id, "job-generic");
  assert.equal(data.snapshot_date, "2026-07-02");
}

async function testCurrentQuotesRejectsEmptyAndInvalidCodes() {
  const env = createBaseEnv();
  const emptyResponse = await handleRequest(
    createRequest("/api/quotes/current", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ codes: [] }),
    }),
    env,
  );
  assert.equal(emptyResponse.status, 400);
  assert.equal((await parseJsonFromResponse(emptyResponse)).error, "codes must be a non-empty array");

  const invalidResponse = await handleRequest(
    createRequest("/api/quotes/current", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ codes: ["000001", "bad-code"] }),
    }),
    env,
  );
  assert.equal(invalidResponse.status, 400);
  assert.deepEqual((await parseJsonFromResponse(invalidResponse)).invalid_codes, ["bad-code"]);

  const nonStockCodes = ["110000", "159001", "200001", "900901"];
  const nonStockResponse = await handleRequest(
    createRequest("/api/quotes/current", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ codes: nonStockCodes }),
    }),
    env,
  );
  assert.equal(nonStockResponse.status, 400);
  assert.deepEqual((await parseJsonFromResponse(nonStockResponse)).invalid_codes, nonStockCodes);
}

async function testCurrentQuotesDeduplicatesAndEnforcesLimit() {
  const env = createBaseEnv();
  const origFetch = globalThis.fetch;
  const requestedUrls = [];
  globalThis.fetch = async (url) => {
    requestedUrls.push(String(url));
    return {
      ok: true,
      async json() {
        return { data: { diff: [{ f12: "000001", f2: 10.25 }, { f12: "000300", f2: 3900.5 }] } };
      },
    };
  };

  try {
    const response = await handleRequest(
      createRequest("/api/quotes/current", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ codes: ["000001", "000001"] }),
      }),
      env,
    );
    assert.equal(response.status, 200);
    assert.equal((await parseJsonFromResponse(response)).quotes.length, 1);
    assert.ok(requestedUrls.some((url) => url.includes("secids=0.000001")));

    const tooMany = Array.from({ length: 201 }, (_, index) => String(index).padStart(6, "0"));
    const limitResponse = await handleRequest(
      createRequest("/api/quotes/current", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ codes: tooMany }),
      }),
      env,
    );
    assert.equal(limitResponse.status, 400);
    assert.equal((await parseJsonFromResponse(limitResponse)).error, "too many codes (maximum 200)");
  } finally {
    globalThis.fetch = origFetch;
  }
}

async function testCurrentQuotesParsesStocksAndBenchmark() {
  const env = createBaseEnv();
  const origFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url) => {
    calls.push(String(url));
    return {
      ok: true,
      async json() {
        return { data: { diff: [{ f12: "000001", f2: 10.25 }, { f12: "600000", f2: 8.1 }, { f12: "000300", f2: 3900.5 }] } };
      },
    };
  };

  try {
    const response = await handleRequest(
      createRequest("/api/quotes/current", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ codes: ["000001", "600000"] }),
      }),
      env,
    );
    assert.equal(response.status, 200);
    const data = await parseJsonFromResponse(response);
    assert.deepEqual(data.quotes, [
      { code: "000001", current_price: 10.25, status: "ok" },
      { code: "600000", current_price: 8.1, status: "ok" },
    ]);
    assert.deepEqual(data.benchmark, { code: "000300", current_price: 3900.5, status: "ok" });
    assert.match(data.quoted_at, /^\d{4}-\d{2}-\d{2}T/);
    assert.equal(calls.length, 2);
    assert.ok(calls.every((url) => url.startsWith("https://push2.eastmoney.com/api/qt/ulist.np/get?")));
    assert.equal(new URL(calls[1]).searchParams.get("secids"), "1.000300");
  } finally {
    globalThis.fetch = origFetch;
  }
}

async function testCurrentQuotesMapsSupportedAshareMarkets() {
  const env = createBaseEnv();
  const origFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url) => {
    calls.push(String(url));
    const codes = new URL(String(url)).searchParams.get("secids").split(",").map((secid) => secid.split(".")[1]);
    return {
      ok: true,
      async json() {
        return { data: { diff: codes.map((code) => ({ f12: code, f2: 10 })) } };
      },
    };
  };

  try {
    const response = await handleRequest(
      createRequest("/api/quotes/current", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ codes: ["600000", "000001", "300001", "430047", "830799", "920130"] }),
      }),
      env,
    );
    assert.equal(response.status, 200);
    assert.equal(
      new URL(calls[0]).searchParams.get("secids"),
      "1.600000,0.000001,0.300001,0.430047,0.830799,0.920130",
    );
  } finally {
    globalThis.fetch = origFetch;
  }
}

async function testCurrentQuotesDoesNotCoerceInvalidPricesToZero() {
  const env = createBaseEnv();
  const origFetch = globalThis.fetch;
  globalThis.fetch = async (url) => {
    const isBenchmark = new URL(String(url)).searchParams.get("secids") === "1.000300";
    return {
      ok: true,
      async json() {
        return isBenchmark
          ? { data: { diff: [{ f12: "000300", f2: 3900.5 }] } }
          : { data: { diff: [
            { f12: "600001", f2: null },
            { f12: "600002", f2: "" },
            { f12: "600003", f2: "-" },
          ] } };
      },
    };
  };

  try {
    const response = await handleRequest(
      createRequest("/api/quotes/current", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ codes: ["600001", "600002", "600003"] }),
      }),
      env,
    );
    assert.equal(response.status, 200);
    const data = await parseJsonFromResponse(response);
    assert.deepEqual(data.quotes, [
      { code: "600001", current_price: null, status: "not_found" },
      { code: "600002", current_price: null, status: "not_found" },
      { code: "600003", current_price: null, status: "not_found" },
    ]);
  } finally {
    globalThis.fetch = origFetch;
  }
}

async function testCurrentQuotesReturnsPartialFailure() {
  const env = createBaseEnv();
  const origFetch = globalThis.fetch;
  globalThis.fetch = async (url) => {
    if (String(url).includes("0.000001")) {
      throw new Error("upstream unavailable");
    }
    return {
      ok: true,
      async json() {
        return { data: { diff: [{ f12: "000300", f2: 3900.5 }] } };
      },
    };
  };

  try {
    const response = await handleRequest(
      createRequest("/api/quotes/current", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ codes: ["000001"] }),
      }),
      env,
    );
    assert.equal(response.status, 200);
    const data = await parseJsonFromResponse(response);
    assert.deepEqual(data.quotes, [{ code: "000001", current_price: null, status: "upstream_error" }]);
    assert.equal(data.benchmark.status, "ok");
    assert.equal(data.status, "partial");
  } finally {
    globalThis.fetch = origFetch;
  }
}

async function testCurrentQuotesReturns502WhenEveryUpstreamRequestFails() {
  const env = createBaseEnv();
  const origFetch = globalThis.fetch;
  globalThis.fetch = async () => {
    throw new Error("upstream unavailable");
  };

  try {
    const response = await handleRequest(
      createRequest("/api/quotes/current", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ codes: ["600001"] }),
      }),
      env,
    );
    assert.equal(response.status, 502);
    assert.equal((await parseJsonFromResponse(response)).error, "quote upstream unavailable");
  } finally {
    globalThis.fetch = origFetch;
  }
}

async function testCurrentQuotesFallsBackToTencentWhenEastmoneyIsUnavailable() {
  const env = createBaseEnv();
  const origFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url) => {
    calls.push(String(url));
    if (String(url).startsWith("https://push2.eastmoney.com/")) {
      throw new Error("eastmoney blocked at edge");
    }
    if (String(url).includes("q=sz000001")) {
      return {
        ok: true,
        async text() {
          return 'v_sz000001="51~Ping An~000001~10.78~10.77~10.75";';
        },
      };
    }
    if (String(url).includes("q=sh000300")) {
      return {
        ok: true,
        async text() {
          return 'v_sh000300="1~CSI 300~000300~4728.11~4700.00~4690.00";';
        },
      };
    }
    throw new Error(`unexpected upstream ${url}`);
  };

  try {
    const response = await handleRequest(
      createRequest("/api/quotes/current", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ codes: ["000001"] }),
      }),
      env,
    );
    assert.equal(response.status, 200);
    const data = await parseJsonFromResponse(response);
    assert.equal(data.status, "ok");
    assert.deepEqual(data.quotes, [{ code: "000001", current_price: 10.78, status: "ok" }]);
    assert.deepEqual(data.benchmark, { code: "000300", current_price: 4728.11, status: "ok" });
    assert.equal(calls.filter((url) => url.startsWith("https://push2.eastmoney.com/")).length, 2);
    assert.equal(calls.filter((url) => url.startsWith("https://qt.gtimg.cn/")).length, 2);
  } finally {
    globalThis.fetch = origFetch;
  }
}

async function testCurrentQuotesSplitsMoreThan100CodesIntoBatches() {
  const env = createBaseEnv();
  const origFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url) => {
    calls.push(String(url));
    const codes = new URL(String(url)).searchParams.get("secids").split(",").map((secid) => secid.split(".")[1]);
    return {
      ok: true,
      async json() {
        return { data: { diff: codes.map((code) => ({ f12: code, f2: 10 })) } };
      },
    };
  };

  try {
    const codes = Array.from({ length: 101 }, (_, index) => String(600000 + index));
    const response = await handleRequest(
      createRequest("/api/quotes/current", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ codes }),
      }),
      env,
    );
    assert.equal(response.status, 200);
    assert.equal((await parseJsonFromResponse(response)).quotes.length, 101);
    assert.equal(calls.length, 3);
    assert.equal(new URL(calls[0]).searchParams.get("secids").split(",").length, 100);
    assert.equal(new URL(calls[1]).searchParams.get("secids").split(",").length, 1);
    assert.equal(new URL(calls[2]).searchParams.get("secids"), "1.000300");
  } finally {
    globalThis.fetch = origFetch;
  }
}

async function testCurrentQuotesTracksFailureByOwningBatch() {
  const env = createBaseEnv();
  const origFetch = globalThis.fetch;
  globalThis.fetch = async (url) => {
    const secids = new URL(String(url)).searchParams.get("secids").split(",");
    if (secids.length === 1 && secids[0] === "1.600100") {
      throw new Error("second stock batch unavailable");
    }
    const rows = secids
      .map((secid) => secid.split(".")[1])
      .filter((code) => code !== "600099")
      .map((code) => ({ f12: code, f2: 10 }));
    return {
      ok: true,
      async json() {
        return { data: { diff: rows } };
      },
    };
  };

  try {
    const codes = Array.from({ length: 101 }, (_, index) => String(600000 + index));
    const response = await handleRequest(
      createRequest("/api/quotes/current", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ codes }),
      }),
      env,
    );
    assert.equal(response.status, 200);
    const data = await parseJsonFromResponse(response);
    assert.equal(data.status, "partial");
    assert.deepEqual(data.quotes[99], { code: "600099", current_price: null, status: "not_found" });
    assert.deepEqual(data.quotes[100], { code: "600100", current_price: null, status: "upstream_error" });
    assert.equal(data.benchmark.status, "ok");
  } finally {
    globalThis.fetch = origFetch;
  }
}

async function testCurrentQuotesUsesExistingCorsRules() {
  const env = createBaseEnv();
  env.ALLOWED_ORIGINS = "https://allowed.example";
  const response = await handleRequest(
    createRequest("/api/quotes/current", {
      method: "OPTIONS",
      headers: { origin: "https://allowed.example" },
    }),
    env,
  );
  assert.equal(response.status, 204);
  assert.equal(response.headers.get("access-control-allow-origin"), "https://allowed.example");
}

function watchlistItem(code = "300308", overrides = {}) {
  return {
    code,
    note: code === "300308" ? "中际旭创" : "测试股",
    role: "strong_watch",
    enabled: true,
    tags: ["用户重点观察"],
    thesis: "等待板块、事件和个股结构共振。",
    ...overrides,
  };
}

async function testWatchlistGetReturnsRevisionAndEtag() {
  const env = createBaseEnv();
  const response = await handleRequest(
    createRequest("/api/decision-watchlist", { method: "GET" }),
    env,
  );
  assert.equal(response.status, 200);
  const data = await parseJsonFromResponse(response);
  assert.ok(data.revision);
  assert.ok(Array.isArray(data.items));
  assert.equal(data.items.length, 5);
  assert.equal(response.headers.get("etag"), `"${data.revision}"`);
}

async function testWatchlistPutRequiresAuthenticationAndIfMatch() {
  const env = createBaseEnv();
  const current = await handleRequest(
    createRequest("/api/decision-watchlist", { method: "GET" }), env,
  );
  const etag = current.headers.get("etag");
  const body = JSON.stringify({ items: [watchlistItem()] });

  const unauthenticated = await handleRequest(
    createRequest("/api/decision-watchlist", {
      method: "PUT",
      headers: { "content-type": "application/json", "if-match": etag },
      body,
    }),
    env,
  );
  assert.equal(unauthenticated.status, 401);

  const missingEtag = await handleRequest(
    createRequest("/api/decision-watchlist", {
      method: "PUT",
      headers: {
        "content-type": "application/json",
        authorization: "Bearer watch-secret-1",
      },
      body,
    }),
    env,
  );
  assert.equal(missingEtag.status, 428);
}

async function testWatchlistPutRejectsConflictAndReturnsCurrentRevision() {
  const env = createBaseEnv();
  const response = await handleRequest(
    createRequest("/api/decision-watchlist", {
      method: "PUT",
      headers: {
        "content-type": "application/json",
        authorization: "Bearer watch-secret-1",
        "if-match": '"stale-revision"',
      },
      body: JSON.stringify({ items: [watchlistItem()] }),
    }),
    env,
  );
  assert.equal(response.status, 412);
  const data = await parseJsonFromResponse(response);
  assert.equal(data.error, "watchlist revision conflict");
  assert.ok(data.current?.revision);
  assert.equal(response.headers.get("etag"), `"${data.current.revision}"`);
}

async function testWatchlistPutValidatesItemsAndMaximumSize() {
  const env = createBaseEnv();
  const current = await handleRequest(
    createRequest("/api/decision-watchlist", { method: "GET" }), env,
  );
  const headers = {
    "content-type": "application/json",
    authorization: "Bearer watch-secret-1",
    "if-match": current.headers.get("etag"),
  };
  const invalid = await handleRequest(
    createRequest("/api/decision-watchlist", {
      method: "PUT",
      headers,
      body: JSON.stringify({ items: [watchlistItem("bad", { role: "owner" })] }),
    }),
    env,
  );
  assert.equal(invalid.status, 400);

  const invalidRole = await handleRequest(
    createRequest("/api/decision-watchlist", {
      method: "PUT",
      headers,
      body: JSON.stringify({ items: [watchlistItem("300308", { role: "owner" })] }),
    }),
    env,
  );
  assert.equal(invalidRole.status, 400);
  assert.equal((await parseJsonFromResponse(invalidRole)).error, "invalid watchlist role");

  const tooMany = await handleRequest(
    createRequest("/api/decision-watchlist", {
      method: "PUT",
      headers,
      body: JSON.stringify({
        items: Array.from({ length: 21 }, (_, index) => watchlistItem(String(600000 + index))),
      }),
    }),
    env,
  );
  assert.equal(tooMany.status, 400);
  assert.equal((await parseJsonFromResponse(tooMany)).error, "watchlist maximum is 20 items");
}

async function testWatchlistPutUpdatesRevisionAndCreatesAuditRecord() {
  const env = createBaseEnv();
  const current = await handleRequest(
    createRequest("/api/decision-watchlist", { method: "GET" }), env,
  );
  const previous = await parseJsonFromResponse(current);
  const response = await handleRequest(
    createRequest("/api/decision-watchlist", {
      method: "PUT",
      headers: {
        "content-type": "application/json",
        authorization: "Bearer watch-secret-1",
        "if-match": current.headers.get("etag"),
      },
      body: JSON.stringify({
        items: [watchlistItem("300139", { note: "晓程科技" }), watchlistItem()],
      }),
    }),
    env,
  );
  assert.equal(response.status, 200);
  const data = await parseJsonFromResponse(response);
  assert.notEqual(data.revision, previous.revision);
  assert.equal(data.items[0].priority, 1);
  assert.equal(data.items[1].priority, 2);
  assert.equal(data.analysis_effect, "next_report");
  assert.equal(response.headers.get("etag"), `"${data.revision}"`);
  const saved = await env.DECISION_WATCHLIST.storage.get("decision:watchlist:current");
  assert.equal(saved.revision, data.revision);
  const audit = await env.DECISION_WATCHLIST.storage.get(`decision:watchlist:audit:${data.revision}`);
  assert.equal(audit.previous_revision, previous.revision);
  assert.equal(audit.updated_by, "web_admin");
}

async function testWatchlistConcurrentPutAllowsExactlyOneRevisionWinner() {
  const env = createBaseEnv();
  const current = await handleRequest(
    createRequest("/api/decision-watchlist", { method: "GET" }), env,
  );
  const etag = current.headers.get("etag");
  const requestFor = (code) => handleRequest(
    createRequest("/api/decision-watchlist", {
      method: "PUT",
      headers: {
        "content-type": "application/json",
        authorization: "Bearer watch-secret-1",
        "if-match": etag,
      },
      body: JSON.stringify({ items: [watchlistItem(code)] }),
    }),
    env,
  );

  const responses = await Promise.all([
    requestFor("300139"),
    requestFor("300308"),
  ]);
  assert.deepEqual(responses.map((response) => response.status).sort(), [200, 412]);
  const winner = await responses.find((response) => response.status === 200).json();
  const saved = await env.DECISION_WATCHLIST.storage.get("decision:watchlist:current");
  const audit = await env.DECISION_WATCHLIST.storage.get(`decision:watchlist:audit:${winner.revision}`);
  assert.equal(saved.revision, winner.revision);
  assert.equal(audit.revision, winner.revision);
}

async function testWatchlistCorsAllowsVersionedPutHeaders() {
  const env = createBaseEnv();
  env.ALLOWED_ORIGINS = "https://allowed.example";
  const response = await handleRequest(
    createRequest("/api/decision-watchlist", {
      method: "OPTIONS",
      headers: { origin: "https://allowed.example" },
    }),
    env,
  );
  assert.equal(response.status, 204);
  assert.match(response.headers.get("access-control-allow-methods"), /PUT/);
  assert.match(response.headers.get("access-control-allow-headers"), /if-match/);
  assert.match(response.headers.get("access-control-expose-headers"), /ETag/i);
}

async function main() {
  await testWrongPassword();
  await testRunDispatchSuccess();
  await testLockConflict();
  await testCallbackTokenFailure();
  await testCallbackSuccess();
  await testLatestByDate();
  await testLatestMissing();
  await testLatestByDateFallsBackToGenericLatest();
  await testCurrentQuotesRejectsEmptyAndInvalidCodes();
  await testCurrentQuotesDeduplicatesAndEnforcesLimit();
  await testCurrentQuotesParsesStocksAndBenchmark();
  await testCurrentQuotesMapsSupportedAshareMarkets();
  await testCurrentQuotesDoesNotCoerceInvalidPricesToZero();
  await testCurrentQuotesReturnsPartialFailure();
  await testCurrentQuotesFallsBackToTencentWhenEastmoneyIsUnavailable();
  await testCurrentQuotesReturns502WhenEveryUpstreamRequestFails();
  await testCurrentQuotesSplitsMoreThan100CodesIntoBatches();
  await testCurrentQuotesTracksFailureByOwningBatch();
  await testCurrentQuotesUsesExistingCorsRules();
  await testWatchlistGetReturnsRevisionAndEtag();
  await testWatchlistPutRequiresAuthenticationAndIfMatch();
  await testWatchlistPutRejectsConflictAndReturnsCurrentRevision();
  await testWatchlistPutValidatesItemsAndMaximumSize();
  await testWatchlistPutUpdatesRevisionAndCreatesAuditRecord();
  await testWatchlistConcurrentPutAllowsExactlyOneRevisionWinner();
  await testWatchlistCorsAllowsVersionedPutHeaders();

  console.log("top10-worker.test.js: all tests passed");
}

await main();
