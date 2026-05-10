#!/usr/bin/env python3
"""
SOL Meme Hunter v3 — WebSocket 持续监听架构
策略：少而准，持续盯链，高标准出手
"""
import subprocess, json, time, os, threading, queue
from datetime import datetime

# ─── 配置 ─────────────────────────────────────────────────────────────────────
WALLET    = "AXBCfbioEHiJ48ejNp5feEzWt2iHFLUDNMk27t5vXWLE"
USDC_ADDR = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

MAX_POSITION  = 3      # 单笔 3U
SAFETY_LINE   = 80     # USDC 低于此值暂停开仓
MAX_POSITIONS = 6      # 最多同时持仓数量

# ── 出手条件（基于65个样本真实数据校准 v3.2）──────────────────────────────────────
#
# 关键发现（SM组 vs 无SM组 对比）：
#   1. creator_close 是 100% SM币的共同特征 → 加入强制过滤
#   2. TOP10 在 SM币中普遍 12-22%，危险阈值 >50%
#   3. bundle/sniper 无法排除高倍币（BMNTP bundle=36% 涨12000%，Bear sniper=79 涨831%）
#   4. soldRatioPercent 含义：<30%=SM未跑，30-50%=出本金但仍持有，>50%=信号失效
#   5. SM数量 >= 10 为强信号，SM=3-9 为中等信号
#   6. 危险无SM组特征：top10>80% 或 bundle=100% 且 SM=0

MIN_SM_WALLETS    = 3      # 至少3个聪明钱（早期信号仅3-4个，等SM=10再进就晚了）
MAX_SOLD_RATIO    = 50     # soldRatio < 50%（出了本金但还持仓的SM仍是有效信号）
MIN_MC            = 15000  # 最小市值 $15k（过低的MC数据质量差，信号不可靠）
MAX_MC            = 500000 # 最大市值 $500k（SM信号出现时MC已到几十万，不限太死）
MAX_BUNDLE        = 50     # bundle无淘汰效力，设50%仅过滤极端情况（bundle=100%）
MAX_RUG_RATIO     = 0.25   # rug风险 < 0.25
MAX_TOP10         = 0.40   # top10 < 40%（SM币实测12-22%，40%已足够宽松）
MAX_SNIPER        = 100    # sniper不作为淘汰条件（Bear sniper=79仍然涨831%）
DEV_MUST_CLOSE    = True   # creator_close 强制要求（SM组100%验证）
REQUIRE_DUAL_SRC  = False  # 先单源，积累数据后再开启
KLINE_HIGH_PCT    = 0.95   # 开盘即拉无回调，放宽到95%
KLINE_VOL_PCT     = 0.80   # 量能要求
KLINE_AGE_SKIP    = 600    # 开盘后10分钟内跳过K线检查

LOG_FILE = "/tmp/meme_hunter_v3.log"

os.environ["PATH"] = "/home/ubuntu/.local/bin:/home/ubuntu/.nvm/versions/node/v22.22.2/bin:" + os.environ.get("PATH", "")

# ─── 工具 ──────────────────────────────────────────────────────────────────────
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

# ─── WebSocket 监听 ───────────────────────────────────────────────────────────
class WSListener:
    """启动 onchainos ws session，持续 poll 事件放入队列"""

    def __init__(self, event_queue):
        self.q = event_queue
        self.sessions = {}  # name -> session_id

    def start_sessions(self):
        log("Starting WebSocket sessions...")

        # 频道1: SM + KOL 实时交易
        out = run("onchainos ws start --channel kol_smartmoney-tracker-activity --idle-timeout 0")
        d = jparse(out)
        sid = d.get("data", {}).get("id", "")
        if sid:
            self.sessions["sm_tracker"] = sid
            log(f"  sm_tracker session: {sid}")

        # 频道2: Solana 实时信号
        out2 = run("onchainos ws start --channel dex-market-new-signal-openapi --chain-index 501 --idle-timeout 0")
        d2 = jparse(out2)
        sid2 = d2.get("data", {}).get("id", "")
        if sid2:
            self.sessions["signal"] = sid2
            log(f"  signal session: {sid2}")

        # 频道3: Solana 新盘上线
        out3 = run("onchainos ws start --channel dex-market-memepump-new-token-openapi --chain-index 501 --idle-timeout 0")
        d3 = jparse(out3)
        sid3 = d3.get("data", {}).get("id", "")
        if sid3:
            self.sessions["new_token"] = sid3
            log(f"  new_token session: {sid3}")

        log(f"WebSocket sessions started: {len(self.sessions)}/3")
        return len(self.sessions) > 0

    def poll_loop(self):
        """持续 poll 所有 session，把事件放入队列"""
        while True:
            for name, sid in list(self.sessions.items()):
                out = run(f"onchainos ws poll --id {sid}", timeout=15)
                d = jparse(out)
                events = d.get("data", {}).get("events", [])
                for evt in events:
                    self.q.put({"source": name, "event": evt})
            time.sleep(2)  # 每2秒轮询一次，近实时

    def stop_all(self):
        run("onchainos ws stop")
        log("WebSocket sessions stopped")

