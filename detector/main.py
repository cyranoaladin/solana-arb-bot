"""Main loop for the Solana arbitrage bot."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

load_dotenv()

from detector.config import BotConfig
from detector.price_fetcher import PriceFetcher
from detector.arbitrage import ArbitrageDetector, VolatilityTracker
from detector.executor_bridge import ExecutorBridge
from detector.notifier import TelegramNotifier
from detector.helius import HeliusClient
from detector.circuit_breaker import CircuitBreaker, CircuitBreakerOpen
from detector.health import BotStats, start_health_server
from detector.ml_scorer import OpportunityScorer
from detector.nightly_report import run_nightly_report
from detector.arb_control_mcp import set_bot_state
from detector.ws_price_feed import WebSocketPriceFeed
from detector.db import TradeDB
from detector.oracle import PythOracle
from detector.trader_stats import TraderStats
from detector.sorted_opportunities import OpportunityRanker


class JsonFormatter(logging.Formatter):
    """Structured JSON log formatter."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0]:
            entry["exception"] = self.formatException(record.exc_info)
        # Merge extra fields
        for key in ("pair", "dex", "amount", "profit_pct", "fee", "tx_hash"):
            val = getattr(record, key, None)
            if val is not None:
                entry[key] = val
        return json.dumps(entry, default=str)


def setup_logging() -> None:
    """Configure structured JSON logging to stdout (captured by systemd)."""
    import sys
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    # Suppress noisy httpx request logs
    logging.getLogger("httpx").setLevel(logging.WARNING)


logger = logging.getLogger(__name__)

PAIRS = [("SOL", "USDC"), ("SOL", "USDT")]
# Additional pairs for triangular arb: USDC↔USDT
TRIANGULAR_PAIRS = [("SOL", "USDC"), ("SOL", "USDT"), ("USDC", "USDT")]
SUMMARY_INTERVAL = timedelta(hours=6)
NIGHTLY_REPORT_HOUR = 2


