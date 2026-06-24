"""Stock review data models."""
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict


@dataclass
class Holding:
    account: str
    code: str
    name: str
    source: str
    quantity: Optional[float] = None
    cost_price: Optional[float] = None
    market_price: Optional[float] = None
    market_value: Optional[float] = None
    pnl: Optional[float] = None
    pnl_pct: Optional[float] = None
    note: str = ""


@dataclass
class StockReviewResult:
    holding: Holding
    price_snapshot: dict
    chanlun_daily: dict
    chanlun_30min: dict
    fundamentals: dict
    news: dict
    rule_action: dict
    llm_review: dict
    risks: List[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d
