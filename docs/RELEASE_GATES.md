# Release Gates

## Current status

| Level | Status | Notes |
|-------|--------|-------|
| **Dry-run ready** | YES | Safe to run with DRY_RUN=true |
| **Observation ready** | YES | Detects and logs opportunities, no execution |
| **Live-ready (limited)** | CONDITIONAL | Raydium-only, non-atomic, estimated PnL only |
| **Production-ready** | NO | Missing atomicity, realized PnL, Jito integration |

## Checklist: go to observation mode

- [x] DRY_RUN=true (default)
- [x] Wallet funded (not strictly needed for observation)
- [x] RPC endpoint configured
- [x] Telegram configured for alerts
- [x] Services running as arbbot (non-root)
- [x] Health/Dashboard on 127.0.0.1

## Checklist: go to live (limited)

- [ ] 72h successful dry-run with no anomalies
- [ ] DRY_RUN=false + TRADING_ENABLED=true
- [ ] LIVE_TRADING_ALLOW_UNSUPPORTED_ROUTES=false (blocks non-Raydium routes)
- [ ] Wallet funded with at least TRADE_AMOUNT_SOL + KILL_SWITCH_SOL
- [ ] Database configured for trade persistence
- [ ] Dashboard credentials strong and unique
- [ ] Understanding that:
  - Execution is Raydium-only (not truly cross-DEX)
  - Execution is non-atomic (2 separate transactions)
  - Profit is estimated, not realized
  - MEV sandwich risk exists between legs

## Must remain disabled until fixed

| Feature | Reason |
|---------|--------|
| Orca live execution | No HTTP swap API |
| Meteora live execution | No swap API in this build |
| Lifinity live execution | No public API |
| Triangular arb execution | No execution path |

## Now available

| Feature | Status |
|---------|--------|
| Jito atomic bundles | WIRED to main loop (USE_JITO_BUNDLES=true by default) |
| Realized PnL tracking | Pre/post balance comparison after each trade |
| build-swap CLI command | Builds tx without sending (for bundle composition) |

## Known residual risks

1. **Non-atomic execution**: Leg 2 may execute at a worse price than estimated
2. **MEV exposure**: Transactions are in the standard mempool (Jito not wired)
3. **Reference vs executable quotes**: Detection uses pool prices, execution uses swap quotes — may diverge
4. **ML scorer on synthetic data**: Accuracy metric is not meaningful

## Validation commands

```bash
# Run all Python tests
PYTEST_CURRENT_TEST=1 python -m pytest tests/ -v

# Run Rust tests + clippy
cd executor && cargo test && cargo clippy -- -D warnings

# Verify safety gate
python -c "
import os
os.environ['RPC_URL'] = 'https://fake'
os.environ['DRY_RUN'] = 'false'
from detector.config import BotConfig
try: BotConfig()
except ValueError as e: print('GATE OK:', e)
"

# Verify execution policy
python -c "
from detector.execution_policy import evaluate_opportunity, TradeDecision
from unittest.mock import MagicMock
cfg = MagicMock(dry_run=False, trading_enabled=True, live_trading_allow_unsupported_routes=False)
opp = MagicMock(buy_dex='orca', sell_dex='raydium', pair='SOL/USDC')
plan = evaluate_opportunity(opp, cfg)
assert plan.decision == TradeDecision.BLOCKED_UNSUPPORTED_ROUTE
print('POLICY OK: orca route blocked')
"

# Verify min_out enforced in Rust
grep -c 'min_out > 0.0 && output_amount < min_out' executor/src/swap.rs
# Should output: 1
```
