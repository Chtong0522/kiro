"""
risk_check.py - Standalone pre/post trade risk assessment for Solana meme tokens.
Drop-in module for SOL Meme Hunter v7 and any onchainos-based strategy.

OVERVIEW
--------
Two public functions:

  pre_trade_checks(addr, sym, quick=True)  - pre-trade gate. Call before entering any position.
  post_trade_flags(addr, sym, ...)         - post-trade monitor. Call periodically while in position.

All data comes from onchainos CLI (~/.local/bin/onchainos). No extra API keys needed.

SEVERITY GRADES
---------------
Grade 4 - HARD BLOCK. Do not enter. Abort immediately.
  Triggers: honeypot, buy/sell tax >50%, dev actively removing liquidity,
            OKX riskControlLevel >=4, active dev/insider dump >=5 SOL/min.

Grade 3 - STRONG WARNING. Do not enter. Too risky.
  Triggers: serial rugger (>=3 rugs), rug rate >50%, LP <80% burned,
            volume plunge tag, snipers >15%, suspicious wallets >10%,
            wash trading (round-trip wallets), single LP provider with unburned LP.

Grade 2 - CAUTION. Proceed with awareness. Log the flags.
  Triggers: top 10 wallets hold >30%, bundles still in >5%, dev sold all (non-CTO),
            paid DexScreener listing, no smart money detected.

Grade 0 - PASS. All checks clear.

result["pass"] is True when grade < 3 (grades 0 and 2 are both tradeable).

V7 CHANGES
----------
- Holder selling moved from G3 pre-trade to post-trade EXIT_NEXT_TP only
  (normal profit-taking should not block entry)
- post_trade_flags: HOLDER_SELLING now triggers EXIT_NEXT_TP instead of EXIT_NOW
  (V6 was too aggressive, causing premature exits on normal profit-taking)
- Selling velocity thresholds relaxed slightly for post-trade (warn only, don't instant-exit
  unless it's truly massive)

CLI USAGE
---------
    python3 risk_check.py <token_address> [symbol]
"""

import subprocess
import json
import os
import sys
import time
from collections import defaultdict

# ── Configuration (self-contained, no config import) ──────────────────────────

_ONCHAINOS = os.path.expanduser("~/.local/bin/onchainos")
_CHAIN     = "solana"
_CHAIN_ID  = "501"

# Ensure onchainos binary is on PATH
_LOCAL_BIN = os.path.expanduser("~/.local/bin")
if _LOCAL_BIN not in os.environ.get("PATH", ""):
    os.environ["PATH"] = _LOCAL_BIN + ":" + os.environ.get("PATH", "")

# Selling velocity - SOL sold per minute thresholds
_SELL_VEL_WARN_SOL_PM  = 1.0   # G3: > 1 SOL/min from dev/insiders
_SELL_VEL_BLOCK_SOL_PM = 5.0   # G4: > 5 SOL/min (active dump)

# Wash trading - round-trip detection thresholds
_WASH_ROUNDTRIP_RATIO = 0.50   # G3: >=50% of active wallets round-tripped alone
_WASH_ROUNDTRIP_SOFT  = 0.30   # G3: >=30% round-tripped AND concentration above threshold
_WASH_CONC_THRESHOLD  = 0.40   # top-3 wallets driving >40% of all trades = suspicious

# LP checks
_LP_DRAIN_EXIT_PCT = 0.30      # post-trade: exit if liquidity drops > 30%


# ── Internal CLI wrapper ──────────────────────────────────────────────────────

def _onchainos(*args, timeout: int = 20) -> dict:
    """Run onchainos CLI command, return parsed JSON or empty fallback."""
    try:
        r = subprocess.run(
            [_ONCHAINOS, *args],
            capture_output=True, text=True, timeout=timeout
        )
        return json.loads(r.stdout)
    except Exception:
        return {"ok": False, "data": None}


def _data(r: dict):
    """Extract single data item from response (handles list vs dict)."""
    d = r.get("data")
    if isinstance(d, list):
        return d[0] if d else {}
    return d or {}


def _data_list(r: dict) -> list:
    """Extract data as list from response."""
    d = r.get("data")
    return d if isinstance(d, list) else []


# ── API calls ─────────────────────────────────────────────────────────────────

