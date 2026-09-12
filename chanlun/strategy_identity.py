"""Shared identities for outputs produced by the current selection policy.

Changing scoring/ranking policy creates a new comparison cohort.  Historical
v1/v2 records remain readable through their stored identity and are never
silently relabelled by these current-output constants.
"""

DECISION_POLICY_VERSION = "decision-v2"
PURE_STRATEGY_VERSION = "daily-pure-close-v2"
FUSION_STRATEGY_VERSION = "daily-fusion-close-v2"
PRE_CLOSE_STRATEGY_VERSION = "preclose-1445-v3"
LUOJIE_RESEARCH_STRATEGY_VERSION = "luojie-15m-research-v2"

# The browser/public transport contract is intentionally independent from the
# strategy identity and remains stable while archived v2 snapshots are read.
PRE_CLOSE_PUBLIC_SCHEMA_VERSION = "preclose-selection-v1"
