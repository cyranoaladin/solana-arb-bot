"""Tests for the backtesting engine."""
from __future__ import annotations
import json
import tempfile
import pytest
from detector.backtester import run_backtest, load_price_jsonl, generate_sample_data, BacktestResult


def _make_tick(ts, orca_price, ray_price, amount=0.05):
    """Generate two price rows (orca + raydium) for a given timestamp."""
    return [
        {"timestamp": ts, "dex": "orca", "input_token": "SOL", "output_token": "USDC",
         "input_amount": amount, "output_amount": amount * orca_price, "price": orca_price},
        {"timestamp": ts, "dex": "raydium", "input_token": "SOL", "output_token": "USDC",
         "input_amount": amount, "output_amount": amount * ray_price, "price": ray_price},
    ]


def test_backtest_no_opportunities():
    """Same prices on both DEXes = no trades."""
    data = _make_tick("2026-03-01T00:00:00+00:00", 91.5, 91.5)
    result = run_backtest(data, min_profit_pct=0.1)
    assert result.total_trades == 0
    assert result.net_profit == 0.0


def test_backtest_finds_opportunity():
    """Large spread should trigger a trade."""
    data = _make_tick("2026-03-01T00:00:00+00:00", 90.0, 92.0)
    result = run_backtest(data, min_profit_pct=0.1, use_adaptive_thresholds=False)
    assert result.total_trades >= 1
    assert result.total_profit > 0


def test_backtest_hourly_distribution():
    """Trades at different hours should be tracked."""
    data = (
        _make_tick("2026-03-01T02:00:00+00:00", 90.0, 93.0)
        + _make_tick("2026-03-01T14:00:00+00:00", 89.0, 94.0)
    )
    result = run_backtest(data, min_profit_pct=0.1, use_adaptive_thresholds=False)
    assert result.total_trades >= 2
    assert result.hourly_profit[2] > 0
    assert result.hourly_profit[14] > 0


def test_backtest_win_rate():
    data = _make_tick("2026-03-01T00:00:00+00:00", 90.0, 92.0)
    result = run_backtest(data, min_profit_pct=0.1, fee_per_trade_sol=0.0, use_adaptive_thresholds=False)
    assert result.win_rate == 100.0


def test_generate_sample_data():
    """Generate sample data and verify it loads."""
    import os
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        path = f.name
    try:
        generate_sample_data(path, num_ticks=50)
        data = load_price_jsonl(path)
        assert len(data) == 100  # 50 ticks * 2 DEXes
        result = run_backtest(data)
        assert isinstance(result, BacktestResult)
    finally:
        os.unlink(path)


def test_backtest_summary_format():
    data = _make_tick("2026-03-01T00:00:00+00:00", 90.0, 92.0)
    result = run_backtest(data, min_profit_pct=0.1, use_adaptive_thresholds=False)
    summary = result.summary()
    assert "Backtest Results" in summary
    assert "Total trades" in summary
    assert "Win rate" in summary
