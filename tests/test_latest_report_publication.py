"""Synthetic, offline recovery of an interrupted same-day publication."""
import json
import copy
from pathlib import Path
from unittest import mock

import pytest

from chanlun.report_generator import build_aggregate_day_projection, generate_report, update_data_json
from chanlun.report_generator import _build_report_bootstrap, write_data_manifest
from chanlun.report_view_model import build_workspace
from chanlun.decision_workbench import build_decision_workbench
from scripts import enable_shadow_evaluation_snapshot as atomic
from scripts import repair_strategy_scorecard_snapshot as repair
from scripts.validate_today_report import validate_report_contract, validate_runtime_cutover
from scripts.validate_today_report import main as validate_main


DAY = "2026-10-12"


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def docs(tmp_path):
    root = tmp_path / "docs"
    report = {
        "date": DAY, "picks_pure": [], "picks_fusion": [],
        "next_day_boom": {"mode": "disabled", "status": "disabled", "candidates": []},
        "luojie_pool": {"mode": "disabled", "status": "disabled", "candidates": []},
        "selection_input_health": {"schema_version": 1, "status": "verified",
            "formal": {"status": "verified", "formal_actions_allowed": True,
                       "invalid_count": 0}, "sublevels": {}},
        "data_quality": {
            "report_date": DAY, "generated_at": DAY + "T15:05:00+08:00",
            "as_of": DAY + "T15:05:00+08:00", "bar_state": "closed",
            "sources_trusted": True, "is_trading_day": True, "is_official": True,
            "stock_pool_incomplete": False, "market_status": "verified",
            "fallback_used": False, "stale_stock_count": 0, "missing_daily_count": 0,
            "runtime_policy": {"market_history_cutover_mode": "sqlite",
                "recall_strategy_mode": "legacy",
                "decision_semantics": "v2_missing_position_is_observe"}},
        "diagnostics": {"candidate_funnel": {"persist_status": "saved"}},
        "shadow_evaluations": {"production_guard": {"unchanged": True}},
    }
    generate_report(report, output_dir=root, comparison_db_path="")
    update_data_json(report, output_dir=root)
    source = atomic._read_json(root / "data" / (DAY + ".json"))
    assert validate_report_contract(source, require_official=True) == []
    assert validate_runtime_cutover(source) == []
    return root


def publish(docs):
    source = atomic._read_json(docs / "data" / (DAY + ".json"))
    cards = {"schema_version": 2, "formal": [], "baselines": [], "research": [],
             "gates": [], "classification_failures": []}
    receipt = {"status": "finalized", "today_entries": 0,
               "finalized_today_entries": 0, "missing_today_entries": 0}
    cards = source.get("strategy_scorecards") if isinstance(source.get("strategy_scorecards"), dict) else cards
    receipt = (source.get("diagnostics") or {}).get("recommendation_ledger", receipt)
    review = (source.get("diagnostics") or {}).get("strategy_review", {"status": "ok"})
    # Only external DB/ledger evaluation is stubbed; all public reads, report
    # transformations, validators, staging and atomic publication are real.
    with mock.patch.object(repair, "compute_scorecards", return_value=(
            cards, review, 0, receipt)):
        return repair.publish_strategy_scorecard_snapshot(
            docs_dir=docs, report_date=DAY, ledger_path=docs / "unused.jsonl",
            market_db_path="")


def latest(docs):
    path = docs / "data" / (DAY + ".json")
    report = atomic._read_json(path)
    report["data_quality"]["generated_at"] = DAY + "T15:20:00+08:00"
    report["market_temperature"] = {"score": 37, "label": "latest synthetic"}
    report["legitimate_supplement"] = {"source": "latest daily", "value": 13}
    dump(path, report)
    return report


def fingerprints(docs):
    return {str(p.relative_to(docs)): p.read_bytes()
            for p in docs.rglob("*") if p.is_file()}


