#!/usr/bin/env python3
"""
SOL Meme Hunter v4 — OKX战场专属架构
核心发现：
  1. inflowUsd > 0 的币100%在涨，< 0 的100%在跌（OKX hot-tokens数据验证）
  2. OKX战场MC中位数 $585k，不是pump.fun新盘
  3. riskLevelControl=1 是OKX自己的安全背书
  4. creator_close 是 SM高倍币100%验证的必要条件
  5. 晚间（UTC 14:00-22:00 / 北京时间 22:00-06:00）安全线提高到 $150
"""
import subprocess, json, time, os, threading, queue
from datetime import datetime, timezone

WALLET    = "AXBCfbioEHiJ48ejNp5feEzWt2iHFLUDNMk27t5vXWLE"
USDC_ADDR = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

MAX_POSITION   = 3      # 单笔 3U
SAFETY_LINE    = 80     # 白天安全线
SAFETY_LINE_NIGHT = 150 # 晚间安全线（UTC 14:00-22:00，北京 22:00-06:00）
MAX_POSITIONS  = 6

# ── OKX战场专属参数（基于真实数据校准）─────────────────────────────────────────
# 核心信号：OKX signal list + OKX hot-tokens inflowUsd
# 验证数据：inflowUsd>0 涨组100% vs 跌组0%
# ── 参数（基于320个样本数据分析最终版 v4.1）──────────────────────────────────
# 核心数据发现：
#   SM 3-29 + MC $50k-500k + liq $5k-100k + top10<25% → 死亡率25%，涨>100% 17%
#   流动性>$100k 后涨>100% 接近 0%，流动性$5k-20k 涨幅最佳
#   MAX_SM 不设上限（热门大meme SM很多但仍然值得跟）
#   soldRatio<35% 才是真正早期信号（>35% 聪明钱已大量离场）
OKX_INFLOW_MIN    = 1000   # hot-tokens inflowUsd 最低 $1000
OKX_RISK_MAX      = 1      # riskLevelControl <= 1
MIN_SM_WALLETS    = 3      # 至少3个SM钱包
MAX_SOLD_RATIO    = 35     # soldRatio < 35%（真正早期信号）
MIN_MC            = 50000  # 最小市值 $50k（<$50k 死亡率>50%）
MAX_MC            = 500000 # 最大市值 $500k（$50k-500k 是最优区间）
MIN_LIQ           = 5000   # 最低流动性 $5k（$5k-20k 是最佳涨幅区间）
MAX_LIQ           = 100000 # 最高流动性 $100k（>$100k 涨>100% 接近0%）
MAX_BUNDLE        = 50     # bundle宽松（不是淘汰条件）
MAX_RUG_RATIO     = 0.25
MAX_TOP10         = 0.25   # top10 < 25%（数据显示25%以下最优）
DEV_MUST_CLOSE    = True   # creator_close 强制（65个样本100%验证）
REQUIRE_DUAL_SRC  = False
KLINE_HIGH_PCT    = 0.95
KLINE_VOL_PCT     = 0.80
KLINE_AGE_SKIP    = 600

LOG_FILE = "/tmp/meme_hunter_v4.log"
os.environ["PATH"] = "/home/ubuntu/.local/bin:/home/ubuntu/.nvm/versions/node/v22.22.2/bin:" + os.environ.get("PATH", "")

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
    except:
        return ""

def jparse(raw):
    try:
        return json.loads(raw)
    except:
        return {}

def sf(v):
    try: return float(v) if v else 0
    except: return 0

def is_night_time():
    """晚间模式：UTC 14:00-22:00（北京时间 22:00-06:00）"""
    utc_hour = datetime.now(timezone.utc).hour
    return 14 <= utc_hour < 22

def get_safety_line():
    """根据时间返回安全线"""
    if is_night_time():
        return SAFETY_LINE_NIGHT
    return SAFETY_LINE

def get_max_position(usdc):
    """根据余额和时间确定仓位大小"""
    night = is_night_time()
    if night:
        # 晚间更保守
        if usdc > 170: return 2
        if usdc > 150: return 1
        return 0  # 晚间安全线触发，不开仓
    else:
        if usdc > 150: return MAX_POSITION
        if usdc > 120: return 2
        return 1

