#!/bin/bash
# ══════════════════════════════════════════════════════════════════════════════
# SOL Meme Hunter v8.0 — Watchdog Auto-Restart
#
# Features:
#   - Checks bot health every 30 seconds
#   - Auto-restarts on crash/disconnect
#   - Pulls latest code from git before restart
#   - Health logging every 10 minutes
#   - Max restart limit with 24h reset (prevents infinite crash loops)
#   - Cooldown between restarts
#
# Usage:
#   screen -dmS watchdog bash ~/meme-hunter/watchdog.sh
#
# Monitor:
#   tail -f /tmp/watchdog.log
#
# Stop:
#   screen -X -S watchdog quit
#
# One-liner (start watchdog + bot):
#   screen -dmS watchdog bash ~/meme-hunter/watchdog.sh && echo "OK"
# ══════════════════════════════════════════════════════════════════════════════

# ── Configuration ─────────────────────────────────────────────────────────────
BOT_SESSION="meme-hunter"
HUNTER_SCRIPT="$HOME/meme-hunter/hunter.py"
KIRO_DIR="$HOME/kiro"
MEME_DIR="$HOME/meme-hunter"
LOG="/tmp/watchdog.log"
BOT_LOG="/tmp/meme_hunter_v8.log"
CHECK_INTERVAL=30       # Check every 30s
MAX_RESTARTS=20         # Max restarts per 24h window
RESTART_COOLDOWN=60     # Wait 60s between restarts
HEALTH_LOG_INTERVAL=600 # Log health every 10min

# ── Functions ─────────────────────────────────────────────────────────────────
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG"
}

is_running() {
    screen -list 2>/dev/null | grep -q "$BOT_SESSION"
}

pull_latest() {
    if [ -d "$KIRO_DIR/.git" ]; then
        log "  Pulling latest code..."
        if (cd "$KIRO_DIR" && git pull -q 2>/dev/null); then
            # Copy updated files
            for f in hunter.py config.py risk_check.py dashboard.html; do
                [ -f "$KIRO_DIR/meme-hunter/$f" ] && cp "$KIRO_DIR/meme-hunter/$f" "$MEME_DIR/"
            done
            log "  Code updated"
        else
            log "  Git pull failed, using existing code"
        fi
    fi
}

restart_bot() {
    log "=== RESTART #$restart_count ==="

    # Stop old session
    screen -X -S "$BOT_SESSION" quit 2>/dev/null
    sleep 2

    # Pull latest
    pull_latest

    # Start new session
    screen -dmS "$BOT_SESSION" python3 "$HUNTER_SCRIPT"
    sleep 3

    if is_running; then
        log "  Restart successful"
        return 0
    else
        log "  ERROR: Restart failed!"
        return 1
    fi
}

# ── Main Loop ─────────────────────────────────────────────────────────────────
log "════════════════════════════════════════════════"
log "  Watchdog v8.0 started"
log "  Bot: $HUNTER_SCRIPT"
log "  Check: every ${CHECK_INTERVAL}s"
log "  Max restarts: $MAX_RESTARTS/24h"
log "════════════════════════════════════════════════"

restart_count=0
last_restart_ts=0
last_health_ts=0

while true; do
    sleep "$CHECK_INTERVAL"
    now=$(date '+%s')

    if is_running; then
        # Bot alive — log health periodically
        if [ $((now - last_health_ts)) -ge $HEALTH_LOG_INTERVAL ]; then
            last_health_ts=$now
            last_line=$(grep "SOL:" "$BOT_LOG" 2>/dev/null | tail -1)
            log "  ALIVE | $last_line"
        fi
        continue
    fi

    # Bot is DOWN
    log "  ALERT: Bot not running!"

    # Check restart limit
    if [ "$restart_count" -ge "$MAX_RESTARTS" ]; then
        hours_since=$(( (now - last_restart_ts) / 3600 ))
        if [ "$hours_since" -ge 24 ]; then
            log "  Reset restart counter (24h elapsed)"
            restart_count=0
        else
            log "  Max restarts reached. Waiting for 24h reset."
            sleep 300
            continue
        fi
    fi

    # Cooldown
    secs_since=$((now - last_restart_ts))
    if [ "$secs_since" -lt "$RESTART_COOLDOWN" ] && [ "$last_restart_ts" -gt 0 ]; then
        wait=$((RESTART_COOLDOWN - secs_since))
        log "  Cooldown: ${wait}s..."
        sleep "$wait"
    fi

    # Restart
    restart_count=$((restart_count + 1))
    last_restart_ts=$(date '+%s')

    if restart_bot; then
        sleep "$RESTART_COOLDOWN"
    fi
done
