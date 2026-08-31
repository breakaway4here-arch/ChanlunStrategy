import { env } from "cloudflare:workers";
import { runInDurableObject, SELF } from "cloudflare:test";
import { afterEach, describe, expect, it, vi } from "vitest";

import { handleRequest, type PrecloseSnapshotBody } from "../src/index";

const PAGE_ORIGIN = "https://breakaway4here-arch.github.io";
const TOKEN = "test-write-token";

function snapshot(date: string, suffix = "a"): PrecloseSnapshotBody {
  const contentHash = suffix.repeat(64).slice(0, 64);
  return {
    schema_version: "preclose-selection-v1",
    strategy_version: "preclose-1445-v2",
    mode: "preclose_advisory",
    trade_date: date,
    snapshot_id: `preclose:${date}:${contentHash.slice(0, 16)}`,
    content_hash: contentHash,
    source_sha: "6412624c",
    as_of: `${date}T14:45:00+08:00`,
    generated_at: `${date}T14:48:00+08:00`,
    expires_at: `${date}T14:56:30+08:00`,
    status: "available",
    is_final: false,
    affects_formal: false,
    pools: {
      main: [{ code: "300998", name: "宁波方正", reference_price: 26.86, score: 99 } as never],
      h4_t3: [],
      acceleration: [],
    },
    diagnostics: { internal_reason: "must-not-leak" },
  };
}

function request(path: string, init: RequestInit = {}): Request {
  const headers = new Headers(init.headers);
  if (!headers.has("origin")) headers.set("origin", PAGE_ORIGIN);
  return new Request(`https://preclose.example${path}`, { ...init, headers });
}

async function put(body: PrecloseSnapshotBody, headers: HeadersInit = {}) {
  return SELF.fetch(request("/api/preclose/snapshot", {
    method: "PUT",
    headers: {
      authorization: `Bearer ${TOKEN}`,
      "content-type": "application/json",
      ...headers,
    },
    body: JSON.stringify(body),
  }));
}

afterEach(() => {
  vi.useRealTimers();
});

