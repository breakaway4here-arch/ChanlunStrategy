#!/usr/bin/env python3
"""Build a local derived observation preview without altering saved facts."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from chanlun.selection_performance import (  # noqa: E402
    build_selection_performance,
    write_selection_performance,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports-dir", required=True)
    parser.add_argument("--market-db", required=True)
    parser.add_argument("--report-as-of", required=True)
    parser.add_argument("--evaluation-as-of", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--price-series-file")
    args = parser.parse_args(argv)
    reports = Path(args.reports_dir).expanduser().resolve()
    output = Path(args.output_dir).expanduser().resolve()
    if not reports.is_dir():
        parser.error("reports directory is missing")
    if output == reports or reports in output.parents or output == reports.parent:
        parser.error("output must be an isolated derived directory")
    dataset = build_selection_performance(
        reports, args.market_db, args.report_as_of, args.evaluation_as_of,
        price_series_file=args.price_series_file,
    )
    target = write_selection_performance(dataset, output)
    print(json.dumps({
        "status": "ok", "output": str(target),
        "dataset_id": dataset["dataset_id"],
        "report_as_of": dataset["report_as_of"],
        "evaluation_as_of": dataset["evaluation_as_of"],
        "published_report_dates": dataset["coverage"]["published_report_dates"],
        "registered_observations": dataset["coverage"]["registered_observations"],
        "ready_by_horizon": {
            key: value["counts"]["ready"]
            for key, value in dataset["summary"].items()
        },
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
