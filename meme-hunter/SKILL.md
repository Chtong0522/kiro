---
name: sol-meme-hunter-v6
description: >
  SOL Meme Hunter v6.0 - Agentic Wallet TEE signing automated Solana meme token
  trading bot. 3-Tier architecture (Smart Money Signal + Graduation Ambush + Hot Momentum),
  7-Layer exit system, dynamic position scoring, session risk control, atomic persistence.
  onchainos CLI driven (no API Key needed), stdlib-only Python 3, single-file bot.
  Triggers when the user mentions meme hunter, SOL meme bot, meme trading bot,
  solana meme scanner, smart money copy trade, graduation ambush, hot momentum,
  auto trade meme coins, meme coin sniper, pump.fun hunter, Meme 猎手, 自动交易,
  聪明钱跟单, 毕业伏击, 热门动量, Meme 狙击, SOL Meme 自动, 链上交易机器人,
  or wants to automatically detect and trade Solana meme tokens using onchainos.

version: 6.0
updated: 2026-05-12
---

# SOL Meme Hunter v6.0

> This strategy is a real trading bot. Make sure you understand the risks before use. It is recommended to start with small position sizes and monitor closely.

---

## Disclaimer

**This strategy script, parameter configuration, and all related documentation are for educational research and technical reference only, and do not constitute any form of investment advice, trading guidance, or financial recommendation.**

1. **Extreme Risk Warning**: SOL Meme Hunter targets small-cap meme tokens on Solana, which represent **the highest-risk trading type** in cryptocurrency. Tokens may go to zero within minutes (Rug Pull, Dev Dump, liquidity drain). You may lose your entire invested capital.
2. **Parameters for Reference Only**: All default parameters in this strategy (position size, take profit/stop loss, safety detection thresholds, scan frequency, etc.) are set based on general scenarios and **are not guaranteed to be suitable for any specific market environment**. Market conditions change rapidly; parameters that worked yesterday may fail today.
3. **User Customization**: Users are encouraged to deeply understand the meaning of each parameter and modify them according to their own risk tolerance. Every parameter in `config.py` is annotated with bilingual comments for easy customization.
4. **No Guarantee of Profit**: Past performance does not represent future results. Even tokens that pass all safety checks may still cause losses due to sudden market changes, contract vulnerabilities, or unforeseen events.
5. **Trading Costs**: Accumulated fees, slippage, and gas costs from automated trading may significantly erode profits. Please fully evaluate total trading costs including Solana priority fees.
6. **Technical Risks**: On-chain transactions are irreversible. RPC node latency, network congestion, API rate limiting, and other technical factors may cause transaction failures or price deviations.
7. **Third-Party Dependency Risks**: This strategy depends on onchainos CLI, OKX infrastructure, and the Solana network. Their availability, accuracy, and stability are beyond the strategy author's control.
8. **Regulatory/Legal Risks**: Cryptocurrency trading may be subject to strict restrictions or prohibition in some jurisdictions. Users should ensure compliance with all applicable laws and regulations.
9. **Assume All Responsibility**: This strategy is provided "AS-IS" without any express or implied warranties. All trading decisions and consequences are the sole responsibility of the user.

---

## File Structure

```
meme-hunter/
├── SKILL.md          <- This file (strategy documentation)
├── config.py         <- All adjustable parameters (modify parameters here only)
├── risk_check.py     <- Pre/post trade risk assessment module
├── hunter.py         <- Strategy main program (single-file bot)
├── dashboard.html    <- Web Dashboard UI
├── setup.sh          <- One-command server setup script
└── start.sh          <- Bot startup script (screen-based)
```

---

## Prerequisites

### 1. Install onchainos CLI (>= 2.1.0)

```bash
# Check if already installed
onchainos --version

# If not installed, run setup.sh or follow onchainos official documentation
# Ensure onchainos is in PATH or located at ~/.local/bin/onchainos
```

### 2. Log in to Agentic Wallet (TEE Signing)

```bash
# One-time login (email verification)
onchainos wallet login <your-email>

# Verify login status
onchainos wallet status
# -> loggedIn: true

# Confirm Solana address
onchainos wallet addresses --chain 501
```

> Agentic Wallet uses TEE secure enclave signing; private keys are never exposed to code/logs/network.

### 3. No pip install needed

This strategy only depends on Python 3 standard library + onchainos CLI, no third-party packages required.

---

## Quick Start

