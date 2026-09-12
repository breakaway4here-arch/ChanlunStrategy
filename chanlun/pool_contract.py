"""Single fail-closed parser for report stock-pool runtime states."""

from collections.abc import Mapping
import math


def _result(state, candidates=None, reason="", contract_valid=False):
    return {
        "state": state,
        "candidates": list(candidates or []),
        "count": len(candidates or []),
        "reason": str(reason or "").strip(),
        "contract_valid": bool(contract_valid),
    }


def resolve_list_pool(report, field_name):
    """Resolve a top-level array pool without coercing bad shapes to empty."""
    source = report if isinstance(report, Mapping) else {}
    if field_name not in source or source.get(field_name) is None:
        return _result("unavailable", reason="上游结果未提供")
    rows = source.get(field_name)
    if not isinstance(rows, (list, tuple)):
        return _result("unavailable", reason="上游结果合同无效")
    if rows:
        return _result(
            "ran", rows, "策略已运行并产生信号", contract_valid=True
        )
    return _result(
        "verified_empty", [], "策略运行正常，今日没有信号",
        contract_valid=True,
    )


def resolve_nested_strategy_pool(report, field_name, *, formal_h4=False):
    """Resolve enabled/disabled nested pools and the attested H4 pool."""
    source = report if isinstance(report, Mapping) else {}
    if field_name not in source or source.get(field_name) is None:
        return _result("unavailable", reason="策略池未提供")
    pool = source.get(field_name)
    if not isinstance(pool, Mapping):
        return _result("unavailable", reason="策略池合同无效")

    reason = str(pool.get("reason") or "").strip()
    mode = str(pool.get("mode") or "").strip().lower()
    status = str(pool.get("status") or "").strip().lower()
    if formal_h4:
        if mode in {"partial", "degraded"} or status in {
            "partial", "degraded",
        }:
            return _result(
                "partial", reason=reason or "生产数据合同不完整"
            )
        if not (
            pool.get("production_attested") is True
            and mode == "production"
            and status == "ok"
        ):
            return _result(
                "unavailable", reason=reason or "生产证明无效或状态异常"
            )
    else:
        if mode == "disabled":
            return _result(
                "disabled", reason=reason or "今日触发条件未成立",
                contract_valid=True,
            )
        if mode in {"partial", "degraded"} or status in {
            "partial", "degraded",
        }:
            # A research pool may retain a bounded partial output only when
            # the producer attests each retained code.  Formal/H4 callers
            # never enter this branch.
            health = pool.get("input_health")
            if not isinstance(health, Mapping):
                selection = source.get("selection_input_health")
                selection = selection if isinstance(selection, Mapping) else {}
                by_strategy = selection.get("by_strategy")
                by_strategy = by_strategy if isinstance(by_strategy, Mapping) else {}
                health = by_strategy.get(field_name)
            health = health if isinstance(health, Mapping) else {}
            raw_codes = health.get("verified_codes")
            verified_codes = {
                str(code) for code in raw_codes or [] if str(code)
            } if isinstance(raw_codes, (list, tuple, set, frozenset)) else set()
            try:
                verified_number = float(health.get("verified_count"))
            except (TypeError, ValueError, OverflowError):
                verified_number = None
            verified_count = (
                int(verified_number)
                if verified_number is not None
                and math.isfinite(verified_number)
                and verified_number >= 0
                and verified_number.is_integer()
                else 0
            )
            try:
                requested_number = float(health.get("requested_count"))
            except (TypeError, ValueError, OverflowError):
                requested_number = None
            requested_count = (
                int(requested_number)
                if requested_number is not None
                and math.isfinite(requested_number)
                and requested_number >= 0
                and requested_number.is_integer()
                else None
            )
            try:
                missing_number = float(health.get("missing_count"))
            except (TypeError, ValueError, OverflowError):
                missing_number = None
            missing_count = (
                int(missing_number)
                if missing_number is not None
                and math.isfinite(missing_number)
                and missing_number >= 0
                and missing_number.is_integer()
                else None
            )
            raw_missing_codes = health.get("missing_codes")
            missing_codes_valid = isinstance(
                raw_missing_codes, (list, tuple, set, frozenset)
            )
            missing_codes = {
                str(code) for code in raw_missing_codes if str(code)
            } if missing_codes_valid else set()
            count_contract_valid = bool(
                requested_count is not None
                and missing_count is not None
                and verified_count <= requested_count
                and missing_count == requested_count - verified_count
                and missing_codes_valid
                and len(missing_codes) == requested_count - verified_count
            )
            partial_allowed = bool(
                status == "partial"
                and count_contract_valid
                and verified_count > 0
                and verified_count == len(verified_codes)
                and verified_codes
            )
            rows = pool.get("candidates")
            if partial_allowed and isinstance(rows, (list, tuple)):
                retained = [
                    row for row in rows
                    if isinstance(row, Mapping)
                    and str(row.get("code") or "") in verified_codes
                ]
                dropped_count = max(0, len(rows) - len(retained))
                partial_reason = reason or "策略池数据合同部分可用"
                if retained:
                    partial_reason += "；已保留 {} 只逐股核验候选".format(len(retained))
                if dropped_count:
                    partial_reason += "，{} 只候选待数据核验".format(dropped_count)
                return _result(
                    "partial", retained, reason=partial_reason,
                    contract_valid=True,
                )
            return _result(
                "partial", reason=reason or "策略池数据合同不完整"
            )
        if mode != "enabled":
            return _result(
                "unavailable", reason=reason or "策略池运行模式无效"
            )
        if status in {
            "error", "failed", "unavailable", "missing", "invalid",
        }:
            return _result(
                "unavailable", reason=reason or "策略池运行状态异常"
            )

    if "candidates" not in pool or not isinstance(
        pool.get("candidates"), (list, tuple)
    ):
        return _result(
            "unavailable", reason=reason or "策略池 candidates 合同无效"
        )
    rows = pool.get("candidates")
    if rows:
        return _result(
            "ran", rows, reason or "策略已运行并产生信号",
            contract_valid=True,
        )
    return _result(
        "verified_empty", [], reason or "策略运行正常，今日没有信号",
        contract_valid=True,
    )
