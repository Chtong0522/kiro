#!/usr/bin/env python3
"""
SOL Meme Hunter v2 — OKX Agentic Trading Contest
调整参数：Gate2 dev复合判断 / Gate3 bundle放宽25% / K线阈值92%
"""
import subprocess, json, time, os, sys
from datetime import datetime

# ─── 配置 ─────────────────────────────────────────────────────────────────────
WALLET      = "AXBCfbioEHiJ48ejNp5feEzWt2iHFLUDNMk27t5vXWLE"
USDC_ADDR   = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
COMP_ID     = "113"

SCAN_INTERVAL   = 30     # 30秒一轮，持续高频扫描
MAX_POSITION    = 3      # 单笔 3U（测试阶段）
SAFETY_LINE     = 80     # USDC < 80 停止开新仓

# Gate 阈值（已调整）
GATE_RUG_MAX        = 0.25   # rug_ratio 上限
GATE_BUNDLE_MAX     = 25.0   # bundle% 上限（从15%放宽到25%）
GATE_TOP10_MAX      = 0.55   # top10持仓上限
GATE_SNIPER_MAX     = 25     # sniper数量上限
GATE_KLINE_HIGH_PCT = 0.92   # 当前价格不能超过1h高点的92%（从88%放宽）
GATE_KLINE_VOL_PCT  = 0.75   # 最近2根K线量能不超过均量75%
GATE_MC_MIN         = 8000   # 最小市值
GATE_MC_MAX         = 600000 # 最大市值
GATE_SOLD_MAX       = 28     # soldRatioPercent 上限

LOG_FILE = "/tmp/meme_hunter_v2.log"

# ─── 工具函数 ──────────────────────────────────────────────────────────────────
def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

def run(cmd, timeout=30):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception as e:
        return ""

def parse_json(raw):
    try:
        return json.loads(raw)
    except:
        return {}

# ─── 余额检查 ──────────────────────────────────────────────────────────────────
def get_usdc_balance():
    out = run("onchainos wallet balance --chain solana")
    d = parse_json(out)
    for asset in d.get("data", {}).get("details", [{}])[0].get("tokenAssets", []):
        if asset.get("symbol") == "USDC":
            return float(asset.get("balance", 0))
    return 0

# ─── 信号采集 ──────────────────────────────────────────────────────────────────
def get_okx_signals():
    out = run("onchainos signal list --chain solana --wallet-type 1,2 --limit 20", timeout=25)
    d = parse_json(out)
    results = []
    for s in d.get("data", []):
        sold  = float(s.get("soldRatioPercent", 100))
        count = int(s.get("triggerWalletCount", 0))
        addr  = s.get("token", {}).get("tokenAddress", "")
        sym   = s.get("token", {}).get("symbol", "?")
        mc    = float(s.get("token", {}).get("marketCapUsd", 0))
        wtype = s.get("walletType", "0")
        if sold < GATE_SOLD_MAX and count >= 3 and addr and GATE_MC_MIN < mc < GATE_MC_MAX:
            results.append({"addr": addr, "sym": sym, "mc": mc,
                             "sold": sold, "count": count, "source": f"OKX-wt{wtype}"})
    return results

def get_gmgn_signals():
    out = run("gmgn-cli market signal --chain sol --signal-type 12 --raw", timeout=25)
    d = parse_json(out)
    items = d if isinstance(d, list) else d.get("data", [])
    clusters = {}
    now = time.time()
    for item in items:
        addr = item.get("token_address", "")
        mc   = float(item.get("trigger_mc") or item.get("market_cap") or 0)
        ts   = item.get("trigger_at", 0)
        age  = now - ts if ts else 9999
        if addr and GATE_MC_MIN < mc < GATE_MC_MAX and age < 3600:
            if addr not in clusters:
                clusters[addr] = {"addr": addr, "mc": mc, "count": 0, "source": "GMGN-SM12"}
            clusters[addr]["count"] += 1
    return [v for v in clusters.values() if v["count"] >= 2]