def test_same_day_partial_update_uses_latest_daily_and_preserves_history_and_shell(docs):
    source = latest(docs)
    aggregate = atomic._read_json(docs / "data.json")
    aggregate["reports"]["2026-10-09"] = {"unmodified_history": True}
    aggregate["dates"].insert(0, "2026-10-09")
    aggregate["extra_config"] = "keep"
    aggregate["reports"][DAY]["legacy_supplement"] = {"keep": True}
    dump(docs / "data.json", aggregate)
    shells = {name: atomic._read_bootstrap_envelope(docs / relative)
              for name, relative in (("inline", "index.html"),
                                     ("archive", DAY + "/index.html"))}
    for relative in ("index.html", DAY + "/index.html"):
        path = docs / relative
        html = path.read_text()
        envelope = atomic._read_bootstrap_envelope(path)
        envelope["decisionWorkbench"] = {"stale_sentinel": True}
        match = atomic._BOOTSTRAP_PATTERN.search(html)
        path.write_text(html[:match.start(1)] + json.dumps(envelope) + html[match.end(1):])
    publish(docs)
    planes = atomic._load_public_planes(docs, DAY)
    assert {p["data_quality"]["generated_at"] for p in planes.values()} == {
        source["data_quality"]["generated_at"]}
    assert planes["inline"] == planes["archive"] == planes["daily"]
    assert planes["daily"]["legitimate_supplement"] == source["legitimate_supplement"]
    assert planes["aggregate"]["market_temperature"] == source["market_temperature"]
    assert planes["aggregate"]["legacy_supplement"] == {"keep": True}
    final_aggregate = atomic._read_json(docs / "data.json")
    assert final_aggregate["reports"]["2026-10-09"] == {"unmodified_history": True}
    assert final_aggregate["dates"] == aggregate["dates"]
    assert final_aggregate["extra_config"] == "keep"
    for name, relative in (("inline", "index.html"), ("archive", DAY + "/index.html")):
        envelope = atomic._read_bootstrap_envelope(docs / relative)
        assert "stale_sentinel" not in envelope["decisionWorkbench"]
        for key in ("top10ApiBase", "precloseApiBase", "accessControlEnabled", "accessKeyHash"):
            assert envelope[key] == shells[name][key]


@pytest.mark.parametrize("case", ["future", "same_time_conflict", "wrong_date", "bad_source"])
def test_conflicting_or_invalid_source_fails_without_writes(docs, case):
    latest(docs)
    if case == "bad_source":
        source_path = docs / "data" / (DAY + ".json")
        source = atomic._read_json(source_path)
        source["data_quality"]["sources_trusted"] = False
        dump(source_path, source)
    else:
        value = atomic._read_json(docs / "data.json")
        old = value["reports"][DAY]
        if case == "future":
            old["data_quality"]["generated_at"] = DAY + "T16:00:00+08:00"
        elif case == "same_time_conflict":
            old["data_quality"]["generated_at"] = DAY + "T15:20:00+08:00"
        else:
            old["data_quality"]["report_date"] = "2026-10-09"
        dump(docs / "data.json", value)
    before = fingerprints(docs)
    with pytest.raises((ValueError, RuntimeError)):
        publish(docs)
    assert fingerprints(docs) == before


@pytest.mark.parametrize("case", ["missing", "truncated"])
def test_bad_aggregate_fails_explicitly_without_losing_history(docs, case):
    latest(docs)
    target = docs / "data.json"
    if case == "missing":
        target.unlink()
    else:
        target.write_text('{"reports":')
    before = fingerprints(docs)
    with pytest.raises((ValueError, RuntimeError), match="aggregate.*history"):
        publish(docs)
    assert fingerprints(docs) == before


@pytest.mark.parametrize("relative,case", [(DAY + "/index.html", "missing"),
    ("index.html", "truncated"), ("data/comparison-index.json", "missing")])
def test_missing_or_broken_derived_file_is_recovered(docs, relative, case):
    source = latest(docs)
    target = docs / relative
    if case == "missing":
        target.unlink()
    else:
        target.write_text("<html>interrupted")
    publish(docs)
    planes = atomic._load_public_planes(docs, DAY)
    assert planes["inline"] == planes["archive"] == planes["daily"]
    assert planes["daily"]["data_quality"] == source["data_quality"]
    assert (docs / "data/comparison-index.json").is_file()


def test_unchanged_snapshot_keeps_selection_facts(docs):
    source = atomic._read_json(docs / "data" / (DAY + ".json"))
    publish(docs)
    daily = atomic._read_json(docs / "data" / (DAY + ".json"))
    assert repair.protected_report_digest(daily) == repair.protected_report_digest(source)


def test_concurrent_edit_is_not_overwritten(docs):
    latest(docs)
    rebuild = repair._rebuild_staged_artifacts
    path = docs / "index.html"
    def edit_after_stage(*args, **kwargs):
        result = rebuild(*args, **kwargs)
        path.write_text("user edit")
        return result
    with mock.patch.object(repair, "_rebuild_staged_artifacts", side_effect=edit_after_stage):
        with pytest.raises(RuntimeError, match="changed during staging"):
            publish(docs)
    assert path.read_text() == "user edit"