def _security_scan(addr: str) -> dict:
    """Security token-scan: honeypot flag, buy/sell tax."""
    r = _onchainos("security", "token-scan",
                   "--tokens", f"{_CHAIN_ID}:{addr}")
    d = _data(r)
    return d if isinstance(d, dict) else {}


def _advanced_info(addr: str) -> dict:
    """Token advanced-info: dev rug history, LP burn, sniper %, tags, top10, bundles."""
    r = _onchainos("token", "advanced-info",
                   "--chain", _CHAIN, "--address", addr)
    d = _data(r)
    return d if isinstance(d, dict) else {}


def _liquidity_usd(addr: str) -> float:
    """Current total liquidity in USD from price-info."""
    r = _onchainos("token", "price-info",
                   "--chain", _CHAIN, "--address", addr)
    items = _data_list(r)
    if not items:
        items = [_data(r)]
    for item in items:
        if isinstance(item, dict) and item.get("liquidity"):
            try:
                return float(item["liquidity"])
            except (ValueError, TypeError):
                pass
    return -1.0


def _lp_pools(addr: str) -> list:
    """Top LP pools with creator info (full mode only)."""
    r = _onchainos("token", "liquidity",
                   "--chain", _CHAIN, "--address", addr)
    return _data_list(r)


def _tagged_trades(addr: str, tag: int, limit: int = 50) -> list:
    """Trades filtered by wallet tag (2=dev, 4=whale, 6=insider, 7=sniper)."""
    r = _onchainos("token", "trades",
                   "--chain", _CHAIN, "--address", addr,
                   "--tag-filter", str(tag),
                   "--limit", str(limit))
    return _data_list(r)


def _recent_trades(addr: str, limit: int = 100) -> list:
    """All recent trades for wash trading detection."""
    r = _onchainos("token", "trades",
                   "--chain", _CHAIN, "--address", addr,
                   "--limit", str(limit))
    return _data_list(r)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _tags(info: dict) -> list:
    """Get tokenTags from info, always returns list."""
    return info.get("tokenTags") or []


def _has_tag(info: dict, prefix: str) -> bool:
    """Check if any tokenTag starts with prefix."""
    return any(t.startswith(prefix) for t in _tags(info))


def _pct(info: dict, field: str) -> float:
    """Extract percentage float from info field, return -1.0 on failure."""
    v = info.get(field, "") or ""
    try:
        return float(v)
    except (ValueError, TypeError):
        return -1.0


def _int_val(info: dict, field: str) -> int:
    """Extract integer from info field, return 0 on failure."""
    v = info.get(field, 0) or 0
    try:
        return int(v)
    except (ValueError, TypeError):
        return 0


def _trade_sol(trade: dict) -> float:
    """Extract SOL amount from a trade's changedTokenInfo or volume."""
    for t in trade.get("changedTokenInfo", []):
        if t.get("tokenSymbol") in ("SOL", "wSOL"):
            try:
                return float(t.get("amount", 0))
            except (ValueError, TypeError):
                pass
    try:
        return float(trade.get("volume", 0))
    except (ValueError, TypeError):
        return 0.0


# ── Check: Selling velocity (dev + insider sells) ────────────────────────────

def _selling_velocity(addr: str) -> tuple:
    """
    Returns (sol_per_min, reason_str).
    Checks dev (tag=2) + insider (tag=6) sells over a 5-min window.
    Detects soft rugs: steady sell pressure from privileged wallets.
    """
    sells_by_wallet = defaultdict(list)

    for tag in (2, 6):  # dev + insider
        for trade in _tagged_trades(addr, tag, limit=50):
            if trade.get("type") != "sell":
                continue
            ts = int(trade.get("time", 0))
            sol = _trade_sol(trade)
            if sol > 0 and ts > 0:
                sells_by_wallet[trade.get("userAddress", "?")].append((ts, sol))

    if not sells_by_wallet:
        return 0.0, ""

    now_ms = int(time.time() * 1000)
    window = 5 * 60 * 1000  # 5-minute window
    total_sol = 0.0
    wallets = []

    for wallet, events in sells_by_wallet.items():
        recent = [(ts, sol) for ts, sol in events if now_ms - ts <= window]
        if recent:
            sol_sum = sum(s for _, s in recent)
            total_sol += sol_sum
            wallets.append(f"{wallet[:8]}...({sol_sum:.2f}SOL)")

    if total_sol == 0:
        return 0.0, ""

    elapsed_min = window / 60000
    sol_pm = total_sol / elapsed_min
    detail = f"{sol_pm:.2f} SOL/min -- {', '.join(wallets)}"
    return sol_pm, detail


