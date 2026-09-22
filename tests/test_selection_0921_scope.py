import json
import unittest
from pathlib import Path

from chanlun.identity import normalize_identity


FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "selection_2026_09_21_scope.json"
)

EXPECTED_MISSING_30M = frozenset(
    {
        "SZ:000617",
        "SZ:000766",
        "SZ:002153",
        "SZ:002273",
        "SZ:002335",
        "SZ:002555",
        "SZ:002645",
        "SZ:002733",
        "SZ:002845",
        "SZ:002939",
        "SZ:002993",
        "SZ:300100",
        "SZ:300842",
        "SZ:300890",
        "SZ:301050",
        "SZ:301310",
        "SZ:301377",
        "SH:600392",
        "SH:600683",
        "SH:601016",
        "SH:601360",
        "SH:601619",
        "SH:603501",
        "SH:688351",
        "SH:688390",
        "SH:688410",
        "SH:688798",
        "SH:688818",
        "SH:688981",
    }
)

EXPECTED_MISSING_15M = frozenset(
    {
        "SZ:001267",
        "SZ:001309",
        "SZ:002028",
        "SZ:002077",
        "SZ:002185",
        "SZ:002212",
        "SZ:002261",
        "SZ:002371",
        "SZ:002409",
        "SZ:002560",
        "SZ:002902",
        "SZ:003026",
        "SZ:300033",
        "SZ:300085",
        "SZ:300136",
        "SZ:300283",
        "SZ:300442",
        "SZ:300454",
        "SZ:300458",
        "SZ:300623",
        "SZ:300672",
        "SZ:300782",
        "SZ:300803",
        "SZ:300913",
        "SZ:301165",
        "SZ:301308",
        "SZ:301380",
        "SH:600026",
        "SH:600360",
        "SH:600498",
        "SH:600584",
        "SH:600641",
        "SH:601360",
        "SH:601872",
        "SH:601919",
        "SH:603005",
        "SH:603501",
        "SH:603986",
        "SH:605358",
        "SH:688012",
        "SH:688041",
        "SH:688048",
        "SH:688082",
        "SH:688110",
        "SH:688120",
        "SH:688123",
        "SH:688141",
        "SH:688146",
        "SH:688225",
        "SH:688256",
        "SH:688347",
        "SH:688362",
        "SH:688372",
        "SH:688385",
        "SH:688403",
        "SH:688521",
        "SH:688525",
        "SH:688702",
        "SH:688783",
        "SH:688981",
    }
)

EXPECTED_RESEARCH_MINUTE_MISSING = frozenset(
    {"SZ:002845", "SH:600392", "SH:600683", "SH:688410"}
)

EXPECTED_RESEARCH_VALID_NO_CONFIRM = frozenset(
    {
        "SZ:000963",
        "SZ:002019",
        "SZ:002031",
        "SZ:002081",
        "SZ:002169",
        "SZ:002196",
        "SZ:002249",
        "SZ:002271",
        "SZ:300059",
        "SZ:300127",
        "SZ:300136",
        "SZ:300170",
        "SZ:300181",
        "SZ:300204",
        "SZ:300253",
        "SZ:300357",
        "SZ:300436",
        "SZ:300458",
        "SZ:300476",
        "SZ:300488",
        "SZ:300546",
        "SZ:300652",
        "SZ:300660",
        "SZ:300723",
        "SZ:300970",
        "SZ:301012",
        "SZ:301162",
        "SZ:301188",
        "SZ:301246",
        "SZ:301293",
        "SZ:301301",
        "SZ:301371",
        "SH:600129",
        "SH:600276",
        "SH:600380",
        "SH:600791",
        "SH:600867",
        "SH:600888",
        "SH:600909",
        "SH:600977",
        "SH:601636",
        "SH:601858",
        "SH:603319",
        "SH:603341",
        "SH:603728",
        "SH:603777",
        "SH:605060",
        "SH:688036",
        "SH:688059",
        "SH:688221",
        "SH:688277",
        "SH:688626",
    }
)


