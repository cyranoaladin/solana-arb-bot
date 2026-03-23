"""Price fetcher module — retrieves quotes from Jupiter API."""

from __future__ import annotations

import logging
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

JUPITER_QUOTE_URL = "https://quote-api.jup.ag/v6/quote"


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
    """Fetches token prices from on-chain DEX aggregators."""

    def __init__(self, rpc_url: str) -> None:
        self.rpc_url = rpc_url
        self.client = httpx.AsyncClient(timeout=5)

    async def get_jupiter_price(
        self,
        input_token: str,
        output_token: str,
        amount: float,
    ) -> Optional[float]:
        """Fetch a quote from Jupiter Quote API v6.

        Returns the output amount as a float (adjusted for decimals), or None on error.
        """
        try:
            input_mint = TOKEN_MINTS[input_token]
            output_mint = TOKEN_MINTS[output_token]
            input_decimals = TOKEN_DECIMALS[input_token]
            output_decimals = TOKEN_DECIMALS[output_token]

            raw_amount = int(amount * (10 ** input_decimals))

            response = await self.client.get(
                JUPITER_QUOTE_URL,
                params={
                    "inputMint": input_mint,
                    "outputMint": output_mint,
                    "amount": str(raw_amount),
                    "slippageBps": "50",
                },
            )
            response.raise_for_status()
            data = response.json()

            raw_out = int(data["outAmount"])
            return raw_out / (10 ** output_decimals)
        except Exception:
            logger.exception("Failed to fetch Jupiter quote for %s -> %s", input_token, output_token)
            return None

    async def get_all_prices(
        self,
        input_token: str,
        output_token: str,
        amount: float,
    ) -> list[PriceQuote]:
        """Fetch prices from all supported DEXes and return a list of PriceQuote."""
        quotes: list[PriceQuote] = []

        jup_output = await self.get_jupiter_price(input_token, output_token, amount)
        if jup_output is not None:
            price = jup_output / amount if amount else 0.0
            quotes.append(
                PriceQuote(
                    dex="jupiter",
                    input_token=input_token,
                    output_token=output_token,
                    input_amount=amount,
                    output_amount=jup_output,
                    price=price,
                )
            )

        return quotes

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self.client.aclose()
