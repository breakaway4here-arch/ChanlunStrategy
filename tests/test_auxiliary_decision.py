import unittest

from chanlun.auxiliary_decision import (
    build_decision_brief,
    build_limit_up_snapshot,
)


def _item(code="300308", sector="通信设备", lianban=1, first_time="09:25"):
    return {
        "code": code,
        "name": code,
        "sector": sector,
        "lianban": lianban,
        "first_time": first_time,
        "fund": 100,
    }


def _diagnostics(total, parsed, *, errors=0, status="verified", date="2026-08-20"):
    return {
        "raw_total": total,
        "parsed_count": parsed,
        "parse_error_count": errors,
        "evidence_date": date,
        "data_status": status,
        "source": "eastmoney_limit_pools",
        "error": "" if status == "verified" else "upstream unavailable",
    }


class LimitUpSnapshotTests(unittest.TestCase):
    def test_verified_complete_requires_total_and_parsed_items_to_match(self):
        snapshot = build_limit_up_snapshot(
            "2026-08-20",
            [_item("300308"), _item("002281")],
            _diagnostics(2, 2),
            limit_down_total=12,
            as_of="2026-08-20T15:10:00+08:00",
            generated_at="2026-08-20T15:11:00+08:00",
        )

        self.assertEqual(snapshot["status"], "verified_complete")
        self.assertEqual(snapshot["raw_total"], 2)
        self.assertEqual(snapshot["parsed_count"], 2)
        self.assertEqual(snapshot["coverage"], 1.0)
        self.assertEqual(snapshot["limit_down_total"], 12)

    def test_verified_zero_is_distinct_from_missing_items(self):
        snapshot = build_limit_up_snapshot(
            "2026-08-20", [], _diagnostics(0, 0), limit_down_total=0
        )

        self.assertEqual(snapshot["status"], "verified_empty")
        self.assertEqual(snapshot["coverage"], 1.0)

    def test_nonzero_total_with_some_items_is_partial(self):
        snapshot = build_limit_up_snapshot(
            "2026-08-20",
            [_item()],
            _diagnostics(3, 1, errors=2),
            limit_down_total=12,
        )

        self.assertEqual(snapshot["status"], "partial")
        self.assertEqual(snapshot["coverage"], 0.3333)
        self.assertEqual(snapshot["parse_error_count"], 2)

    def test_nonzero_total_with_no_items_is_error_not_verified_empty(self):
        snapshot = build_limit_up_snapshot(
            "2026-08-20", [], _diagnostics(79, 0, errors=79)
        )

        self.assertEqual(snapshot["status"], "error")
        self.assertEqual(snapshot["coverage"], 0.0)

    def test_missing_upstream_evidence_is_missing(self):
        snapshot = build_limit_up_snapshot(
            "2026-08-20",
            [],
            _diagnostics(None, 0, status="missing"),
        )

        self.assertEqual(snapshot["status"], "missing")
        self.assertIn("upstream unavailable", snapshot["error"])

    def test_evidence_date_mismatch_is_error(self):
        snapshot = build_limit_up_snapshot(
            "2026-08-20",
            [_item()],
            _diagnostics(1, 1, date="2026-08-19"),
        )

        self.assertEqual(snapshot["status"], "error")
        self.assertIn("date mismatch", snapshot["error"])

    def test_theme_groups_and_leaders_are_derived_from_facts(self):
        snapshot = build_limit_up_snapshot(
            "2026-08-20",
            [
                _item("300308", "通信设备", 2, "09:25"),
                _item("002281", "通信设备", 1, "09:31"),
                _item("688525", "半导体", 1, "10:05"),
            ],
            _diagnostics(3, 3),
        )

        self.assertEqual(snapshot["theme_groups"][0]["name"], "通信设备")
        self.assertEqual(snapshot["theme_groups"][0]["count"], 2)
        self.assertEqual(snapshot["leaders"][0]["code"], "300308")
        self.assertEqual(snapshot["leaders"][0]["link_type"], "limit_up_leader")


def _event(
    title,
    theme,
    *,
    score=62,
    no_impact=False,
    category="policy",
    positive_stocks=None,
):
    return {
        "title": title,
        "content": title,
        "ctime": 1787190000,
        "impact_score": score,
        "impact_level": "重大" if score >= 55 else "一般",
        "tradability": "强" if score >= 45 else "中",
        "event_category": category,
        "affected_themes": [theme] if theme else [],
        "matched_hot_sectors": ["通信"] if theme == "光模块" else [],
        "market_validation": "板块资金流排名2" if theme == "光模块" else "",
        "stock_list": [],
        "impact": {
            "status": "ok",
            "no_impact": no_impact,
            "headline": "对A股无明显影响" if no_impact else title,
            "analysis": [] if no_impact else ["事件催化需要盘面继续确认"],
            "positive_sectors": [] if no_impact else [theme],
            "negative_sectors": [theme] if category == "risk" else [],
            "positive_stocks": positive_stocks or [],
            "negative_stocks": [],
        },
    }


