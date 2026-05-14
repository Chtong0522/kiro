#!/bin/bash
# SOL Meme Hunter v7.0 - One-Command Server Setup
# For Ubuntu 20.04/22.04 (AWS/Lightsail/Cloud)
set -e

echo "================================================"
echo "  SOL Meme Hunter v7.0 - Server Setup"
echo "  4-Tier (S/A/B/D) + Smart Wallet Signal"
echo "================================================"

# 1. System packages
echo "[1/6] Installing system packages..."
apt-get update -qq
apt-get install -y curl wget git screen python3 -qq
echo "  Python: $(python3 --version)"

# 2. Install Node.js 22 (required for onchainos CLI)
echo "[2/6] Installing Node.js 22..."
if ! node --version 2>/dev/null | grep -q "v22"; then
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
    apt-get install -y nodejs -qq
fi
echo "  Node: $(node --version) | npm: $(npm --version)"

# 3. Install onchainos CLI (latest)
echo "[3/6] Installing onchainos CLI..."
if ! command -v onchainos &>/dev/null; then
    LATEST=$(curl -sSL "https://api.github.com/repos/okx/onchainos-skills/releases/latest" | python3 -c "import sys,json; print(json.load(sys.stdin)['tag_name'])")
    echo "  Version: $LATEST"
    curl -sSL "https://raw.githubusercontent.com/okx/onchainos-skills/${LATEST}/install.sh" | sh
    export PATH="$HOME/.local/bin:$PATH"
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
else
    echo "  onchainos already installed"
fi
onchainos --version

# 4. Create working directory
echo "[4/6] Creating ~/meme-hunter directory..."
mkdir -p ~/meme-hunter

# 5. Copy all v7 files
echo "[5/6] Copying v7 files..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cp "$SCRIPT_DIR/config.py" ~/meme-hunter/
cp "$SCRIPT_DIR/risk_check.py" ~/meme-hunter/
cp "$SCRIPT_DIR/hunter.py" ~/meme-hunter/
cp "$SCRIPT_DIR/dashboard.html" ~/meme-hunter/
cp "$SCRIPT_DIR/SKILL.md" ~/meme-hunter/
cp "$SCRIPT_DIR/start.sh" ~/meme-hunter/
cp "$SCRIPT_DIR/smart_wallets_page_all_all_202605141414.csv" ~/meme-hunter/
echo "  Copied: config.py risk_check.py hunter.py dashboard.html SKILL.md start.sh smart_wallets.csv"

# 6. Set permissions
echo "[6/6] Setting permissions..."
chmod +x ~/meme-hunter/start.sh

echo ""
echo "================================================"
echo "  Setup complete!"
echo ""
echo "  Next steps:"
echo "    1. onchainos wallet login <your-email>"
echo "    2. onchainos wallet status    (verify login)"
echo "    3. ~/meme-hunter/start.sh     (start the bot)"
echo ""
echo "  Dashboard: http://localhost:3250"
echo "  Log file:  /tmp/meme_hunter_v7.log"
echo "================================================"
