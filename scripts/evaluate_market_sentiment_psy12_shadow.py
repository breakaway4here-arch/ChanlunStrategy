#!/usr/bin/env python3
"""Read-only PSY12 shadow audit for manual production review."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from chanlun.psy12_shadow_audit import evaluate_shadow_reports


def _load_reports(data_dir, as_of=None):
    """Envelope every selected file so any bad input fails the whole audit."""
    reports = []
    for path in sorted(Path(data_dir).glob("????-??-??.json")):
        if as_of and path.stem > as_of:
            continue
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            report = None
        reports.append({
            "trade_date": path.stem,
            "report": report,
            "source": "daily_file",
        })
    return reports


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default=str(ROOT / "docs" / "data"))
    parser.add_argument("--as-of")
    parser.add_argument("--required-days", type=int, default=20)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)

    result = evaluate_shadow_reports(
        _load_reports(args.data_dir, args.as_of),
        required_days=args.required_days,
        as_of_date=args.as_of,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(str(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
