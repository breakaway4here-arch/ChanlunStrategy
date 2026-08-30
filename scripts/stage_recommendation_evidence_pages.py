#!/usr/bin/env python3
"""Build a guarded, page-only staging tree for recommendation evidence.

This command intentionally never replaces files in ``docs`` and never runs
``git add``.  It reads the serialized daily report, the existing HTML shells,
and the source report assets, then atomically leaves a separate staging tree
containing only the five files that the release process may review.
"""

from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from html.parser import HTMLParser


ROOT_DIR = Path(__file__).resolve().parents[1]
if os.fspath(ROOT_DIR) not in sys.path:
    sys.path.insert(0, os.fspath(ROOT_DIR))

from chanlun.recommendation_evidence import (  # noqa: E402
    build_recommendation_evidence_projection,
)
from chanlun.report_generator import (  # noqa: E402
    _escape_inline_json,
    replace_report_asset_versions,
)
try:  # noqa: E402 - optional shared checkout configuration
    from config import MARKET_HISTORY_DB_PATH as CONFIG_MARKET_HISTORY_DB_PATH
except (ImportError, OSError, ValueError):  # pragma: no cover - minimal fixture
    CONFIG_MARKET_HISTORY_DB_PATH = None


REPORT_ASSETS = ("report-v2.css", "report-v2.js")
NORMALIZED_ASSET_VERSION = "000000000000"
_BOOTSTRAP_ASSIGNMENT_RE = re.compile(
    r"window\s*\.\s*CHANLUN_BOOTSTRAP\s*=",
)


class StageRecommendationEvidenceError(ValueError):
    """Raised when a page cannot be proven to satisfy the allowlist."""


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise StageRecommendationEvidenceError(
            "cannot read UTF-8 HTML: {}".format(path)
        ) from exc


def _read_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StageRecommendationEvidenceError(
            "invalid JSON input: {}".format(path)
        ) from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise StageRecommendationEvidenceError(
            "cannot hash protected file: {}".format(path)
        ) from exc
    return digest.hexdigest()


def _parse_date(value: str, field_name: str = "report_date") -> str:
    try:
        parsed = date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise StageRecommendationEvidenceError(
            "{} must be YYYY-MM-DD".format(field_name)
        ) from exc
    normalized = parsed.isoformat()
    if normalized != str(value):
        raise StageRecommendationEvidenceError(
            "{} must be YYYY-MM-DD".format(field_name)
        )
    return normalized


def _skip_js_string(source: str, index: int, quote: str) -> int:
    index += 1
    while index < len(source):
        char = source[index]
        if char == "\\":
            index += 2
            continue
        if char == quote:
            return index + 1
        index += 1
    raise StageRecommendationEvidenceError("unterminated JavaScript string")


def _assignment_matches(script: str):
    """Yield assignment matches outside JavaScript strings and comments."""
    matches = []
    index = 0
    while index < len(script):
        char = script[index]
        if char in "'\"`":
            index = _skip_js_string(script, index, char)
            continue
        if char == "/" and index + 1 < len(script):
            next_char = script[index + 1]
            if next_char == "/":
                newline = script.find("\n", index + 2)
                index = len(script) if newline < 0 else newline + 1
                continue
            if next_char == "*":
                end = script.find("*/", index + 2)
                if end < 0:
                    raise StageRecommendationEvidenceError(
                        "unterminated JavaScript block comment"
                    )
                index = end + 2
                continue
        match = _BOOTSTRAP_ASSIGNMENT_RE.match(script, index)
        if match:
            matches.append(match)
            index = match.end()
            continue
        index += 1
    return matches


