"""
risk_check.py — Pre/Post Trade Risk Assessment for Solana Meme Tokens
═══════════════════════════════════════════════════════════════════════

v8.0: Improved error handling, structured fallbacks, reduced API calls.

Two public functions:
  pre_trade_checks(addr, sym, quick=True)  — Pre-trade gate (call before entry)
  post_trade_flags(addr, sym, ...)         — Post-trade monitor (call while in position)

All data from onchainOS CLI. No extra API keys needed.

SEVERITY GRADES:
  G4 BLOCK  — Hard refuse (honeypot, tax >50%, dev removing liquidity)
  G3 WARN   — Strong refuse (serial rugger, LP unburned, snipers >15%, wash trading)
  G2 CAUTION — Allow with note (top10 >30%, bundles >5%, no smart money)
  G0 PASS   — All checks clear

result["pass"] is True when grade < 3.

CLI Usage:
  python3 risk_check.py <token_address> [symbol]
"""

import subprocess
import json
import os
import sys
import time
from collections import defaultdict

# ── Environment ───────────────────────────────────────────────────────────────

_LOCAL_BIN = os.path.expanduser("~/.local/bin")
if _LOCAL_BIN not in os.environ.get("PATH", ""):
    os.environ["PATH"] = _LOCAL_BIN + ":" + os.environ.get("PATH", "")

_CHAIN = "solana"
_CHAIN_ID = "501"

# ── Thresholds ────────────────────────────────────────────────────────────────

_SELL_VEL_WARN_SOL_PM = 1.0    # G3: > 1 SOL/min from dev/insiders
_SELL_VEL_BLOCK_SOL_PM = 5.0   # G4: > 5 SOL/min (active dump)
_WASH_ROUNDTRIP_RATIO = 0.50   # G3: >=50% wallets round-tripped
_WASH_ROUNDTRIP_SOFT = 0.30    # G3: >=30% + high concentration
_WASH_CONC_THRESHOLD = 0.40    # top-3 wallets >40% of trades
_LP_DRAIN_EXIT_PCT = 0.30      # post-trade: exit if liq drops >30%


# ── CLI Wrapper (with error handling) ─────────────────────────────────────────

def _onchainos(*args, timeout=20):
    """Run onchainos CLI. Returns parsed JSON or empty fallback."""
    try:
        r = subprocess.run(
            ["onchainos", *args],
            capture_output=True, text=True, timeout=timeout
        )
        return json.loads(r.stdout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "data": None, "msg": "timeout"}
    except json.JSONDecodeError:
        return {"ok": False, "data": None, "msg": "parse_error"}
    except FileNotFoundError:
        return {"ok": False, "data": None, "msg": "onchainos_not_found"}
    except Exception as e:
        return {"ok": False, "data": None, "msg": str(e)[:80]}


def _data(r):
    """Extract single data item from response."""
    d = r.get("data")
    if isinstance(d, list):
        return d[0] if d else {}
    return d or {}


def _data_list(r):
    """Extract data as list."""
    d = r.get("data")
    return d if isinstance(d, list) else []


# ── API Calls ─────────────────────────────────────────────────────────────────

def _security_scan(addr):
    """Security token-scan: honeypot, buy/sell tax."""
    r = _onchainos("security", "token-scan", "--tokens", f"{_CHAIN_ID}:{addr}")
    d = _data(r)
    return d if isinstance(d, dict) else {}


def _advanced_info(addr):
    """Token advanced-info: dev history, LP burn, snipers, tags."""
    r = _onchainos("token", "advanced-info", "--chain", _CHAIN, "--address", addr)
    d = _data(r)
    return d if isinstance(d, dict) else {}


def _liquidity_usd(addr):
    """Current liquidity in USD from price-info."""
    r = _onchainos("token", "price-info", "--chain", _CHAIN, "--address", addr)
    items = _data_list(r) or [_data(r)]
    for item in items:
        if isinstance(item, dict):
            try:
                liq = float(item.get("liquidity", 0) or 0)
                if liq > 0:
                    return liq
            except (ValueError, TypeError):
                pass
    return -1.0


def _tagged_trades(addr, tag, limit=50):
    """Trades by wallet tag (2=dev, 4=whale, 6=insider, 7=sniper)."""
    r = _onchainos("token", "trades", "--chain", _CHAIN, "--address", addr,
                   "--tag-filter", str(tag), "--limit", str(limit))
    return _data_list(r)


