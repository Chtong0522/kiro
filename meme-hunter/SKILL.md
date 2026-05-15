---
name: sol-meme-hunter-v8
version: "8.0"
updated: "2025-05-15"
author: "Meme Hunter Team"
description: >
  Autonomous Solana meme token trading system powered by onchainOS.
  4-Tier signal architecture (Smart Wallet Follow / Smart Money / Graduation Ambush / Hot Momentum),
  proprietary 816-address Smart Wallet database with 3-tier quality scoring,
  9-Layer adaptive exit with cover-cost-first philosophy,
  user-configurable risk presets (conservative/balanced/aggressive),
  and TEE-secured wallet signing for safe 24/7 operation.

triggers:
  keywords:
    en:
      - meme hunter
      - SOL meme bot
      - meme trading bot
      - solana meme scanner
      - smart money copy trade
      - smart wallet follow
      - copy trading bot
      - graduation ambush
      - pumpfun graduate sniper
      - hot momentum trader
      - alpha bot
      - auto trade meme coins
      - meme coin sniper
      - pump.fun hunter
      - solana alpha
      - degen bot
      - meme coin strategy
      - on-chain trading bot
      - agentic wallet trading
      - cover cost strategy
      - double-and-out
      - take-profit ladder
      - trailing stop bot
      - onchain meme strategy
      - solana copy trader
      - smart wallet signal
    zh:
      - Meme 猎手
      - 自动交易
      - 聪明钱跟单
      - 跟单机器人
      - 毕业伏击
      - 热门动量
      - Meme 狙击
      - SOL Meme 自动
      - 链上交易机器人
      - 翻倍出本
      - 聪明钱包数据库
      - 夜间自动运行
      - 安全过夜
      - 9层退出
      - 智能止盈止损
      - agentic wallet
      - TEE 签名
      - 链上 alpha
      - pump.fun 自动
      - 毕业代币
      - Meme 币策略
      - 链上狙击手
      - 聪明钱信号
  intent_patterns:
    - "automatically detect and trade Solana meme tokens"
    - "copy smart wallets on Solana"
    - "snipe newly graduated pump.fun tokens"
    - "run an overnight meme trading bot"
    - "set up autonomous meme coin trading"
    - "configure risk parameters for meme trading"
    - "自动检测并交易 Solana meme 代币"
    - "跟踪聪明钱包的交易"
    - "狙击 pump.fun 毕业代币"
    - "设置过夜自动交易机器人"
  do_not_trigger:
    - stocks or traditional forex trading
    - NFT minting or trading
    - generic crypto news queries
    - ETH/BTC swing trading strategies
    - non-Solana chain operations
    - wallet balance inquiries without trading intent
    - general DeFi yield farming

prerequisites:
  - "onchainOS CLI >= 2.1.0 (installed via setup.sh)"
  - "Python 3.10+ (stdlib only, zero pip dependencies)"
  - "Agentic Wallet logged in: onchainos wallet login <email>"
  - "Smart Wallet CSV database in working directory"

output_format: "structured_log"
---

# SOL Meme Hunter v8.0

> **Core Philosophy: 翻倍出本，利润奔跑** — When price doubles (+100%), sell 50% to recover full cost. Remaining position rides risk-free with trailing stops to capture 3-10x meme moves.

---

## 1. Overview

SOL Meme Hunter is a single-file Python bot that autonomously detects, evaluates, enters, and exits Solana meme tokens using **onchainOS CLI as the sole data source and execution engine**. No API keys, no external services, no pip dependencies.

### What Makes v8 Different

| Feature | Description |
|---------|-------------|
| **User Presets** | 3 risk profiles (conservative/balanced/aggressive) — configure once, trade safely |
| **4-Tier Signals** | S (Smart Wallet Follow) → A (Smart Money) → B (Graduation) → D (Hot Momentum) |
| **816-Address DB** | Proprietary smart wallet database with 3-tier quality + role-weighted scoring |
| **9-Layer Exit** | Priority-ordered exits from emergency to take-profit, all strictly enforced |
| **Volume Gate** | 5-min volume + buy/sell ratio confirmation prevents dead-market entries |
| **Safe Overnight** | Daily loss → 30-min pause (not stop). TP/SL keep executing during pause |
| **Zero Dependencies** | Python 3 stdlib + onchainOS CLI. No pip install, no API keys |

---

## 2. File Structure

```
meme-hunter/
├── SKILL.md              ← This file (strategy docs + skill metadata)
├── config.py             ← User-configurable parameters + risk presets
├── hunter.py             ← Main bot (single-file, all logic)
├── risk_check.py         ← Pre/post trade risk assessment module
├── dashboard.html        ← Real-time web dashboard (port 3250)
├── smart_wallets_*.csv   ← 816-address smart wallet database
├── setup.sh              ← One-command server setup
├── start.sh              ← Bot launcher (screen-based)
└── watchdog.sh           ← Auto-restart watchdog
```

