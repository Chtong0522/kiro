#!/usr/bin/env python3
"""
SOL Meme Hunter v5 — 三层预测架构

v5 vs v4.5 核心改变：
  v4.5 追涨逻辑：等 hot-tokens inflowUsd 出现才买 → 信号已经滞后，追高亏损
  v5 预判逻辑：在价格爆发前埋伏，三层流水线：
    Tier A（智能钱包跟单）：onchainos tracker activities 实时追踪 SM 钱包聚集买入信号
              多钱包 10 分钟内同步买入 → 强信号直接买；单钱包 → 需 hot-tokens 确认
    Tier B（MIGRATING 毕业伏击）：bonding curve 70-97% 时埋伏，等待毕业后价格爆发
              dev 已售出 + insiders<30% + top10<40% + 交易活跃 = 健康毕业候选
    Tier C（NEW 机器人触发抢跑）：bonding 3-10% 极早期，dev 已抛 + 极少持有者
              3 分钟内不涨就全清，快进快出抢机器人买盘

  三层联动：Tier A 作为涨势确认，Tier B/C 作为早期布局
  夜间（UTC 14-22）Tier C 禁止，Tier A/B 仓位缩减
"""

import subprocess
import json
import time
import os
from datetime import datetime, timezone

os.environ["PATH"] = "/home/ubuntu/.local/bin:/home/ubuntu/.nvm/versions/node/v22.22.2/bin:" + os.environ.get("PATH", "")

# ─── 核心常量 ────────────────────────────────────────────────────────────────
WALLET    = "AXBCfbioEHiJ48ejNp5feEzWt2iHFLUDNMk27t5vXWLE"
USDC_ADDR = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
LOG_FILE  = "/tmp/meme_hunter_v4.log"
ACTED_FILE = "/tmp/meme_hunter_acted.json"
SESSION_FILE = "/tmp/meme_hunter_session.json"

# 安全熔断
SAFETY_LINE_DAY   = 80
SAFETY_LINE_NIGHT = 150
DAILY_LOSS_LIMIT  = 15   # 触发后需重启才能恢复（不会自动日重置）
MAX_POSITIONS     = 6
MAX_TIER_C_DAY    = 4
TIER_C_COOLDOWN   = 7200  # 2小时冷却（连续2次亏损后）

# 仓位大小
TIER_A_SIZE  = 8
TIER_B_SIZE  = 5
TIER_C_SIZE  = 3
TIER_A_NIGHT = 5
TIER_B_NIGHT = 3

# Tier A 过滤（智能钱包跟单）
SM_MIN_MC    = 50000
SM_MAX_MC    = 2000000
SM_MIN_LIQ   = 5000
SM_MAX_LIQ   = 200000
SM_WINDOW    = 600   # 10 分钟内多钱包信号视为强信号

# Tier B 过滤（MIGRATING 毕业伏击）
MIN_BONDING    = 70
MAX_BONDING    = 97
MAX_INSIDERS   = 30
MAX_TOP10_B    = 40
TIER_B_MIN_MC  = 30000   # MC 至少 $30k，过滤极小垃圾币
TIER_B_MIN_HOLDERS = 50  # 至少 50 个持有人，说明有真实社区
TIER_B_MIN_APED    = 2   # 至少 2 个 OKX 用户跟单（提高置信度）

# Tier C 过滤（NEW 机器人触发）
MIN_BONDING_C   = 3
MAX_BONDING_C   = 10
MAX_TOKEN_AGE_C = 5   # 最多 5 分钟

# 刷新间隔（秒）
HOT_REFRESH       = 300
SM_REFRESH        = 30
MIGRATING_REFRESH = 60
NEW_REFRESH       = 15

# ─── v5.1 策略常量 ────────────────────────────────────────────────────────────
# 追踪止损：TP1 后从峰值回撤触发清仓
TRAIL_DISTANCE_A = 0.12   # 12% drawdown from peak after TP1 → exit Tier A
TRAIL_DISTANCE_B = 0.10   # 10% drawdown from peak after TP1 → exit Tier B

# 时间衰减止损：持仓时间过长但未达硬止损时提前离场
# Fix 2: 60min threshold must be less negative (stricter) than 30min — exit if still underwater at all
TIME_DECAY_SL = [(30, -0.08), (60, -0.01)]  # (minutes_held, pnl_threshold)

# 会话连续亏损熔断
SESSION_CONSEC_LOSS_MAX = 3
SESSION_CONSEC_PAUSE    = 600   # 10 分钟


# ─── v5.1 模块级状态 ──────────────────────────────────────────────────────────
# 信号冷却去重：卖出后 30 分钟内不重新买同一 token
cooldown_until: dict = {}

# 会话连续亏损状态
session_state = {'consecutive_losses': 0, 'pause_until': 0.0}


def load_session_state():
    """加载 session_state，如文件不存在则返回默认值"""
    try:
        if os.path.exists(SESSION_FILE):
            with open(SESSION_FILE, "r") as f:
                data = json.load(f)
            # Reset pause_until if it already expired (don't re-apply stale pauses)
            if data.get('pause_until', 0) < time.time():
                data['pause_until'] = 0.0
            return data
    except Exception:
        pass
    return {'consecutive_losses': 0, 'pause_until': 0.0}


def save_session_state():
    """保存 session_state 到磁盘"""
    try:
        with open(SESSION_FILE, "w") as f:
            json.dump(session_state, f)
    except Exception:
        pass


# ─── 工具函数 ────────────────────────────────────────────────────────────────

def log(msg):
    """带时间戳输出到 LOG_FILE 和 stdout"""
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def run(cmd, timeout=30):
    """执行 shell 命令，返回 stdout.strip() 或空字符串"""
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception:
        return ""


def jparse(raw):
    """安全 JSON 解析，出错返回 {}"""
    try:
        return json.loads(raw)
    except Exception:
        return {}


def sf(v):
    """安全 float 转换，出错返回 0"""
    try:
        return float(v) if v is not None else 0.0
    except Exception:
        return 0.0


def is_night_time():
    """UTC 14:00-22:00 为夜间模式（北京时间 22:00-06:00）"""
    utc_hour = datetime.now(timezone.utc).hour
    return 14 <= utc_hour < 22


def get_safety_line():
    """根据时间段返回安全线"""
    return SAFETY_LINE_NIGHT if is_night_time() else SAFETY_LINE_DAY


# ─── acted 持久化 ─────────────────────────────────────────────────────────────

def load_acted():
    """
    加载已处理地址，自动过期超过 12 小时的记录。
    返回 dict {addr: timestamp}
    """
    try:
        if os.path.exists(ACTED_FILE):
            with open(ACTED_FILE, "r") as f:
                raw = json.load(f)
            now = time.time()
            # 兼容旧格式（set/list）和新格式（dict）
            if isinstance(raw, dict) and "acted" in raw:
                # 旧格式：{"acted": [...]}
                entries = raw["acted"]
                if isinstance(entries, list):
                    data = {addr: now for addr in entries}
                else:
                    data = entries
            elif isinstance(raw, dict):
                data = raw
            else:
                data = {}
            # 过期 12h (43200s) 的条目
            cleaned = {addr: ts for addr, ts in data.items() if now - float(ts) < 43200}
            log(f"  acted 加载: {len(cleaned)} 个有效记录 (共{len(data)})")
            return cleaned
    except Exception as e:
        log(f"  acted 加载失败: {e}")
    return {}


def save_acted(acted):
    """保存 acted dict 到文件"""
    try:
        with open(ACTED_FILE, "w") as f:
            json.dump(acted, f)
    except Exception as e:
        log(f"  acted 保存失败: {e}")


def is_acted(acted, addr):
    """检查地址是否在 acted 中且未过期（12h）"""
    if addr not in acted:
        return False
    return time.time() - float(acted[addr]) < 43200


