# On-Demand Top10 Cloudflare + GitHub Actions Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a password-protected button on the static report page that triggers an on-demand GitHub Actions Top10 snapshot through Cloudflare Worker, then displays the finished result.

**Architecture:** GitHub Pages remains static. The page calls a Cloudflare Worker, the Worker validates a trigger password and dispatches a GitHub Actions workflow, the workflow runs the Python snapshot script and posts the result back to the Worker, and the Worker stores job state in Cloudflare KV for polling.

**Tech Stack:** Vanilla JS/CSS report UI, Python unittest/script, GitHub Actions `workflow_dispatch`, Cloudflare Workers, Cloudflare KV.

---

## Requirements

- The report page must expose an on-demand Top10 action.
- Clicking the action must require a password. The first fixed password is `1122`, but it must live only in Cloudflare Worker secret `TRIGGER_PASSWORD`, not in frontend source or repo config.
- Frontend requests must go only to Cloudflare Worker endpoints.
- Cloudflare Worker must trigger GitHub Actions with `workflow_dispatch`; GitHub token must be stored as Worker secret.
- The NAS must not be exposed.
- No 1-5 minute scheduled upload is required. Work happens only after the user clicks the button.
- GitHub Actions must produce a compact Top10 JSON snapshot and callback the Worker.
- Callback writes must require `CALLBACK_TOKEN`.
- Worker state must include lock/duplicate protection, job status, timeout-safe responses, CORS, and JSON error responses.
- Final answer must tell the user exactly what to configure in GitHub and Cloudflare.

## Runtime Flow

```text
docs report button
  -> POST https://<worker-host>/api/top10/run { "password": "<user input>" }
  -> Worker checks TRIGGER_PASSWORD and top10:lock
  -> Worker dispatches .github/workflows/top10-on-demand.yml with job_id
  -> Actions runs python3 run.py --preview
  -> Actions runs scripts/generate_top10_snapshot.py --data-dir docs-preview/data --job-id "$job_id" --output "$RUNNER_TEMP/top10.json"
  -> Actions POSTs result to /api/top10/callback with CALLBACK_TOKEN
  -> Worker stores top10:job:{job_id} and top10:latest in KV
  -> frontend polls GET /api/top10/status?job_id=...
```

## Deliverables

### Task 1: Cloudflare Worker API

**Files:**
- Create: `cloudflare/top10-worker/src/index.js`
- Create: `cloudflare/top10-worker/wrangler.jsonc`
- Create: `cloudflare/top10-worker/test/top10-worker.test.js`
- Create: `cloudflare/top10-worker/package.json`
- Create: `cloudflare/top10-worker/README.md`

**Behavior:**
- `OPTIONS *`: CORS preflight.
- `POST /api/top10/run`: parse JSON, validate `password`, reject wrong password with `401`, reject concurrent unexpired lock with `409`, create `job_id`, write queued/running state to KV, call GitHub workflow dispatch, return `{ job_id, status }`.
- `GET /api/top10/status?job_id=...`: return job state, or timeout if stale running state exceeds configured timeout.
- `POST /api/top10/callback`: validate `CALLBACK_TOKEN`, accept success/failure payload from GitHub Actions, clear lock, write final state and `top10:latest`.

**Secrets / vars:**
- `TRIGGER_PASSWORD`
- `GITHUB_TOKEN`
- `GITHUB_OWNER`
- `GITHUB_REPO`
- `GITHUB_WORKFLOW_ID`
- `GITHUB_REF`
- `CALLBACK_TOKEN`
- `ALLOWED_ORIGINS`

**Tests:**
- Wrong trigger password returns `401`.
- Correct password dispatches GitHub and writes KV state.
- Existing lock returns `409`.
- Wrong callback token returns `401`.
- Successful callback writes `done` and clears lock.

### Task 2: GitHub Actions + Python Top10 Snapshot

**Files:**
- Create: `.github/workflows/top10-on-demand.yml`
- Create: `scripts/generate_top10_snapshot.py`
- Create: `tests/test_generate_top10_snapshot.py`

**Behavior:**
- Workflow is manually dispatchable by Worker only through GitHub API.
- Workflow accepts `job_id`.
- Script outputs stable JSON with:
  - `job_id`
  - `generated_at`
  - `source`
  - `items`
  - optional `diagnostics`
- Workflow first runs a fresh preview report in CI, then the script reads `docs-preview/data` and prefers workspace highlights for the compact Top10 payload.
- If live preview generation fails, workflow returns a failed callback instead of silently reusing stale static data.
- Workflow always callbacks Worker, including failure state.

**Tests:**
- Script can build Top10 JSON from a fixture/latest docs data file.
- Items are capped at 10.
- Required fields are present.

### Task 3: Frontend On-Demand Top10 Button

**Files:**
- Modify: `chanlun/report_assets/report-v2.js`
- Modify: `chanlun/report_assets/report-v2.css`
- Modify generated/copy assets under `docs/assets/` after source asset edits.
- Modify: `tests/test_report_generator.py`

**Behavior:**
- Add a compact on-demand Top10 control near the report action/header area.
- Prompt or inline input for password on click.
- Do not hard-code `1122` anywhere in frontend source or generated docs assets.
- Worker endpoint should come from `window.CHANLUN_BOOTSTRAP.top10ApiBase` or equivalent config field; if unset, the control is disabled or hidden with a non-noisy unavailable state.
- Call `/api/top10/run`, poll `/api/top10/status`, render queued/running/done/failed.
- Render result fields: rank, code, name, score, action, reason, generated time.

**Tests:**
- Report JS includes Top10 control logic.
- Generated HTML/JS does not include literal `1122`.
- Existing report generator tests still pass.

### Task 4: Integration Verification

**Commands:**
- `node cloudflare/top10-worker/test/top10-worker.test.js`
- `python3 -m unittest tests.test_generate_top10_snapshot`
- `python3 -m unittest tests.test_report_generator`
- `python3 -m py_compile scripts/generate_top10_snapshot.py`
- `git diff --check`

**Manual configuration output:**
- GitHub secrets and Actions settings.
- Cloudflare KV namespace, Worker secrets, and deploy commands.
- Frontend `top10ApiBase` configuration location.

## Security Notes

- Frontend password is user-entered only; the fixed value `1122` is a Worker secret.
- GitHub token is Worker-only and should be fine-grained with Actions write permission for this repo.
- Callback token is shared between GitHub Actions secret and Worker secret.
- Worker should not log password or callback token.
- CORS should allow only the GitHub Pages origin and local development origins if needed.

## Non-Goals

- No NAS API exposure.
- No always-on market polling.
- No Cloudflare-side rewrite of the Python strategy.
- No persistent user account system.