# ─── OKX热门榜缓存（每5分钟刷新一次）──────────────────────────────────────────
_hot_tokens_cache = {}
_hot_tokens_ts = 0

def get_hot_tokens_inflow():
    """获取 OKX hot-tokens 的 inflowUsd 数据，带缓存"""
    global _hot_tokens_cache, _hot_tokens_ts
    now = time.time()
    if now - _hot_tokens_ts < 300 and _hot_tokens_cache:
        return _hot_tokens_cache

    out = run("onchainos token hot-tokens --chain solana --ranking-type 4 --limit 50", timeout=25)
    d = jparse(out)
    items = d.get('data', [])
    if isinstance(items, dict):
        items = items.get('list', [])

    result = {}
    for t in items:
        addr = t.get('tokenContractAddress', '')
        if addr:
            result[addr] = {
                'inflow': sf(t.get('inflowUsd', 0)),
                'risk': int(sf(t.get('riskLevelControl', 99))),
                'top10': sf(t.get('top10HoldPercent', 100)),
                'bundle': sf(t.get('bundleHoldPercent', 1)),
                'dev': sf(t.get('devHoldPercent', 1)),
                'mc': sf(t.get('marketCap', 0)),
                'change': sf(t.get('change', 0)),
                'sym': t.get('tokenSymbol', '?'),
                'liq': sf(t.get('liquidity', 0)),
            }

    _hot_tokens_cache = result
    _hot_tokens_ts = now
    log(f"  hot-tokens refreshed: {len(result)} tokens")
    return result

def get_hot_token_candidates(hot_data):
    """路径A：直接从 hot-tokens 找候选，不依赖 signal list"""
    candidates = []
    for addr, info in hot_data.items():
        inflow = info.get('inflow', 0)
        change = info.get('change', 0)
        top10  = info.get('top10', 100)
        mc     = info.get('mc', 0)
        risk   = info.get('risk', 99)
        sym    = info.get('sym', '?')
        liq    = info.get('liq', 0)

        if inflow < 1000: continue
        if change < 5: continue
        if top10 > MAX_TOP10 * 100: continue
        if not (MIN_MC < mc < MAX_MC): continue
        if risk > OKX_RISK_MAX: continue
        if not (MIN_LIQ <= liq <= MAX_LIQ): continue

        candidates.append({
            'addr': addr, 'sym': sym, 'mc': mc,
            'inflow': inflow, 'change': change,
            'source': 'hot_inflow',
            'score': inflow / 1000 + change / 10
        })
    return sorted(candidates, key=lambda x: -x['score'])


# ─── WebSocket 监听 ────────────────────────────────────────────────────────────
class WSListener:
    def __init__(self, event_queue):
        self.q = event_queue
        self.sessions = {}

    def start_sessions(self):
        log("Starting WebSocket sessions...")
        # SM + KOL 实时交易
        out = run("onchainos ws start --channel kol_smartmoney-tracker-activity --idle-timeout 0")
        d = jparse(out)
        sid = d.get("data", {}).get("id", "")
        if sid:
            self.sessions["sm_tracker"] = sid
            log(f"  sm_tracker: {sid}")

        # Solana 实时信号
        out2 = run("onchainos ws start --channel dex-market-new-signal-openapi --chain-index 501 --idle-timeout 0")
        d2 = jparse(out2)
        sid2 = d2.get("data", {}).get("id", "")
        if sid2:
            self.sessions["signal"] = sid2
            log(f"  signal: {sid2}")

        # 新盘上线
        out3 = run("onchainos ws start --channel dex-market-memepump-new-token-openapi --chain-index 501 --idle-timeout 0")
        d3 = jparse(out3)
        sid3 = d3.get("data", {}).get("id", "")
        if sid3:
            self.sessions["new_token"] = sid3
            log(f"  new_token: {sid3}")

        log(f"WS sessions: {len(self.sessions)}/3")
        return len(self.sessions) > 0

    def poll_loop(self):
        while True:
            for name, sid in list(self.sessions.items()):
                out = run(f"onchainos ws poll --id {sid}", timeout=15)
                d = jparse(out)
                events = d.get("data", {}).get("events", [])
                for evt in events:
                    self.q.put({"source": name, "event": evt})
            time.sleep(2)

    def stop_all(self):
        run("onchainos ws stop")