# ─── 余额与价格 ───────────────────────────────────────────────────────────────

def get_usdc_balance():
    """查询 USDC 余额，返回 float"""
    out = run("onchainos wallet balance --chain solana", timeout=20)
    d = jparse(out)
    assets = d.get("data", {}).get("details", [{}])
    if assets:
        for a in assets[0].get("tokenAssets", []):
            if a.get("symbol") == "USDC":
                return sf(a.get("balance", 0))
    return 0.0


def get_token_price(addr):
    """查询 token 当前价格，返回 float 或 0"""
    out = run(f"onchainos token price-info --address {addr} --chain solana", timeout=15)
    d = jparse(out)
    return sf(d.get("data", {}).get("price"))


def load_existing_positions():
    """
    持仓接管：启动时扫描钱包，跳过 USDC/SOL/WSOL，
    其余 token 注入 positions，tier='takeover'，entry_time=now-3600
    """
    log("=== 持仓接管：扫描已有持仓 ===")
    positions = {}
    out = run("onchainos wallet balance --chain solana", timeout=20)
    d = jparse(out)
    assets = d.get("data", {}).get("details", [{}])
    if not assets:
        log("  持仓接管：未获取到余额数据")
        return positions
    skip_syms = {"USDC", "SOL", "WSOL"}
    for a in assets[0].get("tokenAssets", []):
        sym     = a.get("symbol", "?")
        addr    = a.get("tokenContractAddress", "")
        bal     = sf(a.get("balance", 0))
        val_usd = sf(a.get("usdValue", 0))
        if sym in skip_syms or not addr or val_usd < 0.5:
            continue
        entry_price = 0
        for _try in range(3):
            entry_price = get_token_price(addr)
            if entry_price > 0:
                break
            time.sleep(1)
        if entry_price <= 0:
            log(f"  WARN: {sym} takeover price=0 after 3 retries, storing entry_price=0 amt_tokens=0")
        positions[addr] = {
            "sym":           sym,
            "amount_usd":    val_usd,
            "amount_tokens": bal,
            "entry_price":   entry_price if entry_price > 0 else 0.0,
            "entry_time":    time.time() - 3600,
            "tier":          "takeover",
            "tp1_done":      False,
            "tp2_done":      False,
            "tp3_done":      False,
            "holders_at_entry": 0,
            "peak_price":    entry_price if entry_price > 0 else 0.0,
            "last_liq_check": 0,
            "zero_price_count": 0,
        }
        log(f"  接管 {sym}: {bal:.2f}枚 ~${val_usd:.2f} entry=${entry_price:.8f} addr={addr[:12]}...")
    log(f"  接管完成，共 {len(positions)} 个持仓")
    return positions


# ─── 每日 PnL 状态 ────────────────────────────────────────────────────────────

def reset_daily_if_needed(daily_state):
    """检查 UTC 日期，新的一天则重置 daily_state（注意：halted 标志不重置，需重启清除）"""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if daily_state["date"] != today:
        log(f"  新的一天 {today}，重置 daily_state（昨日 PnL={daily_state['realized_pnl']:+.2f}）")
        daily_state["date"] = today
        daily_state["realized_pnl"] = 0.0
        daily_state["tier_c_count"] = 0
        daily_state["tier_c_consecutive_losses"] = 0
        daily_state["tier_c_pause_until"] = 0.0
        # halted 标志不重置 — 需要人工重启脚本才能恢复


def add_realized_pnl(daily_state, pnl_usd):
    """记录已实现 PnL"""
    daily_state["realized_pnl"] += pnl_usd
    log(f"  已实现 PnL 更新: {pnl_usd:+.2f} → 今日合计 {daily_state['realized_pnl']:+.2f}")


# ─── 交易执行 ─────────────────────────────────────────────────────────────────

def sell_token(addr, sym, amount_tokens, reason, max_retries=3):
    """
    执行卖出，失败自动重试最多 max_retries 次，退避 5/10/15 秒。
    返回 (True, tx_hash) 或 (False, '')
    """
    for attempt in range(1, max_retries + 1):
        log(f"  sell [{attempt}/{max_retries}] {sym} {amount_tokens:.6f} tokens | 原因: {reason}")
        cmd = (
            f"onchainos swap execute "
            f"--from {addr} --to {USDC_ADDR} "
            f"--readable-amount {amount_tokens:.6f} "
            f"--chain solana --wallet {WALLET} "
            f"--gas-level fast --slippage 15"
        )
        out = run(cmd, timeout=90)
        d = jparse(out)
        tx = d.get("data", {}).get("swapTxHash", "")
        if tx:
            log(f"  卖出成功 {sym} | TX: https://solscan.io/tx/{tx}")
            return True, tx
        err = out[:150] if out else "无返回"
        log(f"  卖出失败 [{attempt}/{max_retries}] {sym} | {err}")
        if attempt < max_retries:
            time.sleep(5 * attempt)
    log(f"  卖出彻底失败 {sym}，已重试 {max_retries} 次，需人工处理")
    return False, ""


def execute_swap(from_addr, to_addr, amount_readable, is_sell=False):
    """
    执行 swap：
      买入：from=USDC_ADDR, to=token
      卖出：from=token, to=USDC_ADDR
    返回 (True, tx_hash) 或 (False, '')
    """
    cmd = (
        f"onchainos swap execute "
        f"--from {from_addr} --to {to_addr} "
        f"--readable-amount {amount_readable:.6f} "
        f"--chain solana --wallet {WALLET} "
        f"--gas-level fast --slippage 15"
    )
    out = run(cmd, timeout=90)
    d = jparse(out)
    tx = d.get("data", {}).get("swapTxHash", "")
    if tx:
        log(f"  swap 成功 | TX: https://solscan.io/tx/{tx}")
        return True, tx
    log(f"  swap 失败: {out[:200]}")
    return False, ""


# ─── Tier A：智能钱包跟单信号引擎 ─────────────────────────────────────────────
#
# sm_buys[token_addr] = {
#     'wallets': set(),      # 买入的唯一 SM 钱包地址
#     'first_seen': float,   # 第一个 SM 钱包买入时间戳
#     'last_seen': float,    # 最近一次 SM 钱包买入时间戳
#     'mc': float,
#     'sym': str,
# }

def fetch_sm_activities(sm_buys):
    """
    调用 onchainos tracker activities，更新 sm_buys dict。
    返回信号列表：[(addr, signal_strength, n_wallets, mc, sym), ...]
      signal_strength: 'STRONG' (>=2 钱包 10 分钟内) 或 'NORMAL' (1 钱包)
    同时清理超过 1 小时的陈旧条目。
    """
    cmd = (
        "onchainos tracker activities "
        "--tracker-type smart_money --chain solana --trade-type 1 "
        "--min-volume 500 --min-market-cap 50000 --max-market-cap 2000000 "
        "--min-liquidity 5000 --max-liquidity 200000"
    )
    out = run(cmd, timeout=30)
    d = jparse(out)
    items = d.get("data", [])
    if isinstance(items, dict):
        items = items.get("list", [])

    now = time.time()
    for item in (items or []):
        addr   = item.get("tokenContractAddress", "")
        sym    = item.get("tokenSymbol", "?")
        mc     = sf(item.get("marketCap", 0))
        wallet = item.get("walletAddress", "")
        if not addr:
            continue
        if addr not in sm_buys:
            sm_buys[addr] = {
                "wallets":    set(),
                "first_seen": now,
                "last_seen":  now,
                "mc":         mc,
                "sym":        sym,
            }
        entry = sm_buys[addr]
        if wallet:
            entry["wallets"].add(wallet)
        entry["last_seen"] = now
        if mc > 0:
            entry["mc"] = mc
        if sym != "?":
            entry["sym"] = sym

    # 清理超过 1 小时的条目 (Fix 4: use last_seen not first_seen for staleness)
    stale = [a for a, e in sm_buys.items() if now - e["last_seen"] > 3600]
    for a in stale:
        del sm_buys[a]

    # 生成信号列表
    signals = []
    for addr, entry in sm_buys.items():
        n = len(entry["wallets"])
        window = entry["last_seen"] - entry["first_seen"]
        if n >= 2 and window <= SM_WINDOW:
            strength = "STRONG"
        elif n >= 1:
            strength = "NORMAL"
        else:
            continue
        signals.append((addr, strength, n, entry["mc"], entry["sym"]))

    return signals


