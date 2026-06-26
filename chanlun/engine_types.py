"""ChanLun engine shared dataclasses."""

import numpy as np
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Fractal:
    """分型"""
    type: str        # "top" | "bottom"
    index: int       # 原始K线索引
    price: float     # 顶分型取high，底分型取low
    klines: list = field(default_factory=list)  # 构成分型的K线索引列表


@dataclass
class Stroke:
    """笔"""
    start_idx: int
    end_idx: int
    start_price: float
    end_price: float
    direction: str   # "up" | "down"
    start_fractal: Optional[Fractal] = None
    end_fractal: Optional[Fractal] = None


@dataclass
class Segment:
    """线段"""
    strokes: list   # list of Stroke
    start_idx: int
    end_idx: int
    direction: str  # "up" | "down"
    high: float
    low: float
    destroyed_by_idx: Optional[int] = None
    confirmed: bool = True


@dataclass
class Pivot:
    """中枢"""
    ZD: float        # 中枢下沿 = max(段低点)
    ZG: float        # 中枢上沿 = min(段高点)
    segments: list   # 构成中枢的线段列表
    start_idx: int
    end_idx: int
    level: str = "本级别"


@dataclass
class ChanResult:
    """单只股票的完整缠论分析结果"""
    code: str
    name: str
    closes: np.ndarray
    highs: np.ndarray
    lows: np.ndarray
    opens: np.ndarray
    volumes: np.ndarray
    dates: list
    fractals: list = field(default_factory=list)
    strokes: list = field(default_factory=list)
    segments: list = field(default_factory=list)
    pivots: list = field(default_factory=list)
    swing_waves: list = field(default_factory=list)  # swing tracking 笔
    swing_zones: list = field(default_factory=list)  # 笔中枢（swing tracking）
    divergence: Optional[dict] = None
    buy_points: list = field(default_factory=list)
    sell_points: list = field(default_factory=list)
    trend_type: str = ""  # "盘整" | "上涨趋势" | "下跌趋势"
    macd_dif: np.ndarray = None
    macd_dea: np.ndarray = None
    macd_hist: np.ndarray = None