# ─── 信号聚合 ─────────────────────────────────────────────────────────────────
class SignalAggregator:
    def __init__(self):
        self.signals = {}
        self.lock = threading.Lock()

    def add_event(self, source, event):
        addr = self._extract_addr(source, event)
        if not addr:
            return
        mc = self._extract_mc(event)
        sym = self._extract_sym(event)
        wallets = self._extract_wallets(source, event)

        if not (MIN_MC < mc < MAX_MC):
            return
        # 流动性在 add_event 时无法获取，在 gate_check 里验证

        with self.lock:
            if addr not in self.signals:
                self.signals[addr] = {
                    "okx_count": 0, "wallets": set(), "mc": mc,
                    "sym": sym, "last_seen": time.time(), "sold_ratio": 100
                }
            s = self.signals[addr]
            s["last_seen"] = time.time()
            s["mc"] = mc
            if sym != "?": s["sym"] = sym

            if source == "sm_tracker":
                s["okx_count"] += len(wallets)
                s["wallets"].update(wallets)
                sold = event.get("soldRatioPercent", 100)
                if isinstance(sold, (int, float)):
                    s["sold_ratio"] = min(s["sold_ratio"], float(sold))
            elif source in ("signal", "new_token"):
                s["okx_count"] += 1

    def get_strong_signals(self):
        now = time.time()
        result = []
        with self.lock:
            stale = [a for a, s in self.signals.items() if now - s["last_seen"] > 1800]
            for a in stale:
                del self.signals[a]

            for addr, s in self.signals.items():
                total_w = len(s["wallets"])
                sold = s["sold_ratio"]
                if total_w < MIN_SM_WALLETS: continue
                if sold > MAX_SOLD_RATIO: continue
                result.append({
                    "addr": addr, "sym": s["sym"], "mc": s["mc"],
                    "wallets": total_w, "sold": sold,
                    "okx": s["okx_count"],
                    "score": total_w * 2 + s["okx_count"] - sold / 10
                })
        return sorted(result, key=lambda x: -x["score"])

    def _extract_addr(self, source, evt):
        if source == "sm_tracker":
            return evt.get("baseAddress") or evt.get("base_address", "")
        elif source == "signal":
            return evt.get("tokenAddress") or evt.get("token", {}).get("tokenAddress", "")
        elif source == "new_token":
            return evt.get("address") or evt.get("tokenAddress", "")
        return ""

    def _extract_mc(self, evt):
        for key in ["marketCapUsd", "market_cap", "usdMarketCap"]:
            v = evt.get(key)
            if v:
                try: return float(v)
                except: pass
        token = evt.get("token", {})
        for key in ["marketCapUsd", "market_cap"]:
            v = token.get(key)
            if v:
                try: return float(v)
                except: pass
        return 0

    def _extract_sym(self, evt):
        for key in ["symbol", "tokenSymbol"]:
            v = evt.get(key)
            if v: return v
        return evt.get("token", {}).get("symbol", "?")

    def _extract_wallets(self, source, evt):
        if source == "sm_tracker":
            addr = evt.get("maker") or evt.get("walletAddress", "")
            return {addr} if addr else set()
        ws = evt.get("triggerWalletAddress", "")
        return set(ws.split(",")) if ws else set()

