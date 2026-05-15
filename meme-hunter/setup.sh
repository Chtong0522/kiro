#!/bin/bash
# ══════════════════════════════════════════════════════════════════════════════
# SOL Meme Hunter v8.0 — One-Command Server Setup
# For Ubuntu 20.04/22.04 (AWS, Lightsail, VPS, Cloud)
#
# What this does:
#   1. Installs system packages (python3, screen, curl)
#   2. Installs Node.js 22 (required for onchainos CLI)
#   3. Installs onchainos CLI (latest release)
#   4. Copies bot files to ~/meme-hunter/
#   5. Sets permissions
#
# Usage:
#   chmod +x setup.sh && sudo ./setup.sh
# ══════════════════════════════════════════════════════════════════════════════
set -e

echo "════════════════════════════════════════════════════"
echo "  SOL Meme Hunter v8.0 — Server Setup"
echo "  4-Tier (S/A/B/D) + User-Configurable Presets"
echo "════════════════════════════════════════════════════"

# ── 1. System packages ────────────────────────────────────────────────────────
echo "[1/5] Installing system packages..."
apt-get update -qq
apt-get install -y curl wget git screen python3 -qq
echo "  Python: $(python3 --version 2>&1)"

# ── 2. Node.js 22 ────────────────────────────────────────────────────────────
echo "[2/5] Installing Node.js 22..."
if ! node --version 2>/dev/null | grep -q "v22"; then
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
    apt-get install -y nodejs -qq
fi
echo "  Node: $(node --version 2>&1) | npm: $(npm --version 2>&1)"

# ── 3. onchainos CLI ─────────────────────────────────────────────────────────
echo "[3/5] Installing onchainos CLI..."
if ! command -v onchainos &>/dev/null; then
    LATEST=$(curl -sSL "https://api.github.com/repos/okx/onchainos-skills/releases/latest" \
        | python3 -c "import sys,json; print(json.load(sys.stdin)['tag_name'])" 2>/dev/null || echo "latest")
    echo "  Version: $LATEST"
    curl -sSL "https://raw.githubusercontent.com/okx/onchainos-skills/${LATEST}/install.sh" | sh
    export PATH="$HOME/.local/bin:$PATH"
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
else
    echo "  onchainos already installed: $(onchainos --version 2>&1 | head -1)"
fi

# ── 4. Copy files ────────────────────────────────────────────────────────────
echo "[4/5] Copying v8 files to ~/meme-hunter/..."
mkdir -p ~/meme-hunter
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

for f in config.py risk_check.py hunter.py dashboard.html SKILL.md start.sh watchdog.sh; do
    if [ -f "$SCRIPT_DIR/$f" ]; then
        cp "$SCRIPT_DIR/$f" ~/meme-hunter/
    fi
done

# Copy smart wallet CSV (glob pattern for any version)
for csv in "$SCRIPT_DIR"/smart_wallets_*.csv; do
    [ -f "$csv" ] && cp "$csv" ~/meme-hunter/
done

echo "  Copied to ~/meme-hunter/"

# ── 5. Permissions ───────────────────────────────────────────────────────────
echo "[5/5] Setting permissions..."
chmod +x ~/meme-hunter/start.sh ~/meme-hunter/watchdog.sh 2>/dev/null || true

echo ""
echo "════════════════════════════════════════════════════"
echo "  Setup complete!"
echo ""
echo "  Next steps:"
echo "    1. onchainos wallet login <your-email>"
echo "    2. onchainos wallet status"
echo "    3. Edit ~/meme-hunter/config.py"
echo "       → Set PRESET = \"conservative\" | \"balanced\" | \"aggressive\""
echo "       → Set PAPER_TRADE = True for testing"
echo "    4. ~/meme-hunter/start.sh"
echo ""
echo "  Dashboard: http://localhost:3250"
echo "  Log:       /tmp/meme_hunter_v8.log"
echo "════════════════════════════════════════════════════"