---

## 3. Quick Start

```bash
# Step 1: Server setup (Ubuntu 20.04+)
chmod +x setup.sh && sudo ./setup.sh

# Step 2: Wallet login (one-time)
onchainos wallet login <your-email>
onchainos wallet status  # verify: loggedIn=true

# Step 3: Choose risk preset (edit config.py)
# Options: "conservative", "balanced", "aggressive"
# Default: "balanced"

# Step 4: Start bot
~/meme-hunter/start.sh

# Step 5: Monitor
open http://localhost:3250       # Dashboard
tail -f /tmp/meme_hunter_v8.log # Live log

# Stop: screen -X -S meme-hunter quit
```

---

## 4. User-Configurable Risk Presets

Every user can select a preset in `config.py` that controls all key parameters:

| Parameter | Conservative | Balanced | Aggressive |
|-----------|-------------|----------|------------|
| Position size (day) | $3-5 | $5-8 | $8-15 |
| Position size (night) | $2-3 | $3-5 | $5-8 |
| Max positions | 4 | 6 | 10 |
| Daily loss limit | $10 | $20 | $40 |
| TP1 trigger | +150% | +100% | +80% |
| SL1 trigger | -15% | -20% | -25% |
| Score threshold (Tier D) | 65 | 55 | 45 |
| Volume min (5m) | $12K | $8K | $5K |
| MC range | $200K-$2M | $100K-$5M | $50K-$10M |

Users can also override individual parameters after selecting a preset. See `config.py` for full documentation.

---

## 5. Signal Architecture

### 5.1 Tier S: Smart Wallet Follow (Highest Confidence)

**Why**: When historically top-performing wallets buy a new token, it's the strongest leading indicator available.

**How it works**:
1. Every 45s, randomly sample 10 Tier-1 wallets from our 816-address database
2. Check each wallet's last 5 transactions via `onchainos wallet history`
3. If a wallet bought a token within 30 minutes → evaluate as candidate
4. Run filters (MC, liquidity, holders, top10) + volume confirmation + risk check
5. Enter on first qualifying candidate

**onchainOS commands used**:
```bash
onchainos wallet history --address <wallet> --chain-index 501 --limit 5
onchainos token price-info --chain solana --address <token>
onchainos token holders --chain solana --address <token> --limit 20
onchainos market candles --chain solana --address <token> --bar 1m
```

### 5.2 Tier A: Smart Money Signal

**Why**: Multiple smart wallets co-buying the same token is statistically significant.

**How it works**:
1. Query `onchainos signal list` for multi-wallet buy signals
2. STRONG (≥3 wallets): Direct entry after filters
3. NORMAL (=2 wallets): Requires hot-tokens confirmation (positive net inflow)

**onchainOS commands used**:
```bash
onchainos signal list --chain solana --wallet-type 1,2,3
onchainos token hot-tokens --chain solana --ranking-type 4
```

### 5.3 Tier B: Graduation Ambush

**Why**: Tokens graduating from PumpFun bonding curve to Raydium often pump violently in the first 60 minutes.

**How it works**:
1. Query `onchainos memepump tokens --stage MIGRATED`
2. Filter: only tokens graduated within 60 minutes
3. Critical: only **MIGRATED** (not MIGRATING) tokens can be swapped

**V8 Fast-TP**: If token rises +30% within 10 minutes → fire TP1 immediately.

**onchainOS commands used**:
```bash
onchainos memepump tokens --chain solana --stage MIGRATED
```

### 5.4 Tier D: Hot Momentum (Dynamic Sizing)

**Why**: Trending tokens with strong fundamentals + smart wallet presence offer momentum plays.

**Composite Score (0-100+)**:
- Holders: 0-30 points
- Buy/sell ratio: 0-25 points
- Unique traders: 0-15 points
- Price change: 0-15 points
- Net inflow: 0-15 points
- Smart Wallet boost: 0-50 points (from DB match)

**onchainOS commands used**:
```bash
onchainos token hot-tokens --chain solana --ranking-type 4 --limit 20
```

---

## 6. Smart Wallet Database

816 unique Solana addresses organized into quality tiers:

| Tier | Groups | Score Boost | Purpose |
|------|--------|-------------|---------|
| Tier 1 | 盈利Top, 暴富新人, 底部高倍数, 频繁高胜, 离场赢家, 低频重炮 | +30 | Direct follow signal (Tier S) + maximum scoring boost |
| Tier 2 | 中等盈利, 持仓Top, 沉睡OG, 微赚, 稳健均衡 | +20 | Scoring boost for entry confidence |
| Tier 3 | 中性, 早期建仓, 赌徒命中 | +10 | Light scoring boost |
| Negative | 亏损者, 稳输者 | -10 | Negative signal (reduce score) |

