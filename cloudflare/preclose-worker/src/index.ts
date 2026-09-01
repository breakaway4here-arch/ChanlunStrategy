import { DurableObject } from "cloudflare:workers";

const POOL_KEYS = ["main", "h4_t3", "acceleration"] as const;
const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;
const HASH_PATTERN = /^[a-f0-9]{64}$/;
const CODE_PATTERN = /^\d{6}$/;
const EXPLICIT_TIMEZONE_PATTERN = /(?:Z|[+-]\d{2}:\d{2})$/;
const NO_STORE = { "cache-control": "no-store" };

type PoolKey = (typeof POOL_KEYS)[number];

export interface PrecloseCandidate {
  code: string;
  name: string;
  reference_price: number;
  [key: string]: unknown;
}

export interface PrecloseSnapshotBody {
  schema_version: string;
  strategy_version: string;
  mode: string;
  trade_date: string;
  snapshot_id: string;
  content_hash: string;
  source_sha: string;
  as_of: string;
  generated_at: string;
  expires_at: string;
  status: string;
  is_final: false;
  affects_formal: false;
  pools: Record<PoolKey, PrecloseCandidate[]>;
  diagnostics?: unknown;
  [key: string]: unknown;
}

interface WorkerEnv {
  ALLOWED_ORIGINS?: string;
  PRECLOSE_ENABLED?: string;
  PRE_CLOSE_WRITE_TOKEN?: string;
  PRE_CLOSE_SNAPSHOT: DurableObjectNamespace<PrecloseSnapshot>;
}

interface StoredRow {
  revision: number;
  content_hash: string;
  body: string;
}

interface MutationResult {
  ok: boolean;
  status: "created" | "updated" | "idempotent" | "precondition_failed";
  revision: number;
}

interface PublicReadResult {
  revision: number;
  value: unknown;
}

interface PublicReadStub {
  getPublicSnapshot(nowMs?: number): Promise<PublicReadResult | null>;
  getReconciliation(): Promise<PublicReadResult | null>;
}

function isCanonicalDate(value: unknown): value is string {
  if (typeof value !== "string" || !DATE_PATTERN.test(value)) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
}

function isIsoOnShanghaiDate(value: unknown, date: string): value is string {
  if (typeof value !== "string" || !EXPLICIT_TIMEZONE_PATTERN.test(value)) return false;
  const parsed = Date.parse(value);
  if (Number.isNaN(parsed)) return false;
  return new Date(parsed + 8 * 60 * 60 * 1000).toISOString().slice(0, 10) === date;
}

function isExactShanghaiExpiry(value: unknown, date: string): value is string {
  return isIsoOnShanghaiDate(value, date)
    && Date.parse(value) === Date.parse(`${date}T14:56:30+08:00`);
}

function isObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function normalizeCandidate(value: unknown): PrecloseCandidate | null {
  if (!isObject(value)) return null;
  const code = typeof value.code === "string" ? value.code.trim() : "";
  const name = typeof value.name === "string" ? value.name.trim() : "";
  const referencePrice = Number(value.reference_price);
  if (!CODE_PATTERN.test(code) || !name || !Number.isFinite(referencePrice) || referencePrice <= 0) {
    return null;
  }
  return { code, name, reference_price: Math.round(referencePrice * 100) / 100 };
}

function normalizePools(value: unknown): Record<PoolKey, PrecloseCandidate[]> | null {
  if (!isObject(value)) return null;
  const pools = {} as Record<PoolKey, PrecloseCandidate[]>;
  for (const key of POOL_KEYS) {
    const rows = value[key];
    if (!Array.isArray(rows)) return null;
    const normalized = rows.map(normalizeCandidate);
    if (normalized.some((row) => row === null)) return null;
    pools[key] = normalized as PrecloseCandidate[];
  }
  return pools;
}

