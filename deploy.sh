#!/usr/bin/env bash
set -euo pipefail

VPS="root@46.224.150.0"
REMOTE_DIR="/opt/solana-arb-bot"

echo "==> Syncing project to $VPS:$REMOTE_DIR ..."
rsync -avz --delete \
  --exclude '.env' \
  --exclude 'target/' \
  --exclude 'executor/target/' \
  --exclude '__pycache__/' \
  --exclude '.git/' \
  --exclude '.venv/' \
  --exclude '.hypothesis/' \
  --exclude '.pytest_cache/' \
  --exclude 'Cargo.lock' \
  . "$VPS:$REMOTE_DIR/"

echo "==> Setting up on VPS ..."
ssh "$VPS" bash -s <<'REMOTE'
set -euo pipefail
cd /opt/solana-arb-bot

# Install Python dependencies
echo "--- Installing Python deps ---"
pip3 install --break-system-packages --ignore-installed -r detector/requirements.txt
pip3 install --break-system-packages --ignore-installed -r dashboard/requirements.txt

# Build Rust executor if cargo is available
if command -v cargo &>/dev/null; then
  echo "--- Building Rust executor ---"
  cd executor && cargo build --release && cd ..
else
  echo "--- cargo not found, installing Rust ---"
  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
  source "$HOME/.cargo/env"
  cd executor && cargo build --release && cd ..
fi

# Create log directory
mkdir -p /var/log/arb-bot

# Install systemd services
echo "--- Installing systemd services ---"
cp arb-bot.service /etc/systemd/system/arb-bot.service
cp arb-dashboard.service /etc/systemd/system/arb-dashboard.service
systemctl daemon-reload

# Enable services
systemctl enable arb-bot
systemctl enable arb-dashboard

# Restart services
systemctl restart arb-bot
sleep 2
systemctl restart arb-dashboard

echo ""
echo "--- Bot service status ---"
systemctl status arb-bot --no-pager || true
echo ""
echo "--- Dashboard service status ---"
systemctl status arb-dashboard --no-pager || true
echo ""
echo "--- Checking health endpoint ---"
sleep 3
curl -s http://localhost:8080/health 2>/dev/null || echo "(health endpoint not ready yet)"
echo ""
REMOTE

echo "==> Deploy complete."
echo "    Bot:       systemctl status arb-bot"
echo "    Dashboard: http://46.224.150.0:3000 (admin/admin)"
echo "    Health:    http://46.224.150.0:8080/health"
echo "    Logs:      ssh $VPS 'tail -f /var/log/arb-bot/bot.log'"
