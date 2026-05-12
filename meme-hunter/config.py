"""
SOL Meme Hunter v6.0 -- Strategy Configuration
Modify this file to adjust strategy parameters without changing hunter.py

Architecture: 3-Tier (A/B/D) with dynamic scoring and session risk control.
Swap flow: swap swap -> contract-call -> wallet history (NOT swap execute).
Tier C removed: bonding curve tokens cannot be swapped via onchainos swap.

Disclaimer:
This script and all parameter configurations are provided solely for educational
research and technical reference purposes. They do not constitute any investment advice.
Cryptocurrency trading (especially meme coins) carries extremely high risk, including but not limited to:
  - Smart money signals do not guarantee profits; signal delays and market reversals can happen at any time
  - Graduated tokens may dump immediately after migration
  - On-chain transactions are irreversible; once executed they cannot be undone
  - Low market cap tokens have poor liquidity and may not sell at the expected price
Users should adjust all parameters based on their own risk tolerance and assume
full responsibility for any losses incurred from using this strategy.
"""

# ── Operating Mode / 运行模式 ──────────────────────────────────────────────
PAUSED         = False    # True=暂停(不开新仓), False=正常交易 | True=Paused, False=Normal trading
PAPER_TRADE    = False    # True=模拟盘, False=实盘 | True=Paper trading, False=Live trading

# ── Wallet & Chain / 钱包与链 ──────────────────────────────────────────────
CHAIN_ID       = 501                                              # Solana 链 ID | Solana chain ID
SOL_NATIVE     = "11111111111111111111111111111111"                # 原生 SOL 地址 (32个1) | Native SOL address (32 ones)
USDC_ADDR      = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"  # USDC SPL 地址 | USDC SPL address
WALLET         = "AXBCfbioEHiJ48ejNp5feEzWt2iHFLUDNMk27t5vXWLE"  # 交易钱包 | Trading wallet

# ── File Paths / 文件路径 ──────────────────────────────────────────────────
LOG_FILE       = "/tmp/meme_hunter_v6.log"                        # 主日志 | Main log
ACTED_FILE     = "/tmp/meme_hunter_v6_acted.json"                 # 已操作代币记录 | Acted tokens record
SESSION_FILE   = "/tmp/meme_hunter_v6_session.json"               # 会话风控状态 | Session risk state
POSITIONS_FILE = "/tmp/meme_hunter_v6_positions.json"             # 持仓文件 | Positions file
TRADES_FILE    = "/tmp/meme_hunter_v6_trades.json"                # 交易历史 | Trade history

# ── Night Mode / 夜间模式 ─────────────────────────────────────────────────
# UTC 14:00-22:00 = 北京时间 22:00-06:00 (流动性低, 减仓) | Low liquidity hours, reduce size
NIGHT_START_UTC = 14   # UTC 14:00 = 北京 22:00
NIGHT_END_UTC   = 22   # UTC 22:00 = 北京 06:00

# ══════════════════════════════════════════════════════════════════════════════
# TIER A: Smart Money Signal / 聪明钱信号跟单
# 来源: onchainos signal list | Source: onchainos signal list
# 逻辑: STRONG(>=3钱包)直接买入, NORMAL(==2钱包)需hot-tokens确认
# Logic: STRONG(>=3 wallets) buy direct, NORMAL(==2) needs hot-tokens confirmation
# ══════════════════════════════════════════════════════════════════════════════

# -- Position Sizing / 仓位 --
TIER_A_SIZE_DAY    = 8     # 白天每笔 $8 | Day trade size $8
TIER_A_SIZE_NIGHT  = 5     # 夜间每笔 $5 | Night trade size $5

# -- Signal Filters / 信号过滤 --
SM_MIN_WALLETS     = 2     # 最低跟单钱包数 | Min co-rider wallets
SM_STRONG_THRESH   = 3     # >=3钱包=强信号, 直接买入 | >=3 wallets = STRONG, buy direct
SM_LABELS          = [1, 2, 3]  # 1=SmartMoney 2=KOL 3=Whale