describe("pre-close worker", () => {
  it("rejects missing and incorrect write tokens with timing-safe auth", async () => {
    const body = snapshot("2026-09-01");
    for (const authorization of [undefined, "Bearer wrong-token"]) {
      const response = await SELF.fetch(request("/api/preclose/snapshot", {
        method: "PUT",
        headers: {
          ...(authorization ? { authorization } : {}),
          "content-type": "application/json",
        },
        body: JSON.stringify(body),
      }));
      expect(response.status).toBe(401);
    }
  });

  it("creates once and treats the same snapshot id and hash as idempotent", async () => {
    const body = snapshot("2026-09-02");
    const first = await put(body);
    expect(first.status).toBe(201);
    expect(await first.json()).toMatchObject({ status: "created", revision: 1 });

    const repeated = await put(body);
    expect(repeated.status).toBe(200);
    expect(await repeated.json()).toMatchObject({ status: "idempotent", revision: 1 });
  });

  it("rejects a changed content projection that reuses the same snapshot id and hash", async () => {
    const body = snapshot("2026-09-18");
    expect((await put(body)).status).toBe(201);
    const changed = structuredClone(body);
    changed.pools.main[0].name = "被篡改的候选";
    expect((await put(changed)).status).toBe(400);
  });

  it("binds the snapshot id suffix to the declared content hash", async () => {
    const body = snapshot("2026-09-21");
    body.snapshot_id = `preclose:${body.trade_date}:${"f".repeat(16)}`;
    expect((await put(body)).status).toBe(400);
  });

  it("requires a matching revision before replacing a different hash", async () => {
    const date = "2026-09-03";
    await put(snapshot(date, "a"));
    const conflict = await put(snapshot(date, "b"));
    expect(conflict.status).toBe(412);

    const replaced = await put(snapshot(date, "b"), { "if-match": '"1"' });
    expect(replaced.status).toBe(200);
    expect(await replaced.json()).toMatchObject({ status: "updated", revision: 2 });

    const stale = await put(snapshot(date, "c"), { "if-match": '"1"' });
    expect(stale.status).toBe(412);
  });

  it("returns no-store public fields and strips diagnostics and extra candidate data", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-04T06:50:00Z"));
    await put(snapshot("2026-09-04"));

    const response = await SELF.fetch(request("/api/preclose/latest?date=2026-09-04"));
    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toBe("no-store");
    const body = await response.json<Record<string, unknown>>();
    expect(body).not.toHaveProperty("diagnostics");
    expect(JSON.stringify(body)).not.toContain("internal_reason");
    expect(JSON.stringify(body)).not.toContain("score");
    expect(body).toMatchObject({
      trade_date: "2026-09-04",
      status: "available",
      pools: { main: [{ code: "300998", name: "宁波方正", reference_price: 26.86 }] },
    });
  });

  it("maps an available snapshot with three empty pools to the unified empty state", async () => {
    vi.useFakeTimers();
    const date = "2026-09-19";
    vi.setSystemTime(new Date(`${date}T06:50:00Z`));
    const body = snapshot(date);
    body.pools = { main: [], h4_t3: [], acceleration: [] };
    expect((await put(body)).status).toBe(201);

    const response = await SELF.fetch(request(`/api/preclose/latest?date=${date}`));
    expect(response.status).toBe(200);
    expect(await response.json()).toMatchObject({
      status: "empty",
      message: "本期未选出推荐票",
      pools: { main: [], h4_t3: [], acceleration: [] },
    });
  });

  it("fails closed at the inclusive server expiry boundary", async () => {
    vi.useFakeTimers();
    await put(snapshot("2026-09-05"));
    vi.setSystemTime(new Date("2026-09-05T06:56:30Z"));
    const response = await SELF.fetch(request("/api/preclose/latest?date=2026-09-05"));
    const body = await response.json<Record<string, any>>();
    expect(body.status).toBe("expired");
    expect(body.pools).toEqual({ main: [], h4_t3: [], acceleration: [] });
    expect(JSON.stringify(body)).not.toContain("300998");
  });

  it("rejects timezone-naive timestamps and an expiry that is not exactly 14:56:30 Asia/Shanghai", async () => {
    const naiveExpiry = snapshot("2026-09-12");
    naiveExpiry.expires_at = "2026-09-12T14:56:30";
    expect((await put(naiveExpiry)).status).toBe(400);

    const wrongExpiryInstant = snapshot("2026-09-13");
    wrongExpiryInstant.expires_at = "2026-09-13T14:56:30Z";
    expect((await put(wrongExpiryInstant)).status).toBe(400);

    const naiveAsOf = snapshot("2026-09-14");
    naiveAsOf.as_of = "2026-09-14T14:47:00";
    expect((await put(naiveAsOf)).status).toBe(400);

    const equivalentUtcExpiry = snapshot("2026-09-15");
    equivalentUtcExpiry.expires_at = "2026-09-15T06:56:30Z";
    expect((await put(equivalentUtcExpiry)).status).toBe(201);
  });

  it("allows only the Pages CORS origin and never emits a wildcard", async () => {
    const rejected = await SELF.fetch(new Request(
      "https://preclose.example/api/preclose/latest?date=2026-09-06",
      { headers: { origin: "https://evil.example" } },
    ));
    expect(rejected.status).toBe(403);
    expect(rejected.headers.get("access-control-allow-origin")).toBeNull();

    const preflight = await SELF.fetch(request("/api/preclose/latest?date=2026-09-06", {
      method: "OPTIONS",
      headers: {
        origin: PAGE_ORIGIN,
        "access-control-request-method": "GET",
      },
    }));
    expect(preflight.status).toBe(204);
    expect(preflight.headers.get("access-control-allow-origin")).toBe(PAGE_ORIGIN);
    expect(preflight.headers.get("access-control-allow-origin")).not.toBe("*");
  });

  it("requires explicit enablement and blocks every route before storage", async () => {
    const paths = [
      request("/api/preclose/latest?date=2026-09-06"),
      request("/api/preclose/reconciliation?date=2026-09-06"),
      request("/api/preclose/snapshot", {
        method: "PUT",
        headers: { authorization: `Bearer ${TOKEN}`, "content-type": "application/json" },
        body: JSON.stringify(snapshot("2026-09-06")),
      }),
      request("/api/preclose/reconciliation", {
        method: "PUT",
        headers: { authorization: `Bearer ${TOKEN}`, "content-type": "application/json" },
        body: JSON.stringify({
          trade_date: "2026-09-06",
          content_hash: "e".repeat(64),
          preclose_content_hash: "a".repeat(64),
          formal_content_hash: "f".repeat(64),
          status: "changed",
          pools: {},
        }),
      }),
      request("/api/preclose/latest?date=2026-09-06", {
        method: "OPTIONS",
        headers: {
          origin: PAGE_ORIGIN,
          "access-control-request-method": "GET",
        },
      }),
    ];

    for (const enabled of [undefined, "", "false", "FALSE", "TRUE", "1", " true "]) {
      let storageCalls = 0;
      const disabledEnv = {
        ALLOWED_ORIGINS: PAGE_ORIGIN,
        PRECLOSE_ENABLED: enabled,
        PRE_CLOSE_WRITE_TOKEN: TOKEN,
        PRE_CLOSE_SNAPSHOT: {
          getByName() {
            storageCalls += 1;
            throw new Error("disabled worker must not access Durable Objects");
          },
        },
      } as never;

      for (const source of paths) {
        const response = await handleRequest(source.clone(), disabledEnv);
        expect(response.status).toBe(503);
        expect(response.headers.get("cache-control")).toBe("no-store");
        expect(response.headers.get("access-control-allow-origin")).toBe(PAGE_ORIGIN);
        expect(await response.json()).toEqual({ error: "pre-close service disabled" });
      }
      expect(storageCalls).toBe(0);
    }
  });

  it("routes different dates through getByName and calls RPC methods, never stub.fetch", async () => {
    const names: string[] = [];
    const rpcCalls: string[] = [];
    const fakeEnv = {
      ALLOWED_ORIGINS: PAGE_ORIGIN,
      PRECLOSE_ENABLED: "true",
      PRE_CLOSE_WRITE_TOKEN: TOKEN,
      PRE_CLOSE_SNAPSHOT: {
        getByName(name: string) {
          names.push(name);
          return {
            async getPublicSnapshot() {
              rpcCalls.push("getPublicSnapshot");
              return null;
            },
            async putSnapshot() {
              rpcCalls.push("putSnapshot");
              return { ok: true, status: "created", revision: 1 };
            },
            fetch() {
              throw new Error("stub.fetch must not be used");
            },
          };
        },
      },
    } as never;

    await handleRequest(request("/api/preclose/latest?date=2026-09-07"), fakeEnv);
    await handleRequest(request("/api/preclose/latest?date=2026-09-08"), fakeEnv);
    await handleRequest(request("/api/preclose/snapshot", {
      method: "PUT",
      headers: { authorization: `Bearer ${TOKEN}`, "content-type": "application/json" },
      body: JSON.stringify(snapshot("2026-09-09")),
    }), fakeEnv);

    expect(names).toEqual(["2026-09-07", "2026-09-08", "2026-09-09"]);
    expect(rpcCalls).toEqual(["getPublicSnapshot", "getPublicSnapshot", "putSnapshot"]);
  });

  it("persists snapshots and audit versions in SQLite-backed Durable Object storage", async () => {
    const date = "2026-09-10";
    await put(snapshot(date));
    const stub = env.PRE_CLOSE_SNAPSHOT.getByName(date);
    const counts = await runInDurableObject(stub, async (_instance, state) => {
      const snapshots = state.storage.sql.exec<{ count: number }>(
        "SELECT COUNT(*) AS count FROM snapshots",
      ).one();
      const audits = state.storage.sql.exec<{ count: number }>(
        "SELECT COUNT(*) AS count FROM audit_versions",
      ).one();
      return { snapshots: snapshots.count, audits: audits.count };
    });
    expect(counts).toEqual({ snapshots: 1, audits: 1 });
  });

  it("stores and reads reconciliation through the same per-date RPC object", async () => {
    const date = "2026-09-11";
    const storedSnapshot = snapshot(date);
    await put(storedSnapshot);
    const reconciliation = {
      trade_date: date,
      snapshot_id: storedSnapshot.snapshot_id,
      content_hash: "e".repeat(64),
      preclose_content_hash: storedSnapshot.content_hash,
      formal_content_hash: "f".repeat(64),
      status: "changed",
      diagnostics: { hidden: true },
      pools: { main: { retained: ["300998"] } },
    };
    const write = await SELF.fetch(request("/api/preclose/reconciliation", {
      method: "PUT",
      headers: { authorization: `Bearer ${TOKEN}`, "content-type": "application/json" },
      body: JSON.stringify(reconciliation),
    }));
    expect(write.status).toBe(201);
    const read = await SELF.fetch(request(`/api/preclose/reconciliation?date=${date}`));
    expect(read.status).toBe(200);
    expect(read.headers.get("cache-control")).toBe("no-store");
    const body = await read.json<Record<string, unknown>>();
    expect(body).toMatchObject({
      trade_date: date,
      status: "changed",
      content_hash: "e".repeat(64),
    });
    expect(body).not.toHaveProperty("diagnostics");

    const repeated = await SELF.fetch(request("/api/preclose/reconciliation", {
      method: "PUT",
      headers: { authorization: `Bearer ${TOKEN}`, "content-type": "application/json" },
      body: JSON.stringify(reconciliation),
    }));
    expect(await repeated.json()).toMatchObject({ status: "idempotent", revision: 1 });

    const staleHashBody = structuredClone(reconciliation);
    staleHashBody.pools = { main: { retained: ["600000"] } };
    const staleHashWrite = await SELF.fetch(request("/api/preclose/reconciliation", {
      method: "PUT",
      headers: { authorization: `Bearer ${TOKEN}`, "content-type": "application/json" },
      body: JSON.stringify(staleHashBody),
    }));
    expect(staleHashWrite.status).toBe(400);

    const revised = { ...reconciliation, content_hash: "d".repeat(64), status: "unchanged" };
    const conflict = await SELF.fetch(request("/api/preclose/reconciliation", {
      method: "PUT",
      headers: { authorization: `Bearer ${TOKEN}`, "content-type": "application/json" },
      body: JSON.stringify(revised),
    }));
    expect(conflict.status).toBe(412);
    const updated = await SELF.fetch(request("/api/preclose/reconciliation", {
      method: "PUT",
      headers: {
        authorization: `Bearer ${TOKEN}`,
        "content-type": "application/json",
        "if-match": '"1"',
      },
      body: JSON.stringify(revised),
    }));
    expect(await updated.json()).toMatchObject({ status: "updated", revision: 2 });

    const stub = env.PRE_CLOSE_SNAPSHOT.getByName(date);
    const auditCount = await runInDurableObject(stub, async (_instance, state) => (
      state.storage.sql.exec<{ count: number }>(
        "SELECT COUNT(*) AS count FROM audit_versions WHERE kind = 'reconciliation'",
      ).one().count
    ));
    expect(auditCount).toBe(2);
  });

  it("binds reconciliation to the stored snapshot identity and content hash", async () => {
    const missingDate = "2026-09-16";
    const missingSnapshot = snapshot(missingDate);
    const base = {
      trade_date: missingDate,
      snapshot_id: missingSnapshot.snapshot_id,
      content_hash: "e".repeat(64),
      preclose_content_hash: missingSnapshot.content_hash,
      formal_content_hash: "f".repeat(64),
      status: "changed",
      pools: {},
    };
    const write = (body: Record<string, unknown>) => SELF.fetch(request("/api/preclose/reconciliation", {
      method: "PUT",
      headers: { authorization: `Bearer ${TOKEN}`, "content-type": "application/json" },
      body: JSON.stringify(body),
    }));

    expect((await write(base)).status).toBe(400);

    const date = "2026-09-17";
    const storedSnapshot = snapshot(date);
    await put(storedSnapshot);
    const valid = {
      ...base,
      trade_date: date,
      snapshot_id: storedSnapshot.snapshot_id,
      preclose_content_hash: storedSnapshot.content_hash,
    };
    expect((await write({ ...valid, snapshot_id: `${storedSnapshot.snapshot_id}-wrong` })).status).toBe(400);
    expect((await write({ ...valid, preclose_content_hash: "b".repeat(64) })).status).toBe(400);
    expect((await write(valid)).status).toBe(201);
  });

  it("seals a snapshot after reconciliation and fails closed for a legacy mismatch", async () => {
    const date = "2026-09-20";
    const storedSnapshot = snapshot(date, "a");
    await put(storedSnapshot);
    const reconciliation = {
      trade_date: date,
      snapshot_id: storedSnapshot.snapshot_id,
      content_hash: "e".repeat(64),
      preclose_content_hash: storedSnapshot.content_hash,
      formal_content_hash: "f".repeat(64),
      status: "unchanged",
      pools: {},
    };
    const write = await SELF.fetch(request("/api/preclose/reconciliation", {
      method: "PUT",
      headers: { authorization: `Bearer ${TOKEN}`, "content-type": "application/json" },
      body: JSON.stringify(reconciliation),
    }));
    expect(write.status).toBe(201);

    const replacement = snapshot(date, "b");
    expect((await put(replacement, { "if-match": '"1"' })).status).toBe(400);

    const stub = env.PRE_CLOSE_SNAPSHOT.getByName(date);
    await runInDurableObject(stub, async (_instance, state) => {
      state.storage.sql.exec(
        "UPDATE snapshots SET content_hash = ?, body = ? WHERE singleton = 1",
        replacement.content_hash,
        JSON.stringify(replacement),
      );
    });
    const read = await SELF.fetch(request(`/api/preclose/reconciliation?date=${date}`));
    expect(read.status).toBe(404);
  });
});
