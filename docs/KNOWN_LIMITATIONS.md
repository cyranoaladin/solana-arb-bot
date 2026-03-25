# Known Limitations

## Execution

1. **Single-DEX execution**: Only Raydium has a supported swap API. All trades execute via Raydium regardless of which DEX detected the opportunity.

2. **Non-atomic 2-leg trades**: Leg 1 and Leg 2 are separate transactions. No atomicity guarantee. Inventory risk between legs.

3. **No Orca execution**: Orca has no public HTTP swap API. Used for price observation only.

4. **No Meteora/Lifinity execution**: Same limitation as Orca.

5. **Triangular arbitrage**: Detection only. No execution path exists in this build.

6. **Jito bundles**: Code exists (`executor/src/jito.rs`, `send-bundle` CLI command) but is NOT wired to the Python main loop. Not used for standard trades.

## Pricing

7. **Heterogeneous quotes**: Orca/Meteora provide pool spot prices. Raydium provides amount-specific computed quotes. Comparing them is not apples-to-apples.

8. **Background polling, not WebSocket**: Prices are HTTP-polled every 500ms. Not streamed via WebSocket. `ws_price_feed.py` is a background poller despite its name.

9. **Linear rescaling removed**: The cache no longer rescales a price fetched for amount=1.0 to arbitrary amounts. Quotes are fetched for the actual trade amount.

## Accounting

10. **No realized PnL**: Only estimated profit is tracked. On-chain reconciliation of actual trade results is not implemented.

11. **ML scorer**: Trained on synthetic data. Accuracy number is meaningless until retrained on real trades.

12. **Backtester**: Adds simulated slippage/MEV but cannot model real network latency, adversarial MEV strategies, or price movement during block confirmation.

## Infrastructure

13. **Health/Dashboard internal only**: Bound to 127.0.0.1 by default. Requires SSH tunnel for remote access.

14. **Database optional**: PostgreSQL persistence is optional. If DATABASE_URL is not set, trades are not persisted.

15. **Nightly AI report**: Uses Ollama local model (qwen2.5:1.5b). Quality depends on model capability and log content. Report is descriptive, not prescriptive.