# -- Deep Verification / 深度验证 --
TIER_A_MC_MIN         = 200_000    # 最低市值 $200K | Min market cap $200K
TIER_A_MC_MAX         = 2_000_000  # 最高市值 $2M | Max market cap $2M
TIER_A_LIQ_MIN        = 80_000     # 最低流动性 $80K | Min liquidity $80K
TIER_A_HOLDERS_MIN    = 300        # 最低持有人数 | Min holders count
TIER_A_DEV_RUG        = 0          # Dev rug次数必须=0 | Dev rug count must be 0
TIER_A_BUNDLER_ATH    = 25.0       # Bundler ATH占比上限 25% | Bundler ATH max 25%
TIER_A_LP_BURN_MIN    = 80         # LP销毁最低 80% | LP burn min 80%
TIER_A_TOP10_MAX      = 50.0       # Top10持仓占比上限 50% | Top10 holdings max 50%
TIER_A_K1_PUMP_GUARD  = 15.0       # 1分钟涨幅>15%=追高, 跳过 | 1m pump >15% = chasing, skip

# ══════════════════════════════════════════════════════════════════════════════
# TIER B: Graduation Ambush / 毕业伏击
# 来源: onchainos memepump tokens --stage MIGRATED
# Source: onchainos memepump tokens --stage MIGRATED
# 注意: 必须用 MIGRATED (已毕业), 不能用 MIGRATING (迁移中swap会失败)
# Note: MUST use MIGRATED (graduated), NOT MIGRATING (swap fails on bonding curve)
# ══════════════════════════════════════════════════════════════════════════════

# -- Position Sizing / 仓位 --
TIER_B_SIZE_DAY    = 5     # 白天每笔 $5 | Day trade size $5
TIER_B_SIZE_NIGHT  = 3     # 夜间每笔 $3 | Night trade size $3

# -- Stage & Timing / 阶段与时机 --
TIER_B_STAGE       = "MIGRATED"  # 毕业阶段 (关键!) | Graduation stage (CRITICAL!)
TIER_B_MAX_AGE_MIN = 30          # 毕业后最大年龄 30分钟 | Max age after graduation 30min

# -- Filters / 过滤条件 --
TIER_B_MC_MIN      = 50_000      # 最低市值 $50K | Min market cap $50K
TIER_B_MC_MAX      = 500_000     # 最高市值 $500K | Max market cap $500K
TIER_B_HOLDERS_MIN = 100         # 最低持有人 | Min holders
TIER_B_DEV_SOLD    = True        # Dev必须已卖出 | Dev must have sold
TIER_B_INSIDERS_MAX = 15.0       # 内部人占比上限 15% | Insiders max 15%
TIER_B_TOP10_MAX   = 40.0        # Top10持仓上限 40% | Top10 holdings max 40%
TIER_B_APED_MIN    = 1           # 至少1个大户冲入 | At least 1 whale aped in

# ══════════════════════════════════════════════════════════════════════════════
# TIER D: Hot Momentum / 热门趋势动量
# 来源: onchainos hot-tokens --ranking-type 4
# Source: onchainos hot-tokens --ranking-type 4
# 动态仓位: 根据评分调整仓位大小
# Dynamic sizing: position sized by composite score
# ══════════════════════════════════════════════════════════════════════════════

# -- Position Sizing / 仓位 --
TIER_D_SIZE_BASE   = 5     # 基础仓位 $5 | Base position $5

# -- Dynamic Sizing / 动态加仓 --
# score 45-60: base | score 60-75: +1U | score 75+: +3U
TIER_D_SCORE_TIERS = [
    {"min_score": 75, "extra": 3},   # 高分 +$3 | High score +$3
    {"min_score": 60, "extra": 1},   # 中分 +$1 | Mid score +$1
    {"min_score": 45, "extra": 0},   # 基础 | Base
]

