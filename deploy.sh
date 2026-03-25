#!/usr/bin/env bash
set -euo pipefail

VPS="${DEPLOY_VPS:-root@46.224.150.0}"
REMOTE_DIR="/opt/solana-arb-bot"
BOT_USER="arbbot"

echo "==> Syncing project to $VPS:$REMOTE_DIR ..."
rsync -avz --delete \
  --exclude '.env' \
  --exclude 'wallet.json' \
  --exclude 'target/' \
  --exclude 'executor/target/' \
  --exclude '__pycache__/' \
  --exclude '.git/' \
  --exclude '.venv/' \
  --exclude '.hypothesis/' \
  --exclude '.pytest_cache/' \
  --exclude 'Cargo.lock' \
  --exclude 'models/*.pkl' \
  --exclude 'docs/mobula-monorepo/' \
  --exclude '.coverage' \
  . "$VPS:$REMOTE_DIR/"

echo "==> Setting up on VPS ..."
ssh "$VPS" bash -s <<'REMOTE'
set -euo pipefail
cd /opt/solana-arb-bot

# --- Create dedicated user if not exists ---
if ! id -u arbbot &>/dev/null; then
  echo "--- Creating arbbot user ---"
  useradd -r -m -s /bin/bash arbbot
fi

# --- Create Python venv ---
if [ ! -d venv ]; then
  echo "--- Creating Python venv ---"
  python3 -m venv venv
fi
source venv/bin/activate

# --- Install Python dependencies in venv ---
echo "--- Installing Python deps ---"
pip install -q -r detector/requirements.txt
pip install -q -r dashboard/requirements.txt

# --- Build Rust executor ---
if command -v cargo &>/dev/null; then
  echo "--- Building Rust executor ---"
  cd executor && cargo build --release 2>&1 | tail -3 && cd ..
elif [ -f "$HOME/.cargo/env" ]; then
  source "$HOME/.cargo/env"
  echo "--- Building Rust executor ---"
  cd executor && cargo build --release 2>&1 | tail -3 && cd ..
else
  echo "--- WARNING: cargo not found, skipping Rust build ---"
fi

# --- Create log directory ---
mkdir -p /var/log/arb-bot

# --- Set ownership ---
chown -R arbbot:arbbot /opt/solana-arb-bot /var/log/arb-bot

# --- Verify .env exists ---
if [ ! -f /opt/solana-arb-bot/.env ]; then
  echo "WARNING: .env file not found at /opt/solana-arb-bot/.env"
  echo "Copy .env.example to .env and configure before starting services."
fi

# --- Install systemd services ---
echo "--- Installing systemd services ---"
cp arb-bot.service /etc/systemd/system/arb-bot.service
cp arb-dashboard.service /etc/systemd/system/arb-dashboard.service
systemctl daemon-reload
systemctl enable arb-bot
systemctl enable arb-dashboard

# --- Restart services ---
systemctl restart arb-bot
sleep 3
systemctl restart arb-dashboard

echo ""
echo "--- Bot service status ---"
systemctl status arb-bot --no-pager || true
echo ""
echo "--- Dashboard service status ---"
systemctl status arb-dashboard --no-pager || true
echo ""
echo "--- Checking health endpoint ---"
curl -s http://127.0.0.1:8080/health 2>/dev/null || echo "(health endpoint not ready yet)"
echo ""
REMOTE

echo "==> Deploy complete."
echo "    Bot:       systemctl status arb-bot"
echo "    Dashboard: http://127.0.0.1:3000 (internal only — use SSH tunnel)"
echo "    Health:    http://127.0.0.1:8080/health (internal only)"
echo "    Logs:      ssh $VPS 'tail -f /var/log/arb-bot/bot.log'"
echo ""
echo "    NOTE: Dashboard and health are bound to 127.0.0.1."
echo "    To access remotely, use SSH tunnel:"
echo "      ssh -L 3000:127.0.0.1:3000 -L 8080:127.0.0.1:8080 $VPS"
