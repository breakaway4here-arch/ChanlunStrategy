# ChanLun Engine Phase 5.1 Experiment Registry Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a versioned engine experiment registry so candidate variants are plugins, not a second ChanLun engine.

**Architecture:** Keep `analyze()` pinned to `LEGACY_PROVIDERS`. Add an opt-in experiment registry that builds provider bundles from `LEGACY_PROVIDERS` plus named overrides. Existing `CANDIDATE_ANALYZERS` remains compatible while new code uses experiment metadata and bundle factories.

**Tech Stack:** Python standard library, `dataclasses`, `unittest`, existing `chanlun.engine_pipeline` provider bundle.

---

## Scope

This phase builds infrastructure only.

Do:
- Create a registry for experiment definitions.
- Support single-module provider overrides.
- Preserve current `analyze()` behavior and current dual compare CLI behavior.
- Keep current candidate functions available for compatibility.

Do not:
- Change production `analyze()`.
- Add business return metrics.
- Add new strategy logic.
- Remove existing candidate analyzers.

## Current Baseline

- `chanlun/engine_pipeline.py` already has `EngineProviders`, `LEGACY_PROVIDERS`, and `with_provider_overrides`.
- `chanlun/engine_candidate.py` has `_CANDIDATE_PROVIDER_OVERRIDES` and `CANDIDATE_ANALYZERS`.
- `scripts/compare_chan_engine_dual.py` selects from `CANDIDATE_ANALYZERS`.

## Task 1: Add Experiment Definition Model

**Files:**
- Create: `chanlun/engine_experiments.py`
- Test: `tests/test_engine_experiments.py`

**Step 1: Write failing tests**

Create tests for:
- `get_experiment("legacy")` returns a baseline definition.
- `get_experiment("signal_v1")` returns metadata with `module == "signal"`.
- `build_experiment_provider_bundle("signal_v1")` returns an `EngineProviders` instance.
- Unknown experiment raises `ValueError`.
- Production `LEGACY_PROVIDERS` object is not mutated.

Run:

```bash
python3 -m unittest tests.test_engine_experiments -v
```

Expected: fail because module does not exist.

**Step 2: Implement minimal model**

Create `ExperimentDefinition`:

```python
@dataclass(frozen=True)
class ExperimentDefinition:
    name: str
    module: str
    description: str
    overrides: dict
    risk: str = "low"
```

Add:
- `EXPERIMENT_REGISTRY`
- `get_experiment(name)`
- `list_experiments()`
- `build_experiment_provider_bundle(name)`

Use `with_provider_overrides(LEGACY_PROVIDERS, **definition.overrides)`.

**Step 3: Register parity experiments**

Register:
- `legacy`
- `macd_v1`
- `inclusion_v1`
- `fractal_v1`
- `stroke_v1`
- `segment_v1`
- `pivot_v1`
- `trend_v1`
- `divergence_v1`
- `signal_v1`
- `all_v1`

The `_v1` variants should point to existing candidate providers from `engine_candidate.py`.

**Step 4: Verify tests pass**

Run:

```bash
python3 -m unittest tests.test_engine_experiments -v
```

Expected: pass.

## Task 2: Make Candidate Analyzers Use Registry

**Files:**
- Modify: `chanlun/engine_candidate.py`
- Test: `tests/test_engine_experiments.py`
- Existing tests: `tests/test_chan_engine_candidate_*_script.py`

**Step 1: Replace candidate bundle construction**

Update `candidate_provider_bundle(candidate_name)` to map legacy names to experiment names:

```python
_LEGACY_CANDIDATE_TO_EXPERIMENT = {
    "macd": "macd_v1",
    "signal": "signal_v1",
}
```

Then delegate to `build_experiment_provider_bundle`.

Keep external behavior:
- `candidate_provider_bundle("signal")` still works.
- `CANDIDATE_ANALYZERS["signal"]` still works.
- `--candidate signal` still works.

**Step 2: Preserve all-candidate behavior**

`all_candidate_provider_bundle()` may either remain local or delegate to `all_v1`. Prefer delegating to the registry if it does not create import cycles.

**Step 3: Verify compatibility**

Run:

```bash
python3 -m unittest tests.test_engine_experiments tests.test_chan_engine_candidate_signal_script tests.test_chan_engine_candidate_all_script -v
```

Expected: pass.

## Task 3: Add Experiment-Aware CLI Option

**Files:**
- Modify: `scripts/compare_chan_engine_dual.py`
- Test: create or extend `tests/test_chan_engine_experiment_script.py`

**Step 1: Add tests**

Test that:
- `--experiment signal_v1` runs and writes JSON.
- report summary contains `"experiment": "signal_v1"`.
- existing `--candidate signal` still works.
- `--candidate` and `--experiment` cannot both be provided.

**Step 2: Implement CLI**

Add optional `--experiment`.

When provided:
- Build a candidate analyzer from `build_experiment_provider_bundle(experiment_name)`.
- Run through `analyze_dual`.
- Put experiment metadata into report summary.

Keep existing `--candidate` output compatible.

**Step 3: Verify**

Run:

```bash
python3 -m unittest tests.test_chan_engine_experiment_script tests.test_chan_engine_dual_script tests.test_chan_engine_candidate_signal_script -v
python3 scripts/compare_chan_engine_dual.py --experiment signal_v1 --output /tmp/chan_engine_signal_v1.json
```

Expected:
- tests pass
- script exits 0 for parity experiments
- JSON summary includes `experiment`.

## Final Verification

Run:

```bash
python3 -m py_compile chanlun/engine_experiments.py chanlun/engine_candidate.py scripts/compare_chan_engine_dual.py
python3 -m unittest tests.test_engine_experiments tests.test_chan_engine_dual_script tests.test_chan_engine_candidate_signal_script tests.test_chan_engine_candidate_all_script tests.test_chan_engine_experiment_script -v
python3 -m unittest discover tests
```

Expected:
- all tests pass
- no production `analyze()` behavior changes
- `git diff` shows infrastructure only

## Commit

```bash
git add chanlun/engine_experiments.py chanlun/engine_candidate.py scripts/compare_chan_engine_dual.py tests/test_engine_experiments.py tests/test_chan_engine_experiment_script.py
git commit -m "feat: add engine experiment registry"
```
