import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from chanlun.report_generator import generate_report, update_data_json
from scripts import enable_shadow_evaluation_snapshot as shadow
from scripts import repair_auxiliary_decision_snapshot as auxiliary
from scripts import repair_strategy_scorecard_snapshot as scorecard
from scripts import repair_sublevel_selection_snapshot as sublevel


FORMAL_DAY = "2026-11-17"
RECOVERY_DAY = "2026-11-12"
BATCH = "history-20261028-20261112"
ROW = {
    "date": RECOVERY_DAY,
    "page": f"{BATCH}/{RECOVERY_DAY}.html",
    "is_official": False,
    "formal_actions_allowed": False,
}


def write_index(docs, reports):
    root = docs / "recovery"
    root.mkdir(exist_ok=True)
    (root / "index.json").write_text(json.dumps({
        "schema_version": 1,
        "report_kind": "market_data_recovery",
        "reports": reports,
    }), encoding="utf-8")


def write_recovery_batch(docs, reports):
    write_index(docs, reports)
    batch = docs / "recovery" / BATCH
    batch.mkdir()
    (batch / "index.html").write_text("archive", encoding="utf-8")
    (batch / f"{RECOVERY_DAY}.html").write_text("recovered report", encoding="utf-8")


def render(docs):
    report = {"date": FORMAL_DAY, "data_quality": {
        "report_date": FORMAL_DAY, "is_trading_day": True, "is_official": True,
        "generated_at": FORMAL_DAY + "T15:05:00+08:00",
    }}
    generate_report(report, output_dir=docs, comparison_db_path="")
    update_data_json(report, output_dir=docs)


