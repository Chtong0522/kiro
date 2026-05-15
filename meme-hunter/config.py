"""
SOL Meme Hunter v8.0 — User-Configurable Strategy Parameters
═══════════════════════════════════════════════════════════════

HOW TO USE:
  1. Choose a PRESET below: "conservative", "balanced", or "aggressive"
  2. Optionally override individual parameters after the preset section
  3. Restart the bot for changes to take effect

PRESETS:
  conservative — Smaller positions, tighter filters, lower risk. Best for beginners.
  balanced     — Default. Good risk/reward for experienced traders.
  aggressive   — Larger positions, wider filters, higher risk/reward potential.

All parameters are documented inline. Change only what you understand.

Disclaimer: Educational/research only. Not investment advice. Use at own risk.
"""

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1: RISK PRESET SELECTION
# Change this single value to adjust the entire strategy profile.
# After selecting a preset, you can still override individual values below.
# ══════════════════════════════════════════════════════════════════════════════

PRESET = "balanced"  # Options: "conservative", "balanced", "aggressive"

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2: PRESET DEFINITIONS
# These define the default values for each preset.
# DO NOT modify this section unless you understand the full system.
# ══════════════════════════════════════════════════════════════════════════════

_PRESETS = {
    "conservative": {
        # Position sizing
        "TIER_S_SIZE_DAY": 5, "TIER_S_SIZE_NIGHT": 3,
        "TIER_A_SIZE_DAY": 5, "TIER_A_SIZE_NIGHT": 3,
        "TIER_B_SIZE_DAY": 3, "TIER_B_SIZE_NIGHT": 2,
        "TIER_D_SIZE_BASE": 3,
        # Risk control
        "MAX_POSITIONS": 4,
        "DAILY_LOSS_LIMIT": 10,
        "MAX_CONSEC_LOSS": 15,
        "PAUSE_CONSEC_SEC": 1200,  # 20min
        "DAILY_LOSS_PAUSE": 2400,  # 40min
        # Filters (strictest: only highest quality entries)
        "TIER_A_MC_MIN": 300_000, "TIER_A_MC_MAX": 2_000_000,
        "TIER_A_LIQ_MIN": 60_000, "TIER_A_HOLDERS_MIN": 500,
        "TIER_B_MC_MIN": 150_000, "TIER_B_MC_MAX": 400_000,
        "TIER_B_HOLDERS_MIN": 300,
        "TIER_D_MC_MIN": 300_000, "TIER_D_MC_MAX": 5_000_000,
        "TIER_D_LIQ_MIN": 60_000, "TIER_D_SCORE_THRESHOLD": 70,
        "TIER_D_HOLDERS_MIN": 800,
        "TIER_S_MC_MIN": 200_000, "TIER_S_MC_MAX": 3_000_000,
        "TIER_S_LIQ_MIN": 50_000, "TIER_S_HOLDERS_MIN": 250,
        # Volume (strictest)
        "VOLUME_5M_MIN_USD": 15_000,
        "VOLUME_BUY_SELL_RATIO": 1.5,
        # Take profit (higher TP1 = need bigger move to cover cost)
        "TP1_PCT": 0.50, "TP1_SELL": 0.70,
        "TP2_PCT": 2.50, "TP2_SELL": 0.30,
        "TP3_PCT": 6.00, "TP3_SELL": 0.30,
        # Stop loss (tighter = cut losses faster)
        "SL1_PCT": -0.15, "SL1_SELL": 0.50,
        "SL2_PCT": -0.25, "SL2_SELL": 1.0,
    },
    "balanced": {
        # Position sizing
        "TIER_S_SIZE_DAY": 8, "TIER_S_SIZE_NIGHT": 5,
        "TIER_A_SIZE_DAY": 8, "TIER_A_SIZE_NIGHT": 5,
        "TIER_B_SIZE_DAY": 5, "TIER_B_SIZE_NIGHT": 3,
        "TIER_D_SIZE_BASE": 5,
        # Risk control
        "MAX_POSITIONS": 6,
        "DAILY_LOSS_LIMIT": 20,
        "MAX_CONSEC_LOSS": 15,
        "PAUSE_CONSEC_SEC": 900,  # 15min
        "DAILY_LOSS_PAUSE": 1800,  # 30min
        # Filters (v8: tightened from v7 for higher quality entries)
        "TIER_A_MC_MIN": 200_000, "TIER_A_MC_MAX": 3_000_000,
        "TIER_A_LIQ_MIN": 50_000, "TIER_A_HOLDERS_MIN": 300,
        "TIER_B_MC_MIN": 100_000, "TIER_B_MC_MAX": 500_000,
        "TIER_B_HOLDERS_MIN": 300,
        "TIER_D_MC_MIN": 200_000, "TIER_D_MC_MAX": 8_000_000,
        "TIER_D_LIQ_MIN": 50_000, "TIER_D_SCORE_THRESHOLD": 60,
        "TIER_D_HOLDERS_MIN": 300,
        "TIER_S_MC_MIN": 150_000, "TIER_S_MC_MAX": 5_000_000,
        "TIER_S_LIQ_MIN": 40_000, "TIER_S_HOLDERS_MIN": 250,
        # Volume (stricter: must have real activity)
        "VOLUME_5M_MIN_USD": 10_000,
        "VOLUME_BUY_SELL_RATIO": 1.3,
        # Take profit (TP1=+35% 出本金，剩余免费奔跑)
        "TP1_PCT": 0.35, "TP1_SELL": 0.75,
        "TP2_PCT": 2.00, "TP2_SELL": 0.30,
        "TP3_PCT": 5.00, "TP3_SELL": 0.30,
        # Stop loss
        "SL1_PCT": -0.20, "SL1_SELL": 0.50,
        "SL2_PCT": -0.30, "SL2_SELL": 1.0,
    },
    "aggressive": {
        # Position sizing
        "TIER_S_SIZE_DAY": 12, "TIER_S_SIZE_NIGHT": 8,
        "TIER_A_SIZE_DAY": 12, "TIER_A_SIZE_NIGHT": 8,
        "TIER_B_SIZE_DAY": 8, "TIER_B_SIZE_NIGHT": 5,
        "TIER_D_SIZE_BASE": 8,
        # Risk control
        "MAX_POSITIONS": 10,
        "DAILY_LOSS_LIMIT": 40,
        "MAX_CONSEC_LOSS": 15,
        "PAUSE_CONSEC_SEC": 600,  # 10min
        "DAILY_LOSS_PAUSE": 1200,  # 20min
        # Filters (still stricter than v7 aggressive)
        "TIER_A_MC_MIN": 150_000, "TIER_A_MC_MAX": 5_000_000,
        "TIER_A_LIQ_MIN": 40_000, "TIER_A_HOLDERS_MIN": 300,
        "TIER_B_MC_MIN": 80_000, "TIER_B_MC_MAX": 800_000,
        "TIER_B_HOLDERS_MIN": 300,
        "TIER_D_MC_MIN": 150_000, "TIER_D_MC_MAX": 12_000_000,
        "TIER_D_LIQ_MIN": 40_000, "TIER_D_SCORE_THRESHOLD": 50,
        "TIER_S_MC_MIN": 100_000, "TIER_S_MC_MAX": 8_000_000,
        "TIER_S_LIQ_MIN": 30_000,
        # Volume (still requires activity)
        "VOLUME_5M_MIN_USD": 8_000,
        "VOLUME_BUY_SELL_RATIO": 1.1,
        # Take profit (earlier TP1 to secure gains faster in volatile markets)
        "TP1_PCT": 0.30, "TP1_SELL": 0.75,
        "TP2_PCT": 1.50, "TP2_SELL": 0.30,
        "TP3_PCT": 4.00, "TP3_SELL": 0.30,
        # Stop loss (wider but still disciplined)
        "SL1_PCT": -0.25, "SL1_SELL": 0.50,
        "SL2_PCT": -0.35, "SL2_SELL": 1.0,
    },
}

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3: APPLY PRESET (auto-populated from selection above)
# ══════════════════════════════════════════════════════════════════════════════