class _InlineScriptRangeParser(HTMLParser):
    """Locate executable inline script content without matching text in attrs."""

    EXECUTABLE_TYPES = {
        "",
        "text/javascript",
        "application/javascript",
        "application/ecmascript",
        "text/ecmascript",
        "module",
    }

    def __init__(self, html: str):
        super().__init__(convert_charrefs=False)
        self.ranges = []
        self._active = None
        self._line_offsets = [0]
        for match in re.finditer(r"\n", html):
            self._line_offsets.append(match.end())

    def _offset(self, position):
        line, column = position
        return self._line_offsets[line - 1] + column

    def handle_starttag(self, tag, attrs):
        if self._active is not None or tag.lower() != "script":
            return
        start = self._offset(self.getpos())
        start_tag = self.get_starttag_text() or ""
        attributes = {key.lower(): value or "" for key, value in attrs}
        script_type = str(attributes.get("type") or "").strip().lower()
        self._active = {
            "content_start": start + len(start_tag),
            "executable": (
                "src" not in attributes
                and script_type in self.EXECUTABLE_TYPES
            ),
        }

    def handle_startendtag(self, tag, attrs):
        # A self-closing script has no executable content and therefore cannot
        # contain a bootstrap assignment.
        del attrs
        if self._active is not None or tag.lower() != "script":
            return

    def handle_endtag(self, tag):
        if self._active is None or tag.lower() != "script":
            return
        end = self._offset(self.getpos())
        if self._active["executable"]:
            self.ranges.append((self._active["content_start"], end))
        self._active = None


def _iter_inline_script_ranges(html: str):
    """Yield ``(content_start, content_end)`` for executable inline scripts."""
    parser = _InlineScriptRangeParser(html)
    try:
        parser.feed(html)
        parser.close()
    except Exception as exc:
        raise StageRecommendationEvidenceError(
            "cannot parse HTML while locating bootstrap"
        ) from exc
    if parser._active is not None:
        raise StageRecommendationEvidenceError("unterminated script element")
    yield from parser.ranges


def _skip_json_whitespace(raw: str, index: int) -> int:
    while index < len(raw) and raw[index] in " \t\r\n":
        index += 1
    return index


def _read_bootstrap_info(html: str, path: Path):
    """Return the sole executable bootstrap assignment and its JSON span."""
    decoder = json.JSONDecoder()
    occurrences = []
    for content_start, content_end in _iter_inline_script_ranges(html):
        content = html[content_start:content_end]
        for match in _assignment_matches(content):
            raw_index = content_start + match.end()
            json_start = _skip_json_whitespace(html, raw_index)
            try:
                payload, json_end = decoder.raw_decode(html, json_start)
            except (TypeError, ValueError) as exc:
                raise StageRecommendationEvidenceError(
                    "invalid report bootstrap JSON: {}".format(path)
                ) from exc
            if not isinstance(payload, dict):
                raise StageRecommendationEvidenceError(
                    "report bootstrap must be an object: {}".format(path)
                )
            statement_end = _skip_json_whitespace(html, json_end)
            if statement_end >= len(html) or html[statement_end] != ";":
                raise StageRecommendationEvidenceError(
                    "report bootstrap assignment must end with ';': {}".format(path)
                )
            occurrences.append(
                {
                    "payload": payload,
                    "assignment_start": content_start + match.start(),
                    "json_start": json_start,
                    "json_end": json_end,
                }
            )
    if not occurrences:
        raise StageRecommendationEvidenceError(
            "missing report bootstrap: {}".format(path)
        )
    if len(occurrences) != 1:
        raise StageRecommendationEvidenceError(
            "duplicate report bootstrap: {}".format(path)
        )
    return occurrences[0]


def _parse_top_level_key_span(raw: str, key: str):
    """Return ``(key_start, value_start, value_end)`` for a root key."""
    decoder = json.JSONDecoder()
    index = 0
    containers = []
    while index < len(raw):
        char = raw[index]
        if char == '"':
            try:
                decoded, end = decoder.raw_decode(raw, index)
            except ValueError as exc:
                raise StageRecommendationEvidenceError(
                    "invalid JSON while locating bootstrap key"
                ) from exc
            if containers == ["{"] and decoded == key:
                colon = _skip_json_whitespace(raw, end)
                if colon >= len(raw) or raw[colon] != ":":
                    raise StageRecommendationEvidenceError(
                        "invalid bootstrap key separator"
                    )
                value_start = _skip_json_whitespace(raw, colon + 1)
                try:
                    _, value_end = decoder.raw_decode(raw, value_start)
                except ValueError as exc:
                    raise StageRecommendationEvidenceError(
                        "invalid bootstrap key value"
                    ) from exc
                return index, value_start, value_end
            index = end
            continue
        if char in " \t\r\n":
            index += 1
            continue
        if char in "[{":
            containers.append(char)
        elif char in "]}":
            if containers:
                containers.pop()
        index += 1
    return None


