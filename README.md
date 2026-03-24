# Solana Arbitrage Bot

Automated SOL/USDC and SOL/USDT arbitrage detector and executor across Orca and Raydium DEXes on Solana.

## Architecture

```
+------------------+       +------------------+       +------------------+
|  Price Fetcher   | ----> | Arbitrage Detect | ----> | Rust Executor    |
| Orca (pools API) |       | (spread calc,    |       | Raydium swap API |
| Raydium (compute)|       |  tx fee deduct)  |       | sign + send tx   |
+------------------+       +------------------+       +------------------+
         |                          |                          |
         v                          v                          v
+---------------------------------------------------------------+
|                    Telegram Notifier                          |
|              (alerts, trades, periodic summary)               |
+---------------------------------------------------------------+
```

- **detector/** -- Python: price fetching (Orca + Raydium), spread detection, main loop, Telegram alerts
- **executor/** -- Rust: on-chain swap execution via Raydium swap API + Solana RPC

### How it works

1. Every 3 seconds, fetches SOL/USDC and SOL/USDT prices from **Orca Whirlpool** (pool price) and **Raydium** (compute/swap API)
2. Compares prices across DEXes. If spread > `MIN_PROFIT_PCT` (after tx fees), triggers arbitrage
3. **Leg 1**: Swaps SOL→USDC via Raydium API (gets serialized tx, signs, sends)
4. **Leg 2**: Swaps USDC→SOL back via Raydium API (captures the spread)
5. Sends Telegram notification with trade details and Solscan link
6. Kill switch stops trading if balance drops below threshold

## Setup

```bash
git clone <repo-url> && cd solana-arb-bot

# Configure environment
cp .env.example .env   # then edit with your values

# Install Python dependencies
pip3 install -r detector/requirements.txt

# Build Rust executor
cd executor && cargo build --release && cd ..

# Run in dry-run mode (default)
python -m detector.main
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

## Going to production

1. Fund the wallet with SOL (check address with `./executor/target/release/executor pubkey --keypair-path ./wallet.json`)
2. Set `DRY_RUN=false` in `.env`
3. Start with a small `TRADE_AMOUNT_SOL` (e.g., 0.01)
4. Monitor via Telegram and logs
5. Increase trade amount gradually once confident

## Tests

```bash
python -m pytest tests/ -v
```