function normalizeSnapshot(value: unknown): PrecloseSnapshotBody | null {
  if (!isObject(value)) return null;
  const tradeDate = value.trade_date;
  if (!isCanonicalDate(tradeDate)) return null;
  const pools = normalizePools(value.pools);
  if (!pools) return null;
  const statuses = new Set(["available", "empty", "failed", "deadline_exceeded", "not_run"]);
  if (
    value.schema_version !== "preclose-selection-v1"
    || value.strategy_version !== "preclose-1445-v2"
    || value.mode !== "preclose_advisory"
    || typeof value.snapshot_id !== "string"
    || typeof value.content_hash !== "string"
    || !HASH_PATTERN.test(value.content_hash)
    || value.snapshot_id !== `preclose:${tradeDate}:${value.content_hash.slice(0, 16)}`
    || typeof value.source_sha !== "string"
    || !value.source_sha.trim()
    || !isIsoOnShanghaiDate(value.as_of, tradeDate)
    || !isIsoOnShanghaiDate(value.generated_at, tradeDate)
    || !isExactShanghaiExpiry(value.expires_at, tradeDate)
    || !statuses.has(String(value.status))
    || value.is_final !== false
    || value.affects_formal !== false
  ) {
    return null;
  }
  return {
    ...value,
    schema_version: "preclose-selection-v1",
    strategy_version: "preclose-1445-v2",
    mode: "preclose_advisory",
    trade_date: tradeDate,
    snapshot_id: value.snapshot_id,
    content_hash: value.content_hash.toLowerCase(),
    source_sha: value.source_sha.trim(),
    as_of: value.as_of,
    generated_at: value.generated_at,
    expires_at: value.expires_at,
    status: String(value.status),
    is_final: false,
    affects_formal: false,
    pools,
  } as PrecloseSnapshotBody;
}

function publicSnapshot(snapshot: PrecloseSnapshotBody, revision: number, now: number) {
  const expired = now >= Date.parse(snapshot.expires_at);
  const hasRows = POOL_KEYS.some((key) => snapshot.pools[key].length > 0);
  const available = snapshot.status === "available" && hasRows && !expired;
  const replayable = snapshot.status === "available" && expired;
  const showPools = available || replayable;
  const pools = {} as Record<PoolKey, PrecloseCandidate[]>;
  for (const key of POOL_KEYS) pools[key] = showPools ? snapshot.pools[key].map(normalizeCandidate).filter(Boolean) as PrecloseCandidate[] : [];
  return {
    schema_version: snapshot.schema_version,
    strategy_version: snapshot.strategy_version,
    mode: snapshot.mode,
    trade_date: snapshot.trade_date,
    snapshot_id: snapshot.snapshot_id,
    content_hash: snapshot.content_hash,
    source_sha: snapshot.source_sha,
    as_of: snapshot.as_of,
    generated_at: snapshot.generated_at,
    expires_at: snapshot.expires_at,
    status: expired ? "expired" : available ? "available" : "empty",
    is_final: false,
    affects_formal: false,
    revision,
    pools,
    message: expired
      ? "预跑已封存，仅供回看；14:57后不再依据预跑清单新增动作"
      : available ? "14:56:30前有效" : "本期未选出推荐票",
  };
}

function snapshotContentProjection(snapshot: PrecloseSnapshotBody) {
  const pools = {} as Record<PoolKey, PrecloseCandidate[]>;
  for (const key of POOL_KEYS) pools[key] = snapshot.pools[key];
  return {
    schema_version: snapshot.schema_version,
    mode: snapshot.mode,
    strategy_version: snapshot.strategy_version,
    trade_date: snapshot.trade_date,
    as_of: snapshot.as_of,
    expires_at: snapshot.expires_at,
    status: snapshot.status,
    is_final: snapshot.is_final,
    affects_formal: snapshot.affects_formal,
    source_sha: snapshot.source_sha,
    pools,
  };
}

function stableJson(value: unknown): string {
  if (value === undefined || value === null) return "null";
  if (Array.isArray(value)) return `[${value.map(stableJson).join(",")}]`;
  if (isObject(value)) {
    return `{${Object.keys(value).sort().map((key) => (
      `${JSON.stringify(key)}:${stableJson(value[key])}`
    )).join(",")}}`;
  }
  return JSON.stringify(value);
}

function reconciliationContentProjection(value: Record<string, unknown>) {
  return {
    schema_version: value.schema_version,
    trade_date: value.trade_date,
    snapshot_id: value.snapshot_id,
    preclose_content_hash: value.preclose_content_hash,
    formal_content_hash: value.formal_content_hash,
    status: value.status,
    pools: value.pools,
  };
}

function normalizeDiffList(value: unknown): unknown[] {
  if (!Array.isArray(value)) return [];
  return value.slice(0, 100).map((item) => {
    const candidate = normalizeCandidate(item);
    if (candidate) return candidate;
    return typeof item === "string" ? item.slice(0, 80) : "";
  }).filter(Boolean);
}

