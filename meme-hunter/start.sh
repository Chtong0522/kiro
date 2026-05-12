#!/bin/bash
# SOL Meme Hunter v6.0 - Start Script
# Uses screen for background execution
set -e

export PATH="$HOME/.local/bin:/usr/local/bin:$PATH"

SESSION="meme-hunter"
SCRIPT="$HOME/meme-hunter/hunter.py"
LOG="/tmp/meme_hunter_v6.log"

echo "SOL Meme Hunter v6.0 - Starting..."

# 1. Check onchainos wallet status
echo "Checking wallet status..."
WALLET_STATUS=$(onchainos wallet status 2>/dev/null || echo '{}')
LOGGED_IN=$(echo "$WALLET_STATUS" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    data = d.get('data', d)
    if data.get('loggedIn'):
        print('yes')
        email = data.get('email', 'unknown')
        print(email, file=sys.stderr)
    else:
        print('no')
except:
    print('no')
" 2>/dev/null)

if [ "$LOGGED_IN" != "yes" ]; then
    echo "ERROR: Wallet not logged in!"
    echo "  Run: onchainos wallet login <your-email>"
    exit 1
fi
echo "  Wallet: logged in"

# 2. Kill existing meme-hunter screen if running
if screen -list 2>/dev/null | grep -q "$SESSION"; then
    echo "  Stopping existing session..."
    screen -X -S "$SESSION" quit 2>/dev/null
    sleep 2
fi

# 3. Start hunter.py in new screen session
echo "  Launching bot in screen session '$SESSION'..."
screen -dmS "$SESSION" python3 "$SCRIPT"

# 4. Wait and show tail of log
sleep 5
echo ""
if [ -f "$LOG" ]; then
    echo "=== Recent log output ==="
    tail -20 "$LOG"
    echo ""
fi

# 5. Print useful commands
if screen -list 2>/dev/null | grep -q "$SESSION"; then
    echo "================================================"
    echo "  Bot is running in background!"
    echo ""
    echo "  Useful commands:"
    echo "    View live log:    tail -f $LOG"
    echo "    Attach screen:    screen -r $SESSION"
    echo "    Detach screen:    Ctrl+A then D"
    echo "    Stop bot:         screen -X -S $SESSION quit"
    echo "    Dashboard:        http://localhost:3250"
    echo "================================================"
else
    echo "ERROR: Bot failed to start. Run manually to see errors:"
    echo "  python3 $SCRIPT"
    exit 1
fi
