"""Price fetcher module — retrieves quotes from Orca and Raydium APIs."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

TOKEN_MINTS = {
    "SOL": "So11111111111111111111111111111111111111112",
    "USDC": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "USDT": "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
}

TOKEN_DECIMALS = {"SOL": 9, "USDC": 6, "USDT": 6}

ORCA_POOLS_URL = "https://api.orca.so/v2/solana/pools"
RAYDIUM_POOLS_URL = "https://api-v3.raydium.io/pools/info/mint"


@dataclass
class PriceQuote:
    """A price quote from a DEX."""
    dex: str
    input_token: str
    output_token: str
    input_amount: float
    output_amount: float
    price: float


class PriceFetcher:
    """Fetches token prices from Orca and Raydium DEX APIs."""

    def __init__(self, rpc_url: str) -> None:
        self.rpc_url = rpc_url
        self.client = httpx.AsyncClient(timeout=10)

    async def get_orca_price(
        self, input_token: str, output_token: str, amount: float,
    ) -> Optional[float]:
        """Fetch price from Orca Whirlpool API using sqrtPrice."""
        try:
            input_mint = TOKEN_MINTS[input_token]
            output_mint = TOKEN_MINTS[output_token]
            input_dec = TOKEN_DECIMALS[input_token]
            output_dec = TOKEN_DECIMALS[output_token]

            response = await self.client.get(
                ORCA_POOLS_URL,
                params={"tokenA": input_mint, "tokenB": output_mint},
            )
            response.raise_for_status()
            data = response.json()

            pools = data.get("data", [])
            if not pools:
                return None

            # Use the pool with highest liquidity
            pool = max(pools, key=lambda p: int(p.get("liquidity", "0")))
            sqrt_price = int(pool["sqrtPrice"])

            # sqrtPrice is Q64.64 fixed point: price = (sqrtPrice / 2^64)^2
            price_raw = (sqrt_price / (2 ** 64)) ** 2
            # Adjust for decimal difference
            decimal_adjustment = 10 ** (input_dec - output_dec)
            price = price_raw * decimal_adjustment

            output_amount = amount * price
            return output_amount
        except Exception:
            logger.exception("Failed to fetch Orca price for %s -> %s", input_token, output_token)
            return None

    async def get_raydium_price(
        self, input_token: str, output_token: str, amount: float,
    ) -> Optional[float]:
        """Fetch price from Raydium V3 API."""
        try:
            input_mint = TOKEN_MINTS[input_token]
            output_mint = TOKEN_MINTS[output_token]

            response = await self.client.get(
                RAYDIUM_POOLS_URL,
                params={
                    "mint1": input_mint,
                    "mint2": output_mint,
                    "poolType": "standard",
                    "poolSortField": "liquidity",
                    "sortType": "desc",
                    "pageSize": "1",
                },
            )
            response.raise_for_status()
            data = response.json()

            pools = data.get("data", {}).get("data", [])
            if not pools:
                return None

            pool = pools[0]
            price = float(pool.get("price", 0))
            if price <= 0:
                return None

            output_amount = amount * price
            return output_amount
        except Exception:
            logger.exception("Failed to fetch Raydium price for %s -> %s", input_token, output_token)
            return None

    async def get_all_prices(
        self, input_token: str, output_token: str, amount: float,
    ) -> list[PriceQuote]:
        """Fetch prices from all supported DEXes and return a list of PriceQuote."""
        quotes: list[PriceQuote] = []

        # Fetch Orca and Raydium in parallel
        import asyncio
        orca_task = asyncio.create_task(self.get_orca_price(input_token, output_token, amount))
        raydium_task = asyncio.create_task(self.get_raydium_price(input_token, output_token, amount))

        orca_out, raydium_out = await asyncio.gather(orca_task, raydium_task)

        if orca_out is not None and orca_out > 0:
            quotes.append(PriceQuote(
                dex="orca", input_token=input_token, output_token=output_token,
                input_amount=amount, output_amount=orca_out, price=orca_out / amount,
            ))

        if raydium_out is not None and raydium_out > 0:
            quotes.append(PriceQuote(
                dex="raydium", input_token=input_token, output_token=output_token,
                input_amount=amount, output_amount=raydium_out, price=raydium_out / amount,
            ))

        return quotes

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self.client.aclose()
