---
name: sol-meme-hunter-v7
description: >
  SOL Meme Hunter v7.0 — The most advanced agentic Solana meme token trading system
  built on onchainOS. Features a proprietary 816-address Smart Wallet database with
  3-tier quality scoring, 4-Tier signal architecture (Smart Wallet Follow + Smart Money
  Signal + Graduation Ambush + Hot Momentum), 9-Layer adaptive exit system with
  cover-cost-first philosophy (TP1 at +100% sells 50% to recover full cost), volume
  confirmation gates, and session risk control designed for safe overnight autonomous
  operation. Single-file Python 3 stdlib bot with TEE-secured wallet signing, atomic
  state persistence, and real-time web dashboard.

  Triggers when the user mentions: meme hunter, SOL meme bot, meme trading bot,
  solana meme scanner, smart money copy trade, smart wallet follow, copy trading bot,
  graduation ambush, pumpfun graduate sniper, hot momentum trader, alpha bot,
  auto trade meme coins, meme coin sniper, pump.fun hunter, solana alpha,
  degen bot, meme coin strategy, on-chain trading bot, agentic wallet trading,
  cover cost strategy, double-and-out, take-profit ladder, trailing stop bot,
  Meme 猎手, 自动交易, 聪明钱跟单, 跟单机器人, 毕业伏击, 热门动量,
  Meme 狙击, SOL Meme 自动, 链上交易机器人, 翻倍出本, 聪明钱包数据库,
  夜间自动运行, 安全过夜, 9层退出, 智能止盈止损, agentic wallet,
  TEE 签名, 链上 alpha, 撸毛机器人, pump.fun 自动, 毕业代币,
  or wants to automatically detect, score, enter, and exit Solana meme tokens
  using onchainOS CLI without API keys. Do NOT trigger for: stocks, traditional
  forex, NFT trading, generic crypto news, ETH/BTC swing trading, or non-Solana chains.

version: 7.0
updated: 2025-05-14
---

# SOL Meme Hunter v7.0

> **Core Philosophy: 翻倍出本，利润奔跑** (Double-and-cover, let profit ride)
>
> When TP1 hits at +100%, sell exactly 50% — this recovers your full cost. Everything remaining is "house money" that runs freely with wide trailing stops to capture 3-10x meme moves.

---

## Why V7 Stands Out

| Innovation | What It Does | Why It Matters |
|-----------|--------------|----------------|
| **Proprietary Smart Wallet DB** | 816 curated Solana addresses, 3-tier quality scoring, role-weighted | Acts as both signal source AND quality filter for every entry. Detects when high-PnL wallets are accumulating before the crowd notices. |
| **4-Tier Signal Architecture** | S → A → B → D priority chain with independent filters | Diversified alpha sources prevent missing trades from any single channel. Each tier has its own optimal entry/exit profile. |
| **Cover-Cost-First TP** | TP1=+100% sells 50%; TP2=+300% sells 30%; TP3=+800% sells 30% | Solves meme coin's biggest dilemma: take profit too early and miss 10x, take too late and round-trip. By recovering cost at 2x, the rest can ride risk-free. |
| **9-Layer Adaptive Exit** | HE1 → FAST_DUMP → LIQ → SL → Time-decay → Timeout → Floor → Trailing → TP | Every failure mode covered. Emergencies override the 10% floor; normal exits respect it. |
| **Volume Confirmation Gate** | 5-min volume ≥ $8K + buy/sell ratio ≥ 1.2 | Filters out dead/manipulated tokens. A token can't pump if nobody's actually trading it. |
| **Safe Overnight Operation** | Daily loss → 30-min PAUSE (not stop). TP/SL keep executing. | Run it before bed without fear. Existing positions are still protected; new entries simply pause. |
| **Floor Position Cleanup** | Loss > -30% or age > 4h with loss → auto-clear | Eliminates dead capital. Stop holding "ghost" floor positions in failed projects. |
| **Sell Failure Force-Remove** | After 15 sell attempts → drop the position | Prevents zombie tokens from blocking position slots indefinitely. |
| **Zero API Keys** | Pure onchainOS CLI + TEE wallet | No API key management, no signing exposure. Plug-and-play deployment. |