def _apply_preset(preset_name):
    """Apply preset values to module globals. Called at import time."""
    import sys
    module = sys.modules[__name__]
    preset = _PRESETS.get(preset_name, _PRESETS["balanced"])
    for key, value in preset.items():
        setattr(module, key, value)

_apply_preset(PRESET)



# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4: OPERATING MODE
# These control bot behavior regardless of preset.
# ══════════════════════════════════════════════════════════════════════════════

PAUSED         = False    # True = no new positions opened (existing positions still managed)
PAPER_TRADE    = False    # True = simulate trades without real execution

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5: WALLET & CHAIN
# ══════════════════════════════════════════════════════════════════════════════

CHAIN_ID       = 501
SOL_NATIVE     = "11111111111111111111111111111111"
USDC_ADDR      = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
WALLET         = ""  # Auto-detected from onchainos. Set manually only if needed.

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 6: FILE PATHS
# ══════════════════════════════════════════════════════════════════════════════

LOG_FILE       = "/tmp/meme_hunter_v8.log"
ACTED_FILE     = "/tmp/meme_hunter_v8_acted.json"
SESSION_FILE   = "/tmp/meme_hunter_v8_session.json"
POSITIONS_FILE = "/tmp/meme_hunter_v8_positions.json"
TRADES_FILE    = "/tmp/meme_hunter_v8_trades.json"

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 7: NIGHT MODE
# Reduced position sizes during low-liquidity hours.
# UTC 14:00-22:00 = Beijing 22:00-06:00
# ══════════════════════════════════════════════════════════════════════════════