# ── Check: LP provider concentration ─────────────────────────────────────────

def _lp_provider_check(addr: str, lp_burned: float) -> tuple:
    """
    Returns (is_risky, reason_str).
    Single LP provider + LP not burned = high rug risk.
    """
    pools = _lp_pools(addr)
    if not pools:
        return False, ""

    creators = set()
    for pool in pools:
        liq = 0.0
        try:
            liq = float(pool.get("liquidityUsd", 0))
        except (ValueError, TypeError):
            pass
        if liq > 100:  # ignore dust pools
            creator = pool.get("poolCreator", "")
            if creator:
                creators.add(creator)

    if len(creators) == 1 and lp_burned < 80:
        creator = next(iter(creators))
        total_liq = sum(
            float(p.get("liquidityUsd", 0) or 0) for p in pools
        )
        return (
            True,
            f"SINGLE_LP_PROVIDER -- {creator[:12]}... controls "
            f"${total_liq:,.0f} liquidity, LP only {lp_burned:.0f}% burned"
        )

    return False, ""


# ── Check: Wash trading ───────────────────────────────────────────────────────

def _wash_trading_check(addr: str) -> tuple:
    """
    Returns (is_wash, reason_str).
    Detects wash trading via two signals:
      1. Round-trip wallets -- wallets that both buy AND sell within a 5-min window.
         Flags if >=50% of active wallets are round-tripping (strong signal alone),
         or >=30% round-tripping AND top-3 wallets drive >40% of trades (combined signal).
      2. Wallet concentration -- high trade share from a tiny set of wallets amplifies
         the round-trip signal, indicating coordinated volume inflation.
    """
    trades = _recent_trades(addr, limit=200)
    if len(trades) < 15:
        return False, ""

    wallet_buys = defaultdict(list)
    wallet_sells = defaultdict(list)
    wallet_count = defaultdict(int)

    for t in trades:
        w = t.get("userAddress", "")
        ts = int(t.get("time", 0))
        if not w or ts == 0:
            continue
        wallet_count[w] += 1
        if t.get("type") == "buy":
            wallet_buys[w].append(ts)
        else:
            wallet_sells[w].append(ts)

    active_wallets = set(wallet_buys) | set(wallet_sells)
    if not active_wallets:
        return False, ""

    # Round-trip: any buy followed by a sell from the same wallet within 5 min
    window_ms = 5 * 60 * 1000
    rt_wallets = 0
    for w in active_wallets:
        buys = sorted(wallet_buys[w])
        sells = sorted(wallet_sells[w])
        if not buys or not sells:
            continue
        if any(any(s > b and s - b <= window_ms for s in sells) for b in buys):
            rt_wallets += 1

    total_wallets = len(active_wallets)
    rt_ratio = rt_wallets / total_wallets

    # Wallet concentration: top-3 wallets share of all trades
    top3 = sum(c for _, c in sorted(wallet_count.items(), key=lambda x: -x[1])[:3])
    concentration = top3 / len(trades)

    if rt_ratio >= _WASH_ROUNDTRIP_RATIO:
        return (
            True,
            f"WASH_TRADING -- {rt_wallets}/{total_wallets} wallets round-tripped "
            f"({rt_ratio*100:.0f}%) within 5-min windows"
        )
    if rt_ratio >= _WASH_ROUNDTRIP_SOFT and concentration >= _WASH_CONC_THRESHOLD:
        return (
            True,
            f"WASH_TRADING -- {rt_wallets}/{total_wallets} wallets round-tripped "
            f"({rt_ratio*100:.0f}%) + top-3 wallets drive {concentration*100:.0f}% of volume"
        )

    return False, ""


# ── Check: Holder sell coordination ──────────────────────────────────────────