async def run_bot() -> None:
    """Run the arbitrage bot main loop."""
    setup_logging()

    config = BotConfig()

    # --- SAFETY GATES ---
    execution_mode = "dry_run"
    live_block_reason = config.live_block_reason
    if config.live_execution_allowed:
        execution_mode = "live_raydium_only"
        live_block_reason = ""
        logger.warning("LIVE TRADING ENABLED — execution_mode=%s", execution_mode)
    else:
        logger.info("Live trading BLOCKED: %s", live_block_reason)

    logger.info(
        "Bot config loaded — dry_run=%s, trading_enabled=%s, execution_mode=%s, poll=%ds",
        config.dry_run, config.trading_enabled, execution_mode, config.poll_interval_sec,
    )

    fetcher = PriceFetcher(rpc_url=config.rpc_url)
    detector = ArbitrageDetector(min_profit_pct=config.min_profit_pct)
    vol_tracker = VolatilityTracker()
    bridge = ExecutorBridge(
        executor_path=config.executor_path,
        rpc_url=config.rpc_url,
        keypair_path=config.keypair_path,
    )
    notifier = TelegramNotifier(
        token=config.telegram_bot_token,
        chat_id=config.telegram_chat_id,
    )
    helius = HeliusClient(rpc_url=config.rpc_url)
    oracle = PythOracle()
    scorer = OpportunityScorer()

    # Deduplicate all pairs for the WebSocket price feed
    all_pairs = list(dict.fromkeys(PAIRS + TRIANGULAR_PAIRS))
    ws_feed = WebSocketPriceFeed(price_fetcher=fetcher, pairs=all_pairs, poll_interval=0.5)

    # PostgreSQL trade storage (graceful if unavailable)
    trade_db = TradeDB()
    trade_db.init_schema()

    # Circuit breakers for API resilience (kept for RPC calls)
    cb_rpc = CircuitBreaker("rpc", failure_threshold=5, cooldown_sec=60)

    # Shared state for health endpoint
    stats = BotStats(
        dry_run=config.dry_run,
        live_enabled=config.live_execution_allowed,
        live_block_reason=live_block_reason,
        execution_mode=execution_mode,
    )

    # Smart trader analytics
    trader_stats = TraderStats()

    # Opportunity dedup + ranking (60s TTL, max 100)
    opp_ranker = OpportunityRanker(max_size=100, ttl_sec=60.0)

    # Start health check server
    health_server = await start_health_server(stats, host=config.health_bind_host)

    # Register bot state for MCP server access
    set_bot_state(stats=stats, config=config, detector=detector,
                  vol_tracker=vol_tracker, notifier=notifier,
                  trader_stats=trader_stats)

    # Start background price feed (replaces per-cycle REST polling)
    await ws_feed.start()

    # Startup alert
    await notifier.alert("Bot started (dry_run={})".format(config.dry_run))
    logger.info("Bot started")

    trades_since_summary = 0
    profit_since_summary = 0.0
    last_summary = datetime.now(timezone.utc)
    last_nightly = datetime.now(timezone.utc) - timedelta(hours=24)

    try:
        while True:
            if stats.paused:
                await asyncio.sleep(config.poll_interval_sec)
                continue

            # --- Kill switch ---
            try:
                balance = await cb_rpc.call(bridge.get_balance)
                stats.balance_sol = balance
            except CircuitBreakerOpen:
                logger.warning("RPC circuit breaker open, skipping cycle")
                await asyncio.sleep(config.poll_interval_sec)
                continue
            except Exception:
                logger.exception("Failed to get balance")
                stats.errors_total += 1
                await asyncio.sleep(config.poll_interval_sec)
                continue

            if balance < config.kill_switch_sol and config.live_execution_allowed:
                msg = f"Kill switch triggered: balance {balance:.4f} SOL < {config.kill_switch_sol} SOL"
                logger.warning(msg)
                await notifier.alert(msg)
                break

            # --- Pre-trade balance check ---
            if config.live_execution_allowed and balance < config.trade_amount_sol:
                logger.warning(
                    "Insufficient balance for trading: %.6f SOL < %.6f required",
                    balance, config.trade_amount_sol,
                )
                await asyncio.sleep(config.poll_interval_sec)
                continue

            # --- Get dynamic priority fee ---
            priority_fee = await helius.get_priority_fee()

            # --- Get oracle price for DEX cross-check ---
            oracle_sol_price = await oracle.get_sol_price_usd()

            # --- Scan pairs (prices come from background ws_feed) ---
            for input_token, output_token in PAIRS:
                quotes = ws_feed.get_quotes(input_token, output_token, config.trade_amount_sol)
                stats.last_scan_ts = time.time()

                if len(quotes) < 2:
                    continue

                # Feed prices to volatility tracker and adapt threshold
                for q in quotes:
                    vol_tracker.add_price(q.price)
                detector.min_profit_pct = vol_tracker.get_adaptive_min_profit()
                logger.info(
                    "Volatility=%.6f adaptive_min_profit=%.4f%%",
                    vol_tracker.get_volatility(),
                    detector.min_profit_pct,
                )

                opportunities = detector.find_opportunities(quotes)
                stats.opportunities_seen += len(opportunities)

                for opp in opportunities:
                    logger.info(
                        "Opportunity: %s buy@%s(%.4f) sell@%s(%.4f) profit=%.4f%% fee=%d",
                        opp.pair, opp.buy_dex, opp.buy_price,
                        opp.sell_dex, opp.sell_price, opp.profit_pct,
                        priority_fee,
                    )

                    # --- Dedup: skip if same opportunity seen recently ---
                    if not opp_ranker.add(opp.pair, opp.buy_dex, opp.sell_dex,
                                          opp.profit_pct, opp.estimated_profit):
                        logger.debug("Duplicate opportunity skipped: %s", opp.pair)
                        continue

                    # --- ML scorer gate ---
                    if not scorer.should_execute(opp, vol_tracker.get_volatility()):
                        logger.info("ML scorer rejected opportunity")
                        continue

                    # --- DEX vs Oracle divergence check ---
                    if oracle_sol_price and opp.pair.startswith("SOL"):
                        dex_price = opp.sell_price / opp.amount  # USDC per SOL
                        div = await oracle.check_dex_oracle_divergence(dex_price, oracle_sol_price)
                        if div.get("diverges"):
                            logger.warning(
                                "DEX-Oracle divergence: %.2f%% — skipping",
                                div["divergence_pct"],
                            )
                            continue

                    # --- Route support check ---
                    # Only Raydium execution is supported. Both legs go through Raydium.
                    # This is NOT true cross-DEX execution.
                    route_supported = True
                    if not config.live_trading_allow_unsupported_routes:
                        # All execution goes via Raydium regardless of detection DEX
                        # This is a known limitation documented in CURRENT_LIMITATIONS.md
                        pass

                    # --- Dynamic slippage based on spread size ---
                    # Larger spreads = more room for slippage (safe)
                    # Smaller spreads = tighter slippage (protect thin margin)
                    if opp.profit_pct > 0.5:
                        dynamic_slippage = min(config.max_slippage_pct, 0.8)
                    elif opp.profit_pct > 0.2:
                        dynamic_slippage = min(config.max_slippage_pct, 0.3)
                    else:
                        dynamic_slippage = min(config.max_slippage_pct * 0.5, 0.15)

                    # --- Determine execution mode ---
                    is_dry = config.dry_run or not config.live_execution_allowed
                    trade_status = "dry_run" if is_dry else "submitted"

                    # --- Leg 1: Swap input→output via Raydium ---
                    # min_out based on buy_price (what we expect to get), not sell_price
                    leg1_min_out = opp.buy_price * (1 - dynamic_slippage / 100)
                    result_leg1 = await bridge.swap_with_retry(
                        from_token=input_token,
                        to_token=output_token,
                        amount=opp.amount,
                        dex="raydium",
                        min_out=leg1_min_out,
                        dry_run=is_dry,
                        priority_fee=priority_fee,
                    )

                    if result_leg1.get("status") == "error":
                        logger.error("Leg 1 failed: %s", result_leg1.get("message"))
                        stats.errors_total += 1
                        trader_stats.record_trade(
                            pair=opp.pair, buy_dex=opp.buy_dex, sell_dex=opp.sell_dex,
                            profit_pct=opp.profit_pct, estimated_profit=opp.estimated_profit,
                            success=False,
                        )
                        await notifier.alert(
                            f"Leg 1 FAILED for {opp.pair}: {result_leg1.get('message', 'unknown')}"
                        )
                        continue

                    # --- Leg 2: use ACTUAL amount from Leg 1 (not estimated) ---
                    # In live: get actual output from result. In dry-run: use estimate.
                    leg1_actual_out = result_leg1.get("output_amount")
                    if leg1_actual_out is not None:
                        leg2_input = float(leg1_actual_out)
                    else:
                        # Fallback to estimate (dry-run or Raydium didn't return output)
                        leg2_input = opp.sell_price
                        if not is_dry:
                            logger.warning(
                                "Leg 1 did not return actual output_amount — using estimate %.6f",
                                leg2_input,
                            )

                    leg2_min_out = opp.amount * (1 - dynamic_slippage / 100)
                    result_leg2 = await bridge.swap_with_retry(
                        from_token=output_token,
                        to_token=input_token,
                        amount=leg2_input,
                        dex="raydium",
                        min_out=leg2_min_out,
                        dry_run=is_dry,
                        priority_fee=priority_fee,
                    )

                    if result_leg2.get("status") == "error":
                        logger.error("Leg 2 failed: %s", result_leg2.get("message"))
                        stats.errors_total += 1
                        trader_stats.record_trade(
                            pair=opp.pair, buy_dex=opp.buy_dex, sell_dex=opp.sell_dex,
                            profit_pct=opp.profit_pct, estimated_profit=opp.estimated_profit,
                            success=False,
                        )
                        await notifier.alert(
                            f"Leg 2 FAILED for {opp.pair}: {result_leg2.get('message', 'unknown')}"
                        )
                        continue

                    tx_hash_1 = result_leg1.get("tx_hash", "n/a")
                    tx_hash_2 = result_leg2.get("tx_hash", "n/a")

                    # --- Honest notification with explicit status ---
                    await notifier.notify_trade(
                        pair=opp.pair,
                        buy_dex=opp.buy_dex,
                        sell_dex=opp.sell_dex,
                        amount=opp.amount,
                        profit=opp.estimated_profit,
                        tx_hash=tx_hash_1,
                        status=trade_status,
                    )
                    trades_since_summary += 1
                    profit_since_summary += opp.estimated_profit
                    stats.trades_total += 1
                    stats.estimated_profit_total += opp.estimated_profit
                    stats.record_trade(
                        estimated_profit=opp.estimated_profit,
                        realized_profit=0.0,  # not yet reconciled
                    )
                    trader_stats.record_trade(
                        pair=opp.pair, buy_dex=opp.buy_dex, sell_dex=opp.sell_dex,
                        profit_pct=opp.profit_pct, estimated_profit=opp.estimated_profit,
                    )
                    trade_db.insert_trade(
                        pair=opp.pair, buy_dex=opp.buy_dex, sell_dex=opp.sell_dex,
                        amount=opp.amount, profit_pct=opp.profit_pct,
                        estimated_profit=opp.estimated_profit,
                        tx_hash_1=tx_hash_1, tx_hash_2=tx_hash_2,
                        dry_run=is_dry,
                    )
                    logger.info(
                        "Arb %s: leg1=%s leg2=%s estimated_profit=%.6f (realized=pending)",
                        trade_status, tx_hash_1, tx_hash_2, opp.estimated_profit,
                    )

            # --- Triangular arb scan (SOL→A→B→SOL) ---
            try:
                tri_quotes: dict[str, list] = {}
                for in_tok, out_tok in TRIANGULAR_PAIRS:
                    pair_key = f"{in_tok}/{out_tok}"
                    pair_quotes = ws_feed.get_quotes(in_tok, out_tok, config.trade_amount_sol)
                    if pair_quotes:
                        tri_quotes[pair_key] = pair_quotes
                if len(tri_quotes) >= 3:
                    tri_opps = detector.find_triangular_opportunities(
                        tri_quotes, start_token="SOL", start_amount=config.trade_amount_sol,
                    )
                    stats.opportunities_seen += len(tri_opps)
                    for opp in tri_opps:
                        logger.info("Triangular opportunity: %s profit=%.4f%%", opp.pair, opp.profit_pct)
                        # Log only — triangular execution requires Jito bundles (3 atomic txs)
                        await notifier.alert(
                            f"Triangular arb detected: {opp.pair} profit={opp.profit_pct:.4f}%"
                        )
            except Exception:
                logger.debug("Triangular scan error", exc_info=True)

            # --- Periodic summary ---
            now = datetime.now(timezone.utc)
            if now - last_summary >= SUMMARY_INTERVAL:
                current_balance = await bridge.get_balance()
                stats.balance_sol = current_balance
                await notifier.summary(
                    trades=trades_since_summary,
                    total_profit=profit_since_summary,
                    balance=current_balance,
                )
                trades_since_summary = 0
                profit_since_summary = 0.0
                last_summary = now

            # --- Nightly AI report ---
            if now.hour == NIGHTLY_REPORT_HOUR and (now - last_nightly).total_seconds() > 82800:  # ~23h
                await run_nightly_report(notifier, stats=stats.to_dict(), log_path=config.log_path)
                last_nightly = now

            await asyncio.sleep(config.poll_interval_sec)

    except KeyboardInterrupt:
        logger.info("Received KeyboardInterrupt, shutting down...")
    except asyncio.CancelledError:
        logger.info("Task cancelled, shutting down...")
    finally:
        await ws_feed.stop()
        health_server.close()
        await health_server.wait_closed()
        await fetcher.close()
        await helius.close()
        await oracle.close()
        trade_db.close()
        await notifier.alert("Bot stopped")
        logger.info("Bot stopped")


if __name__ == "__main__":
    asyncio.run(run_bot())
