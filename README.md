# Solana Arbitrage Bot

Automated SOL/USDC arbitrage detector and executor across Jupiter DEX routes on Solana.

## Architecture

```
+------------------+       +------------------+       +------------------+
|  Price Fetcher   | ----> | Arbitrage Detect | ----> | Rust Executor    |
|  (Jupiter API)   |       | (spread calc)    |       | (swap + confirm) |
+------------------+       +------------------+       +------------------+
         |                          |                          |
         v                          v                          v
+---------------------------------------------------------------+
|                    Telegram Notifier                          |
|              (alerts, trades, periodic summary)               |
+---------------------------------------------------------------+
```

- **detector/** -- Python: price fetching, spread detection, main loop, Telegram alerts
- **executor/** -- Rust: on-chain swap execution via Solana RPC

## Setup

```bash
git clone <repo-url> && cd solana-arb-bot

# Configure environment
cp .env.example .env   # then edit with your values

# Install Python dependencies
pip3 install -r detector/requirements.txt

# Build Rust executor
cd executor && cargo build --release && cd ..
```

## Deploy to VPS

```bash
./deploy.sh
```

This rsyncs the project to the VPS, installs deps, builds the executor, and starts the systemd service.

## Commands

```bash
# Start / stop / restart
sudo systemctl start arb-bot
sudo systemctl stop arb-bot
sudo systemctl restart arb-bot

# Logs
tail -f /var/log/arb-bot/bot.log
tail -f /var/log/arb-bot/error.log

# Status
sudo systemctl status arb-bot
```

## Configuration (.env)

| Variable            | Description                        | Default        |
|---------------------|------------------------------------|----------------|
| `RPC_URL`           | Solana RPC endpoint                | _(required)_   |
| `KEYPAIR_PATH`      | Path to wallet JSON keypair        | `./wallet.json`|
| `TELEGRAM_BOT_TOKEN`| Telegram bot API token             | _(required)_   |
| `TELEGRAM_CHAT_ID`  | Telegram chat ID for notifications | _(required)_   |
| `TRADE_AMOUNT_SOL`  | Amount of SOL per trade            | `0.05`         |
| `MIN_PROFIT_PCT`    | Minimum profit % to trigger trade  | `0.1`          |
| `MAX_SLIPPAGE_PCT`  | Maximum allowed slippage %         | `0.5`          |
| `KILL_SWITCH_SOL`   | Stop trading below this balance    | `0.05`         |
| `DRY_RUN`           | Simulate trades without executing  | `true`         |
| `POLL_INTERVAL_SEC` | Seconds between price checks       | `3`            |
| `EXECUTOR_PATH`     | Path to Rust executor binary       | `./executor/target/release/executor` |
