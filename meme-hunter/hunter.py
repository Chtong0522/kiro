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
# ── 参数 v4.5：基于320样本+2小时复盘综合优化 ──────────────────────────────
# 复盘发现：sold>35%是最大障碍（12/12错过），top10>25%拦了6个，MC>500k拦了3个
# soldRatio 完全不可信（signal list 数据是历史数据，早已>35%）
# 改为只依赖 hot-tokens 路径A + inflowUsd 作为主信号
OKX_INFLOW_MIN    = 500    # inflowUsd 降至 $500（放宽抓更多早期机会）
OKX_RISK_MAX      = 2      # risk<=2（risk=2不算高风险，扩大候选池）
MIN_SM_WALLETS    = 3      # 至少3个SM钱包
MAX_SOLD_RATIO    = 85     # soldRatio 放宽（路径B降级为辅助，主要靠路径A）
MIN_MC            = 50000  # 最小市值 $50k（数据验证：<$50k 死亡率>50%）
MAX_MC            = 1500000 # 最大市值 $1.5M（Bear $534k、Bucky $572k 涨幅好）
MIN_LIQ           = 5000   # 最低流动性 $5k
MAX_LIQ           = 200000 # 最高流动性 $200k（Bear/wobbles 流动性>100k 仍然涨）
MAX_BUNDLE        = 50     # bundle宽松
MAX_RUG_RATIO     = 0.25
MAX_TOP10         = 0.35   # top10 < 35%（从25%放宽，top10>25%拦了6个好币）
DEV_MUST_CLOSE    = True   # creator_close 强制
REQUIRE_DUAL_SRC  = False
KLINE_HIGH_PCT    = 0.95
KLINE_VOL_PCT     = 0.80
KLINE_AGE_SKIP    = 600

# 仓位配置：少出手但每笔要准，用户要求高质量大仓位
POS_NORMAL        = 8      # 普通信号：8U
POS_STRONG        = 12     # 强信号：12U（inflowUsd>$5000 或 change>50%）

LOG_FILE = "/tmp/meme_hunter_v4.log"
ACTED_FILE = "/tmp/meme_hunter_acted.json"  # 已处理地址持久化文件
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

