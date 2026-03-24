"""Tests for the health check module."""

from __future__ import annotations

from detector.health import BotStats


def test_bot_stats_to_dict():
    stats = BotStats(dry_run=True)
    stats.balance_sol = 1.5
    stats.trades_total = 10
    stats.profit_total = 0.001234

    d = stats.to_dict()
    assert d["status"] == "running"
    assert d["dry_run"] is True
    assert d["balance_sol"] == 1.5
    assert d["trades_total"] == 10
    assert d["profit_total"] == 0.001234
    assert "uptime_sec" in d


def test_bot_stats_paused():
    stats = BotStats()
    stats.paused = True
    d = stats.to_dict()
    assert d["status"] == "paused"