NIGHT_START_UTC = 14
NIGHT_END_UTC   = 22

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 8: SMART WALLET DATABASE
# 816 curated addresses loaded from CSV at startup.
# Used for Tier S (direct follow) and all-tier scoring boost.
# ══════════════════════════════════════════════════════════════════════════════

SMART_WALLET_CSV = "smart_wallets_page_all_all_202605141414.csv"

# Group -> Quality Tier mapping
SMART_WALLET_GROUP_TIER = {
    # Tier 1: Highest quality (proven top performers)
    "盈利Top": 1, "暴富新人": 1, "底部高倍数": 1,
    "频繁高胜": 1, "离场赢家": 1, "低频重炮": 1,
    # Tier 2: Medium quality
    "中等盈利": 2, "持仓Top": 2, "沉睡OG": 2,
    "微赚": 2, "稳健均衡": 2,
    # Tier 3: Reference value
    "中性": 3, "早期建仓": 3, "赌徒命中": 3,
    # Negative: Deduct points
    "亏损者": -1, "稳输者": -1,
}

# Score boost per tier
SMART_WALLET_SCORE_BOOST = {1: 30, 2: 20, 3: 10, -1: -10}

# Role-based multiplier (applied on top of tier boost)
SMART_WALLET_ROLE_WEIGHT = {
    "early-buyer": 1.5,      # Strongest leading signal
    "pnl-leader": 1.3,       # Highest PnL on the token
    "current-holder": 1.0,   # Still holding
    "peak-seller": 0.5,      # Sold near peak (weakened)
}

# Cap on total smart wallet boost per token
SMART_WALLET_MAX_BOOST = 50

# Minimum matched wallets for signal validity
SMART_WALLET_MIN_MATCH = 1

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 9: TIER S — SMART WALLET FOLLOW
# Scans Tier-1 wallets for fresh buys. Highest confidence signal.
# ══════════════════════════════════════════════════════════════════════════════

TIER_S_ENABLED      = True
TIER_S_REFRESH_SEC  = 45       # Scan interval
TIER_S_FOLLOW_TIERS = [1]      # Only follow Tier-1 wallets
TIER_S_SAMPLE_SIZE  = 10       # Wallets sampled per cycle
TIER_S_MAX_AGE_MIN  = 30       # Max age of wallet's buy (minutes)
TIER_S_HOLDERS_MIN  = 250
TIER_S_TOP10_MAX    = 40.0
TIER_S_DEDUP_SEC    = 7200     # Skip same wallet+token for 2 hours

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 10: TIER A — SMART MONEY SIGNAL
# Multi-wallet co-buy detection via onchainos signal.
# ══════════════════════════════════════════════════════════════════════════════

SM_MIN_WALLETS      = 2        # Minimum co-buying wallets
SM_STRONG_THRESH    = 3        # >=3 = strong signal (bypass hot-tokens check)
SM_LABELS           = [1, 2, 3]  # 1=SmartMoney, 2=KOL, 3=Whale
SM_REFRESH_SEC      = 30       # Scan interval

TIER_A_DEV_RUG      = 0
TIER_A_BUNDLER_ATH  = 25.0
TIER_A_LP_BURN_MIN  = 80
TIER_A_TOP10_MAX    = 40.0
TIER_A_K1_PUMP_GUARD = 10.0   # Skip if 1m candle pumped >10% (stricter)

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 11: TIER B — GRADUATION AMBUSH
# Catch tokens within 60min of PumpFun → Raydium migration.
# ══════════════════════════════════════════════════════════════════════════════

TIER_B_STAGE        = "MIGRATED"
TIER_B_MAX_AGE_MIN  = 60       # Only tokens graduated within 60min
TIER_B_DEV_SOLD     = True     # Require dev to have sold
TIER_B_INSIDERS_MAX = 12.0
TIER_B_TOP10_MAX    = 35.0
TIER_B_APED_MIN     = 0

# Fast TP: if +30% within 10min, fire TP1 immediately
TIER_B_FAST_TP_MIN  = 10
TIER_B_FAST_TP_PCT  = 0.30

