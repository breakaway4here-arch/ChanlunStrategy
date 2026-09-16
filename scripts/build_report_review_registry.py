#!/usr/bin/env python3
"""Build a read-only comparison/review derivative from stored report artifacts."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chanlun.report_comparison import build_comparison_index  # noqa: E402


def _is_within(path, directory):
    try:
        path.relative_to(directory)
    except ValueError:
        return False
    return True


def _atomic_write_json(path, value):
    path = Path(path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=".review-registry-", suffix=".json", dir=str(path.parent)
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Derive review_registry from stored reports and local prices"
    )
    parser.add_argument("--docs-dir", required=True)
    parser.add_argument("--market-db", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--window-size", type=int, default=26)
    args = parser.parse_args(argv)

    docs_lexical = Path(os.path.abspath(str(Path(args.docs_dir).expanduser())))
    output_lexical = Path(os.path.abspath(str(Path(args.output).expanduser())))
    docs_dir = docs_lexical.resolve()
    data_dir = docs_dir / "data"
    market_db = Path(args.market_db).expanduser().resolve()
    output = output_lexical.resolve()
    source_index = (data_dir / "comparison-index.json").resolve()
    if output == source_index:
        raise ValueError(
            "read-only derivation refuses to overwrite source comparison index"
        )
    if output == market_db:
        raise ValueError(
            "read-only derivation refuses to overwrite or alias market database"
        )
    if (
        _is_within(output_lexical, docs_lexical)
        or _is_within(output, docs_dir)
    ):
        raise ValueError(
            "read-only derivation refuses output inside source docs tree"
        )
    index = build_comparison_index(
        str(data_dir),
        str(market_db),
        window_size=args.window_size,
    )
    _atomic_write_json(output, index)
    registry = index.get("review_registry", {})
    print(json.dumps({
        "output": str(output),
        "window_start": registry.get("window_start"),
        "window_end": registry.get("window_end"),
        "registered_count": registry.get("registered_count"),
        "instrument_count": registry.get("instrument_count"),
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
