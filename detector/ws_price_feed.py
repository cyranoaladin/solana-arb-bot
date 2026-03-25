"""Background price polling feed (NOT WebSocket — HTTP polling at 500ms)."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Callable

import httpx

logger = logging.getLogger(__name__)


@dataclass
class PriceCache:
    """Thread-safe cache of latest prices from all DEXes."""
    prices: dict[str, dict[str, float]] = field(default_factory=dict)
    # Format: prices["SOL/USDC"]["orca"] = 91.5
    liquidity: dict[str, dict[str, float]] = field(default_factory=dict)
    # Format: liquidity["SOL/USDC"]["orca"] = 5000000.0  (TVL in USD)
    last_update_ts: dict[str, float] = field(default_factory=dict)

    def update(self, pair: str, dex: str, price: float, liquidity: float = 0.0) -> None:
        if pair not in self.prices:
            self.prices[pair] = {}
            self.liquidity[pair] = {}
        self.prices[pair][dex] = price
        self.liquidity[pair][dex] = liquidity
        self.last_update_ts[f"{pair}:{dex}"] = time.time()

    def get_quotes(self, input_token: str, output_token: str, amount: float):
        """Get all cached quotes for a pair."""
        from detector.price_fetcher import PriceQuote
        pair = f"{input_token}/{output_token}"
        quotes = []
        if pair not in self.prices:
            return quotes
        for dex, price in self.prices[pair].items():
            output_amount = amount * price
            liq = self.liquidity.get(pair, {}).get(dex, 0.0)
            quotes.append(PriceQuote(
                dex=dex, input_token=input_token, output_token=output_token,
                input_amount=amount, output_amount=output_amount, price=price,
                liquidity=liq,
            ))
        return quotes


class BackgroundPriceFeed:
    """Manages background price polling at high frequency (500ms) as a step toward full WebSocket.

    Uses asyncio tasks to continuously fetch prices in the background,
    making the latest prices available instantly to the main loop.

    Note: Full Solana accountSubscribe WebSocket requires parsing raw pool
    account data (Whirlpool/AMM state), which is DEX-specific and complex.
    This implementation uses high-frequency background polling as the
    practical first step, achieving 500ms latency vs the original 3s.
    """

    def __init__(self, price_fetcher, pairs: list[tuple[str, str]], poll_interval: float = 0.5):
        self.fetcher = price_fetcher
        self.pairs = pairs
        self.poll_interval = poll_interval
        self.cache = PriceCache()
        self._tasks: list[asyncio.Task] = []
        self._running = False

    async def start(self) -> None:
        """Start background price polling tasks."""
        self._running = True
        for input_tok, output_tok in self.pairs:
            task = asyncio.create_task(self._poll_pair(input_tok, output_tok))
            self._tasks.append(task)
        logger.info("Background price feed started for %d pairs (poll=%.1fs)", len(self.pairs), self.poll_interval)

    async def stop(self) -> None:
        """Stop all background polling tasks."""
        self._running = False
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        logger.info("Background price feed stopped")

    async def _poll_pair(self, input_token: str, output_token: str) -> None:
        """Continuously poll prices for a single pair."""
        pair = f"{input_token}/{output_token}"
        while self._running:
            try:
                # Fetch from all DEXes via get_all_prices (includes liquidity)
                quotes = await self.fetcher.get_all_prices(input_token, output_token, 1.0)
                for quote in quotes:
                    self.cache.update(pair, quote.dex, quote.price, quote.liquidity)
            except asyncio.CancelledError:
                return
            except Exception:
                logger.debug("Price poll error for %s", pair, exc_info=True)

            await asyncio.sleep(self.poll_interval)

    def get_quotes(self, input_token: str, output_token: str, amount: float):
        """Get the latest cached quotes for a pair, scaled to the given amount."""
        return self.cache.get_quotes(input_token, output_token, amount)
