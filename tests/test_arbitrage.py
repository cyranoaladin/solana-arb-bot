"""Tests for the arbitrage detection engine."""

from __future__ import annotations

import pytest

from detector.arbitrage import ArbitrageDetector, Opportunity, PriceQuote


def _make_quote(dex: str, output_amount: float) -> PriceQuote:
    """Helper to build a PriceQuote with sensible defaults."""
    return PriceQuote(
        dex=dex,
        input_token="SOL",
        output_token="USDC",
        input_amount=1.0,
        output_amount=output_amount,
        price=output_amount,
    )


def test_detect_profitable_opportunity():
    """2 quotes with >0.1% spread should yield 1 opportunity."""
    detector = ArbitrageDetector(min_profit_pct=0.1)
    quotes = [
        _make_quote("jupiter", 100.0),
        _make_quote("raydium", 100.5),
    ]
    opps = detector.find_opportunities(quotes)

    assert len(opps) == 1
    assert opps[0].buy_dex == "jupiter"
    assert opps[0].sell_dex == "raydium"


def test_no_opportunity_when_spread_too_small():
    """2 quotes with tiny spread (<0.1%) should yield 0 opportunities."""
    detector = ArbitrageDetector(min_profit_pct=0.1)
    quotes = [
        _make_quote("jupiter", 100.0),
        _make_quote("raydium", 100.05),
    ]
    opps = detector.find_opportunities(quotes)

    assert len(opps) == 0


def test_no_opportunity_with_single_quote():
    """1 quote should yield 0 opportunities (need at least 2)."""
    detector = ArbitrageDetector(min_profit_pct=0.1)
    quotes = [_make_quote("jupiter", 100.0)]
    opps = detector.find_opportunities(quotes)

    assert len(opps) == 0


def test_opportunities_sorted_by_profit():
    """3 quotes creating 2 opportunities should be sorted highest profit first."""
    detector = ArbitrageDetector(min_profit_pct=0.1)
    quotes = [
        _make_quote("jupiter", 100.0),
        _make_quote("raydium", 100.2),   # 0.2% spread vs jupiter
        _make_quote("orca", 101.0),       # 1.0% spread vs jupiter
    ]
    opps = detector.find_opportunities(quotes)

    assert len(opps) >= 2
    assert opps[0].profit_pct >= opps[1].profit_pct


def test_profit_calculation_correct():
    """Verify profit_pct math: (spread / buy.output_amount) * 100."""
    detector = ArbitrageDetector(min_profit_pct=0.1)
    quotes = [
        _make_quote("jupiter", 200.0),
        _make_quote("raydium", 201.0),
    ]
    opps = detector.find_opportunities(quotes)

    assert len(opps) == 1
    expected_spread = 201.0 - 200.0
    expected_pct = (expected_spread / 200.0) * 100  # 0.5%
    assert opps[0].profit_pct == pytest.approx(expected_pct, rel=1e-6)
    assert opps[0].estimated_profit == pytest.approx(expected_spread, rel=1e-6)
