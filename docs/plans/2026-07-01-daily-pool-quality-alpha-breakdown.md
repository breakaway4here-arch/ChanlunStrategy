# Daily Pool Quality Alpha Implementation Breakdown

> **For Codex:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Add bounded pool-quality alpha to existing daily Chanlun ranking without changing pool discovery or introducing a new framework.

**Architecture:** Existing `pool -> scoring -> ranking -> report` flow stays intact. `chanlun.report_view_model` derives `pool_quality` from existing candidate fields and passes it through `compute_opportunity_score()` context; `chanlun.scoring_engine` converts that payload into a small capped alpha bonus; existing offline backtest tooling reports T+1 impact.

**Tech Stack:** Python stdlib, `unittest`, existing report JSON under `docs/data`, existing scoring/report modules.

---

## Constraints

- Do not add a new stock pool, feature layer, backtest framework, or scoring pipeline split.
- Do not change `compute_opportunity_score()` signature.
- Do not touch `scripts/joinquant_alpha_weight_experiment.py`.
- Do not introduce network-dependent tests.
- Pool quality is a soft positive alpha only; no hard filtering in v1.

## Task A: Pool Quality Feature Extraction And Report Diagnostics

**Model:** `gpt-5.3-codex-spark`

**Files:**
- Modify: `chanlun/report_view_model.py`
- Test: `tests/test_report_view_model.py`

**Implementation steps:**

1. Add `_build_pool_quality_features(item, source)` near other report-view helpers.
2. Derive from existing fields only:
   - `code`
   - `volumes`
   - `volume_ratio`
   - `change_pct`
   - `sector_rank`
   - `sector_flow`
3. Compute a dict with:
   - `volume20`
   - `volume_ratio20`
   - `liquidity_score`
   - `growth_board_score`
   - `growth_board_label`
   - `sector_quality_score`
   - `pool_quality_score`
   - `pool_quality_tags`
4. Missing data must return neutral zeros and empty tags, not raise.
5. Pass the dict into `compute_opportunity_score()` via context:
   - `{"alpha_features": {"pool_quality": pool_quality}}`
6. Add top-level `"pool_quality"` to each workspace item.
7. Preserve existing sort field names and view shapes.

**Acceptance tests:**

- Existing report view tests still pass.
- New tests prove:
  - growth board tags for `300`, `688`, `002`.
  - no negative score for `60` / `000`.
  - missing volume does not crash and returns neutral liquidity.
  - workspace item exposes `pool_quality`.
  - rank trace includes pool-quality fields after Task B is integrated.

## Task B: Bounded Pool Quality Bonus

**Model:** `gpt-5.3-codex-spark`

**Files:**
- Modify: `chanlun/scoring_engine.py`
- Test: `tests/test_scoring_engine.py`

**Implementation steps:**

1. Add `_score_pool_quality_bonus(pool_quality)`.
2. Read `pool_quality` from resolved alpha features.
3. Bonus is positive-only and bounded:
   - liquidity: max `+1.2`
   - growth board: max `+1.0`
   - sector quality: max `+0.8`
   - total pool bonus: max `+3.0`
4. Continue to cap total alpha bonus with `ALPHA_BONUS_LIMIT`.
5. Include diagnostics in trace:
   - `pool_quality_bonus`
   - `pool_quality_score`
   - `pool_quality_tags`

**Acceptance tests:**

- `alpha_enabled=False` remains identical.
- Missing `pool_quality` remains identical.
- Valid `pool_quality` adds a small positive score.
- Extreme score values are clamped.
- `ALPHA_BONUS_LIMIT` still applies.

## Task C: Lightweight T+1 Evaluation

**Model:** `gpt-5.3-codex-spark`

**Files:**
- Prefer modifying: `scripts/backtest_scoring_alpha_impact.py`
- Test or smoke: existing script invocation only

**Implementation steps:**

1. Reuse existing offline docs/data snapshot loading and kline cache.
2. Add optional T+1-oriented output without adding a new framework.
3. Compare `alpha_enabled=False` vs current pool-quality alpha.
4. Focus on:
   - `highlights`
   - `main`
   - `acceleration`
   - `luojie`
5. Report:
   - mean T+1 return
   - win rate
   - median T+1 return
   - worst T+1 return
   - evaluated sample count
   - skipped no-next-day count
   - top ranking changed / switched-in sample summary when available

**Acceptance tests:**

- Script runs offline with `--min-forward-days 1`.
- Missing next-day rows are counted/skipped.
- Output clearly states baseline vs alpha and whether stable improvement exists.

## Main Agent Review And Verification

After workers return:

1. Review diff for forbidden changes:
   - no new pool module
   - no hard filter
   - no pipeline split
   - no network dependency
2. Run:

```bash
python3 -m unittest tests.test_report_view_model tests.test_scoring_engine -v
python3 -m unittest tests.test_daily_structure_pool tests.test_candidate_upgrade tests.test_fusion_admission tests.test_signal_recency tests.test_strong_startup tests.test_startup_labels -v
python3 -m py_compile chanlun/report_view_model.py chanlun/scoring_engine.py scripts/backtest_scoring_alpha_impact.py
git diff --check
```

3. Run evaluation:

```bash
python3 scripts/backtest_scoring_alpha_impact.py --min-forward-days 1
python3 scripts/backtest_scoring_alpha_impact.py --min-forward-days 3
```

4. Keep the change only if T+1 Top10 or main improves without worst-return deterioration.
