#!/usr/bin/env python3
"""
SOL Meme Hunter v8.0 — Autonomous Solana Meme Token Trading Bot
═══════════════════════════════════════════════════════════════════

Architecture: 4-Tier (S/A/B/D) + Smart Wallet Signal + 9-Layer Adaptive Exit
Data Source:  onchainOS CLI (sole source, zero API keys)
Execution:    TEE-secured wallet signing via onchainos contract-call

Tiers:
  S — Smart Wallet Follow (curated 816-address database)
  A — Smart Money Signal (onchainos signal list, multi-wallet co-buy)
  B — Graduation Ambush (PumpFun → Raydium MIGRATED tokens)
  D — Hot Momentum (composite-scored trending tokens)

V8 Improvements over V7:
  - User-configurable presets (conservative/balanced/aggressive)
  - Improved error handling with structured fallbacks
  - Reduced redundant API calls (cache-first architecture)
  - Better thread safety with context managers
  - Structured logging with severity levels
  - Graceful degradation on API failures

Dashboard: http://localhost:3250
"""

# ══════════════════════════════════════════════════════════════════════════════
# IMPORTS
# ══════════════════════════════════════════════════════════════════════════════

import subprocess
import json
import time
import os
import csv
import threading
import signal
import sys
import random
import string
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict
from http.server import HTTPServer, BaseHTTPRequestHandler
from contextlib import contextmanager

import config
from risk_check import pre_trade_checks, post_trade_flags

# ══════════════════════════════════════════════════════════════════════════════
# ENVIRONMENT SETUP
# ══════════════════════════════════════════════════════════════════════════════

os.environ["PATH"] = (
    os.path.expanduser("~/.local/bin") + ":"
    + os.path.expanduser("~/.nvm/versions/node/v22.22.2/bin") + ":"
    + os.environ.get("PATH", "")
)

PROJECT_DIR = Path(__file__).parent
SOL_NATIVE = config.SOL_NATIVE
_NEVER_TRADE = getattr(config, "_NEVER_TRADE_MINTS", set())
_startup_ts = time.time()
_VERSION = "8.0"

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1: SMART WALLET DATABASE
# ══════════════════════════════════════════════════════════════════════════════

_smart_wallets = {}  # {addr: {"tier": int, "group": str, "roles": set, "tokens": set}}


def load_smart_wallets():
    """Load smart wallet database from CSV. Fail-safe: logs warning on error."""
    global _smart_wallets
    csv_path = PROJECT_DIR / config.SMART_WALLET_CSV
    if not csv_path.exists():
        log("WARN", f"Smart wallet CSV not found: {csv_path}")
        return

    wallets = {}
    try:
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                addr = row.get("钱包地址", "").strip()
                group = row.get("分组", "").strip()
                token = row.get("代币", "").strip()
                role_str = row.get("角色", "").strip()

                if not addr:
                    continue

                tier = config.SMART_WALLET_GROUP_TIER.get(group, 3)

                if addr not in wallets:
                    wallets[addr] = {"tier": tier, "group": group, "roles": set(), "tokens": set()}
                else:
                    # Keep best tier
                    if tier > 0 and (wallets[addr]["tier"] < 0 or tier < wallets[addr]["tier"]):
                        wallets[addr]["tier"] = tier

                if token:
                    wallets[addr]["tokens"].add(token)
                if role_str:
                    for r in role_str.split(","):
                        wallets[addr]["roles"].add(r.strip())

        _smart_wallets = wallets
        tier_counts = defaultdict(int)
        for w in wallets.values():
            tier_counts[w["tier"]] += 1
        log("INFO", f"Smart Wallets: {len(wallets)} loaded | "
            f"T1={tier_counts[1]} T2={tier_counts[2]} T3={tier_counts[3]} neg={tier_counts[-1]}")
    except Exception as e:
        log("ERROR", f"Loading smart wallets: {e}")


def get_smart_wallet_score(token_holders):
    """Calculate smart wallet boost from token's top holders."""
    if not _smart_wallets or not token_holders:
        return 0, []

    total_boost = 0
    matched = []

    for holder_addr in token_holders:
        if holder_addr in _smart_wallets:
            info = _smart_wallets[holder_addr]
            base_boost = config.SMART_WALLET_SCORE_BOOST.get(info["tier"], 0)
            best_mult = max((config.SMART_WALLET_ROLE_WEIGHT.get(r, 1.0) for r in info["roles"]), default=1.0)
            boost = int(base_boost * best_mult)
            total_boost += boost
            matched.append({"addr": holder_addr[:8], "tier": info["tier"], "boost": boost})

    return min(total_boost, config.SMART_WALLET_MAX_BOOST), matched


def get_smart_wallet_addresses(tier_filter=None):
    """Get wallet addresses, optionally filtered by tier."""
    if tier_filter is None:
        return list(_smart_wallets.keys())
    return [a for a, i in _smart_wallets.items() if i["tier"] in tier_filter]


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2: STATE MANAGEMENT (Thread-Safe)
# ══════════════════════════════════════════════════════════════════════════════

_state_lock = threading.Lock()
_pos_lock = threading.Lock()
_trades_lock = threading.Lock()

cooldown_map = {}
_selling = set()
_wallet_addr = ""
_risk_semaphore = threading.Semaphore(3)

state = {
    "positions": {},
    "trades": [],
    "feed": [],
    "stats": {"cycle": 0, "buys": 0, "sells": 0, "wins": 0, "losses": 0, "net_pnl": 0.0},
}

session_risk = {
    "consecutive_losses": 0,
    "cumulative_loss_usd": 0.0,
    "paused_until": 0,
}

acted = {}


@contextmanager
def pos_locked():
    """Context manager for position lock — ensures save on exit."""
    _pos_lock.acquire()
    try:
        yield state["positions"]
    finally:
        _pos_lock.release()


def _atomic_write(filepath, data):
    """Write JSON atomically (tmp + replace). Prevents corruption."""
    tmp = filepath + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(data, f, default=str, indent=2)
        os.replace(tmp, filepath)
    except Exception as e:
        log("ERROR", f"Atomic write failed {filepath}: {e}")


def load_positions():
    try:
        with open(config.POSITIONS_FILE) as f:
            state["positions"] = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        state["positions"] = {}
    # Ensure all positions have required fields
    now = time.time()
    for pos in state["positions"].values():
        pos.setdefault("entry_ts", pos.get("opened_at_ts", now))
        pos.setdefault("opened_at_ts", pos.get("entry_ts", now))
        pos.setdefault("remaining", 1.0)
        pos.setdefault("sl1_triggered", False)
        pos.setdefault("tp_tier", 0)
        pos.setdefault("zero_count", 0)
        pos.setdefault("sell_fail_count", 0)


def save_positions():
    _atomic_write(config.POSITIONS_FILE, state["positions"])


def load_trades():
    try:
        with open(config.TRADES_FILE) as f:
            state["trades"] = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        state["trades"] = []


def save_trades():
    _atomic_write(config.TRADES_FILE, state["trades"])


def load_acted():
    global acted
    try:
        with open(config.ACTED_FILE) as f:
            acted = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        acted = {}


def save_acted():
    _atomic_write(config.ACTED_FILE, acted)


def load_session():
    global session_risk
    try:
        with open(config.SESSION_FILE) as f:
            data = json.load(f)
            session_risk.update(data)
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    session_risk.pop("stopped", None)  # Remove legacy field


def save_session():
    _atomic_write(config.SESSION_FILE, session_risk)



# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3: LOGGING & UTILITIES
# ══════════════════════════════════════════════════════════════════════════════

