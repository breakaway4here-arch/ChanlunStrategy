"""
缠论选股系统 — 所有可调参数
"""

# ============================================================
# 运行时间
# ============================================================
RUN_HOUR = 14
RUN_MINUTE = 35

# ============================================================
# 缠论计算参数（纯净版 & 融合版共用）
# ============================================================
BI_MIN_KLINE_COUNT = 5       # 笔的最小包含K线数（含两端）
SEGMENT_MIN_STROKES = 3      # 线段的最小笔数
PIVOT_MIN_SEGMENTS = 3       # 中枢的最小次级别段数
USE_SEGMENT_BREAK_BUILDER = True  # 线段破坏确认版（False 回退到固定窗口）
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
DAY_LOOKBACK = 100           # 日线回溯天数（足够覆盖3段→中枢→背驰→买卖点全链）
MIN30_LOOKBACK_DAYS = 10     # 30分钟线回溯天数（约80根K线，足够缠论分析）

# ============================================================
# 纯净版参数
# ============================================================
PURE_DIVERGENCE_THRESHOLD = 0.85   # 背驰力度比阈值
DIVERGENCE_PLATEAU = 0.5           # 盘整背驰力度比阈值（更严格）

# 纯净版评分权重
PURE_WEIGHT_DIVERGENCE = 0.40
PURE_WEIGHT_RESONANCE = 0.35
PURE_WEIGHT_POSITION = 0.25

# ============================================================
# 融合版参数
# ============================================================

# 大盘趋势 — 强趋势
FUSION_DIVERGENCE_TREND = 0.85       # 强趋势背驰阈值（宽松）
FUSION_BUY_POINTS_TREND = ["三买"]  # 强趋势优先（类二买 phase1 禁用）

# 大盘趋势 — 弱市
FUSION_DIVERGENCE_WEAK = 0.75        # 弱市背驰阈值（严格）
FUSION_BUY_POINTS_WEAK = ["一买", "二买"]    # 弱市优先

# MA 均线
MA_SHORT = 5
MA_MID = 10
MA_LONG = 20
MA_TREND = 50   # 大盘趋势判断用

# 评分权重
FUSION_WEIGHT_DIVERGENCE = 0.30
FUSION_WEIGHT_RESONANCE = 0.25
FUSION_WEIGHT_POSITION = 0.20
FUSION_WEIGHT_SECTOR = 0.15
FUSION_WEIGHT_VOLUME = 0.10

# 止盈三档（相对买入价的涨幅百分比）
FUSION_TRAILING_TIERS = [3.0, 5.0, 8.0]

# 硬止损（相对买入价的跌幅百分比）
FUSION_HARD_STOP = -5.0

# 活跃标记
FUSION_ACTIVE_DAYS = 7       # 近N日内
FUSION_ACTIVE_THRESHOLD = 5.0  # 单日涨幅超过此值标记为活跃

# ============================================================
# 多级候选升级特性开关
# ============================================================
ENABLE_DAILY_STRUCTURE_POOL = True       # 日线结构池（含可升级参考信号）
ENABLE_30MIN_CANDIDATE_UPGRADE = True    # 30分钟候选升级

# 候选覆盖率优化开关（默认全开，仅线上紧急隔离时关闭）
ENABLE_SWING_POSITION_SEEDS = True           # swing底背驰参考 → 候选种子（日线位置保护）
ENABLE_RELAXED_30MIN_CONFIRM = True          # 30min中确认放宽（EMA5收复 + 止跌结构）
ENABLE_SIGNAL_DISTRIBUTION_DIAGNOSTICS = True  # 详细信号分布诊断
ENABLE_FUSION_ADMISSION_POLICY = True         # 融合版独立admission策略（MA多头+大盘强弱门槛矩阵）

# ============================================================
# 强势启动候选（独立于底背驰通道的右侧启动检测）
# ============================================================
ENABLE_STRONG_STARTUP_CANDIDATES = True
STRONG_STARTUP_MIN_CHANGE_PCT = 4.0
STRONG_STARTUP_MIN_VOLUME_RATIO = 1.5
STRONG_STARTUP_LOW_POSITION_60D_RATIO = 0.88
STRONG_STARTUP_LOW_POSITION_120D_RATIO = 0.82
STRONG_STARTUP_PRE_START_LOW_RATIO = 1.12

# ============================================================
# 信号时效
# ============================================================
SIGNAL_MAX_AGE_TRADING_DAYS = 10

# ============================================================
# 弱保护访问控制（前端 hash 校验，非安全鉴权）
# ============================================================
ENABLE_WEAK_ACCESS_CONTROL = True
PUBLIC_DATES = ["2026-05-26", "2026-05-27"]
FULL_ACCESS_KEY = "02951e20-6de2-418c-8bab-463647220883"
FULL_ACCESS_KEY_SALT = "chanlun-report-salt-v1"

# ============================================================
# K线本地缓存
# ============================================================
KLINE_CACHE_ENABLED = True
KLINE_CACHE_DIR = ".cache/chanlun"
KLINE_CACHE_VERBOSE = False
KLINE_CACHE_FORCE_REFRESH = False
KLINE_CACHE_TRADING_DAYS = 10
DAY_KLINE_CACHE_RETENTION_TRADING_DAYS = max(DAY_LOOKBACK, KLINE_CACHE_TRADING_DAYS)
MIN30_KLINE_CACHE_RETENTION_TRADING_DAYS = KLINE_CACHE_TRADING_DAYS
DAY_KLINE_INCREMENTAL_FETCH_COUNT = 5
MIN30_KLINE_INCREMENTAL_FETCH_COUNT = 16

# ============================================================
# 通用过滤参数（两版本共用）
# ============================================================
MIN_LISTED_DAYS = 60               # 上市最少天数
MIN_DAILY_AMOUNT = 50_000_000      # 近5日日均最低成交额（元），排除僵尸股
TOP_SECTOR_COUNT = 20              # 取资金流入TOP N板块

# ============================================================
# 涨停/跌停判断阈值
# ============================================================
LIMIT_UP_THRESHOLD = 9.5    # 涨幅 > 此值视为涨停（单位%）
LIMIT_DOWN_THRESHOLD = -9.5  # 跌幅 < 此值视为跌停

# ============================================================
# 输出
# ============================================================
OUTPUT_DIR = "docs"
DEBUG_OUTPUT_DIR = "output_debug"  # debug 模式输出隔离，避免覆盖上线数据
HISTORY_DAYS = 5  # 保留最近N个交易日

# ============================================================
# 新增模块配置
# ============================================================
SECTOR_OUTFLOW_COUNT = 5       # 资金流出 TOP N
LIMIT_UP_PAGE_SIZE = 200       # 涨停板池每页数量
CLS_NEWS_COUNT = 100           # 财联社抓取快讯数量
EVENT_TOP_N = 10               # 事件驱动展示 Top N
