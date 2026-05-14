"""
SOL Meme Hunter v7.0 -- Strategy Configuration
Architecture: 4-Tier (S/A/B/D) + Smart Wallet Signal + Adaptive Exit System
Swap flow: swap swap -> contract-call -> wallet history

V7 Core Philosophy:
  - 让赢家跑，快速切断输家 (Let winners run, cut losers fast)
  - 出本保本，利润奔跑 (Cover cost first, let profit ride)
  - Smart Wallet 信号加权 (Smart Wallet signal weighting)
  - 止盈止损强制执行，无强制关机 (TP/SL strictly enforced, no forced shutdown)
  - 可以安全跑一整晚 (Safe to run overnight)

Disclaimer:
This script is for educational/research purposes only. Not investment advice.
Crypto trading carries extreme risk. Use at your own risk.
"""

# ── Operating Mode / 运行模式 ──────────────────────────────────────────────
PAUSED         = False    # True=暂停(不开新仓) | True=Paused (no new positions)
PAPER_TRADE    = False    # True=模拟盘 | True=Paper trading

# ── Wallet & Chain / 钱包与链 ──────────────────────────────────────────────
CHAIN_ID       = 501
SOL_NATIVE     = "11111111111111111111111111111111"
USDC_ADDR      = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
WALLET         = "AXBCfbioEHiJ48ejNp5feEzWt2iHFLUDNMk27t5vXWLE"

# ── File Paths / 文件路径 ──────────────────────────────────────────────────
LOG_FILE       = "/tmp/meme_hunter_v7.log"
ACTED_FILE     = "/tmp/meme_hunter_v7_acted.json"
SESSION_FILE   = "/tmp/meme_hunter_v7_session.json"
POSITIONS_FILE = "/tmp/meme_hunter_v7_positions.json"
TRADES_FILE    = "/tmp/meme_hunter_v7_trades.json"

# ── Night Mode / 夜间模式 ─────────────────────────────────────────────────
# UTC 14:00-22:00 = 北京时间 22:00-06:00
NIGHT_START_UTC = 14
NIGHT_END_UTC   = 22

# ══════════════════════════════════════════════════════════════════════════════
# SMART WALLET DATABASE / 聪明钱数据库
# 从 smart_wallets CSV 提取的地址分3层, 作为入场加分因子
# ══════════════════════════════════════════════════════════════════════════════

SMART_WALLET_CSV = "smart_wallets_page_all_all_202605141414.csv"

# 分组 -> 质量层级
SMART_WALLET_GROUP_TIER = {
    # Tier 1: 最高质量 (历史表现优秀)
    "盈利Top": 1,
    "暴富新人": 1,
    "底部高倍数": 1,
    "频繁高胜": 1,
    "离场赢家": 1,
    # Tier 2: 中等质量
    "中等盈利": 2,
    "持仓Top": 2,
    "沉睡OG": 2,
    "微赚": 2,
    # Tier 3: 参考价值
    "中性": 3,
    "早期建仓": 3,  # 视角分组中的早期建仓
    # 负面 (不加分, 可能减分)
    "亏损者": -1,
    "稳输者": -1,
    "赌徒命中": 3,
    "稳健均衡": 2,
    "低频重炮": 1,
}

# 各层级的评分加成
SMART_WALLET_SCORE_BOOST = {
    1: 30,   # Tier 1: +30 分
    2: 20,   # Tier 2: +20 分
    3: 10,   # Tier 3: +10 分
    -1: -10, # 负面: -10 分
}

# 角色加权乘数
SMART_WALLET_ROLE_WEIGHT = {
    "early-buyer": 1.5,      # 早期买入 - 信号最强
    "pnl-leader": 1.3,       # PnL领先
    "current-holder": 1.0,   # 当前持有
    "peak-seller": 0.5,      # 高点卖出
}

# Smart Wallet 加分上限 (防止过度加权)
SMART_WALLET_MAX_BOOST = 50

# 最低 Smart Wallet 匹配数量才算有效信号
SMART_WALLET_MIN_MATCH = 1

# ══════════════════════════════════════════════════════════════════════════════
# TIER S: Smart Wallet Follow / 聪明钱跟单 (新增！)
# 定期扫描高质量钱包的最近交易, 发现新买入直接作为候选
# ══════════════════════════════════════════════════════════════════════════════

TIER_S_ENABLED     = True
TIER_S_SIZE_DAY    = 8     # 白天每笔 $8 (最强信号, 值得加大)
TIER_S_SIZE_NIGHT  = 5     # 夜间每笔 $5
TIER_S_REFRESH_SEC = 45    # 扫描间隔 45s