# ─── Hot-tokens 缓存 ─────────────────────────────────────────────────────────

_hot_tokens_cache = {}
_hot_tokens_ts = 0


def get_hot_tokens():
    """
    获取 hot-tokens 列表，缓存 HOT_REFRESH 秒。
    返回 {addr: {inflow, sym, mc}}
    """
    global _hot_tokens_cache, _hot_tokens_ts
    now = time.time()
    if now - _hot_tokens_ts < HOT_REFRESH and _hot_tokens_cache:
        return _hot_tokens_cache

    out = run("onchainos token hot-tokens --chain solana --ranking-type 4 --limit 50", timeout=25)
    d = jparse(out)
    items = d.get("data", [])
    if isinstance(items, dict):
        items = items.get("list", [])

    result = {}
    for t in (items or []):
        addr = t.get("tokenContractAddress", "")
        if addr:
            result[addr] = {
                "inflow": sf(t.get("inflowUsd", 0)),
                "sym":    t.get("tokenSymbol", "?"),
                "mc":     sf(t.get("marketCap", 0)),
            }

    _hot_tokens_cache = result
    _hot_tokens_ts = now
    log(f"  hot-tokens 刷新: {len(result)} 个")
    return result


def get_hot_inflow(hot_cache, addr):
    """从缓存中返回 inflow，未命中返回 0"""
    return hot_cache.get(addr, {}).get("inflow", 0)


# ─── v5.1：K1 pump guard + TOP_ZONE filter ───────────────────────────────────

def check_k1_pump(addr, sym="?"):
    """
    查询最近 1 分钟 K 线，若涨幅 > +15% 则返回 True（防追高）。
    API 失败时 fail-open 返回 False。
    """
    try:
        out = run(f"onchainos market kline --chain solana --address {addr} --bar 1m", timeout=15)
        d = jparse(out)
        candles = d.get("data", [])
        if not candles:
            return False
        last = candles[-1]
        close = sf(last.get("close", 0))
        open_ = sf(last.get("open", close))
        if open_ <= 0:
            return False
        pct = (close - open_) / open_
        if pct > 0.15:
            log(f"  K1_PUMP_GUARD: skip {sym} 1m={pct:.1%}")
            return True
        return False
    except Exception as e:
        log(f"  WARN check_k1_pump: {e} (fail-open)")
        return False


def check_top_zone(addr, cur_price, sym="?"):
    """
    取最近 12 根 5m K 线（= 1h），若当前价 > 85% of 1h high → True（处于顶部区）。
    API 失败时 fail-open 返回 False。
    """
    try:
        out = run(f"onchainos market kline --chain solana --address {addr} --bar 5m", timeout=15)
        d = jparse(out)
        candles = d.get("data", [])
        if not candles:
            return False
        recent = candles[-12:] if len(candles) >= 12 else candles
        h1_high = max(sf(c.get("high", 0)) for c in recent)
        if h1_high <= 0:
            return False
        pct = cur_price / h1_high
        if pct > 0.85:
            log(f"  TOP_ZONE: {sym} at {pct:.0%} of 1h high")
            return True
        return False
    except Exception as e:
        log(f"  WARN check_top_zone: {e} (fail-open)")
        return False


# ─── Tier B：MIGRATING 毕业伏击信号引擎 ──────────────────────────────────────

def fetch_migrating_tokens():
    """
    调用 onchainos memepump tokens MIGRATING，过滤健康候选。
    过滤条件：
      - bondingPercent 70-97
      - devHoldingsPercent == 0 (dev 已出局)
      - insidersPercent < 30
      - top10HoldingsPercent < 40
      - aped >= 1 (至少 1 个 SM 钱包跟单)
      - 有社交媒体 (x OR telegram OR website 非空)
      - buyTxCount1h > sellTxCount1h (买盘强于卖盘)
    返回候选列表
    """
    cmd = (
        "onchainos memepump tokens "
        "--chain solana --stage MIGRATING --dev-sell-all true "
        f"--min-bonding-percent {MIN_BONDING} --max-bonding-percent {MAX_BONDING}"
    )
    out = run(cmd, timeout=30)
    d = jparse(out)
    items = d.get("data", [])
    if isinstance(items, dict):
        items = items.get("list", [])

    candidates = []
    for t in (items or []):
        bonding   = sf(t.get("bondingPercent", 0))
        dev_hold  = sf(t.get("tags", {}).get("devHoldingsPercent", 1))
        insiders  = sf(t.get("tags", {}).get("insidersPercent", 100))
        top10     = sf(t.get("tags", {}).get("top10HoldingsPercent", 100))
        aped      = int(sf(t.get("aped", 0)))
        buy_tx    = int(sf(t.get("market", {}).get("buyTxCount1h", 0)))
        sell_tx   = int(sf(t.get("market", {}).get("sellTxCount1h", 0)))
        social    = t.get("social", {})
        has_social = any([
            social.get("x", ""),
            social.get("telegram", ""),
            social.get("website", ""),
        ])
        addr = t.get("tokenAddress", "")
        sym  = t.get("symbol", "?")
        mc   = sf(t.get("market", {}).get("marketCapUsd", 0))

        if not addr:
            continue
        if not (MIN_BONDING <= bonding <= MAX_BONDING):
            continue
        if dev_hold != 0:
            continue
        if insiders >= MAX_INSIDERS:
            continue
        if top10 >= MAX_TOP10_B:
            continue
        if aped < TIER_B_MIN_APED:
            continue
        if mc < TIER_B_MIN_MC:
            continue
        holders = int(sf(t.get("tags", {}).get("totalHolders", 0)))
        if holders < TIER_B_MIN_HOLDERS:
            continue
        if not has_social:
            continue
        if buy_tx <= sell_tx:
            continue

        t["tokenAddress"] = addr
        t["_sym"] = sym
        t["_mc"]  = mc
        candidates.append(t)

    return candidates


# ─── Tier C：NEW 机器人触发抢跑信号引擎 ──────────────────────────────────────

def fetch_new_tokens():
    """
    调用 onchainos memepump tokens NEW，过滤极早期候选。
    过滤条件：
      - bondingPercent 3-10
      - devHoldingsPercent == 0
      - totalHolders >= 2
      - buyTxCount1h > 5
    返回候选列表
    """
    cmd = (
        "onchainos memepump tokens "
        "--chain solana --stage NEW --dev-sell-all true "
        f"--min-bonding-percent {MIN_BONDING_C} --max-bonding-percent {MAX_BONDING_C} "
        f"--max-token-age {MAX_TOKEN_AGE_C}"
    )
    out = run(cmd, timeout=30)
    d = jparse(out)
    items = d.get("data", [])
    if isinstance(items, dict):
        items = items.get("list", [])

    candidates = []
    for t in (items or []):
        bonding   = sf(t.get("bondingPercent", 0))
        dev_hold  = sf(t.get("tags", {}).get("devHoldingsPercent", 1))
        holders   = int(sf(t.get("tags", {}).get("totalHolders", 0)))
        buy_tx    = int(sf(t.get("market", {}).get("buyTxCount1h", 0)))
        addr = t.get("tokenAddress", "")
        sym  = t.get("symbol", "?")
        mc   = sf(t.get("market", {}).get("marketCapUsd", 0))

        if not addr:
            continue
        if not (MIN_BONDING_C <= bonding <= MAX_BONDING_C):
            continue
        if dev_hold != 0:
            continue
        if mc < 3000:   # MC 至少 $3000，过滤极小垃圾币
            continue
        if holders < 2:
            continue
        if buy_tx <= 5:
            continue

        t["tokenAddress"] = addr
        t["_sym"] = sym
        t["_mc"]  = mc
        candidates.append(t)

    return candidates


