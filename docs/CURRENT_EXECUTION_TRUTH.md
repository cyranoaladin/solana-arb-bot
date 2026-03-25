# Current Execution Truth

## What the bot actually does

1. **Polls** prices from 4 DEXes every 500ms (HTTP, not WebSocket)
2. **Detects** spreads between DEX prices
3. **In dry-run**: logs the opportunity, no execution
4. **In live (if enabled)**: executes BOTH legs through Raydium API only

## What "cross-DEX arbitrage" means here

When the bot says "buy@orca sell@raydium", it means:
- The spread was **detected** by comparing Orca pool price vs Raydium compute quote
- The trade is **executed** via Raydium for BOTH legs
- This is NOT "buy on Orca, sell on Raydium"
- This is "detected on Orca, executed on Raydium"

## Why this matters

- The Orca price is a **pool spot price** (not a swap quote for the exact amount)
- The Raydium price is an **executable swap quote** (amount-specific)
- These are different types of data
- The detected spread may not exist when execution happens

## Quote types

| DEX | Quote type | Executable | Amount-specific |
|-----|-----------|------------|-----------------|
| Raydium | Computed swap quote | Yes | Yes |
| Orca | Pool spot price | No | No |
| Meteora | Pool current_price | No | No |
| Lifinity | Best-effort API | No | No |

## Atomicity

The two legs of an arbitrage trade are **separate transactions**.
There is no atomicity guarantee. Between Leg 1 and Leg 2:
- The price can move
- MEV bots can sandwich
- The second leg can fail

Jito bundle support exists in the Rust executor but is **not connected** to the Python main loop.

## Profit tracking

Only `estimated_profit` is tracked (pre-execution estimate).
`realized_profit` requires post-trade on-chain reconciliation, which is not implemented.