# 只跟 Tier1 钱包的最新买入
TIER_S_FOLLOW_TIERS = [1]

# 过滤
TIER_S_MC_MIN       = 100_000     # 最低市值 $100K
TIER_S_MC_MAX       = 5_000_000   # 最高市值 $5M
TIER_S_LIQ_MIN      = 30_000      # 最低流动性 $30K
TIER_S_HOLDERS_MIN  = 100         # 最低持有人
TIER_S_TOP10_MAX    = 45.0        # Top10持仓上限 45%
TIER_S_MAX_AGE_MIN  = 30          # 钱包买入后最大年龄 30min (只要新鲜的)

# ══════════════════════════════════════════════════════════════════════════════
# TIER A: Smart Money Signal / 聪明钱信号跟单 (onchainos signal)
# ══════════════════════════════════════════════════════════════════════════════

TIER_A_SIZE_DAY    = 8     # 白天每笔 $8 (V7加大, 信号质量最高)
TIER_A_SIZE_NIGHT  = 5     # 夜间每笔 $5

# Signal Filters
SM_MIN_WALLETS     = 2     # 最低跟单钱包数
SM_STRONG_THRESH   = 3     # >=3钱包=强信号
SM_LABELS          = [1, 2, 3]  # 1=SmartMoney 2=KOL 3=Whale

# Deep Verification (V7: 提高门槛)
TIER_A_MC_MIN         = 150_000    # V7: $100K -> $150K
TIER_A_MC_MAX         = 3_000_000  # V7: $2M -> $3M (允许稍大的币)
TIER_A_LIQ_MIN        = 40_000     # V7: $25K -> $40K (确保能卖出)
TIER_A_HOLDERS_MIN    = 200        # V7: 150 -> 200
TIER_A_DEV_RUG        = 0
TIER_A_BUNDLER_ATH    = 25.0
TIER_A_LP_BURN_MIN    = 80
TIER_A_TOP10_MAX      = 45.0       # V7: 50% -> 45%
TIER_A_K1_PUMP_GUARD  = 12.0       # V7: 15% -> 12% (更严格追高防护)

# ══════════════════════════════════════════════════════════════════════════════
# TIER B: Graduation Ambush / 毕业伏击
# ══════════════════════════════════════════════════════════════════════════════

TIER_B_SIZE_DAY    = 5
TIER_B_SIZE_NIGHT  = 3

TIER_B_STAGE       = "MIGRATED"
TIER_B_MAX_AGE_MIN = 60            # V7: 120min -> 60min (只要最新鲜的)

TIER_B_MC_MIN      = 50_000
TIER_B_MC_MAX      = 500_000
TIER_B_HOLDERS_MIN = 100
TIER_B_DEV_SOLD    = True
TIER_B_INSIDERS_MAX = 15.0
TIER_B_TOP10_MAX   = 40.0
TIER_B_APED_MIN    = 0

# V7新增: Tier B 快速止盈 (10min内涨30%直接TP1)
TIER_B_FAST_TP_MIN = 10            # 分钟
TIER_B_FAST_TP_PCT = 0.30          # +30%

# ══════════════════════════════════════════════════════════════════════════════
# TIER D: Hot Momentum / 热门趋势动量
# ══════════════════════════════════════════════════════════════════════════════

TIER_D_SIZE_BASE   = 5

# Dynamic Sizing (V7: 提高门槛)
TIER_D_SCORE_TIERS = [
    {"min_score": 80, "extra": 3},   # V7: 75 -> 80
    {"min_score": 65, "extra": 1},   # V7: 60 -> 65
    {"min_score": 55, "extra": 0},   # V7: 45 -> 55
]

# Filters (V7: 提高质量)
TIER_D_SCORE_THRESHOLD = 55         # V7: 45 -> 55
TIER_D_HOLDERS_MIN     = 500
TIER_D_MC_MIN          = 150_000    # V7: $100K -> $150K
TIER_D_MC_MAX          = 10_000_000
TIER_D_LIQ_MIN         = 40_000    # V7: $30K -> $40K
TIER_D_TOP10_MAX       = 35.0
TIER_D_RISK_LEVEL      = 1
TIER_D_MIN_INFLOW      = 0
TIER_D_MIN_CHANGE      = 0.0
TIER_D_UNIQUE_TRADERS  = 0

# ══════════════════════════════════════════════════════════════════════════════
# V7 VOLUME CONFIRMATION / 成交量确认 (新增!)
# 买入前检查5分钟K线成交量, 确认有真实买盘
# ══════════════════════════════════════════════════════════════════════════════