# -- Filters / 过滤条件 --
TIER_D_SCORE_THRESHOLD = 45          # 最低综合评分 | Min composite score
TIER_D_HOLDERS_MIN     = 500         # 最低持有人 | Min holders
TIER_D_MC_MIN          = 100_000     # 最低市值 $100K | Min market cap $100K
TIER_D_MC_MAX          = 10_000_000  # 最高市值 $10M | Max market cap $10M
TIER_D_LIQ_MIN         = 30_000      # 最低流动性 $30K | Min liquidity $30K
TIER_D_TOP10_MAX       = 35.0        # Top10持仓上限 35% | Top10 holdings max 35%
TIER_D_RISK_LEVEL      = 1           # 风险等级必须=1 (最低) | Risk level must be 1 (lowest)
TIER_D_MIN_INFLOW      = 0           # 净流入>0 (正向资金流) | Net inflow > 0 (positive flow)
TIER_D_MIN_CHANGE      = 5.0         # 价格变化>5% (有动量) | Price change > 5% (has momentum)
TIER_D_UNIQUE_TRADERS  = 100         # 独立交易者>=100 | Unique traders >= 100

# ── Take Profit / 止盈策略 ─────────────────────────────────────────────────
# 每层独立止盈规则 | Per-tier TP rules
# pct = 目标涨幅, sell = 卖出比例, trail = 触发TP1后的追踪止盈回撤比例
# pct = target gain, sell = sell ratio, trail = trailing drop after TP1

TP_RULES = {
    "A": {
        "tp1_pct": 0.15,       # +15% 卖出60% | +15% sell 60%
        "tp1_sell": 0.60,
        "tp2_pct": 0.30,       # +30% 卖出剩余50% | +30% sell 50% of remaining
        "tp2_sell": 0.50,
        "trailing_pct": 0.12,  # TP1后追踪12%回撤 | 12% trailing after TP1
    },
    "B": {
        "tp1_pct": 0.20,       # +20% 卖出60% | +20% sell 60%
        "tp1_sell": 0.60,
        "tp2_pct": 0.40,       # +40% 全部卖出 | +40% sell all
        "tp2_sell": 1.00,
        "trailing_pct": 0.10,  # TP1后追踪10%回撤 | 10% trailing after TP1
    },
    "D": {
        "tp1_pct": 0.15,       # +15% 卖出60% | +15% sell 60%
        "tp1_sell": 0.60,
        "tp2_pct": 0.30,       # +30% 卖出剩余50% | +30% sell 50% of remaining
        "tp2_sell": 0.50,
        "trailing_pct": 0.08,  # TP1后追踪8%回撤 | 8% trailing after TP1
    },
}

# ── Stop Loss / 止损策略 ──────────────────────────────────────────────────
# 每层独立止损规则 | Per-tier SL rules

SL_RULES = {
    "A": {
        "sl_pct": -0.15,                        # 硬止损 -15% | Hard SL -15%
        "time_decay": [(30, -0.08), (60, -0.05)],  # (分钟, 收紧到) | (min, tighten to)
        "timeout_hrs": 48,                      # 最大持仓时间 48h | Max hold 48h
    },
    "B": {
        "sl_pct": -0.15,                        # 硬止损 -15% | Hard SL -15%
        "time_decay": [],                       # 无时间衰减 | No time decay
        "timeout_hrs": 2,                       # 最大持仓时间 2h | Max hold 2h
    },
    "D": {
        "sl_pct": -0.10,                        # 硬止损 -10% | Hard SL -10%
        "time_decay": [],                       # 无时间衰减 | No time decay
        "timeout_hrs": 6,                       # 最大持仓时间 6h | Max hold 6h
    },
}