class RecoveryNavigationTests(unittest.TestCase):
    def assert_recovery_links(self, docs):
        for relative, prefix in (("index.html", ""), (f"{FORMAL_DAY}/index.html", "../")):
            html = (docs / relative).read_text(encoding="utf-8")
            self.assertEqual(html.count('id="history-recovery-nav"'), 1)
            self.assertLess(html.index('id="kaipanla-context"'), html.index('id="history-recovery-nav"'))
            self.assertLess(html.index('id="history-recovery-nav"'), html.index('id="app"'))
            self.assertIn(f'href="{prefix}recovery/{BATCH}/"', html)
            self.assertIn("历史补发日报（10 月 28 日至 11 月 12 日）", html)
            self.assertIn("非正式", html)

    def test_daily_render_adds_relative_links_without_changing_report_or_recovery_bytes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            enabled, baseline = root / "enabled", root / "baseline"
            enabled.mkdir()
            write_recovery_batch(enabled, [
                ROW, ROW,
                {**ROW, "page": "https://example.com/incorrect.html"},
                {**ROW, "page": f'{BATCH}/exfil.html" onmouseover="unsafe'},
                {**ROW, "title": "<img src=x onerror=unsafe>"},
            ])
            recovery_files = {p: p.read_bytes() for p in (enabled / "recovery").rglob("*") if p.is_file()}
            render(enabled)
            render(baseline)
            self.assert_recovery_links(enabled)
            for name in (f"data/{FORMAL_DAY}.json", "data/index.json", "data.json"):
                self.assertEqual((enabled / name).read_bytes(), (baseline / name).read_bytes())
            manifest = json.loads((enabled / "data/index.json").read_text())
            self.assertNotIn(RECOVERY_DAY, manifest["dates"])
            for path, original in recovery_files.items():
                self.assertEqual(path.read_bytes(), original)
            self.assertNotIn("exfil.html", (enabled / "index.html").read_text())
            self.assertNotIn("onerror=unsafe", (enabled / "index.html").read_text())

    def test_missing_empty_invalid_or_untrusted_index_only_omits_recovery_links(self):
        for kind in ("missing", "empty", "invalid", "unsafe_rows", "linked_landing", "missing_landing"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                docs = Path(directory)
                if kind == "empty":
                    write_index(docs, [])
                elif kind == "invalid":
                    (docs / "recovery").mkdir()
                    (docs / "recovery/index.json").write_bytes(b'{"reports":')
                elif kind == "unsafe_rows":
                    write_recovery_batch(docs, [
                        {**ROW, "page": f"../{BATCH}/{RECOVERY_DAY}.html"},
                        {**ROW, "page": f"//example.com/{ROW['page']}"},
                        {**ROW, "page": "javascript:alert(1)"},
                        {**ROW, "date": "2026-11-11"},
                        {**ROW, "is_official": True},
                        {**ROW, "formal_actions_allowed": True},
                    ])
                elif kind in ("linked_landing", "missing_landing"):
                    write_recovery_batch(docs, [ROW])
                    landing = docs / "recovery" / BATCH / "index.html"
                    landing.unlink()
                    if kind == "linked_landing":
                        landing.symlink_to(docs / "recovery/index.json")
                render(docs)
                html = (docs / "index.html").read_text(encoding="utf-8")
                self.assertNotIn("history-recovery-nav", html)
                self.assertIn('id="app"', html)
                self.assertTrue((docs / f"data/{FORMAL_DAY}.json").is_file())

    def test_scorecard_rebuild_keeps_recovery_links(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            docs = Path(temp_dir)
            write_recovery_batch(docs, [ROW])
            render(docs)
            planes = scorecard.atomic._load_public_planes(docs, FORMAL_DAY)
            aggregate = json.loads((docs / "data.json").read_text())
            bootstraps = {
                "inline": scorecard.atomic._read_bootstrap_envelope(docs / "index.html"),
                "archive": scorecard.atomic._read_bootstrap_envelope(docs / FORMAL_DAY / "index.html"),
            }
            for plane in planes.values():
                formal_sha = scorecard.formal_report_digest(plane)
                plane["shadow_evaluations"] = {"production_guard": {
                    "unchanged": True,
                    "before_sha256": formal_sha,
                    "after_sha256": formal_sha,
                }}
            scorecard._rebuild_staged_artifacts(docs, FORMAL_DAY, planes, aggregate, bootstraps, "")
            self.assert_recovery_links(docs)
            self.assertEqual(scorecard.validate_public_report_alignment(docs, FORMAL_DAY)["daily"], planes["daily"])
            expected = (
                docs, FORMAL_DAY,
                {name: scorecard.protected_report_digest(plane) for name, plane in planes.items()},
                {name: None for name in planes},
                {name: set() for name in planes},
                planes["daily"].get("strategy_scorecards"), None, None,
                json.loads((docs / "data/index.json").read_text()),
            )
            scorecard._validate_staged_artifacts(*expected)
            archive = docs / FORMAL_DAY / "index.html"
            archive.write_bytes(archive.read_bytes().replace(
                f'href="../recovery/{BATCH}/"'.encode(),
                b'href="../recovery/unverified/"', 1,
            ))
            with self.assertRaisesRegex(RuntimeError, "HTML mismatch: archive"):
                scorecard._validate_staged_artifacts(*expected)

    def test_inaccessible_recovery_dir_still_writes_formal_pages(self):
        with tempfile.TemporaryDirectory() as directory:
            docs = Path(directory).resolve()
            write_recovery_batch(docs, [ROW])
            original_is_symlink = Path.is_symlink

            def check_permissions(path):
                if path == docs / "recovery/index.json":
                    raise PermissionError("recovery directory cannot be entered")
                return original_is_symlink(path)

            with mock.patch.object(Path, "is_symlink", new=check_permissions):
                render(docs)
            for relative in ("index.html", f"{FORMAL_DAY}/index.html"):
                html = (docs / relative).read_text(encoding="utf-8")
                self.assertNotIn("history-recovery-nav", html)
                self.assertIn('id="app"', html)
            self.assertTrue((docs / f"data/{FORMAL_DAY}.json").is_file())

    def test_non_regular_recovery_index_is_never_read(self):
        with tempfile.TemporaryDirectory() as directory:
            docs = Path(directory).resolve()
            write_recovery_batch(docs, [ROW])
            manifest = docs / "recovery/index.json"
            original_is_file = Path.is_file
            original_read_text = Path.read_text

            def is_regular_file(path):
                return path != manifest and original_is_file(path)

            def read_regular_text(path, *args, **kwargs):
                self.assertNotEqual(path, manifest, "non-regular recovery index was read")
                return original_read_text(path, *args, **kwargs)

            with mock.patch.object(Path, "is_file", new=is_regular_file), mock.patch.object(
                Path, "read_text", new=read_regular_text
            ):
                render(docs)
            self.assertNotIn("history-recovery-nav", (docs / "index.html").read_text())
            self.assertTrue((docs / f"data/{FORMAL_DAY}.json").is_file())

    def test_explicit_repair_rebuilders_keep_recovery_links(self):
        for repair in (auxiliary, sublevel, shadow):
            with self.subTest(repair=repair.__name__), tempfile.TemporaryDirectory() as directory:
                docs = Path(directory)
                write_recovery_batch(docs, [ROW])
                render(docs)
                planes = scorecard.atomic._load_public_planes(docs, FORMAL_DAY)
                aggregate = json.loads((docs / "data.json").read_text())
                bootstraps = {
                    "inline": scorecard.atomic._read_bootstrap_envelope(docs / "index.html"),
                    "archive": scorecard.atomic._read_bootstrap_envelope(docs / FORMAL_DAY / "index.html"),
                }
                if repair is shadow:
                    repair._rebuild_staged_public_artifacts(docs, planes, aggregate, bootstraps, FORMAL_DAY, {})
                else:
                    repair._rebuild_staged_artifacts(docs, FORMAL_DAY, planes, aggregate, bootstraps)
                self.assert_recovery_links(docs)


if __name__ == "__main__":
    unittest.main()
