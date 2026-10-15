"""Build a dated, read-only icepoint observation sidecar from verified evidence.

This command has no network access or implicit output path. It never edits the
report or the evidence input; publication is a separate operation.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chanlun.market_icepoint import supplement_icepoint


CN = timezone(timedelta(hours=8))
OPENAPI_URL = "https://openapi.iwencai.com/v1/query2data"


def _instant(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.astimezone(CN) if parsed.tzinfo is not None else None


def _amount(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value > 0)


def _date(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return False
    try:
        return datetime.fromisoformat(value).date().isoformat() == value
    except ValueError:
        return False


def build_icepoint_supplement(report, evidence):
    """Return a self-bound supplement; reject mixed dates and unproven claims."""
    if not isinstance(report, dict) or not isinstance(evidence, dict):
        raise ValueError("report and evidence must be objects")
    report_date = report.get("date")
    original = report.get("market_icepoint")
    turnover = evidence.get("turnover")
    breadth = evidence.get("breadth")
    if (not _date(report_date) or evidence.get("schema_version") != 1
            or evidence.get("report_date") != report_date
            or evidence.get("source") != "hithink_iwencai_883957"
            or evidence.get("selection_usage") != "not_used"
            or not isinstance(original, dict) or original.get("date") != report_date
            or original.get("phase") != "closed" or original.get("status") != "insufficient"
            or not isinstance(turnover, dict) or not isinstance(breadth, dict)):
        raise ValueError("frozen report or supplement identity is invalid")
    prior = turnover.get("prior")
    prior_dates = turnover.get("prior_dates")
    current = turnover.get("current")
    if (turnover.get("source") != "wencai" or turnover.get("source_code") != "883957.TI"
            or turnover.get("evidence_contract") != "provider_aggregate_v1"
            or turnover.get("amount_unit") != "CNY"
            or turnover.get("date") != report_date or turnover.get("market_date") != report_date
            or turnover.get("market_phase") != "closed" or turnover.get("quality") != "comparable"
            or turnover.get("trading_days_verified") is not True or turnover.get("complete") is not True
            or not isinstance(prior, list) or len(prior) != 5 or not all(_amount(item) for item in prior)
            or not _amount(current) or not isinstance(prior_dates, list) or len(prior_dates) != 5
            or not all(_date(day) and day < report_date for day in prior_dates)
            or prior_dates != sorted(set(prior_dates))):
        raise ValueError("six-day same-scope turnover is incomplete")
    retrieved = _instant(turnover.get("retrieved_at"))
    breadth_retrieved = _instant(breadth.get("retrieved_at"))
    report_end = datetime.fromisoformat(report_date + "T23:59:59+08:00")
    if (not retrieved or retrieved <= report_end or _instant(turnover.get("as_of")) != retrieved
            or not breadth_retrieved or breadth_retrieved <= report_end
            or breadth.get("source") != "quote_snapshot+wencai"
            or breadth.get("scope") != "all_a" or breadth.get("date") != report_date
            or breadth.get("complete") is not True):
        raise ValueError("supplement acquisition time or breadth provenance is invalid")
    counts = ("advance_count", "decline_count", "flat_count", "valid_count", "denominator",
              "trading_count", "quote_snapshot_count", "suspended_count", "unknown_count")
    if any(not isinstance(breadth.get(name), int) or isinstance(breadth[name], bool)
           or breadth[name] < 0 for name in counts):
        raise ValueError("breadth count is invalid")
    if (breadth["unknown_count"] != 0
            or breadth["trading_count"] != sum(breadth[name] for name in counts[:3])
            or breadth["trading_count"] != breadth["valid_count"]
            or breadth["trading_count"] != breadth["denominator"]
            or breadth["quote_snapshot_count"] != breadth["trading_count"] + breadth["suspended_count"]):
        raise ValueError("breadth and suspension population do not reconcile")
    receipts = evidence.get("source_evidence")
    supplemented_at = max(retrieved, breadth_retrieved)
    if not isinstance(receipts, list) or not receipts:
        raise ValueError("source receipts are required")
    for receipt in receipts:
        received = _instant(receipt.get("received_at")) if isinstance(receipt, dict) else None
        if (not isinstance(receipt, dict) or receipt.get("url") != OPENAPI_URL
                or not re.fullmatch(r"[0-9a-f]{64}", str(receipt.get("sha256")))
                or not received or not report_end < received <= supplemented_at):
            raise ValueError("source receipt is invalid")
    corrected = supplement_icepoint(copy.deepcopy(original),
                                    {"turnover": copy.deepcopy(turnover),
                                     "breadth": copy.deepcopy(breadth)})
    if (not isinstance(corrected, dict) or corrected.get("date") != report_date
            or corrected.get("status") != "not_matched"
            or corrected.get("verified_count") != 4 or corrected.get("matched_count") != 0
            or _instant(corrected.get("supplemented_at")) != supplemented_at):
        raise ValueError("icepoint evidence did not verify all four conditions")
    changed_keys = {"volume_drop", "breadth"}
    if any(corrected["items"].get(key) != original["items"].get(key)
           for key in ("six_indices", "sealed_limits")) or corrected.get("etf") != original.get("etf"):
        raise ValueError("supplement changed frozen evidence")
    for name in corrected["items"]:
        if name not in changed_keys and corrected["items"][name] != original["items"].get(name):
            raise ValueError("supplement changed unrelated icepoint condition")
    return {
        "schema_version": 1, "report_date": report_date,
        "source": "hithink_iwencai_883957", "selection_usage": "not_used",
        "supplemented_at": corrected["supplemented_at"],
        "original_market_icepoint": copy.deepcopy(original),
        "supplemented_market_icepoint": copy.deepcopy(corrected),
        "turnover_days": [{"date": day, "amount_cny": amount}
                          for day, amount in zip(prior_dates + [report_date], prior + [current])],
        "source_evidence": copy.deepcopy(receipts),
    }


def write_icepoint_supplement(report_path, evidence_path, output_path):
    report_path = Path(report_path)
    evidence_path = Path(evidence_path)
    output_path = Path(output_path)
    if output_path.resolve() in (report_path.resolve(), evidence_path.resolve()):
        raise ValueError("output must be distinct from frozen inputs")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    payload = build_icepoint_supplement(report, evidence)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    write_icepoint_supplement(args.report, args.evidence, args.output)


if __name__ == "__main__":
    main()
