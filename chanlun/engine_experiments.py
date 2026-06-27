"""Experiment registry for opt-in ChanLun pipeline variants."""

from dataclasses import dataclass

from .engine_candidate import (
    build_segments_candidate,
    build_strokes_candidate,
    calc_macd_candidate,
    check_divergence_candidate,
    classify_trend_candidate,
    find_fractals_candidate,
    find_pivots_candidate,
    inclusion_process_candidate,
    locate_buy_sell_points_candidate,
)
from .engine_signal_experiments import (
    locate_buy_sell_points_p0_distance_guard,
    locate_buy_sell_points_p0_p1_guard,
    locate_buy_sell_points_delay1_by_type_guard,
    locate_buy_sell_points_p1_confirmation_guard,
)
from .engine_pipeline import LEGACY_PROVIDERS, EngineProviders, with_provider_overrides


@dataclass(frozen=True)
class ExperimentDefinition:
    name: str
    module: str
    description: str
    overrides: dict
    risk: str = "low"


EXPERIMENT_REGISTRY = {
    "legacy": ExperimentDefinition(
        name="legacy",
        module="legacy",
        description="Legacy production pipeline with no overrides.",
        overrides={},
    ),
    "macd_v1": ExperimentDefinition(
        name="macd_v1",
        module="macd",
        description="Candidate MACD implementation.",
        overrides={"macd_provider": calc_macd_candidate},
    ),
    "inclusion_v1": ExperimentDefinition(
        name="inclusion_v1",
        module="inclusion",
        description="Candidate inclusion implementation.",
        overrides={"inclusion_provider": inclusion_process_candidate},
    ),
    "fractal_v1": ExperimentDefinition(
        name="fractal_v1",
        module="fractal",
        description="Candidate fractal implementation.",
        overrides={"fractal_provider": find_fractals_candidate},
    ),
    "stroke_v1": ExperimentDefinition(
        name="stroke_v1",
        module="stroke",
        description="Candidate stroke implementation.",
        overrides={"stroke_provider": build_strokes_candidate},
    ),
    "segment_v1": ExperimentDefinition(
        name="segment_v1",
        module="segment",
        description="Candidate segment implementation.",
        overrides={"segment_provider": build_segments_candidate},
    ),
    "pivot_v1": ExperimentDefinition(
        name="pivot_v1",
        module="pivot",
        description="Candidate pivot implementation.",
        overrides={"pivot_provider": find_pivots_candidate},
    ),
    "trend_v1": ExperimentDefinition(
        name="trend_v1",
        module="trend",
        description="Candidate trend classification implementation.",
        overrides={"trend_provider": classify_trend_candidate},
    ),
    "divergence_v1": ExperimentDefinition(
        name="divergence_v1",
        module="divergence",
        description="Candidate divergence implementation.",
        overrides={"divergence_provider": check_divergence_candidate},
    ),
    "signal_v1": ExperimentDefinition(
        name="signal_v1",
        module="signal",
        description="Candidate signal implementation.",
        overrides={"signal_provider": locate_buy_sell_points_candidate},
    ),
    "signal_p0_distance_guard": ExperimentDefinition(
        name="signal_p0_distance_guard",
        module="signal",
        description="Guard buy points by distance_from_reference_pct for 底背驰候选.",
        overrides={"signal_provider": locate_buy_sell_points_p0_distance_guard},
        risk="medium",
    ),
    "signal_p1_confirmation_guard": ExperimentDefinition(
        name="signal_p1_confirmation_guard",
        module="signal",
        description="Guard buy points by confirmation pattern.",
        overrides={"signal_provider": locate_buy_sell_points_p1_confirmation_guard},
        risk="medium",
    ),
    "signal_p0_p1_guard": ExperimentDefinition(
        name="signal_p0_p1_guard",
        module="signal",
        description="Apply both distance and confirmation guards to signal buy points.",
        overrides={"signal_provider": locate_buy_sell_points_p0_p1_guard},
        risk="medium",
    ),
    "signal_delay1_by_type_guard": ExperimentDefinition(
        name="signal_delay1_by_type_guard",
        module="signal",
        description="Delay-confirm only 底背驰候选 signals by type, no-op for others.",
        overrides={
            "signal_provider": locate_buy_sell_points_delay1_by_type_guard,
        },
        risk="medium",
    ),
    "all_v1": ExperimentDefinition(
        name="all_v1",
        module="all",
        description="All candidate implementations in one provider bundle.",
        overrides={
            "macd_provider": calc_macd_candidate,
            "inclusion_provider": inclusion_process_candidate,
            "fractal_provider": find_fractals_candidate,
            "stroke_provider": build_strokes_candidate,
            "segment_provider": build_segments_candidate,
            "pivot_provider": find_pivots_candidate,
            "trend_provider": classify_trend_candidate,
            "divergence_provider": check_divergence_candidate,
            "signal_provider": locate_buy_sell_points_candidate,
        },
    ),
}


def get_experiment(name):
    try:
        return EXPERIMENT_REGISTRY[name]
    except KeyError as exc:
        raise ValueError(f"unknown experiment: {name}") from exc


def list_experiments():
    return tuple(EXPERIMENT_REGISTRY.keys())


def build_experiment_provider_bundle(name) -> EngineProviders:
    definition = get_experiment(name)
    if not definition.overrides:
        return LEGACY_PROVIDERS
    return with_provider_overrides(LEGACY_PROVIDERS, **definition.overrides)