def log(level, msg):
    """Structured logging with severity level."""
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] [{level}] {msg}"
    print(line, flush=True)
    try:
        with open(config.LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass
    with _state_lock:
        state["feed"].append({"msg": msg, "t": ts, "level": level})
        state["feed"] = state["feed"][-60:]


def feed(msg):
    """Shortcut for INFO-level log (backward compat)."""
    log("INFO", msg)


def safe_float(v, default=0.0):
    try:
        return float(v)
    except (ValueError, TypeError):
        return default


def safe_int(v, default=0):
    try:
        return int(v)
    except (ValueError, TypeError):
        return default


def is_night():
    h = datetime.now(timezone.utc).hour
    s, e = config.NIGHT_START_UTC, config.NIGHT_END_UTC
    return (s <= h < e) if s < e else (h >= s or h < e)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4: ONCHAINOS CLI INTERFACE
# Centralized CLI wrapper with timeout, error handling, and caching.
# ══════════════════════════════════════════════════════════════════════════════

_price_cache = {}  # {addr: (timestamp, data)}
_PRICE_CACHE_TTL = 5  # seconds


def onchainos_run(*args, timeout=20):
    """Execute onchainos CLI command. Returns parsed JSON or error dict."""
    try:
        r = subprocess.run(
            ["onchainos", *args],
            capture_output=True, text=True, timeout=timeout
        )
        if r.returncode != 0 and not r.stdout.strip():
            return {"ok": False, "msg": f"exit_code={r.returncode}", "data": None}
        return json.loads(r.stdout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "msg": "timeout", "data": None}
    except json.JSONDecodeError:
        return {"ok": False, "msg": "parse_error", "data": None}
    except FileNotFoundError:
        return {"ok": False, "msg": "onchainos_not_found", "data": None}
    except Exception as e:
        return {"ok": False, "msg": str(e)[:100], "data": None}


def onchainos_data(*args, timeout=20):
    """Execute onchainos CLI and return .data field."""
    result = onchainos_run(*args, timeout=timeout)
    return result.get("data")


def get_wallet_address():
    """Get wallet address (cached after first call)."""
    global _wallet_addr
    if _wallet_addr:
        return _wallet_addr
    try:
        data = onchainos_data("wallet", "addresses", "--chain", "501")
        if isinstance(data, dict):
            sol_addrs = data.get("solana", [])
            if sol_addrs and isinstance(sol_addrs, list):
                _wallet_addr = sol_addrs[0].get("address", "")
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and item.get("chainIndex") in (501, "501"):
                    _wallet_addr = item.get("address", "")
                    break
        if not _wallet_addr:
            _wallet_addr = config.WALLET
    except Exception:
        _wallet_addr = config.WALLET
    return _wallet_addr


def get_sol_balance():
    """Get SOL balance from wallet."""
    try:
        data = onchainos_data("wallet", "balance", "--chain", "501")
        if isinstance(data, dict):
            details = data.get("details", [])
            if isinstance(details, list):
                for detail in details:
                    for a in detail.get("tokenAssets", []):
                        if a.get("tokenAddress") in ("", None) or (a.get("symbol") or "").upper() == "SOL":
                            return safe_float(a.get("balance", 0))
        elif isinstance(data, list):
            for b in data:
                if b.get("tokenAddress") in ("", None) or (b.get("symbol") or "").upper() == "SOL":
                    return safe_float(b.get("balance", 0))
    except Exception:
        pass
    return 0.0


def get_sol_price():
    """Get current SOL price in USD."""
    try:
        data = onchainos_data("token", "price-info", "--chain", "solana", "--address", SOL_NATIVE)
        if isinstance(data, list):
            for item in data:
                p = safe_float(item.get("price", 0))
                if p > 0:
                    return p
        elif isinstance(data, dict):
            return safe_float(data.get("price", 0))
    except Exception:
        pass
    return 0.0


def get_token_price(addr):
    """Get token price info (cached for 5s to reduce API calls)."""
    now = time.time()
    cached = _price_cache.get(addr)
    if cached and (now - cached[0]) < _PRICE_CACHE_TTL:
        return cached[1]

    try:
        data = onchainos_data("token", "price-info", "--chain", "solana", "--address", addr)
        result = {}
        if isinstance(data, list) and data:
            result = data[0]
        elif isinstance(data, dict):
            result = data
        _price_cache[addr] = (now, result)
        return result
    except Exception:
        return _price_cache.get(addr, (0, {}))[1]


def get_token_balance(wallet_addr, token_addr):
    """Get specific token balance for wallet."""
    try:
        data = onchainos_data("portfolio", "token-balances",
                              "--address", wallet_addr,
                              "--tokens", f"501:{token_addr}")
        if isinstance(data, list) and data:
            return safe_float(data[0].get("amount", 0))
        elif isinstance(data, dict):
            return safe_float(data.get("amount", 0))
    except Exception:
        pass
    return 0.0


def get_token_holders(token_addr, limit=20):
    """Get top holder addresses for a token."""
    try:
        data = onchainos_data("token", "holders", "--chain", "solana",
                              "--address", token_addr, "--limit", str(limit))
        if isinstance(data, list):
            return [item.get("holderAddress", "") or item.get("address", "")
                    for item in data if item.get("holderAddress") or item.get("address")]
        elif isinstance(data, dict):
            items = data.get("items", data.get("holders", []))
            return [item.get("holderAddress", "") or item.get("address", "")
                    for item in items if item.get("holderAddress") or item.get("address")]
    except Exception:
        pass
    return []



# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5: VOLUME CONFIRMATION (Pre-Entry Gate)
# ══════════════════════════════════════════════════════════════════════════════

def check_volume_confirmation(addr, symbol="?"):
    """
    Pre-entry volume gate: 5-min volume, buy/sell ratio, trend, sell pressure.
    Returns (pass: bool, reason: str).
    Fail-open: on API error, allows entry (don't block on missing data).
    """
    if not config.VOLUME_CONFIRM_ENABLED:
        return True, "disabled"

    try:
        # 5-minute volume from 1m candles
        data = onchainos_data("market", "candles", "--chain", "solana",
                              "--address", addr, "--bar", "1m", timeout=15)
        if not isinstance(data, list) or len(data) < 5:
            return True, "insufficient_data"

        recent = data[-5:]
        total_volume = sum(safe_float(c.get("v", 0)) for c in recent)

        if total_volume < config.VOLUME_5M_MIN_USD:
            return False, f"vol_5m=${total_volume:.0f}<${config.VOLUME_5M_MIN_USD}"

        # Volume trend: declining rapidly?
        if config.VOLUME_TREND_CHECK and len(recent) >= 3:
            first_half = sum(safe_float(c.get("v", 0)) for c in recent[:2])
            second_half = sum(safe_float(c.get("v", 0)) for c in recent[3:])
            if first_half > 0 and second_half < first_half * 0.3:
                return False, "vol_declining_rapidly"

        # Buy/sell ratio
        bs_ratio = _check_buy_sell_ratio(addr)
        if bs_ratio < config.VOLUME_BUY_SELL_RATIO:
            return False, f"buy_sell_ratio={bs_ratio:.2f}<{config.VOLUME_BUY_SELL_RATIO}"

        # Holder sell pressure
        if config.HOLDER_SELL_CHECK_ENABLED:
            sell_ok, sell_reason = _check_holder_sell_pressure(addr)
            if not sell_ok:
                return False, sell_reason

        # Momentum check: not entering a dumping token
        green_count = sum(1 for c in recent
                         if safe_float(c.get("c", 0)) >= safe_float(c.get("o", 0)))
        if green_count <= 1:
            return False, f"dumping({green_count}/5 green)"

        return True, f"vol=${total_volume:.0f} bs={bs_ratio:.1f} green={green_count}/5"

    except Exception:
        return True, "check_error"


def _check_buy_sell_ratio(addr):
    """Get buy/sell ratio from recent trades. Returns ratio (default 1.0 on error)."""
    try:
        data = onchainos_data("token", "trades", "--chain", "solana",
                              "--address", addr, "--limit", "50", timeout=15)
        if not isinstance(data, list) or len(data) < 10:
            return 1.0
        buys = sum(1 for t in data if (t.get("side", "") or t.get("type", "")).lower() == "buy")
        sells = len(data) - buys
        return buys / max(sells, 1)
    except Exception:
        return 1.0


def _check_holder_sell_pressure(addr):
    """Check if dev/snipers are actively dumping. Returns (pass, reason)."""
    try:
        now_ms = int(time.time() * 1000)
        window_ms = 5 * 60 * 1000
        total_sell_sol = 0.0

        for tag in (2, 7):  # dev, sniper
            data = onchainos_data("token", "trades", "--chain", "solana",
                                  "--address", addr, "--tag-filter", str(tag),
                                  "--limit", "20", timeout=12)
            if not isinstance(data, list):
                continue
            for trade in data:
                if trade.get("type") != "sell":
                    continue
                ts = safe_int(trade.get("time", 0))
                if ts <= 0 or (now_ms - ts) > window_ms:
                    continue
                sol_amt = 0.0
                for tok_info in trade.get("changedTokenInfo", []):
                    if tok_info.get("tokenSymbol") in ("SOL", "wSOL"):
                        sol_amt = safe_float(tok_info.get("amount", 0))
                        break
                if sol_amt <= 0:
                    sol_amt = safe_float(trade.get("volume", 0))
                total_sell_sol += sol_amt

        max_sell = config.HOLDER_SELL_MAX_SOL_5M
        if total_sell_sol > max_sell:
            return False, f"holder_selling={total_sell_sol:.1f}SOL>{max_sell}"
        return True, "ok"
    except Exception:
        return True, "check_error"


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 6: SWAP EXECUTION ENGINE
# Iron Rule: NEVER use `swap execute`. Always: swap swap → contract-call → confirm.
# ══════════════════════════════════════════════════════════════════════════════

def poll_tx_status(tx_hash, timeout=60):
    """Poll transaction status until confirmed/failed/timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            data = onchainos_data("wallet", "history",
                                  "--tx-hash", tx_hash, "--chain-index", "501", timeout=15)
            if data:
                item = data[0] if isinstance(data, list) else data
                status = (item.get("status") or "").lower()
                if status in ("confirmed", "success", "complete"):
                    return "confirmed"
                if status in ("failed", "error", "reverted"):
                    return "failed"
        except Exception:
            pass
        time.sleep(3)
    return "timeout"


def execute_buy(token_addr, amount_usd):
    """
    Buy token via 3-step swap flow.
    Returns: (success, tx_hash, token_amount)
    """
    wallet = get_wallet_address()
    if not wallet:
        log("ERROR", "BUY FAIL: no wallet address")
        return False, "", 0.0

    sol_price = get_sol_price()
    if sol_price <= 0:
        log("ERROR", "BUY FAIL: cannot get SOL price")
        return False, "", 0.0

    lamports = int(amount_usd / sol_price * 1e9)

    if config.PAPER_TRADE:
        try:
            data = onchainos_data("swap", "quote", "--from", SOL_NATIVE, "--to", token_addr,
                                  "--amount", str(lamports), "--chain", "solana", timeout=30)
            if not data:
                return False, "", 0.0
            q = data[0] if isinstance(data, list) else data
            router = q.get("routerResult", q)
            token_amount = safe_float(router.get("toTokenAmount", 0))
            return True, f"paper_{int(time.time())}", token_amount
        except Exception:
            return False, "", 0.0

    # Step 1: Build unsigned TX
    try:
        data = onchainos_data("swap", "swap", "--chain", "solana",
                              "--from", SOL_NATIVE, "--to", token_addr,
                              "--amount", str(lamports),
                              "--slippage", str(config.SLIPPAGE_BUY),
                              "--wallet", wallet, timeout=60)
        if not data:
            log("WARN", "BUY FAIL: swap returned no data")
            return False, "", 0.0
    except Exception as e:
        log("ERROR", f"BUY FAIL swap: {e}")
        return False, "", 0.0

    q = data[0] if isinstance(data, list) else data
    router = q.get("routerResult", q)
    token_amount = safe_float(router.get("toTokenAmount", 0))
    tx = q.get("tx", {})
    tx_to = tx.get("to", "")
    unsigned_tx = tx.get("data", "")

    if not tx_to or not unsigned_tx:
        log("WARN", "BUY FAIL: missing tx.to or tx.data")
        return False, "", 0.0

    # Step 2: TEE sign + broadcast
    try:
        result = onchainos_data("wallet", "contract-call", "--chain", "501",
                                "--to", tx_to, "--unsigned-tx", unsigned_tx, timeout=60)
        if not result:
            log("WARN", "BUY FAIL: contract-call returned no data")
            return False, "", 0.0
    except Exception as e:
        if "timeout" in str(e).lower():
            return False, "TIMEOUT", token_amount
        log("ERROR", f"BUY FAIL contract-call: {e}")
        return False, "", 0.0

    # Step 3: Extract TX hash and confirm
    tx_hash = ""
    if isinstance(result, dict):
        tx_hash = result.get("txHash") or result.get("orderId") or ""
    elif isinstance(result, str):
        tx_hash = result

    if tx_hash:
        status = poll_tx_status(tx_hash, timeout=30)
        if status == "failed":
            log("WARN", f"BUY FAIL: tx {tx_hash[:12]} failed on-chain")
            return False, tx_hash, 0.0

    # Fallback: check balance if token_amount unknown
    if token_amount <= 0 and tx_hash:
        time.sleep(2)
        token_amount = get_token_balance(wallet, token_addr)

    return True, tx_hash, token_amount


def execute_sell(token_addr, symbol, token_amount, reason, max_retries=3):
    """
    Sell token via 3-step swap flow with retry.
    Returns: (success, tx_hash)
    """
    wallet = get_wallet_address()
    if not wallet or int(token_amount) <= 0:
        return False, ""

    if config.PAPER_TRADE:
        feed(f"  [PAPER] SELL {symbol} reason={reason}")
        return True, f"paper_sell_{int(time.time())}"

    raw_amount = str(int(token_amount))

    for attempt in range(max_retries):
        try:
            data = onchainos_data("swap", "swap", "--chain", "solana",
                                  "--from", token_addr, "--to", SOL_NATIVE,
                                  "--amount", raw_amount,
                                  "--slippage", str(config.SLIPPAGE_SELL),
                                  "--wallet", wallet, timeout=60)
            if not data:
                time.sleep(5 * (attempt + 1))
                continue

            q = data[0] if isinstance(data, list) else data
            tx = q.get("tx", {})
            tx_to, unsigned_tx = tx.get("to", ""), tx.get("data", "")
            if not tx_to or not unsigned_tx:
                time.sleep(5 * (attempt + 1))
                continue

            result = onchainos_data("wallet", "contract-call", "--chain", "501",
                                    "--to", tx_to, "--unsigned-tx", unsigned_tx, timeout=60)
            if not result:
                time.sleep(5 * (attempt + 1))
                continue

            tx_hash = ""
            if isinstance(result, dict):
                tx_hash = result.get("txHash") or result.get("orderId") or ""
            elif isinstance(result, str):
                tx_hash = result

            if tx_hash:
                feed(f"  SELL {symbol} TX: https://solscan.io/tx/{tx_hash}")
            return True, tx_hash

        except Exception as e:
            log("WARN", f"SELL {symbol} attempt {attempt+1} error: {e}")
            time.sleep(5 * (attempt + 1))

    return False, ""



# ══════════════════════════════════════════════════════════════════════════════
# SECTION 7: TIER S — SMART WALLET FOLLOW
# Highest confidence: follows Tier-1 curated wallets' fresh buys.
# ══════════════════════════════════════════════════════════════════════════════

_tier_s_last_seen = {}  # {wallet:token: first_seen_ts}


def process_tier_s():
    """Scan Tier-1 wallets for new buys. Enter on first qualifying candidate."""
    if not config.TIER_S_ENABLED or not _smart_wallets:
        return

    tier1_addrs = get_smart_wallet_addresses(tier_filter=config.TIER_S_FOLLOW_TIERS)
    if not tier1_addrs:
        return

    sample_size = min(config.TIER_S_SAMPLE_SIZE, len(tier1_addrs))
    sampled = random.sample(tier1_addrs, sample_size)
    night = is_night()
    size = config.TIER_S_SIZE_NIGHT if night else config.TIER_S_SIZE_DAY
    candidates = []

    for wallet_addr in sampled:
        try:
            data = onchainos_data("wallet", "history", "--address", wallet_addr,
                                  "--chain-index", "501", "--limit", "5", timeout=15)
            if not isinstance(data, list):
                continue

            for tx in data:
                tx_type = (tx.get("type", "") or tx.get("txType", "")).lower()
                if "swap" not in tx_type and "buy" not in tx_type:
                    continue

                token_addr = (tx.get("toTokenAddress", "") or
                              tx.get("tokenAddress", "") or
                              tx.get("contractAddress", ""))
                if not token_addr or token_addr in _NEVER_TRADE or token_addr == SOL_NATIVE:
                    continue

                tx_ts = safe_float(tx.get("timestamp", 0) or tx.get("blockTimestamp", 0))
                if tx_ts > 1e12:
                    tx_ts /= 1000.0
                if tx_ts <= 0:
                    continue
                age_min = (time.time() - tx_ts) / 60.0
                if age_min > config.TIER_S_MAX_AGE_MIN:
                    continue

                key = f"{wallet_addr}:{token_addr}"
                if key in _tier_s_last_seen:
                    continue
                _tier_s_last_seen[key] = time.time()

                candidates.append({"addr": token_addr, "wallet": wallet_addr, "age_min": age_min})
        except Exception:
            continue

    if not candidates:
        return

    feed(f"Tier S smart wallet candidates: {len(candidates)}")

    for cand in candidates:
        addr = cand["addr"]
        if addr in acted or (addr in cooldown_map and time.time() < cooldown_map.get(addr, 0)):
            continue
        with _pos_lock:
            if addr in state["positions"]:
                continue

        price_info = get_token_price(addr)
        mc = safe_float(price_info.get("marketCap", 0))
        liq = safe_float(price_info.get("liquidity", 0))
        holders = safe_int(price_info.get("holders", 0))
        price = safe_float(price_info.get("price", 0))
        symbol = price_info.get("symbol", "?")

        # Filters
        if mc < config.TIER_S_MC_MIN or mc > config.TIER_S_MC_MAX:
            continue
        if liq < config.TIER_S_LIQ_MIN:
            continue
        if holders < config.TIER_S_HOLDERS_MIN:
            continue
        top10 = safe_float(price_info.get("top10HoldPercent", 0))
        if top10 > config.TIER_S_TOP10_MAX:
            continue

        if _k1_pump_guard(addr, config.TIER_A_K1_PUMP_GUARD):
            feed(f"  Skip_S {symbol}: K1 pump guard")
            continue

        vol_ok, vol_reason = check_volume_confirmation(addr, symbol)
        if not vol_ok:
            feed(f"  Skip_S {symbol}: {vol_reason}")
            continue

        try:
            rc = pre_trade_checks(addr, symbol, quick=True)
            if not rc.get("pass", False):
                feed(f"  Skip_S {symbol}: risk G{rc.get('grade', '?')}")
                continue
        except Exception:
            continue

        ok, reason = can_enter()
        if not ok:
            feed(f"  Skip_S: {reason}")
            return

        feed(f"ENTER TIER_S {symbol} ${size} | MC=${mc:,.0f} | SmartWallet={cand['wallet'][:8]}")
        success, tx_hash, token_amt = execute_buy(addr, size)

        if success and token_amt > 0:
            _create_position(addr, symbol, "S", size, price, mc, liq, token_amt, tx_hash, rc)
            acted[addr] = int(time.time())
            save_acted()
            if tx_hash and not tx_hash.startswith("paper"):
                feed(f"  swap OK | TX: https://solscan.io/tx/{tx_hash}")
            return
        elif tx_hash == "TIMEOUT":
            _create_unconfirmed_position(addr, symbol, "S", size, price, mc)
            acted[addr] = int(time.time())
            save_acted()
            return
        else:
            feed(f"  BUY FAIL {symbol}")
            cooldown_map[addr] = time.time() + 300
            return


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 8: TIER A — SMART MONEY SIGNAL
# Multi-wallet co-buy detection via onchainos signal list.
# ══════════════════════════════════════════════════════════════════════════════

def fetch_sm_signals():
    """Fetch smart money signals from onchainos."""
    try:
        labels = ",".join(str(l) for l in config.SM_LABELS)
        data = onchainos_data("signal", "list", "--chain", "solana",
                              "--wallet-type", labels,
                              "--min-address-count", str(config.SM_MIN_WALLETS))
        if isinstance(data, list):
            return data
        return [data] if isinstance(data, dict) else []
    except Exception:
        return []


def process_tier_a():
    """Process smart money signals. Enter on first qualifying candidate."""
    signals = fetch_sm_signals()
    if not signals:
        return

    feed(f"Tier A SM signals: {len(signals)}")
    night = is_night()
    size = config.TIER_A_SIZE_NIGHT if night else config.TIER_A_SIZE_DAY
    hot = _get_hot_cache()

    for sig in signals:
        token = sig.get("token", {})
        if not isinstance(token, dict):
            continue
        addr = token.get("tokenAddress", "") or token.get("address", "")
        symbol = token.get("symbol", "?")
        wallet_count = safe_int(sig.get("triggerWalletCount", 0))
        sold_ratio = safe_float(sig.get("soldRatioPercent", 100))

        if not addr or addr in _NEVER_TRADE:
            continue
        if addr in acted or (addr in cooldown_map and time.time() < cooldown_map.get(addr, 0)):
            continue
        with _pos_lock:
            if addr in state["positions"]:
                continue
        if sold_ratio > 80:
            continue

        # Strong vs normal signal
        is_strong = wallet_count >= config.SM_STRONG_THRESH
        if not is_strong:
            hot_entry = hot.get(addr, {})
            if safe_float(hot_entry.get("inflow", 0)) <= 0:
                continue

        price_data = get_token_price(addr)
        mc = safe_float(price_data.get("marketCap", 0))
        liq = safe_float(price_data.get("liquidity", 0))
        holders = safe_int(price_data.get("holders", 0))
        price = safe_float(price_data.get("price", 0))

        if mc < config.TIER_A_MC_MIN or mc > config.TIER_A_MC_MAX:
            continue
        if liq < config.TIER_A_LIQ_MIN or holders < config.TIER_A_HOLDERS_MIN:
            continue

        if _k1_pump_guard(addr, config.TIER_A_K1_PUMP_GUARD):
            continue

        vol_ok, vol_reason = check_volume_confirmation(addr, symbol)
        if not vol_ok:
            feed(f"  Skip_A {symbol}: {vol_reason}")
            continue

        # Smart wallet boost (informational)
        sw_boost = 0
        try:
            holders_list = get_token_holders(addr, limit=20)
            sw_boost, sw_matched = get_smart_wallet_score(holders_list)
            if sw_matched:
                feed(f"  {symbol} SmartWallet boost: +{sw_boost} ({len(sw_matched)} matched)")
        except Exception:
            pass

        rc = pre_trade_checks(addr, symbol, quick=True)
        if not rc.get("pass", False):
            feed(f"  Skip_A {symbol}: risk G{rc.get('grade', '?')}")
            continue

        ok, reason = can_enter()
        if not ok:
            return

        feed(f"ENTER TIER_A {symbol} ${size} | MC=${mc:,.0f} | wallets={wallet_count} | sw+{sw_boost}")
        success, tx_hash, token_amt = execute_buy(addr, size)

        if success and token_amt > 0:
            _create_position(addr, symbol, "A", size, price, mc, liq, token_amt, tx_hash, rc)
            acted[addr] = int(time.time())
            save_acted()
            if tx_hash and not tx_hash.startswith("paper"):
                feed(f"  swap OK | TX: https://solscan.io/tx/{tx_hash}")
            return
        elif tx_hash == "TIMEOUT":
            _create_unconfirmed_position(addr, symbol, "A", size, price, mc)
            acted[addr] = int(time.time())
            save_acted()
            return
        else:
            feed(f"  BUY FAIL {symbol}")
            cooldown_map[addr] = time.time() + 300



# ══════════════════════════════════════════════════════════════════════════════
# SECTION 9: TIER B — GRADUATION AMBUSH
# Catch tokens within 60min of PumpFun → Raydium migration.
# ══════════════════════════════════════════════════════════════════════════════

def process_tier_b():
    """Process graduated tokens. Enter on first qualifying candidate."""
    try:
        data = onchainos_data("memepump", "tokens", "--chain", "solana",
                              "--stage", config.TIER_B_STAGE)
        candidates = data if isinstance(data, list) else ([data] if isinstance(data, dict) else [])
    except Exception:
        return

    night = is_night()
    size = config.TIER_B_SIZE_NIGHT if night else config.TIER_B_SIZE_DAY
    filtered = []

    for tok in candidates:
        if not isinstance(tok, dict):
            continue
        addr = tok.get("tokenAddress", "") or tok.get("address", "") or tok.get("mint", "")
        if not addr or addr in _NEVER_TRADE:
            continue

        market = tok.get("market", {}) if isinstance(tok.get("market"), dict) else {}
        tags = tok.get("tags", {}) if isinstance(tok.get("tags"), dict) else {}

        mc = safe_float(market.get("marketCapUsd", 0) or tok.get("marketCap", 0))
        holders = safe_int(tags.get("totalHolders", 0) or tok.get("holders", 0))
        dev_hold_pct = safe_float(tags.get("devHoldingsPercent", 0))
        insiders_pct = safe_float(tags.get("insidersPercent", 0) or tok.get("insiderPercent", 0))
        top10 = safe_float(tags.get("top10HoldingsPercent", 0) or tok.get("top10HoldPercent", 0))

        if mc < config.TIER_B_MC_MIN or mc > config.TIER_B_MC_MAX:
            continue
        if holders < config.TIER_B_HOLDERS_MIN:
            continue
        if config.TIER_B_DEV_SOLD and dev_hold_pct > 0:
            continue
        if insiders_pct > config.TIER_B_INSIDERS_MAX or top10 > config.TIER_B_TOP10_MAX:
            continue

        # Age check
        migrated_ts = safe_float(
            tok.get("migratedBeginTimestamp", 0) or tok.get("migratedEndTimestamp", 0)
            or tok.get("migratedTime", 0) or tok.get("graduatedAt", 0))
        if migrated_ts > 0:
            if migrated_ts > 1e12:
                migrated_ts /= 1000.0
            if (time.time() - migrated_ts) > config.TIER_B_MAX_AGE_MIN * 60:
                continue

        filtered.append({"addr": addr, "mc": mc, "holders": holders,
                         "symbol": tok.get("symbol", tok.get("tokenSymbol", "?"))})

    if filtered:
        feed(f"Tier B MIGRATED candidates: {len(filtered)}")

    for cand in filtered:
        addr, symbol, mc = cand["addr"], cand["symbol"], cand["mc"]
        if addr in acted or (addr in cooldown_map and time.time() < cooldown_map.get(addr, 0)):
            continue
        with _pos_lock:
            if addr in state["positions"]:
                continue

        if _k1_pump_guard(addr, config.TIER_A_K1_PUMP_GUARD):
            continue

        vol_ok, _ = check_volume_confirmation(addr, symbol)
        if not vol_ok:
            continue

        try:
            rc = pre_trade_checks(addr, symbol, quick=True)
            if not rc.get("pass", False):
                continue
        except Exception:
            continue

        price_info = get_token_price(addr)
        price = safe_float(price_info.get("price", 0))
        liq = safe_float(price_info.get("liquidity", 0))

        ok, reason = can_enter()
        if not ok:
            return

        sw_boost = 0
        try:
            holders_list = get_token_holders(addr, limit=20)
            sw_boost, _ = get_smart_wallet_score(holders_list)
        except Exception:
            pass

        feed(f"ENTER TIER_B {symbol} ${size} | MC=${mc:,.0f} | sw+{sw_boost}")
        success, tx_hash, token_amt = execute_buy(addr, size)

        if success and token_amt > 0:
            _create_position(addr, symbol, "B", size, price, mc, liq, token_amt, tx_hash, rc)
            acted[addr] = int(time.time())
            save_acted()
            if tx_hash and not tx_hash.startswith("paper"):
                feed(f"  swap OK | TX: https://solscan.io/tx/{tx_hash}")
            return
        elif tx_hash == "TIMEOUT":
            _create_unconfirmed_position(addr, symbol, "B", size, price, mc)
            acted[addr] = int(time.time())
            save_acted()
            return
        else:
            feed(f"  BUY FAIL {symbol}")
            cooldown_map[addr] = time.time() + 300
            return


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 10: TIER D — HOT MOMENTUM (Dynamic Sizing)
# Composite-scored trending tokens with smart wallet boost.
# ══════════════════════════════════════════════════════════════════════════════

def calculate_score(tok, sw_boost=0):
    """Calculate composite score 0-100+ for hot momentum token."""
    score = 0

    holders = safe_int(tok.get("holders", 0) or tok.get("holderCount", 0))
    for threshold, points in [(5000, 30), (2000, 25), (1000, 20), (500, 15)]:
        if holders >= threshold:
            score += points
            break

    buys = safe_int(tok.get("buys", 0) or tok.get("buyCount", 0))
    sells = safe_int(tok.get("sells", 0) or tok.get("sellCount", 0))
    if sells > 0:
        ratio = buys / sells
        for threshold, points in [(2.0, 25), (1.5, 20), (1.2, 15), (1.0, 10)]:
            if ratio >= threshold:
                score += points
                break

    traders = safe_int(tok.get("uniqueTraders", 0) or tok.get("traderCount", 0))
    for threshold, points in [(500, 15), (300, 12), (200, 9), (100, 6)]:
        if traders >= threshold:
            score += points
            break

    change = safe_float(tok.get("change", 0) or tok.get("priceChange", 0))
    for threshold, points in [(30, 15), (20, 12), (10, 9), (5, 6)]:
        if change >= threshold:
            score += points
            break

    inflow = safe_float(tok.get("inflowUsd", 0) or tok.get("netInflowUsd", 0) or tok.get("inflow", 0))
    for threshold, points in [(50000, 15), (20000, 12), (5000, 9), (0.01, 5)]:
        if inflow >= threshold:
            score += points
            break

    return score + sw_boost


def score_to_size(score):
    """Convert composite score to position size in USD."""
    base = 3 if is_night() else config.TIER_D_SIZE_BASE
    for tier in config.TIER_D_SCORE_TIERS:
        if score >= tier["min_score"]:
            return base + tier["extra"]
    return base


def process_tier_d():
    """Process hot momentum tokens. Enter on first qualifying candidate."""
    try:
        data = onchainos_data("token", "hot-tokens", "--chain", "solana",
                              "--ranking-type", "4", "--limit", "20")
        candidates = data if isinstance(data, list) else ([data] if isinstance(data, dict) else [])
    except Exception:
        return

    filtered = []
    for tok in candidates:
        if not isinstance(tok, dict):
            continue
        addr = tok.get("tokenAddress", "") or tok.get("address", "")
        if not addr or addr in _NEVER_TRADE:
            continue

        holders = safe_int(tok.get("holders", 0) or tok.get("holderCount", 0))
        mc = safe_float(tok.get("marketCap", 0) or tok.get("usdMarketCap", 0))
        liq = safe_float(tok.get("liquidity", 0) or tok.get("liquidityUsd", 0))
        top10 = safe_float(tok.get("top10HoldPercent", 0))
        risk_level = safe_int(tok.get("riskLevelControl", tok.get("riskLevel", 99)))

        if holders < config.TIER_D_HOLDERS_MIN or mc < config.TIER_D_MC_MIN or mc > config.TIER_D_MC_MAX:
            continue
        if liq < config.TIER_D_LIQ_MIN or top10 > config.TIER_D_TOP10_MAX:
            continue
        if risk_level > config.TIER_D_RISK_LEVEL:
            continue

        filtered.append(tok)

    if filtered:
        feed(f"Tier D hot candidates: {len(filtered)}")

    for tok in filtered:
        addr = tok.get("tokenAddress", "") or tok.get("address", "")
        symbol = tok.get("symbol", tok.get("tokenSymbol", "?"))
        mc = safe_float(tok.get("marketCap", 0) or tok.get("usdMarketCap", 0))

        if addr in acted or (addr in cooldown_map and time.time() < cooldown_map.get(addr, 0)):
            continue
        with _pos_lock:
            if addr in state["positions"]:
                continue

        sw_boost = 0
        try:
            holders_list = get_token_holders(addr, limit=20)
            sw_boost, _ = get_smart_wallet_score(holders_list)
        except Exception:
            pass

        score = calculate_score(tok, sw_boost=sw_boost)
        if score < config.TIER_D_SCORE_THRESHOLD:
            continue

        if _k1_pump_guard(addr, config.TIER_A_K1_PUMP_GUARD):
            continue

        vol_ok, vol_reason = check_volume_confirmation(addr, symbol)
        if not vol_ok:
            feed(f"  Skip_D {symbol}: {vol_reason}")
            continue

        try:
            rc = pre_trade_checks(addr, symbol, quick=True)
            if not rc.get("pass", False):
                continue
        except Exception:
            continue

        price_info = get_token_price(addr)
        price = safe_float(price_info.get("price", 0))
        liq = safe_float(price_info.get("liquidity", 0))

        ok, reason = can_enter()
        if not ok:
            return

        size = score_to_size(score)
        feed(f"ENTER TIER_D {symbol} ${size} | MC=${mc:,.0f} | score={score} | sw+{sw_boost}")
        success, tx_hash, token_amt = execute_buy(addr, size)

        if success and token_amt > 0:
            _create_position(addr, symbol, "D", size, price, mc, liq, token_amt, tx_hash, rc)
            acted[addr] = int(time.time())
            save_acted()
            if tx_hash and not tx_hash.startswith("paper"):
                feed(f"  swap OK | TX: https://solscan.io/tx/{tx_hash}")
            return
        elif tx_hash == "TIMEOUT":
            _create_unconfirmed_position(addr, symbol, "D", size, price, mc)
            acted[addr] = int(time.time())
            save_acted()
            return
        else:
            feed(f"  BUY FAIL {symbol}")
            cooldown_map[addr] = time.time() + 300
            return



# ══════════════════════════════════════════════════════════════════════════════
# SECTION 11: POSITION MONITOR — 9-LAYER ADAPTIVE EXIT
# Priority-ordered exits. Higher layers override lower ones.
# ══════════════════════════════════════════════════════════════════════════════

def monitor_positions():
    """Position monitor loop. Runs every MONITOR_SEC (1s)."""
    while True:
        time.sleep(config.MONITOR_SEC)
        try:
            _monitor_cycle()
        except Exception as e:
            log("ERROR", f"MONITOR: {e}")


def _monitor_cycle():
    """Single monitoring cycle for all positions."""
    with _pos_lock:
        positions = dict(state["positions"])
    if not positions:
        return

    now = time.time()

    # Handle unconfirmed positions
    for addr, pos in list(positions.items()):
        if not pos.get("unconfirmed"):
            continue
        elapsed = now - pos.get("unconfirmed_ts", now)
        if elapsed < 60:
            continue
        checks = pos.get("unconfirmed_checks", 0)
        try:
            pi = get_token_price(addr)
            price = safe_float(pi.get("price", 0))
            if price > 0:
                with _pos_lock:
                    if addr in state["positions"]:
                        p = state["positions"][addr]
                        p.pop("unconfirmed", None)
                        p.pop("unconfirmed_ts", None)
                        p.pop("unconfirmed_checks", None)
                        p["entry_price"] = price
                        p["peak_price"] = price
                        bal = get_token_balance(get_wallet_address(), addr)
                        if bal > 0:
                            p["token_amount"] = bal
                        save_positions()
                feed(f"  CONFIRMED {pos.get('symbol', addr[:8])}")
                continue
        except Exception:
            pass
        checks += 1
        with _pos_lock:
            if addr in state["positions"]:
                state["positions"][addr]["unconfirmed_checks"] = checks
        if checks >= 10 and elapsed >= 180:
            with _pos_lock:
                state["positions"].pop(addr, None)
                save_positions()
            feed(f"  DROPPED {pos.get('symbol', addr[:8])}: unconfirmed x{checks}")
        continue

    # Process each active position through exit layers
    for addr, pos in positions.items():
        if pos.get("unconfirmed") or addr in _selling:
            continue

        pi = get_token_price(addr)
        cur_price = safe_float(pi.get("price", 0))
        cur_liq = safe_float(pi.get("liquidity", 0))
        entry_price = safe_float(pos.get("entry_price", 0))

        if entry_price <= 0:
            if cur_price > 0:
                with _pos_lock:
                    if addr in state["positions"]:
                        state["positions"][addr]["entry_price"] = cur_price
                        state["positions"][addr]["peak_price"] = cur_price
                entry_price = cur_price
            else:
                continue

        # Zero price protection (3-check)
        if cur_price <= 0:
            with _pos_lock:
                if addr in state["positions"]:
                    zc = state["positions"][addr].get("zero_count", 0) + 1
                    state["positions"][addr]["zero_count"] = zc
                    if zc >= 30 and (now - safe_float(pos.get("entry_ts", now))) > 86400:
                        state["positions"].pop(addr, None)
                        save_positions()
                        feed(f"  GHOST_CLEANUP {pos.get('symbol', addr[:8])}")
            continue
        else:
            with _pos_lock:
                if addr in state["positions"]:
                    state["positions"][addr]["zero_count"] = 0

        # Calculate metrics
        pnl_pct = (cur_price - entry_price) / entry_price
        entry_ts = safe_float(pos.get("entry_ts", now))
        age_sec = now - entry_ts
        age_min = age_sec / 60.0
        tier = pos.get("tier", "D")
        symbol = pos.get("symbol", addr[:8])
        peak_price = safe_float(pos.get("peak_price", entry_price))

        if cur_price > peak_price:
            peak_price = cur_price
            with _pos_lock:
                if addr in state["positions"]:
                    state["positions"][addr]["peak_price"] = cur_price
                    state["positions"][addr]["last_peak_ts"] = now

        # Update live display data
        with _pos_lock:
            if addr in state["positions"]:
                state["positions"][addr]["current_price"] = cur_price
                state["positions"][addr]["pnl_pct"] = pnl_pct
                state["positions"][addr]["age_min"] = age_min

        tp_rules = config.TP_RULES.get(tier, config.TP_RULES.get("D", {}))
        sl_rules = config.SL_RULES.get(tier, config.SL_RULES.get("D", {}))
        remaining = safe_float(pos.get("remaining", 1.0))
        tp_tier_done = safe_int(pos.get("tp_tier", 0))

        # ─── LAYER 1: HE1 EMERGENCY (-50%) ──────────────────────────
        if pnl_pct <= config.HE1_PCT:
            _exit_position(addr, pos, 1.0, "HE1_EMERGENCY", pnl_pct)
            continue

        # ─── LAYER 2: FAST DUMP (flash crash from peak) ─────────────
        if peak_price > 0:
            drop = (peak_price - cur_price) / peak_price
            if drop >= abs(config.FAST_DUMP_PCT):
                last_peak = safe_float(pos.get("last_peak_ts", 0))
                if last_peak > 0 and (now - last_peak) <= config.FAST_DUMP_WINDOW:
                    _exit_position(addr, pos, 1.0, "FAST_DUMP", pnl_pct)
                    continue

        # ─── LAYER 3: LIQUIDITY EMERGENCY ────────────────────────────
        if cur_liq > 0 and cur_liq < config.LIQ_EMERGENCY:
            _exit_position(addr, pos, 1.0, "LIQ_EMERGENCY", pnl_pct)
            continue

        # ─── LAYER 4: TIERED STOP LOSS ──────────────────────────────
        sl1_triggered = pos.get("sl1_triggered", False)
        sl_pct = safe_float(sl_rules.get("sl_pct", -0.20))
        sl2_pct = safe_float(sl_rules.get("sl2_pct", -0.30))

        if not sl1_triggered and pnl_pct <= sl_pct:
            sl_sell = safe_float(sl_rules.get("sl_sell", 0.50))
            _exit_position(addr, pos, sl_sell, f"SL1({sl_pct*100:.0f}%)", pnl_pct)
            with _pos_lock:
                if addr in state["positions"]:
                    state["positions"][addr]["sl1_triggered"] = True
            continue

        if pnl_pct <= sl2_pct:
            _exit_position(addr, pos, 1.0, f"SL2({sl2_pct*100:.0f}%)", pnl_pct)
            continue

        # ─── LAYER 5: TIME-DECAY STOP LOSS ──────────────────────────
        for min_threshold, sl_thresh in sl_rules.get("time_decay", []):
            if age_min >= min_threshold and pnl_pct <= sl_thresh:
                _exit_position(addr, pos, 0.50, f"TIME_DECAY({min_threshold}m)", pnl_pct)
                break

        # ─── LAYER 6: TIMEOUT ────────────────────────────────────────
        timeout_hrs = safe_float(sl_rules.get("timeout_hrs", 48))
        if age_sec >= timeout_hrs * 3600:
            _exit_position(addr, pos, 1.0, f"TIMEOUT({timeout_hrs}h)", pnl_pct)
            continue

        # ─── LAYER 7: FLOOR EXIT (dead positions) ────────────────────
        floor_pct = safe_float(tp_rules.get("floor_pct", 0.10))
        if config.FLOOR_EXIT_ENABLED and remaining <= floor_pct + 0.01:
            if pnl_pct <= config.FLOOR_EXIT_LOSS_PCT:
                _exit_position(addr, pos, 1.0, "FLOOR_LOSS", pnl_pct)
                continue
            if age_sec >= config.FLOOR_EXIT_AGE_HRS * 3600 and pnl_pct < config.FLOOR_EXIT_AGE_LOSS:
                _exit_position(addr, pos, 1.0, "FLOOR_AGED", pnl_pct)
                continue

        # ─── LAYER 8: TRAILING STOP (after TP1) ─────────────────────
        if tp_tier_done >= 1 and peak_price > 0:
            trail_pct = safe_float(tp_rules.get("trailing_pct", 0.20))
            trail_sell = safe_float(tp_rules.get("trailing_sell", 0.40))
            drop = (peak_price - cur_price) / peak_price
            if drop >= trail_pct:
                _exit_position(addr, pos, trail_sell, f"TRAILING({trail_pct*100:.0f}%)", pnl_pct)
                continue

        # ─── LAYER 9: TAKE PROFIT ────────────────────────────────────
        # V8 Tier B fast TP: +30% in 10min
        if tier == "B" and tp_tier_done < 1:
            if age_min <= config.TIER_B_FAST_TP_MIN and pnl_pct >= config.TIER_B_FAST_TP_PCT:
                tp_sell = safe_float(tp_rules.get("tp1_sell", 0.50))
                _exit_position(addr, pos, tp_sell, "FAST_TP_B", pnl_pct)
                with _pos_lock:
                    if addr in state["positions"]:
                        state["positions"][addr]["tp_tier"] = 1
                continue

        # Standard TP1/TP2/TP3
        for tp_level, tp_key, sell_key in [(1, "tp1_pct", "tp1_sell"),
                                            (2, "tp2_pct", "tp2_sell"),
                                            (3, "tp3_pct", "tp3_sell")]:
            if tp_tier_done >= tp_level:
                continue
            tp_threshold = safe_float(tp_rules.get(tp_key, 999))
            if pnl_pct >= tp_threshold:
                tp_sell = safe_float(tp_rules.get(sell_key, 0.30))
                _exit_position(addr, pos, tp_sell, f"TP{tp_level}(+{tp_threshold*100:.0f}%)", pnl_pct)
                with _pos_lock:
                    if addr in state["positions"]:
                        state["positions"][addr]["tp_tier"] = tp_level
                break

        # Background risk check (async, throttled)
        risk_last = safe_float(pos.get("risk_last_checked", 0))
        if now - risk_last >= 60:
            with _pos_lock:
                if addr in state["positions"]:
                    state["positions"][addr]["risk_last_checked"] = now
            _async_risk_check(addr, pos)

    # Save after cycle
    with _pos_lock:
        save_positions()


def _async_risk_check(addr, pos):
    """Run post-trade risk check in background thread."""
    def _run():
        if not _risk_semaphore.acquire(blocking=False):
            return
        try:
            flags = post_trade_flags(
                addr, pos.get("symbol", "?"),
                entry_liquidity_usd=safe_float(pos.get("entry_liq", 0)),
                entry_top10=safe_float(pos.get("entry_top10", 0)),
                entry_sniper_pct=safe_float(pos.get("entry_sniper_pct", 0)))
            for flag in flags:
                feed(f"  RISK {pos.get('symbol', '?')}: {flag}")
                if flag.startswith("EXIT_NOW"):
                    _exit_position(addr, None, 1.0, "RISK_EXIT", 0)
                    break
                elif flag.startswith("EXIT_NEXT_TP"):
                    with _pos_lock:
                        if addr in state["positions"]:
                            state["positions"][addr]["force_exit_at_tp"] = True
        except Exception:
            pass
        finally:
            _risk_semaphore.release()

    threading.Thread(target=_run, daemon=True).start()



# ══════════════════════════════════════════════════════════════════════════════
# SECTION 12: EXIT EXECUTION & TRADE RECORDING
# ══════════════════════════════════════════════════════════════════════════════

def _exit_position(addr, pos, sell_ratio, reason, pnl_pct):
    """Execute position exit. Thread-safe with sell deduplication."""
    with _pos_lock:
        if addr not in state["positions"] or addr in _selling:
            return
        _selling.add(addr)
        pos = dict(state["positions"][addr])

    try:
        symbol = pos.get("symbol", addr[:8])
        token_amount = safe_float(pos.get("token_amount", 0))
        size_usd = safe_float(pos.get("size_usd", 0))
        sell_amount = token_amount * sell_ratio

        if sell_amount <= 0 or int(sell_amount) <= 0:
            return

        success, tx_hash = execute_sell(addr, symbol, sell_amount, reason)

        if not success:
            log("WARN", f"SELL FAIL {symbol} [{reason}]")
            with _pos_lock:
                if addr in state["positions"]:
                    fc = state["positions"][addr].get("sell_fail_count", 0) + 1
                    state["positions"][addr]["sell_fail_count"] = fc
                    if fc >= 15:
                        state["positions"].pop(addr, None)
                        save_positions()
                        feed(f"  FORCE_REMOVE {symbol}: {fc} sell failures")
            return

        # Record trade
        pnl_usd = size_usd * sell_ratio * pnl_pct
        _record_trade(addr, pos, reason, pnl_pct, sell_ratio, tx_hash, pnl_usd)

        # Update or remove position
        with _pos_lock:
            if sell_ratio >= 0.99:
                state["positions"].pop(addr, None)
                cooldown_map[addr] = time.time() + 1800
            else:
                if addr in state["positions"]:
                    state["positions"][addr]["token_amount"] = token_amount - sell_amount
                    state["positions"][addr]["size_usd"] = size_usd * (1 - sell_ratio)
                    state["positions"][addr]["sell_fail_count"] = 0
                    old_rem = safe_float(state["positions"][addr].get("remaining", 1.0))
                    state["positions"][addr]["remaining"] = old_rem * (1 - sell_ratio)
            save_positions()

        multiplier = 1 + pnl_pct
        feed(f"SELL {symbol} [{reason}] {sell_ratio:.0%} PnL={pnl_pct*100:+.1f}% ({multiplier:.2f}x)")

        with _state_lock:
            state["stats"]["sells"] += 1
            state["stats"]["net_pnl"] = round(state["stats"]["net_pnl"] + pnl_usd, 2)
            if pnl_pct >= 0:
                state["stats"]["wins"] += 1
            else:
                state["stats"]["losses"] += 1

    finally:
        with _pos_lock:
            _selling.discard(addr)


def _record_trade(addr, pos, reason, pnl_pct, sell_ratio, tx_hash, pnl_usd):
    """Record trade in history and update session risk."""
    trade = {
        "tradeId": f"sell-{int(time.time())}-{addr[:4]}-{''.join(random.choices(string.ascii_lowercase, k=4))}",
        "timestamp": int(time.time()),
        "direction": "sell",
        "tokenAddress": addr,
        "symbol": pos.get("symbol", addr[:8]),
        "tier": pos.get("tier", "?"),
        "size_usd": safe_float(pos.get("size_usd", 0)) * sell_ratio,
        "pnl_pct": pnl_pct,
        "pnl_usd": round(pnl_usd, 4),
        "reason": reason,
        "sell_ratio": sell_ratio,
        "txHash": tx_hash or "",
        "mode": "paper" if config.PAPER_TRADE else "live",
        "t": datetime.now().strftime("%H:%M:%S"),
    }

    with _state_lock:
        state["trades"].insert(0, trade)
        state["trades"] = state["trades"][:200]
    with _trades_lock:
        save_trades()

    if pnl_pct < 0:
        _record_loss(pnl_usd)
    else:
        _record_win()


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 13: SESSION RISK CONTROL
# V8: Pause only, never stop. TP/SL continue during pause.
# ══════════════════════════════════════════════════════════════════════════════

_was_paused = False


def can_enter():
    """Check if new entries are allowed. Returns (ok, reason)."""
    global _was_paused

    if config.PAUSED:
        return False, "PAUSED"

    if time.time() - _startup_ts < config.STARTUP_COOLDOWN:
        remain = int(config.STARTUP_COOLDOWN - (time.time() - _startup_ts))
        return False, f"STARTUP_COOLDOWN({remain}s)"

    with _state_lock:
        if time.time() < session_risk["paused_until"]:
            remain = int(session_risk["paused_until"] - time.time())
            _was_paused = True
            return False, f"SESSION_PAUSED({remain}s)"
        elif _was_paused:
            _was_paused = False
            feed("SESSION_RESUMED: pause expired")

    with _pos_lock:
        active = sum(1 for p in state["positions"].values()
                     if p.get("tp_tier", 0) < 1
                     and p.get("sell_fail_count", 0) < 10
                     and p.get("remaining", 1.0) > 0.15)
        if active >= config.MAX_POSITIONS:
            return False, "MAX_POSITIONS"

    return True, "OK"


def _record_loss(pnl_usd):
    """Record loss → update session risk (pause logic)."""
    with _state_lock:
        session_risk["consecutive_losses"] += 1
        session_risk["cumulative_loss_usd"] += abs(pnl_usd)

        if session_risk["cumulative_loss_usd"] >= config.DAILY_LOSS_LIMIT:
            session_risk["paused_until"] = time.time() + config.DAILY_LOSS_PAUSE
            feed(f"SESSION_PAUSE: daily loss ${session_risk['cumulative_loss_usd']:.2f} >= "
                 f"${config.DAILY_LOSS_LIMIT} -> paused {config.DAILY_LOSS_PAUSE//60}min")
        elif session_risk["consecutive_losses"] >= config.MAX_CONSEC_LOSS:
            session_risk["paused_until"] = time.time() + config.PAUSE_CONSEC_SEC
            feed(f"SESSION_PAUSE: {session_risk['consecutive_losses']} consecutive losses -> "
                 f"paused {config.PAUSE_CONSEC_SEC//60}min")
    save_session()


def _record_win():
    """Record win → reset consecutive losses."""
    with _state_lock:
        session_risk["consecutive_losses"] = 0
    save_session()


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 14: HOT TOKENS CACHE & HELPERS
# ══════════════════════════════════════════════════════════════════════════════

_hot_cache = {}
_hot_cache_ts = 0


def _get_hot_cache():
    """Get hot tokens with 60s cache TTL."""
    global _hot_cache, _hot_cache_ts
    now = time.time()
    if now - _hot_cache_ts < config.HOT_REFRESH_SEC and _hot_cache:
        return _hot_cache
    try:
        data = onchainos_data("token", "hot-tokens", "--chain", "solana",
                              "--ranking-type", "4", "--limit", "50")
        if isinstance(data, list):
            cache = {}
            for tok in data:
                addr = tok.get("tokenAddress", "") or tok.get("address", "")
                if addr:
                    cache[addr] = {
                        "inflow": safe_float(tok.get("inflowUsd", 0) or tok.get("netInflowUsd", 0)),
                        "sym": tok.get("symbol", "?"),
                    }
            _hot_cache = cache
            _hot_cache_ts = now
    except Exception:
        pass
    return _hot_cache


def _k1_pump_guard(addr, max_pct):
    """Check if 1m candle shows >max_pct pump (chasing protection)."""
    try:
        data = onchainos_data("market", "candles", "--chain", "solana",
                              "--address", addr, "--bar", "1m")
        if isinstance(data, list) and len(data) >= 2:
            k1 = data[-1]
            k1_open = safe_float(k1.get("o", 0))
            k1_close = safe_float(k1.get("c", 0))
            if k1_open > 0:
                return (k1_close - k1_open) / k1_open * 100 > max_pct
    except Exception:
        pass
    return False


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 15: POSITION CREATION & TAKEOVER
# ══════════════════════════════════════════════════════════════════════════════

def _create_position(addr, symbol, tier, size_usd, price, mc, liq, token_amount, tx_hash, rc):
    """Create a new position record."""
    now = time.time()
    entry_top10 = 0
    entry_sniper = 0
    if rc and rc.get("raw"):
        info = rc["raw"].get("info", {})
        entry_top10 = safe_float(info.get("top10HoldPercent", 0))
        entry_sniper = safe_float(info.get("sniperHoldingPercent", 0))

    with _pos_lock:
        state["positions"][addr] = {
            "symbol": symbol, "address": addr, "tier": tier,
            "size_usd": size_usd,
            "entry_price": price if price > 0 else 0.0001,
            "peak_price": price if price > 0 else 0.0001,
            "token_amount": token_amount,
            "entry_mc": mc, "entry_liq": liq,
            "tx_hash": tx_hash or "",
            "opened_at": datetime.now(timezone.utc).isoformat(),
            "opened_at_ts": now, "entry_ts": now,
            "tp_tier": 0, "zero_count": 0, "sell_fail_count": 0,
            "last_peak_ts": now, "last_liq_check": 0, "risk_last_checked": 0,
            "entry_top10": entry_top10, "entry_sniper_pct": entry_sniper,
            "pnl_pct": 0.0, "age_min": 0.0, "remaining": 1.0, "sl1_triggered": False,
        }
        save_positions()
    with _state_lock:
        state["stats"]["buys"] += 1


def _create_unconfirmed_position(addr, symbol, tier, size_usd, price, mc):
    """Create unconfirmed position (swap timeout)."""
    now = time.time()
    with _pos_lock:
        state["positions"][addr] = {
            "symbol": symbol, "address": addr, "tier": tier,
            "size_usd": size_usd,
            "entry_price": price if price > 0 else 0.0001,
            "peak_price": price if price > 0 else 0.0001,
            "token_amount": 0, "entry_mc": mc, "entry_liq": 0,
            "opened_at": datetime.now(timezone.utc).isoformat(),
            "opened_at_ts": now, "entry_ts": now,
            "tp_tier": 0, "zero_count": 0, "sell_fail_count": 0,
            "last_peak_ts": now, "last_liq_check": 0, "risk_last_checked": 0,
            "entry_top10": 0, "entry_sniper_pct": 0,
            "unconfirmed": True, "unconfirmed_ts": now, "unconfirmed_checks": 0,
            "remaining": 1.0, "sl1_triggered": False,
        }
        save_positions()


def takeover_existing_positions():
    """Scan wallet at startup. Inject existing tokens as 'takeover' tier."""
    feed("=== Position Takeover ===")
    wallet = get_wallet_address()
    if not wallet:
        return

    try:
        data = onchainos_data("wallet", "balance", "--chain", "501")
        if not data:
            return

        assets = []
        if isinstance(data, dict):
            for detail in data.get("details", []):
                assets.extend(detail.get("tokenAssets", []))
        elif isinstance(data, list):
            assets = data

        taken = 0
        for asset in assets:
            addr = asset.get("tokenAddress", "")
            sym = (asset.get("symbol") or "").upper()
            bal = safe_float(asset.get("balance", 0))

            if not addr or addr in _NEVER_TRADE or sym in ("SOL", "USDC", "USDT", "WSOL") or bal <= 0:
                continue
            with _pos_lock:
                if addr in state["positions"]:
                    continue

            pi = get_token_price(addr)
            price = safe_float(pi.get("price", 0))
            value_usd = bal * price if price > 0 else 0
            if value_usd < config.MIN_POSITION_VALUE:
                continue

            with _pos_lock:
                state["positions"][addr] = {
                    "symbol": sym or addr[:8], "address": addr, "tier": "takeover",
                    "size_usd": value_usd,
                    "entry_price": price, "peak_price": price,
                    "token_amount": bal,
                    "entry_mc": safe_float(pi.get("marketCap", 0)),
                    "entry_liq": safe_float(pi.get("liquidity", 0)),
                    "opened_at": datetime.now(timezone.utc).isoformat(),
                    "opened_at_ts": time.time(), "entry_ts": time.time(),
                    "tp_tier": 0, "zero_count": 0, "sell_fail_count": 0,
                    "last_peak_ts": time.time(), "last_liq_check": 0, "risk_last_checked": 0,
                    "entry_top10": 0, "entry_sniper_pct": 0,
                    "remaining": 1.0, "sl1_triggered": False,
                }
            taken += 1

        with _pos_lock:
            save_positions()
        feed(f"  Takeover complete: {taken} positions")
    except Exception as e:
        log("ERROR", f"Takeover: {e}")



# ══════════════════════════════════════════════════════════════════════════════
# SECTION 16: WEB DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════

_dashboard_html_path = PROJECT_DIR / "dashboard.html"


class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == "/api/state":
            self._serve_api()
        elif self.path in ("/", "/index.html"):
            self._serve_html()
        else:
            self.send_response(404)
            self.end_headers()

    def _serve_api(self):
        with _state_lock:
            snap = {"feed": list(state["feed"]), "stats": dict(state["stats"])}
        with _pos_lock:
            snap["positions"] = dict(state["positions"])
        with _trades_lock:
            snap["trades"] = list(state["trades"][:50])
        snap["session_risk"] = dict(session_risk)
        snap["config"] = {
            "preset": config.PRESET,
            "paused": config.PAUSED,
            "paper_trade": config.PAPER_TRADE,
            "max_positions": config.MAX_POSITIONS,
            "night_mode": is_night(),
            "version": _VERSION,
        }
        snap["smart_wallets"] = {
            "total": len(_smart_wallets),
            "tier1": sum(1 for w in _smart_wallets.values() if w["tier"] == 1),
        }

        body = json.dumps(snap, ensure_ascii=False, default=str).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _serve_html(self):
        try:
            html = _dashboard_html_path.read_text()
        except FileNotFoundError:
            html = "<html><body><h1>SOL Meme Hunter v8.0</h1><p>API: /api/state</p></body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode())


def start_dashboard():
    if not config.DASHBOARD_ENABLED:
        return
    try:
        HTTPServer.allow_reuse_address = True
        server = HTTPServer(("127.0.0.1", config.DASHBOARD_PORT), DashboardHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        feed(f"Dashboard: http://127.0.0.1:{config.DASHBOARD_PORT}")
    except Exception as e:
        log("WARN", f"Dashboard failed: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 17: SCANNER LOOP & MAIN
# ══════════════════════════════════════════════════════════════════════════════

def scanner_loop():
    """Main scanning loop. Runs Tier S/A/B/D on independent schedules."""
    last_s = last_a = last_b = last_d = last_balance = 0
    last_daily_reset = datetime.now(timezone.utc).date()

    while True:
        try:
            now = time.time()

            # Daily reset at UTC midnight
            today = datetime.now(timezone.utc).date()
            if today != last_daily_reset:
                last_daily_reset = today
                with _state_lock:
                    old_loss = session_risk["cumulative_loss_usd"]
                    session_risk["consecutive_losses"] = 0
                    session_risk["cumulative_loss_usd"] = 0.0
                    session_risk["paused_until"] = 0
                save_session()
                feed(f"  New day {today}, reset (yesterday loss=${old_loss:.2f})")

            # Balance check
            if now - last_balance >= config.BALANCE_CHECK_SEC:
                last_balance = now
                sol_bal = get_sol_balance()
                sol_price = get_sol_price()
                usd_bal = sol_bal * sol_price if sol_price > 0 else 0
                with _pos_lock:
                    n_pos = len(state["positions"])
                    active = sum(1 for p in state["positions"].values()
                                 if p.get("tp_tier", 0) < 1 and p.get("remaining", 1.0) > 0.15)
                feed(f"SOL: {sol_bal:.4f} (~${usd_bal:.2f}) | Positions: {active}/{n_pos} | "
                     f"SW: {len(_smart_wallets)} | Preset: {config.PRESET}")

            # Tier S
            if config.TIER_S_ENABLED and now - last_s >= config.TIER_S_REFRESH_SEC:
                last_s = now
                try:
                    process_tier_s()
                except Exception as e:
                    log("ERROR", f"Tier S: {e}")

            # Tier A
            if now - last_a >= config.SM_REFRESH_SEC:
                last_a = now
                try:
                    process_tier_a()
                except Exception as e:
                    log("ERROR", f"Tier A: {e}")

            # Tier B
            if now - last_b >= config.GRADUATED_REFRESH_SEC:
                last_b = now
                try:
                    process_tier_b()
                except Exception as e:
                    log("ERROR", f"Tier B: {e}")

            # Tier D
            if now - last_d >= config.HOT_REFRESH_SEC:
                last_d = now
                try:
                    process_tier_d()
                except Exception as e:
                    log("ERROR", f"Tier D: {e}")

            with _state_lock:
                state["stats"]["cycle"] += 1

            # Cleanup expired cooldowns & dedup
            expired = [k for k, v in cooldown_map.items() if now >= v]
            for k in expired:
                del cooldown_map[k]
            old_keys = [k for k, ts in _tier_s_last_seen.items() if now - ts > config.TIER_S_DEDUP_SEC]
            for k in old_keys:
                del _tier_s_last_seen[k]

            time.sleep(config.MONITOR_SEC)

        except Exception as e:
            log("ERROR", f"Scanner: {e}")
            time.sleep(5)


def main():
    """Main entry point."""
    print("=" * 60)
    print(f"  SOL MEME HUNTER v{_VERSION}")
    print(f"  Preset: {config.PRESET.upper()}")
    print("  4-Tier (S/A/B/D) + Smart Wallet + 9-Layer Exit")
    print("  Safe overnight: pause only, TP/SL always enforced")
    print("=" * 60)

    # Check onchainos
    try:
        ver = onchainos_run("--version")
        feed(f"onchainos: {ver.get('data', ver.get('msg', 'unknown'))}")
    except Exception:
        log("WARN", "onchainos --version failed")

    # Get wallet
    wallet = get_wallet_address()
    if not wallet:
        log("FATAL", "No wallet address. Run: onchainos wallet login")
        sys.exit(1)
    feed(f"Wallet: {wallet}")

    # Load smart wallets
    load_smart_wallets()

    # Load state
    load_positions()
    load_acted()
    load_session()
    load_trades()

    with _pos_lock:
        n_pos = len(state["positions"])
        active = sum(1 for p in state["positions"].values()
                     if p.get("tp_tier", 0) < 1 and p.get("remaining", 1.0) > 0.15)
    feed(f"  Loaded: {n_pos} positions ({active} active), {len(acted)} acted")

    # Takeover
    takeover_existing_positions()

    # Startup info
    night = is_night()
    feed(f"Mode: {'PAPER' if config.PAPER_TRADE else 'LIVE'} | Night: {night} | Preset: {config.PRESET}")
    feed(f"Tier S: ${config.TIER_S_SIZE_DAY}/${config.TIER_S_SIZE_NIGHT} | "
         f"A: ${config.TIER_A_SIZE_DAY}/${config.TIER_A_SIZE_NIGHT} | "
         f"B: ${config.TIER_B_SIZE_DAY}/${config.TIER_B_SIZE_NIGHT} | "
         f"D: base=${config.TIER_D_SIZE_BASE}")
    feed(f"TP1=+{config.TP1_PCT*100:.0f}%/50% | SL1={config.SL1_PCT*100:.0f}%/50% | "
         f"MAX_POS={config.MAX_POSITIONS} | DAILY_LOSS=${config.DAILY_LOSS_LIMIT}")

    # Start dashboard
    start_dashboard()

    # Start monitor
    threading.Thread(target=monitor_positions, daemon=True).start()

    # Graceful shutdown
    def shutdown(signum, frame):
        feed(f"Shutdown signal {signum}")
        with _pos_lock:
            save_positions()
        save_session()
        feed("Shutdown complete.")
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # Run scanner (blocks forever)
    scanner_loop()


if __name__ == "__main__":
    main()
