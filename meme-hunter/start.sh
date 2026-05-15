#!/bin/bash
# ══════════════════════════════════════════════════════════════════════════════
# SOL Meme Hunter v8.0 — Start Script
# Uses screen for background execution. Safe to run overnight.
#
# Usage:
#   ~/meme-hunter/start.sh
#
# Stop:
#   screen -X -S meme-hunter quit
# ══════════════════════════════════════════════════════════════════════════════
set -e

export PATH="$HOME/.local/bin:/usr/local/bin:$PATH"

SESSION="meme-hunter"
SCRIPT="$HOME/meme-hunter/hunter.py"
LOG="/tmp/meme_hunter_v8.log"

echo "════════════════════════════════════════════════════"
echo "  SOL Meme Hunter v8.0 — Starting"
echo "  Safe overnight: pause only, TP/SL always enforced"
echo "════════════════════════════════════════════════════"

# ── 1. Check wallet login ────────────────────────────────────────────────────
echo "[1/4] Checking wallet..."
LOGGED_IN=$(onchainos wallet status 2>/dev/null | python3 -c "
import sys,json
try:
    d=json.load(sys.stdin)
    data=d.get('data',d)
    print('yes' if data.get('loggedIn') else 'no')
except:
    print('no')
" 2>/dev/null || echo "no")

if [ "$LOGGED_IN" != "yes" ]; then
    echo "  ERROR: Wallet not logged in!"
    echo "  Run: onchainos wallet login <your-email>"
    exit 1
fi
echo "  Wallet: logged in"

# ── 2. Show preset ──────────────────────────────────────────────────────────
PRESET=$(python3 -c "
import sys; sys.path.insert(0,'$HOME/meme-hunter')
import config; print(config.PRESET)
" 2>/dev/null || echo "balanced")
echo "[2/4] Preset: $PRESET"

# ── 3. Kill existing session ────────────────────────────────────────────────
if screen -list 2>/dev/null | grep -q "$SESSION"; then
    echo "[3/4] Stopping existing session..."
    screen -X -S "$SESSION" quit 2>/dev/null
    sleep 2
else
    echo "[3/4] No existing session"
fi

# ── 4. Launch ────────────────────────────────────────────────────────────────
echo "[4/4] Launching bot..."
screen -dmS "$SESSION" python3 "$SCRIPT"
sleep 4

if screen -list 2>/dev/null | grep -q "$SESSION"; then
    echo ""
    if [ -f "$LOG" ]; then
        echo "=== Recent output ==="
        tail -15 "$LOG"
        echo ""
    fi
    echo "════════════════════════════════════════════════════"
    echo "  Bot is running! (preset: $PRESET)"
    echo ""
    echo "  Commands:"
    echo "    tail -f $LOG          # Live log"
    echo "    screen -r $SESSION    # Attach"
    echo "    screen -X -S $SESSION quit  # Stop"
    echo "    http://localhost:3250  # Dashboard"
    echo "════════════════════════════════════════════════════"
else
    echo "  ERROR: Bot failed to start. Run manually:"
    echo "  python3 $SCRIPT"
    exit 1
fi
