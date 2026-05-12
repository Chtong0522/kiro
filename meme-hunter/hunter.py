#!/usr/bin/env python3
"""
SOL Meme Hunter v6.0 - Production Trading Bot
Architecture: 3-Tier (A/B/D) with dynamic scoring and session risk control.
Swap flow: swap swap -> contract-call -> wallet history (proper 3-step flow).

Tiers:
  A - Smart Money Signal (onchainos signal list)
  B - Graduation Ambush (onchainos memepump tokens --stage MIGRATED)
  D - Hot Momentum (onchainos token hot-tokens --ranking-type 4)

Dashboard: http://localhost:3250
"""

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1: Imports & Setup
# ══════════════════════════════════════════════════════════════════════════════

import subprocess
import json
import time
import os
import threading
import signal
import sys
import random
import string
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict
from http.server import HTTPServer, BaseHTTPRequestHandler

import config
from risk_check import pre_trade_checks, post_trade_flags

# Ensure onchainos CLI is on PATH
os.environ["PATH"] = (
    os.path.expanduser("~/.local/bin") + ":"
    + os.path.expanduser("~/.nvm/versions/node/v22.22.2/bin") + ":"
    + os.environ.get("PATH", "")
)

PROJECT_DIR = Path(__file__).parent
SOL_NATIVE = config.SOL_NATIVE
_NEVER_TRADE = getattr(config, "_NEVER_TRADE_MINTS", set())
_startup_ts = time.time()


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2: State Management
# ══════════════════════════════════════════════════════════════════════════════

state_lock = threading.Lock()
pos_lock = threading.Lock()
trades_lock = threading.Lock()

cooldown_map = {}       # {addr: expire_timestamp}
_selling = set()        # prevent concurrent sells of the same token
_wallet_addr = ""       # cached wallet address

state = {
    "positions": {},
    "trades": [],
    "feed": [],
    "stats": {
        "cycle": 0, "buys": 0, "sells": 0,
        "wins": 0, "losses": 0, "net_pnl": 0.0,
    },
}

session_risk = {
    "consecutive_losses": 0,
    "cumulative_loss_usd": 0.0,
    "paused_until": 0,
    "stopped": False,
}

acted = {}  # {addr: timestamp} - permanent, never buy same token twice


def load_positions():
    """Load positions from disk."""
    try:
        with open(config.POSITIONS_FILE) as f:
            state["positions"] = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        state["positions"] = {}


def save_positions():
    """Atomic write positions. Caller must hold pos_lock."""
    tmp = config.POSITIONS_FILE + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(state["positions"], f, default=str, indent=2)
        os.replace(tmp, config.POSITIONS_FILE)
    except Exception:
        pass


def load_trades():
    """Load trade history from disk."""
    try:
        with open(config.TRADES_FILE) as f:
            state["trades"] = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        state["trades"] = []


def save_trades():
    """Atomic write trade history. Caller must hold trades_lock."""
    tmp = config.TRADES_FILE + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(state["trades"], f, default=str, indent=2)
        os.replace(tmp, config.TRADES_FILE)
    except Exception:
        pass


def load_acted():
    """Load acted tokens (permanent - never buy same token again)."""
    global acted
    try:
        with open(config.ACTED_FILE) as f:
            acted = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        acted = {}


def save_acted():
    """Write acted file atomically."""
    tmp = config.ACTED_FILE + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(acted, f, default=str)
        os.replace(tmp, config.ACTED_FILE)
    except Exception:
        pass


def load_session():
    """Load session risk state."""
    global session_risk
    try:
        with open(config.SESSION_FILE) as f:
            data = json.load(f)
            session_risk.update(data)
    except (FileNotFoundError, json.JSONDecodeError):
        pass


def save_session():
    """Write session risk state atomically."""
    tmp = config.SESSION_FILE + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(session_risk, f, default=str)
        os.replace(tmp, config.SESSION_FILE)
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3: Utility Functions
# ══════════════════════════════════════════════════════════════════════════════

