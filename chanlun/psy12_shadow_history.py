"""Read-only filesystem adapter for PSY12 shadow-audit report history."""

from __future__ import annotations

import json
from pathlib import Path


def load_daily_report_envelopes(data_dir, as_of_date=None):
    """Load every dated report file while preserving invalid inputs.

    The audit evaluator owns validation and fail-closed behavior.  This loader
    deliberately keeps an unreadable file as ``report=None`` so the page and
    CLI cannot silently calculate progress from different subsets.
    """

    reports = []
    for path in sorted(Path(data_dir).glob("????-??-??.json")):
        if as_of_date and path.stem > as_of_date:
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