def _recent_trades(addr, limit=200):
    """All recent trades for wash detection."""
    r = _onchainos("token", "trades", "--chain", _CHAIN, "--address", addr,
                   "--limit", str(limit))
    return _data_list(r)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _tags(info):
    return info.get("tokenTags") or []


def _has_tag(info, prefix):
    return any(t.startswith(prefix) for t in _tags(info))


def _pct(info, field):
    try:
        return float(info.get(field, "") or "")
    except (ValueError, TypeError):
        return -1.0


def _int_val(info, field):
    try:
        return int(info.get(field, 0) or 0)
    except (ValueError, TypeError):
        return 0


def _trade_sol(trade):
    """Extract SOL amount from trade."""
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


# ── Check: Selling Velocity ──────────────────────────────────────────────────

def _selling_velocity(addr):
    """Returns (sol_per_min, detail_str). Checks dev+insider sells over 5min."""
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
    window = 5 * 60 * 1000
    total_sol = 0.0
    wallets = []

    for wallet, events in sells_by_wallet.items():
        recent = [(ts, sol) for ts, sol in events if now_ms - ts <= window]
        if recent:
            sol_sum = sum(s for _, s in recent)
            total_sol += sol_sum
            wallets.append(f"{wallet[:8]}({sol_sum:.1f}SOL)")

    if total_sol == 0:
        return 0.0, ""

    sol_pm = total_sol / (window / 60000)
    return sol_pm, f"{sol_pm:.2f} SOL/min [{', '.join(wallets[:3])}]"


# ── Check: Wash Trading ──────────────────────────────────────────────────────

def _wash_trading_check(addr):
    """Detect wash trading via round-trip wallets + concentration."""
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

    # Round-trip detection
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

    # Concentration
    top3 = sum(c for _, c in sorted(wallet_count.items(), key=lambda x: -x[1])[:3])
    concentration = top3 / len(trades)

    if rt_ratio >= _WASH_ROUNDTRIP_RATIO:
        return True, f"WASH_TRADING: {rt_wallets}/{total_wallets} wallets round-tripped ({rt_ratio*100:.0f}%)"
    if rt_ratio >= _WASH_ROUNDTRIP_SOFT and concentration >= _WASH_CONC_THRESHOLD:
        return True, (f"WASH_TRADING: {rt_wallets}/{total_wallets} round-tripped ({rt_ratio*100:.0f}%) "
                      f"+ top-3 drive {concentration*100:.0f}% volume")
    return False, ""


# ── Check: Holder Sell Coordination ──────────────────────────────────────────

def _holder_sell_check(addr):
    """Detect coordinated sells from tagged wallets (dev/whale/insider/sniper)."""
    tag_names = {2: "Dev", 4: "Whale", 6: "Insider", 7: "Sniper"}
    now_ms = int(time.time() * 1000)
    window = 10 * 60 * 1000
    findings = []

    for tag, label in tag_names.items():
        trades = _tagged_trades(addr, tag, limit=30)
        recent_sells = [t for t in trades
                        if t.get("type") == "sell" and now_ms - int(t.get("time", 0)) <= window]
        if len(recent_sells) >= 2:
            sol = sum(_trade_sol(t) for t in recent_sells)
            findings.append(f"{label}x{len(recent_sells)}({sol:.1f}SOL)")

    if findings:
        return True, "HOLDER_SELLING: " + ", ".join(findings) + " in 10min"
    return False, ""


# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC: pre_trade_checks
# ══════════════════════════════════════════════════════════════════════════════