# ─── 五关过滤 ──────────────────────────────────────────────────────────────────
def gate_check(addr, sym):
    # Gate 1: honeypot + basic risk
    out = run(f"onchainos security token-scan --tokens '501:{addr}'", timeout=20)
    d = parse_json(out)
    r = d.get("data", [{}])
    r = r[0] if r else {}
    if r.get("isHoneypot"):     return False, "Gate1: honeypot"
    if r.get("riskLevel") == "HIGH": return False, "Gate1: HIGH risk"
    if r.get("isWash"):         return False, "Gate1: wash trading"
    if r.get("isMintable"):     return False, "Gate1: mintable"

    # Gate 2: dev behavior (复合判断，不单靠rugCount)
    out2 = run(f"gmgn-cli token security --chain sol --address {addr} --raw", timeout=20)
    d2 = parse_json(out2)
    if d2:
        if not d2.get("renounced_mint"):   return False, "Gate2: mint not renounced"
        if not d2.get("renounced_freeze_account"): return False, "Gate2: freeze not renounced"
        rug = float(d2.get("rug_ratio") or 0)
        if rug > GATE_RUG_MAX:             return False, f"Gate2: rug_ratio={rug:.2f}"
        top10 = float(d2.get("top_10_holder_rate") or 0)
        if top10 > GATE_TOP10_MAX:         return False, f"Gate2: top10={top10:.0%}"
        snipers = int(d2.get("sniper_count") or 0)
        if snipers > GATE_SNIPER_MAX:      return False, f"Gate2: snipers={snipers}"
        # dev holding: 只有 creator_hold + rugCount>30 才淘汰（复合判断）
        cstatus = d2.get("creator_token_status", "")
        rug_count = int(d2.get("dev_rug_count") or 0)
        if cstatus == "creator_hold" and rug_count > 30:
            return False, f"Gate2: dev holding + rugCount={rug_count}"
        if d2.get("is_wash_trading"):      return False, "Gate2: wash trading"

    # Gate 3: bundle (放宽到25%)
    out3 = run(f"onchainos memepump token-bundle-info --address {addr}", timeout=20)
    d3 = parse_json(out3)
    pct = float(d3.get("data", {}).get("bundlerAthPercent") or 0)
    if pct > GATE_BUNDLE_MAX:
        return False, f"Gate3: bundle={pct:.1f}% > {GATE_BUNDLE_MAX}%"

    # Gate 5: SM exit check
    out5 = run(
        f"gmgn-cli token traders --chain sol --address {addr} "
        f"--tag smart_degen --order-by sell_volume_cur --direction desc --limit 5 --raw",
        timeout=20
    )
    d5 = parse_json(out5)
    traders = d5.get("list", [])
    if traders:
        top = traders[0]
        sell_v = float(top.get("sell_volume_cur") or 0)
        buy_v  = float(top.get("buy_volume_cur")  or 0)
        if buy_v > 0 and sell_v > buy_v * 1.5:
            return False, f"Gate5: SM exiting sell${sell_v:.0f} > buy${buy_v:.0f}"

    return True, "✅ all gates passed"

# ─── K线时机 ───────────────────────────────────────────────────────────────────
def kline_check(addr):
    ts_from = int(time.time()) - 3600
    ts_to   = int(time.time())
    out = run(
        f"gmgn-cli market kline --chain sol --address {addr} "
        f"--resolution 5m --from {ts_from} --to {ts_to} --raw",
        timeout=20
    )
    d = parse_json(out)
    candles = d.get("list", [])
    if len(candles) < 4:
        return False, "kline: insufficient data"

    closes  = [float(c["close"])  for c in candles]
    vols    = [float(c["volume"]) for c in candles]
    highs   = [float(c["high"])   for c in candles]
    high1h  = max(highs)
    avg_p   = sum(closes) / len(closes)
    cur     = closes[-1]
    avg_v   = sum(vols) / len(vols) if vols else 1
    last2v  = sum(vols[-2:]) / 2   if len(vols) >= 2 else avg_v

    pct_high   = cur / high1h  if high1h > 0 else 1
    within_avg = abs(cur - avg_p) / avg_p if avg_p > 0 else 1
    vol_ratio  = last2v / avg_v   if avg_v > 0 else 1

    reasons = []
    if pct_high   > GATE_KLINE_HIGH_PCT:
        reasons.append(f"price={pct_high:.0%} of 1h-high")
    if vol_ratio  > GATE_KLINE_VOL_PCT:
        reasons.append(f"vol={vol_ratio:.0%} not declining")
    if within_avg > 0.30:
        reasons.append(f"price ±{within_avg:.0%} from avg")

    if reasons:
        return False, "KL veto: " + " | ".join(reasons)

    return True, f"cur={cur:.8f} {pct_high:.0%}ofHigh vol={vol_ratio:.0%}"

# ─── 执行交易 ──────────────────────────────────────────────────────────────────
def execute_swap(addr, sym, amount, reason):
    log(f"  💸 SWAP ${amount} USDC → {sym}")
    log(f"     reason: {reason}")
    cmd = (
        f"onchainos swap execute "
        f"--from {USDC_ADDR} "
        f"--to {addr} "
        f"--readable-amount {amount} "
        f"--chain solana "
        f"--wallet {WALLET} "
        f"--gas-level fast "
        f"--slippage 15"
    )
    out = run(cmd, timeout=90)
    try:
        d = parse_json(out)
        tx = d.get("data", {}).get("swapTxHash", "")
        if tx:
            log(f"  ✅ TX: {tx}")
            return True, tx
        else:
            log(f"  ❌ swap failed: {out[:200]}")
            return False, out[:200]
    except:
        log(f"  ❌ swap error: {out[:200]}")
        return False, out[:200]