```bash
# 1. Run setup (installs system deps + onchainos + copies files)
chmod +x setup.sh && sudo ./setup.sh

# 2. Login to wallet (one-time)
onchainos wallet login <your-email>

# 3. Start the bot
chmod +x ~/meme-hunter/start.sh
~/meme-hunter/start.sh

# 4. View Dashboard
open http://localhost:3250

# 5. Monitor logs
tail -f /tmp/meme_hunter_v6.log

# 6. Stop
screen -X -S meme-hunter quit
```

---

## Parameter Adjustment

**All adjustable parameters are in `config.py`**, no need to modify `hunter.py` or `risk_check.py`.

### Common Adjustments

| Need | Modify in `config.py` |
|---|---|
| Pause/resume trading | `PAUSED = True/False` |
| Switch to paper trading | `PAPER_TRADE = True` |
| Tier A position size | `TIER_A_SIZE_DAY = 8` / `TIER_A_SIZE_NIGHT = 5` |
| Tier B position size | `TIER_B_SIZE_DAY = 5` / `TIER_B_SIZE_NIGHT = 3` |
| Tier D base position | `TIER_D_SIZE_BASE = 5` |
| Max concurrent positions | `MAX_POSITIONS = 6` |
| Daily loss limit | `DAILY_LOSS_LIMIT = 15` (dollars) |
| Tier A take profit | `TP_RULES["A"]["tp1_pct"] = 0.15` |
| Tier D stop loss | `SL_RULES["D"]["sl_pct"] = -0.10` |
| SM scan interval | `SM_REFRESH_SEC = 30` (seconds) |
| Graduation scan interval | `GRADUATED_REFRESH_SEC = 60` (seconds) |
| Hot tokens scan interval | `HOT_REFRESH_SEC = 60` (seconds) |
| Dashboard port | `DASHBOARD_PORT = 3250` |
| Night mode hours (UTC) | `NIGHT_START_UTC = 14` / `NIGHT_END_UTC = 22` |

Restart bot for changes to take effect.

---

## Strategy Architecture

```
hunter.py (Single-file Bot)
├── scanner_loop()     <- background thread
│   ├── Tier A: Smart Money Signal (30s)
│   │   └── onchainos signal list -> deep verify -> buy
│   ├── Tier B: Graduation Ambush (60s)
│   │   └── memepump tokens MIGRATED -> filter -> buy
│   └── Tier D: Hot Momentum (60s)
│       └── hot-tokens ranking -> composite score -> buy
├── monitor_loop()     <- background thread (1s)
│   ├── 7-Layer Exit System
│   │   ├── HE1: -50% emergency
│   │   ├── FAST_DUMP: -15% in 10s
│   │   ├── SL: hard stop loss (per-tier)
│   │   ├── Time decay: tighten SL over time
│   │   ├── Timeout: max hold exceeded
│   │   ├── Trailing: drawdown after TP1
│   │   └── TP1/TP2: take profit levels
│   └── post_trade_flags() (60s per position)
│       └── balance check + 3-check protection
├── Dashboard (port 3250)
│   └── HTTP server serving dashboard.html + /api/state
└── Persistence (atomic JSON)
    ├── positions.json  (thread-safe, tmp + os.replace)
    ├── trades.json     (trade history)
    ├── acted.json      (never buy same token twice)
    └── session.json    (risk control state)
```

---

## Strategy Tiers

| Tier | Source | Conditions | Position Size |
|------|--------|-----------|---------------|
| **A: Smart Money** | `onchainos signal list` | >= 2 wallets co-buying, MC $200K-$2M, liq >= $80K, holders >= 300, dev rug = 0, bundler ATH <= 25% | $8 day / $5 night |
| **B: Graduation** | `memepump tokens --stage MIGRATED` | Recently graduated (<30min), MC $50K-$500K, holders >= 100, dev sold, insiders <= 15% | $5 day / $3 night |
| **D: Hot Momentum** | `hot-tokens --ranking-type 4` | Score >= 45, holders >= 500, MC $100K-$10M, liq >= $30K, risk level = 1, net inflow > 0, change > 5% | $5-$8 (dynamic by score) |

### Tier D Dynamic Sizing

| Score Range | Extra | Total Position |
|-------------|-------|---------------|
| 75+ | +$3 | $8 |
| 60-74 | +$1 | $6 |
| 45-59 | +$0 | $5 |

---

## Safety Detection

### Pre-Trade Checks (risk_check.py)

