"""Tests for publishing an enabled-but-empty shadow evaluation snapshot."""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from chanlun.h4_t3_pool import STRATEGY_VERSION
from chanlun.report_generator import generate_report, update_data_json
from scripts import enable_shadow_evaluation_snapshot as snapshot
from scripts.finalize_recommendation_ledger import _shadow_report_authorization


REPORT_DATE = "2026-08-21"
STARTED_AT = "2026-08-22"


def _formal_digest(payload):
    return snapshot.formal_report_digest(payload)


def _read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _bootstrap(path):
    html = Path(path).read_text(encoding="utf-8")
    match = re.search(
        r"window\.CHANLUN_BOOTSTRAP\s*=\s*(\{[\s\S]*?\});",
        html,
    )
    if not match:
        raise AssertionError("missing report bootstrap")
    return json.loads(match.group(1))


def _strip_legacy_shadow_from_html(path):
    path = Path(path)
    html = path.read_text(encoding="utf-8")
    match = re.search(
        r"window\.CHANLUN_BOOTSTRAP\s*=\s*(\{[\s\S]*?\});",
        html,
    )
    if not match:
        raise AssertionError("missing report bootstrap")
    bootstrap = json.loads(match.group(1))
    bootstrap["inlineReportData"].pop("shadow_evaluations", None)
    rewritten = html[:match.start(1)] + json.dumps(
        bootstrap, ensure_ascii=False, separators=(",", ":")
    ) + html[match.end(1):]
    path.write_text(rewritten, encoding="utf-8")


def _file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _report_fixture():
    return {
        "date": REPORT_DATE,
        "market": {"status": "closed", "index": 3580.2},
        "chanlun_structure": {"trend": "up"},
        "picks_pure": [{
            "code": "000001",
            "name": "正式结构候选",
            "dates": ["2026-08-20", REPORT_DATE],
            "opens": [9.8, 10.0],
            "highs": [10.2, 10.3],
            "lows": [9.7, 9.9],
            "closes": [10.0, 10.1],
            "volumes": [1000, 1200],
            "best_buy_point": {
                "type": "三买", "price": 10.0, "index": 0
            },
        }],
        "picks_fusion": [{
            "code": "000001",
            "name": "正式融合主推",
            "dates": ["2026-08-20", REPORT_DATE],
            "opens": [9.8, 10.0],
            "highs": [10.2, 10.3],
            "lows": [9.7, 9.9],
            "closes": [10.0, 10.1],
            "volumes": [1000, 1200],
            "best_buy_point": {
                "type": "三买", "price": 10.0, "index": 0
            },
        }],
        "decision_brief": {
            "summary": "正式辅助决策保持不变",
            "risk_reasons": ["正式风险原因"],
        },
        "diagnostics": {"formal": {"status": "ok"}},
        "data_quality": {
            "report_date": REPORT_DATE,
            "generated_at": "2026-08-21T15:01:02+08:00",
            "bar_state": "closed",
            "is_trading_day": True,
            "is_official": True,
            "sources_trusted": True,
            "market_status": "verified",
            "stock_pool_source": "fixture",
        },
        "h4_t3_pool": {
            "status": "ok",
            "production_attested": True,
            "mode": "production",
            "horizon": "T+3",
            "strategy": "H4",
            "strategy_version": STRATEGY_VERSION,
            "candidates": [],
        },
    }


class EnableShadowEvaluationSnapshotTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="shadow_snapshot_test_")
        self.addCleanup(shutil.rmtree, self.tmpdir)
        self.docs = Path(self.tmpdir) / "docs"
        report = _report_fixture()
        generate_report(report, output_dir=self.docs, comparison_db_path="")
        update_data_json(report, output_dir=self.docs)
        daily_path = self.docs / "data" / f"{REPORT_DATE}.json"
        daily = _read_json(daily_path)
        daily.pop("shadow_evaluations", None)
        daily_path.write_text(
            json.dumps(daily, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        aggregate_path = self.docs / "data.json"
        aggregate = _read_json(aggregate_path)
        aggregate["reports"][REPORT_DATE].pop("shadow_evaluations", None)
        aggregate_path.write_text(
            json.dumps(aggregate, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        _strip_legacy_shadow_from_html(self.docs / "index.html")
        _strip_legacy_shadow_from_html(
            self.docs / REPORT_DATE / "index.html"
        )

    def _enable(self):
        return snapshot.enable_shadow_evaluation_snapshot(
            docs_dir=self.docs,
            report_date=REPORT_DATE,
            started_at=STARTED_AT,
        )

    def test_builds_only_post_deployment_empty_h4_contract(self):
        daily_path = self.docs / "data" / f"{REPORT_DATE}.json"
        before = _read_json(daily_path)
        before_digest = _formal_digest(before)

        result = self._enable()

        after = _read_json(daily_path)
        shadow = after["shadow_evaluations"]
        experiment = shadow["experiments"][0]
        self.assertEqual(result["formal_digest_before"], before_digest)
        self.assertEqual(result["formal_digest_after"], before_digest)
        self.assertEqual(_formal_digest(after), before_digest)
        self.assertEqual(shadow["schema_version"], 1)
        self.assertEqual(shadow["mode"], "shadow")
        self.assertFalse(shadow["affects_production"])
        self.assertEqual(shadow["status"], "collecting")
        self.assertEqual(shadow["started_at"], STARTED_AT)
        self.assertTrue(shadow["production_guard"]["unchanged"])
        self.assertEqual(
            shadow["production_guard"]["before_sha256"], before_digest
        )
        self.assertEqual(
            shadow["production_guard"]["after_sha256"], before_digest
        )
        self.assertRegex(before_digest, r"^[0-9a-f]{64}$")

        self.assertEqual(experiment["version"], STRATEGY_VERSION)
        self.assertEqual(experiment["upstream_pool"], "picks_pure")
        self.assertEqual(experiment["source_pool"], "h4_t3_pool")
        self.assertEqual(experiment["intended_horizon"], 3)
        self.assertEqual(experiment["entry_mode"], "immediate_close")
        self.assertEqual(experiment["status"], "available")
        self.assertFalse(experiment["affects_production"])
        self.assertFalse(experiment["promotion_eligible"])
        self.assertEqual(experiment["research_tier"], "oot_shadow")
        self.assertEqual(experiment["comparison_status"], "collecting")
        self.assertEqual(experiment["today"]["candidates"], [])
        self.assertEqual(experiment["sample_size"], 0)
        for field in (
            "mean_close_return",
            "median_close_return",
            "up_rate",
            "hit_rate_ge_5",
            "mean_mfe",
            "mean_mae",
            "worst_close_return",
        ):
            self.assertIsNone(experiment[field])
        self.assertEqual(shadow["today_entries"], [])
        self.assertEqual(shadow["scorecards"], [])
        self.assertEqual(shadow["pending"]["status"], "withheld")
        self.assertNotIn("batch", shadow["pending"])
        self.assertNotIn("batch_sha256", shadow["pending"])
        self.assertEqual(
            _shadow_report_authorization(REPORT_DATE, report_path=daily_path)[
                "status"
            ],
            "withheld",
        )

    def test_rebuilds_all_public_planes_and_assets_without_formal_drift(self):
        original_daily = _read_json(
            self.docs / "data" / f"{REPORT_DATE}.json"
        )
        original_aggregate = _read_json(self.docs / "data.json")["reports"][
            REPORT_DATE
        ]
        original_inline = _bootstrap(self.docs / "index.html")[
            "inlineReportData"
        ]
        original_archive = _bootstrap(
            self.docs / REPORT_DATE / "index.html"
        )["inlineReportData"]

        self._enable()

        daily = _read_json(self.docs / "data" / f"{REPORT_DATE}.json")
        aggregate = _read_json(self.docs / "data.json")["reports"][REPORT_DATE]
        inline = _bootstrap(self.docs / "index.html")["inlineReportData"]
        archive = _bootstrap(self.docs / REPORT_DATE / "index.html")[
            "inlineReportData"
        ]
        shadow = daily["shadow_evaluations"]
        for before, after in (
            (original_daily, daily),
            (original_aggregate, aggregate),
            (original_inline, inline),
            (original_archive, archive),
        ):
            self.assertEqual(_formal_digest(after), _formal_digest(before))
            self.assertEqual(after["shadow_evaluations"], shadow)
        js = (self.docs / "assets" / "report-v2.js").read_text(
            encoding="utf-8"
        )
        css = (self.docs / "assets" / "report-v2.css").read_text(
            encoding="utf-8"
        )
        self.assertIn("function renderShadowEvaluations", js)
        self.assertIn(".shadow-card", css)

    def test_rerun_is_idempotent(self):
        self._enable()
        targets = [
            self.docs / "index.html",
            self.docs / "data.json",
            self.docs / "data" / f"{REPORT_DATE}.json",
            self.docs / REPORT_DATE / "index.html",
            self.docs / "assets" / "report-v2.js",
            self.docs / "assets" / "report-v2.css",
        ]
        first = {os.fspath(path): _file_sha(path) for path in targets}

        self._enable()

        second = {os.fspath(path): _file_sha(path) for path in targets}
        self.assertEqual(second, first)

    def test_rejects_wrong_date_and_existing_nonempty_shadow(self):
        with self.assertRaisesRegex(ValueError, "report date mismatch"):
            snapshot.enable_shadow_evaluation_snapshot(
                docs_dir=self.docs,
                report_date="2026-08-20",
                started_at=STARTED_AT,
            )

        daily_path = self.docs / "data" / f"{REPORT_DATE}.json"
        report = _read_json(daily_path)
        report["shadow_evaluations"] = {
            "mode": "shadow",
            "today_entries": [{"code": "000001"}],
        }
        daily_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        with self.assertRaisesRegex(ValueError, "existing shadow snapshot"):
            self._enable()

    def test_generation_formal_drift_fails_before_replacing_docs(self):
        daily_path = self.docs / "data" / f"{REPORT_DATE}.json"
        index_path = self.docs / "index.html"
        original_daily_sha = _file_sha(daily_path)
        original_index_sha = _file_sha(index_path)
        real_rebuild = snapshot._rebuild_staged_public_artifacts

        def drifting_rebuild(
            staged_docs,
            original_planes,
            original_aggregate_payload,
            original_bootstraps,
            report_date,
            expected_shadow,
        ):
            result = real_rebuild(
                staged_docs,
                original_planes,
                original_aggregate_payload,
                original_bootstraps,
                report_date,
                expected_shadow,
            )
            generated = Path(staged_docs) / "data" / f"{REPORT_DATE}.json"
            payload = _read_json(generated)
            payload["decision_brief"]["summary"] = "意外漂移"
            generated.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return result

        with mock.patch.object(
            snapshot,
            "_rebuild_staged_public_artifacts",
            side_effect=drifting_rebuild,
        ):
            with self.assertRaisesRegex(RuntimeError, "formal digest drift"):
                self._enable()

        self.assertEqual(_file_sha(daily_path), original_daily_sha)
        self.assertEqual(_file_sha(index_path), original_index_sha)

    def test_each_target_replace_failure_rolls_back_every_public_artifact(self):
        relative_targets = [
            value.format(report_date=REPORT_DATE)
            for value in snapshot.PUBLIC_TARGETS
        ]
        real_replace = snapshot.os.replace

        for fail_index in range(len(relative_targets)):
            with self.subTest(fail_index=fail_index):
                case_docs = Path(self.tmpdir) / "atomic-case-{}".format(
                    fail_index
                )
                staged_docs = Path(self.tmpdir) / "atomic-stage-{}".format(
                    fail_index
                )
                shutil.copytree(self.docs, case_docs)
                shutil.copytree(self.docs, staged_docs)
                targets = [
                    (case_docs / relative).resolve()
                    for relative in relative_targets
                ]
                original_hashes = {
                    os.fspath(path): _file_sha(path) for path in targets
                }
                for relative in relative_targets:
                    staged_path = staged_docs / relative
                    staged_path.write_bytes(
                        staged_path.read_bytes()
                        + "\nshadow replacement {}\n".format(
                            fail_index
                        ).encode("utf-8")
                    )

                state = {"attempt": 0, "failed": False}

                def fail_one_target_once(source, destination):
                    source_path = Path(source)
                    destination_path = Path(destination)
                    is_next_publish = (
                        source_path.name.endswith(".shadow-next")
                        and destination_path in targets
                    )
                    if is_next_publish:
                        current = state["attempt"]
                        state["attempt"] += 1
                        if current == fail_index and not state["failed"]:
                            state["failed"] = True
                            raise OSError(
                                "injected replace failure {}".format(
                                    fail_index
                                )
                            )
                    return real_replace(source, destination)

                with mock.patch.object(
                    snapshot.os,
                    "replace",
                    side_effect=fail_one_target_once,
                ):
                    with self.assertRaisesRegex(
                        OSError,
                        "injected replace failure {}".format(fail_index),
                    ):
                        snapshot._atomic_replace_targets(
                            staged_docs, case_docs, REPORT_DATE
                        )

                self.assertTrue(state["failed"])
                self.assertEqual(
                    {
                        os.fspath(path): _file_sha(path)
                        for path in targets
                    },
                    original_hashes,
                )
                leftovers = [
                    path
                    for path in case_docs.rglob("*")
                    if path.name.endswith(".shadow-next")
                    or path.name.endswith(".shadow-backup")
                ]
                self.assertEqual(leftovers, [])

    def test_hard_exit_is_recovered_on_rerun_without_mixed_artifacts(self):
        expected_docs = Path(self.tmpdir) / "hard-exit-expected" / "docs"
        case_docs = Path(self.tmpdir) / "hard-exit-case" / "docs"
        expected_docs.parent.mkdir()
        case_docs.parent.mkdir()
        shutil.copytree(self.docs, expected_docs)
        shutil.copytree(self.docs, case_docs)
        snapshot.enable_shadow_evaluation_snapshot(
            docs_dir=expected_docs,
            report_date=REPORT_DATE,
            started_at=STARTED_AT,
        )
        relative_targets = [
            value.format(report_date=REPORT_DATE)
            for value in snapshot.PUBLIC_TARGETS
        ]
        expected_hashes = {
            relative: _file_sha(expected_docs / relative)
            for relative in relative_targets
        }
        child_code = r"""
import os
import sys
from pathlib import Path
from scripts import enable_shadow_evaluation_snapshot as snapshot

docs = Path(sys.argv[1]).resolve()
real_replace = snapshot.os.replace
state = {"attempt": 0}

def hard_exit_after_third_publish(source, destination):
    result = real_replace(source, destination)
    source_path = Path(source)
    destination_path = Path(destination)
    if (
        source_path.name.endswith(".shadow-next")
        and docs in destination_path.parents
    ):
        current = state["attempt"]
        state["attempt"] += 1
        if current == 2:
            os._exit(91)
    return result

snapshot.os.replace = hard_exit_after_third_publish
snapshot.enable_shadow_evaluation_snapshot(
    docs_dir=docs,
    report_date="2026-08-21",
    started_at="2026-08-22",
)
"""
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(filter(None, [
            os.fspath(Path(__file__).resolve().parents[1]),
            env.get("PYTHONPATH", ""),
        ]))
        crashed = subprocess.run(
            [sys.executable, "-c", child_code, os.fspath(case_docs)],
            cwd=os.fspath(Path(__file__).resolve().parents[1]),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        self.assertEqual(crashed.returncode, 91, crashed.stderr)
        journal = snapshot.transaction_journal_path(case_docs)
        self.assertTrue(journal.is_file())

        snapshot.enable_shadow_evaluation_snapshot(
            docs_dir=case_docs,
            report_date=REPORT_DATE,
            started_at=STARTED_AT,
        )

        self.assertEqual(
            {
                relative: _file_sha(case_docs / relative)
                for relative in relative_targets
            },
            expected_hashes,
        )
        leftovers = [
            path
            for path in case_docs.parent.rglob("*")
            if path.name.endswith(".shadow-next")
            or path.name.endswith(".shadow-backup")
            or path == journal
        ]
        self.assertEqual(leftovers, [])

    def test_concurrent_public_drift_is_not_overwritten(self):
        case_docs = Path(self.tmpdir) / "concurrent-drift" / "docs"
        case_docs.parent.mkdir()
        shutil.copytree(self.docs, case_docs)
        target = case_docs / "index.html"
        other_targets = [
            case_docs / value.format(report_date=REPORT_DATE)
            for value in snapshot.PUBLIC_TARGETS
            if value != "index.html"
        ]
        other_hashes = {
            os.fspath(path): _file_sha(path) for path in other_targets
        }
        real_validate = snapshot._validate_staged_docs

        def drift_after_validation(*args, **kwargs):
            result = real_validate(*args, **kwargs)
            target.write_bytes(target.read_bytes() + b"\nexternal drift\n")
            return result

        with mock.patch.object(
            snapshot,
            "_validate_staged_docs",
            side_effect=drift_after_validation,
        ):
            with self.assertRaisesRegex(
                RuntimeError, "public artifact changed during staging"
            ):
                snapshot.enable_shadow_evaluation_snapshot(
                    docs_dir=case_docs,
                    report_date=REPORT_DATE,
                    started_at=STARTED_AT,
                )

        self.assertTrue(target.read_bytes().endswith(b"external drift\n"))
        self.assertEqual(
            {
                os.fspath(path): _file_sha(path) for path in other_targets
            },
            other_hashes,
        )

    def test_rejects_unofficial_open_or_untrusted_snapshot(self):
        violations = (
            ("is_official", False, "official"),
            ("bar_state", "open", "closed"),
            ("sources_trusted", False, "trusted"),
            ("market_status", "stale", "verified"),
        )
        for index, (field, value, message) in enumerate(violations):
            with self.subTest(field=field):
                case_docs = Path(self.tmpdir) / "quality-{}".format(index) / "docs"
                case_docs.parent.mkdir()
                shutil.copytree(self.docs, case_docs)
                daily_path = case_docs / "data" / f"{REPORT_DATE}.json"
                report = _read_json(daily_path)
                report["data_quality"][field] = value
                daily_path.write_text(
                    json.dumps(report, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(ValueError, message):
                    snapshot.enable_shadow_evaluation_snapshot(
                        docs_dir=case_docs,
                        report_date=REPORT_DATE,
                        started_at=STARTED_AT,
                    )

    def test_report_date_is_validated_before_path_resolution(self):
        with self.assertRaisesRegex(ValueError, "report_date must be YYYY-MM-DD"):
            snapshot.enable_shadow_evaluation_snapshot(
                docs_dir=self.docs,
                report_date="../2026-08-21",
                started_at=STARTED_AT,
            )

    def test_tampered_html_or_asset_is_rejected_before_publish(self):
        real_rebuild = snapshot._rebuild_staged_public_artifacts
        cases = (
            (
                "asset",
                lambda staged: (staged / "assets" / "report-v2.js").write_bytes(
                    (staged / "assets" / "report-v2.js").read_bytes()
                    + b"\nwindow.evil = true;\n"
                ),
                "asset whitelist mismatch",
            ),
            (
                "html",
                lambda staged: (staged / "index.html").write_text(
                    (staged / "index.html").read_text(encoding="utf-8")
                    .replace(
                        "</head>",
                        '<script src="https://evil.invalid/x.js"></script></head>',
                    ),
                    encoding="utf-8",
                ),
                "HTML whitelist mismatch",
            ),
        )
        for index, (name, tamper, expected_error) in enumerate(cases):
            with self.subTest(name=name):
                case_docs = Path(self.tmpdir) / "tamper-{}".format(index) / "docs"
                case_docs.parent.mkdir()
                shutil.copytree(self.docs, case_docs)

                def tampering_rebuild(*args, **kwargs):
                    result = real_rebuild(*args, **kwargs)
                    tamper(Path(args[0]))
                    return result

                with mock.patch.object(
                    snapshot,
                    "_rebuild_staged_public_artifacts",
                    side_effect=tampering_rebuild,
                ):
                    with self.assertRaisesRegex(RuntimeError, expected_error):
                        snapshot.enable_shadow_evaluation_snapshot(
                            docs_dir=case_docs,
                            report_date=REPORT_DATE,
                            started_at=STARTED_AT,
                        )


class DocsPublishLockTest(unittest.TestCase):
    def test_daily_run_uses_the_same_lock_wrapper_before_normal_work(self):
        root = Path(__file__).resolve().parents[1]
        daily = (root / "daily_run.sh").read_text(encoding="utf-8")
        wrapper = root / "scripts" / "run_with_docs_publish_lock.py"
        self.assertTrue(wrapper.is_file())
        self.assertIn("CHANLUN_DOCS_PUBLISH_LOCK_HELD", daily)
        self.assertIn("CHANLUN_DOCS_PUBLISH_LOCK_PATH", daily)
        self.assertIn("scripts/run_with_docs_publish_lock.py", daily)
        self.assertLess(
            daily.index("scripts/run_with_docs_publish_lock.py"),
            daily.index("source ~/.zshrc"),
        )

    def test_lock_wrapper_blocks_until_the_shared_lock_is_released(self):
        root = Path(__file__).resolve().parents[1]
        wrapper = root / "scripts" / "run_with_docs_publish_lock.py"
        with tempfile.TemporaryDirectory(prefix="docs_publish_lock_") as tmp:
            lock_path = Path(tmp) / "publish.lock"
            marker = Path(tmp) / "ran"
            holder_code = (
                "import fcntl,sys; "
                "f=open(sys.argv[1],'a+'); "
                "fcntl.flock(f.fileno(),fcntl.LOCK_EX); "
                "print('ready',flush=True); sys.stdin.readline()"
            )
            holder = subprocess.Popen(
                [sys.executable, "-c", holder_code, os.fspath(lock_path)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.addCleanup(lambda: holder.kill() if holder.poll() is None else None)
            self.assertEqual(holder.stdout.readline().strip(), "ready")
            command = (
                "from pathlib import Path; "
                "Path({!r}).write_text('ran',encoding='utf-8')"
            ).format(os.fspath(marker))
            wrapped = subprocess.Popen(
                [
                    sys.executable,
                    os.fspath(wrapper),
                    "--lock-path",
                    os.fspath(lock_path),
                    "--",
                    sys.executable,
                    "-c",
                    command,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.addCleanup(lambda: wrapped.kill() if wrapped.poll() is None else None)
            time.sleep(0.2)
            self.assertIsNone(wrapped.poll())
            self.assertFalse(marker.exists())
            holder.stdin.write("\n")
            holder.stdin.flush()
            holder.communicate(timeout=5)
            stdout, stderr = wrapped.communicate(timeout=5)
            self.assertEqual(wrapped.returncode, 0, stdout + stderr)
            self.assertEqual(marker.read_text(encoding="utf-8"), "ran")


if __name__ == "__main__":
    unittest.main()
