"""Tests for MCP tool dispatch (arb_control_mcp._dispatch)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from detector.arb_control_mcp import _dispatch, set_bot_state, _bot_state
from detector.health import BotStats
from detector.arbitrage import ArbitrageDetector, VolatilityTracker
from detector.trader_stats import TraderStats


@pytest.fixture(autouse=True)
def _setup_bot_state():
    """Provide a fresh bot state for every test."""
    stats = BotStats()
    config = MagicMock()
    config.trade_amount_sol = 0.05
    config.max_slippage_pct = 0.5
    config.poll_interval_sec = 3
    config.min_profit_pct = 0.1
    config.dry_run = True

    detector = ArbitrageDetector(min_profit_pct=0.1)
    vol_tracker = VolatilityTracker()
    trader_stats = TraderStats()

    set_bot_state(
        stats=stats,
        config=config,
        detector=detector,
        vol_tracker=vol_tracker,
        notifier=MagicMock(),
        trader_stats=trader_stats,
    )
    yield
    # cleanup
    _bot_state.clear()


def _stats() -> BotStats:
    return _bot_state["stats"]


def _config():
    return _bot_state["config"]


# ---------- 5. test_mcp_get_live_state ----------

@pytest.mark.asyncio
async def test_mcp_get_live_state() -> None:
    result = await _dispatch("get_live_state", {})
    assert "status" in result
    assert "uptime_sec" in result
    assert "dry_run" in result
    assert "balance_sol" in result


# ---------- 6. test_mcp_get_session_stats ----------

@pytest.mark.asyncio
async def test_mcp_get_session_stats() -> None:
    result = await _dispatch("get_session_stats", {})
    assert "volatility" in result
    assert "adaptive_min_profit_pct" in result
    assert "price_samples" in result


# ---------- 7. test_mcp_set_param_valid ----------

@pytest.mark.asyncio
async def test_mcp_set_param_valid() -> None:
    result = await _dispatch("set_param", {"name": "min_profit_pct", "value": 0.5})
    assert result["ok"] is True
    assert result["value"] == 0.5
    assert _bot_state["detector"].min_profit_pct == 0.5


# ---------- 8. test_mcp_set_param_out_of_range ----------

@pytest.mark.asyncio
async def test_mcp_set_param_out_of_range() -> None:
    result = await _dispatch("set_param", {"name": "min_profit_pct", "value": 100.0})
    assert "error" in result
    assert "out of range" in result["error"]


# ---------- 9. test_mcp_set_param_unknown ----------

@pytest.mark.asyncio
async def test_mcp_set_param_unknown() -> None:
    result = await _dispatch("set_param", {"name": "unknown_param", "value": 1.0})
    assert "error" in result
    assert "Unknown param" in result["error"]


# ---------- 10. test_mcp_pause_resume ----------

@pytest.mark.asyncio
async def test_mcp_pause_resume() -> None:
    result = await _dispatch("pause_trading", {})
    assert result["paused"] is True
    assert _stats().paused is True

    result = await _dispatch("resume_trading", {})
    assert result["paused"] is False
    assert _stats().paused is False


# ---------- 11. test_mcp_force_dry_run ----------

@pytest.mark.asyncio
async def test_mcp_force_dry_run() -> None:
    result = await _dispatch("force_dry_run", {"enable": True})
    assert result["dry_run"] is True
    assert _stats().dry_run is True

    result = await _dispatch("force_dry_run", {"enable": False})
    assert result["dry_run"] is False
    assert _stats().dry_run is False


# ---------- 12. test_mcp_set_ai_provider ----------

@pytest.mark.asyncio
async def test_mcp_set_ai_provider() -> None:
    with patch("detector.arb_control_mcp.nr", create=True) as _:
        # The dispatch does: import detector.nightly_report as nr; nr.ai_provider = ...
        import detector.nightly_report as nr

        result = await _dispatch("set_ai_provider", {"provider": "anthropic"})
        assert result["ok"] is True
        assert result["ai_provider"] == "anthropic"
        assert nr.ai_provider == "anthropic"

        result = await _dispatch("set_ai_provider", {"provider": "ollama"})
        assert result["ok"] is True
        assert result["ai_provider"] == "ollama"
        assert nr.ai_provider == "ollama"

        result = await _dispatch("set_ai_provider", {"provider": "invalid"})
        assert "error" in result


# ---------- 13. test_mcp_get_pnl_curve_empty ----------

@pytest.mark.asyncio
async def test_mcp_get_pnl_curve_empty() -> None:
    result = await _dispatch("get_pnl_curve", {})
    assert result["pnl_curve"] == []
    assert result["count"] == 0


# ---------- 14. test_mcp_get_pnl_curve_with_data ----------

@pytest.mark.asyncio
async def test_mcp_get_pnl_curve_with_data() -> None:
    stats = _stats()
    stats.profit_total = 0.0001
    stats.record_trade(0.0001)
    stats.profit_total = 0.0003
    stats.record_trade(0.0002)
    stats.profit_total = 0.0006
    stats.record_trade(0.0003)

    result = await _dispatch("get_pnl_curve", {})
    assert result["count"] == 3
    assert len(result["pnl_curve"]) == 3
    assert "ts" in result["pnl_curve"][0]
    assert "profit" in result["pnl_curve"][0]
    assert "cumulative" in result["pnl_curve"][0]


# ---------- 15. test_mcp_get_opportunities ----------

@pytest.mark.asyncio
async def test_mcp_get_opportunities() -> None:
    result = await _dispatch("get_opportunities", {})
    assert "opportunities" in result
    assert isinstance(result["opportunities"], list)


# ---------- 16. test_mcp_get_trader_stats ----------

@pytest.mark.asyncio
async def test_mcp_get_trader_stats() -> None:
    ts = _bot_state["trader_stats"]
    ts.record_trade("SOL/USDC", "raydium", "orca", 0.15, 0.0001, success=True)
    ts.record_trade("SOL/USDC", "orca", "raydium", 0.10, 0.00005, success=True)

    result = await _dispatch("get_trader_stats", {})
    assert "total_trades" in result
    assert result["total_trades"] == 2
    assert "win_rate" in result
    assert "sharpe_ratio" in result
    assert "best_hours" in result
    assert "best_dex_routes" in result


# ---------- 17. test_mcp_get_market_context ----------

@pytest.mark.asyncio
async def test_mcp_get_market_context() -> None:
    mock_dex_tvls = {"raydium": {"name": "Raydium", "tvl": 500_000_000}}
    mock_solana_tvl = 12_000_000_000.0

    instance = AsyncMock()
    instance.get_dex_tvl_comparison.return_value = mock_dex_tvls
    instance.get_solana_tvl.return_value = mock_solana_tvl
    instance.close = AsyncMock()

    # _dispatch does `from detector.defillama import DeFiLlamaClient` locally
    with patch("detector.defillama.DeFiLlamaClient", return_value=instance):
        result = await _dispatch("get_market_context", {})

    assert "solana_chain_tvl" in result
    assert "dex_tvls" in result
    assert result["solana_chain_tvl"] == mock_solana_tvl
    assert result["dex_tvls"] == mock_dex_tvls


# ---------- 18. test_mcp_db_tools_graceful_without_db ----------

@pytest.mark.asyncio
async def test_mcp_db_tools_graceful_without_db() -> None:
    # Patch TradeDB so it never connects to a real DB
    mock_db = MagicMock()
    mock_db.get_stats_by_hour.return_value = []
    mock_db.get_recent_trades.return_value = []

    with patch("detector.db.TradeDB", return_value=mock_db):
        result1 = await _dispatch("db_stats_by_hour", {})
        assert result1["hourly_stats"] == []

        result2 = await _dispatch("db_recent_trades", {"limit": 5})
        assert result2["trades"] == []


# ---------- 19. test_mcp_unknown_tool ----------

@pytest.mark.asyncio
async def test_mcp_unknown_tool() -> None:
    result = await _dispatch("nonexistent_tool", {})
    assert "error" in result
    assert "Unknown tool" in result["error"]