**Role Multipliers** (applied on top of tier boost):
- `early-buyer`: 1.5× (bought before the crowd)
- `pnl-leader`: 1.3× (highest PnL on the token)
- `current-holder`: 1.0× (still believes)
- `peak-seller`: 0.5× (sold near peak, weakened signal)

---

## 7. 9-Layer Adaptive Exit System

Exits are priority-ordered. Higher layers override lower ones. Emergencies override the floor.

| # | Layer | Trigger | Action | Overrides Floor? |
|---|-------|---------|--------|-----------------|
| 1 | HE1 Emergency | PnL ≤ -50% | Sell 100% | YES |
| 2 | FAST_DUMP | -20% from peak in 60s | Sell 100% | YES |
| 3 | LIQ_EMERGENCY | Liquidity < $5K | Sell 100% | YES |
| 4 | Tiered SL | SL1: -20% → 50%; SL2: -30% → 100% | Partial/Full | SL2 only |
| 5 | Time-decay SL | 30min: -15%; 60min: -10% | Sell 50% | No |
| 6 | Timeout | S/A: 48h, B: 6h, D: 12h | Sell 100% | YES |
| 7 | Floor Exit | Floor + loss>-30% OR age>4h+loss | Sell 100% | N/A |
| 8 | Trailing Stop | After TP1: 20% drop from peak | Sell 40% | No |
| 9 | Take Profit | TP1=+100%/50%, TP2=+300%/30%, TP3=+800%/30% | Partial | No |

### Cover-Cost-First Math

```
Entry: $1.00 (1 unit)
TP1 (+100%, price=$2): Sell 50% → recover $1 = FULL COST BACK
  Remaining 0.5 units = pure profit (house money)
TP2 (+300%, price=$4): Sell 30% → +$0.60 cash out
TP3 (+800%, price=$9): Sell 30% → +$1.80 bonus
  Remaining 0.1 units = free lottery ticket

Worst case after TP1: even if remaining goes to ZERO, you break even.
Best case: 0.1 units holds for 50x → +500% bonus on top.
```

---

## 8. Volume Confirmation Gate

Before every entry, three conditions must pass:

1. **5-min volume ≥ $8K** — confirms real trading activity
2. **Buy/sell ratio ≥ 1.2** — more buyers than sellers
3. **Volume not collapsing** — recent volume not declining rapidly

**Why**: A token may pass all other checks but if nobody's trading it, you've entered a dead market.

---

## 9. Risk Assessment (risk_check.py)

### Pre-Trade Grades

| Grade | Action | Triggered By |
|-------|--------|--------------|
| G4: BLOCK | Hard refuse | Honeypot, tax >50%, dev removing liquidity, risk level ≥4 |
| G3: WARN | Refuse | Serial rugger, LP <80% burned, snipers >15%, wash trading |
| G2: CAUTION | Allow (log) | Top10 >30%, bundles >5%, dev sold all, no smart money |
| G0: PASS | Clear | All checks passed |

### Post-Trade Monitoring (every 60s per position)

| Action | Triggered By |
|--------|--------------|
| EXIT_NOW | Dev removing liquidity, liquidity drain >30%, active dump >5 SOL/min |
| EXIT_NEXT_TP | Volume plunge, soft rug velocity, coordinated selling |
| REDUCE_POSITION | Sniper concentration spike |
| ALERT | Top10 drift (informational) |

---

## 10. Session Risk Control

| Rule | Behavior |
|------|----------|
| 4 consecutive losses | Pause 15 minutes |
| Daily loss ≥ $20 | Pause 30 minutes (NOT stop) |
| Max positions | 6 concurrent (configurable) |
| Sell fail ≥ 15 | Auto-remove zombie position |

**Critical**: Pause only affects NEW entries. Position monitor keeps running — TP/SL always execute.

---

## 11. onchainOS Commands Reference

All 15 commands used, zero API keys required:

| Command | Purpose |
|---------|---------|
| `signal list --chain solana --wallet-type 1,2,3` | Smart money signals |
| `memepump tokens --chain solana --stage MIGRATED` | Graduated tokens |
| `token hot-tokens --chain solana --ranking-type 4` | Hot momentum |
| `wallet history --address <> --chain-index 501` | Smart wallet trades |
| `token price-info --chain solana --address <>` | Price/MC/liquidity |
| `token holders --chain solana --address <>` | Top holders |
| `market candles --chain solana --address <> --bar 1m` | Volume/candles |
| `token trades --chain solana --address <>` | Buy/sell analysis |
| `token advanced-info --chain solana --address <>` | Risk data |
| `security token-scan --tokens 501:<>` | Honeypot detection |
| `swap swap --chain solana --from <> --to <> --amount <>` | Build TX |
| `wallet contract-call --chain 501 --to <> --unsigned-tx <>` | TEE sign |
| `wallet history --tx-hash <> --chain-index 501` | TX confirmation |
| `wallet balance --chain 501` | SOL balance |
| `portfolio token-balances --address <> --tokens 501:<>` | Token balance |