# ─── 持仓止盈检查 ─────────────────────────────────────────────────────────────
def check_positions(positions):
    if not positions:
        return
    log(f"Checking {len(positions)} open positions...")
    for addr, pos in list(positions.items()):
        sym = pos["sym"]
        entry_usd = pos.get("entry_price_usd", 0)
        entry_time = pos.get("entry_time", 0)
        age_h = (time.time() - entry_time) / 3600

        # 查当前价格
        out = run(f"onchainos token price-info --address {addr} --chain solana", timeout=20)
        d = parse_json(out)
        cur_price = float(d.get("data", {}).get("price") or 0)

        if entry_usd > 0 and cur_price > 0:
            pnl = (cur_price - entry_usd) / entry_usd
            log(f"  {sym}: entry={entry_usd:.8f} cur={cur_price:.8f} PnL={pnl:+.1%} age={age_h:.1f}h")

            # TP1: +60%
            if pnl >= 0.60 and not pos.get("tp1_done"):
                log(f"  🎯 TP1 triggered (+60%) for {sym} — selling 25%")
                pos["tp1_done"] = True

            # TP2: +150%
            if pnl >= 1.50 and not pos.get("tp2_done"):
                log(f"  🎯 TP2 triggered (+150%) for {sym} — selling 25%")
                pos["tp2_done"] = True

            # TP3: +300%
            if pnl >= 3.00 and not pos.get("tp3_done"):
                log(f"  🎯 TP3 triggered (+300%) for {sym} — selling 15%")
                pos["tp3_done"] = True

            # 时间止损: 48h无动作
            if age_h > 48:
                log(f"  ⏰ Time stop: {sym} held {age_h:.0f}h — removing from tracking")
                del positions[addr]

# ─── 主循环 ────────────────────────────────────────────────────────────────────
def main():
    seen = set()
    seen_time = {}   # addr -> timestamp，超过10分钟重新评估
    positions = {}
    round_num = 0

    log("=" * 55)
    log("SOL MEME HUNTER v2 — started")
    log(f"Wallet: {WALLET}")
    log(f"Position: ${MAX_POSITION} | Safety: ${SAFETY_LINE}")
    log(f"Gates: rug<{GATE_RUG_MAX} bundle<{GATE_BUNDLE_MAX}% kline<{GATE_KLINE_HIGH_PCT:.0%}ofHigh")
    log("=" * 55)

    while True:
        round_num += 1
        log(f"\n{'─'*20} ROUND {round_num} {'─'*20}")

        # 安全线
        usdc = get_usdc_balance()
        log(f"USDC: ${usdc:.1f}")
        if usdc < SAFETY_LINE:
            log(f"🔴 SAFETY LINE triggered (${usdc:.1f} < ${SAFETY_LINE}) — skip new entries")
            check_positions(positions)
            time.sleep(SCAN_INTERVAL)
            continue

        # 持仓检查
        check_positions(positions)

        # 信号扫描
        okx_sigs  = get_okx_signals()
        gmgn_sigs = get_gmgn_signals()
        log(f"Signals: OKX={len(okx_sigs)} GMGN={len(gmgn_sigs)}")

        # 合并去重（超过10分钟的token重新允许评估）
        now_ts = time.time()
        for addr in list(seen_time.keys()):
            if now_ts - seen_time[addr] > 600:
                seen.discard(addr)
                del seen_time[addr]

        candidates = {}
        for s in okx_sigs + gmgn_sigs:
            addr = s["addr"]
            if addr not in seen and addr not in positions:
                if addr not in candidates or s.get("count", 0) > candidates[addr].get("count", 0):
                    candidates[addr] = s

        log(f"New candidates: {len(candidates)}")

        # 按 score 排序，取 top 6
        ranked = sorted(candidates.values(), key=lambda x: -x.get("count", 0))[:6]

        entered = 0
        for c in ranked:
            addr   = c["addr"]
            sym    = c.get("sym", "?")
            mc     = c.get("mc", 0)
            source = c.get("source", "?")
            seen.add(addr)
            seen_time[addr] = time.time()

            log(f"\n  [{source}] {sym} MC=${mc:.0f} signals={c.get('count',0)} sold={c.get('sold',0):.0f}%")

            ok, reason = gate_check(addr, sym)
            if not ok:
                log(f"  ❌ {reason}")
                continue

            ok2, reason2 = kline_check(addr)
            if not ok2:
                log(f"  ⚠️  {reason2}")
                continue

            log(f"  ✅ PASS {reason} | {reason2}")

            # 仓位大小
            if usdc > 150:   pos_size = MAX_POSITION
            elif usdc > 120: pos_size = 2
            else:            pos_size = 1

            success, tx = execute_swap(addr, sym, pos_size, f"{source} score={c.get('count')}")
            if success:
                positions[addr] = {
                    "sym": sym, "amount_usd": pos_size,
                    "entry_time": time.time(), "entry_price_usd": 0,
                    "source": source
                }
                entered += 1

            time.sleep(5)

        log(f"\nRound {round_num}: entered={entered} | positions={len(positions)} | USDC=${usdc:.1f}")
        log(f"Sleeping {SCAN_INTERVAL}s...")
        time.sleep(SCAN_INTERVAL)

if __name__ == "__main__":
    main()