# ─── 信号聚合 ─────────────────────────────────────────────────────────────────
class SignalAggregator:
    """聚合来自不同 WS 频道的信号，找到多源共振的 token"""

    def __init__(self):
        # addr -> {okx_count, gmgn_count, wallets, mc, sym, last_seen}
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

        with self.lock:
            if addr not in self.signals:
                self.signals[addr] = {
                    "okx_count": 0, "gmgn_count": 0,
                    "wallets": set(), "mc": mc, "sym": sym,
                    "last_seen": time.time(), "sold_ratio": 100
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

            elif source == "signal":
                s["okx_count"] += 1

            elif source == "new_token":
                s["gmgn_count"] += 1

    def get_strong_signals(self):
        """返回达到出手标准的 token 列表"""
        now = time.time()
        result = []
        with self.lock:
            # 清理超过30分钟的旧信号
            stale = [a for a, s in self.signals.items() if now - s["last_seen"] > 1800]
            for a in stale:
                del self.signals[a]

            for addr, s in self.signals.items():
                total_wallets = len(s["wallets"])
                okx = s["okx_count"]
                sold = s["sold_ratio"]

                # 出手条件
                if total_wallets < MIN_SM_WALLETS:
                    continue
                if sold > MAX_SOLD_RATIO:
                    continue
                if REQUIRE_DUAL_SRC and not (okx >= 3 and s["gmgn_count"] >= 1):
                    # 放宽：OKX信号 >=5 也可以单独触发
                    if total_wallets < 8:
                        continue

                result.append({
                    "addr": addr,
                    "sym": s["sym"],
                    "mc": s["mc"],
                    "wallets": total_wallets,
                    "sold": sold,
                    "okx": okx,
                    "score": total_wallets * 2 + okx - sold / 10
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
        for key in ["marketCapUsd", "market_cap", "usdMarketCap", "mcap"]:
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
        token = evt.get("token", {})
        return token.get("symbol", "?")

    def _extract_wallets(self, source, evt):
        if source == "sm_tracker":
            addr = evt.get("maker") or evt.get("walletAddress", "")
            return {addr} if addr else set()
        wallets_str = evt.get("triggerWalletAddress", "")
        if wallets_str:
            return set(wallets_str.split(","))
        return set()

# ─── 五关过滤 ─────────────────────────────────────────────────────────────────
def gate_check(addr):
    # Gate 1: 蜜罐 + 基础风险
    out = run(f"onchainos security token-scan --tokens '501:{addr}'", timeout=20)
    d = jparse(out)
    r = (d.get("data") or [{}])[0]
    if r.get("isHoneypot"):          return False, "G1:honeypot"
    if r.get("riskLevel") == "HIGH": return False, "G1:HIGH risk"
    if r.get("isWash"):              return False, "G1:wash"
    if r.get("isMintable"):          return False, "G1:mintable"

    # Gate 2+4: GMGN 安全检查
    out2 = run(f"gmgn-cli token security --chain sol --address {addr} --raw", timeout=20)
    d2 = jparse(out2)
    if d2:
        if not d2.get("renounced_mint"):           return False, "G2:mint"
        if not d2.get("renounced_freeze_account"): return False, "G2:freeze"
        if float(d2.get("rug_ratio") or 0) > MAX_RUG_RATIO:
            return False, f"G2:rug={d2.get('rug_ratio')}"
        if float(d2.get("top_10_holder_rate") or 0) > MAX_TOP10:
            return False, f"G4:top10={d2.get('top_10_holder_rate')}"
        # creator_close 强制要求（65个样本中SM组100%验证为creator_close）
        cstatus = d2.get("creator_token_status", "")
        if DEV_MUST_CLOSE and cstatus == "creator_hold":
            return False, "G2:dev_still_holding"
        if d2.get("is_wash_trading"):
            return False, "G4:wash"
        # sniper 不再作为淘汰条件（Bear sniper=79 仍然涨831%）

    # Gate 3: Bundle
    out3 = run(f"onchainos memepump token-bundle-info --address {addr}", timeout=20)
    d3 = jparse(out3)
    pct = float(d3.get("data", {}).get("bundlerAthPercent") or 0)
    if pct > MAX_BUNDLE:
        return False, f"G3:bundle={pct:.0f}%"

    # Gate 5: SM 是否在出货
    out5 = run(
        f"gmgn-cli token traders --chain sol --address {addr} "
        f"--tag smart_degen --order-by sell_volume_cur --direction desc --limit 5 --raw",
        timeout=20
    )
    d5 = jparse(out5)
    traders = d5.get("list", [])
    if traders:
        top = traders[0]
        sv = float(top.get("sell_volume_cur") or 0)
        bv = float(top.get("buy_volume_cur") or 0)
        if bv > 0 and sv > bv * 1.3:
            return False, f"G5:SM_exit sell${sv:.0f}>buy${bv:.0f}"

    return True, "PASS"

# ─── K线时机检查 ──────────────────────────────────────────────────────────────
def kline_check(addr, token_open_ts=0):
    now_ts = int(time.time())

    # 新开盘10分钟内跳过K线检查（开盘即拉无回调窗口）
    if token_open_ts > 0:
        age_sec = now_ts - token_open_ts
        if age_sec < KLINE_AGE_SKIP:
            return True, f"new_token age={age_sec}s skip_kline"

    tf = now_ts - 3600
    out = run(
        f"gmgn-cli market kline --chain sol --address {addr} "
        f"--resolution 5m --from {tf} --to {now_ts} --raw", timeout=20
    )
    d = jparse(out)
    candles = d.get("list", [])
    if len(candles) < 3:
        # 数据不足时放行（新币数据可能不完整）
        return True, "kline:insufficient_data(pass)"

    closes = [float(c["close"]) for c in candles]
    vols   = [float(c["volume"]) for c in candles]
    highs  = [float(c["high"]) for c in candles]
    high1h = max(highs)
    avg_v  = sum(vols) / len(vols) if vols else 1
    last2v = sum(vols[-2:]) / 2 if len(vols) >= 2 else avg_v
    cur    = closes[-1]

    pct_h = cur / high1h if high1h > 0 else 1
    vol_r = last2v / avg_v if avg_v > 0 else 1

    if pct_h > KLINE_HIGH_PCT:
        return False, f"KL:price={pct_h:.0%}ofHigh"
    if vol_r > KLINE_VOL_PCT:
        return False, f"KL:vol={vol_r:.0%} not declining"

    return True, f"{pct_h:.0%}ofHigh vol={vol_r:.0%}"

# ─── 执行交易 ─────────────────────────────────────────────────────────────────
def execute_swap(addr, sym, amount):
    cmd = (
        f"onchainos swap execute "
        f"--from {USDC_ADDR} --to {addr} "
        f"--readable-amount {amount} "
        f"--chain solana --wallet {WALLET} "
        f"--gas-level fast --slippage 15"
    )
    out = run(cmd, timeout=90)
    d = jparse(out)
    tx = d.get("data", {}).get("swapTxHash", "")
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
    for addr, pos in list(positions.items()):
        sym = pos["sym"]
        entry = pos.get("entry_price", 0)
        if not entry:
            continue
        out = run(f"onchainos token price-info --address {addr} --chain solana", timeout=15)
        d = jparse(out)
        cur = float(d.get("data", {}).get("price") or 0)
        if not cur:
            continue
        pnl = (cur - entry) / entry
        age_h = (time.time() - pos["entry_time"]) / 3600
        log(f"  {sym}: PnL={pnl:+.1%} age={age_h:.1f}h")

        amount_held = pos.get("amount_tokens", 0)

        if pnl >= 0.60 and not pos.get("tp1"):
            log(f"  TP1 +60% {sym} -- sell 25%")
            execute_swap(USDC_ADDR, sym, 0)  # placeholder, need token->USDC swap
            pos["tp1"] = True
        if pnl >= 1.50 and not pos.get("tp2"):
            log(f"  TP2 +150% {sym} -- sell 25%")
            pos["tp2"] = True
        if pnl >= 3.00 and not pos.get("tp3"):
            log(f"  TP3 +300% {sym} -- sell 15%")
            pos["tp3"] = True
        if age_h > 48:
            log(f"  Time stop {sym}")
            del positions[addr]
            break

# ─── 主程序 ───────────────────────────────────────────────────────────────────
def main():
    log("=" * 55)
    log("SOL MEME HUNTER v3 -- WebSocket Architecture")
    log(f"Wallet: {WALLET}")
    log(f"Entry: ${MAX_POSITION} | Min SM wallets: {MIN_SM_WALLETS} | Max sold: {MAX_SOLD_RATIO}%")
    log(f"MC range: ${MIN_MC}-${MAX_MC} | Dual source required: {REQUIRE_DUAL_SRC}")
    log("=" * 55)

    event_queue = queue.Queue()
    aggregator  = SignalAggregator()
    ws_listener = WSListener(event_queue)
    positions   = {}
    acted       = set()   # 已处理过的 addr（进场后不重复）

    # 启动 WebSocket sessions
    if not ws_listener.start_sessions():
        log("WebSocket sessions failed -- falling back to polling mode")
        # fallback: 每30秒轮询一次信号
        fallback_mode = True
    else:
        fallback_mode = False

    # 启动 WS poll 线程
    if not fallback_mode:
        poll_thread = threading.Thread(target=ws_listener.poll_loop, daemon=True)
        poll_thread.start()
        log("WS poll thread started")

    # ── 主循环 ────────────────────────────────────────────────────────────────
    round_num = 0
    last_balance_check = 0
    last_position_check = 0
    usdc = 200.0

    while True:
        round_num += 1
        now = time.time()

        # 余额检查（每60秒一次）
        if now - last_balance_check > 60:
            usdc = get_usdc_balance()
            last_balance_check = now
            log(f"USDC: ${usdc:.1f} | Positions: {len(positions)}")

        # 安全线
        if usdc < SAFETY_LINE:
            log(f"SAFETY LINE ${usdc:.1f} -- paused")
            time.sleep(30)
            continue

        # 持仓检查（每5分钟一次）
        if now - last_position_check > 300:
            check_and_tp(positions)
            last_position_check = now

        # 处理 WS 事件
        if not fallback_mode:
            processed = 0
            while not event_queue.empty() and processed < 50:
                item = event_queue.get_nowait()
                aggregator.add_event(item["source"], item["event"])
                processed += 1
        else:
            # fallback: 直接调用 REST API
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

        # 获取强信号
        strong = aggregator.get_strong_signals()
        if strong:
            log(f"Strong signals: {len(strong)} -- top: {strong[0]['sym']} wallets={strong[0]['wallets']} sold={strong[0]['sold']:.0f}%")

        # 检查是否可以开仓
        if len(positions) >= MAX_POSITIONS:
            time.sleep(5)
            continue

        for sig in strong[:3]:
            addr = sig["addr"]
            sym  = sig["sym"]
            mc   = sig["mc"]

            if addr in acted or addr in positions:
                continue

            log(f"\nEvaluating {sym} ({addr[:12]}...) MC=${mc:.0f} wallets={sig['wallets']} sold={sig['sold']:.0f}%")

            # 五关过滤
            ok, reason = gate_check(addr)
            if not ok:
                log(f"  REJECT {reason}")
                acted.add(addr)
                continue

            # K线时机
            ok2, reason2 = kline_check(addr)
            if not ok2:
                log(f"  WAIT {reason2} -- waiting")
                # 不加入 acted，等K线好了再试
                continue

            log(f"  Gates PASS | K-line: {reason2}")

            # 仓位大小
            pos_size = MAX_POSITION if usdc > 150 else (2 if usdc > 100 else 1)

            ok3, tx = execute_swap(addr, sym, pos_size)
            if ok3:
                positions[addr] = {
                    "sym": sym, "amount_usd": pos_size,
                    "entry_time": time.time(), "entry_price": 0,
                    "source": sig.get("source", "ws")
                }
                acted.add(addr)
                usdc -= pos_size
                log(f"  Entered {sym} ${pos_size} | USDC remaining: ${usdc:.1f}")
            else:
                acted.add(addr)  # 失败也标记，避免反复尝试

            time.sleep(3)

        # 主循环节奏（WS模式近实时，fallback模式30秒）
        time.sleep(2 if not fallback_mode else 30)

if __name__ == "__main__":
    main()