def _holder_sell_check(addr: str) -> tuple:
    """
    Returns (is_selling, reason_str).
    Detects coordinated sells from tagged wallets (dev, whale, insider, sniper).
    Flags when >=2 sells from the same tag type within 10 minutes.
    """
    tag_names = {2: "Dev", 4: "Whale", 6: "Insider", 7: "Sniper"}
    now_ms = int(time.time() * 1000)
    window = 10 * 60 * 1000  # 10-minute window
    findings = []

    for tag, label in tag_names.items():
        trades = _tagged_trades(addr, tag, limit=30)
        recent_sells = [
            t for t in trades
            if t.get("type") == "sell"
            and now_ms - int(t.get("time", 0)) <= window
        ]
        if len(recent_sells) >= 2:
            sol = sum(_trade_sol(t) for t in recent_sells)
            findings.append(f"{label}x{len(recent_sells)}({sol:.2f}SOL)")

    if findings:
        return True, "HOLDER_SELLING -- " + ", ".join(findings) + " in last 10min"
    return False, ""


# ── Core: pre_trade_checks ────────────────────────────────────────────────────

def pre_trade_checks(addr: str, sym: str, quick: bool = True) -> dict:
    """
    Run pre-trade risk assessment.

    quick=True  - fast mode (4 API calls, ~0.8s). Use for pre-trade gates.
                  Runs: security scan + advanced-info + price-info + wash trading.
                  Skips: selling velocity, LP provider, holder sells.

    quick=False - full mode (~11 API calls). Use for manual analysis only.

    Returns:
    {
        "pass":     bool,       # True when grade < 3
        "grade":    int,        # 4=block, 3=warn, 2=caution, 0=pass
        "level":    int,        # alias for grade (backward compat)
        "reasons":  [str],      # grade 4 + 3 failures
        "cautions": [str],      # grade 2 flags
        "raw": {
            "scan": dict,
            "info": dict,
            "liquidity_usd": float
        }
    }
    """
    scan = _security_scan(addr)
    info = _advanced_info(addr)
    liq_usd = _liquidity_usd(addr)
    lp_burned = _pct(info, "lpBurnedPercent")

    reasons = []
    cautions = []
    level = 0

    # ── Grade 4 - Hard Block ─────────────────────────────────────────────────

    if scan.get("isRiskToken"):
        reasons.append("G4: HONEYPOT -- isRiskToken flagged by OKX")
        level = 4

    buy_tax = _pct(scan, "buyTaxes")
    if buy_tax > 50:
        reasons.append(f"G4: BUY_TAX {buy_tax:.0f}% > 50%")
        level = 4

    sell_tax = _pct(scan, "sellTaxes")
    if sell_tax > 50:
        reasons.append(f"G4: SELL_TAX {sell_tax:.0f}% > 50%")
        level = 4

    if _has_tag(info, "devRemoveLiq"):
        tag = next(t for t in _tags(info) if t.startswith("devRemoveLiq"))
        reasons.append(f"G4: DEV_REMOVING_LIQUIDITY -- {tag}")
        level = 4

    if _has_tag(info, "lowLiquidity"):
        reasons.append("G4: LOW_LIQUIDITY -- total liquidity < $5K")
        level = 4

    risk_lvl = _int_val(info, "riskControlLevel")
    if risk_lvl >= 4:
        reasons.append(f"G4: OKX_RISK_LEVEL {risk_lvl} >= 4")
        level = 4

    # Selling velocity - active dump (full mode only)
    vel_sol_pm, vel_detail = (0.0, "") if quick else _selling_velocity(addr)
    if vel_sol_pm >= _SELL_VEL_BLOCK_SOL_PM:
        reasons.append(f"G4: ACTIVE_DUMP -- {vel_detail}")
        level = 4

    # ── Grade 3 - Strong Warning ─────────────────────────────────────────────

    rug_count = _int_val(info, "devRugPullTokenCount")
    dev_created = _int_val(info, "devCreateTokenCount")

    if dev_created > 0:
        rug_rate = rug_count / dev_created
        if rug_rate >= 0.20 and rug_count >= 3:
            reasons.append(
                f"G3: SERIAL_RUGGER -- {rug_count}/{dev_created} tokens rugged "
                f"({rug_rate*100:.0f}%)"
            )
            level = max(level, 3)
        elif rug_rate >= 0.05 and rug_count >= 2:
            cautions.append(
                f"G2: RUG_HISTORY -- {rug_count}/{dev_created} tokens rugged "
                f"({rug_rate*100:.0f}%)"
            )
    elif rug_count >= 5:
        reasons.append(f"G3: SERIAL_RUGGER -- {rug_count} confirmed rug pulls (no total count)")
        level = max(level, 3)

    if 0 <= lp_burned < 80:
        reasons.append(f"G3: LP_NOT_BURNED -- {lp_burned:.1f}% burned (< 80%)")
        level = max(level, 3)

    if _has_tag(info, "volumeChangeRateVolumePlunge"):
        reasons.append("G3: VOLUME_PLUNGE -- trading activity collapsing")
        level = max(level, 3)

    sniper_pct = _pct(info, "sniperHoldingPercent")
    if sniper_pct > 15:
        reasons.append(f"G3: SNIPERS_HOLDING {sniper_pct:.1f}% > 15%")
        level = max(level, 3)

    suspicious_pct = _pct(info, "suspiciousHoldingPercent")
    if suspicious_pct > 10:
        reasons.append(f"G3: SUSPICIOUS_WALLETS {suspicious_pct:.1f}% > 10%")
        level = max(level, 3)

    # Wash trading - round-trip + concentration (1 extra API call, ~0.2s)
    is_wash, wash_reason = _wash_trading_check(addr)
    if is_wash:
        reasons.append(f"G3: {wash_reason}")
        level = max(level, 3)

    # ── Slow checks - full mode only ─────────────────────────────────────────

    if not quick:
        # Selling velocity - soft rug (steady bleed)
        if 0 < vel_sol_pm < _SELL_VEL_BLOCK_SOL_PM and vel_sol_pm >= _SELL_VEL_WARN_SOL_PM:
            reasons.append(f"G3: SOFT_RUG_VELOCITY -- {vel_detail}")
            level = max(level, 3)

        # LP provider concentration
        lp_risky, lp_reason = _lp_provider_check(addr, lp_burned)
        if lp_risky:
            reasons.append(f"G3: {lp_reason}")
            level = max(level, 3)

        # Holder selling - coordinated exits from tagged wallets
        is_selling, sell_reason = _holder_sell_check(addr)
        if is_selling:
            reasons.append(f"G3: {sell_reason}")
            level = max(level, 3)

    # ── Grade 2 - Caution ────────────────────────────────────────────────────

    top10 = _pct(info, "top10HoldPercent")
    if top10 > 30:
        cautions.append(f"G2: SUPPLY_CONCENTRATED -- top 10 hold {top10:.1f}%")
        level = max(level, 2)

    bundle_pct = _pct(info, "bundleHoldingPercent")
    if bundle_pct > 5:
        cautions.append(f"G2: BUNDLES_STILL_IN {bundle_pct:.1f}% > 5%")
        level = max(level, 2)

    is_cto = _has_tag(info, "dexScreenerTokenCommunityTakeOver")
    if _has_tag(info, "devHoldingStatusSellAll") and not is_cto:
        cautions.append("G2: DEV_SOLD_ALL -- dev exited (not a CTO)")
        level = max(level, 2)

    if _has_tag(info, "dsPaid"):
        cautions.append("G2: PAID_LISTING -- dexscreener listing was paid")
        level = max(level, 2)

    if not _has_tag(info, "smartMoneyBuy"):
        cautions.append("G2: NO_SMART_MONEY -- no smart money wallet detected")
        level = max(level, 2)

    # ── Result ────────────────────────────────────────────────────────────────

    passed = level < 3

    return {
        "pass":     passed,
        "grade":    level,
        "level":    level,
        "reasons":  reasons,
        "cautions": cautions,
        "raw": {
            "scan":          scan,
            "info":          info,
            "liquidity_usd": liq_usd,
        },
    }


