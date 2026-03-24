"""Tests for the Pyth Network oracle module."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from detector.oracle import PythOracle


@pytest.mark.asyncio
async def test_pyth_price_parsing():
    """Mock a valid Pyth Hermes response and verify price computation."""
    oracle = PythOracle()

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "parsed": [
            {
                "id": "ef0d8b6fda2ceba41da15d4095d1da392a0d2f8ed0c6c7bc0f4cfac8c280b56d",
                "price": {
                    "price": "14500000000",
                    "conf": "5000000",
                    "expo": -8,
                    "publish_time": 1700000000,
                },
                "ema_price": {
                    "price": "14480000000",
                    "conf": "4800000",
                    "expo": -8,
                    "publish_time": 1700000000,
                },
            }
        ]
    }

    oracle.client = AsyncMock()
    oracle.client.get = AsyncMock(return_value=mock_response)

    price = await oracle.get_sol_price_usd()

    assert price is not None
    # 14500000000 * 10^-8 = 145.0
    assert price == pytest.approx(145.0)
    # Value should be cached
    assert oracle._cache["SOL/USD"] == pytest.approx(145.0)

    await oracle.close()


@pytest.mark.asyncio
async def test_divergence_detection():
    """Test check_dex_oracle_divergence with divergent and non-divergent prices."""
    oracle = PythOracle()

    # Non-divergent: DEX=145.5 vs Oracle=145.0 => 0.3448% < 1.0%
    result = await oracle.check_dex_oracle_divergence(
        dex_price=145.5, oracle_price=145.0, threshold_pct=1.0,
    )
    assert result["diverges"] is False
    assert result["divergence_pct"] == pytest.approx(0.3448, abs=0.001)

    # Divergent: DEX=150.0 vs Oracle=145.0 => 3.4483% > 1.0%
    result = await oracle.check_dex_oracle_divergence(
        dex_price=150.0, oracle_price=145.0, threshold_pct=1.0,
    )
    assert result["diverges"] is True
    assert result["divergence_pct"] == pytest.approx(3.4483, abs=0.001)

    # Edge case: invalid oracle price
    result = await oracle.check_dex_oracle_divergence(
        dex_price=145.0, oracle_price=0, threshold_pct=1.0,
    )
    assert result["diverges"] is False
    assert "error" in result

    await oracle.close()


@pytest.mark.asyncio
async def test_pyth_cache_on_error():
    """Verify cached value is returned when the API call fails."""
    oracle = PythOracle()

    # Pre-populate cache
    oracle._cache["SOL/USD"] = 142.0

    # Make the HTTP call raise an exception
    oracle.client = AsyncMock()
    oracle.client.get = AsyncMock(side_effect=Exception("network error"))

    price = await oracle.get_sol_price_usd()

    # Should return cached value
    assert price == pytest.approx(142.0)

    await oracle.close()


@pytest.mark.asyncio
async def test_unknown_feed_returns_none():
    """Requesting an unknown feed name returns None without making any HTTP call."""
    oracle = PythOracle()
    oracle.client = AsyncMock()

    price = await oracle.get_price("BTC/USD")

    assert price is None
    oracle.client.get.assert_not_called()

    await oracle.close()
