#!/usr/bin/env python3
"""Finalize a staged recommendation batch after report validation succeeds."""

import argparse
import os
import sys


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
    finalize_staged_shadow_evaluation_entries,
    shadow_pending_ledger_path,
)


def finalize_for_date(
    report_date,
    *,
    recommendation_pending_dir=None,
    recommendation_ledger_path=None,
    shadow_pending_dir=None,
    shadow_ledger_path=None,
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

    shadow_staged_path = shadow_pending_ledger_path(
        report_date, pending_dir=shadow_pending_dir
    )
    if not os.path.exists(shadow_staged_path):
        result.update({
            "shadow_status": "no_pending_batch",
            "shadow_appended_entries": 0,
        })
    else:
        try:
            shadow_appended = finalize_staged_shadow_evaluation_entries(
                shadow_staged_path,
                shadow_ledger_path or DEFAULT_SHADOW_LEDGER_PATH,
            )
        except (OSError, TypeError, ValueError) as exc:
            result.update({
                "shadow_status": "unavailable",
                "shadow_appended_entries": 0,
                "shadow_error": "{}: {}".format(
                    type(exc).__name__, str(exc)[:160]
                ),
            })
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
