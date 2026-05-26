"""
Signal tier policy — constants and helpers for classifying buy point signals.

Tiers:
  formal     Fully confirmed daily Chanlun buy point. Recommendable directly.
  candidate  Daily reference upgraded by 30min sub-level confirmation. Recommendable.
  reference  Informational only; never recommended by itself.
  blocked    Explicitly not recommendable.
"""

# —— Tier constants ——
FORMAL_TYPES = {"一买", "二买", "三买"}

UPGRADEABLE_REFERENCE_TYPES = {
    "二买待确认",
    "盘整背驰参考",
    "中枢震荡低吸参考",
}

REFERENCE_ONLY_TYPES = {
    "swing底背驰参考",
}

CANDIDATE_SEED_TYPES = {
    "swing底背驰候选种子",
}

BLOCKED_TYPES = {
    "三买已错过",
    "类二买",
}

CANDIDATE_TYPES = {
    "二买候选",
    "盘整低吸候选",
    "中枢低吸候选",
    "三买候选",
    "底背驰候选",
}

ALL_RECOMMENDABLE_TYPES = FORMAL_TYPES | CANDIDATE_TYPES

UPGRADE_OUTPUT_TYPE = {
    "二买待确认": "二买候选",
    "盘整背驰参考": "盘整低吸候选",
    "中枢震荡低吸参考": "中枢低吸候选",
    "三买待确认": "三买候选",
    "swing底背驰候选种子": "底背驰候选",
}

# —— Helper functions ——

def infer_signal_tier(bp):
    """Infer the signal tier from a buy point dict's 'type' or explicit 'tier' field."""
    if "tier" in bp:
        return bp["tier"]
    t = bp.get("type", "")
    if t in FORMAL_TYPES:
        return "formal"
    if t in CANDIDATE_TYPES:
        return "candidate"
    if t in CANDIDATE_SEED_TYPES:
        return "seed"
    if t in UPGRADEABLE_REFERENCE_TYPES or t in REFERENCE_ONLY_TYPES:
        return "reference"
    if t in BLOCKED_TYPES:
        return "blocked"
    return "reference"


def is_formal_buy(bp):
    return infer_signal_tier(bp) == "formal"


def is_upgradeable_reference(bp):
    t = bp.get("type", "")
    return t in UPGRADEABLE_REFERENCE_TYPES


def is_candidate_seed(bp):
    return infer_signal_tier(bp) == "seed"


def is_reference_only(bp):
    t = bp.get("type", "")
    return t in REFERENCE_ONLY_TYPES


def is_recommendable_buy(bp):
    return infer_signal_tier(bp) in ("formal", "candidate")


def is_blocked_buy(bp):
    return infer_signal_tier(bp) == "blocked"