# ─── 安全检查 ─────────────────────────────────────────────────────────────────

def security_check(addr):
    """
    onchainos security token-scan，返回 (True, 'PASS') 或 (False, reason)
    拒绝：isHoneypot / riskLevel==HIGH / isWash / isMintable
    """
    out = run(f"onchainos security token-scan --tokens '501:{addr}'", timeout=20)
    d = jparse(out)
    items = d.get("data", [])
    if not items:
        log(f"  WARN security_check: no data for {addr[:12]}, passing (fail-open)")
        return True, "PASS (no data)"
    r = items[0] if isinstance(items, list) else items
    if r.get("isHoneypot"):
        return False, "honeypot"
    if r.get("riskLevel") == "HIGH":
        return False, "HIGH_risk"
    if r.get("isWash"):
        return False, "wash_trading"
    if r.get("isMintable"):
        return False, "mintable"
    return True, "PASS"


def check_sm_exiting(addr):
    """
    gmgn-cli token traders，检查 SM 是否正在出货。
    如果顶部 smart_degen 钱包 sell_volume_cur > buy_volume_cur * 1.3 → True
    """
    out = run(
        f"gmgn-cli token traders --chain sol --address {addr} "
        f"--tag smart_degen --order-by sell_volume_cur --direction desc --limit 5 --raw",
        timeout=20
    )
    d = jparse(out)
    traders = d.get("list", [])
    if not traders:
        log(f"  WARN: check_sm_exiting returned empty traders for {addr} — treating as not-exiting")
        return False
    top = traders[0]
    sv = sf(top.get("sell_volume_cur"))
    bv = sf(top.get("buy_volume_cur"))
    if bv > 0 and sv > bv * 1.3:
        log(f"  SM 出货确认: sell=${sv:.0f} > buy=${bv:.0f}*1.3")
        return True
    return False


# ─── 入场守卫 ─────────────────────────────────────────────────────────────────

def entry_guard(positions, daily_state, usdc, tier, addr=None):
    """
    所有入场前检查，返回 (True, size) 或 (False, reason)
    """
    # v5.1: session consecutive loss pause
    if time.time() < session_state['pause_until']:
        remaining = session_state['pause_until'] - time.time()
        return False, f"session_paused {remaining:.0f}s left"

    # v5.1: signal cooldown dedup
    if addr and time.time() < cooldown_until.get(addr, 0):
        remaining = cooldown_until[addr] - time.time()
        return False, f"cooldown {remaining:.0f}s left"

    safety = get_safety_line()
    night = is_night_time()

    if usdc < safety:
        return False, f"safety_line ${usdc:.1f}<${safety}"
    if len(positions) >= MAX_POSITIONS:
        return False, f"max_positions {len(positions)}/{MAX_POSITIONS}"
    if daily_state.get("halted") or daily_state["realized_pnl"] < -DAILY_LOSS_LIMIT:
        return False, f"halted/daily_loss_limit ${daily_state['realized_pnl']:.2f}"

    tier_upper = tier.upper() if isinstance(tier, str) else ""

    if "C" in tier_upper:
        if night:
            return False, "tier_c_disabled_night"
        if daily_state["tier_c_count"] >= MAX_TIER_C_DAY:
            return False, f"tier_c_day_limit {daily_state['tier_c_count']}/{MAX_TIER_C_DAY}"
        if time.time() < daily_state["tier_c_pause_until"]:
            remaining = daily_state["tier_c_pause_until"] - time.time()
            return False, f"tier_c_cooldown {remaining/60:.0f}min left"
        size = TIER_C_SIZE
    elif "B" in tier_upper:
        size = TIER_B_NIGHT if night else TIER_B_SIZE
    elif "A" in tier_upper or "takeover" in tier_upper.lower():
        size = TIER_A_NIGHT if night else TIER_A_SIZE
    else:
        size = TIER_A_SIZE

    if usdc < size:
        return False, f"insufficient_usdc ${usdc:.1f}<${size}"

    return True, size


# ─── 持仓监控与 TP/SL ────────────────────────────────────────────────────────

def _record_sell_outcome(pnl_usd, addr):
    """
    记录卖出结果：更新 session 连续亏损计数 + 设置冷却。
    在每一次 sell 成功后调用。
    """
    # cooldown dedup: 30 分钟内不重入
    cooldown_until[addr] = time.time() + 1800

    # session consecutive loss tracking
    if pnl_usd < 0:
        session_state['consecutive_losses'] += 1
        if session_state['consecutive_losses'] >= SESSION_CONSEC_LOSS_MAX:
            session_state['pause_until'] = time.time() + SESSION_CONSEC_PAUSE
            log(f"  SESSION_PAUSE: {SESSION_CONSEC_LOSS_MAX} consecutive losses, pausing {SESSION_CONSEC_PAUSE//60}min")
    else:
        session_state['consecutive_losses'] = 0
    save_session_state()