| Check | Tier A | Tier B | Tier D |
|-------|--------|--------|--------|
| Market cap range | $200K-$2M | $50K-$500K | $100K-$10M |
| Min liquidity | $80K | - | $30K |
| Min holders | 300 | 100 | 500 |
| Dev rug count | = 0 | - | - |
| Bundler ATH | <= 25% | - | - |
| LP burn | >= 80% | - | - |
| Top10 holdings | <= 50% | <= 40% | <= 35% |
| Insiders | - | <= 15% | - |
| Dev sold | - | Required | - |
| Risk level | - | - | = 1 |
| K1 pump guard | > 15% skip | - | - |

### Deep Verification (Tier A)

Additional checks run via onchainos CLI before Tier A entry:
- `memepump token-dev-info`: dev rug history, dev holdings
- `memepump token-bundle-info`: bundler ATH percentage, bundler count
- `memepump aped-wallet`: whale count rushing in
- Token LP burn status via token details

---

## 7-Layer Exit System

| Priority | Type | Trigger | Sell Ratio |
|----------|------|---------|------------|
| 1 | **HE1** Emergency | PnL <= -50% | 100% |
| 2 | **FAST_DUMP** Flash crash | -15% drop within 10 seconds | 100% |
| 3 | **SL** Hard stop loss | A: -15%, B: -15%, D: -10% | 100% |
| 4 | **Time Decay** | A: tighten to -8% at 30min, -5% at 60min | 100% |
| 5 | **Timeout** Max hold | A: 48h, B: 2h, D: 6h | 100% |
| 6 | **Trailing** After TP1 | A: 12% drawdown, B: 10%, D: 8% | 100% |
| 7 | **TP1/TP2** Take profit | A: +15%/+30%, B: +20%/+40%, D: +15%/+30% | TP1: 60%, TP2: 50-100% |

> Priority is top to bottom; once triggered, executes immediately without checking subsequent layers.

---

## Session Risk Control

| Rule | Value | Effect |
|------|-------|--------|
| Consecutive loss pause | 3 losses | Pause 600s (10 min) |
| Daily loss limit | $15 | Stop all trading for the day |
| Max concurrent positions | 6 | No new entries until a slot opens |
| Startup cooldown | 180s | Scan but no trade on first 3 min |
| Night mode | UTC 14:00-22:00 | Reduce position sizes |
| Liquidity emergency | < $5K | Immediate exit |

---

## Iron Rules (Must Not Be Violated)

1. **NEVER use `swap execute`**. Always use `swap swap` to build the transaction, then `wallet contract-call` to sign and broadcast via TEE, then `wallet history` to confirm. This is the only safe swap flow.
2. **NEVER delete a position based on a single balance check.** Must have `zero_balance_count >= 3` (3-check protection). Solana RPC has significant latency; false zeros are common.
3. **NEVER call `save_positions()` outside of `pos_lock`.** All position mutations must be thread-safe.
4. **NEVER buy the same token twice.** The acted file is permanent and survives restarts.
5. **NEVER buy MIGRATING tokens.** Only MIGRATED tokens can be swapped. Bonding curve tokens fail with `swap swap`.
6. **Atomic file writes only.** Write to tmp file first, then `os.replace()` to final path. Never write directly to position/trade files.
7. **Fail-closed safety.** If any safety check API call fails or times out, treat the token as unsafe and skip.
8. **Cooldown after sell.** After selling a token, do not re-enter for the cooldown period.
9. **Gas reserve.** Always keep >= 0.05 SOL for gas; never use the full balance for swaps.

---

## onchainos CLI Command Reference