GRADUATED_REFRESH_SEC = 60     # Scan interval

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 12: TIER D — HOT MOMENTUM
# Composite-scored trending tokens with dynamic sizing.
# ══════════════════════════════════════════════════════════════════════════════

TIER_D_SCORE_TIERS = [
    {"min_score": 80, "extra": 3},   # Score 80+ → base + $3
    {"min_score": 65, "extra": 1},   # Score 65-79 → base + $1
    {"min_score": 55, "extra": 0},   # Score 55-64 → base only
]

TIER_D_HOLDERS_MIN   = 800
TIER_D_TOP10_MAX     = 30.0
TIER_D_RISK_LEVEL    = 1
TIER_D_MIN_INFLOW    = 0
TIER_D_MIN_CHANGE    = 0.0
TIER_D_UNIQUE_TRADERS = 100    # 至少100个独立交易者，防止少数人制造假活跃

HOT_REFRESH_SEC      = 60     # Scan interval

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 13: VOLUME CONFIRMATION
# Pre-entry check: 5min volume + buy/sell ratio + trend.
# ══════════════════════════════════════════════════════════════════════════════

VOLUME_CONFIRM_ENABLED = True
VOLUME_TREND_CHECK     = True   # Check if volume is declining

# Holder sell pressure detection (pre-trade)
HOLDER_SELL_CHECK_ENABLED = True
HOLDER_SELL_MAX_SOL_5M    = 1.5  # Max SOL sold by dev+sniper in 5min (stricter)

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 14: TAKE PROFIT RULES
# Per-tier TP configuration. Override preset values here if needed.
# Core: TP1 = cover cost, TP2/TP3 = let profit ride.
# ══════════════════════════════════════════════════════════════════════════════

TP_RULES = {
    "S": {
        "tp1_pct": TP1_PCT, "tp1_sell": TP1_SELL,
        "tp2_pct": TP2_PCT, "tp2_sell": TP2_SELL,
        "tp3_pct": TP3_PCT, "tp3_sell": TP3_SELL,
        "trailing_pct": 0.25, "trailing_sell": 0.40,
        "floor_pct": 0.10,
    },
    "A": {
        "tp1_pct": TP1_PCT, "tp1_sell": TP1_SELL,
        "tp2_pct": TP2_PCT, "tp2_sell": TP2_SELL,
        "tp3_pct": TP3_PCT, "tp3_sell": TP3_SELL,
        "trailing_pct": 0.20, "trailing_sell": 0.40,
        "floor_pct": 0.10,
    },
    "B": {
        "tp1_pct": TP1_PCT, "tp1_sell": TP1_SELL,
        "tp2_pct": min(TP2_PCT, 2.50), "tp2_sell": TP2_SELL,
        "tp3_pct": min(TP3_PCT, 6.00), "tp3_sell": TP3_SELL,
        "trailing_pct": 0.18, "trailing_sell": 0.40,
        "floor_pct": 0.10,
    },
    "D": {
        "tp1_pct": TP1_PCT, "tp1_sell": TP1_SELL,
        "tp2_pct": TP2_PCT, "tp2_sell": TP2_SELL,
        "tp3_pct": TP3_PCT, "tp3_sell": TP3_SELL,
        "trailing_pct": 0.20, "trailing_sell": 0.40,
        "floor_pct": 0.10,
    },
    "takeover": {
        "tp1_pct": 0.50, "tp1_sell": 0.50,
        "tp2_pct": 1.50, "tp2_sell": 0.30,
        "tp3_pct": 5.00, "tp3_sell": 0.30,
        "trailing_pct": 0.15, "trailing_sell": 0.40,
        "floor_pct": 0.10,
    },
}

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 15: STOP LOSS RULES
# Per-tier SL configuration. Override preset values here if needed.
# ══════════════════════════════════════════════════════════════════════════════

