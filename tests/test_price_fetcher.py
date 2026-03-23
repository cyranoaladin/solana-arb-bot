"""Tests for the price fetcher module."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from detector.price_fetcher import (
    PriceFetcher,
    PriceQuote,
    TOKEN_DECIMALS,
    TOKEN_MINTS,
)


@pytest.mark.asyncio
async def test_fetch_jupiter_quote():
    """Mock httpx client.get to return a valid Jupiter quote response."""
    fetcher = PriceFetcher(rpc_url="https://fake-rpc.example.com")

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"outAmount": "14500000"}
    mock_response.raise_for_status = MagicMock()

    fetcher.client.get = AsyncMock(return_value=mock_response)

    result = await fetcher.get_jupiter_price("SOL", "USDC", 1.0)

    assert result == pytest.approx(14.5, rel=0.01)
    await fetcher.close()


@pytest.mark.asyncio
async def test_fetch_returns_none_on_error():
    """Mock httpx to raise an HTTPError; result should be None."""
    import httpx

    fetcher = PriceFetcher(rpc_url="https://fake-rpc.example.com")
    fetcher.client.get = AsyncMock(side_effect=httpx.HTTPError("connection failed"))

    result = await fetcher.get_jupiter_price("SOL", "USDC", 1.0)

    assert result is None
    await fetcher.close()


@pytest.mark.asyncio
async def test_get_all_prices_returns_quotes():
    """Mock get_jupiter_price and verify get_all_prices returns correct quotes."""
    fetcher = PriceFetcher(rpc_url="https://fake-rpc.example.com")

    with patch.object(fetcher, "get_jupiter_price", new_callable=AsyncMock) as mock_jup:
        mock_jup.return_value = 14.5

        quotes = await fetcher.get_all_prices("SOL", "USDC", 1.0)

    assert len(quotes) == 1
    assert quotes[0].dex == "jupiter"
    assert quotes[0].input_token == "SOL"
    assert quotes[0].output_token == "USDC"
    assert quotes[0].input_amount == 1.0
    assert quotes[0].output_amount == 14.5
    await fetcher.close()


def test_price_quote_dataclass():
    """Create a PriceQuote and verify all fields are set correctly."""
    quote = PriceQuote(
        dex="jupiter",
        input_token="SOL",
        output_token="USDC",
        input_amount=1.0,
        output_amount=14.5,
        price=14.5,
    )

    assert quote.dex == "jupiter"
    assert quote.input_token == "SOL"
    assert quote.output_token == "USDC"
    assert quote.input_amount == 1.0
    assert quote.output_amount == 14.5
    assert quote.price == 14.5