| # | Command | Purpose |
|---|---------|---------|
| 1 | `onchainos memepump tokens --chain solana --stage MIGRATED` | Discover graduated tokens (Tier B) |
| 2 | `onchainos memepump token-details --chain solana --address <addr>` | Token details (MC, holders, LP) |
| 3 | `onchainos memepump token-dev-info --chain solana --address <addr>` | Dev safety check (rug history) |
| 4 | `onchainos memepump token-bundle-info --chain solana --address <addr>` | Bundler analysis |
| 5 | `onchainos memepump aped-wallet --chain solana --address <addr>` | Whale rush detection |
| 6 | `onchainos token price-info --chain solana --address <addr>` | Real-time price |
| 7 | `onchainos market kline --chain solana --address <addr> --bar 1m` | K-line data |
| 8 | `onchainos token trades --chain solana --address <addr>` | Recent trades |
| 9 | `onchainos swap swap --chain solana --from <> --to <> --amount <> --slippage <> --wallet <>` | Build swap transaction |
| 10 | `onchainos wallet contract-call --chain 501 --to <> --unsigned-tx <>` | TEE sign + broadcast |
| 11 | `onchainos wallet history --tx-hash <> --chain-index 501` | Transaction confirmation |
| 12 | `onchainos wallet status` | Login status check |
| 13 | `onchainos wallet addresses --chain 501` | Get Solana address |
| 14 | `onchainos portfolio all-balances --address <> --chains solana` | All token balances |
| 15 | `onchainos portfolio token-balances --address <> --tokens 501:<mint>` | Single token balance |
| 16 | `onchainos signal list --chain solana` | Smart money signals (Tier A) |
| 17 | `onchainos hot-tokens --chain solana --ranking-type 4` | Hot tokens ranking (Tier D) |

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "FATAL: onchainos CLI not found" | Install onchainos and ensure it is on PATH (`~/.local/bin/onchainos`) |
| "FATAL: Agentic Wallet not logged in" | Run `onchainos wallet login <email>` |
| "FATAL: Unable to parse Solana address" | Check `onchainos wallet addresses --chain 501` output |
| Dashboard won't open | Check if port 3250 is in use: `lsof -i:3250` |
| Bot not trading (PAUSED) | Edit config.py `PAUSED = False` and restart |
| Swap fails on bonding curve token | Ensure Tier B uses `--stage MIGRATED` not `MIGRATING` |
| Transaction timeout | Position created as `unconfirmed=True`, bot will verify on next cycle |
| "Session paused" in logs | 3 consecutive losses triggered cooldown; wait 10 min or restart |
| "Daily loss limit reached" | $15 daily loss hit; bot stops for the day, resets at midnight UTC |
| Login expired | Re-run `onchainos wallet login <email>` |
| High slippage on sells | Normal for low-cap tokens; SLIPPAGE_SELL=50 in config.py handles this |
| Screen session not found | Run `screen -ls` to check; start with `~/meme-hunter/start.sh` |

---

## Glossary

| Term | Definition |
|------|------------|
| **Tier A / Smart Money** | Strategy tier that copies trades from wallets labeled as smart money, KOL, or whale by onchainos signal detection |
| **Tier B / Graduation** | Strategy tier that buys tokens immediately after they graduate (migrate) from bonding curve to AMM DEX |
| **Tier D / Hot Momentum** | Strategy tier that buys trending tokens with high composite scores from the hot-tokens ranking |
| **MIGRATED** | Token stage indicating graduation from bonding curve to Raydium/Orca AMM; only these can be swapped |
| **MIGRATING** | Token still on bonding curve, in process of migration; cannot be swapped via onchainos swap |
| **TEE** | Trusted Execution Environment; onchainos signing is performed within a secure enclave |
| **Agentic Wallet** | onchainos managed wallet; private key stays inside TEE, never leaves the secure environment |
| **swap swap** | onchainos command that builds an unsigned swap transaction (does NOT execute); must be followed by contract-call |
| **contract-call** | onchainos command that signs and broadcasts a transaction via TEE |
| **3-check protection** | Requires 3 consecutive zero-balance readings before deleting a position; prevents RPC false positives |
| **Atomic write** | Write to temporary file then os.replace() to target; prevents corruption from crashes mid-write |
| **Trailing stop** | After TP1 is hit, track the price peak; exit if price drops a set percentage from that peak |
| **Time decay** | Stop loss tightens as position ages; prevents holding losers too long |
| **Fail-closed** | When safety check API fails, treat as unsafe and do not buy |
| **Composite score** | Tier D scoring combining holders, volume, inflow, change, unique traders into 0-100 score |
| **Night mode** | UTC 14:00-22:00 (HKT 22:00-06:00); reduced position sizes during low-liquidity hours |
| **acted file** | Persistent record of all tokens ever traded; ensures never buying the same token twice |
| **pos_lock** | Threading lock protecting all position mutations; ensures thread safety |
| **HE1** | Highest-priority emergency exit at -50% loss |
| **FAST_DUMP** | Flash crash detection; -15% drop within 10 seconds triggers immediate exit |
| **Slippage** | Difference between expected and actual execution price; worse liquidity means higher slippage |
| **Native SOL** | SOL native token address `11111111111111111111111111111111` (32 ones); must use this for swap --from |
| **WSOL** | Wrapped SOL (So11...112); SPL Token form of SOL; cannot be used for swap --from |
| **MC / MCAP** | Market Cap; token total supply x current price |
| **LP** | Liquidity Pool; token pair on DEX; larger LP means lower slippage |
| **Rug Pull** | Developers suddenly withdraw liquidity or dump holdings, causing token price to crash to zero |
| **Bundler** | Addresses that buy large amounts via bundled transactions at token launch; may be insiders |
| **Dev** | Token developer/deployer; their holdings and historical behavior are key risk indicators |