def get_max_position(usdc, is_strong=False):
    """
    仓位大小：少出手但每笔要准
    普通信号：8U
    强信号（inflowUsd>5000 或 change>50%）：12U
    晚间更保守
    """
    night = is_night_time()
    if night:
        if usdc > 170: return 3
        if usdc > 150: return 2
        return 0
    else:
        base = POS_STRONG if is_strong else POS_NORMAL
        if usdc > 150: return base
        if usdc > 120: return max(3, base // 2)
        return 3

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

        if inflow < OKX_INFLOW_MIN: continue
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

def load_acted():
    """从文件加载已处理地址，防止重启后重复买入"""
    try:
        if os.path.exists(ACTED_FILE):
            with open(ACTED_FILE, "r") as f:
                data = json.load(f)
                acted = set(data.get("acted", []))
                log(f"  acted加载: {len(acted)}个已处理地址")
                return acted
    except Exception as e:
        log(f"  acted加载失败: {e}")
    return set()

def save_acted(acted):
    """保存已处理地址到文件"""
    try:
        with open(ACTED_FILE, "w") as f:
            json.dump({"acted": list(acted)}, f)
    except Exception as e:
        log(f"  acted保存失败: {e}")

def get_usdc_balance():
    out = run("onchainos wallet balance --chain solana")
    d = jparse(out)
    for a in d.get("data", {}).get("details", [{}])[0].get("tokenAssets", []):
        if a.get("symbol") == "USDC":
            return float(a.get("balance", 0))
    return 0

def load_existing_positions():
    """
    持仓接管：启动时扫描钱包已有 token 余额，自动注入 positions
    跳过 USDC 和 SOL（原生币），其余视为待管理持仓
    """
    log("=== 持仓接管：扫描已有持仓 ===")
    positions = {}
    out = run("onchainos wallet balance --chain solana")
    d = jparse(out)
    assets = d.get("data", {}).get("details", [{}])[0].get("tokenAssets", [])
    skip_syms = {"USDC", "SOL", "WSOL"}
    for a in assets:
        sym     = a.get("symbol", "?")
        addr    = a.get("tokenContractAddress", "")
        bal     = sf(a.get("balance", 0))
        val_usd = sf(a.get("usdValue", 0))
        if sym in skip_syms or not addr or val_usd < 0.5:
            continue
        # 获取当前价格作为 entry_price（接管时无法知道原始买入价，用当前价代替）
        out2 = run(f"onchainos token price-info --address {addr} --chain solana", timeout=15)
        d2   = jparse(out2)
        cur  = sf(d2.get("data", {}).get("price"))
        positions[addr] = {
            "sym":          sym,
            "amount_usd":   val_usd,
            "amount_tokens": bal,
            "entry_price":  cur if cur > 0 else 0,
            "entry_time":   time.time() - 3600,  # 假设持仓1小时（保守估计）
            "source":       "takeover",
        }
        log(f"  接管 {sym}: {bal:.2f}枚 ~${val_usd:.2f} addr={addr[:12]}...")
    log(f"  接管完成，共 {len(positions)} 个持仓")
    return positions

# ─── 持仓管理 ─────────────────────────────────────────────────────────────────
def sell_token(addr, sym, amount_tokens, reason, max_retries=3):
    """
    严格执行卖出，失败自动重试最多3次
    amount_tokens: 要卖出的 token 数量
    """
    for attempt in range(1, max_retries + 1):
        log(f"  💸 [{attempt}/{max_retries}] 卖出 {sym} {amount_tokens:.2f} tokens | 原因: {reason}")
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
            log(f"  ✅ 卖出成功 {sym} | TX: https://solscan.io/tx/{tx}")
            return True, tx
        err = out[:150] if out else "无返回"
        log(f"  ❌ 卖出失败 [{attempt}/{max_retries}] {sym} | {err}")
        if attempt < max_retries:
            time.sleep(5 * attempt)  # 递增等待：5s、10s
    log(f"  🚨 卖出彻底失败 {sym}，已重试{max_retries}次，需人工处理")
    return False, ""


def check_and_tp(positions):
    """
    持仓监控 + 严格自动止盈止损
    策略：
      TP1: +50%  → 自动卖出 75%，保留 25% 底仓（零成本）
      TP2: +150% → 再卖底仓的 50%
      TP3: +300% → 再卖剩余 50%，只留极少底仓飞
      SL:  -40%  → 查 SM 是否出货，确认则清仓；未出货则继续持有
      超时: >48h 无动作 → 全清仓
    每档止盈/止损失败最多重试 3 次
    """
    if not positions:
        return
    log(f"=== 持仓检查 ({len(positions)}个) ===")
    for addr, pos in list(positions.items()):
        sym        = pos["sym"]
        entry      = pos.get("entry_price", 0)
        amt_usd    = pos.get("amount_usd", 0)
        amt_tokens = pos.get("amount_tokens", 0)
        age_h      = (time.time() - pos["entry_time"]) / 3600
        src        = pos.get("source", "?")

        # 获取当前价格
        out = run(f"onchainos token price-info --address {addr} --chain solana", timeout=15)
        d   = jparse(out)
        cur = sf(d.get("data", {}).get("price"))

        if not cur or not entry or not amt_tokens:
            log(f"  ❓ {sym}: 无法获取价格或无持仓数据 age={age_h:.1f}h [{src}]")
            # 超时仍然清仓
            if age_h > 48 and amt_tokens > 0 and not pos.get("timeout_done"):
                log(f"  ⏰ 超时清仓 {sym} ({age_h:.0f}h)")
                ok, _ = sell_token(addr, sym, amt_tokens, "超时>48h清仓")
                if ok:
                    pos["timeout_done"] = True
                    del positions[addr]
            continue

        pnl     = (cur - entry) / entry
        pnl_usd = amt_usd * pnl
        cur_val = amt_tokens * cur

        # 状态标签
        if pnl >= 3.0:    tag = "🚀 +300%+"
        elif pnl >= 1.5:  tag = "🎯 +150%+"
        elif pnl >= 0.5:  tag = "✅ +50%+"
        elif pnl >= 0.0:  tag = "📈 盈利"
        elif pnl >= -0.4: tag = "⚠️ 亏损"
        else:              tag = "🛑 -40%+"

        multiplier = 1 + pnl
        log(f"  {tag} {sym}: 入场${amt_usd:.1f}({amt_tokens:.0f}枚) 现值${cur_val:.2f} {multiplier:.2f}x PnL={pnl:+.1%}(${pnl_usd:+.2f}) age={age_h:.1f}h [{src}]")

        # ── TP1: +50% → 卖 75% ────────────────────────────────────────────────
        if pnl >= 0.50 and not pos.get("tp1_done"):
            sell_amt = amt_tokens * 0.75
            log(f"  🎯 TP1触发 +{pnl:.0%} → 卖出75% ({sell_amt:.0f}枚)")
            ok, _ = sell_token(addr, sym, sell_amt, f"TP1 +{pnl:.0%}")
            if ok:
                pos["tp1_done"]    = True
                pos["amount_tokens"] = amt_tokens * 0.25
                pos["amount_usd"]  = amt_usd * 0.25
                log(f"  TP1完成，底仓剩 {pos['amount_tokens']:.0f}枚 (${pos['amount_usd']:.1f})")

        # ── TP2: +150% → 再卖底仓50% ──────────────────────────────────────────
        elif pnl >= 1.50 and pos.get("tp1_done") and not pos.get("tp2_done"):
            sell_amt = pos["amount_tokens"] * 0.50
            log(f"  🎯 TP2触发 +{pnl:.0%} → 再卖底仓50% ({sell_amt:.0f}枚)")
            ok, _ = sell_token(addr, sym, sell_amt, f"TP2 +{pnl:.0%}")
            if ok:
                pos["tp2_done"]    = True
                pos["amount_tokens"] = pos["amount_tokens"] * 0.50
                pos["amount_usd"]  = pos["amount_usd"] * 0.50
                log(f"  TP2完成，底仓剩 {pos['amount_tokens']:.0f}枚 (${pos['amount_usd']:.1f})")

        # ── TP3: +300% → 再卖剩余50%，留极少底仓 ─────────────────────────────
        elif pnl >= 3.00 and pos.get("tp2_done") and not pos.get("tp3_done"):
            sell_amt = pos["amount_tokens"] * 0.50
            log(f"  🎯 TP3触发 +{pnl:.0%} → 再卖50% ({sell_amt:.0f}枚)")
            ok, _ = sell_token(addr, sym, sell_amt, f"TP3 +{pnl:.0%}")
            if ok:
                pos["tp3_done"]    = True
                pos["amount_tokens"] = pos["amount_tokens"] * 0.50
                pos["amount_usd"]  = pos["amount_usd"] * 0.50
                log(f"  TP3完成，月球底仓 {pos['amount_tokens']:.0f}枚 (${pos['amount_usd']:.1f})")

        # ── SL: -40% → 检查SM出货，确认则清仓 ────────────────────────────────
        elif pnl <= -0.40 and not pos.get("tp1_done") and not pos.get("sl_done"):
            log(f"  🛑 SL触发 {pnl:.0%} → 检查SM是否出货...")
            out5 = run(
                f"gmgn-cli token traders --chain sol --address {addr} "
                f"--tag smart_degen --order-by sell_volume_cur --direction desc --limit 5 --raw",
                timeout=20
            )
            d5 = jparse(out5)
            traders = d5.get("list", [])
            sm_exiting = False
            if traders:
                top = traders[0]
                sv = sf(top.get("sell_volume_cur"))
                bv = sf(top.get("buy_volume_cur"))
                sm_exiting = bv > 0 and sv > bv * 1.3
                log(f"  SM状态: sell=${sv:.0f} buy=${bv:.0f} → {'出货中' if sm_exiting else '未出货'}")

            if sm_exiting:
                log(f"  🛑 SM出货确认，清仓 {sym}")
                ok, _ = sell_token(addr, sym, pos["amount_tokens"], f"SL {pnl:.0%}+SM出货")
                if ok:
                    pos["sl_done"] = True
                    del positions[addr]
                    continue
            else:
                log(f"  ⏸ SM未出货，继续持有 {sym} (pnl={pnl:.0%})")

        # ── 超时止损: >48h 无任何止盈触发 → 清仓 ─────────────────────────────
        if age_h > 48 and addr in positions and not pos.get("tp1_done") and not pos.get("timeout_done"):
            log(f"  ⏰ 超时清仓 {sym} ({age_h:.0f}h，无止盈触发)")
            ok, _ = sell_token(addr, sym, pos["amount_tokens"], f"超时{age_h:.0f}h")
            if ok:
                pos["timeout_done"] = True
                del positions[addr]

# ─── 主程序 ────────────────────────────────────────────────────────────────────
def main():
    log("=" * 60)
    log("SOL MEME HUNTER v4 — OKX战场专属版")
    log(f"Wallet: {WALLET}")
    log(f"Day safety: ${SAFETY_LINE} | Night safety: ${SAFETY_LINE_NIGHT}")
    log(f"Signal: inflowUsd>${OKX_INFLOW_MIN} + risk<={OKX_RISK_MAX} + SM>={MIN_SM_WALLETS} + soldRatio<{MAX_SOLD_RATIO}%")
    log(f"MC: ${MIN_MC}-${MAX_MC} | liq: ${MIN_LIQ}-${MAX_LIQ} | top10<{MAX_TOP10:.0%} | DEV_MUST_CLOSE: {DEV_MUST_CLOSE}")
    log(f"仓位: 普通${POS_NORMAL} | 强信号${POS_STRONG} | 持仓检查3s | TP:+50%→75% +150%→50% +300%→50% | SL:-40%+SM | 重试3次")
    log("=" * 60)

    event_queue = queue.Queue()
    aggregator  = SignalAggregator()
    ws_listener = WSListener(event_queue)
    positions   = load_existing_positions()
    acted       = load_acted()
    acted.update(positions.keys())  # 已接管的地址也加入 acted，防止重复建仓
    save_acted(acted)

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

        # 持仓检查（每3秒，meme价格变化极快）
        if now - last_position_check > 3:
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

            # 强信号判断：inflowUsd>$5000 或 change>50%
            is_strong = (sig.get('inflow', 0) > 5000 or sig.get('change', 0) > 50)
            pos_size = get_max_position(usdc, is_strong=is_strong)
            if pos_size == 0:
                log(f"  SKIP: night mode, position size=0")
                continue
            if is_strong:
                log(f"  💪 强信号 inflow=${sig.get('inflow',0):.0f} change={sig.get('change',0):.1f}% → 仓位${pos_size}")

            ok3, tx = execute_swap(addr, sym, pos_size)
            if ok3:
                # 立即查询买入价格记录，用于止盈止损计算
                price_out = run(f"onchainos token price-info --address {addr} --chain solana", timeout=10)
                price_d = jparse(price_out)
                entry_price = sf(price_d.get("data", {}).get("price"))
                # 估算买入的 token 数量
                amount_tokens = (pos_size / entry_price) if entry_price > 0 else 0
                positions[addr] = {
                    "sym": sym, "amount_usd": pos_size,
                    "amount_tokens": amount_tokens,
                    "entry_time": time.time(), "entry_price": entry_price,
                    "source": src
                }
                log(f"  entry_price=${entry_price:.8f} amount_tokens={amount_tokens:.0f}")
                acted.add(addr)
                save_acted(acted)
                usdc -= pos_size
                log(f"  ENTERED {sym} ${pos_size} | USDC left: ${usdc:.1f}")
            else:
                acted.add(addr)
                save_acted(acted)

            time.sleep(3)

        time.sleep(2 if not fallback_mode else 30)

if __name__ == "__main__":
    main()
