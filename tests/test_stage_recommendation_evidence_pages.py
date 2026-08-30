"""Guarded staging tests for the HTML-only recommendation evidence plane.

The tests deliberately use a temporary git repository.  The production docs
tree is never used as an output target; a successful run leaves a separate
staging directory and a failed run leaves both the source tree and the target
untouched.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from chanlun.recommendation_evidence import (
    build_recommendation_evidence_projection,
)
from scripts.stage_recommendation_evidence_pages import (
    stage_recommendation_evidence_pages,
)


REPORT_DATE = "2026-08-28"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bootstrap_from_html(html: str) -> dict:
    marker = "window.CHANLUN_BOOTSTRAP ="
    # The fixture intentionally contains the same text in an embedded string;
    # the executable assignment is the final occurrence.
    start = html.rindex(marker) + len(marker)
    start += len(html[start:]) - len(html[start:].lstrip())
    decoder = json.JSONDecoder()
    value, _ = decoder.raw_decode(html[start:])
    return value


def _html_for(
    data: dict,
    *,
    archive: bool,
    asset_version: str = "legacy",
    evidence: dict | None = None,
) -> str:
    prefix = "../" if archive else ""
    bootstrap = {
        "pageDate": REPORT_DATE,
        "inlineReportData": data,
        "top10ApiBase": "https://top10.example.test",
        "precloseApiBase": "https://preclose.example.test",
        "decisionWatchlistUrl": "https://watchlist.example.test",
        "accessControlEnabled": True,
        "accessKeyHash": "redacted-hash",
        "accessKeySalt": "redacted-salt",
    }
    if evidence is not None:
        bootstrap["recommendationEvidence"] = evidence
    serialized = json.dumps(bootstrap, ensure_ascii=False, separators=(",", ":"))
    return f"""<!doctype html>
<html lang="zh-CN"><head>
<meta charset="utf-8">
<link rel="stylesheet" href="{prefix}assets/report-v2.css?v={asset_version}">
<title>保留标题</title>
</head><body>
<!-- 保留注释：report-v2.js?v=comment-sentinel -->
<main data-sentinel="正文/注释/嵌入字符串必须保留">正式页面正文</main>
<script>
  var embedded = "window.CHANLUN_BOOTSTRAP = {{\\"fake\\":true}};";
  window.CHANLUN_BOOTSTRAP = {serialized};
</script>
<script src="{prefix}assets/report-v2.js?v={asset_version}" defer></script>
</body></html>
"""


class StageFixture:
    def __init__(self, tmpdir: str):
        self.root = Path(tmpdir)
        self.docs = self.root / "docs"
        self.source_assets = self.root / "source-assets"
        self.docs.mkdir()
        (self.docs / "data").mkdir()
        (self.docs / "assets").mkdir()
        (self.docs / "compare").mkdir()
        (self.docs / REPORT_DATE).mkdir()
        self.data = {
            "date": REPORT_DATE,
            "data_quality": {
                "is_trading_day": True,
                "is_official": True,
            },
            "workspace": {
                "view_order": ["main"],
                "views": {"main": []},
            },
            "picks_fusion": [],
        }
        (self.docs / "data" / f"{REPORT_DATE}.json").write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (self.docs / "data.json").write_text(
            json.dumps({"reports": {REPORT_DATE: self.data}}, ensure_ascii=False)
            + "\n",
            encoding="utf-8",
        )

        # Copy the actual source assets into an isolated source directory.  A
        # test can change this fixture without touching the checkout assets.
        checkout_assets = Path(__file__).resolve().parents[1] / "chanlun" / "report_assets"
        self.source_assets.mkdir()
        for name in ("report-v2.css", "report-v2.js"):
            shutil.copy2(checkout_assets / name, self.source_assets / name)
            (self.docs / "assets" / name).write_text(
                f"old {name} bytes\n", encoding="utf-8"
            )

        (self.docs / "index.html").write_text(
            _html_for(self.data, archive=False), encoding="utf-8"
        )
        (self.docs / REPORT_DATE / "index.html").write_text(
            _html_for(self.data, archive=True), encoding="utf-8"
        )
        (self.docs / "compare" / "index.html").write_text(
            """<!doctype html><html><head>
