#!/usr/bin/env python3
"""Export the compact frozen training rows required by H4 T+3 production."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from chanlun.h4_t3_pool import (  # noqa: E402
    FEATURE_DIMENSION,
    MODEL_PATH,
    NEIGHBOR_COUNT,
    STRATEGY_VERSION,
    H4T3PoolError,
    build_tail_feature_vector,
    is_continuation_microstate,
)


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _t3_labels(labels):
    rows = labels.get("records") if isinstance(labels, Mapping) else None
    if not isinstance(rows, list):
        raise H4T3PoolError("development labels are invalid")
    output = {}
    for row in rows:
        nested = row.get("labels") if isinstance(row, Mapping) else None
        label = nested.get("t3") if isinstance(nested, Mapping) else None
        index = row.get("record_index") if isinstance(row, Mapping) else None
        if not isinstance(index, int) or isinstance(index, bool) or not isinstance(label, Mapping):
            continue
        if label.get("horizon") not in (3, "3", "t3"):
            continue
        output[index] = {
            "trade_date": str(row.get("trade_date") or ""),
            "code": str(row.get("code") or ""),
            "exit_date": str(label.get("exit_date") or ""),
            "return_pct": float(label.get("primary_return_pct")),
        }
    return output


def build_model_payload(features, labels, source_identity=None):
    records = features.get("records") if isinstance(features, Mapping) else None
    if not isinstance(records, list):
        raise H4T3PoolError("frozen feature records are invalid")
    label_map = _t3_labels(labels)
    grouped = {}
    for row in records:
        if not isinstance(row, Mapping) or row.get("pool") != "picks_fusion":
            continue
        trade_date = str(row.get("trade_date") or "")
        code = str(row.get("code") or "")
        record_index = row.get("record_index")
        if not trade_date or not code or not isinstance(record_index, int) or isinstance(record_index, bool):
            raise H4T3PoolError("frozen feature identity is invalid")
        if not is_continuation_microstate(row):
            continue
        label = label_map.get(record_index)
        if not label or label["trade_date"] != trade_date or label["code"] != code:
            continue
        vector = [float(value) for value in build_tail_feature_vector(row)]
        item = {
            "trade_date": trade_date,
            "exit_date": label["exit_date"],
            "code": code,
            "record_index": record_index,
            "return_pct": label["return_pct"],
            "vector": vector,
        }
        identity = (trade_date, code)
        current = grouped.get(identity)
        if current is None or (tuple(vector), record_index) < (
            tuple(current["vector"]), current["record_index"]
        ):
            grouped[identity] = item
    training_rows = [grouped[key] for key in sorted(grouped)]
    if not training_rows:
        raise H4T3PoolError("no H4 training rows were exported")
    return {
        "artifact_type": "h4_t3_production_model",
        "schema_version": 1,
        "strategy_version": STRATEGY_VERSION,
        "feature_dimension": FEATURE_DIMENSION,
        "neighbor_count": NEIGHBOR_COUNT,
        "training_row_count": len(training_rows),
        "training_date_count": len(set(row["trade_date"] for row in training_rows)),
        "source_identity": dict(source_identity or {}),
        "training_rows": training_rows,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--features", required=True)
    parser.add_argument("--labels", required=True)
    parser.add_argument("--output", default=str(MODEL_PATH))
    args = parser.parse_args(argv)
    feature_path = Path(args.features).resolve()
    label_path = Path(args.labels).resolve()
    with feature_path.open("r", encoding="utf-8") as handle:
        features = json.load(handle)
    with label_path.open("r", encoding="utf-8") as handle:
        labels = json.load(handle)
    payload = build_model_payload(
        features,
        labels,
        source_identity={
            "feature_sha256": _sha256(feature_path),
            "label_sha256": _sha256(label_path),
        },
    )
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        handle.write("\n")
    print(json.dumps({
        "output": str(output),
        "training_row_count": payload["training_row_count"],
        "training_date_count": payload["training_date_count"],
        "bytes": output.stat().st_size,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
