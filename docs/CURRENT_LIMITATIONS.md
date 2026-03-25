# Current Limitations — Honest Assessment

## Detection ≠ Execution

The bot detects price differences across 4 DEXes (Orca, Raydium, Meteora, Lifinity).
**Only Raydium has a supported execution path** via its HTTP swap API.

When the bot says "buy@orca sell@raydium", it means:
- The price was **observed** as better on Orca
- The trade is **executed** on Raydium for both legs
- The actual execution price is the Raydium price, not the Orca price

This means:
- The "estimated profit" is based on the observed price difference
- The "realized profit" depends on what Raydium actually gives
- These can be very different

## Price data heterogeneity

| Source | Data type | Executable? | Amount-specific? |
|--------|-----------|-------------|------------------|
| Orca | Pool spot price (TVL-derived) | NO | NO (uses pool ratio) |
| Raydium | Computed swap quote | YES | YES (for exact input amount) |
| Meteora | Pool current_price field | NO | NO |
| Lifinity | API unavailable | NO | N/A |

Comparing an Orca pool price to a Raydium executable quote is **not apples-to-apples**.
The Raydium quote includes routing and slippage; the Orca price does not.

## Profit metrics

- `estimated_profit`: pre-execution estimate assuming zero slippage
- `realized_profit`: actual P&L after execution (requires on-chain confirmation)
- Currently, the bot only tracks estimated profit. Realized profit tracking requires post-trade balance reconciliation, which is not yet implemented.

## ML Scorer

The ML model is trained on **synthetic data** (not real trades).
Its accuracy (89.5%) is meaningless until retrained on real trade outcomes.
It should be treated as a placeholder, not a reliable filter.

## Backtester

The backtester assumes:
- Instant execution at quoted price
- Zero slippage
- Zero MEV impact
- No network latency

Real-world results will be significantly worse than backtest results.

## Jito Bundles

The Jito bundle sender (`send-bundle` CLI command) is implemented but **not connected to the main trading loop**. Two-leg trades still execute as separate transactions.

## Nightly AI Report

The report analyzes logs, not actual trade results. It can only comment on what the bot observed and logged, not on realized P&L.