# ─── OKX专属五关过滤 ──────────────────────────────────────────────────────────
def gate_check(addr, hot_data=None, source='signal'):
    """
    OKX战场过滤器：
    Gate 0: OKX inflowUsd > 0（新增，OKX独有的最强信号）
    Gate 1: 蜜罐 + 基础风险
    Gate 2: dev行为 + top10 + creator_close
    Gate 3: bundle
    Gate 5: SM出货检测

    source='hot_inflow' 路径A：Gate0已由候选筛过，DEV_MUST_CLOSE 仍强制
    source='signal'     路径B：DEV_MUST_CLOSE 放宽为仅记录日志
    """
    # Gate 0: OKX inflowUsd 检查（OKX战场核心信号）
    if hot_data and addr in hot_data:
        token_hot = hot_data[addr]
        inflow = token_hot.get('inflow', 0)
        risk = token_hot.get('risk', 99)
        top10_hot = token_hot.get('top10', 100)

        if inflow < OKX_INFLOW_MIN:
            return False, f"G0:inflow=${inflow:.0f}<${OKX_INFLOW_MIN}"
        if risk > OKX_RISK_MAX:
            return False, f"G0:risk={risk}>{OKX_RISK_MAX}"
        if top10_hot > MAX_TOP10 * 100:  # hot-tokens 用百分比值
            return False, f"G0:top10={top10_hot:.1f}%"

    # Gate 0.5: 流动性检查（数据验证：liq>$100k 后涨>100% 接近0%）
    if hot_data and addr in hot_data:
        liq = hot_data[addr].get('liq', 0)
        if liq > 0 and not (MIN_LIQ <= liq <= MAX_LIQ):
            return False, f"G0:liq=${liq:.0f} out of ${MIN_LIQ}-${MAX_LIQ}"

    # Gate 1: 蜜罐
    out = run(f"onchainos security token-scan --tokens '501:{addr}'", timeout=20)
    d = jparse(out)
    r = (d.get("data") or [{}])[0]
    if r.get("isHoneypot"):          return False, "G1:honeypot"
    if r.get("riskLevel") == "HIGH": return False, "G1:HIGH_risk"
    if r.get("isWash"):              return False, "G1:wash"
    if r.get("isMintable"):          return False, "G1:mintable"

    # Gate 2: GMGN 安全检查（辅助验证）
    out2 = run(f"gmgn-cli token security --chain sol --address {addr} --raw", timeout=20)
    d2 = jparse(out2)
    if d2:
        if not d2.get("renounced_mint"):           return False, "G2:mint"
        if not d2.get("renounced_freeze_account"): return False, "G2:freeze"
        if sf(d2.get("rug_ratio")) > MAX_RUG_RATIO:
            return False, f"G2:rug={d2.get('rug_ratio')}"
        if sf(d2.get("top_10_holder_rate")) > MAX_TOP10:
            return False, f"G2:top10={d2.get('top_10_holder_rate')}"
        cstatus = d2.get("creator_token_status", "")
        if cstatus == "creator_hold":
            if DEV_MUST_CLOSE and source == 'hot_inflow':
                return False, "G2:dev_still_holding"
            elif cstatus == "creator_hold":
                log(f"  NOTE G2:dev_still_holding (signal path, not rejected)")
        if d2.get("is_wash_trading"):
            return False, "G2:wash"

    # Gate 3: Bundle（宽松，只过滤极端）
    out3 = run(f"onchainos memepump token-bundle-info --address {addr}", timeout=20)
    d3 = jparse(out3)
    pct = sf(d3.get("data", {}).get("bundlerAthPercent"))
    if pct > MAX_BUNDLE:
        return False, f"G3:bundle={pct:.0f}%"

    # Gate 5: SM出货检测
    out5 = run(
        f"gmgn-cli token traders --chain sol --address {addr} "
        f"--tag smart_degen --order-by sell_volume_cur --direction desc --limit 5 --raw",
        timeout=20
    )
    d5 = jparse(out5)
    traders = d5.get("list", [])
    if traders:
        top = traders[0]
        sv = sf(top.get("sell_volume_cur"))
        bv = sf(top.get("buy_volume_cur"))
        if bv > 0 and sv > bv * 1.3:
            return False, f"G5:SM_exit sell${sv:.0f}>buy${bv:.0f}"

    return True, "PASS"

# ─── K线时机 ──────────────────────────────────────────────────────────────────
def kline_check(addr, token_open_ts=0):
    now_ts = int(time.time())
    if token_open_ts > 0 and now_ts - token_open_ts < KLINE_AGE_SKIP:
        return True, f"new_token_skip_kline"

    out = run(
        f"gmgn-cli market kline --chain sol --address {addr} "
        f"--resolution 5m --from {now_ts - 3600} --to {now_ts} --raw", timeout=20
    )
    d = jparse(out)
    candles = d.get("list", [])
    if len(candles) < 3:
        return True, "kline:no_data(pass)"

    closes = [sf(c["close"]) for c in candles]
    vols   = [sf(c["volume"]) for c in candles]
    highs  = [sf(c["high"]) for c in candles]
    high1h = max(highs) if highs else 1
    avg_v  = sum(vols) / len(vols) if vols else 1
    last2v = sum(vols[-2:]) / 2 if len(vols) >= 2 else avg_v
    cur    = closes[-1] if closes else 0

    pct_h = cur / high1h if high1h > 0 else 1
    vol_r = last2v / avg_v if avg_v > 0 else 1

    if pct_h > KLINE_HIGH_PCT: return False, f"KL:price={pct_h:.0%}ofHigh"
    if vol_r > KLINE_VOL_PCT:  return False, f"KL:vol={vol_r:.0%}"
    return True, f"{pct_h:.0%}ofHigh vol={vol_r:.0%}"

