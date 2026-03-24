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
async def test_fetch_orca_quote():
    """Mock httpx client.get to return a valid Orca pool response."""
    fetcher = PriceFetcher(rpc_url="https://fake-rpc.example.com")

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": [
            {
                "tokenMintA": TOKEN_MINTS["SOL"],
                "tokenMintB": TOKEN_MINTS["USDC"],
                "price": "145.0",
                "liquidity": "1000000000",
            }
        ]
    }
    mock_response.raise_for_status = MagicMock()

    fetcher.client.get = AsyncMock(return_value=mock_response)

    result = await fetcher.get_orca_price("SOL", "USDC", 1.0)

    assert result is not None
    assert result == pytest.approx(145.0, rel=0.01)
    await fetcher.close()


@pytest.mark.asyncio
async def test_fetch_orca_reverse_pool():
    """Orca pool may have tokens in reverse order."""
    fetcher = PriceFetcher(rpc_url="https://fake-rpc.example.com")

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": [
            {
                "tokenMintA": TOKEN_MINTS["USDC"],
                "tokenMintB": TOKEN_MINTS["SOL"],
                "price": "0.006897",  # 1/145 USDC per SOL
                "liquidity": "1000000000",
            }
        ]
    }
    mock_response.raise_for_status = MagicMock()

    fetcher.client.get = AsyncMock(return_value=mock_response)

    result = await fetcher.get_orca_price("SOL", "USDC", 1.0)

    assert result is not None
    # 1 / 0.006897 ≈ 145
    assert result == pytest.approx(145.0, rel=0.01)
    await fetcher.close()


@pytest.mark.asyncio
async def test_fetch_raydium_quote():
    """Mock httpx client.get to return a valid Raydium compute response."""
    fetcher = PriceFetcher(rpc_url="https://fake-rpc.example.com")

    mock_response = MagicMock()
    mock_response.status_code = 200
    # Raydium compute API returns outputAmount in raw units (USDC has 6 decimals)
    mock_response.json.return_value = {
        "success": True,
        "data": {
            "outputAmount": "146500000",  # 146.5 USDC
        },
    }
    mock_response.raise_for_status = MagicMock()

    fetcher.client.get = AsyncMock(return_value=mock_response)

    result = await fetcher.get_raydium_price("SOL", "USDC", 1.0)

    assert result is not None
    assert result == pytest.approx(146.5, rel=0.01)
    await fetcher.close()


@pytest.mark.asyncio
async def test_fetch_returns_none_on_error():
    """Mock httpx to raise an HTTPError; result should be None."""
    import httpx

    fetcher = PriceFetcher(rpc_url="https://fake-rpc.example.com")
    fetcher.client.get = AsyncMock(side_effect=httpx.HTTPError("connection failed"))

    result = await fetcher.get_orca_price("SOL", "USDC", 1.0)
    assert result is None

    result = await fetcher.get_raydium_price("SOL", "USDC", 1.0)
    assert result is None

    await fetcher.close()


@pytest.mark.asyncio
async def test_get_all_prices_returns_quotes():
    """Mock internal liquidity-aware methods and verify get_all_prices returns correct quotes."""
    fetcher = PriceFetcher(rpc_url="https://fake-rpc.example.com")

    with (
        patch.object(fetcher, "_get_orca_price_with_liquidity", new_callable=AsyncMock) as mock_orca,
        patch.object(fetcher, "get_raydium_price", new_callable=AsyncMock) as mock_ray,
        patch.object(fetcher, "_get_meteora_price_with_liquidity", new_callable=AsyncMock) as mock_met,
        patch.object(fetcher, "get_lifinity_price", new_callable=AsyncMock) as mock_lif,
    ):
        mock_orca.return_value = (145.0, 5000000.0)
        mock_ray.return_value = 146.5
        mock_met.return_value = None
        mock_lif.return_value = None

        quotes = await fetcher.get_all_prices("SOL", "USDC", 1.0)

    assert len(quotes) == 2
    dexes = {q.dex for q in quotes}
    assert dexes == {"orca", "raydium"}

    orca_q = next(q for q in quotes if q.dex == "orca")
    assert orca_q.input_token == "SOL"
    assert orca_q.output_token == "USDC"
    assert orca_q.output_amount == 145.0
    assert orca_q.liquidity == 5000000.0

    ray_q = next(q for q in quotes if q.dex == "raydium")
    assert ray_q.output_amount == 146.5

    await fetcher.close()


@pytest.mark.asyncio
async def test_fetch_meteora_quote():
    """Mock httpx client.get to return a valid Meteora DLMM pool response."""
    fetcher = PriceFetcher(rpc_url="https://fake-rpc.example.com")

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "total": 1,
        "pages": 1,
        "current_page": 1,
        "page_size": 10,
        "data": [
            {
                "address": "BGm1tav58oGcsQJehL9WXBFXF7D27vZsKefj4xJKD5Y",
                "name": "SOL-USDC",
                "current_price": 145.5,
                "tvl": 5600000,
                "token_x": {
                    "address": TOKEN_MINTS["SOL"],
                    "symbol": "SOL",
                    "decimals": 9,
                },
                "token_y": {
                    "address": TOKEN_MINTS["USDC"],
                    "symbol": "USDC",
                    "decimals": 6,
                },
            }
        ],
    }
    mock_response.raise_for_status = MagicMock()

    fetcher.client.get = AsyncMock(return_value=mock_response)

    result = await fetcher.get_meteora_price("SOL", "USDC", 1.0)

    assert result is not None
    assert result == pytest.approx(145.5, rel=0.01)
    await fetcher.close()


