"""Candidate registry facade for building candidate analyzers and provider bundles."""

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from .engine_experiments import build_experiment_provider_bundle
from .engine_experiments import EXPERIMENT_REGISTRY, get_experiment
from .engine_pipeline import EngineProviders
from .engine_pipeline import analyze_with_provider_bundle


@dataclass(frozen=True)
class CandidateDefinition:
    name: str
    module: str
    experiment: str
    description: str = ""
    risk: str = "low"
    alias_of: Optional[str] = None


_LEGACY_ALIASES = {
    "macd": "macd_v1",
    "inclusion": "inclusion_v1",
    "fractal": "fractal_v1",
    "stroke": "stroke_v1",
    "segment": "segment_v1",
    "pivot": "pivot_v1",
    "trend": "trend_v1",
    "divergence": "divergence_v1",
    "signal": "signal_v1",
    "all": "all_v1",
}


def _make_candidates_from_experiments():
    registry: Dict[str, CandidateDefinition] = {}
    for name, experiment in EXPERIMENT_REGISTRY.items():
        if experiment.name == "legacy":
            continue
        registry[experiment.name] = CandidateDefinition(
            name=experiment.name,
            module=experiment.module,
            experiment=experiment.name,
            description=experiment.description,
            risk=experiment.risk,
            alias_of=None,
        )

    for alias, experiment_name in _LEGACY_ALIASES.items():
        experiment = get_experiment(experiment_name)
        registry[alias] = CandidateDefinition(
            name=alias,
            module=experiment.module,
            experiment=experiment.name,
            description="Legacy alias.",
            risk=experiment.risk,
            alias_of=experiment.name,
        )

    return registry


CANDIDATE_REGISTRY: Dict[str, CandidateDefinition] = _make_candidates_from_experiments()


def get_candidate_definition(name):
    try:
        return CANDIDATE_REGISTRY[name]
    except KeyError as exc:
        raise ValueError(f"unknown candidate: {name}") from exc


def list_candidate_definitions() -> Tuple[str, ...]:
    return tuple(CANDIDATE_REGISTRY.keys())


def build_candidate_provider_bundle(name) -> EngineProviders:
    definition = get_candidate_definition(name)
    return build_experiment_provider_bundle(definition.experiment)


def build_candidate_analyzer(candidate_name):
    providers = build_candidate_provider_bundle(candidate_name)

    def analyze_candidate(
        code,
        name,
        dates,
        opens,
        highs,
        lows,
        closes,
        volumes=None,
        amounts=None,
    ):
        if volumes is None and amounts is not None:
            volumes = amounts
        return analyze_with_provider_bundle(
            code,
            name,
            dates,
            opens,
            highs,
            lows,
            closes,
            volumes,
            providers=providers,
        )

    analyze_candidate.__name__ = f"analyze_with_candidate_{candidate_name}"
    return analyze_candidate