SL_RULES = {
    "S": {
        "sl_pct": SL1_PCT, "sl_sell": SL1_SELL,
        "sl2_pct": SL2_PCT, "sl2_sell": SL2_SELL,
        "time_decay": [(30, -0.15), (60, -0.10)],
        "timeout_hrs": 48,
    },
    "A": {
        "sl_pct": SL1_PCT, "sl_sell": SL1_SELL,
        "sl2_pct": SL2_PCT, "sl2_sell": SL2_SELL,
        "time_decay": [(30, -0.15), (60, -0.10)],
        "timeout_hrs": 48,
    },
    "B": {
        "sl_pct": SL1_PCT, "sl_sell": SL1_SELL,
        "sl2_pct": SL2_PCT, "sl2_sell": SL2_SELL,
        "time_decay": [(20, -0.15)],
        "timeout_hrs": 6,
    },
    "D": {
        "sl_pct": SL1_PCT, "sl_sell": SL1_SELL,
        "sl2_pct": SL2_PCT, "sl2_sell": SL2_SELL,
        "time_decay": [(15, -0.15), (30, -0.10)],
        "timeout_hrs": 12,
    },
    "takeover": {
        "sl_pct": SL1_PCT, "sl_sell": SL1_SELL,
        "sl2_pct": SL2_PCT, "sl2_sell": SL2_SELL,
        "time_decay": [],
        "timeout_hrs": 48,
    },
}

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 16: FLOOR POSITION EXIT
# Floor positions (remaining after all TPs) are cleaned when losing.
# ══════════════════════════════════════════════════════════════════════════════

FLOOR_EXIT_ENABLED  = True
FLOOR_EXIT_LOSS_PCT = -0.30   # Exit floor if loss exceeds -30%
FLOOR_EXIT_AGE_HRS  = 4.0    # Exit floor if age > 4h AND in loss
FLOOR_EXIT_AGE_LOSS = 0.0    # PnL threshold with age check

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 17: EMERGENCY EXIT
# These override ALL other rules including floor protection.
# ══════════════════════════════════════════════════════════════════════════════

HE1_PCT         = -0.50       # -50% = sell everything immediately
FAST_DUMP_PCT   = -0.20       # -20% from peak within window
FAST_DUMP_WINDOW = 60         # Window in seconds for flash crash detection
LIQ_EMERGENCY   = 5_000      # Liquidity < $5K = sell everything

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 18: SESSION RISK CONTROL
# V8: Pause only, never stop. TP/SL continue during pause.
# ══════════════════════════════════════════════════════════════════════════════

DAILY_LOSS_ACTION  = "pause"   # "pause" = temporary pause, never "stop"
STARTUP_COOLDOWN   = 120       # Seconds to wait before first trade after startup

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 19: SCAN INTERVALS & TIMING
# ══════════════════════════════════════════════════════════════════════════════

MONITOR_SEC        = 1         # Position monitor check interval
BALANCE_CHECK_SEC  = 60        # Balance display interval

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 20: SAFETY & EXECUTION
# ══════════════════════════════════════════════════════════════════════════════

SLIPPAGE_BUY       = 18        # Buy slippage tolerance (%)
SLIPPAGE_SELL      = 30        # Sell slippage tolerance (%) — high for illiquid tokens
SOL_GAS_RESERVE    = 0.05      # Keep this much SOL for gas
MIN_POSITION_VALUE = 0.10      # Minimum USD value to track a position

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 21: DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════

DASHBOARD_PORT     = 3250
DASHBOARD_ENABLED  = True

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 22: TRADE BLACKLIST
# Tokens that should never be traded (stablecoins, wrapped SOL, etc.)
# ══════════════════════════════════════════════════════════════════════════════

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

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 23: VALIDATION
# Auto-validates configuration at import time. Raises on critical errors.
# ══════════════════════════════════════════════════════════════════════════════

def validate_config():
    """Validate configuration values. Called at import time."""
    errors = []

    if PRESET not in _PRESETS:
        errors.append(f"PRESET '{PRESET}' invalid. Use: conservative, balanced, aggressive")
    if MAX_POSITIONS < 1 or MAX_POSITIONS > 20:
        errors.append(f"MAX_POSITIONS={MAX_POSITIONS} out of range [1, 20]")
    if DAILY_LOSS_LIMIT < 1:
        errors.append(f"DAILY_LOSS_LIMIT={DAILY_LOSS_LIMIT} must be > 0")
    if SLIPPAGE_BUY < 1 or SLIPPAGE_BUY > 50:
        errors.append(f"SLIPPAGE_BUY={SLIPPAGE_BUY} out of range [1, 50]")
    if HE1_PCT > -0.20:
        errors.append(f"HE1_PCT={HE1_PCT} too high (must be <= -0.20)")

    if errors:
        print("=" * 60)
        print("  CONFIG VALIDATION ERRORS:")
        for e in errors:
            print(f"    - {e}")
        print("=" * 60)
        raise SystemExit(1)

validate_config()

# ══════════════════════════════════════════════════════════════════════════════
# LEGACY COMPATIBILITY (do not remove)
# ══════════════════════════════════════════════════════════════════════════════

SOL_PER_TRADE = TIER_D_SIZE_BASE