def test_failed_atomic_promotion_restores_missing_and_existing_targets(docs):
    latest(docs)
    (docs / DAY / "index.html").unlink()
    before = fingerprints(docs)
    replace = atomic.os.replace
    def fail_once(source, target):
        if str(source).endswith(".shadow-next") and Path(target) == docs / "assets/report-v2.js":
            raise OSError("synthetic promotion failure")
        return replace(source, target)
    with mock.patch.object(atomic.os, "replace", side_effect=fail_once):
        with pytest.raises(OSError, match="synthetic promotion failure"):
            publish(docs)
    assert fingerprints(docs) == before
    publish(docs)
    assert atomic._load_public_planes(docs, DAY)["daily"] == atomic._load_public_planes(docs, DAY)["archive"]


def test_public_validation_rejects_mixed_files_without_market_requests(docs):
    latest(docs)
    with mock.patch("scripts.validate_today_report.fetch_market_indices", side_effect=AssertionError("network forbidden")):
        assert validate_main(["--docs-dir", str(docs), "--public-planes-only", DAY]) == 1
        publish(docs)
        assert validate_main(["--docs-dir", str(docs), "--public-planes-only", DAY]) == 0


def test_ready_check_uses_source_not_html_or_mtime():
    script = (Path(__file__).resolve().parents[1] / "daily_run.sh").read_text()
    body = script.split("is_today_output_ready() {", 1)[1].split("\n}", 1)[0]
    assert '"$TODAY_DATA_PATH"' in body
    assert "INDEX_PATH" not in body
    assert "mtime" not in body
    commit = script.split("commit_today_report_if_changed() {", 1)[1].split("\n}", 1)[0]
    assert commit.index("--public-planes-only") < commit.index("git add")


def test_public_validation_rejects_stale_bootstrap_business_projection(docs):
    publish(docs)
    path = docs / "index.html"
    html = path.read_text()
    match = atomic._BOOTSTRAP_PATTERN.search(html)
    envelope = atomic._read_bootstrap_envelope(path)
    envelope["decisionWorkbench"] = {"stale_sentinel": True}
    path.write_text(html[:match.start(1)] + json.dumps(envelope) + html[match.end(1):])
    assert validate_main(["--docs-dir", str(docs), "--public-planes-only", DAY]) == 1


@pytest.mark.parametrize("mutation", [None, "price", "score", "order", "health", "wrong_point"])
def test_frozen_oct12_light_projection_accepts_only_representation_differences(mutation):
    frozen_docs = Path(__file__).resolve().parents[1] / "docs"
    source = atomic._read_json(frozen_docs / "data" / (DAY + ".json"))
    # The rolling data.json will eventually remove this date. Recreate only
    # the observed original-window/null-price differences of its 10/12 rows.
    aggregate = build_aggregate_day_projection(source)
    aggregate["selection_input_health"].pop("by_view", None)
    for row in aggregate["picks_pure"]:
        point = row["best_buy_point"]
        offset = point["startup_index"] - point["index"]
        for candidate_point in [point] + row["buy_points"]:
            candidate_point["index"] += offset
        for field in ("reference_price", "current_price", "distance_from_reference_pct"):
            point[field] = None
    if mutation == "price":
        aggregate["picks_pure"][0]["best_buy_point"]["price"] += 1
    elif mutation == "score":
        aggregate["picks_pure"][0]["score"] += 1
    elif mutation == "order":
        aggregate["picks_pure"].reverse()
    elif mutation == "health":
        aggregate["selection_input_health"]["formal"]["formal_actions_allowed"] = False
    elif mutation == "wrong_point":
        aggregate["picks_pure"][0]["best_buy_point"]["index"] -= 1
    assert repair._aggregate_matches_source(aggregate, source) is (mutation is None)


def reordered_window_projections():
    """Use recorded, differently truncated windows with a source order change."""
    frozen_docs = Path(__file__).resolve().parents[1] / "docs"
    source = atomic._read_json(frozen_docs / "data" / (DAY + ".json"))
    source["picks_pure"] = source["picks_pure"][:2]
    source["picks_fusion"] = []
    aggregate = build_aggregate_day_projection(copy.deepcopy(source))
    by_code = {row["code"]: row for row in source["picks_pure"]}
    source["picks_pure"] = [
        by_code[row["code"]] for row in reversed(aggregate["picks_pure"])
    ]
    for row in aggregate["picks_pure"]:
        point = row["best_buy_point"]
        offset = point["startup_index"] - point["index"]
        for candidate_point in [point] + row["buy_points"]:
            candidate_point["index"] += offset
        for field in ("reference_price", "current_price", "distance_from_reference_pct"):
            point[field] = None
    return source, aggregate