---

## Disclaimer

**This strategy is for educational research and technical reference only. It does not constitute investment advice.** Solana meme coin trading carries extreme risk including total loss of capital. Tokens may rug pull within minutes. Past performance does not guarantee future results. Users must understand each parameter and assume full responsibility. See [Full Disclaimer](#full-disclaimer) at bottom.

---

## File Structure

```
meme-hunter/
├── SKILL.md                                          ← Strategy documentation (this file)
├── config.py                                         ← All adjustable V7 parameters (single source of truth)
├── risk_check.py                                     ← Pre/post trade risk assessment module
├── hunter.py                                         ← Main trading bot (2456 lines, single-file)
├── dashboard.html                                    ← Real-time Web Dashboard UI
├── smart_wallets_page_all_all_202605141414.csv       ← Proprietary 816-address smart wallet database
├── setup.sh                                          ← One-command server setup
└── start.sh                                          ← Bot startup script (screen-based)
```

---

## Prerequisites

### 1. Install onchainOS CLI (≥ 2.1.0)

```bash
onchainos --version
# If not installed, setup.sh handles this automatically.
```

**Why onchainOS**: Provides unified access to Solana on-chain data (token info, trades, signals, hot tokens, candles, holders), swap execution via TEE-secured wallet signing, and portfolio management — all through a single CLI with **no API keys required**. This is the foundation that makes V7 possible.

### 2. Agentic Wallet Login (TEE Signing)

```bash
onchainos wallet login <your-email>
onchainos wallet status                     # → loggedIn: true
onchainos wallet addresses --chain 501      # → your Solana address
```

**Why TEE**: Private keys never leave the secure enclave. The bot builds unsigned transactions, sends them to TEE for signing, then broadcasts. **Zero key exposure risk** — your seed phrase is never on disk, in memory, or in logs.

### 3. Zero pip dependencies

V7 uses only Python 3 stdlib + onchainOS CLI. No `pip install`, no API keys, no external services.

---

## Quick Start

```bash
# 1. Server setup (Ubuntu 20.04+)
chmod +x setup.sh && sudo ./setup.sh

# 2. Wallet login (one-time)
onchainos wallet login <your-email>

# 3. Start bot (safe to run overnight!)
~/meme-hunter/start.sh

# 4. Monitor in real-time
open http://localhost:3250          # Web Dashboard
tail -f /tmp/meme_hunter_v7.log     # Live log

# 5. Stop gracefully
screen -X -S meme-hunter quit
```

---

## Strategy Architecture

```
                    ┌─────────────────────────────────────────────┐
                    │       SOL Meme Hunter v7.0                   │
                    │   4-Tier Signal + 9-Layer Exit               │
                    └──────────────────────┬──────────────────────┘
                                           │
              ┌────────────────────────────┼────────────────────────────┐
              │                            │                            │
    ┌─────────┴──────────┐      ┌─────────┴─────────┐      ┌──────────┴──────────┐
    │   Scanner Loop      │      │  Position Monitor │      │   Web Dashboard     │
    │   (main thread)     │      │  (daemon, 1s)     │      │   (HTTP :3250)      │
    └─────────┬───────────┘      └─────────┬─────────┘      └─────────────────────┘
              │                            │
    ┌─────────┴────────┐         ┌─────────┴─────────┐
    │  Tier S (45s)    │         │  9-Layer Exit     │
    │  Tier A (30s)    │         │  System           │
    │  Tier B (60s)    │         │                   │
    │  Tier D (60s)    │         │  + Background     │
    │                  │         │    risk flags     │
    │  ↓ for each:     │         │                   │
    │  • Filter        │         │  ↓ each position: │
    │  • Score boost   │         │  HE1→FAST_DUMP→   │
    │  • Volume confirm│         │  LIQ→SL→Time→     │
    │  • Risk check    │         │  Timeout→Floor→   │
    │  • Buy execution │         │  Trail→TP1/2/3    │
    └──────────────────┘         └───────────────────┘
              │                            │
              └────────────┬───────────────┘
                           │
                  ┌────────┴─────────┐
                  │ Atomic JSON      │
                  │ Persistence      │
                  │ • positions      │
                  │ • trades         │
                  │ • acted          │
                  │ • session_risk   │
                  └──────────────────┘
```

---

## Signal Tier Details

### Tier S: Smart Wallet Follow (V7 Exclusive Innovation)

**Source**: Proprietary database of 816 curated Solana wallet addresses, loaded from CSV at startup.

**Logic**:
1. Every 45 seconds, randomly sample 10 Tier-1 wallets from the database
2. For each wallet, check `onchainos wallet history` for last 5 transactions
3. If a wallet bought a token within the last 30 minutes → evaluate as candidate
4. Run standard filters (MC, liquidity, holders, top10) + volume confirmation + risk check
5. Enter on first qualifying candidate (1 per cycle to avoid clustering)

**Why this works**: Tier-1 wallets were curated from historical performance data — they are demonstrated top-PnL traders across multiple meme coin cycles. When a Tier-1 wallet (盈利Top, 暴富新人, 底部高倍数, 频繁高胜) enters a new token, it's the strongest leading indicator available. Following them puts us **ahead of the crowd**, not behind.

**Position sizing**: $8 day / $5 night (highest confidence tier).

### Tier A: Smart Money Signal

**Source**: `onchainos signal list --chain solana --wallet-type 1,2,3` (SmartMoney + KOL + Whale)

**Logic**:
- **STRONG signal** (≥3 wallets co-buying): Direct entry after filters
- **NORMAL signal** (=2 wallets): Requires hot-tokens confirmation (positive net inflow)
- Both paths run through the same V7 quality gates

**Why this works**: Multi-wallet co-buy patterns are statistically significant. A single whale could be wrong; three independent smart money wallets buying the same token within a short window is a very high-confidence signal.

**Position sizing**: $8 day / $5 night.

### Tier B: Graduation Ambush

**Source**: `onchainos memepump tokens --chain solana --stage MIGRATED`

**Logic**: Catches tokens within 60 minutes of graduating from PumpFun bonding curve to Raydium AMM. Critical: only **MIGRATED** (not MIGRATING) tokens can be swapped through onchainOS.

**V7 Innovation — Fast TP for Tier B**: If the token rises +30% within 10 minutes of entry, fire TP1 immediately. Graduation pumps are often violent and short — capture the move before it reverses.

**Position sizing**: $5 day / $3 night.

### Tier D: Hot Momentum (Dynamic Sizing)

**Source**: `onchainos token hot-tokens --chain solana --ranking-type 4`

**Composite Score (0-100+)**:

| Factor | Weight | Tiers |
|--------|--------|-------|
| Holders | 0-30 | 5000+/2000+/1000+/500+ |
| Buy/sell ratio | 0-25 | 2.0+/1.5+/1.2+/1.0+ |
| Unique traders | 0-15 | 500+/300+/200+/100+ |
| Price change | 0-15 | 30+%/20+%/10+%/5+% |
| Net inflow USD | 0-15 | $50K+/$20K+/$5K+/$0+ |
| **Smart Wallet boost** | **0-50** | **+30 per Tier-1 holder × role multiplier** |

**Dynamic Sizing**:

| Score | Position |
|-------|----------|
| 80+ | $8 (base $5 + bonus $3) |
| 65-79 | $6 (base $5 + bonus $1) |
| 55-64 | $5 (base) |
| < 55 | SKIP (filtered out) |

---

## Smart Wallet Database — V7's Secret Sauce

### Database Composition

816 unique Solana wallet addresses, organized into 3 quality tiers based on historical PnL performance and trading patterns:

| Tier | Wallet Groups | Score Boost | Approx Count |
|------|---------------|-------------|--------------|
| **Tier 1** | 盈利Top (Top Profitable), 暴富新人 (Sudden Wealth), 底部高倍数 (Bottom-buying multi-baggers), 频繁高胜 (Frequent High-winrate), 离场赢家 (Smart Exiters), 低频重炮 (Low-freq Heavy Hitters) | **+30** | ~113 |
| **Tier 2** | 中等盈利 (Medium Profit), 持仓Top (Top Holders), 沉睡OG (Dormant OGs), 微赚 (Slight Profit), 稳健均衡 (Steady) | **+20** | ~250 |
| **Tier 3** | 中性 (Neutral), 早期建仓 (Early Position), 赌徒命中 (Lucky Gamblers) | **+10** | ~240 |
| **Negative** | 亏损者 (Losers), 稳输者 (Consistent Losers) | **-10** | ~213 |

### Role-Based Multiplier (Applied on top of tier boost)

| Role | Multiplier | Interpretation |
|------|-----------|----------------|
| `early-buyer` | 1.5× | Bought before the crowd — strongest leading signal |
| `pnl-leader` | 1.3× | Highest PnL ranking on the token |
| `current-holder` | 1.0× | Currently holds (still believes in it) |
| `peak-seller` | 0.5× | Sold near the peak (if back in, signal is weakened) |

**Example calculation**: A Tier-1 wallet tagged as `early-buyer` and `pnl-leader` who is currently holding → boost = 30 × 1.5 (best multiplier) = **+45 points** added to the token's composite score. With score cap at +50, this single wallet match nearly maxes out the boost.

### Two Usage Modes

1. **Tier S Entry Signal** (Direct): Tier-1 wallet's recent buy → candidate token
2. **Score Boost** (All Tiers): Token's top-20 holders checked against database → boost added to entry decision

---

## 9-Layer Adaptive Exit System

> **Design principles**: Emergencies override the 10% floor. Take-profit and stop-loss are strictly enforced. Floor positions are cleaned when they become dead weight. Designed for safe overnight operation.

| Layer | Trigger | Action | Override Floor? | Why It Exists |
|-------|---------|--------|----------------|---------------|
| **1. HE1 Emergency** | PnL ≤ -50% | Sell 100% | YES | Catastrophic loss — preserve what's left |
| **2. FAST_DUMP** | -20% drop from peak within 60s | Sell 100% | YES | Flash crash detected — rug or exploit |
| **3. LIQ_EMERGENCY** | Liquidity < $5K | Sell 100% | YES | Pool drying up — exit before unable to sell |
| **4. Tiered SL** | -20% (SL1) → -30% (SL2) | SL1: 50%; SL2: 100% | SL2 only | Bleed control with retest opportunity |
| **5. Time-decay SL** | 30min: -15%; 60min: -10% | Sell 50% | No | Tighten as time passes — old loser, cut bait |
| **6. Timeout** | S/A: 48h, B: 6h, D: 12h | Sell 100% | YES | Capital must rotate, no infinite holds |
| **7. Floor Exit** (V7) | Floor pos + loss>-30% OR (age>4h + loss) | Sell 100% | N/A (this IS the floor) | No more dead capital in dust positions |
| **8. Trailing Stop** | After TP1: 20% drop from peak | Sell 40% | No | Lock in gains as the rally fades |
| **9. Take Profit** | TP1=+100%, TP2=+300%, TP3=+800% | TP1: 50%; TP2: 30%; TP3: 30% | No | Cover cost first, then ride profit |

### Take-Profit Math: Why "翻倍出本" is Optimal

```
Initial position: 1.0 unit at $1 entry = $1 cost basis

At +100% (price = $2):
  Sell 50% × 2x = 1.0 unit value recovered = ALL COST IS BACK
  Remaining: 0.5 units = 100% pure profit position

At +300% (price = $4):
  Sell 30% × 4x = 0.6 units worth → +60% additional cash out
  Remaining: 0.2 units (still pure profit)

At +800% (price = $9):
  Sell 30% × 9x = 1.8 units worth → +180% bonus
  Remaining: 0.1 floor

Worst case after TP1: Even if remaining position goes to ZERO,
you still recover your full original capital.

Best case: 0.1 unit holds for +50x → +500% on top of everything.
```

This is the mathematical optimum for high-variance asymmetric bets like meme coins. The downside is capped at break-even (after TP1) while the upside is uncapped.

---

## Volume Confirmation Gate (V7 New)

Before every entry, three checks must pass:

```
1. 5-minute volume ≥ $8,000      # Real activity, not dead chart
2. Buy/sell trade ratio ≥ 1.2    # More buyers than sellers
3. Volume not collapsing         # Recent volume not <30% of earlier
```

**API calls**:
- `onchainos market candles --chain solana --address <addr> --bar 1m` (last 5 candles)
- `onchainos token trades --chain solana --address <addr> --limit 50` (buy/sell counts)

**Why**: A token might pass MC, liquidity, holder, and risk checks — but if nobody is actually trading it, you've entered a dead market. Worse, dropping volume signals momentum dying right as you're entering.

**Result**: Skipped tokens log clear reasons (`vol_5m=$3000<$8000`, `vol_declining_rapidly`, `buy_sell_ratio=0.8<1.2`) for transparency and parameter tuning.

---

## Session Risk Control (V7: No Forced Shutdown)

| Rule | V6 | V7 | Behavior |
|------|----|----|----------|
| Consecutive losses | 3 → pause 10min | 4 → pause 15min | After cooldown, resume |
| Daily loss | $15 → **STOP** | $20 → **PAUSE 30min** | Bot continues, just delays new entries |
| Max concurrent | 6 | 5 | Quality over quantity |
| Startup cooldown | 180s | 120s | Faster scanning warmup |
| Sell fail removal | None | After 15 attempts | Auto-clean zombie positions |

**V7 Critical Change — No Permanent Stop**:
- Daily loss limit triggers a 30-minute pause, not a daily lockout
- The position monitor thread keeps running during pause — TP/SL still execute
- After pause expires, new entries resume
- This means **the bot is genuinely safe to run overnight**: existing positions are protected even when entries are paused

---

## Pre-Trade Risk Assessment (risk_check.py)

Two-stage gating system. Every entry must pass `pre_trade_checks(addr, sym, quick=True)`.

### Severity Grades

| Grade | Action | Triggered By |
|-------|--------|--------------|
| **G4: BLOCK** | Hard refuse | Honeypot flag, buy/sell tax >50%, dev removing liquidity, OKX risk level ≥4, active dump >5 SOL/min |
| **G3: WARN** | Refuse | Serial rugger (≥3 historical rugs OR rug rate >20%), LP <80% burned, snipers >15%, suspicious wallets >10%, wash trading detected |
| **G2: CAUTION** | Allow with note | Top10 holders >30%, bundles >5%, dev sold all (non-CTO), paid DexScreener listing, no smart money detected |
| **G0: PASS** | Clear | All checks passed |

`result["pass"]` is True when grade < 3.

### Post-Trade Monitoring

Runs every 60 seconds per active position:
- `EXIT_NOW`: Dev removing liquidity, liquidity drain >30%, active dump >5 SOL/min
- `EXIT_NEXT_TP`: Volume plunge, soft rug velocity, coordinated holder selling **(V7: downgraded from EXIT_NOW — normal profit-taking should not panic exit)**
- `REDUCE_POSITION`: Sniper concentration spike (>+5% from entry)
- `ALERT`: Top10 concentration drift (informational)

---

## Parameter Quick Reference

### Position Sizing

| Tier | Day Size | Night Size | When |
|------|----------|------------|------|
| S | $8 | $5 | Tier-1 smart wallet bought |
| A | $8 | $5 | ≥2 smart money wallets co-buying |
| B | $5 | $3 | Token graduated within 60min |
| D | $5-$8 | $3-$6 | Score-based dynamic |

Night mode: UTC 14:00-22:00 (Beijing 22:00-06:00) — reduced sizes for low-liquidity hours.

### Entry Filters

| Filter | Tier S | Tier A | Tier B | Tier D |
|--------|--------|--------|--------|--------|
| MC min | $100K | $150K | $50K | $150K |
| MC max | $5M | $3M | $500K | $10M |
| Liquidity min | $30K | $40K | (LP burn check) | $40K |
| Holders min | 100 | 200 | 100 | 500 |
| Top10 max | 45% | 45% | 40% | 35% |
| Volume confirm | YES | YES | YES | YES |
| K1 pump guard | 12% | 12% | 12% | 12% |
| Risk check | quick | quick | quick | quick |

---

## Iron Rules (Must Not Be Violated)

These rules are baked into the code and enforced via locks, validation, and persistence. Documented here so users understand the safety guarantees.

1. **NEVER use `swap execute`**. The only safe swap flow is: `swap swap` (build TX) → `wallet contract-call` (TEE sign + broadcast) → `wallet history` (confirm). `swap execute` would expose private keys.
2. **NEVER delete a position on single zero-balance**. Requires `zero_count ≥ 30` AND age > 24h before ghost cleanup. Solana RPC has high latency; false zeros are common.
3. **NEVER call `save_positions()` outside `pos_lock`**. All position mutations must be thread-safe — the monitor and scanner threads access concurrently.
4. **NEVER buy the same token twice**. The `acted` file is permanent and survives restarts. Tokens that exited (good or bad) get a 30-min cooldown plus permanent acted record.
5. **NEVER buy MIGRATING tokens**. Only MIGRATED tokens can be swapped via onchainOS. Bonding curve tokens fail with "swap returned no data".
6. **Atomic file writes only**. Always write to `.tmp` then `os.replace()` to final path. Prevents corruption from crash mid-write.
7. **Fail-closed safety**. If any safety check API call fails or times out → treat the token as unsafe → skip. Never enter on missing data.
8. **TP/SL always execute**. Even during session pause, the monitor thread continues. Entries pause, exits never.
9. **Floor positions are not sacred**. If the floor is bleeding (-30%+ loss) or aged out (>4h with loss), it gets cleaned. No more dust hoarding.

---

## onchainOS CLI Commands Used

V7 leverages 15 distinct onchainOS commands, all without API keys.

| # | Command | Purpose | Used In |
|---|---------|---------|---------|
| 1 | `signal list --chain solana --wallet-type 1,2,3` | Smart money co-buy signals | Tier A |
| 2 | `memepump tokens --chain solana --stage MIGRATED` | Recently graduated tokens | Tier B |
| 3 | `token hot-tokens --chain solana --ranking-type 4` | Hot momentum ranking | Tier D |
| 4 | `wallet history --address <addr> --chain-index 501 --limit 5` | Smart wallet's recent trades | Tier S |
| 5 | `token price-info --chain solana --address <addr>` | Real-time price/MC/liquidity | All tiers |
| 6 | `token holders --chain solana --address <addr> --limit 20` | Top holders for SW boost check | All tiers |
| 7 | `market candles --chain solana --address <addr> --bar 1m` | Volume confirmation + K1 pump guard | All tiers |
| 8 | `token trades --chain solana --address <addr> --limit 50` | Buy/sell ratio analysis | All tiers |
| 9 | `token advanced-info --chain solana --address <addr>` | Risk assessment data | risk_check.py |
| 10 | `security token-scan --tokens 501:<addr>` | Honeypot/tax detection | risk_check.py |
| 11 | `swap swap --chain solana --from <> --to <> --amount <>` | Build unsigned swap TX | execute_buy/sell |
| 12 | `wallet contract-call --chain 501 --to <> --unsigned-tx <>` | TEE sign + broadcast | execute_buy/sell |
| 13 | `wallet history --tx-hash <> --chain-index 501` | TX confirmation polling | Post-swap |
| 14 | `wallet balance --chain 501` | SOL balance + position takeover | Startup + monitoring |
| 15 | `portfolio token-balances --address <> --tokens 501:<>` | Single token balance check | Position recovery |

---

## Output Format Examples

### Live Log Output

```
[14:23:45] SOL: 0.4521 (~$67.81) | Daily PnL: $+2.13 | Positions: 2/3 | SW: 816 wallets
[14:24:15] Tier S smart wallet candidates: 2
[14:24:18]   Skip_S DOGEX: vol_5m=$3200<$8000
[14:24:22] ENTER TIER_S MOON $8 | MC=$425,000 | SmartWallet=FFcYgSSg
[14:24:25]   swap OK | TX: https://solscan.io/tx/4xK7nP9...
[14:24:48] Tier A SM signals: 5
[14:25:01]   PEPE SmartWallet boost: +45 (2 matched)
[14:25:03] ENTER TIER_A PEPE $8 | MC=$1,250,000 | wallets=3 | sw+45
[14:31:22] SELL MOON [TP1(+100%)] 50% PnL=+102.3% (2.02x)
[14:31:23]   SELL MOON TX: https://solscan.io/tx/8nM2qR5...
[14:45:09] SELL PEPE [TRAILING(20%)] 40% PnL=+185.7% (2.86x)
```

### Dashboard JSON Snippet (`/api/state`)

```json
{
  "stats": {"buys": 12, "sells": 18, "wins": 11, "losses": 7, "net_pnl": 23.45},
  "positions": {
    "9SLPTL...": {
      "symbol": "MOON", "tier": "S",
      "entry_price": 0.0042, "current_price": 0.0084,
      "pnl_pct": 1.0, "tp_tier": 1, "remaining": 0.5,
      "age_min": 7.2, "size_usd": 4.0
    }
  },
  "smart_wallets": {"total": 816, "tier1": 113},
  "session_risk": {"consecutive_losses": 0, "cumulative_loss_usd": 0, "paused_until": 0}
}
```

---

## Common Customizations

All adjustable parameters live in `config.py`. No need to touch `hunter.py` or `risk_check.py`.

| Goal | Edit in `config.py` |
|------|---------------------|
| Pause/resume trading | `PAUSED = True/False` |
| Switch to paper trading | `PAPER_TRADE = True` |
| Increase Tier S confidence | `TIER_S_SIZE_DAY = 12` |
| More aggressive TP1 | `TP_RULES["A"]["tp1_pct"] = 0.50` (50% instead of 100%) |
| Wider stop loss | `SL_RULES["A"]["sl_pct"] = -0.30` |
| Disable Tier S | `TIER_S_ENABLED = False` |
| Faster scanning | `SM_REFRESH_SEC = 15` |
| More positions | `MAX_POSITIONS = 8` |
| Higher daily limit | `DAILY_LOSS_LIMIT = 50` |
| Lower volume bar | `VOLUME_5M_MIN_USD = 5000` |
| Smart wallet boost only | `TIER_S_ENABLED = False` (keeps boost in A/B/D) |

Restart bot for changes to take effect.

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `FATAL: No wallet address` | Run `onchainos wallet login <email>` then verify with `onchainos wallet status` |
| `Smart Wallets: 0 loaded` | Ensure `smart_wallets_page_all_all_202605141414.csv` is in same dir as `hunter.py` |
| Bot logs `SESSION_PAUSED` | Normal after consecutive losses or daily limit; will auto-resume |
| `Skip: vol_5m=$0` | Volume filter working correctly — token has no real activity |
| `Skip: K1 pump guard` | Token already pumped >12% in last 1m — chasing protection working |
| Swap fails on token | Token may still be MIGRATING (bonding curve); check stage |
| `SELL FAIL` repeated | Normal for illiquid tokens; auto-removes after 15 failures |
| Dashboard blank | `curl http://localhost:3250/api/state` to verify; check port |
| Login expired | Re-run `onchainos wallet login <email>` |
| Position stuck at TP1 | Floor position by design; will clean if hits -30% or 4h+loss |

---

## Performance & Efficiency

V7 is designed for token efficiency and minimal API overhead:

- **Hot tokens cache**: 60s TTL prevents redundant `hot-tokens` calls
- **Smart wallet random sampling**: 10 of 113 Tier-1 wallets per cycle (not all 113)
- **Risk check semaphore**: max 3 concurrent post-trade checks
- **Tier S dedup**: same wallet+token pair skipped for 2 hours
- **Atomic file writes**: prevent partial writes from causing reload errors
- **Background risk flags**: don't block monitor cycle

Average API calls per cycle: ~8 (Tier S sampling adds ~10 wallet history calls per 45s).

---

## Full Disclaimer

**This strategy script, parameter configuration, and all related documentation are for educational research and technical reference only, and do not constitute any form of investment advice, trading guidance, or financial recommendation.**

1. **Extreme Risk Warning**: SOL Meme Hunter targets small-cap meme tokens on Solana, the highest-risk trading category in cryptocurrency. Tokens may go to zero within minutes (Rug Pull, Dev Dump, liquidity drain). You may lose your entire capital.
2. **Parameters for Reference Only**: All defaults are based on general scenarios and **are not guaranteed for any specific market environment**. Markets change rapidly; yesterday's winners can be today's losers.
3. **Smart Wallet Database Caveats**: The 816 addresses are curated based on historical performance. Past success does NOT guarantee future success. Smart wallets can lose money. Use as one signal among many, not gospel truth.
4. **No Profit Guarantee**: Past performance does not predict future results. Even tokens passing all safety checks can fail due to sudden market changes, contract bugs, or unforeseen events.
5. **Trading Costs**: Cumulative fees, slippage, and Solana priority gas can significantly erode profits. Evaluate total costs.
6. **Technical Risks**: On-chain transactions are irreversible. RPC latency, network congestion, API rate limits can cause failures or price deviations.
7. **Third-Party Dependency**: Depends on onchainOS CLI, OKX infrastructure, and Solana network availability. Their stability is beyond the author's control.
8. **Regulatory/Legal Risks**: Cryptocurrency trading may face restrictions in your jurisdiction. Ensure compliance with applicable laws.
9. **AS-IS, No Warranty**: This software is provided without warranties. All trading decisions and outcomes are the user's sole responsibility.

---

## Changelog

| Version | Date | Highlights |
|---------|------|------------|
| **7.0** | 2025-05-14 | 4-Tier (S/A/B/D), proprietary 816-address smart wallet DB, 9-layer exit, cover-cost-first TP, volume confirmation, no forced shutdown, floor cleanup, sell fail removal |
| 6.0 | 2025-05-12 | 3-Tier (A/B/D), 7-layer exit, dynamic Tier-D scoring, session risk |

---

## Glossary

| Term | Definition |
|------|------------|
| **Tier S / Smart Wallet Follow** | V7 exclusive: scans 816 curated wallets for fresh buys |
| **Tier A / Smart Money Signal** | onchainOS-detected wallet co-buying patterns |
| **Tier B / Graduation Ambush** | Buy tokens just after PumpFun→Raydium migration |
| **Tier D / Hot Momentum** | Composite-scored trending tokens with smart wallet boost |
| **MIGRATED / MIGRATING** | Token graduation status; only MIGRATED can be swapped |
| **TEE** | Trusted Execution Environment; secure enclave for key signing |
| **Agentic Wallet** | onchainOS managed wallet with TEE signing |
| **Cover-cost-first** | TP1=+100% sell 50% recovers full cost |
| **Floor position** | The 10% remainder after all TPs; cleaned if loss >-30% |
| **Volume confirmation** | 5min vol ≥$8K + buy/sell ≥1.2 entry gate |
| **Smart Wallet Tier 1/2/3** | 3-tier quality classification of curated wallets |
| **Role multiplier** | Boost weight by wallet's role (early-buyer, pnl-leader, etc) |
| **9-Layer Exit** | Priority-ordered exit triggers (HE1 → ... → TP3) |
| **HE1 Emergency** | -50% loss = sell everything, override floor |
| **FAST_DUMP** | -20% from peak in 60s = flash crash exit |
| **K1 pump guard** | Skip if 1m candle pumped >12% (chasing protection) |
| **Time-decay SL** | Stop-loss tightens as position ages |
| **Trailing stop** | After TP1, exit on 20% drop from new peak |
| **Acted file** | Permanent record of traded tokens; never re-buy |
| **3-check protection** | 3 consecutive zero balances before considering position dead |
| **Atomic write** | Write tmp file + os.replace() to prevent corruption |
| **Pos_lock** | Threading lock for position state mutations |
| **Session pause** | V7 replaces hard stop with timed pause |
| **Composite score** | Tier D 0-100+ scoring including SW boost |
| **Native SOL** | `11111111111111111111111111111111` (32 ones) |
| **WSOL** | Wrapped SOL `So11...112`; cannot be swap source |
| **Slippage** | Price deviation between expected and executed; high for small caps |
| **Bundler** | Wallet that buys via bundled TX at launch — possible insider |
| **Dev** | Token deployer; their behavior is key risk indicator |
| **CTO** | Community Take Over — community continues after dev exits |

---

**SOL Meme Hunter v7.0 — Built for traders who want capital protection AND meme upside.**