def _insert_or_replace_evidence(raw_json: str, evidence: dict) -> str:
    encoded = _escape_inline_json(evidence)
    span = _parse_top_level_key_span(raw_json, "recommendationEvidence")
    if span is not None:
        _, start, end = span
        return raw_json[:start] + encoded + raw_json[end:]

    close = raw_json.rfind("}")
    if close < 0:
        raise StageRecommendationEvidenceError("bootstrap root object is incomplete")
    trailing_match = re.search(r"\s*$", raw_json[:close])
    trailing = trailing_match.group(0) if trailing_match else ""
    content_end = close - len(trailing)
    content = raw_json[:content_end]
    has_members = content.rstrip().rstrip("{").strip() != ""
    separator = "," if has_members else ""
    insertion = (
        separator
        + '"recommendationEvidence":'
        + encoded
    )
    return raw_json[:content_end] + insertion + raw_json[content_end:]


def _remove_top_level_key(raw_json: str, key: str) -> str:
    """Remove one root-object member while preserving every other byte."""
    span = _parse_top_level_key_span(raw_json, key)
    if span is None:
        return raw_json
    key_start, _, value_end = span
    after_value = _skip_json_whitespace(raw_json, value_end)
    if after_value < len(raw_json) and raw_json[after_value] == ",":
        # Member is followed by another member; consume its comma.
        return raw_json[:key_start] + raw_json[after_value + 1 :]

    # Last member (or a single-member object): consume the comma before it,
    # including the whitespace between the comma and the key.
    before_key = key_start - 1
    while before_key >= 0 and raw_json[before_key] in " \t\r\n":
        before_key -= 1
    if before_key >= 0 and raw_json[before_key] == ",":
        return raw_json[:before_key] + raw_json[value_end:]
    return raw_json[:key_start] + raw_json[value_end:]


def _inject_evidence(html: str, path: Path, evidence: dict, asset_version: str) -> str:
    info = _read_bootstrap_info(html, path)
    raw_json = html[info["json_start"] : info["json_end"]]
    updated_raw = _insert_or_replace_evidence(raw_json, evidence)
    updated = (
        html[: info["json_start"]]
        + updated_raw
        + html[info["json_end"] :]
    )
    return replace_report_asset_versions(updated, asset_version)


