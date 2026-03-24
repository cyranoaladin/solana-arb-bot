"""Pyth Network oracle integration — cross-check DEX prices with oracle prices."""

from __future__ import annotations

import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

PYTH_HERMES_URL = "https://hermes.pyth.network/v2/updates/price/latest"

# Pyth price feed IDs
PYTH_FEED_IDS = {
    "SOL/USD": "0xef0d8b6fda2ceba41da15d4095d1da392a0d2f8ed0c6c7bc0f4cfac8c280b56d",
    "USDC/USD": "0xeaa020c61cc479712813461ce153894a96a6c00b21ed0cfc2798d1f9a9e9c94a",
}


class PythOracle:
    """Client for Pyth Network Hermes API (free, no key required)."""

    def __init__(self) -> None:
        self.client = httpx.AsyncClient(timeout=10)
        self._cache: dict[str, float] = {}

    async def get_price(self, feed_name: str) -> Optional[float]:
        """Get the latest price from Pyth oracle for a feed (e.g., 'SOL/USD')."""
        feed_id = PYTH_FEED_IDS.get(feed_name)
        if not feed_id:
            return None
        try:
            resp = await self.client.get(
                PYTH_HERMES_URL,
                params={"ids[]": feed_id},
            )
            resp.raise_for_status()
            data = resp.json()

            parsed = data.get("parsed", [])
            if not parsed:
                return None

            price_data = parsed[0].get("price", {})
            price_val = int(price_data.get("price", 0))
            expo = int(price_data.get("expo", 0))

            if price_val == 0:
                return None

            price = price_val * (10 ** expo)
            self._cache[feed_name] = price
            return price
        except Exception:
            logger.warning("Pyth oracle fetch failed for %s", feed_name)
            return self._cache.get(feed_name)  # return cached value on error

    async def get_sol_price_usd(self) -> Optional[float]:
        """Get SOL/USD price from Pyth."""
        return await self.get_price("SOL/USD")

    async def check_dex_oracle_divergence(
        self, dex_price: float, oracle_price: float, threshold_pct: float = 1.0,
    ) -> dict:
        """Check if DEX price diverges from oracle price beyond threshold.

        Returns: {diverges: bool, dex_price, oracle_price, divergence_pct}
        """
        if oracle_price <= 0:
            return {"diverges": False, "error": "invalid oracle price"}

        divergence_pct = abs(dex_price - oracle_price) / oracle_price * 100
        return {
            "diverges": divergence_pct > threshold_pct,
            "dex_price": dex_price,
            "oracle_price": oracle_price,
            "divergence_pct": round(divergence_pct, 4),
        }

    async def close(self) -> None:
        await self.client.aclose()