# ─── 交易执行 ─────────────────────────────────────────────────────────────────
def execute_swap(addr, sym, amount, is_sell=False):
    """
    买入：USDC → token
    卖出：token → USDC（amount 是 USDC 价值，用比例计算 token 数量）
    """
    if is_sell or "_SELL" in sym:
        # 卖出：from=token, to=USDC
        cmd = (
            f"onchainos swap execute "
            f"--from {addr} --to {USDC_ADDR} "
            f"--readable-amount {amount} "
            f"--chain solana --wallet {WALLET} "
            f"--gas-level fast --slippage 15"
        )
    else:
        # 买入：from=USDC, to=token
        cmd = (
            f"onchainos swap execute "
            f"--from {USDC_ADDR} --to {addr} "
            f"--readable-amount {amount} "
            f"--chain solana --wallet {WALLET} "
            f"--gas-level fast --slippage 15"
        )
    out = run(cmd, timeout=90)
    d   = jparse(out)
    tx  = d.get("data", {}).get("swapTxHash", "")
    if tx:
        log(f"  TX: https://solscan.io/tx/{tx}")
        return True, tx
    log(f"  swap failed: {out[:200]}")
    return False, ""

def get_usdc_balance():
    out = run("onchainos wallet balance --chain solana")
    d = jparse(out)
    for a in d.get("data", {}).get("details", [{}])[0].get("tokenAssets", []):
        if a.get("symbol") == "USDC":
            return float(a.get("balance", 0))
    return 0

# ─── 持仓管理 ─────────────────────────────────────────────────────────────────
def check_and_tp(positions):
    """
    止盈策略：宁可少赚，不能犯错
    +50% → 卖75%，留25%底仓
    +150% → 再卖底仓的50%（此时已是纯利润）
    +300% → 卖剩余的50%，只留极少底仓飞
    止损：-40% 且聪明钱出货 → 清仓
    超时：持仓>48h 无动作 → 清仓
    """
    if not positions:
        return
    log(f"Checking {len(positions)} positions...")
    for addr, pos in list(positions.items()):
        sym        = pos["sym"]
        entry      = pos.get("entry_price", 0)
        amount_usd = pos.get("amount_usd", 0)
        if not entry or not amount_usd:
            continue

        out = run(f"onchainos token price-info --address {addr} --chain solana", timeout=15)
        d   = jparse(out)
        cur = sf(d.get("data", {}).get("price"))
        if not cur:
            continue

        pnl   = (cur - entry) / entry
        age_h = (time.time() - pos["entry_time"]) / 3600
        log(f"  {sym}: PnL={pnl:+.1%} age={age_h:.1f}h entry=${entry:.8f} cur=${cur:.8f}")

        # TP1：+50% → 卖75%，留25%底仓（宁可少赚，保住利润）
        if pnl >= 0.50 and not pos.get("tp1"):
            sell_amt = amount_usd * 0.75
            log(f"  🎯 TP1 +50% {sym} — sell 75% (${sell_amt:.1f}), keep 25% floor")
            ok, tx = execute_swap(addr, sym + "_SELL", sell_amt)
            if ok:
                pos["tp1"]        = True
                pos["amount_usd"] = amount_usd * 0.25
                log(f"  TP1 done, floor=${pos['amount_usd']:.1f}U")

        # TP2：+150% → 再卖底仓50%（此时已是纯利润在飞）
        elif pnl >= 1.50 and pos.get("tp1") and not pos.get("tp2"):
            sell_amt = pos["amount_usd"] * 0.50
            log(f"  🎯 TP2 +150% {sym} — sell 50% of floor (${sell_amt:.1f})")
            ok, tx = execute_swap(addr, sym + "_SELL", sell_amt)
            if ok:
                pos["tp2"]        = True
                pos["amount_usd"] = pos["amount_usd"] * 0.50
                log(f"  TP2 done, floor=${pos['amount_usd']:.1f}U")

        # TP3：+300% → 卖剩余50%，只留极少底仓
        elif pnl >= 3.00 and pos.get("tp2") and not pos.get("tp3"):
            sell_amt = pos["amount_usd"] * 0.50
            log(f"  🎯 TP3 +300% {sym} — sell 50% of remaining (${sell_amt:.1f})")
            ok, tx = execute_swap(addr, sym + "_SELL", sell_amt)
            if ok:
                pos["tp3"]        = True
                pos["amount_usd"] = pos["amount_usd"] * 0.50
                log(f"  TP3 done, moonbag=${pos['amount_usd']:.1f}U")

        # 止损：-40% 且 SM 出货 → 清仓
        elif pnl <= -0.40 and not pos.get("tp1"):
            log(f"  🛑 Stop loss {sym} PnL={pnl:+.1%} — checking SM exit...")
            out5 = run(
                f"gmgn-cli token traders --chain sol --address {addr} "
                f"--tag smart_degen --order-by sell_volume_cur --direction desc --limit 5 --raw",
                timeout=20
            )
            d5 = jparse(out5)
            traders = d5.get("list", [])
            if traders:
                top = traders[0]
                sv = sf(top.get("sell_volume_cur"))
                bv = sf(top.get("buy_volume_cur"))
                if bv > 0 and sv > bv * 1.3:
                    log(f"  🛑 SM exiting confirmed, closing {sym}")
                    del positions[addr]
                    break
                else:
                    log(f"  SM not exiting (sv=${sv:.0f} bv=${bv:.0f}), holding")
            else:
                log(f"  No SM data, holding despite loss")

        # 超时止损：48h 无动作
        if age_h > 48 and addr in positions:
            log(f"  ⏰ Time stop {sym} ({age_h:.0f}h)")
            del positions[addr]
            break