VOLUME_CONFIRM_ENABLED = True
VOLUME_5M_MIN_USD      = 8_000     # 5min最低成交量 $8K
VOLUME_BUY_SELL_RATIO  = 1.2       # 买/卖比 >= 1.2
VOLUME_TREND_CHECK     = True      # 检查成交量趋势 (递增=好)

# ══════════════════════════════════════════════════════════════════════════════
# TAKE PROFIT / 止盈策略 (V7 重大改版!)
#
# V7核心改变:
#   - TP1 = +100% 卖50% (翻倍出本, 比V6的+50%/67%更合理)
#   - TP2 = +300% 卖30% (让利润跑)
#   - TP3 = +800% 卖30% (新增! 大涨机会)
#   - Trailing放宽到20% (V6=12-15%, meme波动大需要空间)
#   - 底仓有条件保留 (盈利保留, 亏损清掉)
# ══════════════════════════════════════════════════════════════════════════════

TP_RULES = {
    "S": {
        "tp1_pct": 1.00,       # +100% 卖50% (翻倍出本) | Double → sell 50% (cover cost)
        "tp1_sell": 0.50,
        "tp2_pct": 3.00,       # +300% 卖30% | 4x → sell 30%
        "tp2_sell": 0.30,
        "tp3_pct": 8.00,       # +800% 卖30% | 9x → sell 30%
        "tp3_sell": 0.30,
        "trailing_pct": 0.25,  # TP1后25%回撤卖40% | 25% trailing after TP1
        "trailing_sell": 0.40,
        "floor_pct": 0.10,     # 底仓10%
    },
    "A": {
        "tp1_pct": 1.00,       # +100% 卖50% (翻倍出本)
        "tp1_sell": 0.50,
        "tp2_pct": 3.00,       # +300% 卖30%
        "tp2_sell": 0.30,
        "tp3_pct": 8.00,       # +800% 卖30%
        "tp3_sell": 0.30,
        "trailing_pct": 0.20,  # V7: 15% -> 20%
        "trailing_sell": 0.40,
        "floor_pct": 0.10,
    },
    "B": {
        "tp1_pct": 1.00,       # +100% 卖50% (翻倍出本)
        "tp1_sell": 0.50,
        "tp2_pct": 2.50,       # +250% 卖30% (B稍保守)
        "tp2_sell": 0.30,
        "tp3_pct": 6.00,       # +600% 卖30%
        "tp3_sell": 0.30,
        "trailing_pct": 0.18,  # V7: 12% -> 18%
        "trailing_sell": 0.40,
        "floor_pct": 0.10,
    },
    "D": {
        "tp1_pct": 1.00,       # +100% 卖50% (翻倍出本)
        "tp1_sell": 0.50,
        "tp2_pct": 3.00,       # +300% 卖30%
        "tp2_sell": 0.30,
        "tp3_pct": 8.00,       # +800% 卖30%
        "tp3_sell": 0.30,
        "trailing_pct": 0.20,  # V7: 12% -> 20%
        "trailing_sell": 0.40,
        "floor_pct": 0.10,
    },
    "takeover": {
        "tp1_pct": 0.50,       # 接管仓位: +50% 卖50%
        "tp1_sell": 0.50,
        "tp2_pct": 1.50,       # +150% 卖30%
        "tp2_sell": 0.30,
        "tp3_pct": 5.00,       # +500% 卖30%
        "tp3_sell": 0.30,
        "trailing_pct": 0.15,
        "trailing_sell": 0.40,
        "floor_pct": 0.10,
    },
}

# ══════════════════════════════════════════════════════════════════════════════
# STOP LOSS / 止损策略 (V7 改版!)
#
# V7核心改变:
#   - 硬止损放宽: -12% -> -20% (meme波动大是正常的)
#   - SL1卖出比例降低: 60% -> 50% (给反弹机会)
#   - SL2放宽: -20% -> -30%
#   - 时间衰减更合理
#   - 新增: 底仓止损 (亏损底仓不再死拿)
# ══════════════════════════════════════════════════════════════════════════════