def _watchlist():
    return {
        "config_revision": "watchlist-20260820-01",
        "items": [
            {
                "code": "300308",
                "name": "中际旭创",
                "tags": ["用户重点观察", "光通信"],
                "thesis": "跟踪海外算力和高速光模块催化",
                "fact_status": "fresh",
                "candidate_intersections": [],
                "evidence_refs": ["watch-fact:2026-08-20:300308"],
            },
            {
                "code": "688525",
                "name": "佰维存储",
                "tags": ["用户重点观察", "存储"],
                "thesis": "跟踪存储涨价",
                "fact_status": "fresh",
                "candidate_intersections": [],
                "evidence_refs": ["watch-fact:2026-08-20:688525"],
            },
        ],
    }


class DecisionBriefTests(unittest.TestCase):
    def _brief(self, events, llm_analyzer=None):
        return build_decision_brief(
            "2026-08-20",
            events,
            sector_flow=[
                {"name": "通信", "flow": 20.0, "change_pct": 2.0},
                {"name": "半导体", "flow": 10.0, "change_pct": 1.0},
            ],
            limit_up_snapshot={
                "status": "verified_complete",
                "theme_groups": [{"name": "通信设备", "count": 3}],
                "leaders": [
                    {
                        "code": "000001",
                        "name": "事实龙头",
                        "sector": "通信设备",
                        "link_type": "limit_up_leader",
                        "evidence_ref": "limit-up:2026-08-20:000001",
                    }
                ],
            },
            personal_watchlist=_watchlist(),
            llm_analyzer=llm_analyzer,
        )

    def test_overseas_optical_event_links_watchlist_with_evidence(self):
        event = _event(
            "海外光通信股上涨强化高速光模块景气预期",
            "光模块",
            positive_stocks=[
                {"name": "中际旭创", "code": "300308", "reason": "光通信映射"}
            ],
        )

        brief = self._brief([event])

        self.assertEqual(brief["status"], "rules_only")
        self.assertEqual(len(brief["theses"]), 1)
        links = brief["theses"][0]["stock_links"]
        middle = next(link for link in links if link["code"] == "300308")
        self.assertEqual(middle["link_type"], "watchlist_intersection")
        self.assertTrue(middle["evidence_ref"].startswith("watch-fact:"))
        self.assertIn(
            middle["evidence_ref"], brief["theses"][0]["evidence_refs"]
        )

    def test_no_impact_recap_is_not_promoted_to_top_catalyst(self):
        recap = _event(
            "整点回顾：指数反弹与板块复盘",
            "光模块",
            no_impact=True,
        )
        catalyst = _event("光模块行业新增订单", "光模块", score=40)

        brief = self._brief([recap, catalyst])

        self.assertEqual(len(brief["theses"]), 1)
        self.assertNotIn(
            brief["arbitration"][0]["event_ref"],
            brief["theses"][0]["evidence_refs"],
        )
        self.assertEqual(
            brief["arbitration"][0]["arbitration_result"], "no_impact"
        )

    def test_positive_and_risk_directions_can_coexist(self):
        brief = self._brief([
            _event("光通信需求上行", "光模块"),
            _event(
                "半导体公司被立案调查",
                "半导体",
                category="risk",
                score=50,
            ),
        ])

        self.assertEqual(
            {thesis["direction"] for thesis in brief["theses"]},
            {"positive", "negative"},
        )

    def test_does_not_fabricate_rows_to_reach_three(self):
        brief = self._brief([_event("单一半导体催化", "半导体")])

        self.assertEqual(len(brief["theses"]), 1)

    def test_valid_llm_enriches_but_does_not_replace_grounded_thesis(self):
        def analyzer(packet):
            self.assertTrue(packet["directions"][0]["stock_links"])
            evidence_ref = packet["directions"][0]["evidence_refs"][0]
            return {
                "model": "fake-model",
                "prompt_version": "decision-brief-v1",
                "schema_version": "1",
                "theses": [
                    {
                        "theme": "光模块",
                        "direction": "positive",
                        "stage": "confirmed",
                        "confidence": "medium",
                        "evidence_refs": [evidence_ref],
                        "watchlist_codes": ["300308"],
                        "summary": "海外催化已获通信资金验证，继续观察扩散强度。",
                        "next_trigger": ["通信涨停梯队继续扩散"],
                        "invalidation": ["板块资金转负且重点股走弱"],
                    }
                ],
            }

        brief = self._brief(
            [_event("海外光通信需求上行", "光模块")], analyzer
        )

        self.assertEqual(brief["status"], "ok")
        self.assertEqual(brief["model"], "fake-model")
        self.assertIn("海外催化", brief["theses"][0]["llm_summary"])
        self.assertEqual(
            brief["theses"][0]["next_trigger"], ["通信涨停梯队继续扩散"]
        )

    def test_invalid_llm_schema_evidence_or_stock_falls_back_explicitly(self):
        bad_payloads = [
            {
                "theme": "光模块",
                "direction": "up",
                "stage": "confirmed",
                "confidence": "medium",
                "evidence_refs": [],
                "watchlist_codes": [],
                "summary": "bad direction",
            },
            {
                "theme": "光模块",
                "direction": "positive",
                "stage": "confirmed",
                "confidence": "medium",
                "evidence_refs": ["event:unknown"],
                "watchlist_codes": [],
                "summary": "bad evidence",
            },
            {
                "theme": "光模块",
                "direction": "positive",
                "stage": "confirmed",
                "confidence": "medium",
                "evidence_refs": [],
                "watchlist_codes": ["999999"],
                "summary": "bad stock",
            },
        ]
        for bad in bad_payloads:
            with self.subTest(bad=bad):
                brief = self._brief(
                    [_event("光通信需求上行", "光模块")],
                    lambda _packet, bad=bad: {
                        "model": "fake-model",
                        "prompt_version": "decision-brief-v1",
                        "schema_version": "1",
                        "theses": [bad],
                    },
                )
                self.assertEqual(brief["status"], "rules_only")
                self.assertTrue(brief["llm_error"])

    def test_llm_direction_conflict_is_audited_and_rule_direction_is_kept(self):
        def analyzer(packet):
            return {
                "model": "fake-model",
                "prompt_version": "decision-brief-v1",
                "schema_version": "1",
                "theses": [{
                    "theme": "光模块",
                    "direction": "negative",
                    "stage": "confirmed",
                    "confidence": "high",
                    "evidence_refs": packet["directions"][0]["evidence_refs"],
                    "watchlist_codes": ["300308"],
                    "summary": "模型认为方向转负",
                    "next_trigger": [],
                    "invalidation": [],
                }],
            }

        brief = self._brief([_event("光通信需求上行", "光模块")], analyzer)

        self.assertEqual(brief["theses"][0]["direction"], "positive")
        self.assertTrue(
            any(
                row.get("arbitration_reason") == "llm_direction_conflict_rule_kept"
                for row in brief["arbitration"]
            )
        )

    def test_llm_failure_has_rules_only_fallback(self):
        def analyzer(_packet):
            raise RuntimeError("provider unavailable")

        brief = self._brief([_event("光通信需求上行", "光模块")], analyzer)

        self.assertEqual(brief["status"], "rules_only")
        self.assertIn("provider unavailable", brief["llm_error"])
        self.assertEqual(len(brief["theses"]), 1)

    def test_hard_risk_survives_event_llm_no_impact_conflict(self):
        risk = _event(
            "半导体公司被立案调查",
            "半导体",
            category="risk",
            score=50,
            no_impact=True,
        )

        brief = self._brief([risk])

        self.assertEqual(brief["arbitration"][0]["arbitration_result"], "risk")
        self.assertEqual(brief["theses"][0]["direction"], "negative")
        self.assertEqual(brief["theses"][0]["stage"], "risk")
        self.assertEqual(
            brief["arbitration"][0]["arbitration_reason"],
            "event_llm_no_impact_conflicts_with_hard_risk",
        )

    def test_event_llm_unavailable_does_not_default_to_positive_direction(self):
        event = _event("产业信息尚待语义判断", "半导体", score=40)
        event["impact"] = {
            "status": "failed",
            "no_impact": True,
            "positive_sectors": [],
            "negative_sectors": [],
        }

        brief = self._brief([event])

        self.assertEqual(brief["arbitration"][0]["arbitration_result"], "monitor")
        self.assertEqual(brief["theses"], [])

    def test_market_validation_confirms_only_the_matching_theme(self):
        event = _event("收盘时贵金属走强，光模块和创新药活跃", "光模块")
        event["affected_themes"] = ["光模块", "创新药", "黄金"]
        event["impact"]["positive_sectors"] = ["光模块", "创新药", "黄金"]
        event["matched_hot_sectors"] = ["贵金属"]
        event["market_validation"] = "板块资金流排名3"

        brief = self._brief([event])
        by_theme = {thesis["theme"]: thesis for thesis in brief["theses"]}

        self.assertEqual(by_theme["黄金"]["stage"], "confirmed")
        self.assertEqual(by_theme["创新药"]["stage"], "developing")
        self.assertEqual(by_theme["光模块"]["stage"], "confirmed")
        self.assertTrue(
            any(
                link["name"] == "通信"
                for link in by_theme["光模块"]["sector_links"]
            )
        )

    def test_stale_watchlist_config_is_not_current_fact_intersection(self):
        watchlist = _watchlist()
        watchlist["items"][0]["fact_status"] = "stale"
        watchlist["items"][0]["evidence_refs"] = []

        brief = build_decision_brief(
            "2026-08-20",
            [_event("海外光通信需求上行", "光模块")],
            sector_flow=[{"name": "通信", "flow": 20.0}],
            limit_up_snapshot={"status": "missing", "theme_groups": [], "leaders": []},
            personal_watchlist=watchlist,
        )

        links = brief["theses"][0]["stock_links"]
        self.assertFalse(any(link["code"] == "300308" for link in links))
        self.assertNotIn("300308", brief["theses"][0]["watchlist_impacts"])

    def test_mixed_event_assigns_direction_per_theme(self):
        event = _event("光通信景气上行但煤炭需求承压", "光模块")
        event["affected_themes"] = ["光模块", "煤炭"]
        event["impact"]["positive_sectors"] = ["通信"]
        event["impact"]["negative_sectors"] = ["煤炭"]

        brief = self._brief([event])
        by_theme = {thesis["theme"]: thesis for thesis in brief["theses"]}

        self.assertEqual(by_theme["光模块"]["direction"], "positive")
        self.assertEqual(by_theme["煤炭"]["direction"], "negative")

    def test_unmatched_theme_does_not_inherit_event_direction(self):
        event = _event("光通信景气上行，煤炭仅被顺带提及", "光模块")
        event["affected_themes"] = ["光模块", "煤炭"]
        event["impact"]["positive_sectors"] = ["通信"]
        event["impact"]["negative_sectors"] = []

        brief = self._brief([event])
        by_theme = {thesis["theme"]: thesis for thesis in brief["theses"]}

        self.assertEqual(by_theme["光模块"]["direction"], "positive")
        self.assertNotIn("煤炭", by_theme)

    def test_named_stock_is_not_copied_to_an_unrelated_event_theme(self):
        event = _event("光通信景气上行但煤炭需求承压", "光模块")
        event["affected_themes"] = ["光模块", "煤炭"]
        event["impact"]["positive_sectors"] = ["通信"]
        event["impact"]["negative_sectors"] = ["煤炭"]
        event["stock_list"] = [{
            "code": "300308",
            "name": "中际旭创",
            "sector": "通信",
        }]

        brief = self._brief([event])
        by_theme = {thesis["theme"]: thesis for thesis in brief["theses"]}

        optical_codes = {
            link["code"] for link in by_theme["光模块"]["stock_links"]
        }
        coal_codes = {
            link["code"] for link in by_theme["煤炭"]["stock_links"]
        }
        self.assertIn("300308", optical_codes)
        self.assertNotIn("300308", coal_codes)

    def test_malformed_event_llm_arrays_degrade_without_crashing(self):
        malformed_values = [123, [{"name": "通信"}], ["通信", 3]]

        for malformed in malformed_values:
            with self.subTest(malformed=malformed):
                event = _event("产业事件待核验", "光模块", score=40)
                event["impact"]["positive_sectors"] = malformed

                brief = self._brief([event])

                self.assertEqual(
                    brief["arbitration"][0]["arbitration_result"],
                    "monitor",
                )
                self.assertEqual(brief["theses"], [])

    def test_ungrounded_stock_name_in_llm_free_text_is_rejected(self):
        def analyzer(packet):
            row = packet["directions"][0]
            return {
                "model": "fake-model",
                "prompt_version": "decision-brief-v1",
                "schema_version": "1",
                "theses": [{
                    "theme": row["theme"],
                    "direction": row["direction"],
                    "stage": row["stage"],
                    "confidence": row["confidence"],
                    "evidence_refs": row["evidence_refs"],
                    "watchlist_codes": row["watchlist_codes"],
                    "stock_mentions": [],
                    "summary": "贵州茅台是绝对龙头并已涨停。",
                    "next_trigger": [],
                    "invalidation": [],
                }],
            }

        brief = self._brief([_event("光通信需求上行", "光模块")], analyzer)

        self.assertEqual(brief["status"], "rules_only")
        self.assertIn("ungrounded stock name", brief["llm_error"])

    def test_theme_term_that_is_also_a_stock_name_is_not_misclassified(self):
        def analyzer(packet):
            row = packet["directions"][0]
            return {
                "model": "fake-model",
                "prompt_version": "decision-brief-v1",
                "schema_version": "1",
                "theses": [{
                    "theme": row["theme"],
                    "direction": row["direction"],
                    "stage": row["stage"],
                    "confidence": row["confidence"],
                    "evidence_refs": row["evidence_refs"],
                    "watchlist_codes": row["watchlist_codes"],
                    "stock_mentions": [],
                    "summary": "机器人方向出现产业催化。",
                    "next_trigger": [],
                    "invalidation": [],
                }],
            }

        brief = build_decision_brief(
            "2026-08-20",
            [_event("机器人产业催化", "机器人")],
            sector_flow=[],
            limit_up_snapshot={"status": "verified_empty"},
            personal_watchlist={"items": []},
            llm_analyzer=analyzer,
            known_stock_map={"300024": "机器人"},
        )

        self.assertEqual(brief["status"], "ok")
        self.assertEqual(brief["theses"][0]["llm_summary"], "机器人方向出现产业催化。")

    def test_llm_cannot_relabel_watch_stock_as_leader_in_free_text(self):
        def analyzer(packet):
            row = packet["directions"][0]
            links = {
                (link["code"], link["link_type"]): link
                for link in row["stock_links"]
            }
            mentions = []
            for key in [("000001", "limit_up_leader"),
                        ("300308", "watchlist_intersection")]:
                link = links[key]
                mentions.append({
                    "code": link["code"],
                    "link_type": link["link_type"],
                    "evidence_ref": link["evidence_ref"],
                })
            return {
                "model": "fake-model",
                "prompt_version": "decision-brief-v1",
                "schema_version": "1",
                "theses": [{
                    "theme": row["theme"],
                    "direction": row["direction"],
                    "stage": row["stage"],
                    "confidence": row["confidence"],
                    "evidence_refs": row["evidence_refs"],
                    "watchlist_codes": row["watchlist_codes"],
                    "stock_mentions": mentions,
                    "summary": "中际旭创是龙头，事实龙头同步走强。",
                    "next_trigger": [],
                    "invalidation": [],
                }],
            }

        brief = self._brief([_event("光通信需求上行", "光模块")], analyzer)

        self.assertEqual(brief["status"], "rules_only")
        self.assertIn("leader claims are not allowed", brief["llm_error"])

    def test_llm_stage_upgrade_or_conflict_is_blocked_and_audited(self):
        def analyzer(packet):
            row = packet["directions"][0]
            return {
                "model": "fake-model",
                "prompt_version": "decision-brief-v1",
                "schema_version": "1",
                "theses": [{
                    "theme": row["theme"],
                    "direction": row["direction"],
                    "stage": "risk",
                    "confidence": "high",
                    "evidence_refs": row["evidence_refs"],
                    "watchlist_codes": row["watchlist_codes"],
                    "stock_mentions": [],
                    "summary": "模型试图把已确认利多改成风险。",
                    "next_trigger": [],
                    "invalidation": [],
                }],
            }

        brief = self._brief([_event("光通信需求上行", "光模块")], analyzer)

        thesis = brief["theses"][0]
        self.assertEqual(thesis["stage"], "confirmed")
        self.assertNotIn("llm_stage", thesis)
        self.assertEqual(thesis["llm_summary"], "")
        self.assertTrue(any(
            row.get("arbitration_reason") == "llm_stage_conflict_rule_kept"
            for row in brief["arbitration"]
        ))

    def test_hard_risk_reserves_a_slot_with_three_higher_scored_positives(self):
        events = [
            _event("光通信强催化", "光模块", score=80),
            _event("人工智能强催化", "AI算力", score=75),
            _event("机器人强催化", "机器人", score=70),
            _event(
                "煤炭公司被立案调查",
                "煤炭",
                score=59,
                category="risk",
            ),
        ]
        for event in events[:3]:
            event["matched_hot_sectors"] = list(event["affected_themes"])
            event["market_validation"] = "对应主题资金已验证"

        brief = self._brief(events)

        self.assertEqual(len(brief["theses"]), 3)
        self.assertTrue(any(
            thesis["theme"] == "煤炭" and thesis["direction"] == "negative"
            for thesis in brief["theses"]
        ))


if __name__ == "__main__":
    unittest.main()
