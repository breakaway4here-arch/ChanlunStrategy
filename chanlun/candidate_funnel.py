"""Candidate funnel records for recall analysis and threshold experiments."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence


FUNNEL_STAGES = (
    "full_a",
    "eligible",
    "retrieval",
    "daily_channel",
    "minute30",
    "fusion",
    "display",
)

TERMINAL_STATES = ("main", "observe", "reject")

RAW_FEATURE_FIELDS = (
    "volume_ratio",
    "amount_ratio",
    "distance_3pct",
    "distance_12pct",
    "distance_from_reference_pct",
    "ma5",
    "ma10",
    "ma20",
    "ma_gap_pct",
    "ma_direction",
    "minute30_confirmations",
    "minute30_strength",
)

RAW_FEATURE_ALIASES = {
    "volume_ratio": ("volume_ratio", "volume_ratio_3v10"),
    "amount_ratio": (
        "amount_ratio",
        "amount_ratio_1v5",
        "turnover_amount_ratio",
    ),
    "distance_3pct": ("distance_3pct", "distance_from_3pct"),
    "distance_12pct": ("distance_12pct", "distance_from_12pct"),
    "distance_from_reference_pct": (
        "distance_from_reference_pct",
        "reference_distance_pct",
    ),
    "ma_gap_pct": ("ma_gap_pct", "ma_distance_pct"),
    "minute30_confirmations": (
        "minute30_confirmations",
        "confirmations",
    ),
    "minute30_strength": ("minute30_strength", "confirmation_strength"),
}


def _first_value(candidate: Mapping[str, Any], field: str) -> Any:
    for alias in RAW_FEATURE_ALIASES.get(field, (field,)):
        value = candidate.get(alias)
        if value is not None:
            if field == "minute30_confirmations" and isinstance(
                value, (list, tuple)
            ):
                return len(value)
            return value
    return None


def _codes(values: Iterable[Any]) -> set:
    result = set()
    for value in values or []:
        if isinstance(value, Mapping):
            code = value.get("code")
        else:
            code = value
        if code is not None and str(code).strip():
            result.add(str(code).strip())
    return result


class CandidateFunnel:
    """Accumulate one immutable first-failure record per candidate."""

    def __init__(
        self,
        run_id: str,
        report_date: str,
        as_of: Optional[str] = None,
        stage_counts: Optional[Mapping[str, Any]] = None,
    ):
        self.run_id = str(run_id).strip()
        self.report_date = str(report_date).strip()
        self.as_of = str(as_of or report_date).strip()
        if not self.run_id or not self.report_date:
            raise ValueError("run_id and report_date are required")
        if self.as_of > self.report_date:
            raise ValueError("funnel as_of cannot be later than report_date")
        self._events: Dict[str, Dict[str, Any]] = {}
        self._stage_counts = dict(stage_counts or {})

    @property
    def events(self) -> List[Dict[str, Any]]:
        return [
            deepcopy(self._events[code])
            for code in sorted(self._events)
        ]

    @property
    def codes(self) -> set:
        return set(self._events)

    def event_for(self, code: str) -> Dict[str, Any]:
        return deepcopy(self._events[str(code)])

    def set_stage_count(self, stage: str, count: int) -> None:
        if stage not in FUNNEL_STAGES:
            raise ValueError("unknown funnel stage: {}".format(stage))
        self._stage_counts[stage] = int(count)

    def register(self, candidate: Mapping[str, Any]) -> Dict[str, Any]:
        code = str(candidate.get("code") or "").strip()
        if not code:
            raise ValueError("candidate code is required")
        event = self._events.get(code)
        if event is None:
            event = {
                "run_id": self.run_id,
                "report_date": self.report_date,
                "as_of": self.as_of,
                "code": code,
                "name": str(candidate.get("name") or ""),
                "source_channel": str(candidate.get("source_channel") or ""),
                "retrieval_pool": str(candidate.get("retrieval_pool") or ""),
                "retrieval_sources": list(
                    candidate.get("retrieval_sources") or []
                ),
                "retrieval_score": candidate.get("retrieval_score"),
                "first_failure_gate": "",
                "first_failure_reason": "",
                "actual_value": None,
                "threshold": None,
                "passed_stages": ["full_a"],
                "final_state": "",
                "decision": "",
                "decision_reason": "",
                "data_quality": deepcopy(
                    candidate.get("data_quality")
                    or candidate.get("data_status")
                    or {}
                ),
                "features": {},
            }
            for field in RAW_FEATURE_FIELDS:
                event[field] = _first_value(candidate, field)
            self._events[code] = event
        else:
            for field in (
                "name",
                "source_channel",
                "retrieval_pool",
                "retrieval_score",
            ):
                if candidate.get(field) not in (None, ""):
                    event[field] = candidate.get(field)
            if candidate.get("retrieval_sources"):
                event["retrieval_sources"] = list(candidate["retrieval_sources"])
            for field in RAW_FEATURE_FIELDS:
                value = _first_value(candidate, field)
                if value is not None:
                    event[field] = value
        extra_features = candidate.get("funnel_features")
        if isinstance(extra_features, Mapping):
            event["features"].update(deepcopy(dict(extra_features)))
        return deepcopy(event)

    def register_many(self, candidates: Iterable[Mapping[str, Any]]) -> None:
        for candidate in candidates or []:
            if isinstance(candidate, Mapping):
                self.register(candidate)

    def _event(self, code: str) -> Dict[str, Any]:
        normalized = str(code).strip()
        if normalized not in self._events:
            self.register({"code": normalized})
        return self._events[normalized]

    @staticmethod
    def _stage_index(stage: str) -> int:
        try:
            return FUNNEL_STAGES.index(str(stage))
        except ValueError:
            raise ValueError("unknown funnel stage: {}".format(stage))

    def pass_stage(
        self,
        code: str,
        stage: str,
        features: Optional[Mapping[str, Any]] = None,
    ) -> None:
        event = self._event(code)
        stage_index = self._stage_index(stage)
        passed = event["passed_stages"]
        if stage in passed:
            if isinstance(features, Mapping):
                event["features"].update(deepcopy(dict(features)))
            return
        if passed:
            last_index = max(self._stage_index(value) for value in passed)
            if stage_index < last_index:
                raise ValueError(
                    "funnel stage cannot move backwards: {} -> {}".format(
                        passed[-1], stage
                    )
                )
        passed.append(stage)
        if isinstance(features, Mapping):
            event["features"].update(deepcopy(dict(features)))
            for field in RAW_FEATURE_FIELDS:
                if features.get(field) is not None:
                    event[field] = features.get(field)

    def fail_stage(
        self,
        code: str,
        stage: str,
        reason: str,
        actual_value: Any = None,
        threshold: Any = None,
        features: Optional[Mapping[str, Any]] = None,
    ) -> None:
        event = self._event(code)
        self._stage_index(stage)
        if isinstance(features, Mapping):
            event["features"].update(deepcopy(dict(features)))
            for field in RAW_FEATURE_FIELDS:
                if features.get(field) is not None:
                    event[field] = features.get(field)
        if event["first_failure_gate"]:
            return
        event["first_failure_gate"] = str(stage)
        event["first_failure_reason"] = str(reason or "{}_failed".format(stage))
        event["actual_value"] = actual_value
        event["threshold"] = threshold

    def mark_membership(
        self,
        stage: str,
        passed_codes: Sequence[Any],
        failure_reason: Optional[str] = None,
        eligible_codes: Optional[Sequence[Any]] = None,
    ) -> None:
        passed = _codes(passed_codes)
        eligible = (
            _codes(eligible_codes)
            if eligible_codes is not None
            else set(self._events)
        )
        for code in sorted(eligible):
            event = self._events.get(code)
            if (
                event
                and event.get("first_failure_gate")
                and stage != "display"
            ):
                continue
            if code in passed:
                self.pass_stage(code, stage)
            elif failure_reason:
                self.fail_stage(code, stage, failure_reason)

    def finalize(
        self,
        main_codes: Sequence[Any],
        observation_codes: Sequence[Any],
        decision_by_code: Optional[Mapping[str, Mapping[str, Any]]] = None,
    ) -> None:
        main = _codes(main_codes)
        observe = _codes(observation_codes) - main
        decisions = decision_by_code or {}
        for code, event in self._events.items():
            if code in main:
                event["final_state"] = "main"
                self.pass_stage(code, "display")
            elif code in observe:
                event["final_state"] = "observe"
                self.pass_stage(code, "display")
            else:
                event["final_state"] = "reject"
                if not event["first_failure_gate"]:
                    missing = next(
                        (
                            stage
                            for stage in FUNNEL_STAGES[1:]
                            if stage not in event["passed_stages"]
                        ),
                        "display",
                    )
                    self.fail_stage(
                        code,
                        missing,
                        "{}_not_passed".format(missing),
                    )
            decision = decisions.get(code)
            if isinstance(decision, Mapping):
                event["decision"] = str(
                    decision.get("decision")
                    or decision.get("recommendation")
                    or ""
                )
                event["decision_reason"] = str(
                    decision.get("reason")
                    or decision.get("decision_reason")
                    or ""
                )

    def summary(self) -> Dict[str, Any]:
        terminal = {state: 0 for state in TERMINAL_STATES}
        computed_stage_counts = {stage: 0 for stage in FUNNEL_STAGES}
        first_failures: Dict[str, int] = {}
        for event in self._events.values():
            for stage in event["passed_stages"]:
                computed_stage_counts[stage] += 1
            state = event.get("final_state")
            if state in terminal:
                terminal[state] += 1
            gate = event.get("first_failure_gate")
            if gate:
                first_failures[gate] = first_failures.get(gate, 0) + 1
        computed_stage_counts.update(self._stage_counts)
        return {
            "run_id": self.run_id,
            "report_date": self.report_date,
            "as_of": self.as_of,
            "candidate_count": len(self._events),
            "stage_counts": computed_stage_counts,
            "terminal_counts": terminal,
            "first_failure_counts": first_failures,
        }

    def run_record(
        self,
        status: str = "complete",
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "report_date": self.report_date,
            "as_of": self.as_of,
            "status": str(status),
            "summary": self.summary(),
            "metadata": deepcopy(dict(metadata or {})),
        }