# ── Emergency Exit / 紧急退出 ─────────────────────────────────────────────
# 所有层通用 | Universal for all tiers
HE1_PCT            = -0.50     # 暴跌 -50% 紧急退出 | -50% crash emergency exit
FAST_DUMP_PCT      = -0.15     # 从峰值跌 -15% 闪崩退出 | -15% from peak flash dump exit
FAST_DUMP_SEC      = 10        # 旧参数 (兼容) | Legacy param (compat)
FAST_DUMP_WINDOW   = 60        # 闪崩检测窗口: 峰值在60秒内且跌>=15%触发 | If peak was within 60s and dropped 15%+, trigger
LIQ_EMERGENCY      = 5_000     # 流动性<$5K紧急退出 | Liquidity < $5K emergency exit

# ── Session Risk Control / 会话风控 ───────────────────────────────────────
MAX_CONSEC_LOSS    = 3         # 连续亏损N次暂停 | N consecutive losses -> pause
PAUSE_CONSEC_SEC   = 600       # 暂停600秒(10分钟) | Pause 600s (10min)
DAILY_LOSS_LIMIT   = 15        # 日亏损上限 $15 停止交易 | Daily loss limit $15 -> stop
MAX_POSITIONS      = 6         # 最大同时持仓数 | Max concurrent positions
STARTUP_COOLDOWN   = 180       # 启动冷却180秒 (扫描但不交易) | Startup cooldown 180s (scan but no trade)

# ── Scan Intervals / 扫描间隔 ─────────────────────────────────────────────
SM_REFRESH_SEC        = 30     # Smart Money信号刷新 30s | SM signal refresh 30s
GRADUATED_REFRESH_SEC = 60     # 毕业代币刷新 60s | Graduated tokens refresh 60s
HOT_REFRESH_SEC       = 60     # 热门代币刷新 60s | Hot tokens refresh 60s
MONITOR_SEC           = 1      # 持仓监控间隔 1s | Position monitor interval 1s
BALANCE_CHECK_SEC     = 60     # 余额检查间隔 60s | Balance check interval 60s

# ── Safety Thresholds / 安全阈值 ──────────────────────────────────────────
SLIPPAGE_BUY       = 10        # 买入滑点 10% | Buy slippage 10%
SLIPPAGE_SELL      = 50        # 卖出滑点 50% (小市值代币流动性差) | Sell slippage 50% (low liq)
SOL_GAS_RESERVE    = 0.05      # SOL Gas预留 | SOL reserved for gas fees
MIN_POSITION_VALUE = 0.10      # 最小持仓价值 $0.10 (粉尘清理) | Min position value $0.10 (dust)

# ── Dashboard / 仪表盘 ────────────────────────────────────────────────────
DASHBOARD_PORT     = 3250      # 本地仪表盘端口 | Local dashboard port
DASHBOARD_ENABLED  = True      # 启用仪表盘 | Dashboard enabled

# ── Trade Blacklist / 交易黑名单 ──────────────────────────────────────────
# 永不交易的代币地址 | Addresses that must never be traded
_WSOL_MINT = "So11111111111111111111111111111111111111112"
_NEVER_TRADE_MINTS = {
    "11111111111111111111111111111111",                # native SOL
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",  # USDT
    "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So",   # mSOL
    "7dHbWXmci3dT8UFYWYZweBLXgycu7Y3iL6trKn1Y7ARj",  # stSOL
    "bSo13r4TkiE4KumL71LsHTPpL2euBYLFx6h9HP3piy1",   # bSOL
    "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn",  # JitoSOL
    _WSOL_MINT,                                        # WSOL
}

# ── Legacy Compat / 兼容旧版 ──────────────────────────────────────────────
# hunter.py 中可能直接引用的常量 | Constants that hunter.py may reference directly
SOL_PER_TRADE = TIER_D_SIZE_BASE   # 默认引用 Tier D 基础仓位 | Default to Tier D base size