SL_RULES = {
    "S": {
        "sl_pct": -0.20,                          # -20% 卖50%
        "sl_sell": 0.50,
        "sl2_pct": -0.30,                         # -30% 卖全部
        "sl2_sell": 1.0,
        "time_decay": [(30, -0.15), (60, -0.10)], # 30min后-15%, 60min后-10%
        "timeout_hrs": 48,                        # 最大持仓48h
    },
    "A": {
        "sl_pct": -0.20,                          # V7: -12% -> -20%
        "sl_sell": 0.50,                          # V7: 60% -> 50%
        "sl2_pct": -0.30,                         # V7: -20% -> -30%
        "sl2_sell": 1.0,
        "time_decay": [(30, -0.15), (60, -0.10)], # 30min后收紧到-15%, 60min后-10%
        "timeout_hrs": 48,                        # V7: 24h -> 48h (给更多时间)
    },
    "B": {
        "sl_pct": -0.20,                          # V7: -12% -> -20%
        "sl_sell": 0.50,
        "sl2_pct": -0.30,
        "sl2_sell": 1.0,
        "time_decay": [(20, -0.15)],              # 20min后收紧到-15%
        "timeout_hrs": 6,                         # V7: 2h -> 6h (给毕业币更多时间)
    },
    "D": {
        "sl_pct": -0.20,                          # V7: -10% -> -20%
        "sl_sell": 0.50,
        "sl2_pct": -0.30,                         # V7: -18% -> -30%
        "sl2_sell": 1.0,
        "time_decay": [(15, -0.15), (30, -0.10)], # V7新增时间衰减
        "timeout_hrs": 12,                        # V7: 6h -> 12h
    },
    "takeover": {
        "sl_pct": -0.20,
        "sl_sell": 0.50,
        "sl2_pct": -0.30,
        "sl2_sell": 1.0,
        "time_decay": [],
        "timeout_hrs": 48,
    },
}

# ── Floor Position Exit / 底仓退出策略 (V7新增!) ──────────────────────────
# 底仓不再死拿! 亏损的底仓会被清理
FLOOR_EXIT_ENABLED     = True
FLOOR_EXIT_LOSS_PCT    = -0.30    # 底仓亏损超-30%时全清
FLOOR_EXIT_AGE_HRS     = 4.0     # 底仓age>4h且亏损时全清
FLOOR_EXIT_AGE_LOSS    = 0.0     # 配合age检查: PnL < 0% 时清理

# ── Emergency Exit / 紧急退出 (强制执行, 不受底仓保护!) ────────────────────
HE1_PCT            = -0.50        # 暴跌 -50% 无条件全卖
FAST_DUMP_PCT      = -0.20        # V7: -15% -> -20% (从峰值)
FAST_DUMP_WINDOW   = 60           # 闪崩窗口 60s
LIQ_EMERGENCY      = 5_000        # 流动性 < $5K 全卖

# ── Session Risk Control / 会话风控 ───────────────────────────────────────
# V7: 去掉强制关机! 只暂停, 不停止. 可以安全跑一整晚.
MAX_CONSEC_LOSS    = 4            # V7: 3 -> 4 (稍微放宽)
PAUSE_CONSEC_SEC   = 900          # V7: 600s -> 900s (15min, 冷静更久)
DAILY_LOSS_LIMIT   = 20           # V7: $15 -> $20 (因为单笔更大)
DAILY_LOSS_ACTION  = "pause"      # V7: "stop" -> "pause" (暂停30min而不是停机)
DAILY_LOSS_PAUSE   = 1800         # 触发日亏损限制后暂停30min
MAX_POSITIONS      = 8            # 最大同时持仓数 (8个 = 更多机会)
STARTUP_COOLDOWN   = 120          # V7: 180s -> 120s

# ── Scan Intervals / 扫描间隔 ─────────────────────────────────────────────
SM_REFRESH_SEC        = 30
GRADUATED_REFRESH_SEC = 60
HOT_REFRESH_SEC       = 60
MONITOR_SEC           = 1
BALANCE_CHECK_SEC     = 60

# ── Safety Thresholds / 安全阈值 ──────────────────────────────────────────
SLIPPAGE_BUY       = 10
SLIPPAGE_SELL      = 50
SOL_GAS_RESERVE    = 0.05
MIN_POSITION_VALUE = 0.10

# ── Dashboard / 仪表盘 ────────────────────────────────────────────────────
DASHBOARD_PORT     = 3250
DASHBOARD_ENABLED  = True

# ── Trade Blacklist / 交易黑名单 ──────────────────────────────────────────
_WSOL_MINT = "So11111111111111111111111111111111111111112"
_NEVER_TRADE_MINTS = {
    "11111111111111111111111111111111",
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
    "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So",
    "7dHbWXmci3dT8UFYWYZweBLXgycu7Y3iL6trKn1Y7ARj",
    "bSo13r4TkiE4KumL71LsHTPpL2euBYLFx6h9HP3piy1",
    "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn",
    _WSOL_MINT,
}

# ── Legacy Compat ─────────────────────────────────────────────────────────
SOL_PER_TRADE = TIER_D_SIZE_BASE