def feed(msg):
    """Log message to stdout, file, and state feed list."""
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(config.LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass
    with state_lock:
        state["feed"].append({"msg": msg, "t": ts})
        state["feed"] = state["feed"][-50:]


def safe_float(v, default=0.0):
    """Safe float conversion."""
    try:
        return float(v)
    except (ValueError, TypeError):
        return default


def safe_int(v, default=0):
    """Safe int conversion."""
    try:
        return int(v)
    except (ValueError, TypeError):
        return default


def is_night():
    """Check if current UTC hour is in night mode range."""
    h = datetime.now(timezone.utc).hour
    if config.NIGHT_START_UTC < config.NIGHT_END_UTC:
        return config.NIGHT_START_UTC <= h < config.NIGHT_END_UTC
    else:
        return h >= config.NIGHT_START_UTC or h < config.NIGHT_END_UTC


def onchainos_run(*args, timeout=20):
    """Run onchainos CLI command. Returns full parsed JSON dict."""
    try:
        r = subprocess.run(
            ["onchainos", *args],
            capture_output=True, text=True, timeout=timeout
        )
        return json.loads(r.stdout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "msg": "timeout", "data": None}
    except (json.JSONDecodeError, Exception):
        return {"ok": False, "msg": "parse_error", "data": None}


def onchainos_data(*args, timeout=20):
    """Run onchainos CLI command, return .data field."""
    result = onchainos_run(*args, timeout=timeout)
    return result.get("data")


def get_wallet_address():
    """Get Solana wallet address. Caches result."""
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
                if isinstance(item, dict):
                    ci = item.get("chainIndex")
                    if ci in (501, "501"):
                        _wallet_addr = item.get("address", "")
                        break
        if not _wallet_addr:
            _wallet_addr = config.WALLET
    except Exception:
        _wallet_addr = config.WALLET
    return _wallet_addr


def get_sol_balance():
    """Get native SOL balance in SOL units."""
    try:
        data = onchainos_data("wallet", "balance", "--chain", "501")
        if isinstance(data, dict):
            details = data.get("details", [])
            if isinstance(details, list):
                for detail in details:
                    assets = detail.get("tokenAssets", [])
                    if isinstance(assets, list):
                        for a in assets:
                            ta = a.get("tokenAddress")
                            sym = (a.get("symbol") or "").upper()
                            if ta in ("", None) or sym == "SOL":
                                return safe_float(a.get("balance", 0))
            ta = data.get("tokenAddress")
            if ta in ("", None):
                return safe_float(data.get("balance", 0))
        elif isinstance(data, list):
            for b in data:
                ta = b.get("tokenAddress")
                sym = (b.get("symbol") or "").upper()
                if ta in ("", None) or sym == "SOL":
                    return safe_float(b.get("balance", 0))
    except Exception:
        pass
    return 0.0


def get_sol_price():
    """Get current SOL price in USD."""
    try:
        data = onchainos_data("token", "price-info", "--chain", "solana",
                              "--address", SOL_NATIVE)
        if isinstance(data, list):
            for item in data:
                p = safe_float(item.get("price", 0))
                if p > 0:
                    return p
        elif isinstance(data, dict):
            p = safe_float(data.get("price", 0))
            if p > 0:
                return p
    except Exception:
        pass
    return 0.0


def get_token_price(addr):
    """Get token price info. Returns dict with price, marketCap, liquidity, holders."""
    try:
        data = onchainos_data("token", "price-info", "--chain", "solana",
                              "--address", addr)
        if isinstance(data, list):
            return data[0] if data else {}
        elif isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def get_token_balance(wallet_addr, token_addr):
    """Get token balance for a specific token in wallet."""
    try:
        data = onchainos_data("portfolio", "token-balances",
                              "--address", wallet_addr,
                              "--tokens", f"501:{token_addr}")
        if isinstance(data, list) and data:
            item = data[0]
            return safe_float(item.get("amount", 0))
        elif isinstance(data, dict):
            return safe_float(data.get("amount", 0))
    except Exception:
        pass
    return 0.0

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4: Swap Execution Engine
# ══════════════════════════════════════════════════════════════════════════════

def poll_tx_status(tx_hash, timeout=60):
    """Poll transaction status. Returns 'confirmed', 'failed', or 'timeout'."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            data = onchainos_data("wallet", "history",
                                  "--tx-hash", tx_hash,
                                  "--chain-index", "501", timeout=15)
            if data:
                status = ""
                if isinstance(data, dict):
                    status = (data.get("status") or "").lower()
                elif isinstance(data, list) and data:
                    status = (data[0].get("status") or "").lower()
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
    Buy token using proper 3-step swap flow.
    amount_usd: position size in USD
    Returns: (success: bool, tx_hash: str, token_amount: float)
    """
    wallet = get_wallet_address()
    if not wallet:
        feed("  BUY FAIL: no wallet address")
        return False, "", 0.0

    # Paper trade mode: use quote only
    if config.PAPER_TRADE:
        sol_price = get_sol_price()
        if sol_price <= 0:
            return False, "", 0.0
        lamports = int(amount_usd / sol_price * 1e9)
        try:
            data = onchainos_data("swap", "quote",
                                  "--from", SOL_NATIVE,
                                  "--to", token_addr,
                                  "--amount", str(lamports),
                                  "--chain", "solana", timeout=30)
            if not data:
                return False, "", 0.0
            q = data[0] if isinstance(data, list) else data
            router = q.get("routerResult", q)
            token_amount = safe_float(router.get("toTokenAmount", 0))
            return True, "paper_" + str(int(time.time())), token_amount
        except Exception as e:
            feed(f"  BUY QUOTE FAIL: {e}")
            return False, "", 0.0

    # Step 1: Get SOL price, convert USD to lamports
    sol_price = get_sol_price()
    if sol_price <= 0:
        feed("  BUY FAIL: cannot get SOL price")
        return False, "", 0.0
    lamports = int(amount_usd / sol_price * 1e9)

    # Step 2: onchainos swap swap
    try:
        data = onchainos_data("swap", "swap",
                              "--chain", "solana",
                              "--from", SOL_NATIVE,
                              "--to", token_addr,
                              "--amount", str(lamports),
                              "--slippage", str(config.SLIPPAGE_BUY),
                              "--wallet", wallet,
                              timeout=60)
        if not data:
            feed("  BUY FAIL: swap returned no data")
            return False, "", 0.0
    except Exception as e:
        feed(f"  BUY FAIL swap: {e}")
        return False, "", 0.0

    q = data[0] if isinstance(data, list) else data
    router = q.get("routerResult", q)
    token_amount = safe_float(router.get("toTokenAmount", 0))

    # Step 3: Extract tx.to and tx.data, call contract-call
    tx = q.get("tx", {})
    tx_to = tx.get("to", "")
    unsigned_tx = tx.get("data", "")

    if not tx_to or not unsigned_tx:
        feed("  BUY FAIL: swap response missing tx.to or tx.data")
        return False, "", 0.0

    try:
        result = onchainos_data("wallet", "contract-call",
                                "--chain", "501",
                                "--to", tx_to,
                                "--unsigned-tx", unsigned_tx,
                                timeout=60)
        if not result:
            feed("  BUY FAIL: contract-call returned no data")
            return False, "", 0.0
    except Exception as e:
        feed(f"  BUY FAIL contract-call: {e}")
        # Timeout - create unconfirmed position
        if "timeout" in str(e).lower():
            return False, "TIMEOUT", token_amount
        return False, "", 0.0

    tx_hash = ""
    if isinstance(result, dict):
        tx_hash = result.get("txHash") or result.get("orderId") or ""
    elif isinstance(result, str):
        tx_hash = result

    # Step 4: Poll for confirmation (non-blocking, short timeout)
    if tx_hash:
        status = poll_tx_status(tx_hash, timeout=30)
        if status == "failed":
            feed(f"  BUY FAIL: tx {tx_hash[:12]} failed on-chain")
            return False, tx_hash, 0.0
        # confirmed or timeout - both OK (timeout = unconfirmed position)

    # If token_amount is 0, try to get it from balance
    if token_amount <= 0 and tx_hash:
        time.sleep(2)
        token_amount = get_token_balance(wallet, token_addr)

    return True, tx_hash, token_amount


def execute_sell(token_addr, symbol, token_amount, reason, max_retries=3):
    """
    Sell token using proper 3-step swap flow with retry logic.
    token_amount: raw amount in token's smallest units
    Returns: (success: bool, tx_hash: str)
    """
    wallet = get_wallet_address()
    if not wallet:
        return False, ""

    if config.PAPER_TRADE:
        feed(f"  [PAPER] SELL {symbol} reason={reason}")
        return True, "paper_sell_" + str(int(time.time()))

    raw_amount = str(int(token_amount))
    if int(token_amount) <= 0:
        return False, ""

    for attempt in range(max_retries):
        try:
            # Step 1: swap swap (sell token for SOL)
            data = onchainos_data("swap", "swap",
                                  "--chain", "solana",
                                  "--from", token_addr,
                                  "--to", SOL_NATIVE,
                                  "--amount", raw_amount,
                                  "--slippage", str(config.SLIPPAGE_SELL),
                                  "--wallet", wallet,
                                  timeout=60)
            if not data:
                feed(f"  SELL {symbol} attempt {attempt+1}: swap returned no data")
                time.sleep(5 * (attempt + 1))
                continue

            q = data[0] if isinstance(data, list) else data

            # Step 2: Extract tx.to and tx.data
            tx = q.get("tx", {})
            tx_to = tx.get("to", "")
            unsigned_tx = tx.get("data", "")

            if not tx_to or not unsigned_tx:
                feed(f"  SELL {symbol} attempt {attempt+1}: missing tx.to/tx.data")
                time.sleep(5 * (attempt + 1))
                continue

            # Step 3: contract-call
            result = onchainos_data("wallet", "contract-call",
                                    "--chain", "501",
                                    "--to", tx_to,
                                    "--unsigned-tx", unsigned_tx,
                                    timeout=60)
            if not result:
                feed(f"  SELL {symbol} attempt {attempt+1}: contract-call no data")
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
            feed(f"  SELL {symbol} attempt {attempt+1} error: {e}")
            time.sleep(5 * (attempt + 1))

    return False, ""


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5: Tier A - Smart Money Signal Scanner
# ══════════════════════════════════════════════════════════════════════════════

def fetch_sm_signals():
    """Fetch smart money signals. Returns list of signal dicts."""
    try:
        labels = ",".join(str(l) for l in config.SM_LABELS)
        data = onchainos_data("signal", "list",
                              "--chain", "solana",
                              "--wallet-type", labels,
                              "--min-address-count", str(config.SM_MIN_WALLETS))
        if isinstance(data, list):
            return data
        elif isinstance(data, dict):
            return [data]
    except Exception:
        pass
    return []


def process_tier_a():
    """Process Tier A smart money signals. Returns after 1 successful buy."""
    signals = fetch_sm_signals()
    if not signals:
        return

    feed(f"Tier A SM signals: {len(signals)}")
    night = is_night()
    size = config.TIER_A_SIZE_NIGHT if night else config.TIER_A_SIZE_DAY

    # Get hot tokens for NORMAL signal confirmation
    hot = get_hot_tokens()

    for sig in signals:
        token = sig.get("token", {})
        if not isinstance(token, dict):
            continue
        addr = token.get("tokenAddress", "") or token.get("address", "")
        symbol = token.get("symbol", "?")
        wallet_count = safe_int(sig.get("triggerWalletCount", 0))
        sold_ratio = safe_float(sig.get("soldRatioPercent", 100))
        mc = safe_float(token.get("marketCap", 0))

        if not addr or addr in _NEVER_TRADE:
            continue
        if addr in acted or addr in cooldown_map and time.time() < cooldown_map.get(addr, 0):
            continue
        with pos_lock:
            if addr in state["positions"]:
                continue

        # Pre-filter from signal data
        if sold_ratio > 80:
            continue
        if mc < config.TIER_A_MC_MIN or mc > config.TIER_A_MC_MAX:
            continue

        # Signal strength classification
        is_strong = wallet_count >= config.SM_STRONG_THRESH

        # NORMAL signals need hot-tokens confirmation
        if not is_strong:
            hot_entry = hot.get(addr, {})
            inflow = safe_float(hot_entry.get("inflow", 0))
            if inflow <= 0:
                continue

        # Deep verification
        try:
            price_info = get_token_price(addr)
            liq = safe_float(price_info.get("liquidity", 0))
            holders = safe_int(price_info.get("holders", 0))
            price = safe_float(price_info.get("price", 0))

            if liq < config.TIER_A_LIQ_MIN:
                continue
            if holders < config.TIER_A_HOLDERS_MIN:
                continue

            # K1 pump guard
            if _k1_pump_guard(addr, config.TIER_A_K1_PUMP_GUARD):
                feed(f"  Skip {symbol}: K1 pump guard")
                continue

            # Risk check
            rc = pre_trade_checks(addr, symbol, quick=True)
            if not rc.get("pass", False):
                feed(f"  Skip {symbol}: risk G{rc.get('grade', '?')}")
                continue

        except Exception as e:
            feed(f"  Skip {symbol}: verification error: {e}")
            continue

        # Entry check
        ok, reason = can_enter()
        if not ok:
            feed(f"  Skip {symbol}: {reason}")
            return

        # Execute buy
        feed(f"ENTER TIER_A {symbol} ${size} | MC=${mc:,.0f} | wallets={wallet_count}")
        success, tx_hash, token_amt = execute_buy(addr, size)

        if success and token_amt > 0:
            _create_position(addr, symbol, "A", size, price, mc, liq,
                             token_amt, tx_hash, rc if 'rc' in dir() else None)
            acted[addr] = int(time.time())
            save_acted()
            if tx_hash and not tx_hash.startswith("paper"):
                feed(f"  swap OK | TX: https://solscan.io/tx/{tx_hash}")
            return
        elif tx_hash == "TIMEOUT":
            _create_unconfirmed_position(addr, symbol, "A", size, price, mc)
            acted[addr] = int(time.time())
            save_acted()
            feed(f"  BUY TIMEOUT {symbol}: created unconfirmed position")
            return
        else:
            feed(f"  BUY FAIL {symbol}")
            cooldown_map[addr] = time.time() + 300


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 6: Tier B - Graduation Ambush Scanner
# ══════════════════════════════════════════════════════════════════════════════

def fetch_graduated_tokens():
    """Fetch recently graduated tokens. Returns list of token dicts."""
    try:
        data = onchainos_data("memepump", "tokens",
                              "--chain", "solana",
                              "--stage", config.TIER_B_STAGE)
        if isinstance(data, list):
            return data
        elif isinstance(data, dict):
            return [data]
    except Exception:
        pass
    return []


def process_tier_b():
    """Process Tier B graduated tokens. Returns after 1 successful buy."""
    candidates = fetch_graduated_tokens()
    if not candidates:
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

        mc = safe_float(tok.get("marketCap", 0) or tok.get("usdMarketCap", 0))
        holders = safe_int(tok.get("holders", 0) or tok.get("holderCount", 0))
        dev_sold = tok.get("devSold", False) or tok.get("creatorClose", False)
        insiders_pct = safe_float(tok.get("insiderPercent", 0) or tok.get("insiderHoldingPercent", 0))
        top10 = safe_float(tok.get("top10HoldPercent", 0) or tok.get("top10Percent", 0))
        aped = safe_int(tok.get("apedCount", 0) or tok.get("smartMoneyCount", 0))

        if mc < config.TIER_B_MC_MIN or mc > config.TIER_B_MC_MAX:
            continue
        if holders < config.TIER_B_HOLDERS_MIN:
            continue
        if config.TIER_B_DEV_SOLD and not dev_sold:
            continue
        if insiders_pct > config.TIER_B_INSIDERS_MAX:
            continue
        if top10 > config.TIER_B_TOP10_MAX:
            continue
        if aped < config.TIER_B_APED_MIN:
            continue

        filtered.append({"addr": addr, "mc": mc, "holders": holders,
                         "symbol": tok.get("symbol", tok.get("tokenSymbol", "?"))})

    feed(f"Tier B MIGRATED candidates: {len(filtered)}")

    for cand in filtered:
        addr = cand["addr"]
        symbol = cand["symbol"]
        mc = cand["mc"]

        if addr in acted or addr in cooldown_map and time.time() < cooldown_map.get(addr, 0):
            continue
        with pos_lock:
            if addr in state["positions"]:
                continue

        # K1 pump guard
        if _k1_pump_guard(addr, config.TIER_A_K1_PUMP_GUARD):
            continue

        # Quick risk check
        try:
            rc = pre_trade_checks(addr, symbol, quick=True)
            if not rc.get("pass", False):
                continue
        except Exception:
            continue

        # Get price info
        price_info = get_token_price(addr)
        price = safe_float(price_info.get("price", 0))
        liq = safe_float(price_info.get("liquidity", 0))

        # Entry check
        ok, reason = can_enter()
        if not ok:
            return

        feed(f"ENTER TIER_B {symbol} ${size} | MC=${mc:,.0f}")
        success, tx_hash, token_amt = execute_buy(addr, size)

        if success and token_amt > 0:
            _create_position(addr, symbol, "B", size, price, mc, liq,
                             token_amt, tx_hash, rc)
            acted[addr] = int(time.time())
            save_acted()
            if tx_hash and not tx_hash.startswith("paper"):
                feed(f"  swap OK | TX: https://solscan.io/tx/{tx_hash}")
            return
        elif tx_hash == "TIMEOUT":
            _create_unconfirmed_position(addr, symbol, "B", size, price, mc)
            acted[addr] = int(time.time())
            save_acted()
            feed(f"  BUY TIMEOUT {symbol}: unconfirmed position")
            return
        else:
            feed(f"  BUY FAIL {symbol}")
            cooldown_map[addr] = time.time() + 300
            return

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 7: Tier D - Hot Momentum Scanner
# ══════════════════════════════════════════════════════════════════════════════

def fetch_hot_momentum():
    """Fetch hot momentum tokens. Returns list of token dicts."""
    try:
        data = onchainos_data("token", "hot-tokens",
                              "--chain", "solana",
                              "--ranking-type", "4",
                              "--limit", "20")
        if isinstance(data, list):
            return data
        elif isinstance(data, dict):
            return [data]
    except Exception:
        pass
    return []


def calculate_score(tok):
    """Calculate composite score 0-100 for a hot momentum token."""
    score = 0

    # Holders weight (0-30)
    holders = safe_int(tok.get("holders", 0) or tok.get("holderCount", 0))
    if holders >= 5000:
        score += 30
    elif holders >= 2000:
        score += 25
    elif holders >= 1000:
        score += 20
    elif holders >= 500:
        score += 15

    # Buy/sell ratio weight (0-25)
    buys = safe_int(tok.get("buys", 0) or tok.get("buyCount", 0))
    sells = safe_int(tok.get("sells", 0) or tok.get("sellCount", 0))
    if sells > 0:
        ratio = buys / sells
        if ratio >= 2.0:
            score += 25
        elif ratio >= 1.5:
            score += 20
        elif ratio >= 1.2:
            score += 15
        elif ratio >= 1.0:
            score += 10

    # Unique traders weight (0-15)
    traders = safe_int(tok.get("uniqueTraders", 0) or tok.get("traderCount", 0))
    if traders >= 500:
        score += 15
    elif traders >= 300:
        score += 12
    elif traders >= 200:
        score += 9
    elif traders >= 100:
        score += 6

    # Price change weight (0-15)
    change = safe_float(tok.get("change", 0) or tok.get("priceChange", 0) or tok.get("changePct", 0))
    if change >= 30:
        score += 15
    elif change >= 20:
        score += 12
    elif change >= 10:
        score += 9
    elif change >= 5:
        score += 6

    # Inflow weight (0-15)
    inflow = safe_float(tok.get("inflowUsd", 0) or tok.get("netInflowUsd", 0) or tok.get("inflow", 0))
    if inflow >= 50000:
        score += 15
    elif inflow >= 20000:
        score += 12
    elif inflow >= 5000:
        score += 9
    elif inflow > 0:
        score += 5

    return score


def score_to_size(score):
    """Convert score to position size in USD."""
    night = is_night()
    base = 3 if night else config.TIER_D_SIZE_BASE
    for tier in config.TIER_D_SCORE_TIERS:
        if score >= tier["min_score"]:
            return base + tier["extra"]
    return base


def process_tier_d():
    """Process Tier D hot momentum tokens. Returns after 1 successful buy."""
    candidates = fetch_hot_momentum()
    if not candidates:
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
        top10 = safe_float(tok.get("top10HoldPercent", 0) or tok.get("top10Percent", 0))
        risk_level = safe_int(tok.get("riskLevel", 99) or tok.get("riskControlLevel", 99))
        inflow = safe_float(tok.get("inflowUsd", 0) or tok.get("netInflowUsd", 0) or tok.get("inflow", 0))
        change = safe_float(tok.get("change", 0) or tok.get("priceChange", 0) or tok.get("changePct", 0))
        traders = safe_int(tok.get("uniqueTraders", 0) or tok.get("traderCount", 0))

        if holders < config.TIER_D_HOLDERS_MIN:
            continue
        if mc < config.TIER_D_MC_MIN or mc > config.TIER_D_MC_MAX:
            continue
        if liq < config.TIER_D_LIQ_MIN:
            continue
        if top10 > config.TIER_D_TOP10_MAX:
            continue
        if risk_level > config.TIER_D_RISK_LEVEL:
            continue
        if inflow <= config.TIER_D_MIN_INFLOW:
            continue
        if change < config.TIER_D_MIN_CHANGE:
            continue
        if traders < config.TIER_D_UNIQUE_TRADERS:
            continue

        filtered.append(tok)

    feed(f"Tier D hot candidates: {len(filtered)}")

    for tok in filtered:
        addr = tok.get("tokenAddress", "") or tok.get("address", "")
        symbol = tok.get("symbol", tok.get("tokenSymbol", "?"))
        mc = safe_float(tok.get("marketCap", 0) or tok.get("usdMarketCap", 0))

        if addr in acted or addr in cooldown_map and time.time() < cooldown_map.get(addr, 0):
            continue
        with pos_lock:
            if addr in state["positions"]:
                continue

        # Calculate score
        score = calculate_score(tok)
        if score < config.TIER_D_SCORE_THRESHOLD:
            continue

        # K1 pump guard
        if _k1_pump_guard(addr, config.TIER_A_K1_PUMP_GUARD):
            feed(f"  Skip {symbol}: K1 pump guard (score={score})")
            continue

        # Quick risk check
        try:
            rc = pre_trade_checks(addr, symbol, quick=True)
            if not rc.get("pass", False):
                feed(f"  Skip {symbol}: risk G{rc.get('grade', '?')}")
                continue
        except Exception:
            continue

        # Get price info
        price_info = get_token_price(addr)
        price = safe_float(price_info.get("price", 0))
        liq = safe_float(price_info.get("liquidity", 0))

        # Entry check
        ok, reason = can_enter()
        if not ok:
            return

        size = score_to_size(score)
        feed(f"ENTER TIER_D {symbol} ${size} | MC=${mc:,.0f} | score={score}")
        success, tx_hash, token_amt = execute_buy(addr, size)

        if success and token_amt > 0:
            _create_position(addr, symbol, "D", size, price, mc, liq,
                             token_amt, tx_hash, rc)
            acted[addr] = int(time.time())
            save_acted()
            if tx_hash and not tx_hash.startswith("paper"):
                feed(f"  swap OK | TX: https://solscan.io/tx/{tx_hash}")
            return
        elif tx_hash == "TIMEOUT":
            _create_unconfirmed_position(addr, symbol, "D", size, price, mc)
            acted[addr] = int(time.time())
            save_acted()
            feed(f"  BUY TIMEOUT {symbol}: unconfirmed position")
            return
        else:
            feed(f"  BUY FAIL {symbol}")
            cooldown_map[addr] = time.time() + 300
            return


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 8: Position Monitor - 7-Layer Exit System
# ══════════════════════════════════════════════════════════════════════════════

def monitor_positions():
    """Position monitor loop. Runs every MONITOR_SEC (1s)."""
    while True:
        time.sleep(config.MONITOR_SEC)
        try:
            _monitor_cycle()
        except Exception as e:
            feed(f"MONITOR ERROR: {e}")


def _monitor_cycle():
    """Single monitoring cycle for all positions."""
    with pos_lock:
        positions = dict(state["positions"])
    if not positions:
        return

    now = time.time()

    # Handle unconfirmed positions first
    for addr, pos in list(positions.items()):
        if not pos.get("unconfirmed"):
            continue
        elapsed = now - pos.get("unconfirmed_ts", pos.get("opened_at_ts", 0))
        if elapsed < 60:
            continue
        checks = pos.get("unconfirmed_checks", 0)
        try:
            pi = get_token_price(addr)
            price = safe_float(pi.get("price", 0))
            if price > 0:
                with pos_lock:
                    if addr in state["positions"]:
                        state["positions"][addr].pop("unconfirmed", None)
                        state["positions"][addr].pop("unconfirmed_ts", None)
                        state["positions"][addr].pop("unconfirmed_checks", None)
                        state["positions"][addr]["entry_price"] = price
                        state["positions"][addr]["peak_price"] = price
                        # Try to get token balance
                        wallet = get_wallet_address()
                        bal = get_token_balance(wallet, addr)
                        if bal > 0:
                            state["positions"][addr]["token_amount"] = bal
                        save_positions()
                feed(f"  CONFIRMED {pos.get('symbol', addr[:8])}: unconfirmed -> active")
                continue
        except Exception:
            pass
        checks += 1
        with pos_lock:
            if addr in state["positions"]:
                state["positions"][addr]["unconfirmed_checks"] = checks
        if checks >= 10 and elapsed >= 180:
            with pos_lock:
                state["positions"].pop(addr, None)
                save_positions()
            feed(f"  DROPPED {pos.get('symbol', addr[:8])}: unconfirmed x{checks}")
        continue

    # Fetch prices for all active positions
    price_map = {}
    for addr, pos in positions.items():
        if pos.get("unconfirmed"):
            continue
        pi = get_token_price(addr)
        if pi:
            price_map[addr] = pi

    # Process each position
    for addr, pos in positions.items():
        if pos.get("unconfirmed"):
            continue
        if addr in _selling:
            continue

        pi = price_map.get(addr, {})
        cur_price = safe_float(pi.get("price", 0))
        cur_liq = safe_float(pi.get("liquidity", 0))

        entry_price = safe_float(pos.get("entry_price", 0))
        if entry_price <= 0:
            continue

        # 3-check protection: if price is 0, increment zero count
        if cur_price <= 0:
            with pos_lock:
                if addr in state["positions"]:
                    zc = state["positions"][addr].get("zero_count", 0) + 1
                    state["positions"][addr]["zero_count"] = zc
                    if zc >= 3:
                        # Still do not delete - just skip monitoring
                        pass
            continue
        else:
            # Reset zero count on valid price
            with pos_lock:
                if addr in state["positions"]:
                    state["positions"][addr]["zero_count"] = 0

        pnl_pct = (cur_price - entry_price) / entry_price
        age_sec = now - safe_float(pos.get("opened_at_ts", now))
        age_min = age_sec / 60.0
        tier = pos.get("tier", "D")
        token_amount = safe_float(pos.get("token_amount", 0))
        symbol = pos.get("symbol", addr[:8])
        peak_price = safe_float(pos.get("peak_price", entry_price))

        # Update peak price
        if cur_price > peak_price:
            peak_price = cur_price
            with pos_lock:
                if addr in state["positions"]:
                    state["positions"][addr]["peak_price"] = cur_price

        # Update live data
        with pos_lock:
            if addr in state["positions"]:
                state["positions"][addr]["current_price"] = cur_price
                state["positions"][addr]["pnl_pct"] = pnl_pct
                state["positions"][addr]["age_min"] = age_min

        # ── Layer 1: HE1 Emergency ──
        if pnl_pct <= config.HE1_PCT:
            _exit_position(addr, pos, 1.0, "HE1_EMERGENCY", pnl_pct)
            continue

        # ── Layer 2: FAST_DUMP ──
        if pnl_pct < 0:
            drop_from_peak = (peak_price - cur_price) / peak_price if peak_price > 0 else 0
            if drop_from_peak >= abs(config.FAST_DUMP_PCT):
                # Check if drop happened recently (within FAST_DUMP_SEC)
                last_peak_ts = safe_float(pos.get("last_peak_ts", 0))
                if last_peak_ts > 0 and (now - last_peak_ts) <= config.FAST_DUMP_SEC:
                    _exit_position(addr, pos, 1.0, "FAST_DUMP", pnl_pct)
                    continue

        # Track peak timestamp for FAST_DUMP detection
        if cur_price >= peak_price:
            with pos_lock:
                if addr in state["positions"]:
                    state["positions"][addr]["last_peak_ts"] = now

        # ── Layer 3: LIQ_EMERGENCY ──
        liq_check_interval = 300  # 5 min
        last_liq_check = safe_float(pos.get("last_liq_check", 0))
        if cur_liq > 0 and (now - last_liq_check) >= liq_check_interval:
            with pos_lock:
                if addr in state["positions"]:
                    state["positions"][addr]["last_liq_check"] = now
            if cur_liq < config.LIQ_EMERGENCY:
                _exit_position(addr, pos, 1.0, "LIQ_EMERGENCY", pnl_pct)
                continue

        # ── Layer 4: Hard Stop Loss ──
        sl_rules = config.SL_RULES.get(tier, config.SL_RULES.get("D", {}))
        hard_sl = safe_float(sl_rules.get("sl_pct", -0.15))
        if pnl_pct <= hard_sl:
            _exit_position(addr, pos, 1.0, f"HARD_SL({hard_sl:.0%})", pnl_pct)
            continue

        # ── Layer 5: Time-decay SL ──
        time_decay = sl_rules.get("time_decay", [])
        td_exit = False
        for rule in sorted(time_decay, key=lambda r: r[0], reverse=True):
            after_min, tighten_to = rule[0], rule[1]
            if age_min >= after_min:
                if pnl_pct <= tighten_to:
                    _exit_position(addr, pos, 1.0,
                                   f"TIME_DECAY_SL({after_min}m/{tighten_to:.0%})", pnl_pct)
                    td_exit = True
                break
        if td_exit:
            continue

        # ── Layer 6: Timeout ──
        timeout_hrs = safe_float(sl_rules.get("timeout_hrs", 48))
        if age_min >= timeout_hrs * 60:
            _exit_position(addr, pos, 1.0, "TIMEOUT", pnl_pct)
            continue

        # ── Layer 7: Trailing Stop (after TP1) ──
        tp_tier_done = safe_int(pos.get("tp_tier", 0))
        tp_rules = config.TP_RULES.get(tier, config.TP_RULES.get("D", {}))
        trailing_pct = safe_float(tp_rules.get("trailing_pct", 0.10))

        if tp_tier_done >= 1 and peak_price > entry_price:
            drop_from_peak = (peak_price - cur_price) / peak_price
            if drop_from_peak >= trailing_pct:
                _exit_position(addr, pos, 1.0, f"TRAILING({trailing_pct:.0%})", pnl_pct)
                continue

        # ── Tiered Take Profit ──
        if tp_tier_done == 0:
            tp1_pct = safe_float(tp_rules.get("tp1_pct", 0.15))
            tp1_sell = safe_float(tp_rules.get("tp1_sell", 0.60))
            if pnl_pct >= tp1_pct:
                _exit_position(addr, pos, tp1_sell, f"TP1(+{tp1_pct:.0%})", pnl_pct)
                with pos_lock:
                    if addr in state["positions"]:
                        state["positions"][addr]["tp_tier"] = 1
                continue

        if tp_tier_done == 1:
            tp2_pct = safe_float(tp_rules.get("tp2_pct", 0.30))
            tp2_sell = safe_float(tp_rules.get("tp2_sell", 0.50))
            if pnl_pct >= tp2_pct:
                _exit_position(addr, pos, tp2_sell, f"TP2(+{tp2_pct:.0%})", pnl_pct)
                with pos_lock:
                    if addr in state["positions"]:
                        state["positions"][addr]["tp_tier"] = 2
                continue

    # Post-trade flags (background, throttled)
    for addr, pos in positions.items():
        if pos.get("unconfirmed"):
            continue
        last_rc = safe_float(pos.get("risk_last_checked", 0))
        if now - last_rc < 60:
            continue
        with pos_lock:
            if addr in state["positions"]:
                state["positions"][addr]["risk_last_checked"] = now
        _sym = pos.get("symbol", "?")
        _eliq = safe_float(pos.get("entry_liq", 0))
        _et10 = safe_float(pos.get("entry_top10", 0))
        _esp = safe_float(pos.get("entry_sniper_pct", 0))

        def _run_post_flags(_a=addr, _s=_sym, _l=_eliq, _t=_et10, _sp=_esp):
            try:
                flags = post_trade_flags(_a, _s, entry_liquidity_usd=_l,
                                         entry_top10=_t, entry_sniper_pct=_sp)
                for flag in flags:
                    feed(f"  RISK {_s}: {flag}")
                    if flag.startswith("EXIT_NOW"):
                        _exit_position(_a, None, 1.0, f"RISK_EXIT", 0)
                        break
            except Exception:
                pass

        threading.Thread(target=_run_post_flags, daemon=True).start()

    # Save positions after monitor cycle
    with pos_lock:
        save_positions()


def _exit_position(addr, pos, sell_ratio, reason, pnl_pct):
    """Execute position exit (full or partial sell)."""
    with pos_lock:
        if addr not in state["positions"]:
            return
        if addr in _selling:
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
            feed(f"  SELL FAIL {symbol} [{reason}]")
            with pos_lock:
                if addr in state["positions"]:
                    fc = state["positions"][addr].get("sell_fail_count", 0) + 1
                    state["positions"][addr]["sell_fail_count"] = fc
            return

        # Record trade
        pnl_usd = size_usd * sell_ratio * pnl_pct
        _record_trade(addr, pos, reason, pnl_pct, sell_ratio, tx_hash, pnl_usd)

        # Update or remove position
        with pos_lock:
            if sell_ratio >= 0.99:
                state["positions"].pop(addr, None)
                cooldown_map[addr] = time.time() + 1800  # 30min cooldown
            else:
                if addr in state["positions"]:
                    state["positions"][addr]["token_amount"] = token_amount - sell_amount
                    state["positions"][addr]["size_usd"] = size_usd * (1 - sell_ratio)
                    state["positions"][addr]["sell_fail_count"] = 0
            save_positions()

        pnl_display = f"{pnl_pct*100:+.1f}%"
        multiplier = 1 + pnl_pct
        feed(f"SELL {symbol} [{reason}] {sell_ratio:.0%} PnL={pnl_display} ({multiplier:.2f}x)")

        with state_lock:
            state["stats"]["sells"] += 1
            state["stats"]["net_pnl"] = round(state["stats"]["net_pnl"] + pnl_usd, 2)

    finally:
        with pos_lock:
            _selling.discard(addr)

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 9: Session Risk Control
# ══════════════════════════════════════════════════════════════════════════════

def can_enter():
    """Check if opening new positions is allowed. Returns (ok, reason)."""
    if config.PAUSED:
        return False, "PAUSED"

    # Startup cooldown
    if time.time() - _startup_ts < config.STARTUP_COOLDOWN:
        remain = int(config.STARTUP_COOLDOWN - (time.time() - _startup_ts))
        return False, f"STARTUP_COOLDOWN ({remain}s)"

    with state_lock:
        if session_risk["stopped"]:
            return False, "SESSION_STOPPED (daily loss limit)"
        if time.time() < session_risk["paused_until"]:
            remain = int(session_risk["paused_until"] - time.time())
            return False, f"SESSION_PAUSED ({remain}s)"

    with pos_lock:
        if len(state["positions"]) >= config.MAX_POSITIONS:
            return False, "MAX_POSITIONS"

    return True, "OK"


def record_loss(pnl_usd):
    """Record loss and update session risk control."""
    with state_lock:
        session_risk["consecutive_losses"] += 1
        session_risk["cumulative_loss_usd"] += abs(pnl_usd)

        if session_risk["cumulative_loss_usd"] >= config.DAILY_LOSS_LIMIT:
            session_risk["stopped"] = True
            feed(f"SESSION_STOP: daily loss ${session_risk['cumulative_loss_usd']:.2f} >= ${config.DAILY_LOSS_LIMIT}")
        elif session_risk["consecutive_losses"] >= config.MAX_CONSEC_LOSS:
            session_risk["paused_until"] = time.time() + config.PAUSE_CONSEC_SEC
            feed(f"SESSION_PAUSE: {session_risk['consecutive_losses']} consecutive losses, "
                 f"paused {config.PAUSE_CONSEC_SEC // 60}min")

    save_session()


def record_win():
    """Record win and reset consecutive losses."""
    with state_lock:
        session_risk["consecutive_losses"] = 0
    save_session()


def _record_trade(addr, pos, reason, pnl_pct, sell_ratio, tx_hash, pnl_usd):
    """Record trade in history and update session risk."""
    rand_suffix = ''.join(random.choices(string.ascii_lowercase, k=4))
    trade = {
        "tradeId": f"sell-{int(time.time())}-{addr[:4]}-{rand_suffix}",
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

    with state_lock:
        state["trades"].insert(0, trade)
        state["trades"] = state["trades"][:200]
        with trades_lock:
            save_trades()

    # Session risk update
    if pnl_pct < 0:
        record_loss(pnl_usd)
    else:
        record_win()


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 10: Hot Tokens Cache
# ══════════════════════════════════════════════════════════════════════════════

_hot_cache = {}
_hot_cache_ts = 0


def get_hot_tokens():
    """Get hot tokens cache. Refreshes every HOT_REFRESH_SEC."""
    global _hot_cache, _hot_cache_ts
    now = time.time()
    if now - _hot_cache_ts < config.HOT_REFRESH_SEC and _hot_cache:
        return _hot_cache

    try:
        data = onchainos_data("token", "hot-tokens",
                              "--chain", "solana",
                              "--ranking-type", "4",
                              "--limit", "50")
        if isinstance(data, list):
            cache = {}
            for tok in data:
                addr = tok.get("tokenAddress", "") or tok.get("address", "")
                if addr:
                    cache[addr] = {
                        "inflow": safe_float(tok.get("inflowUsd", 0) or tok.get("netInflowUsd", 0)),
                        "sym": tok.get("symbol", "?"),
                        "mc": safe_float(tok.get("marketCap", 0)),
                    }
            _hot_cache = cache
            _hot_cache_ts = now
            feed(f"  hot-tokens refresh: {len(cache)} tokens")
    except Exception:
        pass

    return _hot_cache


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 11: Position Takeover & Helpers
# ══════════════════════════════════════════════════════════════════════════════

def takeover_existing_positions():
    """Scan wallet balance at startup. Inject existing tokens as 'takeover' tier."""
    feed("=== Position Takeover: scanning wallet ===")
    wallet = get_wallet_address()
    if not wallet:
        feed("  Takeover: no wallet address")
        return

    try:
        data = onchainos_data("wallet", "balance", "--chain", "501")
        if not data:
            feed("  Takeover: no balance data")
            return

        assets = []
        if isinstance(data, dict):
            details = data.get("details", [])
            if isinstance(details, list):
                for detail in details:
                    token_assets = detail.get("tokenAssets", [])
                    if isinstance(token_assets, list):
                        assets.extend(token_assets)
        elif isinstance(data, list):
            assets = data

        taken = 0
        for asset in assets:
            addr = asset.get("tokenAddress", "")
            sym = (asset.get("symbol") or "").upper()
            bal = safe_float(asset.get("balance", 0))

            # Skip native SOL, USDC, WSOL, stablecoins
            if not addr or addr in _NEVER_TRADE:
                continue
            if sym in ("SOL", "USDC", "USDT", "WSOL"):
                continue
            if bal <= 0:
                continue

            # Skip if already tracked
            with pos_lock:
                if addr in state["positions"]:
                    continue

            # Get current price
            pi = get_token_price(addr)
            price = safe_float(pi.get("price", 0))
            mc = safe_float(pi.get("marketCap", 0))
            liq = safe_float(pi.get("liquidity", 0))

            # Skip dust
            value_usd = bal * price if price > 0 else 0
            if value_usd < config.MIN_POSITION_VALUE:
                continue

            # Inject as takeover position
            with pos_lock:
                state["positions"][addr] = {
                    "symbol": sym or asset.get("tokenSymbol", addr[:8]),
                    "address": addr,
                    "tier": "takeover",
                    "size_usd": value_usd,
                    "entry_price": price,
                    "peak_price": price,
                    "token_amount": bal,
                    "entry_mc": mc,
                    "entry_liq": liq,
                    "opened_at": datetime.now(timezone.utc).isoformat(),
                    "opened_at_ts": time.time(),
                    "tp_tier": 0,
                    "zero_count": 0,
                    "sell_fail_count": 0,
                    "last_peak_ts": time.time(),
                    "last_liq_check": 0,
                    "risk_last_checked": 0,
                    "entry_top10": 0,
                    "entry_sniper_pct": 0,
                }
            taken += 1

        with pos_lock:
            save_positions()
        feed(f"  Takeover complete: {taken} positions")

    except Exception as e:
        feed(f"  Takeover error: {e}")


def _create_position(addr, symbol, tier, size_usd, price, mc, liq,
                     token_amount, tx_hash, rc):
    """Create a new position record."""
    now = time.time()
    entry_top10 = 0
    entry_sniper = 0
    if rc and rc.get("raw"):
        info = rc["raw"].get("info", {})
        entry_top10 = safe_float(info.get("top10HoldPercent", 0))
        entry_sniper = safe_float(info.get("sniperHoldingPercent", 0))

    with pos_lock:
        state["positions"][addr] = {
            "symbol": symbol,
            "address": addr,
            "tier": tier,
            "size_usd": size_usd,
            "entry_price": price if price > 0 else 0.0001,
            "peak_price": price if price > 0 else 0.0001,
            "token_amount": token_amount,
            "entry_mc": mc,
            "entry_liq": liq,
            "tx_hash": tx_hash or "",
            "opened_at": datetime.now(timezone.utc).isoformat(),
            "opened_at_ts": now,
            "tp_tier": 0,
            "zero_count": 0,
            "sell_fail_count": 0,
            "last_peak_ts": now,
            "last_liq_check": 0,
            "risk_last_checked": 0,
            "entry_top10": entry_top10,
            "entry_sniper_pct": entry_sniper,
            "pnl_pct": 0.0,
            "age_min": 0.0,
        }
        save_positions()

    with state_lock:
        state["stats"]["buys"] += 1


def _create_unconfirmed_position(addr, symbol, tier, size_usd, price, mc):
    """Create an unconfirmed position (swap timeout)."""
    now = time.time()
    with pos_lock:
        state["positions"][addr] = {
            "symbol": symbol,
            "address": addr,
            "tier": tier,
            "size_usd": size_usd,
            "entry_price": price if price > 0 else 0.0001,
            "peak_price": price if price > 0 else 0.0001,
            "token_amount": 0,
            "entry_mc": mc,
            "entry_liq": 0,
            "opened_at": datetime.now(timezone.utc).isoformat(),
            "opened_at_ts": now,
            "tp_tier": 0,
            "zero_count": 0,
            "sell_fail_count": 0,
            "last_peak_ts": now,
            "last_liq_check": 0,
            "risk_last_checked": 0,
            "entry_top10": 0,
            "entry_sniper_pct": 0,
            "unconfirmed": True,
            "unconfirmed_ts": now,
            "unconfirmed_checks": 0,
        }
        save_positions()


def _k1_pump_guard(addr, max_pct):
    """Check if 1m candle shows >max_pct pump (chasing protection)."""
    try:
        data = onchainos_data("market", "candles",
                              "--chain", "solana",
                              "--address", addr,
                              "--bar", "1m")
        if isinstance(data, list) and len(data) >= 2:
            k1 = data[-1]
            k1_open = safe_float(k1.get("o", 0))
            k1_close = safe_float(k1.get("c", 0))
            if k1_open > 0:
                k1_pct = (k1_close - k1_open) / k1_open * 100
                if k1_pct > max_pct:
                    return True
    except Exception:
        pass
    return False

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 12: Web Dashboard
# ══════════════════════════════════════════════════════════════════════════════

_dashboard_html_path = PROJECT_DIR / "dashboard.html"


class DashboardHandler(BaseHTTPRequestHandler):
    """Simple HTTP handler for dashboard."""

    def log_message(self, *args):
        pass  # Suppress default access logs

    def do_GET(self):
        if self.path == "/api/state":
            self._serve_api()
        elif self.path in ("/", "/index.html"):
            self._serve_html()
        else:
            self.send_response(404)
            self.end_headers()

    def _serve_api(self):
        """Serve JSON state for dashboard."""
        with state_lock:
            snap = {
                "feed": list(state["feed"]),
                "stats": dict(state["stats"]),
            }
        with pos_lock:
            snap["positions"] = dict(state["positions"])
        with trades_lock:
            snap["trades"] = list(state["trades"][:50])
        snap["session_risk"] = dict(session_risk)
        snap["config"] = {
            "paused": config.PAUSED,
            "paper_trade": config.PAPER_TRADE,
            "max_positions": config.MAX_POSITIONS,
            "night_mode": is_night(),
        }

        body = json.dumps(snap, ensure_ascii=False, default=str).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _serve_html(self):
        """Serve dashboard HTML."""
        try:
            html = _dashboard_html_path.read_text()
        except FileNotFoundError:
            html = ("<html><body><h1>SOL Meme Hunter v6.0 Dashboard</h1>"
                    "<p>dashboard.html not found. API available at /api/state</p>"
                    "</body></html>")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode())


def start_dashboard():
    """Start dashboard HTTP server in daemon thread."""
    if not config.DASHBOARD_ENABLED:
        return
    try:
        HTTPServer.allow_reuse_address = True
        server = HTTPServer(("0.0.0.0", config.DASHBOARD_PORT), DashboardHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        feed(f"Dashboard: http://localhost:{config.DASHBOARD_PORT}")
    except Exception as e:
        feed(f"Dashboard failed to start: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 13: Scanner Loop & Main Entry Point
# ══════════════════════════════════════════════════════════════════════════════

_shutdown = False


def scanner_loop():
    """Main scanning loop. Runs Tier A/B/D on schedule."""
    last_a = 0
    last_b = 0
    last_d = 0
    last_balance = 0
    last_daily_reset = datetime.now(timezone.utc).date()

    while not _shutdown:
        try:
            now = time.time()

            # Daily reset at UTC midnight
            today = datetime.now(timezone.utc).date()
            if today != last_daily_reset:
                last_daily_reset = today
                with state_lock:
                    old_loss = session_risk["cumulative_loss_usd"]
                    session_risk["consecutive_losses"] = 0
                    session_risk["cumulative_loss_usd"] = 0.0
                    session_risk["paused_until"] = 0
                    session_risk["stopped"] = False
                save_session()
                feed(f"  New day {today}, reset session risk (yesterday loss=${old_loss:.2f})")

            # Balance check
            if now - last_balance >= config.BALANCE_CHECK_SEC:
                last_balance = now
                sol_bal = get_sol_balance()
                sol_price = get_sol_price()
                usd_bal = sol_bal * sol_price if sol_price > 0 else 0
                with pos_lock:
                    n_pos = len(state["positions"])
                daily_loss = session_risk.get("cumulative_loss_usd", 0)
                feed(f"SOL: {sol_bal:.4f} (~${usd_bal:.2f}) | "
                     f"Daily PnL: ${-daily_loss:+.2f} | Positions: {n_pos}")

            # Tier A: Smart Money (every SM_REFRESH_SEC)
            if now - last_a >= config.SM_REFRESH_SEC:
                last_a = now
                try:
                    process_tier_a()
                except Exception as e:
                    feed(f"Tier A error: {e}")

            # Tier B: Graduation Ambush (every GRADUATED_REFRESH_SEC)
            if now - last_b >= config.GRADUATED_REFRESH_SEC:
                last_b = now
                try:
                    process_tier_b()
                except Exception as e:
                    feed(f"Tier B error: {e}")

            # Tier D: Hot Momentum (every HOT_REFRESH_SEC)
            if now - last_d >= config.HOT_REFRESH_SEC:
                last_d = now
                try:
                    process_tier_d()
                except Exception as e:
                    feed(f"Tier D error: {e}")

            with state_lock:
                state["stats"]["cycle"] += 1

            # Clean expired cooldowns
            expired = [k for k, v in cooldown_map.items() if now >= v]
            for k in expired:
                del cooldown_map[k]

            time.sleep(config.MONITOR_SEC)

        except Exception as e:
            feed(f"Scanner loop error: {e}")
            time.sleep(5)


def main():
    """Main entry point."""
    global _shutdown

    print("=" * 60)
    print("  SOL MEME HUNTER v6.0")
    print("  3-Tier Architecture (A/B/D) + Dynamic Scoring")
    print("  Swap: swap swap -> contract-call -> history")
    print("=" * 60)

    # 1. Check onchainos
    try:
        ver = onchainos_run("--version")
        feed(f"onchainos version: {ver.get('data', ver.get('msg', 'unknown'))}")
    except Exception:
        feed("WARNING: onchainos --version failed")

    # 2. Get wallet address
    wallet = get_wallet_address()
    if not wallet:
        feed("FATAL: No wallet address. Run: onchainos wallet login")
        sys.exit(1)
    feed(f"Wallet: {wallet}")

    # 3. Load state
    load_positions()
    load_acted()
    load_session()
    load_trades()

    with pos_lock:
        n_pos = len(state["positions"])
    feed(f"  Loaded: {n_pos} positions, {len(acted)} acted, {len(state['trades'])} trades")

    # 4. Position takeover
    takeover_existing_positions()

    # 5. Print startup banner
    night = is_night()
    feed(f"Mode: {'PAPER' if config.PAPER_TRADE else 'LIVE'} | "
         f"Night: {night} | PAUSED: {config.PAUSED}")
    feed(f"Tier A: ${config.TIER_A_SIZE_DAY}(day)/${config.TIER_A_SIZE_NIGHT}(night) | "
         f"MC ${config.TIER_A_MC_MIN:,}-${config.TIER_A_MC_MAX:,}")
    feed(f"Tier B: ${config.TIER_B_SIZE_DAY}(day)/${config.TIER_B_SIZE_NIGHT}(night) | "
         f"stage={config.TIER_B_STAGE} | MC ${config.TIER_B_MC_MIN:,}-${config.TIER_B_MC_MAX:,}")
    feed(f"Tier D: base=${config.TIER_D_SIZE_BASE} dynamic | "
         f"MC ${config.TIER_D_MC_MIN:,}-${config.TIER_D_MC_MAX:,} | score>={config.TIER_D_SCORE_THRESHOLD}")
    feed(f"Risk: MAX_POS={config.MAX_POSITIONS} | DAILY_LOSS=${config.DAILY_LOSS_LIMIT} | "
         f"CONSEC_PAUSE={config.MAX_CONSEC_LOSS}x/{config.PAUSE_CONSEC_SEC}s")
    feed(f"Scan intervals: SM={config.SM_REFRESH_SEC}s B={config.GRADUATED_REFRESH_SEC}s "
         f"D={config.HOT_REFRESH_SEC}s MON={config.MONITOR_SEC}s")
    feed(f"Existing positions: {n_pos}")
    print("=" * 60)

    # 6. Start dashboard
    start_dashboard()

    # 7. Start monitor thread
    monitor_thread = threading.Thread(target=monitor_positions, daemon=True)
    monitor_thread.start()

    # 8. Signal handlers
    def shutdown_handler(signum, frame):
        global _shutdown
        _shutdown = True
        feed(f"Received signal {signum}, shutting down...")
        with pos_lock:
            n = len(state["positions"])
            save_positions()
        if n > 0:
            feed(f"  WARNING: {n} position(s) still open on-chain!")
            feed(f"  Positions saved to {config.POSITIONS_FILE}")
        else:
            feed("  No open positions.")
        save_session()
        feed("  Shutdown complete.")
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    # 9. Run scanner loop (blocks)
    scanner_loop()


if __name__ == "__main__":
    main()
