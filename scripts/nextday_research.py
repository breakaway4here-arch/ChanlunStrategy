#!/usr/bin/env python3
"""Build and refresh the research-only next-day shortlist artifacts."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from chanlun.nextday_research import ResearchInputError, process_report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True, help="completed daily report JSON")
    parser.add_argument("--output-dir", type=Path, required=True, help="research runs root")
    parser.add_argument("--db", type=Path, required=True, help="canonical market-history SQLite database")
    parser.add_argument("--as-of", default=None, help="outcome as-of date (defaults to report date)")
    args = parser.parse_args(argv)
    try:
        result = process_report(args.report, args.output_dir, args.db, as_of_date=args.as_of)
    except (ResearchInputError, OSError, ValueError, RuntimeError, TypeError) as exc:
        print(
            json.dumps(
                {"status": "error", "error": "{}: {}".format(type(exc).__name__, str(exc))},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if result.get("status") in ("conflict", "partial_refresh"):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