def pre_trade_checks(addr, sym, quick=True):
    """
    Pre-trade risk assessment.
    quick=True: 3-4 API calls (~0.8s). Use for all pre-trade gates.
    quick=False: ~11 API calls. Use for manual analysis only.

    Returns: {"pass": bool, "grade": int, "reasons": [], "cautions": [], "raw": {}}
    """
    # Fetch data (fail-safe: empty dict on error)
    scan = _security_scan(addr)
    info = _advanced_info(addr)
    liq_usd = _liquidity_usd(addr)
    lp_burned = _pct(info, "lpBurnedPercent")

    reasons = []
    cautions = []
    level = 0

    # ── G4: HARD BLOCK ────────────────────────────────────────────────────

    if scan.get("isRiskToken"):
        reasons.append("G4: HONEYPOT flagged")
        level = 4

    buy_tax = _pct(scan, "buyTaxes")
    if buy_tax > 50:
        reasons.append(f"G4: BUY_TAX {buy_tax:.0f}%")
        level = 4

    sell_tax = _pct(scan, "sellTaxes")
    if sell_tax > 50:
        reasons.append(f"G4: SELL_TAX {sell_tax:.0f}%")
        level = 4

    if _has_tag(info, "devRemoveLiq"):
        reasons.append("G4: DEV_REMOVING_LIQUIDITY")
        level = 4

    if _has_tag(info, "lowLiquidity"):
        reasons.append("G4: LOW_LIQUIDITY (<$5K)")
        level = 4

    risk_lvl = _int_val(info, "riskControlLevel")
    if risk_lvl >= 1:
        reasons.append(f"G3: OKX_RISK_LEVEL={risk_lvl} (any risk blocked)")
        level = max(level, 3)

    # Selling velocity (full mode only)
    vel_sol_pm, vel_detail = (0.0, "") if quick else _selling_velocity(addr)
    if vel_sol_pm >= _SELL_VEL_BLOCK_SOL_PM:
        reasons.append(f"G4: ACTIVE_DUMP {vel_detail}")
        level = 4

    # ── G3: STRONG WARNING ────────────────────────────────────────────────

    rug_count = _int_val(info, "devRugPullTokenCount")
    dev_created = _int_val(info, "devCreateTokenCount")

    if dev_created > 0:
        rug_rate = rug_count / dev_created
        if rug_rate >= 0.20 and rug_count >= 3:
            reasons.append(f"G3: SERIAL_RUGGER {rug_count}/{dev_created} ({rug_rate*100:.0f}%)")
            level = max(level, 3)
        elif rug_rate >= 0.05 and rug_count >= 2:
            cautions.append(f"G2: RUG_HISTORY {rug_count}/{dev_created}")
    elif rug_count >= 5:
        reasons.append(f"G3: SERIAL_RUGGER {rug_count} confirmed rugs")
        level = max(level, 3)

    if 0 <= lp_burned < 80:
        reasons.append(f"G3: LP_NOT_BURNED ({lp_burned:.0f}% < 80%)")
        level = max(level, 3)

    if _has_tag(info, "volumeChangeRateVolumePlunge"):
        reasons.append("G3: VOLUME_PLUNGE")
        level = max(level, 3)

    sniper_pct = _pct(info, "sniperHoldingPercent")
    if sniper_pct > 10:
        reasons.append(f"G3: SNIPERS {sniper_pct:.1f}% > 10%")
        level = max(level, 3)

    suspicious_pct = _pct(info, "suspiciousHoldingPercent")
    if suspicious_pct > 5:
        reasons.append(f"G3: SUSPICIOUS_WALLETS {suspicious_pct:.1f}% > 5%")
        level = max(level, 3)

    # Phishing wallet count check (OKX tags suspicious addresses)
    suspicious_count = _int_val(info, "suspiciousAddressCount")
    if suspicious_count > 10:
        reasons.append(f"G3: PHISHING_WALLETS {suspicious_count} > 10")
        level = max(level, 3)

    # Wash trading (quick mode includes this — 1 extra API call)
    is_wash, wash_reason = _wash_trading_check(addr)
    if is_wash:
        reasons.append(f"G3: {wash_reason}")
        level = max(level, 3)

    # Full mode additional checks
    if not quick:
        if 0 < vel_sol_pm < _SELL_VEL_BLOCK_SOL_PM and vel_sol_pm >= _SELL_VEL_WARN_SOL_PM:
            reasons.append(f"G3: SOFT_RUG_VELOCITY {vel_detail}")
            level = max(level, 3)

        is_selling, sell_reason = _holder_sell_check(addr)
        if is_selling:
            reasons.append(f"G3: {sell_reason}")
            level = max(level, 3)

    # ── G2: CAUTION ───────────────────────────────────────────────────────

    top10 = _pct(info, "top10HoldPercent")
    if top10 > 30:
        cautions.append(f"G2: TOP10_CONCENTRATED {top10:.1f}%")
        level = max(level, 2)

    bundle_pct = _pct(info, "bundleHoldingPercent")
    if bundle_pct > 5:
        cautions.append(f"G2: BUNDLES {bundle_pct:.1f}%")
        level = max(level, 2)

    is_cto = _has_tag(info, "dexScreenerTokenCommunityTakeOver")
    if _has_tag(info, "devHoldingStatusSellAll") and not is_cto:
        cautions.append("G2: DEV_SOLD_ALL (not CTO)")
        level = max(level, 2)

    if _has_tag(info, "dsPaid"):
        cautions.append("G2: PAID_LISTING")
        level = max(level, 2)

    if not _has_tag(info, "smartMoneyBuy"):
        cautions.append("G2: NO_SMART_MONEY")
        level = max(level, 2)

    # ── Result ────────────────────────────────────────────────────────────

    return {
        "pass": level < 3,
        "grade": level,
        "level": level,  # backward compat
        "reasons": reasons,
        "cautions": cautions,
        "raw": {"scan": scan, "info": info, "liquidity_usd": liq_usd},
    }


# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC: post_trade_flags
# ══════════════════════════════════════════════════════════════════════════════

def post_trade_flags(addr, sym,
                     entry_liquidity_usd=0.0,
                     entry_top10=0.0,
                     entry_sniper_pct=0.0):
    """
    Post-trade monitoring. Call every 60s per position.
    Returns list of action strings:
      "EXIT_NOW: ..."         — close immediately
      "EXIT_NEXT_TP: ..."     — exit at next TP
      "REDUCE_POSITION: ..."  — cut size
      "ALERT: ..."            — informational
    """
    info = _advanced_info(addr)
    liq_usd = _liquidity_usd(addr)
    flags = []

    # Dev removing liquidity → EXIT NOW
    if _has_tag(info, "devRemoveLiq"):
        flags.append("EXIT_NOW: DEV_REMOVING_LIQUIDITY")

    # Liquidity drain >30% → EXIT NOW
    if entry_liquidity_usd > 0 and liq_usd > 0:
        drain = (entry_liquidity_usd - liq_usd) / entry_liquidity_usd
        if drain >= _LP_DRAIN_EXIT_PCT:
            flags.append(f"EXIT_NOW: LIQUIDITY_DRAIN {drain*100:.0f}% (${entry_liquidity_usd:,.0f}→${liq_usd:,.0f})")

    # Active dump → EXIT NOW
    vel_sol_pm, vel_detail = _selling_velocity(addr)
    if vel_sol_pm >= _SELL_VEL_BLOCK_SOL_PM:
        flags.append(f"EXIT_NOW: ACTIVE_DUMP {vel_detail}")

    # Holder selling → EXIT_NEXT_TP (v8: downgraded from EXIT_NOW)
    is_selling, sell_reason = _holder_sell_check(addr)
    if is_selling:
        flags.append(f"EXIT_NEXT_TP: {sell_reason}")

    # Volume plunge → EXIT_NEXT_TP
    if _has_tag(info, "volumeChangeRateVolumePlunge"):
        flags.append("EXIT_NEXT_TP: VOLUME_PLUNGE")

    # Soft rug velocity → EXIT_NEXT_TP
    if 0 < vel_sol_pm < _SELL_VEL_BLOCK_SOL_PM and vel_sol_pm >= _SELL_VEL_WARN_SOL_PM:
        flags.append(f"EXIT_NEXT_TP: SOFT_RUG {vel_detail}")

    # Sniper spike → REDUCE
    sniper_pct = _pct(info, "sniperHoldingPercent")
    if sniper_pct > entry_sniper_pct + 5:
        flags.append(f"REDUCE_POSITION: SNIPER_SPIKE {sniper_pct:.1f}% (was {entry_sniper_pct:.1f}%)")

    # Top10 drift → ALERT
    top10 = _pct(info, "top10HoldPercent")
    if top10 > 40 and top10 > entry_top10 + 5:
        flags.append(f"ALERT: TOP10_DRIFT {top10:.1f}% (was {entry_top10:.1f}%)")

    return flags


# ══════════════════════════════════════════════════════════════════════════════
# CLI MODE
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    addr = sys.argv[1] if len(sys.argv) > 1 else ""
    sym = sys.argv[2] if len(sys.argv) > 2 else addr[:8]
    if not addr:
        print("Usage: python3 risk_check.py <token_address> [symbol]")
        sys.exit(1)

    print(f"\n{'='*55}")
    print(f"  Risk Check — {sym}")
    print(f"  {addr}")
    print(f"{'='*55}")

    r = pre_trade_checks(addr, sym, quick=False)

    labels = {0: "PASS", 2: "CAUTION", 3: "WARN", 4: "BLOCK"}
    print(f"\n  Result: {labels.get(r['grade'], str(r['grade']))}")
    print(f"  Liquidity: ${r['raw']['liquidity_usd']:,.0f}")

    if r["reasons"]:
        print("\n  Blocks/Warnings:")
        for reason in r["reasons"]:
            print(f"    - {reason}")

    if r["cautions"]:
        print("\n  Cautions:")
        for c in r["cautions"]:
            print(f"    - {c}")

    print()
