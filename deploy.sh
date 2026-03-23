#!/usr/bin/env bash
set -euo pipefail

VPS="root@46.224.150.0"
REMOTE_DIR="/opt/solana-arb-bot"

echo "==> Syncing project to $VPS:$REMOTE_DIR ..."
rsync -avz --delete \
  --exclude '.env' \
  --exclude 'target/' \
  --exclude '__pycache__/' \
  --exclude '.git/' \
  --exclude '.venv/' \
  . "$VPS:$REMOTE_DIR/"

echo "==> Setting up on VPS ..."
ssh "$VPS" bash -s <<'REMOTE'
set -euo pipefail
cd /opt/solana-arb-bot

# Install Python dependencies
echo "--- Installing Python deps ---"
pip3 install -r detector/requirements.txt

# Build Rust executor if cargo is available
if command -v cargo &>/dev/null; then
  echo "--- Building Rust executor ---"
  cd executor && cargo build --release && cd ..
else
  echo "--- cargo not found, skipping Rust build ---"
fi

# Create log directory
mkdir -p /var/log/arb-bot

# Install systemd service
cp arb-bot.service /etc/systemd/system/arb-bot.service
systemctl daemon-reload
systemctl enable arb-bot
systemctl restart arb-bot

echo "--- Service status ---"
systemctl status arb-bot --no-pager || true
REMOTE

echo "==> Deploy complete."
