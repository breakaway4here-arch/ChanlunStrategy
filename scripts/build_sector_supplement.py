#!/usr/bin/env python3
"""Build a display-only after-close sector supplement from saved evidence.

This tool never fetches data or changes a daily report. The caller supplies a
separately verified JSON input and an explicit output path.
"""

import argparse
import json
import math
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path


SECTOR_CODE = re.compile(r"^BK\d{4}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
BEIJING = timezone(timedelta(hours=8))


def _timestamp(value, field):
    if not isinstance(value, str):
        raise ValueError("{} must be an ISO timestamp".format(field))
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("{} must be an ISO timestamp".format(field)) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("{} requires a timezone".format(field))
    return parsed


def _nonnegative_integer(value, field, *, allow_unknown=False):
    if allow_unknown and value is None:
        return None
    if type(value) is not int or value < 0:
        raise ValueError("{} must be a nonnegative integer".format(field))
    return value


def _money_text(value):
    if abs(value) >= 100_000_000:
        return "{:.2f}亿".format(value / 100_000_000)
    if abs(value) >= 10_000:
        return "{:.2f}万".format(value / 10_000)
    return "{:.2f}元".format(value)


def _flow_rows(rows, direction, observed_at):
    if not isinstance(rows, list) or len(rows) > (20 if direction == "in" else 5):
        raise ValueError("sector {} rows exceed the declared scope".format(direction))
    normalized = []
    seen = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError("sector row is not an object")
        code = row.get("code")
        name = row.get("name")
        flow = row.get("flow")
        change_pct = row.get("change_pct")
        if not (isinstance(code, str) and SECTOR_CODE.fullmatch(code)
                and isinstance(name, str) and name.strip()
                and isinstance(flow, (int, float)) and not isinstance(flow, bool)
                and math.isfinite(flow)
                and (flow > 0 if direction == "in" else flow < 0)
                and (change_pct is None or (
                    isinstance(change_pct, (int, float)) and not isinstance(change_pct, bool)
                    and math.isfinite(change_pct)
                ))
                and row.get("source") == "eastmoney_dataapi"
                and row.get("as_of") == observed_at):
            raise ValueError("sector row lacks verified identity, units, or date")
        if code in seen:
            raise ValueError("duplicate sector code")
        seen.add(code)
        normalized.append({
            "code": code,
            "name": name.strip(),
            "flow": flow,
            "flow_str": _money_text(flow),
            "change_pct": change_pct,
            "source": "eastmoney_dataapi",
            "as_of": observed_at,
        })
    values = [row["flow"] for row in normalized]
    expected = sorted(values, reverse=direction == "in")
    if values != expected:
        raise ValueError("sector flow rank order is inconsistent")
    return normalized


def build_sector_supplement(evidence, *, report_date):
    """Validate the saved facts and return an isolated public projection."""
    if not isinstance(evidence, dict) or evidence.get("schema_version") != 1:
        raise ValueError("sector evidence schema is invalid")
    if not (isinstance(report_date, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", report_date)
            and evidence.get("report_date") == report_date):
        raise ValueError("sector supplement report date mismatch")
    if (evidence.get("source") != "eastmoney_dataapi"
            or evidence.get("selection_usage") != "not_used"
            or evidence.get("status") not in {"verified", "partial"}):
        raise ValueError("sector supplement source or usage is unverified")
    observed = _timestamp(evidence.get("observed_at"), "observed_at")
    fetched = _timestamp(evidence.get("fetched_at"), "fetched_at")
    if observed.astimezone(BEIJING).date().isoformat() != report_date or fetched < observed:
        raise ValueError("sector supplement observation date is invalid")
    observed_at = evidence["observed_at"]
    inflow = _flow_rows(evidence.get("sector_flow"), "in", observed_at)
    outflow = _flow_rows(evidence.get("sector_outflow"), "out", observed_at)
    if not inflow or not outflow:
        raise ValueError("sector supplement has no two-sided funding rank")
    if set(row["code"] for row in inflow).intersection(row["code"] for row in outflow):
        raise ValueError("sector appears in both funding directions")

    raw_diagnostics = evidence.get("component_diagnostics")
    if not isinstance(raw_diagnostics, list):
        raise ValueError("component diagnostics are missing")
    components = []
    seen_components = set()
    for row in raw_diagnostics:
        if not isinstance(row, dict) or row.get("sector_code") in seen_components:
            raise ValueError("component identity is missing or duplicated")
        code = row.get("sector_code")
        if not isinstance(code, str) or not SECTOR_CODE.fullmatch(code):
            raise ValueError("component sector code is invalid")
        seen_components.add(code)
        complete = row.get("complete")
        error = row.get("error")
        requested = _nonnegative_integer(row.get("requested"), "requested", allow_unknown=True)
        raw_unique = _nonnegative_integer(row.get("raw_valid_unique"), "raw_valid_unique")
        filtered_unique = _nonnegative_integer(row.get("filtered_unique"), "filtered_unique")
        if (type(complete) is not bool or not isinstance(error, str)
                or filtered_unique > raw_unique
                or (requested is not None and raw_unique > requested)
                or (complete and (requested is None or requested != raw_unique or error))):
            raise ValueError("component coverage is inconsistent")
        components.append({
            "sector_code": code,
            "requested": requested,
            "raw_valid_unique": raw_unique,
            "filtered_unique": filtered_unique,
            "complete": complete,
            "error": error,
        })
    if seen_components != {row["code"] for row in inflow}:
        raise ValueError("component scope must match the inflow rank exactly")
    if evidence["status"] == "verified" and not all(row["complete"] for row in components):
        raise ValueError("verified component scope is incomplete")

    raw_sources = evidence.get("source_evidence")
    if not isinstance(raw_sources, list) or not raw_sources:
        raise ValueError("source receipts are missing")
    sources = []
    for row in raw_sources:
        if not isinstance(row, dict) or not isinstance(row.get("url"), str) or not row["url"].strip():
            raise ValueError("source receipt URL is missing")
        digest = row.get("sha256")
        if not isinstance(digest, str) or not SHA256.fullmatch(digest):
            raise ValueError("source receipt hash is missing")
        requested = _timestamp(row.get("requested_at"), "requested_at")
        received = _timestamp(row.get("received_at"), "received_at")
        if received < requested or fetched < received:
            raise ValueError("source receipt chronology is invalid")
        sources.append({
            "url": row["url"].strip(), "sha256": digest,
            "requested_at": row["requested_at"], "received_at": row["received_at"],
        })

    return {
        "schema_version": 1,
        "report_date": report_date,
        "observed_at": observed_at,
        "fetched_at": evidence["fetched_at"],
        "source": "eastmoney_dataapi",
        "status": evidence["status"],
        "selection_usage": "not_used",
        "component_scope": "流入前{}板块成分".format(len(inflow)),
        "sector_flow": inflow,
        "sector_outflow": outflow,
        "component_diagnostics": components,
        "source_evidence": sources,
    }


def write_sector_supplement(source_path, output_path, *, report_date):
    source_path = Path(source_path)
    output_path = Path(output_path)
    if source_path.resolve() == output_path.resolve():
        raise ValueError("source and output must be separate files")
    source = json.loads(source_path.read_text(encoding="utf-8"))
    payload = build_sector_supplement(source, report_date=report_date)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=output_path.parent,
                                         prefix=".sector-supplement-", suffix=".json", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary, output_path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validated-evidence", required=True, type=Path)
    parser.add_argument("--report-date", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    payload = write_sector_supplement(
        args.validated_evidence, args.output, report_date=args.report_date
    )
    print("{} {} {} inflow / {} outflow / {} component boards".format(
        args.output, payload["status"], len(payload["sector_flow"]),
        len(payload["sector_outflow"]), len(payload["component_diagnostics"]),
    ))


if __name__ == "__main__":
    main()