def check_positions(positions, daily_state):
    """
    主持仓监控，按层级规则执行止盈止损。
    v5.1 新增（按优先级顺序）：
      1. FAST_DUMP    — 从峰值下跌 >=15% 且当前亏损 → 立即清仓
      2. LIQ_EMERGENCY — 每 5 分钟检查流动性，< $5000 清仓
      3. Time-decay SL — 超时仍亏损提前离场
      4. Trailing Stop — TP1 后从峰值回撤清仓
      5. 原有 TP/SL 逻辑
    3-check protection: get_token_price 返回 0 时累计，>=3 次才执行紧急操作。
    """
    if not positions:
        return
    now = time.time()
    for addr in list(positions.keys()):
        if addr not in positions:
            continue
        pos        = positions[addr]
        sym        = pos["sym"]
        tier       = pos.get("tier", "takeover").upper()
        entry      = pos.get("entry_price", 0)
        amt_usd    = pos.get("amount_usd", 0)
        amt_tokens = pos.get("amount_tokens", 0)
        entry_time = pos.get("entry_time", now)
        age_h      = (now - entry_time) / 3600
        age_min    = age_h * 60

        cur = get_token_price(addr)

        # ── 3-check protection ──────────────────────────────────────────────
        if not cur:
            pos['zero_price_count'] = pos.get('zero_price_count', 0) + 1
            n = pos['zero_price_count']
            log(f"  price_zero [{n}/10] {sym}")
            if n < 10:
                # Not yet confirmed zero — only act on Tier C timeout after 10 confirms
                if ("C" in tier) and age_min > 3 and not pos.get("timeout_done"):
                    log(f"  timeout Tier C {sym} ({age_min:.1f}min) — no price data (waiting {n}/10)")
                continue
            # zero_price_count >= 10: proceed with emergency action
            if ("C" in tier) and age_min > 3 and not pos.get("timeout_done"):
                log(f"  timeout Tier C {sym} ({age_min:.1f}min) — no price data")
                ok, _ = sell_token(addr, sym, amt_tokens, "Tier_C_timeout_no_price")
                if ok:
                    pnl_usd_val = 0.0
                    add_realized_pnl(daily_state, pnl_usd_val)
                    _record_sell_outcome(pnl_usd_val, addr)
                    daily_state["tier_c_count"] = daily_state.get("tier_c_count", 0) + 1
                    daily_state["tier_c_consecutive_losses"] = daily_state.get("tier_c_consecutive_losses", 0) + 1
                    if daily_state["tier_c_consecutive_losses"] >= 2:
                        daily_state["tier_c_pause_until"] = time.time() + TIER_C_COOLDOWN
                        log(f"  Tier C 连续亏损 2 次，冷却 {TIER_C_COOLDOWN/3600:.0f}h")
                    del positions[addr]
            else:
                log(f"  ? {tier} {sym}: no price data (10+ zeros) age={age_h:.1f}h")
            continue

        # Price obtained — reset zero counter
        pos['zero_price_count'] = 0

        if not entry or not amt_tokens:
            log(f"  ? {tier} {sym}: no entry data age={age_h:.1f}h")
            continue

        # Update peak_price
        peak = max(pos.get('peak_price', entry), cur)
        pos['peak_price'] = peak

        pnl_pct = (cur - entry) / entry if entry > 0 else 0
        cur_val  = amt_tokens * cur
        pnl_usd  = cur_val - amt_usd

        # 标准日志格式
        x_mult = 1 + pnl_pct
        log(
            f"  {tier} {sym}: entry=${amt_usd:.1f}({amt_tokens:.0f}t) "
            f"now=${cur_val:.2f} {x_mult:.2f}x "
            f"PnL={pnl_pct:+.1%}(${pnl_usd:+.2f}) age={age_h:.1f}h"
        )

        # ── FAST_DUMP (highest priority) ────────────────────────────────────
        # Fix 3: continue only on success; fall through to LIQ check on failure
        if peak > 0 and (peak - cur) / peak >= 0.15 and cur < entry:
            drop = (peak - cur) / peak
            log(f"  FAST_DUMP {sym}: peak=${peak:.6f} cur=${cur:.6f} drop={drop:.1%}")
            ok, _ = sell_token(addr, sym, pos["amount_tokens"], "FAST_DUMP")
            if ok:
                realized = pos["amount_tokens"] * cur - amt_usd
                add_realized_pnl(daily_state, realized)
                _record_sell_outcome(realized, addr)
                if "C" in tier:
                    daily_state["tier_c_consecutive_losses"] = daily_state.get("tier_c_consecutive_losses", 0) + 1
                    if daily_state["tier_c_consecutive_losses"] >= 2:
                        daily_state["tier_c_pause_until"] = time.time() + TIER_C_COOLDOWN
                del positions[addr]
                continue
            # sell failed: log and fall through to LIQ_EMERGENCY
            log(f"  FAST_DUMP sell failed for {sym}, falling through to LIQ check")

        # ── Liquidity Emergency Exit (every 5 min per position) ─────────────
        # Fix 3: continue only on success; fall through to time-decay checks on failure
        if now - pos.get('last_liq_check', 0) > 300:
            pos['last_liq_check'] = now
            try:
                liq_out = run(f"onchainos market prices --tokens 501:{addr}", timeout=15)
                liq_d = jparse(liq_out)
                liq_items = liq_d.get("data", [])
                if isinstance(liq_items, list) and liq_items:
                    liq = sf(liq_items[0].get("liquidity", liq_items[0].get("liquidityUsd", 999999)))
                elif isinstance(liq_items, dict):
                    liq = sf(liq_items.get("liquidity", liq_items.get("liquidityUsd", 999999)))
                else:
                    liq = 999999
                if 0 < liq < 5000:
                    log(f"  LIQ_EMERGENCY {sym}: liq=${liq:.0f} < $5000")
                    ok, _ = sell_token(addr, sym, pos["amount_tokens"], "LIQ_EMERGENCY")
                    if ok:
                        realized = pos["amount_tokens"] * cur - amt_usd
                        add_realized_pnl(daily_state, realized)
                        _record_sell_outcome(realized, addr)
                        del positions[addr]
                        continue
                    # sell failed: log and fall through to tier-dispatch checks
                    log(f"  LIQ_EMERGENCY sell failed for {sym}, falling through to tier checks")
            except Exception:
                pass  # fail-open

        # ── Time-decay SL (before tp1_done) ─────────────────────────────────
        if not pos.get("tp1_done"):
            _time_decay_triggered = False
            for decay_min, decay_thresh in TIME_DECAY_SL:
                if age_min > decay_min and pnl_pct < decay_thresh:
                    reason = f"TimeDecaySL_{age_min:.0f}min"
                    log(f"  TIME_DECAY_SL {sym}: age={age_min:.0f}min pnl={pnl_pct:.1%} < {decay_thresh:.0%}")
                    ok, _ = sell_token(addr, sym, pos["amount_tokens"], reason)
                    if ok:
                        realized = pos["amount_tokens"] * cur - amt_usd
                        add_realized_pnl(daily_state, realized)
                        _record_sell_outcome(realized, addr)
                        if "C" in tier:
                            daily_state["tier_c_consecutive_losses"] = daily_state.get("tier_c_consecutive_losses", 0) + 1
                            if daily_state["tier_c_consecutive_losses"] >= 2:
                                daily_state["tier_c_pause_until"] = time.time() + TIER_C_COOLDOWN
                        del positions[addr]
                        _time_decay_triggered = True   # FIXED: only fires on successful sell
                    break
            if _time_decay_triggered:
                continue

        # ── Tier A / takeover TP/SL ──────────────────────────────────────────
        if "A" in tier or "TAKEOVER" in tier:
            # TP1: +50% → 卖 75%
            if pnl_pct >= 0.50 and not pos.get("tp1_done"):
                sell_amt = amt_tokens * 0.75
                ok, _ = sell_token(addr, sym, sell_amt, f"Tier_A_TP1 +{pnl_pct:.0%}")
                if ok:
                    sold_usd = sell_amt * cur
                    realized = sold_usd - amt_usd * 0.75
                    add_realized_pnl(daily_state, realized)
                    _record_sell_outcome(realized, addr)
                    pos["tp1_done"]      = True
                    pos["amount_tokens"] = amt_tokens * 0.25
                    pos["amount_usd"]    = amt_usd * 0.25
                    log(f"  Tier A TP1 done, 底仓 {pos['amount_tokens']:.0f}t (${pos['amount_usd']:.1f})")
                continue

            # Trailing Stop after TP1 (Tier A: 12% drawdown from peak, must be profitable)
            if pos.get("tp1_done"):
                if peak > 0 and (peak - cur) / peak >= TRAIL_DISTANCE_A and cur > entry:
                    log(f"  TrailingStop TIER_A {sym}: peak=${peak:.6f} cur=${cur:.6f} drawdown={(peak-cur)/peak:.1%}")
                    ok, _ = sell_token(addr, sym, pos["amount_tokens"], "TrailingStop")
                    if ok:
                        realized = pos["amount_tokens"] * cur - pos["amount_usd"]
                        add_realized_pnl(daily_state, realized)
                        _record_sell_outcome(realized, addr)
                        del positions[addr]
                    continue

            # TP2: +150% 且 tp1 已完成 → 再卖底仓 50%
            if pnl_pct >= 1.50 and pos.get("tp1_done") and not pos.get("tp2_done"):
                sell_amt = pos["amount_tokens"] * 0.50
                ok, _ = sell_token(addr, sym, sell_amt, f"Tier_A_TP2 +{pnl_pct:.0%}")
                if ok:
                    sold_usd = sell_amt * cur
                    realized = sold_usd - pos["amount_usd"] * 0.50
                    add_realized_pnl(daily_state, realized)
                    _record_sell_outcome(realized, addr)
                    pos["tp2_done"]      = True
                    pos["amount_tokens"] = pos["amount_tokens"] * 0.50
                    pos["amount_usd"]    = pos["amount_usd"] * 0.50
                    log(f"  Tier A TP2 done, 底仓 {pos['amount_tokens']:.0f}t (${pos['amount_usd']:.1f})")
                continue

            # TP3: +300% 且 tp2 已完成 → 再卖剩余 50%
            if pnl_pct >= 3.00 and pos.get("tp2_done") and not pos.get("tp3_done"):
                sell_amt = pos["amount_tokens"] * 0.50
                ok, _ = sell_token(addr, sym, sell_amt, f"Tier_A_TP3 +{pnl_pct:.0%}")
                if ok:
                    sold_usd = sell_amt * cur
                    realized = sold_usd - pos["amount_usd"] * 0.50
                    add_realized_pnl(daily_state, realized)
                    _record_sell_outcome(realized, addr)
                    pos["tp3_done"]      = True
                    pos["amount_tokens"] = pos["amount_tokens"] * 0.50
                    pos["amount_usd"]    = pos["amount_usd"] * 0.50
                    log(f"  Tier A TP3 done, 月球底仓 {pos['amount_tokens']:.0f}t (${pos['amount_usd']:.1f})")
                continue

            # SL: -35% 且 tp1 未触发
            if pnl_pct <= -0.35 and not pos.get("tp1_done") and not pos.get("sl_checked"):
                pos["sl_checked"] = True
                log(f"  Tier A SL 触发 {pnl_pct:.0%}，检查 SM 出货...")
                if check_sm_exiting(addr):
                    ok, _ = sell_token(addr, sym, pos["amount_tokens"], f"Tier_A_SL_SM_exit {pnl_pct:.0%}")
                    if ok:
                        realized = pos["amount_tokens"] * cur - pos["amount_usd"]
                        add_realized_pnl(daily_state, realized)
                        _record_sell_outcome(realized, addr)
                        del positions[addr]
                else:
                    log(f"  SM 未出货，持有至 -45%")
                continue

            # SL 二级止损：-45% 且 SM 未出货时仍亏损到 -45%
            if pnl_pct <= -0.45 and not pos.get("tp1_done") and not pos.get("sl_done"):
                ok, _ = sell_token(addr, sym, pos["amount_tokens"], f"Tier_A_SL_45 {pnl_pct:.0%}")
                if ok:
                    realized = pos["amount_tokens"] * cur - pos["amount_usd"]
                    add_realized_pnl(daily_state, realized)
                    _record_sell_outcome(realized, addr)
                    pos["sl_done"] = True
                    del positions[addr]
                continue

            # 超时：48h 无 tp1 → 清仓
            if age_h > 48 and not pos.get("tp1_done") and not pos.get("timeout_done"):
                ok, _ = sell_token(addr, sym, pos["amount_tokens"], f"Tier_A_timeout {age_h:.0f}h")
                if ok:
                    realized = pos["amount_tokens"] * cur - pos["amount_usd"]
                    add_realized_pnl(daily_state, realized)
                    _record_sell_outcome(realized, addr)
                    pos["timeout_done"] = True
                    del positions[addr]
                continue
        elif "B" in tier:
            # TP1: +40% → 卖 70%
            if pnl_pct >= 0.40 and not pos.get("tp1_done"):
                sell_amt = amt_tokens * 0.70
                ok, _ = sell_token(addr, sym, sell_amt, f"Tier_B_TP1 +{pnl_pct:.0%}")
                if ok:
                    sold_usd = sell_amt * cur
                    realized = sold_usd - amt_usd * 0.70
                    add_realized_pnl(daily_state, realized)
                    _record_sell_outcome(realized, addr)
                    pos["tp1_done"]      = True
                    pos["amount_tokens"] = amt_tokens * 0.30
                    pos["amount_usd"]    = amt_usd * 0.30
                    log(f"  Tier B TP1 done, 剩余 {pos['amount_tokens']:.0f}t")
                continue

            # Trailing Stop after TP1 (Tier B: 10% drawdown from peak, must be profitable)
            if pos.get("tp1_done"):
                if peak > 0 and (peak - cur) / peak >= TRAIL_DISTANCE_B and cur > entry:
                    log(f"  TrailingStop TIER_B {sym}: peak=${peak:.6f} cur=${cur:.6f} drawdown={(peak-cur)/peak:.1%}")
                    ok, _ = sell_token(addr, sym, pos["amount_tokens"], "TrailingStop")
                    if ok:
                        realized = pos["amount_tokens"] * cur - pos["amount_usd"]
                        add_realized_pnl(daily_state, realized)
                        _record_sell_outcome(realized, addr)
                        del positions[addr]
                    continue

            # TP2: +100% 且 tp1 完成 → 再卖剩余 50%
            if pnl_pct >= 1.00 and pos.get("tp1_done") and not pos.get("tp2_done"):
                sell_amt = pos["amount_tokens"] * 0.50
                ok, _ = sell_token(addr, sym, sell_amt, f"Tier_B_TP2 +{pnl_pct:.0%}")
                if ok:
                    sold_usd = sell_amt * cur
                    realized = sold_usd - pos["amount_usd"] * 0.50
                    add_realized_pnl(daily_state, realized)
                    _record_sell_outcome(realized, addr)
                    pos["tp2_done"]      = True
                    pos["amount_tokens"] = pos["amount_tokens"] * 0.50
                    pos["amount_usd"]    = pos["amount_usd"] * 0.50
                    log(f"  Tier B TP2 done, 剩余 {pos['amount_tokens']:.0f}t")
                continue

            # SL: -25% → 全清
            if pnl_pct <= -0.25 and not pos.get("sl_done"):
                ok, _ = sell_token(addr, sym, pos["amount_tokens"], f"Tier_B_SL {pnl_pct:.0%}")
                if ok:
                    realized = pos["amount_tokens"] * cur - pos["amount_usd"]
                    add_realized_pnl(daily_state, realized)
                    _record_sell_outcome(realized, addr)
                    pos["sl_done"] = True
                    del positions[addr]
                continue

            # 超时：12h → 全清
            if age_h > 12 and not pos.get("timeout_done"):
                ok, _ = sell_token(addr, sym, pos["amount_tokens"], f"Tier_B_timeout {age_h:.0f}h")
                if ok:
                    realized = pos["amount_tokens"] * cur - pos["amount_usd"]
                    add_realized_pnl(daily_state, realized)
                    _record_sell_outcome(realized, addr)
                    pos["timeout_done"] = True
                    del positions[addr]
                continue

        # ── Tier C TP/SL ─────────────────────────────────────────────────────
        elif "C" in tier:
            # TP: +20% → 全清
            if pnl_pct >= 0.20:
                ok, _ = sell_token(addr, sym, pos["amount_tokens"], f"Tier_C_TP +{pnl_pct:.0%}")
                if ok:
                    realized = pos["amount_tokens"] * cur - pos["amount_usd"]
                    add_realized_pnl(daily_state, realized)
                    _record_sell_outcome(realized, addr)
                    if realized >= 0:
                        daily_state["tier_c_consecutive_losses"] = 0
                    else:
                        daily_state["tier_c_consecutive_losses"] = daily_state.get("tier_c_consecutive_losses", 0) + 1
                    del positions[addr]
                continue

            # Holder pump TP: holders 增加 >30% 时全清
            holders_entry = pos.get("holders_at_entry", 0)
            if holders_entry > 0:
                # 从最近的 memepump 快速确认持有人数（用价格接口代替，此处跳过，仅保留结构）
                pass

            # SL: -25% → 全清
            if pnl_pct <= -0.25:
                ok, _ = sell_token(addr, sym, pos["amount_tokens"], f"Tier_C_SL {pnl_pct:.0%}")
                if ok:
                    realized = pos["amount_tokens"] * cur - pos["amount_usd"]
                    add_realized_pnl(daily_state, realized)
                    _record_sell_outcome(realized, addr)
                    daily_state["tier_c_consecutive_losses"] = daily_state.get("tier_c_consecutive_losses", 0) + 1
                    if daily_state["tier_c_consecutive_losses"] >= 2:
                        daily_state["tier_c_pause_until"] = time.time() + TIER_C_COOLDOWN
                        log(f"  Tier C 连续亏损 2 次，冷却 {TIER_C_COOLDOWN/3600:.0f}h")
                    del positions[addr]
                continue

            # 超时：3 分钟 → 全清
            if age_min > 3 and not pos.get("timeout_done"):
                ok, _ = sell_token(addr, sym, pos["amount_tokens"], f"Tier_C_timeout {age_min:.1f}min")
                if ok:
                    realized = pos["amount_tokens"] * cur - pos["amount_usd"]
                    add_realized_pnl(daily_state, realized)
                    _record_sell_outcome(realized, addr)
                    daily_state["tier_c_consecutive_losses"] = daily_state.get("tier_c_consecutive_losses", 0) + 1
                    if daily_state["tier_c_consecutive_losses"] >= 2:
                        daily_state["tier_c_pause_until"] = time.time() + TIER_C_COOLDOWN
                        log(f"  Tier C 连续亏损 2 次，冷却 {TIER_C_COOLDOWN/3600:.0f}h")
                    pos["timeout_done"] = True
                    del positions[addr]
                continue