# ─── 主程序 ────────────────────────────────────────────────────────────────────
def main():
    log("=" * 60)
    log("SOL MEME HUNTER v4 — OKX战场专属版")
    log(f"Wallet: {WALLET}")
    log(f"Day safety: ${SAFETY_LINE} | Night safety: ${SAFETY_LINE_NIGHT}")
    log(f"Signal: inflowUsd>${OKX_INFLOW_MIN} + risk<={OKX_RISK_MAX} + SM>={MIN_SM_WALLETS} + soldRatio<{MAX_SOLD_RATIO}%")
    log(f"MC: ${MIN_MC}-${MAX_MC} | liq: ${MIN_LIQ}-${MAX_LIQ} | top10<{MAX_TOP10:.0%} | DEV_MUST_CLOSE: {DEV_MUST_CLOSE}")
    log(f"TP: +50%→sell75% | +150%→sell50%floor | +300%→sell50%remain | SL: -40%+SM_exit")
    log("=" * 60)

    event_queue = queue.Queue()
    aggregator  = SignalAggregator()
    ws_listener = WSListener(event_queue)
    positions   = {}
    acted       = set()

    # 启动 WebSocket
    if not ws_listener.start_sessions():
        log("WS failed — falling back to polling")
        fallback_mode = True
    else:
        fallback_mode = False
        poll_thread = threading.Thread(target=ws_listener.poll_loop, daemon=True)
        poll_thread.start()
        log("WS poll thread started")

    last_balance_check  = 0
    last_position_check = 0
    last_hot_log        = 0
    usdc = 200.0

    while True:
        now = time.time()

        # 余额检查（每60秒）
        if now - last_balance_check > 60:
            usdc = get_usdc_balance()
            safety = get_safety_line()
            night  = is_night_time()
            log(f"USDC: ${usdc:.1f} | Safety: ${safety} | Night: {night} | Positions: {len(positions)}")
            last_balance_check = now

        # 安全线检查
        safety_line = get_safety_line()
        if usdc < safety_line:
            log(f"{'🌙' if is_night_time() else '🔴'} SAFETY LINE ${usdc:.1f} < ${safety_line} — paused")
            time.sleep(30)
            continue

        # 持仓检查（每5分钟）
        if now - last_position_check > 300:
            check_and_tp(positions)
            last_position_check = now

        # 获取 OKX hot-tokens 数据（每5分钟自动刷新）
        hot_data = get_hot_tokens_inflow()

        # 处理 WS 事件 / fallback polling
        if not fallback_mode:
            processed = 0
            while not event_queue.empty() and processed < 50:
                item = event_queue.get_nowait()
                aggregator.add_event(item["source"], item["event"])
                processed += 1
        else:
            out = run("onchainos signal list --chain solana --wallet-type 1,2 --limit 20", timeout=25)
            d = jparse(out)
            for s in d.get("data", []):
                evt = {
                    "tokenAddress": s.get("token", {}).get("tokenAddress", ""),
                    "marketCapUsd": s.get("token", {}).get("marketCapUsd", 0),
                    "symbol": s.get("token", {}).get("symbol", "?"),
                    "triggerWalletAddress": s.get("triggerWalletAddress", ""),
                    "soldRatioPercent": s.get("soldRatioPercent", 100),
                }
                aggregator.add_event("signal", evt)
                aggregator.add_event("sm_tracker", evt)

        # ── 路径A：hot-tokens 直接驱动候选 ──────────────────────────────────────
        hot_candidates = get_hot_token_candidates(hot_data)

        # ── 路径B：signal list 补充候选 ──────────────────────────────────────────
        strong = aggregator.get_strong_signals()

        # 合并去重（路径A优先）
        seen_addrs = set(c['addr'] for c in hot_candidates)
        sig_candidates = []
        for s in strong:
            if s['addr'] not in seen_addrs:
                s.setdefault('source', 'signal')
                sig_candidates.append(s)

        all_candidates = hot_candidates + sig_candidates

        if all_candidates and now - last_hot_log > 60:
            top = all_candidates[0]
            src_tag = top.get('source', '?')
            if src_tag == 'hot_inflow':
                log(f"Top candidate [HOT] {top['sym']} MC=${top['mc']:.0f} change=+{top.get('change',0):.1f}% inflow=${top.get('inflow',0):.0f}")
            else:
                hot_info = hot_data.get(top['addr'], {})
                inflow = hot_info.get('inflow', 'N/A')
                log(f"Top candidate [SIG] {top['sym']} wallets={top.get('wallets',0)} sold={top.get('sold',0):.0f}% inflow=${inflow}")
            last_hot_log = now

        if len(positions) >= MAX_POSITIONS:
            time.sleep(2 if not fallback_mode else 30)
            continue

        # 评估候选（top 6，路径A + 路径B混合）
        for sig in all_candidates[:6]:
            addr   = sig["addr"]
            sym    = sig["sym"]
            mc     = sig["mc"]
            src    = sig.get("source", "signal")
            src_tag = "HOT" if src == "hot_inflow" else "SIG"

            if addr in acted or addr in positions:
                continue

            hot_info = hot_data.get(addr, {})
            inflow   = hot_info.get('inflow', 0)
            in_hot   = addr in hot_data

            if src_tag == "HOT":
                log(f"\nEval [{src_tag}] {sym} ({addr[:12]}...) MC=${mc:.0f} change=+{sig.get('change',0):.1f}% inflow=${inflow:.0f}")
            else:
                log(f"\nEval [{src_tag}] {sym} ({addr[:12]}...) MC=${mc:.0f} wallets={sig.get('wallets',0)} sold={sig.get('sold',0):.0f}%")

            # 路径A：Gate0已由候选条件筛过，直接传 None；路径B传 hot_data
            gate_hot = None if src == 'hot_inflow' else (hot_data if in_hot else None)
            ok, reason = gate_check(addr, gate_hot, source=src)
            if not ok:
                log(f"  REJECT {reason}")
                acted.add(addr)
                continue

            ok2, reason2 = kline_check(addr)
            if not ok2:
                log(f"  WAIT {reason2}")
                continue

            log(f"  PASS | {reason2}")

            pos_size = get_max_position(usdc)
            if pos_size == 0:
                log(f"  SKIP: night mode, position size=0")
                continue

            ok3, tx = execute_swap(addr, sym, pos_size)
            if ok3:
                positions[addr] = {
                    "sym": sym, "amount_usd": pos_size,
                    "entry_time": time.time(), "entry_price": 0,
                    "source": src
                }
                acted.add(addr)
                usdc -= pos_size
                log(f"  ENTERED {sym} ${pos_size} | USDC left: ${usdc:.1f}")
            else:
                acted.add(addr)

            time.sleep(3)

        time.sleep(2 if not fallback_mode else 30)

if __name__ == "__main__":
    main()