<link rel="stylesheet" href="../assets/report-v2.css?v=legacy">
</head><body><div>compare-body</div>
<script src="../assets/report-v2.js?v=legacy" defer></script>
</body></html>\n""",
            encoding="utf-8",
        )

        self.protected = []
        for relative, payload in (
            ("ledger/recommendation.json", b"recommendation-ledger\n"),
            ("ledger/shadow.json", b"shadow-ledger\n"),
            ("market_history.sqlite", b"sqlite-placeholder\n"),
            ("preclose/latest.json", b"preclose-snapshot\n"),
        ):
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
            self.protected.append(path)

        # Baseline files are used by the staging guard to distinguish a
        # permitted evidence/query refresh from an external manual edit.
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        subprocess.run(
            ["git", "config", "user.email", "stage-test@example.invalid"],
            cwd=self.root,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "stage-test"],
            cwd=self.root,
            check=True,
        )
        subprocess.run(["git", "add", "-A"], cwd=self.root, check=True)
        subprocess.run(
            ["git", "commit", "-qm", "baseline"], cwd=self.root, check=True
        )

    def source_snapshot(self) -> dict[str, bytes]:
        return {
            str(path.relative_to(self.docs)): path.read_bytes()
            for path in sorted(self.docs.rglob("*"))
            if path.is_file()
        }


class TestStageRecommendationEvidencePages(unittest.TestCase):
    def _fixture(self):
        tmp = tempfile.TemporaryDirectory()
        return tmp, StageFixture(tmp.name)

    def _stage(self, fixture: StageFixture, stage_root: Path | None = None):
        return stage_recommendation_evidence_pages(
            repo_root=fixture.root,
            docs_dir=fixture.docs,
            report_date=REPORT_DATE,
            stage_root=stage_root or (fixture.root / "stage"),
            source_assets_dir=fixture.source_assets,
            protected_paths=fixture.protected,
        )

    def test_stages_evidence_and_only_whitelisted_page_changes(self):
        tmp, fixture = self._fixture()
        try:
            before = fixture.source_snapshot()
            protected_before = {str(path): _sha256(path) for path in fixture.protected}
            result = self._stage(fixture)
            stage = Path(result["stage_dir"])

            self.assertEqual(
                result["staged_files"],
                [
                    "assets/report-v2.css",
                    "assets/report-v2.js",
                    "compare/index.html",
                    f"{REPORT_DATE}/index.html",
                    "index.html",
                ],
            )
            self.assertEqual(before, fixture.source_snapshot())
            self.assertEqual(
                protected_before,
                {str(path): _sha256(path) for path in fixture.protected},
            )

            expected = build_recommendation_evidence_projection(
                fixture.data, fixture.data
            )
            for relative in ("index.html", f"{REPORT_DATE}/index.html"):
                baseline = _bootstrap_from_html(
                    (fixture.docs / relative).read_text(encoding="utf-8")
                )
                staged_html = (stage / relative).read_text(encoding="utf-8")
                staged = _bootstrap_from_html(staged_html)
                self.assertEqual(staged["recommendationEvidence"], expected)
                self.assertEqual(staged["inlineReportData"], baseline["inlineReportData"])
                self.assertEqual(
                    {key: value for key, value in staged.items() if key != "recommendationEvidence"},
                    baseline,
                )
                self.assertIn("正文/注释/嵌入字符串必须保留", staged_html)
                self.assertIn("保留注释：report-v2.js?v=comment-sentinel", staged_html)
                prefix = "../" if relative != "index.html" else ""
                self.assertIn(
                    f"{prefix}assets/report-v2.css?v={result['asset_version']}",
                    staged_html,
                )
                self.assertIn(
                    f"{prefix}assets/report-v2.js?v={result['asset_version']}",
                    staged_html,
                )

            original_compare = (fixture.docs / "compare/index.html").read_text(
                encoding="utf-8"
            )
            staged_compare = (stage / "compare/index.html").read_text(encoding="utf-8")
            self.assertEqual(
                original_compare.replace("?v=legacy", "?v=normalized"),
                staged_compare.replace(
                    f"?v={result['asset_version']}", "?v=normalized"
                ),
            )
            for name in ("report-v2.css", "report-v2.js"):
                self.assertEqual(
                    _sha256(fixture.source_assets / name),
                    _sha256(stage / "assets" / name),
                )
        finally:
            tmp.cleanup()

    def _assert_rejected_without_writes(self, mutate):
        tmp, fixture = self._fixture()
        try:
            mutate(fixture)
            before = fixture.source_snapshot()
            stage = fixture.root / "stage"
            with self.assertRaises(ValueError):
                self._stage(fixture, stage)
            self.assertFalse(stage.exists(), "rejected staging must not leave output")
            self.assertEqual(before, fixture.source_snapshot())
        finally:
            tmp.cleanup()

    def test_rejects_missing_or_duplicate_bootstrap(self):
        self._assert_rejected_without_writes(
            lambda fixture: (fixture.docs / "index.html").write_text(
                (fixture.docs / "index.html")
                .read_text(encoding="utf-8")
                .replace("window.CHANLUN_BOOTSTRAP =", "window.NO_BOOTSTRAP ="),
                encoding="utf-8",
            )
        )

        def duplicate(fixture):
            path = fixture.docs / "index.html"
            html = path.read_text(encoding="utf-8")
            html = html.replace(
                "</script>",
                '<script>window.CHANLUN_BOOTSTRAP = {"duplicate": true};</script></body>',
                1,
            )
            path.write_text(html, encoding="utf-8")

        self._assert_rejected_without_writes(duplicate)

    def test_rejects_date_schema_and_target_path_mismatch(self):
        tmp, fixture = self._fixture()
        try:
            with self.assertRaises(ValueError):
                stage_recommendation_evidence_pages(
                    repo_root=fixture.root,
                    docs_dir=fixture.docs,
                    report_date="2026-08-29",
                    stage_root=fixture.root / "stage",
                    source_assets_dir=fixture.source_assets,
                    protected_paths=fixture.protected,
                )
            self.assertFalse((fixture.root / "stage").exists())

            archive = fixture.docs / REPORT_DATE / "index.html"
            html = archive.read_text(encoding="utf-8").replace(
                f'"pageDate":"{REPORT_DATE}"',
                '"pageDate":"2026-08-27"',
            )
            archive.write_text(html, encoding="utf-8")
            with self.assertRaises(ValueError):
                self._stage(fixture)
            self.assertFalse((fixture.root / "stage").exists())
        finally:
            tmp.cleanup()

        def bad_schema(fixture):
            path = fixture.docs / "index.html"
            html = path.read_text(encoding="utf-8")
            data = _bootstrap_from_html(html)
            data["recommendationEvidence"] = {
                "schema_version": 99,
                "report_date": REPORT_DATE,
                "views": {},
                "market_sentiment": {},
            }
            path.write_text(_html_for(fixture.data, archive=False, evidence=data["recommendationEvidence"]), encoding="utf-8")

        self._assert_rejected_without_writes(bad_schema)

    def test_rejects_non_whitelist_external_html_edits(self):
        def mutate_body(fixture):
            path = fixture.docs / "index.html"
            path.write_text(
                path.read_text(encoding="utf-8").replace("正式页面正文", "外部手工改写"),
                encoding="utf-8",
            )

        self._assert_rejected_without_writes(mutate_body)

        def mutate_compare(fixture):
            path = fixture.docs / "compare/index.html"
            path.write_text(
                path.read_text(encoding="utf-8").replace("compare-body", "tampered"),
                encoding="utf-8",
            )

        self._assert_rejected_without_writes(mutate_compare)

        def mutate_bootstrap(fixture):
            path = fixture.docs / "index.html"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    '"top10ApiBase":"https://top10.example.test"',
                    '"top10ApiBase":"https://tampered.example.test"',
                ),
                encoding="utf-8",
            )

        self._assert_rejected_without_writes(mutate_bootstrap)

    def test_existing_evidence_refresh_is_allowed_but_bootstrap_whitespace_is_not(self):
        tmp, fixture = self._fixture()
        try:
            expected = build_recommendation_evidence_projection(
                fixture.data, fixture.data
            )
            for relative, archive in (("index.html", False), (f"{REPORT_DATE}/index.html", True)):
                path = fixture.docs / relative
                path.write_text(
                    _html_for(fixture.data, archive=archive, evidence=expected),
                    encoding="utf-8",
                )
            result = self._stage(fixture)
            self.assertEqual(result["status"], "staged")
        finally:
            tmp.cleanup()

        def whitespace_edit(fixture):
            path = fixture.docs / "index.html"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    '"top10ApiBase":', ' "top10ApiBase":', 1
                ),
                encoding="utf-8",
            )

        self._assert_rejected_without_writes(whitespace_edit)

    def test_ignores_bootstrap_looking_text_in_non_executable_scripts(self):
        tmp, fixture = self._fixture()
        try:
            path = fixture.docs / "index.html"
            html = path.read_text(encoding="utf-8")
            html = html.replace(
                "</head>",
                '<script type="application/json">window.CHANLUN_BOOTSTRAP = {"fake":true};</script></head>',
                1,
            )
            path.write_text(html, encoding="utf-8")
            # The non-executable script itself is an external HTML edit; add
            # it to the committed baseline so only bootstrap discovery is
            # exercised here.
            subprocess.run(["git", "add", "-A"], cwd=fixture.root, check=True)
            subprocess.run(
                ["git", "commit", "-qm", "fixture script"],
                cwd=fixture.root,
                check=True,
            )
            self.assertEqual(self._stage(fixture)["status"], "staged")
        finally:
            tmp.cleanup()

    def test_stage_root_must_stay_outside_the_read_only_docs_tree(self):
        tmp, fixture = self._fixture()
        try:
            with self.assertRaises(ValueError):
                self._stage(fixture, fixture.docs / "stage")
            self.assertFalse((fixture.docs / "stage").exists())
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
