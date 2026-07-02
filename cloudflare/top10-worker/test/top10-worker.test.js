import assert from "node:assert/strict";

import { handleRequest } from "../src/index.js";

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

function createBaseEnv() {
  return {
    TRIGGER_PASSWORD: "secret-1",
    CALLBACK_TOKEN: "callback-1",
    GITHUB_TOKEN: "ghp_mock_token",
    GITHUB_OWNER: "owner-1",
    GITHUB_REPO: "repo-1",
    GITHUB_WORKFLOW_ID: "workflow.yml",
    GITHUB_REF: "main",
    TOP10_KV: new MemoryKV(),
  };
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

  const jobRaw = await kv.get("top10:job:job-1");
  assert.ok(jobRaw && jobRaw.includes(`"status":"done"`));
}

async function main() {
  await testWrongPassword();
  await testRunDispatchSuccess();
  await testLockConflict();
  await testCallbackTokenFailure();
  await testCallbackSuccess();

  console.log("top10-worker.test.js: all tests passed");
}

await main();
