#!/bin/bash
# SOL Meme Hunter — 服务器一键部署脚本
# 适用于 Ubuntu 20.04/22.04 (阿里云/腾讯云/AWS)
set -e

echo "================================================"
echo "  SOL Meme Hunter — 环境安装"
echo "================================================"

# 1. 系统更新
apt-get update -qq && apt-get install -y curl wget git screen python3 python3-pip -qq

# 2. 安装 Node.js 22
curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
apt-get install -y nodejs -qq
echo "Node: $(node --version) | npm: $(npm --version)"

# 3. 安装 onchainos CLI
LATEST=$(curl -sSL "https://api.github.com/repos/okx/onchainos-skills/releases/latest" | python3 -c "import sys,json; print(json.load(sys.stdin)['tag_name'])")
echo "Installing onchainos $LATEST..."
curl -sSL "https://raw.githubusercontent.com/okx/onchainos-skills/${LATEST}/install.sh" | sh
export PATH="$HOME/.local/bin:$PATH"
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
onchainos --version

# 4. 安装 gmgn-cli
npm install -g gmgn-cli
echo "gmgn-cli: $(gmgn-cli --version 2>/dev/null || echo 'installed')"

# 5. 创建工作目录
mkdir -p ~/meme-hunter
cp hunter.py ~/meme-hunter/
cp start.sh ~/meme-hunter/
chmod +x ~/meme-hunter/start.sh

# 6. 配置 GMGN API Key
mkdir -p ~/.config/gmgn
cat > ~/.config/gmgn/.env << 'GMGN_EOF'
GMGN_API_KEY=gmgn_541393874646efdbfcf8f32b8d08af83
GMGN_EOF
chmod 600 ~/.config/gmgn/.env

echo ""
echo "================================================"
echo "  安装完成！"
echo "  下一步：运行 onchainos wallet login 登录钱包"
echo "  然后运行 ~/meme-hunter/start.sh 启动策略"
echo "================================================"
