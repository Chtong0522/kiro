#!/bin/bash
# SOL Meme Hunter v7.0 - Watchdog Auto-Restart
# 
# 功能:
#   - 每30秒检查 meme-hunter screen 是否还在运行
#   - 如果挂了/断连/崩溃 → 自动重启
#   - 自动拉取最新代码
#   - 重启后记录日志
#
# 使用方法:
#   # 后台运行 watchdog (用独立 screen)
#   screen -dmS watchdog bash ~/meme-hunter/watchdog.sh
#
#   # 查看 watchdog 日志
#   tail -f /tmp/watchdog.log
#
#   # 停止 watchdog
#   screen -X -S watchdog quit
#
# 一键启动 watchdog + bot:
#   screen -dmS watchdog bash ~/meme-hunter/watchdog.sh && echo "Watchdog started"

# ── 配置 ────────────────────────────────────────────────────────────────────
BOT_SESSION="meme-hunter"
HUNTER_SCRIPT="$HOME/meme-hunter/hunter.py"
KIRO_DIR="$HOME/kiro"
MEME_DIR="$HOME/meme-hunter"
LOG_FILE="/tmp/watchdog.log"
BOT_LOG="/tmp/meme_hunter_v7.log"
CHECK_INTERVAL=30       # 每30秒检查一次
MAX_RESTARTS=20         # 24h内最大重启次数 (防止无限循环崩溃)
RESTART_COOLDOWN=60     # 重启后等待60秒再检查

# ── 辅助函数 ─────────────────────────────────────────────────────────────────
log() {
    local ts=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[$ts] $1" | tee -a "$LOG_FILE"
}

is_bot_running() {
    screen -list 2>/dev/null | grep -q "$BOT_SESSION"
}

restart_bot() {
    log "=== RESTARTING BOT (attempt #$restart_count) ==="

    # 1. 停掉旧 session (如果还在)
    screen -X -S "$BOT_SESSION" quit 2>/dev/null
    sleep 2

    # 2. 拉取最新代码
    if [ -d "$KIRO_DIR" ]; then
        log "  Pulling latest code from GitHub..."
        cd "$KIRO_DIR" && git pull -q 2>/dev/null && \
            cp meme-hunter/hunter.py "$MEME_DIR/" && \
            cp meme-hunter/config.py "$MEME_DIR/" && \
            cp meme-hunter/risk_check.py "$MEME_DIR/" && \
            log "  Code updated OK" || \
            log "  Git pull failed, using existing code"
    fi

    # 3. 启动新 session
    screen -dmS "$BOT_SESSION" python3 "$HUNTER_SCRIPT"
    sleep 3

    # 4. 验证是否启动成功
    if is_bot_running; then
        log "  Bot restarted successfully (session: $BOT_SESSION)"
        return 0
    else
        log "  ERROR: Bot failed to start!"
        return 1
    fi
}

# ── 主循环 ───────────────────────────────────────────────────────────────────
log "============================================"
log "  Watchdog started for SOL Meme Hunter v7.0"
log "  Check interval: ${CHECK_INTERVAL}s"
log "  Max restarts: $MAX_RESTARTS"
log "  Bot script: $HUNTER_SCRIPT"
log "============================================"

restart_count=0
last_restart_ts=0
consecutive_failures=0

while true; do
    sleep "$CHECK_INTERVAL"

    if is_bot_running; then
        # Bot is alive — 重置连续失败计数
        consecutive_failures=0

        # 每10分钟记录一次 alive 状态
        minute=$(date '+%M')
        if [ "$minute" = "00" ] || [ "$minute" = "10" ] || [ "$minute" = "20" ] || \
           [ "$minute" = "30" ] || [ "$minute" = "40" ] || [ "$minute" = "50" ]; then
            # 从日志提取最后的余额行
            last_balance=$(grep "SOL:" "$BOT_LOG" 2>/dev/null | tail -1)
            log "  ALIVE | $last_balance"
        fi
        continue
    fi

    # Bot is NOT running
    log "  ALERT: Bot is not running! (consecutive_failures=$consecutive_failures)"
    consecutive_failures=$((consecutive_failures + 1))

    # 检查重启次数限制
    if [ "$restart_count" -ge "$MAX_RESTARTS" ]; then
        # 重置计数器 (超过上限后每小时重置，允许继续重启)
        now_ts=$(date '+%s')
        hours_since=$((($now_ts - $last_restart_ts) / 3600))
        if [ "$hours_since" -ge 24 ]; then
            log "  Resetting restart counter after 24h"
            restart_count=0
        else
            log "  WARNING: Max restarts ($MAX_RESTARTS) reached. Waiting for 24h reset."
            sleep 300   # 等5分钟再检查
            continue
        fi
    fi

    # 等待冷却时间（避免启动失败后立即重试）
    now_ts=$(date '+%s')
    secs_since=$(($now_ts - $last_restart_ts))
    if [ "$secs_since" -lt "$RESTART_COOLDOWN" ] && [ "$last_restart_ts" -gt 0 ]; then
        wait_time=$(($RESTART_COOLDOWN - $secs_since))
        log "  Cooldown: waiting ${wait_time}s before restart..."
        sleep "$wait_time"
    fi

    # 重启
    restart_count=$((restart_count + 1))
    last_restart_ts=$(date '+%s')

    if restart_bot; then
        log "  Restart #$restart_count successful. Sleeping ${RESTART_COOLDOWN}s..."
        sleep "$RESTART_COOLDOWN"
    else
        log "  Restart #$restart_count FAILED. Will retry in ${CHECK_INTERVAL}s"
    fi
done
