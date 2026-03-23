"""Main loop for the Solana arbitrage bot."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

load_dotenv()

from detector.config import BotConfig
from detector.price_fetcher import PriceFetcher
from detector.arbitrage import ArbitrageDetector
from detector.executor_bridge import ExecutorBridge
from detector.notifier import TelegramNotifier

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

PAIRS = [("SOL", "USDC"), ("SOL", "USDT")]
SUMMARY_INTERVAL = timedelta(hours=6)


async def run_bot() -> None:
    """Run the arbitrage bot main loop."""
    config = BotConfig()
    logger.info("Bot config loaded — dry_run=%s, poll=%ds", config.dry_run, config.poll_interval_sec)

    fetcher = PriceFetcher(rpc_url=config.rpc_url)
    detector = ArbitrageDetector(min_profit_pct=config.min_profit_pct)
    bridge = ExecutorBridge(
        executor_path=config.executor_path,
        rpc_url=config.rpc_url,
        keypair_path=config.keypair_path,
    )
    notifier = TelegramNotifier(
        token=config.telegram_bot_token,
        chat_id=config.telegram_chat_id,
    )

    # Startup alert
    await notifier.alert("Bot started (dry_run={})".format(config.dry_run))
    logger.info("Bot started")

    trades_since_summary = 0
    profit_since_summary = 0.0
    last_summary = datetime.now(timezone.utc)

    try:
        while True:
            # --- Kill switch ---
            balance = await bridge.get_balance()
            if balance < config.kill_switch_sol and not config.dry_run:
                msg = f"Kill switch triggered: balance {balance:.4f} SOL < {config.kill_switch_sol} SOL"
                logger.warning(msg)
                await notifier.alert(msg)
                break

            # --- Scan pairs ---
            for input_token, output_token in PAIRS:
                quotes = await fetcher.get_all_prices(input_token, output_token, config.trade_amount_sol)
                if not quotes:
                    continue

                opportunities = detector.find_opportunities(quotes)
                for opp in opportunities:
                    logger.info(
                        "Opportunity: %s buy@%s sell@%s profit=%.4f%%",
                        opp.pair, opp.buy_dex, opp.sell_dex, opp.profit_pct,
                    )

                    min_out = opp.sell_price * (1 - config.max_slippage_pct / 100)
                    result = await bridge.swap(
                        from_token=input_token,
                        to_token=output_token,
                        amount=opp.amount,
                        dex=opp.buy_dex,
                        min_out=min_out,
                        dry_run=config.dry_run,
                    )

                    tx_hash = result.get("tx_hash", "n/a")
                    await notifier.notify_trade(
                        pair=opp.pair,
                        buy_dex=opp.buy_dex,
                        sell_dex=opp.sell_dex,
                        amount=opp.amount,
                        profit=opp.estimated_profit,
                        tx_hash=tx_hash,
                    )
                    trades_since_summary += 1
                    profit_since_summary += opp.estimated_profit

            # --- Periodic summary ---
            now = datetime.now(timezone.utc)
            if now - last_summary >= SUMMARY_INTERVAL:
                current_balance = await bridge.get_balance()
                await notifier.summary(
                    trades=trades_since_summary,
                    total_profit=profit_since_summary,
                    balance=current_balance,
                )
                trades_since_summary = 0
                profit_since_summary = 0.0
                last_summary = now

            await asyncio.sleep(config.poll_interval_sec)

    except KeyboardInterrupt:
        logger.info("Received KeyboardInterrupt, shutting down...")
    except asyncio.CancelledError:
        logger.info("Task cancelled, shutting down...")
    finally:
        await fetcher.close()
        await notifier.alert("Bot stopped")
        logger.info("Bot stopped")


if __name__ == "__main__":
    asyncio.run(run_bot())