@pytest.mark.asyncio
async def test_fetch_meteora_reverse_pool():
    """Meteora pool may have tokens in reverse order."""
    fetcher = PriceFetcher(rpc_url="https://fake-rpc.example.com")

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "total": 1,
        "pages": 1,
        "current_page": 1,
        "page_size": 10,
        "data": [
            {
                "address": "FakePoolAddress",
                "name": "USDC-SOL",
                "current_price": 0.006897,  # USDC per SOL inverted
                "token_x": {
                    "address": TOKEN_MINTS["USDC"],
                    "symbol": "USDC",
                    "decimals": 6,
                },
                "token_y": {
                    "address": TOKEN_MINTS["SOL"],
                    "symbol": "SOL",
                    "decimals": 9,
                },
            }
        ],
    }
    mock_response.raise_for_status = MagicMock()

    fetcher.client.get = AsyncMock(return_value=mock_response)

    result = await fetcher.get_meteora_price("SOL", "USDC", 1.0)

    assert result is not None
    # 1 / 0.006897 ≈ 145
    assert result == pytest.approx(145.0, rel=0.01)
    await fetcher.close()


@pytest.mark.asyncio
async def test_fetch_lifinity_quote():
    """Mock httpx client.get to return a valid Lifinity pool response."""
    fetcher = PriceFetcher(rpc_url="https://fake-rpc.example.com")

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": [
            {
                "pool": "FakeLifinityPool",
                "tokenA": TOKEN_MINTS["SOL"],
                "tokenB": TOKEN_MINTS["USDC"],
                "price": "144.8",
            }
        ]
    }
    mock_response.raise_for_status = MagicMock()

    fetcher.client.get = AsyncMock(return_value=mock_response)

    result = await fetcher.get_lifinity_price("SOL", "USDC", 1.0)

    assert result is not None
    assert result == pytest.approx(144.8, rel=0.01)
    await fetcher.close()


@pytest.mark.asyncio
async def test_fetch_lifinity_returns_none_on_unavailable():
    """Lifinity API is not publicly available; should gracefully return None."""
    import httpx

    fetcher = PriceFetcher(rpc_url="https://fake-rpc.example.com")
    fetcher.client.get = AsyncMock(side_effect=httpx.HTTPError("connection failed"))

    result = await fetcher.get_lifinity_price("SOL", "USDC", 1.0)
    assert result is None
    await fetcher.close()


@pytest.mark.asyncio
async def test_fetch_meteora_returns_none_on_error():
    """Meteora should gracefully return None on error."""
    import httpx

    fetcher = PriceFetcher(rpc_url="https://fake-rpc.example.com")
    fetcher.client.get = AsyncMock(side_effect=httpx.HTTPError("connection failed"))

    result = await fetcher.get_meteora_price("SOL", "USDC", 1.0)
    assert result is None
    await fetcher.close()


@pytest.mark.asyncio
async def test_get_all_prices_includes_all_dexes():
    """Verify get_all_prices returns quotes from all 4 DEXes when available."""
    fetcher = PriceFetcher(rpc_url="https://fake-rpc.example.com")

    with (
        patch.object(fetcher, "_get_orca_price_with_liquidity", new_callable=AsyncMock) as mock_orca,
        patch.object(fetcher, "get_raydium_price", new_callable=AsyncMock) as mock_ray,
        patch.object(fetcher, "_get_meteora_price_with_liquidity", new_callable=AsyncMock) as mock_met,
        patch.object(fetcher, "get_lifinity_price", new_callable=AsyncMock) as mock_lif,
    ):
        mock_orca.return_value = (145.0, 5_000_000.0)
        mock_ray.return_value = 146.5
        mock_met.return_value = (145.5, 2_000_000.0)
        mock_lif.return_value = 144.8

        quotes = await fetcher.get_all_prices("SOL", "USDC", 1.0)

    assert len(quotes) == 4
    dexes = {q.dex for q in quotes}
    assert dexes == {"orca", "raydium", "meteora", "lifinity"}

    meteora_q = next(q for q in quotes if q.dex == "meteora")
    assert meteora_q.output_amount == 145.5
    assert meteora_q.liquidity == 2_000_000.0

    lifinity_q = next(q for q in quotes if q.dex == "lifinity")
    assert lifinity_q.output_amount == 144.8
    assert lifinity_q.liquidity == 0.0

    await fetcher.close()


def test_price_quote_dataclass():
    """Create a PriceQuote and verify all fields are set correctly."""
    quote = PriceQuote(
        dex="orca",
        input_token="SOL",
        output_token="USDC",
        input_amount=1.0,
        output_amount=145.0,
        price=145.0,
    )

    assert quote.dex == "orca"
    assert quote.input_token == "SOL"
    assert quote.output_token == "USDC"
    assert quote.input_amount == 1.0
    assert quote.output_amount == 145.0
    assert quote.price == 145.0