class TestSelection0921Scope(unittest.TestCase):
    def _load_scope(self):
        self.assertTrue(
            FIXTURE_PATH.is_file(),
            f"missing fixed-scope fixture: {FIXTURE_PATH}",
        )
        return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    def _validated_entries(self, scope, collection):
        expected_statuses = {
            "missing_30m": {"minute30_missing"},
            "missing_15m": {"minute15_missing"},
            "research_observation": {
                "minute30_missing",
                "valid_no_confirm",
            },
        }[collection]
        entries = []
        for index, row in enumerate(scope[collection]):
            context = f"{collection}[{index}]"
            self.assertEqual({"identity", "expected"}, set(row), context)
            self.assertIn(row["expected"], expected_statuses, context)
            identity = row["identity"]
            self.assertEqual(
                {"asset_type", "exchange", "code"},
                set(identity),
                context,
            )
            self.assertEqual("stock", identity["asset_type"], context)
            self.assertIsInstance(identity["code"], str, context)
            self.assertRegex(identity["code"], r"^\d{6}$", context)
            self.assertIn(identity["exchange"], {"SH", "SZ"}, context)
            try:
                normalized = normalize_identity(identity)
            except (TypeError, ValueError) as exc:
                self.fail(f"{context} invalid stock identity: {exc}")
            self.assertEqual(identity, normalized.as_dict(), context)
            entries.append(
                (f"{normalized.exchange}:{normalized.code}", row["expected"])
            )
        self.assertEqual(
            len(entries),
            len({identity for identity, _ in entries}),
            f"duplicate identity in {collection}",
        )
        return entries

    def test_fixed_scope_counts_match_the_0921_evidence(self):
        scope = self._load_scope()
        self.assertEqual(
            {"trade_date", "missing_30m", "missing_15m", "research_observation"},
            set(scope),
        )
        self.assertEqual("2026-09-21", scope["trade_date"])
        self.assertEqual(29, len(scope["missing_30m"]))
        self.assertEqual(60, len(scope["missing_15m"]))
        self.assertEqual(56, len(scope["research_observation"]))

    def test_missing_minute_scopes_match_frozen_identity_sets(self):
        scope = self._load_scope()
        actual_missing_30m = {
            identity
            for identity, _ in self._validated_entries(scope, "missing_30m")
        }
        actual_missing_15m = {
            identity
            for identity, _ in self._validated_entries(scope, "missing_15m")
        }

        self.assertEqual(
            EXPECTED_MISSING_30M,
            actual_missing_30m,
            "30m missing scope drifted; compare the explicit identity sets",
        )
        self.assertEqual(
            EXPECTED_MISSING_15M,
            actual_missing_15m,
            "15m missing scope drifted; compare the explicit identity sets",
        )

    def test_research_observation_missing_and_no_confirm_sets_are_disjoint_and_complete(
        self,
    ):
        scope = self._load_scope()
        research_entries = self._validated_entries(scope, "research_observation")
        actual_by_status = {
            status: {
                identity
                for identity, expected in research_entries
                if expected == status
            }
            for status in (
                "minute30_missing",
                "valid_no_confirm",
            )
        }

        self.assertEqual(
            EXPECTED_RESEARCH_MINUTE_MISSING,
            actual_by_status["minute30_missing"],
            "research minute-missing scope drifted",
        )
        self.assertEqual(
            EXPECTED_RESEARCH_VALID_NO_CONFIRM,
            actual_by_status["valid_no_confirm"],
            "research valid-no-confirm scope drifted",
        )
        missing = actual_by_status["minute30_missing"]
        valid_no_confirm = actual_by_status["valid_no_confirm"]
        self.assertEqual(4, len(missing))
        self.assertEqual(52, len(valid_no_confirm))
        self.assertTrue(missing.isdisjoint(valid_no_confirm))
        self.assertEqual(56, len(missing | valid_no_confirm))

        missing_30m = {
            identity
            for identity, _ in self._validated_entries(scope, "missing_30m")
        }
        self.assertTrue(
            missing <= missing_30m,
            "research minute-missing identities must be a subset of missing_30m",
        )
        self.assertTrue(
            valid_no_confirm.isdisjoint(missing_30m),
            "valid-no-confirm identities must not be in missing_30m",
        )

    def test_fixture_entries_contain_only_identity_and_expected_classification(self):
        scope = self._load_scope()
        for collection in (
            "missing_30m",
            "missing_15m",
            "research_observation",
        ):
            self._validated_entries(scope, collection)


if __name__ == "__main__":
    unittest.main()