def test_light_window_offsets_bind_source_by_identity_after_projection_reorders():
    source, aggregate = reordered_window_projections()
    assert [row["code"] for row in source["picks_pure"]] != [
        row["code"] for row in aggregate["picks_pure"]
    ]
    assert len({row["best_buy_point"]["index"] for row in source["picks_pure"]}) == 2
    before = copy.deepcopy((source, aggregate))
    assert repair._aggregate_matches_source(aggregate, source)
    assert (source, aggregate) == before


@pytest.mark.parametrize("mutation", [
    "price", "score", "code", "order", "index", "signal_date", "removed",
])
def test_reordered_light_projection_still_rejects_changed_facts(mutation):
    source, aggregate = reordered_window_projections()
    rows = aggregate["picks_pure"]
    if mutation == "price":
        rows[0]["best_buy_point"]["price"] += 1
    elif mutation == "score":
        rows[0]["score"] += 1
    elif mutation == "code":
        rows[0]["code"] = "999999"
    elif mutation == "order":
        rows.reverse()
    elif mutation == "index":
        rows[0]["best_buy_point"]["index"] += 1
    elif mutation == "signal_date":
        rows[0]["best_buy_point"]["signal_date"] = "2026-10-09"
    elif mutation == "removed":
        rows.pop()
    assert not repair._aggregate_matches_source(aggregate, source)


@pytest.mark.parametrize("plane", ["source", "aggregate", "identical"])
@pytest.mark.parametrize("invalid", ["empty", "duplicate"])
def test_light_projection_rejects_ambiguous_pool_identities(plane, invalid):
    source, aggregate = reordered_window_projections()
    target = aggregate if plane == "aggregate" else source
    rows = target["picks_pure"]
    rows[0]["code"] = "" if invalid == "empty" else rows[1]["code"]
    if plane == "identical":
        aggregate = copy.deepcopy(source)
    assert not repair._aggregate_matches_source(aggregate, source)


@pytest.fixture
def real_docs(tmp_path):
    root = Path(__file__).resolve().parents[1]
    source = atomic._read_json(root / "docs/data" / (DAY + ".json"))
    docs = tmp_path / "docs"
    (docs / "data").mkdir(parents=True)
    (docs / DAY).mkdir()
    dump(docs / "data" / (DAY + ".json"), source)
    dump(docs / "data.json", {"dates": [DAY], "reports": {DAY: build_aggregate_day_projection(source)}})
    dump(docs / "data/comparison-index.json", {})
    write_data_manifest(DAY, str(docs / "data"))
    repair.copy_report_assets(str(docs))
    # Reconstruct the original pre-finalizer view set using the real frozen
    # daily. Independent baseline rows are copied from the published HTML, not
    # recomputed from daily data. This fixture survives rotating home pages.
    published_source = copy.deepcopy(source)
    published_source["workspace"] = build_workspace(source)
    envelope = _build_report_bootstrap(published_source, published_source, "", "", "", "", output_dir=str(docs))
    recorded = atomic._read_json(root / "tests/fixtures/report_20261012_baseline_evidence.json")
    envelope["recommendationEvidence"]["views"]["baseline"] = recorded["rows"]
    envelope["decisionWorkbench"] = build_decision_workbench(
        published_source, published_source["workspace"], envelope["recommendationEvidence"], phase="formal")
    envelope["inlineReportData"] = source
    for relative, prefix in (("index.html", ""), (DAY + "/index.html", "../")):
        (docs / relative).write_text(repair._build_report_v2_html(
            DAY, repair._escape_inline_json(envelope), asset_prefix=prefix,
            asset_version=repair._report_asset_version()))
    return docs


def rewrite_bootstrap(path, change):
    html = path.read_text()
    match = atomic._BOOTSTRAP_PATTERN.search(html)
    envelope = atomic._read_bootstrap_envelope(path)
    change(envelope)
    path.write_text(html[:match.start(1)] + json.dumps(envelope) + html[match.end(1):])


