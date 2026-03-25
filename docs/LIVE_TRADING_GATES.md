# Live Trading Safety Gates

## Current status: LIVE TRADING BLOCKED BY DEFAULT

The bot defaults to `DRY_RUN=true` and `TRADING_ENABLED=false`.
Live trading requires explicit opt-in through **both** flags.

## Prerequisites before enabling live trading

### Mandatory (P0)

1. **TRADING_ENABLED=true** in `.env` — explicit opt-in
2. **DRY_RUN=false** in `.env` — disables simulation mode
3. **Wallet funded** — balance >= TRADE_AMOUNT_SOL + KILL_SWITCH_SOL
4. **RPC endpoint reliable** — Helius paid tier recommended for live
5. **Telegram configured** — alerts must be working to monitor trades

### Strongly recommended (P1)

6. **72h dry-run validation** — run in dry-run for 72h, review all logs
7. **Database configured** — DATABASE_URL set for trade persistence
8. **Dashboard credentials set** — strong DASHBOARD_USER/DASHBOARD_PASS
9. **Services running as non-root** — `arbbot` user configured

## Current execution limitations

| Feature | Status | Detail |
|---------|--------|--------|
| Raydium swap execution | SUPPORTED | Via Raydium compute + transaction API |
| Orca swap execution | NOT SUPPORTED | No HTTP swap API. Used for price discovery only |
| Meteora swap execution | NOT SUPPORTED | Used for price discovery only |
| Lifinity swap execution | NOT SUPPORTED | API not publicly available |
| Two-leg arbitrage (non-atomic) | RISKY | Legs execute independently — MEV sandwich risk |
| Jito atomic bundles | IMPLEMENTED BUT NOT WIRED | `send-bundle` CLI exists but not called from main loop |
| Triangular arbitrage | OBSERVATION ONLY | Detection works, execution not supported |

## What "execution" means today

The bot can only execute swaps via **Raydium's HTTP API**.
When an opportunity is detected between any two DEXes:
- Detection: compares prices from Orca, Raydium, Meteora, Lifinity
- Execution: **both legs route through Raydium** (not through the DEX where the price was found)
- This means the actual execution price may differ from the detected price

## Risk: non-atomic two-leg execution

Currently, Leg 1 and Leg 2 are separate transactions:
1. Leg 1 executes (SOL → USDC)
2. Wait for confirmation
3. Leg 2 executes (USDC → SOL)

Between steps 2 and 3, the price can move. This creates **inventory risk**.

### Mitigation (not yet implemented)
- Use Jito bundles to make both legs atomic (code exists in `jito.rs`)
- Set `LIVE_TRADING_ALLOW_UNSUPPORTED_ROUTES=false` to block routes where execution DEX ≠ detection DEX
