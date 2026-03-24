"""Price fetcher module — retrieves quotes from Orca, Raydium, Meteora DLMM, and Lifinity APIs."""

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
RAYDIUM_COMPUTE_URL = "https://transaction-v1.raydium.io/compute/swap-base-in"
METEORA_DLMM_POOLS_URL = "https://dlmm.datapi.meteora.ag/pools"
LIFINITY_POOLS_URL = "https://api.lifinity.io/pools"


@dataclass
class PriceQuote:
    """A price quote from a DEX."""
    dex: str
    input_token: str
    output_token: str
    input_amount: float
    output_amount: float
    price: float
    liquidity: float = 0.0  # TVL or liquidity in USD (0 = unknown)


class PriceFetcher:
    """Fetches token prices from Orca, Raydium, Meteora DLMM, and Lifinity DEX APIs."""

    def __init__(self, rpc_url: str) -> None:
        self.rpc_url = rpc_url
        self.client = httpx.AsyncClient(timeout=10)

    async def get_orca_price(
        self, input_token: str, output_token: str, amount: float,
    ) -> Optional[float]:
        """Fetch price from Orca Whirlpool API using the pool price field."""
        result = await self._get_orca_price_with_liquidity(input_token, output_token, amount)
        return result[0] if result else None

    async def _get_orca_price_with_liquidity(
        self, input_token: str, output_token: str, amount: float,
    ) -> Optional[tuple[float, float]]:
        """Fetch price and TVL from Orca. Returns (output_amount, liquidity_usd)."""
        try:
            input_mint = TOKEN_MINTS[input_token]
            output_mint = TOKEN_MINTS[output_token]

            response = await self.client.get(
                ORCA_POOLS_URL,
                params={"tokenA": input_mint, "tokenB": output_mint},
            )
            response.raise_for_status()
            data = response.json()

            pools = data.get("data", [])
            if not pools:
                return None

            # Filter to only pools matching both mints exactly
            matching = [
                p for p in pools
                if p.get("tokenMintA") == input_mint and p.get("tokenMintB") == output_mint
            ]
            if not matching:
                # Try reverse order: pool may have tokens swapped
                matching = [
                    p for p in pools
                    if p.get("tokenMintA") == output_mint and p.get("tokenMintB") == input_mint
                ]
                if not matching:
                    return None
                pool = max(matching, key=lambda p: int(p.get("liquidity", "0")))
                # Price is tokenB/tokenA, but our input is tokenB in this pool
                # So we need 1/price to get output per input
                price = float(pool["price"])
                if price <= 0:
                    return None
                output_amount = amount / price
            else:
                pool = max(matching, key=lambda p: int(p.get("liquidity", "0")))
                # Price is tokenB/tokenA = output/input — exactly what we need
                price = float(pool["price"])
                if price <= 0:
                    return None
                output_amount = amount * price

            liquidity = float(pool.get("tvlUsdc", 0))
            return (output_amount, liquidity)
        except Exception:
            logger.exception("Failed to fetch Orca price for %s -> %s", input_token, output_token)
            return None

    async def get_raydium_price(
        self, input_token: str, output_token: str, amount: float,
    ) -> Optional[float]:
        """Fetch price from Raydium V3 API using the swap compute endpoint."""
        try:
            input_mint = TOKEN_MINTS[input_token]
            output_mint = TOKEN_MINTS[output_token]
            input_dec = TOKEN_DECIMALS[input_token]
            output_dec = TOKEN_DECIMALS[output_token]
            amount_raw = int(amount * (10 ** input_dec))

            response = await self.client.get(
                RAYDIUM_COMPUTE_URL,
                params={
                    "inputMint": input_mint,
                    "outputMint": output_mint,
                    "amount": str(amount_raw),
                    "slippageBps": "50",
                    "txVersion": "V0",
                },
            )
            response.raise_for_status()
            data = response.json()

            if not data.get("success", False):
                logger.warning("Raydium compute failed: %s", data.get("msg", "unknown"))
                return None

            out_raw = data.get("data", {}).get("outputAmount")
            if out_raw is None:
                return None

            output_amount = int(out_raw) / (10 ** output_dec)
            return output_amount if output_amount > 0 else None
        except Exception:
            logger.exception("Failed to fetch Raydium price for %s -> %s", input_token, output_token)
            return None

    async def get_meteora_price(
        self, input_token: str, output_token: str, amount: float,
    ) -> Optional[float]:
        """Fetch price from Meteora DLMM API using pool current_price field."""
        result = await self._get_meteora_price_with_liquidity(input_token, output_token, amount)
        return result[0] if result else None

    async def _get_meteora_price_with_liquidity(
        self, input_token: str, output_token: str, amount: float,
    ) -> Optional[tuple[float, float]]:
        """Fetch price and TVL from Meteora. Returns (output_amount, liquidity_usd)."""
        try:
            input_mint = TOKEN_MINTS[input_token]
            output_mint = TOKEN_MINTS[output_token]

            # Search for pools matching the token pair by name (e.g. "SOL-USDC")
            pair_name = f"{input_token}-{output_token}"
            response = await self.client.get(
                METEORA_DLMM_POOLS_URL,
                params={
                    "query": pair_name,
                    "page": "1",
                    "page_size": "10",
                    "sort_by": "volume_24h:desc",
                },
            )
            response.raise_for_status()
            data = response.json()

            pools = data.get("data", [])
            if not pools:
                logger.warning("Meteora: no pools found for %s", pair_name)
                return None

            # Find pool where token_x and token_y match our mints
            best_pool = None
            reversed_pair = False
            for pool in pools:
                tx = pool.get("token_x", {}).get("address", "")
                ty = pool.get("token_y", {}).get("address", "")
                if tx == input_mint and ty == output_mint:
                    best_pool = pool
                    break
                if tx == output_mint and ty == input_mint:
                    best_pool = pool
                    reversed_pair = True
                    break

            if best_pool is None:
                logger.warning("Meteora: no matching pool for mints %s/%s", input_token, output_token)
                return None

            price = float(best_pool.get("current_price", 0))
            if price <= 0:
                return None

            # current_price is token_y per token_x
            if reversed_pair:
                # input is token_y, output is token_x => output = amount / price
                output_amount = amount / price
            else:
                # input is token_x, output is token_y => output = amount * price
                output_amount = amount * price

            if output_amount <= 0:
                return None

            liquidity = float(best_pool.get("tvl", 0))
            return (output_amount, liquidity)
        except Exception:
            logger.exception("Failed to fetch Meteora price for %s -> %s", input_token, output_token)
            return None

    async def get_lifinity_price(
        self, input_token: str, output_token: str, amount: float,
    ) -> Optional[float]:
        """Fetch price from Lifinity API.

        Lifinity does not currently expose a public REST API for pool prices.
        This method attempts to call the known endpoint and gracefully returns
        None if unavailable, so the bot continues operating with other DEXes.
        """
        try:
            input_mint = TOKEN_MINTS[input_token]
            output_mint = TOKEN_MINTS[output_token]

            response = await self.client.get(
                LIFINITY_POOLS_URL,
                params={"tokenA": input_mint, "tokenB": output_mint},
            )
            response.raise_for_status()
            data = response.json()

            # Expected response: list of pools with price info
            pools = data if isinstance(data, list) else data.get("data", [])
            if not pools:
                logger.debug("Lifinity: no pools returned for %s -> %s", input_token, output_token)
                return None

            pool = pools[0]
            price = float(pool.get("price", 0))
            if price <= 0:
                return None

            output_amount = amount * price
            return output_amount if output_amount > 0 else None
        except Exception:
            logger.warning("Lifinity API unavailable for %s -> %s (expected — no public API)", input_token, output_token)
            return None

    async def get_all_prices(
        self, input_token: str, output_token: str, amount: float,
    ) -> list[PriceQuote]:
        """Fetch prices from all supported DEXes and return a list of PriceQuote."""
        quotes: list[PriceQuote] = []

        # Fetch all DEXes in parallel (use liquidity-aware variants where available)
        import asyncio
        orca_task = asyncio.create_task(self._get_orca_price_with_liquidity(input_token, output_token, amount))
        raydium_task = asyncio.create_task(self.get_raydium_price(input_token, output_token, amount))
        meteora_task = asyncio.create_task(self._get_meteora_price_with_liquidity(input_token, output_token, amount))
        lifinity_task = asyncio.create_task(self.get_lifinity_price(input_token, output_token, amount))

        orca_result, raydium_out, meteora_result, lifinity_out = await asyncio.gather(
            orca_task, raydium_task, meteora_task, lifinity_task,
        )

        # Orca: tuple (output_amount, liquidity) or None
        if orca_result is not None and orca_result[0] > 0:
            out_amount, liq = orca_result
            quotes.append(PriceQuote(
                dex="orca", input_token=input_token, output_token=output_token,
                input_amount=amount, output_amount=out_amount, price=out_amount / amount,
                liquidity=liq,
            ))

        # Raydium: plain float, no liquidity info
        if raydium_out is not None and raydium_out > 0:
            quotes.append(PriceQuote(
                dex="raydium", input_token=input_token, output_token=output_token,
                input_amount=amount, output_amount=raydium_out, price=raydium_out / amount,
                liquidity=0.0,
            ))

        # Meteora: tuple (output_amount, liquidity) or None
        if meteora_result is not None and meteora_result[0] > 0:
            out_amount, liq = meteora_result
            quotes.append(PriceQuote(
                dex="meteora", input_token=input_token, output_token=output_token,
                input_amount=amount, output_amount=out_amount, price=out_amount / amount,
                liquidity=liq,
            ))

        # Lifinity: plain float, no liquidity info
        if lifinity_out is not None and lifinity_out > 0:
            quotes.append(PriceQuote(
                dex="lifinity", input_token=input_token, output_token=output_token,
                input_amount=amount, output_amount=lifinity_out, price=lifinity_out / amount,
                liquidity=0.0,
            ))

        return quotes

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self.client.aclose()