def test_real_same_generation_preserves_independent_minutes_and_closes_stale_view(real_docs):
    original = atomic._read_bootstrap_envelope(real_docs / "index.html")
    assert len(original["recommendationEvidence"]["views"]["highlights"]) == 10
    publish(real_docs)
    final = atomic._read_bootstrap_envelope(real_docs / "index.html")
    assert final["recommendationEvidence"]["views"]["baseline"] == original["recommendationEvidence"]["views"]["baseline"]
    for view, rows in original["recommendationEvidence"]["views"].items():
        if view != "highlights":
            assert final["recommendationEvidence"]["views"][view] == rows
    missing = [row for rows in final["recommendationEvidence"]["views"].values() for row in rows
               if row["sublevel_30m"]["status"] == "missing"]
    assert missing and all(row["source_identity"]["status"] == "available" for row in missing)
    assert final["recommendationEvidence"]["views"]["highlights"] == []
    assert all(s["strategy_id"] != "highlights" for item in final["decisionWorkbench"]["items"] for s in item["strategy_results"])
    assert validate_main(["--docs-dir", str(real_docs), "--public-planes-only", DAY]) == 0


@pytest.mark.parametrize("mutation", ["date", "code", "summary_code", "pool", "rank", "ref", "evidence_conflict"])
def test_same_generation_wrong_evidence_binding_is_rejected(real_docs, mutation):
    def corrupt(envelope):
        evidence = envelope["recommendationEvidence"]
        row = evidence["views"]["baseline"][0]
        if mutation == "date": evidence["report_date"] = "2026-10-09"
        elif mutation == "code": row["code"] = "999999"
        elif mutation == "summary_code": row["summary"]["code"] = "999999"
        elif mutation == "pool": row["summary"]["pool_identity"] = "luojie_pool"
        elif mutation == "rank": row["summary"]["view_rank"] = 999
        elif mutation == "ref":
            for item in envelope["decisionWorkbench"]["items"]:
                for result in item["strategy_results"]:
                    if result["strategy_id"] == "baseline":
                        result["candidate"]["ref"]["code"] = "999999"
        else: row["sublevel_30m"]["ema5"] = 999
    rewrite_bootstrap(real_docs / "index.html", corrupt)
    before = fingerprints(real_docs)
    with pytest.raises((ValueError, RuntimeError)):
        publish(real_docs)
    assert fingerprints(real_docs) == before


def test_older_generation_never_donates_minute_evidence(real_docs):
    path = real_docs / "data" / (DAY + ".json")
    source = atomic._read_json(path)
    source["data_quality"]["generated_at"] = DAY + "T16:20:00+08:00"
    dump(path, source)
    publish(real_docs)
    final = atomic._read_bootstrap_envelope(real_docs / "index.html")
    assert all(row["sublevel_30m"]["status"] == "missing" for row in final["recommendationEvidence"]["views"]["baseline"])


def test_published_receipt_detects_changed_independent_minute_payload(real_docs):
    publish(real_docs)
    def corrupt(envelope):
        envelope["recommendationEvidence"]["views"]["baseline"][0]["sublevel_30m"]["ema5"] = 999
    rewrite_bootstrap(real_docs / "index.html", corrupt)
    assert validate_main(["--docs-dir", str(real_docs), "--public-planes-only", DAY]) == 1


def test_independent_kpl_refresh_keeps_receipt_valid_and_allows_next_repair(real_docs):
    from scripts.refresh_kaipanla_context import refresh_context

    publish(real_docs)
    before = atomic._read_bootstrap_envelope(real_docs / "index.html")
    context = copy.deepcopy(before["inlineReportData"]["kaipanla_context"])
    context["groups"][0]["name"] += " · frozen refresh"
    context["fetched_at"] = DAY + "T17:20:00+08:00"
    result = refresh_context(real_docs, DAY, context=context)
    assert result["status"] == "updated"
    after = atomic._read_bootstrap_envelope(real_docs / "index.html")
    assert after["recommendationEvidence"] == before["recommendationEvidence"]
    assert after["decisionWorkbench"] == before["decisionWorkbench"]
    assert after["reportPublication"] == before["reportPublication"]
    assert validate_main(["--docs-dir", str(real_docs), "--public-planes-only", DAY]) == 0
    # Source/plane alignment still includes the supplement, even though the
    # independent evidence receipt does not depend on it.
    aggregate_path = real_docs / "data.json"
    aggregate = atomic._read_json(aggregate_path)
    aggregate["reports"][DAY]["kaipanla_context"] = before["inlineReportData"]["kaipanla_context"]
    dump(aggregate_path, aggregate)
    assert validate_main(["--docs-dir", str(real_docs), "--public-planes-only", DAY]) == 1
    aggregate["reports"][DAY]["kaipanla_context"] = context
    dump(aggregate_path, aggregate)
    publish(real_docs)
    final = atomic._read_bootstrap_envelope(real_docs / "index.html")
    assert final["inlineReportData"]["kaipanla_context"] == context
    assert final["recommendationEvidence"] == before["recommendationEvidence"]