def _head_bytes(repo_root: Path, relative_path: str):
    completed = subprocess.run(
        ["git", "-C", os.fspath(repo_root), "show", "HEAD:{}".format(relative_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if completed.returncode != 0:
        return None
    return completed.stdout


def _asset_version(source_assets_dir: Path) -> str:
    digest = hashlib.sha256()
    for name in REPORT_ASSETS:
        path = source_assets_dir / name
        if not path.is_file():
            raise StageRecommendationEvidenceError(
                "missing source report asset: {}".format(path)
            )
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        try:
            digest.update(path.read_bytes())
        except OSError as exc:
            raise StageRecommendationEvidenceError(
                "cannot read source report asset: {}".format(path)
            ) from exc
    return digest.hexdigest()[:12]


class _AssetRefParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.refs = {"report-v2.css": [], "report-v2.js": []}

    def handle_starttag(self, tag, attrs):
        attributes = {key.lower(): value or "" for key, value in attrs}
        if tag.lower() == "link":
            value = attributes.get("href", "")
            name = "report-v2.css"
        elif tag.lower() == "script":
            value = attributes.get("src", "")
            name = "report-v2.js"
        else:
            return
        if not value:
            return
        path, _, query = value.partition("?")
        if path.rstrip("/").rsplit("/", 1)[-1] == name:
            self.refs[name].append(query)


def _assert_asset_queries(html: str, asset_version: str, path: Path):
    parser = _AssetRefParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception as exc:  # HTMLParser raises several concrete subclasses.
        raise StageRecommendationEvidenceError(
            "cannot parse staged HTML: {}".format(path)
        ) from exc
    for name in REPORT_ASSETS:
        refs = parser.refs[name]
        if not refs or any(query != "v=" + asset_version for query in refs):
            raise StageRecommendationEvidenceError(
                "{} asset query is not synchronized: {}".format(name, path)
            )


def _non_evidence_payload(payload: dict) -> dict:
    return {
        key: value
        for key, value in payload.items()
        if key != "recommendationEvidence"
    }


def _validate_existing_evidence(payload: dict, report_date: str, path: Path):
    evidence = payload.get("recommendationEvidence")
    if evidence is None:
        return
    if not isinstance(evidence, dict):
        raise StageRecommendationEvidenceError(
            "recommendationEvidence must be an object: {}".format(path)
        )
    if evidence.get("schema_version") != 1:
        raise StageRecommendationEvidenceError(
            "unsupported recommendationEvidence schema: {}".format(path)
        )
    if evidence.get("report_date") != report_date:
        raise StageRecommendationEvidenceError(
            "recommendationEvidence date mismatch: {}".format(path)
        )
    if not isinstance(evidence.get("views"), dict) or not isinstance(
        evidence.get("market_sentiment"), dict
    ):
        raise StageRecommendationEvidenceError(
            "invalid recommendationEvidence envelope: {}".format(path)
        )


def _asset_normalized_html(html: str) -> str:
    return replace_report_asset_versions(html, NORMALIZED_ASSET_VERSION)


def _assert_html_allowlist_equivalent(
    baseline: str,
    current: str,
    path: Path,
    *,
    bootstrap: bool,
):
    """Reject edits other than evidence JSON and real asset queries."""
    if bootstrap:
        before_info = _read_bootstrap_info(baseline, path)
        current_info = _read_bootstrap_info(current, path)
        if _non_evidence_payload(before_info["payload"]) != _non_evidence_payload(
            current_info["payload"]
        ):
            raise StageRecommendationEvidenceError(
                "non-whitelist bootstrap change: {}".format(path)
            )
        before_json = baseline[
            before_info["json_start"] : before_info["json_end"]
        ]
        current_json = current[
            current_info["json_start"] : current_info["json_end"]
        ]
        before_skeleton = (
            baseline[: before_info["json_start"]]
            + _remove_top_level_key(before_json, "recommendationEvidence")
            + baseline[before_info["json_end"] :]
        )
        current_skeleton = (
            current[: current_info["json_start"]]
            + _remove_top_level_key(current_json, "recommendationEvidence")
            + current[current_info["json_end"] :]
        )
    else:
        before_skeleton = baseline
        current_skeleton = current
    if _asset_normalized_html(before_skeleton) != _asset_normalized_html(
        current_skeleton
    ):
        raise StageRecommendationEvidenceError(
            "non-whitelist HTML change: {}".format(path)
        )


def _resolve_inside(repo_root: Path, value) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = repo_root / path
    return path.resolve()


def _protected_hashes(repo_root: Path, docs_dir: Path, report_date: str, paths):
    candidates = [
        docs_dir / "data" / (report_date + ".json"),
        docs_dir / "data.json",
    ]
    # These are the repository-local production planes whose hashes must stay
    # outside a page-only refresh.  Shared/remote paths can be supplied with
    # ``protected_paths``; missing optional defaults are simply absent in a
    # temporary fixture and therefore do not make it impossible to stage.
    optional_defaults = (
        repo_root / ".cache" / "chanlun" / "recommendation_ledger.jsonl",
        repo_root / ".cache" / "chanlun" / "shadow_evaluation_ledger.jsonl",
        repo_root / ".cache" / "chanlun" / "market_history.sqlite",
        repo_root / ".cache" / "chanlun" / "preclose" / report_date / "input.json",
        repo_root / ".cache" / "chanlun" / "preclose" / report_date / "snapshot.json",
        repo_root / ".cache" / "chanlun" / "preclose" / report_date / "diagnostics.json",
    )
    if repo_root == ROOT_DIR and CONFIG_MARKET_HISTORY_DB_PATH:
        optional_defaults += (Path(CONFIG_MARKET_HISTORY_DB_PATH),)
    candidates.extend(path for path in optional_defaults if path.is_file())
    for value in paths or ():
        candidates.append(_resolve_inside(repo_root, value))
    unique = []
    seen = set()
    for path in candidates:
        path = path.resolve()
        if path in seen:
            continue
        seen.add(path)
        if not path.is_file():
            raise StageRecommendationEvidenceError(
                "protected file is missing: {}".format(path)
            )
        unique.append(path)
    return {os.fspath(path): _sha256(path) for path in unique}


def _snapshot_inputs(paths):
    snapshot = {}
    for path in paths:
        try:
            snapshot[path] = path.read_bytes()
        except OSError as exc:
            raise StageRecommendationEvidenceError(
                "cannot snapshot input: {}".format(path)
            ) from exc
    return snapshot


def _assert_snapshot_unchanged(snapshot):
    for path, expected in snapshot.items():
        try:
            actual = path.read_bytes()
        except OSError as exc:
            raise StageRecommendationEvidenceError(
                "input changed during staging: {}".format(path)
            ) from exc
        if actual != expected:
            raise StageRecommendationEvidenceError(
                "input changed during staging: {}".format(path)
            )


def _write_bytes(path: Path, payload: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _copy_asset(source: Path, target: Path):
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    with target.open("rb") as handle:
        os.fsync(handle.fileno())


def stage_recommendation_evidence_pages(
    repo_root,
    docs_dir,
    report_date,
    stage_root=None,
    source_assets_dir=None,
    protected_paths=None,
):
    """Create an atomic page-only staging tree and return its manifest.

    ``stage_root`` is the destination directory containing ``index.html``,
    ``<report_date>/index.html``, ``compare/index.html`` and ``assets``.  It
    must not already exist and must be outside ``docs_dir``.  The formal docs
    tree may be used as read-only input, but it is never a staging target.
    """
    repo_root = Path(repo_root).resolve()
    docs_dir = _resolve_inside(repo_root, docs_dir)
    try:
        docs_dir.relative_to(repo_root)
    except ValueError as exc:
        raise StageRecommendationEvidenceError(
            "docs_dir must be inside repo_root"
        ) from exc
    if not docs_dir.is_dir():
        raise StageRecommendationEvidenceError("docs_dir is missing: {}".format(docs_dir))

    report_date = _parse_date(report_date)
    source_assets_dir = (
        _resolve_inside(repo_root, source_assets_dir)
        if source_assets_dir is not None
        else (ROOT_DIR / "chanlun" / "report_assets").resolve()
    )
    if not source_assets_dir.is_dir():
        raise StageRecommendationEvidenceError(
            "source asset directory is missing: {}".format(source_assets_dir)
        )

    daily_path = docs_dir / "data" / (report_date + ".json")
    aggregate_path = docs_dir / "data.json"
    home_path = docs_dir / "index.html"
    archive_path = docs_dir / report_date / "index.html"
    compare_path = docs_dir / "compare" / "index.html"
    for path in (daily_path, aggregate_path, home_path, archive_path, compare_path):
        if not path.is_file():
            raise StageRecommendationEvidenceError("required input is missing: {}".format(path))

    daily_data = _read_json(daily_path)
    aggregate_data = _read_json(aggregate_path)
    if not isinstance(daily_data, dict) or daily_data.get("date") != report_date:
        raise StageRecommendationEvidenceError(
            "daily data date mismatch: {}".format(daily_path)
        )
    if not isinstance(aggregate_data, dict):
        raise StageRecommendationEvidenceError(
            "aggregate data must be an object: {}".format(aggregate_path)
        )

    home_html = _read_text(home_path)
    archive_html = _read_text(archive_path)
    compare_html = _read_text(compare_path)
    home_info = _read_bootstrap_info(home_html, home_path)
    archive_info = _read_bootstrap_info(archive_html, archive_path)
    for info, path in ((home_info, home_path), (archive_info, archive_path)):
        payload = info["payload"]
        if payload.get("pageDate") != report_date:
            raise StageRecommendationEvidenceError(
                "bootstrap pageDate mismatch: {}".format(path)
            )
        inline = payload.get("inlineReportData")
        if not isinstance(inline, dict) or inline.get("date") != report_date:
            raise StageRecommendationEvidenceError(
                "bootstrap inlineReportData date mismatch: {}".format(path)
            )
        if inline != daily_data:
            raise StageRecommendationEvidenceError(
                "inlineReportData does not match official daily JSON: {}".format(path)
            )
        _validate_existing_evidence(payload, report_date, path)

    # Home and archive are expected to carry one identical display projection.
    audit = None
    existing_market = home_info["payload"].get("recommendationEvidence")
    if isinstance(existing_market, dict):
        market = existing_market.get("market_sentiment")
        if isinstance(market, dict) and isinstance(market.get("psy12_shadow_audit"), dict):
            audit = market["psy12_shadow_audit"]
    evidence = build_recommendation_evidence_projection(
        home_info["payload"]["inlineReportData"],
        daily_data,
        psy12_shadow_audit=audit,
    )
    if not isinstance(evidence, dict) or evidence.get("schema_version") != 1:
        raise StageRecommendationEvidenceError("recommendation evidence schema mismatch")
    if evidence.get("report_date") != report_date:
        raise StageRecommendationEvidenceError("recommendation evidence date mismatch")
    if not isinstance(evidence.get("views"), dict) or not isinstance(
        evidence.get("market_sentiment"), dict
    ):
        raise StageRecommendationEvidenceError("recommendation evidence envelope mismatch")
    try:
        json.dumps(evidence, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise StageRecommendationEvidenceError(
            "recommendation evidence is not strict JSON"
        ) from exc

    asset_version = _asset_version(source_assets_dir)
    input_paths = [home_path, archive_path, compare_path, daily_path, aggregate_path]
    input_paths += [source_assets_dir / name for name in REPORT_ASSETS]
    input_snapshot = _snapshot_inputs(input_paths)
    before_protected = _protected_hashes(
        repo_root, docs_dir, report_date, protected_paths
    )

    # Compare the working inputs to the committed baseline before making a
    # staged copy.  Existing recommendationEvidence and asset queries are the
    # only two changes that may already be present in the working tree.
    for path, html, has_bootstrap in (
        (home_path, home_html, True),
        (archive_path, archive_html, True),
        (compare_path, compare_html, False),
    ):
        relative = path.relative_to(repo_root).as_posix()
        baseline_bytes = _head_bytes(repo_root, relative)
        if baseline_bytes is None:
            continue
        try:
            baseline_html = baseline_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise StageRecommendationEvidenceError(
                "committed HTML is not UTF-8: {}".format(path)
            ) from exc
        _assert_html_allowlist_equivalent(
            baseline_html,
            html,
            path,
            bootstrap=has_bootstrap,
        )

    # Verify real links/scripts before and after the replacement.  This also
    # prevents a comment, data-src, title, or embedded string from being
    # counted as an asset reference.
    updated_home = _inject_evidence(home_html, home_path, evidence, asset_version)
    updated_archive = _inject_evidence(
        archive_html, archive_path, evidence, asset_version
    )
    updated_compare = replace_report_asset_versions(compare_html, asset_version)
    _assert_asset_queries(updated_home, asset_version, home_path)
    _assert_asset_queries(updated_archive, asset_version, archive_path)
    _assert_asset_queries(updated_compare, asset_version, compare_path)

    updated_home_info = _read_bootstrap_info(updated_home, home_path)
    updated_archive_info = _read_bootstrap_info(updated_archive, archive_path)
    for info, original_info, path in (
        (updated_home_info, home_info, home_path),
        (updated_archive_info, archive_info, archive_path),
    ):
        payload = info["payload"]
        if payload.get("recommendationEvidence") != evidence:
            raise StageRecommendationEvidenceError(
                "staged recommendation evidence mismatch: {}".format(path)
            )
        if _non_evidence_payload(payload) != _non_evidence_payload(original_info["payload"]):
            raise StageRecommendationEvidenceError(
                "staged bootstrap changed outside evidence: {}".format(path)
            )
    if updated_home_info["payload"].get("recommendationEvidence") != updated_archive_info[
        "payload"
    ].get("recommendationEvidence"):
        raise StageRecommendationEvidenceError("home/archive evidence diverged")

    # Re-check that no source changed while the projection was being built.
    _assert_snapshot_unchanged(input_snapshot)

    if stage_root is None:
        stage_dir = Path(
            tempfile.mkdtemp(
                prefix=".chanlun-recommendation-evidence-stage-",
                dir=os.fspath(repo_root.parent),
            )
        )
        temporary = stage_dir
        created_directly = True
    else:
        stage_dir = _resolve_inside(repo_root, stage_root)
        try:
            stage_dir.relative_to(docs_dir)
        except ValueError:
            pass
        else:
            raise StageRecommendationEvidenceError(
                "stage_root must be outside docs_dir: {}".format(stage_dir)
            )
        if stage_dir.exists():
            raise StageRecommendationEvidenceError(
                "stage_root already exists: {}".format(stage_dir)
            )
        stage_dir.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(
            tempfile.mkdtemp(prefix=".recommendation-evidence-tmp-", dir=stage_dir.parent)
        )
        created_directly = False

    handoff_done = False
    try:
        _write_bytes(temporary / "index.html", updated_home.encode("utf-8"))
        _write_bytes(
            temporary / report_date / "index.html",
            updated_archive.encode("utf-8"),
        )
        _write_bytes(
            temporary / "compare" / "index.html",
            updated_compare.encode("utf-8"),
        )
        for name in REPORT_ASSETS:
            _copy_asset(source_assets_dir / name, temporary / "assets" / name)

        # The second source/hash check closes the race between the first read
        # and the atomic directory handoff.
        _assert_snapshot_unchanged(input_snapshot)
        after_protected = _protected_hashes(
            repo_root, docs_dir, report_date, protected_paths
        )
        if after_protected != before_protected:
            raise StageRecommendationEvidenceError(
                "protected production hash changed during staging"
            )
        if _asset_version(source_assets_dir) != asset_version:
            raise StageRecommendationEvidenceError(
                "source asset changed during staging"
            )

        if not created_directly:
            os.replace(os.fspath(temporary), os.fspath(stage_dir))
            temporary = None
            handoff_done = True
        else:
            stage_dir = temporary
        # Ensure the returned tree is parseable after the atomic handoff.
        _assert_asset_queries(
            (stage_dir / "index.html").read_text(encoding="utf-8"),
            asset_version,
            stage_dir / "index.html",
        )
        _assert_asset_queries(
            (stage_dir / report_date / "index.html").read_text(encoding="utf-8"),
            asset_version,
            stage_dir / report_date / "index.html",
        )
        _assert_asset_queries(
            (stage_dir / "compare/index.html").read_text(encoding="utf-8"),
            asset_version,
            stage_dir / "compare/index.html",
        )
    except Exception:
        if temporary is not None:
            shutil.rmtree(temporary, ignore_errors=True)
        elif (created_directly or handoff_done) and stage_dir.exists():
            shutil.rmtree(stage_dir, ignore_errors=True)
        raise

    staged_files = [
        "assets/report-v2.css",
        "assets/report-v2.js",
        "compare/index.html",
        report_date + "/index.html",
        "index.html",
    ]
    return {
        "status": "staged",
        "report_date": report_date,
        "stage_dir": os.fspath(stage_dir),
        "asset_version": asset_version,
        "staged_files": staged_files,
        "protected_hashes_before": before_protected,
        "protected_hashes_after": after_protected,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--docs-dir", default="docs")
    parser.add_argument("--report-date", required=True)
    parser.add_argument("--stage-root")
    parser.add_argument("--source-assets-dir")
    parser.add_argument("--protected-path", action="append", default=[])
    args = parser.parse_args(argv)
    try:
        result = stage_recommendation_evidence_pages(
            repo_root=args.repo_root,
            docs_dir=args.docs_dir,
            report_date=args.report_date,
            stage_root=args.stage_root,
            source_assets_dir=args.source_assets_dir,
            protected_paths=args.protected_path,
        )
    except (OSError, RuntimeError, StageRecommendationEvidenceError, ValueError) as exc:
        print("推荐票证据页面安全暂存失败: {}".format(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
