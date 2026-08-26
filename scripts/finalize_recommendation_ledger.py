#!/usr/bin/env python3
"""Finalize a staged recommendation batch after report validation succeeds."""

import argparse
import json
import os
import re
import sys
from collections.abc import Mapping


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from chanlun.recommendation_ledger import (  # noqa: E402
    DEFAULT_LEDGER_PATH,
    finalize_staged_recommendation_entries,
    pending_ledger_path,
)
from chanlun.shadow_evaluation import (  # noqa: E402
    DEFAULT_SHADOW_LEDGER_PATH,
    append_shadow_evaluation_entries,
    load_staged_shadow_evaluation_entries,
    shadow_batch_digest,
    shadow_pending_ledger_path,
)


def _shadow_report_authorization(report_date, report_path=None):
    resolved = os.fspath(
        report_path
        or os.path.join(ROOT_DIR, "docs", "data", "{}.json".format(report_date))
    )
    with open(resolved, "r", encoding="utf-8") as handle:
        report = json.load(handle)
    if not isinstance(report, Mapping):
        raise ValueError("verified report must be a JSON object")
    if str(report.get("date") or "").strip() != str(report_date):
        raise ValueError("verified report date mismatch")

    shadow = report.get("shadow_evaluations")
    if not isinstance(shadow, Mapping):
        return {"status": "withheld", "reason": "shadow_report_missing"}
    if type(shadow.get("schema_version")) is not int or (
        shadow.get("schema_version") != 1
    ):
        return {"status": "withheld", "reason": "shadow_schema_unsupported"}
    if shadow.get("affects_production") is not False:
        return {"status": "withheld", "reason": "shadow_isolation_invalid"}
    if shadow.get("mode") != "shadow":
        return {"status": "withheld", "reason": "shadow_mode_not_enabled"}
    production_guard = shadow.get("production_guard")
    before_sha = (
        production_guard.get("before_sha256")
        if isinstance(production_guard, Mapping)
        else None
    )
    after_sha = (
        production_guard.get("after_sha256")
        if isinstance(production_guard, Mapping)
        else None
    )
    digest_pattern = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)
    if (
        not isinstance(production_guard, Mapping)
        or production_guard.get("unchanged") is not True
        or not isinstance(before_sha, str)
        or not isinstance(after_sha, str)
        or digest_pattern.fullmatch(before_sha) is None
        or digest_pattern.fullmatch(after_sha) is None
        or before_sha != after_sha
    ):
        return {
            "status": "withheld",
            "reason": "shadow_production_guard_invalid",
        }
    collection_health = shadow.get("collection_health")
    if not isinstance(collection_health, Mapping):
        return {
            "status": "withheld",
            "reason": "shadow_collection_health_missing",
        }
    collection_status = str(
        collection_health.get("status") or ""
    ).strip()
    if collection_status == "collection_failed" or shadow.get("data_gap") is True:
        return {
            "status": "unavailable",
            "reason": "shadow_collection_failed",
        }
    if shadow.get("data_gap") is not False:
        return {
            "status": "withheld",
            "reason": "shadow_data_gap_invalid",
        }
    if collection_status not in {"ok", "partial"}:
        return {
            "status": "withheld",
            "reason": "shadow_collection_not_healthy",
        }
    shadow_status = str(shadow.get("status") or "").strip()
    if shadow_status == "unavailable":
        return {"status": "unavailable", "reason": "shadow_report_unavailable"}
    if shadow_status not in {"collecting", "partial"}:
        return {
            "status": "withheld",
            "reason": "shadow_report_not_evaluable",
        }

    pending = shadow.get("pending")
    if not isinstance(pending, Mapping) or pending.get("status") != "staged":
        return {"status": "withheld", "reason": "shadow_pending_not_staged"}
    expected_digest = pending.get("batch_sha256")
    if not isinstance(expected_digest, str) or not expected_digest.strip():
        return {"status": "withheld", "reason": "shadow_batch_digest_missing"}

    report_entries = shadow.get("today_entries")
    if not isinstance(report_entries, list):
        return {"status": "withheld", "reason": "shadow_report_entries_missing"}
    if shadow_batch_digest(report_entries) != expected_digest:
        return {
            "status": "withheld",
            "reason": "shadow_report_batch_digest_mismatch",
        }
    return {
        "status": "authorized",
        "batch_sha256": expected_digest,
    }


def _shadow_failure(status, reason=None, error=None):
    result = {
        "shadow_status": status,
        "shadow_appended_entries": 0,
    }
    if reason:
        result["shadow_reason"] = reason
    if error is not None:
        result["shadow_error"] = "{}: {}".format(
            type(error).__name__, str(error)[:160]
        )
    return result


def finalize_for_date(
    report_date,
    *,
    recommendation_pending_dir=None,
    recommendation_ledger_path=None,
    shadow_pending_dir=None,
    shadow_ledger_path=None,
    report_path=None,
):
    staged_path = pending_ledger_path(
        report_date, pending_dir=recommendation_pending_dir
    )
    if not os.path.exists(staged_path):
        result = {"status": "no_pending_batch", "appended_entries": 0}
    else:
        appended = finalize_staged_recommendation_entries(
            staged_path,
            recommendation_ledger_path or DEFAULT_LEDGER_PATH,
        )
        result = {
            "status": "finalized",
            "appended_entries": appended,
        }

    try:
        authorization = _shadow_report_authorization(
            report_date, report_path=report_path
        )
    except (OSError, TypeError, ValueError) as exc:
        result.update(_shadow_failure("unavailable", error=exc))
        return result
    if authorization["status"] != "authorized":
        result.update(_shadow_failure(
            authorization["status"], reason=authorization.get("reason")
        ))
        return result

    shadow_staged_path = shadow_pending_ledger_path(
        report_date, pending_dir=shadow_pending_dir
    )
    if not os.path.exists(shadow_staged_path):
        result.update(_shadow_failure(
            "withheld", reason="shadow_pending_file_missing"
        ))
        return result
    try:
        staged_entries = load_staged_shadow_evaluation_entries(
            shadow_staged_path
        )
        actual_digest = shadow_batch_digest(staged_entries)
        if actual_digest != authorization["batch_sha256"]:
            result.update(_shadow_failure(
                "withheld", reason="shadow_pending_batch_digest_mismatch"
            ))
            return result
        shadow_appended = append_shadow_evaluation_entries(
            shadow_ledger_path or DEFAULT_SHADOW_LEDGER_PATH,
            staged_entries,
        )
    except (OSError, TypeError, ValueError) as exc:
        result.update(_shadow_failure("unavailable", error=exc))
    else:
        result.update({
            "shadow_status": "finalized",
            "shadow_appended_entries": shadow_appended,
        })
    return result


def main():
    parser = argparse.ArgumentParser(
        description="校验通过后固化推荐归因账本"
    )
    parser.add_argument("report_date", help="YYYY-MM-DD")
    args = parser.parse_args()
    result = finalize_for_date(args.report_date)
    print(
        "推荐账本: {}，新增 {} 条；影子账本: {}，新增 {} 条".format(
            result["status"],
            result["appended_entries"],
            result["shadow_status"],
            result["shadow_appended_entries"],
        )
    )


if __name__ == "__main__":
    main()
