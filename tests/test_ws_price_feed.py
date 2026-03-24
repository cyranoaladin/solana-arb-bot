"""Tests for WebSocket price feed module."""

from __future__ import annotations

import pytest

from detector.ws_price_feed import PriceCache


def test_price_cache_update_and_get():
    """Update cache with a single DEX price, verify get_quotes returns correct data."""
    cache = PriceCache()
    cache.update("SOL/USDC", "orca", 150.0)

    quotes = cache.get_quotes("SOL", "USDC", 2.0)
    assert len(quotes) == 1
    q = quotes[0]
    assert q.dex == "orca"
    assert q.input_token == "SOL"
    assert q.output_token == "USDC"
    assert q.input_amount == 2.0
    assert q.output_amount == pytest.approx(300.0)
    assert q.price == pytest.approx(150.0)


def test_price_cache_multiple_dexes():
    """Update cache from 2 DEXes, verify both are returned."""
    cache = PriceCache()
    cache.update("SOL/USDC", "orca", 150.0)
    cache.update("SOL/USDC", "raydium", 151.0)

    quotes = cache.get_quotes("SOL", "USDC", 1.0)
    assert len(quotes) == 2
    dexes = {q.dex for q in quotes}
    assert dexes == {"orca", "raydium"}

    by_dex = {q.dex: q for q in quotes}
    assert by_dex["orca"].output_amount == pytest.approx(150.0)
    assert by_dex["raydium"].output_amount == pytest.approx(151.0)


def test_price_cache_empty_pair():
    """get_quotes on unknown pair returns empty list."""
    cache = PriceCache()
    quotes = cache.get_quotes("SOL", "USDT", 1.0)
    assert quotes == []


def test_price_cache_overwrites_old_value():
    """Updating same dex replaces the previous price."""
    cache = PriceCache()
    cache.update("SOL/USDC", "orca", 100.0)
    cache.update("SOL/USDC", "orca", 200.0)

    quotes = cache.get_quotes("SOL", "USDC", 1.0)
    assert len(quotes) == 1
    assert quotes[0].price == pytest.approx(200.0)


def test_price_cache_last_update_ts():
    """Timestamps are recorded on update."""
    cache = PriceCache()
    cache.update("SOL/USDC", "orca", 150.0)
    assert "SOL/USDC:orca" in cache.last_update_ts
    assert cache.last_update_ts["SOL/USDC:orca"] > 0
