#!/bin/bash
# 启动 Meme Hunter（用 screen 保持后台运行）

export PATH="$HOME/.local/bin:/usr/local/bin:$PATH"

SESSION="meme-hunter"
SCRIPT="$HOME/meme-hunter/hunter.py"

# 检查是否已在运行
if screen -list | grep -q "$SESSION"; then
    echo "⚠️  已有 $SESSION 在运行"
    echo "查看日志: screen -r $SESSION"
    echo "停止: screen -X -S $SESSION quit"
    exit 1
fi

# 检查环境
echo "检查环境..."
onchainos wallet status | python3 -c "
import sys,json
d=json.load(sys.stdin)
data=d.get('data',{})
if data.get('loggedIn'):
    print(f'✅ 钱包已登录: {data.get(\"email\")}')
else:
    print('❌ 钱包未登录，请先运行: onchainos wallet login chuzi0522@gmail.com')
    sys.exit(1)
"

if [ $? -ne 0 ]; then
    exit 1
fi

# 用 screen 后台启动
echo "启动 Meme Hunter..."
screen -dmS "$SESSION" python3 "$SCRIPT"

sleep 2
if screen -list | grep -q "$SESSION"; then
    echo "✅ 已在后台启动 (screen session: $SESSION)"
    echo ""
    echo "常用命令:"
    echo "  查看实时日志:  screen -r $SESSION"
    echo "  退出日志查看:  Ctrl+A 然后按 D"
    echo "  查看日志文件:  tail -f /tmp/meme_hunter_v2.log"
    echo "  停止策略:      screen -X -S $SESSION quit"
else
    echo "❌ 启动失败，直接运行查看错误:"
    echo "   python3 $SCRIPT"
fi
