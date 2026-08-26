"""Single fail-closed parser for report stock-pool runtime states."""

from collections.abc import Mapping


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