# ── Core: post_trade_flags ────────────────────────────────────────────────────

def post_trade_flags(addr: str, sym: str,
                     entry_liquidity_usd: float = 0.0,
                     entry_top10: float = 0.0,
                     entry_sniper_pct: float = 0.0) -> list:
    """
    Call periodically during position monitoring (throttle to once per 60s).

    Returns list of action strings:
        "EXIT_NOW: ..."        - close immediately (dev rug, liquidity drain, active dump)
        "EXIT_NEXT_TP: ..."    - exit at next TP or trailing stop (volume plunge, soft rug)
        "REDUCE_POSITION: ..." - cut position size (sniper spike)
        "ALERT: ..."           - informational, no action required
    """
    info = _advanced_info(addr)
    liq_usd = _liquidity_usd(addr)
    flags = []

    # Dev removing liquidity - EXIT NOW
    if _has_tag(info, "devRemoveLiq"):
        tag = next((t for t in _tags(info) if t.startswith("devRemoveLiq")), "devRemoveLiq")
        flags.append(f"EXIT_NOW: DEV_REMOVING_LIQUIDITY -- {tag}")

    # Liquidity drain > 30% since entry - EXIT NOW
    if entry_liquidity_usd > 0 and liq_usd > 0:
        drain_pct = (entry_liquidity_usd - liq_usd) / entry_liquidity_usd
        if drain_pct >= _LP_DRAIN_EXIT_PCT:
            flags.append(
                f"EXIT_NOW: LIQUIDITY_DRAIN {drain_pct*100:.0f}% -- "
                f"${entry_liquidity_usd:,.0f} -> ${liq_usd:,.0f}"
            )

    # Active dump from dev/insiders - EXIT NOW
    vel_sol_pm, vel_detail = _selling_velocity(addr)
    if vel_sol_pm >= _SELL_VEL_BLOCK_SOL_PM:
        flags.append(f"EXIT_NOW: ACTIVE_DUMP -- {vel_detail}")

    # Holder selling - coordinated exits
    # V7: Downgraded from EXIT_NOW to EXIT_NEXT_TP
    # Reason: Normal profit-taking by whales/insiders is common and doesn't mean rug.
    # Only dev liquidity removal (checked above) warrants immediate exit.
    is_selling, sell_reason = _holder_sell_check(addr)
    if is_selling:
        flags.append(f"EXIT_NEXT_TP: {sell_reason}")

    # Volume collapsing - exit at next TP
    if _has_tag(info, "volumeChangeRateVolumePlunge"):
        flags.append("EXIT_NEXT_TP: VOLUME_PLUNGE -- activity collapsing")

    # Soft rug velocity
    if 0 < vel_sol_pm < _SELL_VEL_BLOCK_SOL_PM and vel_sol_pm >= _SELL_VEL_WARN_SOL_PM:
        flags.append(f"EXIT_NEXT_TP: SOFT_RUG_VELOCITY -- {vel_detail}")

    # Sniper spike
    sniper_pct = _pct(info, "sniperHoldingPercent")
    if sniper_pct > entry_sniper_pct + 5:
        flags.append(
            f"REDUCE_POSITION: SNIPER_SPIKE {sniper_pct:.1f}% "
            f"(was {entry_sniper_pct:.1f}% at entry)"
        )

    # Top 10 concentration increase
    top10 = _pct(info, "top10HoldPercent")
    if top10 > 40 and top10 > entry_top10 + 5:
        flags.append(
            f"ALERT: TOP10_CONCENTRATION {top10:.1f}% "
            f"(was {entry_top10:.1f}% at entry)"
        )

    return flags


# ── CLI usage ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    addr = sys.argv[1] if len(sys.argv) > 1 else ""
    sym = sys.argv[2] if len(sys.argv) > 2 else addr[:8]
    if not addr:
        print("Usage: python3 risk_check.py <token_address> [symbol]")
        sys.exit(1)

    print(f"\n{'='*55}")
    print(f"  Risk Check -- {sym}")
    print(f"  {addr}")
    print(f"{'='*55}")

    r = pre_trade_checks(addr, sym, quick=False)

    level_label = {0: "PASS", 2: "CAUTION", 3: "WARN", 4: "BLOCK"}
    print(f"\n  Result: {level_label.get(r['level'], str(r['level']))}")
    print(f"  Liquidity: ${r['raw']['liquidity_usd']:,.0f}")

    if r["reasons"]:
        print("\n  Blocks / Warnings:")
        for reason in r["reasons"]:
            print(f"    - {reason}")

    if r["cautions"]:
        print("\n  Cautions:")
        for c in r["cautions"]:
            print(f"    - {c}")

    print()