function publicReconciliation(value: unknown, revision: number) {
  if (!isObject(value)) return null;
  const pools: Record<string, unknown> = {};
  if (isObject(value.pools)) {
    for (const key of POOL_KEYS) {
      const source = isObject(value.pools[key]) ? value.pools[key] as Record<string, unknown> : {};
      pools[key] = {
        retained: normalizeDiffList(source.retained),
        added_after_close: normalizeDiffList(source.added_after_close),
        removed_after_close: normalizeDiffList(source.removed_after_close),
        unchanged: source.unchanged === true,
      };
    }
  }
  return {
    content_hash: typeof value.content_hash === "string" ? value.content_hash : undefined,
    trade_date: value.trade_date,
    snapshot_id: typeof value.snapshot_id === "string" ? value.snapshot_id : undefined,
    preclose_content_hash: value.preclose_content_hash,
    formal_content_hash: value.formal_content_hash,
    status: value.status,
    generated_at: typeof value.generated_at === "string" ? value.generated_at : undefined,
    revision,
    pools,
  };
}

async function sha256Text(value: string): Promise<string> {
  const bytes = new TextEncoder().encode(value);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

export class PrecloseSnapshot extends DurableObject<WorkerEnv> {
  constructor(ctx: DurableObjectState, env: WorkerEnv) {
    super(ctx, env);
    this.ctx.storage.sql.exec(`
      CREATE TABLE IF NOT EXISTS snapshots (
        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
        revision INTEGER NOT NULL,
        content_hash TEXT NOT NULL,
        body TEXT NOT NULL,
        updated_at TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS reconciliations (
        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
        revision INTEGER NOT NULL,
        content_hash TEXT NOT NULL,
        body TEXT NOT NULL,
        updated_at TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS audit_versions (
        kind TEXT NOT NULL,
        revision INTEGER NOT NULL,
        content_hash TEXT NOT NULL,
        body TEXT NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY (kind, revision)
      );
    `);
  }

  private row(table: "snapshots" | "reconciliations"): StoredRow | null {
    const rows = this.ctx.storage.sql.exec(
      `SELECT revision, content_hash, body FROM ${table} WHERE singleton = 1`,
    ).toArray() as unknown as StoredRow[];
    return rows[0] ?? null;
  }

  private write(
    table: "snapshots" | "reconciliations",
    kind: "snapshot" | "reconciliation",
    body: string,
    contentHash: string,
    revision: number,
  ) {
    const now = new Date().toISOString();
    this.ctx.storage.sql.exec(
      `INSERT INTO ${table} (singleton, revision, content_hash, body, updated_at)
       VALUES (1, ?, ?, ?, ?)
       ON CONFLICT(singleton) DO UPDATE SET
         revision = excluded.revision,
         content_hash = excluded.content_hash,
         body = excluded.body,
         updated_at = excluded.updated_at`,
      revision, contentHash, body, now,
    );
    this.ctx.storage.sql.exec(
      `INSERT INTO audit_versions (kind, revision, content_hash, body, created_at)
       VALUES (?, ?, ?, ?, ?)`,
      kind, revision, contentHash, body, now,
    );
  }

  async putSnapshot(input: unknown, expectedRevision: number | null): Promise<MutationResult> {
    const snapshot = normalizeSnapshot(input);
    if (!snapshot) throw new Error("invalid snapshot contract");
    const current = this.row("snapshots");
    if (current) {
      const stored = JSON.parse(current.body) as PrecloseSnapshotBody;
      if (stored.snapshot_id === snapshot.snapshot_id && current.content_hash === snapshot.content_hash) {
        if (JSON.stringify(snapshotContentProjection(stored)) !== JSON.stringify(snapshotContentProjection(snapshot))) {
          throw new Error("snapshot content changed without a new content hash");
        }
        return { ok: true, status: "idempotent", revision: current.revision };
      }
    }
    if (this.row("reconciliations")) {
      throw new Error("snapshot is sealed after reconciliation");
    }
    if (current) {
      if (expectedRevision === null || expectedRevision !== current.revision) {
        return { ok: false, status: "precondition_failed", revision: current.revision };
      }
    } else if (expectedRevision !== null && expectedRevision !== 0) {
      return { ok: false, status: "precondition_failed", revision: 0 };
    }
    const revision = current ? current.revision + 1 : 1;
    this.write("snapshots", "snapshot", JSON.stringify(snapshot), snapshot.content_hash, revision);
    return { ok: true, status: current ? "updated" : "created", revision };
  }

  async getPublicSnapshot(nowMs = Date.now()) {
    const current = this.row("snapshots");
    if (!current) return null;
    return {
      revision: current.revision,
      value: publicSnapshot(JSON.parse(current.body) as PrecloseSnapshotBody, current.revision, nowMs),
    };
  }

  async putReconciliation(input: unknown, expectedRevision: number | null): Promise<MutationResult> {
    if (!isObject(input) || !isCanonicalDate(input.trade_date)) {
      throw new Error("invalid reconciliation contract");
    }
    if (
      typeof input.preclose_content_hash !== "string"
      || !HASH_PATTERN.test(input.preclose_content_hash)
      || typeof input.snapshot_id !== "string"
      || typeof input.content_hash !== "string"
      || !HASH_PATTERN.test(input.content_hash)
      || typeof input.formal_content_hash !== "string"
      || !HASH_PATTERN.test(input.formal_content_hash)
      || !new Set(["changed", "unchanged", "formal_pending"]).has(String(input.status))
    ) {
      throw new Error("invalid reconciliation contract");
    }
    const snapshotRow = this.row("snapshots");
    if (!snapshotRow) throw new Error("snapshot required before reconciliation");
    const storedSnapshot = JSON.parse(snapshotRow.body) as PrecloseSnapshotBody;
    if (
      storedSnapshot.trade_date !== input.trade_date
      || storedSnapshot.snapshot_id !== input.snapshot_id
      || snapshotRow.content_hash.toLowerCase() !== input.preclose_content_hash.toLowerCase()
    ) {
      throw new Error("reconciliation does not match stored snapshot");
    }
    const fingerprint = input.content_hash.toLowerCase();
    const current = this.row("reconciliations");
    if (current?.content_hash === fingerprint) {
      const stored = JSON.parse(current.body) as Record<string, unknown>;
      if (
        stableJson(reconciliationContentProjection(stored))
        !== stableJson(reconciliationContentProjection(input))
      ) {
        throw new Error("reconciliation content changed without a new content hash");
      }
      return { ok: true, status: "idempotent", revision: current.revision };
    }
    if (current && (expectedRevision === null || expectedRevision !== current.revision)) {
      return { ok: false, status: "precondition_failed", revision: current.revision };
    }
    const revision = current ? current.revision + 1 : 1;
    this.write("reconciliations", "reconciliation", JSON.stringify(input), fingerprint, revision);
    return { ok: true, status: current ? "updated" : "created", revision };
  }

  async getReconciliation() {
    const current = this.row("reconciliations");
    if (!current) return null;
    const snapshotRow = this.row("snapshots");
    if (!snapshotRow) return null;
    const reconciliation = JSON.parse(current.body) as Record<string, unknown>;
    const snapshot = JSON.parse(snapshotRow.body) as PrecloseSnapshotBody;
    if (
      reconciliation.trade_date !== snapshot.trade_date
      || reconciliation.snapshot_id !== snapshot.snapshot_id
      || String(reconciliation.preclose_content_hash).toLowerCase() !== snapshotRow.content_hash.toLowerCase()
    ) {
      return null;
    }
    return {
      revision: current.revision,
      value: publicReconciliation(reconciliation, current.revision),
    };
  }
}

function allowedOrigins(env: WorkerEnv): Set<string> {
  return new Set(String(env.ALLOWED_ORIGINS ?? "").split(",").map((value) => value.trim()).filter((value) => {
    if (!value || value === "*") return false;
    try {
      return new URL(value).origin === value;
    } catch {
      return false;
    }
  }));
}

function requestOrigin(request: Request, env: WorkerEnv): string | null {
  const origin = request.headers.get("origin");
  if (!origin) return null;
  return allowedOrigins(env).has(origin) ? origin : "";
}

function corsHeaders(origin: string | null): HeadersInit {
  if (!origin) return {};
  return {
    "access-control-allow-origin": origin,
    "access-control-allow-methods": "GET,PUT,OPTIONS",
    "access-control-allow-headers": "authorization,content-type,if-match,x-preclose-token",
    "access-control-expose-headers": "etag",
    "access-control-max-age": "86400",
    vary: "Origin",
  };
}

function jsonResponse(status: number, value: unknown, origin: string | null, extra: HeadersInit = {}) {
  return Response.json(value, {
    status,
    headers: {
      ...NO_STORE,
      ...corsHeaders(origin),
      ...extra,
    },
  });
}

async function timingSafeEqual(left: string, right: string): Promise<boolean> {
  const [leftHash, rightHash] = await Promise.all([sha256Text(left), sha256Text(right)]);
  let difference = left.length === right.length ? 0 : 1;
  for (let index = 0; index < leftHash.length; index += 1) {
    difference |= leftHash.charCodeAt(index) ^ rightHash.charCodeAt(index);
  }
  return difference === 0;
}

function suppliedToken(request: Request): string {
  const authorization = request.headers.get("authorization")?.trim() ?? "";
  if (authorization.toLowerCase().startsWith("bearer ")) return authorization.slice(7).trim();
  return request.headers.get("x-preclose-token")?.trim() ?? "";
}

async function authorized(request: Request, env: WorkerEnv): Promise<boolean> {
  const expected = env.PRE_CLOSE_WRITE_TOKEN?.trim() ?? "";
  return Boolean(expected) && timingSafeEqual(suppliedToken(request), expected);
}

function expectedRevision(request: Request, body: Record<string, unknown>): number | null {
  const header = request.headers.get("if-match")?.trim().replace(/^W\//, "").replace(/^"|"$/g, "");
  const source = header || body.revision;
  if (source === undefined || source === null || source === "") return null;
  const value = Number(source);
  return Number.isInteger(value) && value >= 0 ? value : Number.NaN;
}

async function parsedBody(request: Request): Promise<Record<string, unknown> | null> {
  try {
    const value = await request.json();
    return isObject(value) ? value : null;
  } catch {
    return null;
  }
}

function mutationResponse(result: MutationResult, origin: string | null) {
  if (!result.ok) {
    return jsonResponse(412, { error: "precondition failed", revision: result.revision }, origin, {
      etag: `"${result.revision}"`,
    });
  }
  return jsonResponse(result.status === "created" ? 201 : 200, {
    status: result.status,
    revision: result.revision,
  }, origin, { etag: `"${result.revision}"` });
}

export async function handleRequest(request: Request, env: WorkerEnv): Promise<Response> {
  const origin = requestOrigin(request, env);
  if (origin === "") return jsonResponse(403, { error: "origin not allowed" }, null);
  if (env.PRECLOSE_ENABLED !== "true") return jsonResponse(503, { error: "pre-close service disabled" }, origin);
  if (request.method === "OPTIONS") {
    if (!origin) return jsonResponse(403, { error: "origin required" }, null);
    return new Response(null, { status: 204, headers: { ...corsHeaders(origin), ...NO_STORE } });
  }

  const url = new URL(request.url);
  const isSnapshotWrite = url.pathname === "/api/preclose/snapshot" && request.method === "PUT";
  const isReconciliationWrite = url.pathname === "/api/preclose/reconciliation" && request.method === "PUT";
  if (isSnapshotWrite || isReconciliationWrite) {
    if (!(await authorized(request, env))) return jsonResponse(401, { error: "unauthorized" }, origin);
    const body = await parsedBody(request);
    if (!body || !isCanonicalDate(body.trade_date)) return jsonResponse(400, { error: "invalid request" }, origin);
    const revision = expectedRevision(request, body);
    if (Number.isNaN(revision)) return jsonResponse(400, { error: "invalid revision" }, origin);
    const stub = env.PRE_CLOSE_SNAPSHOT.getByName(body.trade_date);
    try {
      const result = isSnapshotWrite
        ? await stub.putSnapshot(body, revision)
        : await stub.putReconciliation(body, revision);
      return mutationResponse(result, origin);
    } catch {
      return jsonResponse(400, { error: "invalid contract" }, origin);
    }
  }

  const isSnapshotRead = url.pathname === "/api/preclose/latest" && request.method === "GET";
  const isReconciliationRead = url.pathname === "/api/preclose/reconciliation" && request.method === "GET";
  if (isSnapshotRead || isReconciliationRead) {
    const tradeDate = url.searchParams.get("date");
    if (!isCanonicalDate(tradeDate)) return jsonResponse(400, { error: "invalid date" }, origin);
    const stub = env.PRE_CLOSE_SNAPSHOT.getByName(tradeDate) as unknown as PublicReadStub;
    if (isSnapshotRead) {
      const result = await stub.getPublicSnapshot(Date.now());
      if (!result?.value) return jsonResponse(404, { error: "not found", trade_date: tradeDate }, origin);
      return jsonResponse(200, result.value, origin, { etag: `"${result.revision}"` });
    }
    const result = await stub.getReconciliation();
    if (!result?.value) return jsonResponse(404, { error: "not found", trade_date: tradeDate }, origin);
    return jsonResponse(200, result.value, origin, { etag: `"${result.revision}"` });
  }

  return jsonResponse(404, { error: "not found" }, origin);
}

export default { fetch: handleRequest };
