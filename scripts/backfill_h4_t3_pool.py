#!/usr/bin/env python3
"""Incrementally add H4 T+3 to an existing daily report without rerunning it."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from chanlun.h4_t3_pool import build_h4_t3_pool  # noqa: E402
from chanlun.report_generator import (  # noqa: E402
    NpEncoder,
    _backfill_workspace_scores_for_items,
    _escape_inline_json,
    _report_asset_version,
    _serialize_h4_t3_pool,
)
from chanlun.report_view_model import build_workspace  # noqa: E402


class H4T3BackfillError(ValueError):
    """Raised when an existing report cannot be safely patched in place."""


def _patch_bootstrap(path, daily_data):
    text = path.read_text(encoding="utf-8")
    marker = "window.CHANLUN_BOOTSTRAP = "
    start = text.find(marker)
    if start < 0:
        raise H4T3BackfillError("report bootstrap is missing: " + str(path))
    value_start = start + len(marker)
    try:
        bootstrap, consumed = json.JSONDecoder().raw_decode(text[value_start:])
    except ValueError as exc:
        raise H4T3BackfillError("report bootstrap is invalid: " + str(path)) from exc
    if not isinstance(bootstrap, dict):
        raise H4T3BackfillError("report bootstrap is invalid: " + str(path))
    bootstrap["pageDate"] = daily_data["date"]
    bootstrap["inlineReportData"] = daily_data
    replacement = _escape_inline_json(bootstrap)
    updated = text[:value_start] + replacement + text[value_start + consumed:]
    updated = re.sub(
        r"(report-v2\.js\?v=)[^\"'&<>\s]+",
        r"\g<1>" + _report_asset_version(),
        updated,
    )
    path.write_text(updated, encoding="utf-8")


def backfill_h4_t3_pool(output_dir, trade_date, model_path=None):
    output = Path(output_dir).resolve()
    daily_path = output / "data" / (trade_date + ".json")
    if not daily_path.is_file():
        raise H4T3BackfillError("daily JSON is missing: " + str(daily_path))
    try:
        daily_data = json.loads(daily_path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise H4T3BackfillError("daily JSON is invalid: " + str(daily_path)) from exc
    if daily_data.get("date") != trade_date:
        raise H4T3BackfillError("daily JSON date does not match")
    picks_fusion = daily_data.get("picks_fusion")
    if not isinstance(picks_fusion, list):
        raise H4T3BackfillError("daily picks_fusion is invalid")

    pool = build_h4_t3_pool(picks_fusion, trade_date, model_path=model_path)
    daily_data["h4_t3_pool"] = _serialize_h4_t3_pool(pool)
    daily_data["workspace"] = build_workspace(daily_data)
    _backfill_workspace_scores_for_items(
        daily_data["h4_t3_pool"]["candidates"],
        daily_data["workspace"]["views"].get("h4_t3", []),
    )
    daily_path.write_text(
        json.dumps(daily_data, ensure_ascii=False, cls=NpEncoder, indent=2),
        encoding="utf-8",
    )

    html_paths = [output / "index.html", output / trade_date / "index.html"]
    for html_path in html_paths:
        if not html_path.is_file():
            raise H4T3BackfillError("report page is missing: " + str(html_path))
        _patch_bootstrap(html_path, daily_data)
    return {
        "date": trade_date,
        "candidate_count": len(pool["candidates"]),
        "microstate_count": pool["diagnostics"]["microstate_count"],
        "status": pool["status"],
        "daily_json": str(daily_path),
        "pages": [str(path) for path in html_paths],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True)
    parser.add_argument("--output-dir", default="docs")
    parser.add_argument("--model")
    args = parser.parse_args(argv)
    result = backfill_h4_t3_pool(args.output_dir, args.date, model_path=args.model)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
