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


def finalize_for_date(report_date):
    staged_path = pending_ledger_path(report_date)
    if not os.path.exists(staged_path):
        return {"status": "no_pending_batch", "appended_entries": 0}
    appended = finalize_staged_recommendation_entries(
        staged_path,
        DEFAULT_LEDGER_PATH,
    )
    return {
        "status": "finalized",
        "appended_entries": appended,
    }


def main():
    parser = argparse.ArgumentParser(
        description="校验通过后固化推荐归因账本"
    )
    parser.add_argument("report_date", help="YYYY-MM-DD")
    args = parser.parse_args()
    result = finalize_for_date(args.report_date)
    print(
        "推荐账本: {}，新增 {} 条".format(
            result["status"], result["appended_entries"]
        )
    )


if __name__ == "__main__":
    main()
