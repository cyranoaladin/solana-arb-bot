"""Tests for the arbitrage detection engine."""

from __future__ import annotations

import pytest

from detector.arbitrage import ArbitrageDetector, Opportunity, PriceQuote, VolatilityTracker


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
    """Verify profit_pct math: (net_profit / buy.output_amount) * 100."""
    detector = ArbitrageDetector(min_profit_pct=0.1, priority_fee_sol=0.0)
    quotes = [
        _make_quote("jupiter", 200.0),
        _make_quote("raydium", 201.0),
    ]
    opps = detector.find_opportunities(quotes)

    assert len(opps) == 1
    spread = 201.0 - 200.0
    # Tx fees: 2 * 0.000005 SOL = 0.00001 SOL, converted via price (200 USDC/SOL)
    fee_in_output = 0.00001 * (200.0 / 1.0)
    net_profit = spread - fee_in_output
    expected_pct = (net_profit / 200.0) * 100
    assert opps[0].profit_pct == pytest.approx(expected_pct, rel=1e-4)
    assert opps[0].estimated_profit == pytest.approx(net_profit, rel=1e-4)


# --- VolatilityTracker tests ---


def test_volatility_tracker_low_vol():
    """Stable prices should yield low volatility and low_vol_profit threshold."""
    tracker = VolatilityTracker()
    for _ in range(50):
        tracker.add_price(100.0)
    assert tracker.get_adaptive_min_profit() == tracker.low_vol_profit


def test_volatility_tracker_high_vol():
    """Wild price swings should yield high volatility and high_vol_profit threshold."""
    tracker = VolatilityTracker()
    for i in range(50):
        tracker.add_price(50.0 if i % 2 == 0 else 150.0)
    assert tracker.get_adaptive_min_profit() == tracker.high_vol_profit


def test_volatility_tracker_window():
    """Adding more than window prices should cap the list at window size."""
    tracker = VolatilityTracker(window=100)
    for i in range(150):
        tracker.add_price(float(i))
    assert len(tracker.prices) == 100
