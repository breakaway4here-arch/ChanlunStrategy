"""Canonical instrument identity used by all market-data boundaries.

The old data path treated a six-digit code as enough information to choose a
provider route.  That is false for codes such as ``000001`` and ``000063``:
the stock is a Shenzhen instrument while an index with the same code is a
Shanghai instrument.  This module keeps the compatibility default as a stock
identity, but never infers an index from a code.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional


_EXCHANGES = frozenset(("SH", "SZ", "BJ"))
_ASSET_TYPES = frozenset(("stock", "index"))
_INDEX_EXCHANGE_REGISTRY = {
    "000001": "SH",
    "000300": "SH",
    "000688": "SH",
    "000905": "SH",
    "399001": "SZ",
    "399006": "SZ",
}


def infer_stock_exchange(code: Any) -> Optional[str]:
    """Infer an A-share stock exchange from an unambiguous code prefix.

    This is an exchange registry rule for stock identities only.  It is never
    used to infer the asset type, and unknown prefixes fail closed.
    """
    text = str(code or "").strip()
    if text.startswith(("6", "68")):
        return "SH"
    if text.startswith(("0", "3")):
        return "SZ"
    if text.startswith(("4", "8", "92")):
        return "BJ"
    return None


@dataclass(frozen=True)
class InstrumentIdentity:
    """Stable logical identity for one instrument."""

    asset_type: str
    exchange: str
    code: str

    def __post_init__(self) -> None:
        asset_type = str(self.asset_type or "").strip().lower()
        exchange = str(self.exchange or "").strip().upper()
        code = str(self.code or "").strip()
        if not asset_type or exchange not in _EXCHANGES:
            raise ValueError("identity requires a known asset_type and exchange")
        if len(code) != 6 or any(char < "0" or char > "9" for char in code):
            raise ValueError("identity code must be a six-digit string")
        if asset_type not in _ASSET_TYPES:
            raise ValueError(
                "unsupported identity asset_type: {}".format(asset_type)
            )
        if asset_type == "stock":
            expected = infer_stock_exchange(code)
            if expected is not None and expected != exchange:
                raise ValueError(
                    "stock code {} belongs to {}, not {}".format(
                        code, expected, exchange
                    )
                )
        object.__setattr__(self, "asset_type", asset_type)
        object.__setattr__(self, "exchange", exchange)
        object.__setattr__(self, "code", code)

    @property
    def key(self) -> str:
        return "{}|{}|{}".format(self.asset_type, self.exchange, self.code)

    def as_dict(self) -> dict:
        return {
            "asset_type": self.asset_type,
            "exchange": self.exchange,
            "code": self.code,
        }


def _mapping_identity(value: Mapping[str, Any]) -> Mapping[str, Any]:
    nested = value.get("identity")
    if not isinstance(nested, Mapping):
        return value
    # A nested identity may intentionally omit a field while the outer
    # mapping supplies it.  Preserve nested values, but do not drop the
    # outer fallback after the contradiction checks below.
    merged = dict(nested)
    for field in ("asset_type", "exchange", "code"):
        if merged.get(field) is None and value.get(field) is not None:
            merged[field] = value.get(field)
    return merged


def normalize_identity(
    value: Any = None,
    *,
    code: Any = None,
    exchange: Optional[str] = None,
    asset_type: Optional[str] = None,
) -> InstrumentIdentity:
    """Normalize a legacy code or an explicit identity.

    A bare code remains compatible only as a *stock* lookup.  Index callers
    must pass ``asset_type='index'`` and an explicit exchange (or an
    ``InstrumentIdentity``).  Explicit exchange/asset fields are checked for
    contradictions before any provider route is built.
    """
    raw_asset = asset_type
    raw_exchange = exchange
    raw_code = code
    if isinstance(value, InstrumentIdentity):
        if code is not None and str(code).strip() != value.code:
            raise ValueError("identity code conflicts with explicit code")
        raw_asset = value.asset_type
        raw_exchange = value.exchange
        raw_code = value.code
        if asset_type is not None and str(asset_type).lower() != value.asset_type:
            raise ValueError("identity asset_type conflicts with explicit asset_type")
        if exchange is not None and str(exchange).upper() != value.exchange:
            raise ValueError("identity exchange conflicts with explicit exchange")
    elif isinstance(value, Mapping):
        nested = value.get("identity")
        if isinstance(nested, Mapping):
            for field, explicit in (
                ("asset_type", value.get("asset_type")),
                ("exchange", value.get("exchange")),
                ("code", value.get("code")),
            ):
                nested_value = nested.get(field)
                if explicit is not None and nested_value is not None:
                    left = str(explicit).strip()
                    right = str(nested_value).strip()
                    if field == "asset_type":
                        left, right = left.lower(), right.lower()
                    elif field == "exchange":
                        left, right = left.upper(), right.upper()
                    if left != right:
                        raise ValueError(
                            "mapping identity {} conflicts with outer mapping".format(field)
                        )
        mapping = _mapping_identity(value)
        mapping_asset = mapping.get("asset_type")
        mapping_exchange = mapping.get("exchange")
        if (
            asset_type is not None
            and mapping_asset is not None
            and str(asset_type).lower() != str(mapping_asset).lower()
        ):
            raise ValueError("mapping asset_type conflicts with explicit asset_type")
        if (
            exchange is not None
            and mapping_exchange is not None
            and str(exchange).upper() != str(mapping_exchange).upper()
        ):
            raise ValueError("mapping exchange conflicts with explicit exchange")
        mapping_code = mapping.get("code")
        if (
            code is not None
            and mapping_code is not None
            and str(code).strip() != str(mapping_code).strip()
        ):
            raise ValueError("mapping code conflicts with explicit code")
        raw_asset = mapping_asset if asset_type is None else asset_type
        raw_exchange = mapping_exchange if exchange is None else exchange
        raw_code = mapping_code if mapping_code is not None else raw_code
    elif value is not None:
        if code is not None and str(code).strip() != str(value).strip():
            raise ValueError("value code conflicts with explicit code")
        raw_code = value

    normalized_asset = str(raw_asset or "").strip().lower()
    normalized_code = str(raw_code or "").strip()
    normalized_exchange = str(raw_exchange or "").strip().upper()
    if not normalized_asset:
        normalized_asset = "stock"
    if normalized_asset not in _ASSET_TYPES:
        raise ValueError("unsupported identity asset_type: {}".format(normalized_asset))
    if not normalized_asset:
        raise ValueError("identity asset_type is required")
    if not normalized_exchange:
        if normalized_asset == "stock":
            normalized_exchange = infer_stock_exchange(normalized_code) or ""
        else:
            raise ValueError("non-stock identities require an explicit exchange")
    if normalized_asset == "stock" and not normalized_exchange:
        raise ValueError("unknown stock exchange for code {}".format(normalized_code))
    return InstrumentIdentity(
        normalized_asset,
        normalized_exchange,
        normalized_code,
    )


def identity_key(value: Any = None, **kwargs: Any) -> str:
    return normalize_identity(value, **kwargs).key


def normalize_index_identity(
    value: Any = None,
    *,
    code: Any = None,
    exchange: Optional[str] = None,
) -> InstrumentIdentity:
    """Resolve an index while checking nested and explicit fields."""
    fields = ("asset_type", "exchange", "code")

    def canonical_field(field: str, item: Any) -> Optional[str]:
        if item is None:
            return None
        text = str(item).strip()
        if field == "asset_type":
            return text.lower()
        if field == "exchange":
            return text.upper()
        return text

    if isinstance(value, InstrumentIdentity):
        if value.asset_type != "index":
            raise ValueError("index entry received a non-index identity")
        if code is not None and canonical_field("code", code) != value.code:
            raise ValueError("index identity conflicts with explicit code")
        if exchange is not None and canonical_field("exchange", exchange) != value.exchange:
            raise ValueError("index exchange conflicts with explicit exchange")
        registered = _INDEX_EXCHANGE_REGISTRY.get(value.code)
        if registered is not None and registered != value.exchange:
            raise ValueError(
                "registered index {} belongs to {}, not {}".format(
                    value.code, registered, value.exchange
                )
            )
        return value

    nested = value.get("identity") if isinstance(value, Mapping) else None
    nested_fields = (
        nested.as_dict()
        if isinstance(nested, InstrumentIdentity)
        else nested
        if isinstance(nested, Mapping)
        else {}
    )
    mapping_fields = value if isinstance(value, Mapping) else {}
    merged = {}
    for field in fields:
        nested_value = canonical_field(field, nested_fields.get(field))
        outer_value = canonical_field(field, mapping_fields.get(field))
        if (
            nested_value is not None
            and outer_value is not None
            and nested_value != outer_value
        ):
            raise ValueError(
                "index mapping {} conflicts with nested identity".format(field)
            )
        merged[field] = (
            nested_value if nested_value is not None else outer_value
        )

    value_code = canonical_field(
        "code", value if not isinstance(value, Mapping) else merged.get("code")
    )
    if code is not None:
        explicit_code = canonical_field("code", code)
        if value_code is not None and value_code != explicit_code:
            raise ValueError("index identity conflicts with explicit code")
        value_code = explicit_code
    if not value_code:
        raise ValueError("index code is required")

    mapped_asset = merged.get("asset_type")
    if mapped_asset is not None and mapped_asset != "index":
        raise ValueError("index entry received a non-index identity")

    mapped_exchange = merged.get("exchange")
    if exchange is not None:
        explicit_exchange = canonical_field("exchange", exchange)
        if (
            mapped_exchange is not None
            and mapped_exchange != explicit_exchange
        ):
            raise ValueError("index mapping exchange conflicts with explicit exchange")
        mapped_exchange = explicit_exchange

    registered = _INDEX_EXCHANGE_REGISTRY.get(value_code)
    if registered is not None:
        if mapped_exchange is not None and mapped_exchange != registered:
            raise ValueError(
                "registered index {} belongs to {}, not {}".format(
                    value_code, registered, mapped_exchange
                )
            )
        mapped_exchange = registered
    if mapped_exchange is None:
        raise ValueError("unknown index exchange for code {}".format(value_code))
    return normalize_identity(
        {
            "asset_type": "index",
            "exchange": mapped_exchange,
            "code": value_code,
        }
    )


def identity_from_row(row: Mapping[str, Any], *, default_asset_type: str = "stock") -> InstrumentIdentity:
    return normalize_identity(
        row,
        asset_type=row.get("asset_type", default_asset_type),
    )