# ─── 主程序 ───────────────────────────────────────────────────────────────────

def main():
    # 初始化 daily_state
    daily_state = {
        "date":                        "",
        "realized_pnl":                0.0,
        "tier_c_count":                0,
        "tier_c_consecutive_losses":   0,
        "tier_c_pause_until":          0.0,
    }
    sm_buys      = {}
    hot_cache    = {}
    hot_cache_ts = 0

    last_balance_check    = 0
    last_sm_check         = 0
    last_migrating_check  = 0
    last_new_check        = 0
    last_pos_check        = 0

    usdc = 200.0

    # 持仓接管 + acted 加载 + session state 恢复
    positions = load_existing_positions()
    acted     = load_acted()
    acted.update({addr: time.time() for addr in positions})
    # Fix 11: restore session state across restarts
    saved_session = load_session_state()
    session_state.update(saved_session)
    save_acted(acted)

    log("=" * 60)
    log("SOL MEME HUNTER v5.2 — 三层预测架构 + 日亏损重启熔断")
    log(f"Wallet: {WALLET}")
    log(f"Safety  DAY=${SAFETY_LINE_DAY}  NIGHT=${SAFETY_LINE_NIGHT}  DAILY_LOSS_LIMIT=${DAILY_LOSS_LIMIT}")
    log(f"Tier A size={TIER_A_SIZE}(night={TIER_A_NIGHT})  MC ${SM_MIN_MC}-${SM_MAX_MC}  liq ${SM_MIN_LIQ}-${SM_MAX_LIQ}")
    log(f"Tier B size={TIER_B_SIZE}(night={TIER_B_NIGHT})  bonding {MIN_BONDING}-{MAX_BONDING}%")
    log(f"Tier C size={TIER_C_SIZE}  bonding {MIN_BONDING_C}-{MAX_BONDING_C}%  max_age {MAX_TOKEN_AGE_C}min  daily_limit={MAX_TIER_C_DAY}")
    log(f"Refresh  SM={SM_REFRESH}s  MIGRATING={MIGRATING_REFRESH}s  NEW={NEW_REFRESH}s  HOT={HOT_REFRESH}s")
    log(f"v5.1: confidence_scoring | K1_pump_guard | TOP_ZONE_filter | FAST_DUMP | trailing_stop({TRAIL_DISTANCE_A:.0%}A/{TRAIL_DISTANCE_B:.0%}B)")
    log(f"v5.1: time_decay_SL {TIME_DECAY_SL} | 3-check_protection | cooldown_dedup(30min) | session_pause({SESSION_CONSEC_LOSS_MAX}loss/{SESSION_CONSEC_PAUSE}s) | liq_emergency($5k)")
    log(f"Existing positions: {len(positions)}")
    log("=" * 60)

    while True:
        now = time.time()
        reset_daily_if_needed(daily_state)

        # 余额检查（每 60s）
        if now - last_balance_check > 60:
            usdc = get_usdc_balance()
            log(
                f"USDC: ${usdc:.2f} | Daily PnL: ${daily_state['realized_pnl']:+.2f} | "
                f"Safety: ${get_safety_line()} | Positions: {len(positions)}"
            )
            last_balance_check = now

        # 持仓检查（每 3s）
        if now - last_pos_check > 3:
            check_positions(positions, daily_state)
            last_pos_check = now

        # 安全线熔断
        if usdc < get_safety_line():
            log(f"SAFETY LINE: ${usdc:.2f} < ${get_safety_line()} — no new entries")
            time.sleep(10)
            continue

        # 每日亏损熔断 — 触发后需重启才能恢复（不自动日重置）
        if daily_state.get("halted") or daily_state["realized_pnl"] < -DAILY_LOSS_LIMIT:
            if not daily_state.get("halted"):
                daily_state["halted"] = True
                log(f"🚨 DAILY LOSS LIMIT HIT: ${daily_state['realized_pnl']:.2f} — 需重启脚本才能恢复交易")
            log(f"HALTED: 日亏损熔断，请重启脚本恢复 | PnL=${daily_state['realized_pnl']:.2f}")
            time.sleep(60)
            continue

        # Hot-tokens 缓存刷新（每 HOT_REFRESH 秒）
        if now - hot_cache_ts > HOT_REFRESH:
            hot_cache = get_hot_tokens()
            hot_cache_ts = now

        # ── Tier A：SM tracker（每 SM_REFRESH=30s）─────────────────────────
        if now - last_sm_check > SM_REFRESH:
            signals = fetch_sm_activities(sm_buys)
            log(f"Tier A SM signals: {len(signals)}")
            for addr, strength, n_wallets, mc, sym in signals:
                if is_acted(acted, addr) or addr in positions:
                    continue
                # v5.1: cooldown dedup
                if time.time() < cooldown_until.get(addr, 0):
                    remaining = cooldown_until[addr] - time.time()
                    log(f"  COOLDOWN: {sym} skip {remaining:.0f}s left")
                    continue
                ok, size = entry_guard(positions, daily_state, usdc, "A", addr=addr)
                if not ok:
                    log(f"  SKIP Tier A {sym}: {size}")
                    continue
                # STRONG: 直接买; NORMAL: 需要 hot-tokens 确认
                if strength == "NORMAL":
                    inflow = get_hot_inflow(hot_cache, addr)
                    if inflow <= 500:
                        log(f"  SKIP Tier A NORMAL {sym}: not in hot-50 (inflow=${inflow:.0f} <= 500)")
                        continue
                # v5.1: Confidence scoring
                confidence = min(90, n_wallets * 30)
                inflow_val = get_hot_inflow(hot_cache, addr)
                if inflow_val > 500:
                    confidence += 20
                confidence = min(100, confidence)
                if confidence < 60:
                    log(f"  SKIP Tier A {sym}: confidence={confidence} < 60")
                    continue
                sec_ok, sec_reason = security_check(addr)
                if not sec_ok:
                    log(f"  REJECT Tier A {sym} security: {sec_reason}")
                    acted[addr] = time.time()
                    save_acted(acted)
                    continue
                # v5.1: K1 pump guard
                if check_k1_pump(addr, sym):
                    log(f"  SKIP Tier A {sym}: K1 pump guard")
                    continue
                # v5.1: TOP_ZONE filter
                cur_price_pre = get_token_price(addr)
                if cur_price_pre and check_top_zone(addr, cur_price_pre, sym):
                    log(f"  SKIP Tier A {sym}: TOP_ZONE filter")
                    continue
                log(f"ENTER TIER_A {sym} ${size} | MC=${mc:.0f} | {strength} {n_wallets}w | conf={confidence}")
                ok_swap, _ = execute_swap(USDC_ADDR, addr, size)
                if ok_swap:
                    entry_price = 0
                    for _try in range(3):
                        entry_price = get_token_price(addr)
                        if entry_price > 0:
                            break
                        time.sleep(2)
                    if entry_price <= 0:
                        log(f"  WARN: {sym} price=0 after 3 retries, storing amt_tokens=0 (will retry in check_positions)")
                        amt_tokens = 0
                    else:
                        amt_tokens = size / entry_price
                    positions[addr] = {
                        "sym":           sym,
                        "amount_usd":    size,
                        "amount_tokens": amt_tokens,    # 0 if price unavailable
                        "entry_price":   entry_price,   # may be 0 — check_positions will log and skip
                        "entry_time":    time.time(),
                        "tier":          "TIER_A",
                        "tp1_done":      False,
                        "tp2_done":      False,
                        "tp3_done":      False,
                        "holders_at_entry": 0,
                        "peak_price":    entry_price,
                        "last_liq_check": 0,
                        "zero_price_count": 0,
                        "confidence":    confidence,
                    }
                    acted[addr] = time.time()
                    save_acted(acted)
                    usdc -= size
                    log(f"  ENTERED Tier A {sym} ${size} | USDC left: ${usdc:.1f}")
                else:
                    acted[addr] = time.time()
                    save_acted(acted)
            last_sm_check = now

        # ── Tier B：MIGRATING（每 MIGRATING_REFRESH=60s）──────────────────
        if now - last_migrating_check > MIGRATING_REFRESH:
            candidates = fetch_migrating_tokens()
            log(f"Tier B MIGRATING candidates: {len(candidates)}")
            for t in candidates:
                addr = t.get("tokenAddress", "")
                sym  = t.get("_sym", "?")
                mc   = t.get("_mc", 0)
                bonding = sf(t.get("bondingPercent", 0))
                if not addr:
                    continue
                if is_acted(acted, addr) or addr in positions:
                    continue
                # v5.1: cooldown dedup
                if time.time() < cooldown_until.get(addr, 0):
                    remaining = cooldown_until[addr] - time.time()
                    log(f"  COOLDOWN: {sym} skip {remaining:.0f}s left")
                    continue
                ok, size = entry_guard(positions, daily_state, usdc, "B", addr=addr)
                if not ok:
                    log(f"  SKIP Tier B {sym}: {size}")
                    continue
                sec_ok, sec_reason = security_check(addr)
                if not sec_ok:
                    log(f"  REJECT Tier B {sym} security: {sec_reason}")
                    acted[addr] = time.time()
                    save_acted(acted)
                    continue
                # v5.2: K1 pump guard for Tier B too
                if check_k1_pump(addr, sym):
                    log(f"  SKIP Tier B {sym}: K1 pump guard")
                    continue
                log(f"ENTER TIER_B {sym} ${size} | MC=${mc:.0f} | bonding={bonding:.1f}%")
                ok_swap, _ = execute_swap(USDC_ADDR, addr, size)
                if ok_swap:
                    entry_price = 0
                    for _try in range(3):
                        entry_price = get_token_price(addr)
                        if entry_price > 0:
                            break
                        time.sleep(2)
                    if entry_price <= 0:
                        log(f"  WARN: {sym} price=0 after 3 retries, storing amt_tokens=0 (will retry in check_positions)")
                        amt_tokens = 0
                    else:
                        amt_tokens = size / entry_price
                    positions[addr] = {
                        "sym":           sym,
                        "amount_usd":    size,
                        "amount_tokens": amt_tokens,    # 0 if price unavailable
                        "entry_price":   entry_price,   # may be 0 — check_positions will log and skip
                        "entry_time":    time.time(),
                        "tier":          "TIER_B",
                        "tp1_done":      False,
                        "tp2_done":      False,
                        "holders_at_entry": 0,
                        "bonding_at_entry": bonding,
                        "peak_price":    entry_price,
                        "last_liq_check": 0,
                        "zero_price_count": 0,
                    }
                    acted[addr] = time.time()
                    save_acted(acted)
                    usdc -= size
                    log(f"  ENTERED Tier B {sym} ${size} | USDC left: ${usdc:.1f}")
                else:
                    acted[addr] = time.time()
                    save_acted(acted)
            last_migrating_check = now

        # ── Tier C：NEW（每 NEW_REFRESH=15s，夜间禁止）────────────────────
        if not is_night_time() and now - last_new_check > NEW_REFRESH:
            candidates_c = fetch_new_tokens()
            log(f"Tier C NEW candidates: {len(candidates_c)}")
            for t in candidates_c:
                addr    = t.get("tokenAddress", "")
                sym     = t.get("_sym", "?")
                mc      = t.get("_mc", 0)
                bonding = sf(t.get("bondingPercent", 0))
                holders = int(sf(t.get("tags", {}).get("totalHolders", 0)))
                if not addr:
                    continue
                if is_acted(acted, addr) or addr in positions:
                    continue
                # v5.1: cooldown dedup
                if time.time() < cooldown_until.get(addr, 0):
                    remaining = cooldown_until[addr] - time.time()
                    log(f"  COOLDOWN: {sym} skip {remaining:.0f}s left")
                    continue
                # Tier C 连续亏损冷却检查
                if time.time() < daily_state["tier_c_pause_until"]:
                    remaining = daily_state["tier_c_pause_until"] - time.time()
                    log(f"  SKIP Tier C: cooldown {remaining/60:.0f}min left")
                    break
                ok, size = entry_guard(positions, daily_state, usdc, "C", addr=addr)
                if not ok:
                    log(f"  SKIP Tier C {sym}: {size}")
                    continue
                sec_ok, sec_reason = security_check(addr)
                if not sec_ok:
                    log(f"  REJECT Tier C {sym} security: {sec_reason}")
                    acted[addr] = time.time()
                    save_acted(acted)
                    continue
                log(f"ENTER TIER_C {sym} ${size} | MC=${mc:.0f} | bonding={bonding:.1f}% | holders={holders}")
                ok_swap, _ = execute_swap(USDC_ADDR, addr, size)
                if ok_swap:
                    entry_price = 0
                    for _try in range(3):
                        entry_price = get_token_price(addr)
                        if entry_price > 0:
                            break
                        time.sleep(2)
                    if entry_price <= 0:
                        log(f"  WARN: {sym} price=0 after 3 retries, storing amt_tokens=0 (will retry in check_positions)")
                        amt_tokens = 0
                    else:
                        amt_tokens = size / entry_price
                    positions[addr] = {
                        "sym":             sym,
                        "amount_usd":      size,
                        "amount_tokens":   amt_tokens,    # 0 if price unavailable
                        "entry_price":     entry_price,   # may be 0 — check_positions will log and skip
                        "entry_time":      time.time(),
                        "tier":            "TIER_C",
                        "tp1_done":        False,
                        "holders_at_entry": holders,
                        "peak_price":      entry_price,
                        "last_liq_check":  0,
                        "zero_price_count": 0,
                    }
                    acted[addr] = time.time()
                    save_acted(acted)
                    usdc -= size
                    daily_state["tier_c_count"] = daily_state.get("tier_c_count", 0) + 1
                    log(f"  ENTERED Tier C {sym} ${size} | USDC left: ${usdc:.1f}")
                else:
                    acted[addr] = time.time()
                    save_acted(acted)
            last_new_check = now

        time.sleep(2)


if __name__ == "__main__":
    main()