---

## 12. Swap Execution Flow (Iron Rule)

```
NEVER use `swap execute` — it would expose private keys.

Safe flow (always):
1. onchainos swap swap ... → builds unsigned TX
2. onchainos wallet contract-call ... → TEE signs + broadcasts
3. onchainos wallet history --tx-hash ... → confirms on-chain
```

---

## 13. Output Examples

### Log Output
```
[14:23:45] SOL: 0.4521 (~$67.81) | Daily PnL: $+2.13 | Positions: 2/6 | SW: 816 wallets
[14:24:15] Tier S smart wallet candidates: 2
[14:24:18]   Skip_S DOGEX: vol_5m=$3200<$8000
[14:24:22] ENTER TIER_S MOON $8 | MC=$425,000 | SmartWallet=FFcYgSSg
[14:24:25]   swap OK | TX: https://solscan.io/tx/4xK7nP9...
[14:31:22] SELL MOON [TP1(+100%)] 50% PnL=+102.3% (2.02x)
```

### Dashboard API Response (`/api/state`)
```json
{
  "stats": {"buys": 12, "sells": 18, "wins": 11, "losses": 7, "net_pnl": 23.45},
  "positions": {"9SLPTL...": {"symbol": "MOON", "tier": "S", "pnl_pct": 1.0, "remaining": 0.5}},
  "smart_wallets": {"total": 816, "tier1": 113},
  "session_risk": {"consecutive_losses": 0, "cumulative_loss_usd": 0, "paused_until": 0},
  "config": {"preset": "balanced", "paper_trade": false, "version": "8.0"}
}
```

---

## 14. Customization Guide

All parameters in `config.py`. No need to edit `hunter.py` or `risk_check.py`.

| Goal | How |
|------|-----|
| Change risk level | `PRESET = "conservative"` or `"aggressive"` |
| Paper trade first | `PAPER_TRADE = True` |
| Pause trading | `PAUSED = True` |
| Disable a tier | `TIER_S_ENABLED = False` |
| Adjust TP1 | `TP_RULES["A"]["tp1_pct"] = 0.80` |
| Wider stop | `SL_RULES["A"]["sl_pct"] = -0.25` |
| More positions | `MAX_POSITIONS = 10` |
| Lower volume bar | `VOLUME_5M_MIN_USD = 5000` |

---

## 15. Troubleshooting

| Problem | Solution |
|---------|----------|
| `FATAL: No wallet address` | `onchainos wallet login <email>` |
| `Smart Wallets: 0 loaded` | Ensure CSV file is in working directory |
| `SESSION_PAUSED` | Normal — auto-resumes after cooldown |
| `Skip: vol_5m=$0` | Volume filter working — token has no activity |
| Swap fails | Token may still be MIGRATING (bonding curve) |
| `SELL FAIL` repeated | Normal for illiquid tokens; auto-removes after 15 |
| Dashboard blank | `curl http://localhost:3250/api/state` to verify |

---

## 16. Iron Rules (Must Not Be Violated)

1. **NEVER** use `swap execute` — only `swap swap` → `contract-call` → `wallet history`
2. **NEVER** delete position on single zero-balance — requires `zero_count ≥ 30` + age > 24h
3. **NEVER** call `save_positions()` outside `pos_lock` — thread safety
4. **NEVER** buy same token twice — permanent `acted` record
5. **NEVER** buy MIGRATING tokens — only MIGRATED can be swapped
6. **Atomic writes only** — write to `.tmp` then `os.replace()`
7. **Fail-closed** — if safety check fails/times out → skip (never enter on missing data)
8. **TP/SL always execute** — even during session pause
9. **Floor positions cleaned** — loss > -30% or age > 4h with loss → exit

---

## 17. Disclaimer

**Educational research and technical reference only. Not investment advice.**

- Meme tokens carry extreme risk including total loss
- All parameters are reference defaults, not guarantees
- Smart wallet past performance ≠ future results
- On-chain transactions are irreversible
- Software provided AS-IS without warranties
- Users assume full responsibility for all trading decisions
- Ensure compliance with local regulations

---

## Changelog

| Version | Date | Highlights |
|---------|------|------------|
| **8.0** | 2025-05-15 | User-configurable presets, improved SKILL.md structure, token-efficient design, enhanced error handling, dashboard v2 |
| 7.0 | 2025-05-14 | 4-Tier (S/A/B/D), 816-address DB, 9-layer exit, cover-cost-first, volume gate |
| 6.0 | 2025-05-12 | 3-Tier (A/B/D), 7-layer exit, dynamic scoring |
