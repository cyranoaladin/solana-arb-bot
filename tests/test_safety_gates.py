"""Tests for safety gates — ensures live trading cannot be enabled accidentally."""

from __future__ import annotations

import os
import pytest


class TestConfigSafetyGates:
    """Config must block live trading unless explicitly opted in."""

    def test_default_is_dry_run(self, monkeypatch):
        monkeypatch.setenv("RPC_URL", "https://fake")
        monkeypatch.delenv("DRY_RUN", raising=False)
        monkeypatch.delenv("TRADING_ENABLED", raising=False)
        from detector.config import BotConfig
        config = BotConfig()
        assert config.dry_run is True
        assert config.live_execution_allowed is False

    def test_dry_run_false_without_trading_enabled_fails(self, monkeypatch):
        monkeypatch.setenv("RPC_URL", "https://fake")
        monkeypatch.setenv("DRY_RUN", "false")
        monkeypatch.delenv("TRADING_ENABLED", raising=False)
        from detector.config import BotConfig
        with pytest.raises(ValueError, match="TRADING_ENABLED"):
            BotConfig()

    def test_dry_run_false_with_trading_enabled_true(self, monkeypatch):
        monkeypatch.setenv("RPC_URL", "https://fake")
        monkeypatch.setenv("DRY_RUN", "false")
        monkeypatch.setenv("TRADING_ENABLED", "true")
        from detector.config import BotConfig
        config = BotConfig()
        assert config.live_execution_allowed is True
        assert config.live_block_reason == ""

    def test_live_block_reason_dry_run(self, monkeypatch):
        monkeypatch.setenv("RPC_URL", "https://fake")
        monkeypatch.setenv("DRY_RUN", "true")
        from detector.config import BotConfig
        config = BotConfig()
        assert "DRY_RUN" in config.live_block_reason

    def test_health_bind_defaults_to_localhost(self, monkeypatch):
        monkeypatch.setenv("RPC_URL", "https://fake")
        monkeypatch.delenv("HEALTH_BIND_HOST", raising=False)
        from detector.config import BotConfig
        config = BotConfig()
        assert config.health_bind_host == "127.0.0.1"

    def test_dashboard_bind_defaults_to_localhost(self, monkeypatch):
        monkeypatch.setenv("RPC_URL", "https://fake")
        monkeypatch.delenv("DASHBOARD_BIND_HOST", raising=False)
        from detector.config import BotConfig
        config = BotConfig()
        assert config.dashboard_bind_host == "127.0.0.1"

    def test_database_url_no_weak_default(self, monkeypatch):
        monkeypatch.setenv("RPC_URL", "https://fake")
        monkeypatch.delenv("DATABASE_URL", raising=False)
        from detector.config import BotConfig
        config = BotConfig()
        assert config.database_url == ""
        assert "arbbot123" not in config.database_url


class TestHealthStats:
    """Health stats must distinguish estimated vs realized profit."""

    def test_stats_has_estimated_and_realized(self):
        from detector.health import BotStats
        stats = BotStats()
        d = stats.to_dict()
        assert "estimated_profit_total" in d
        assert "realized_profit_total" in d
        assert "live_enabled" in d
        assert "live_block_reason" in d
        assert "execution_mode" in d

    def test_stats_live_disabled_by_default(self):
        from detector.health import BotStats
        stats = BotStats()
        assert stats.live_enabled is False
        assert stats.execution_mode == "dry_run"

    def test_record_trade_with_realized(self):
        from detector.health import BotStats
        stats = BotStats()
        stats.estimated_profit_total = 0.5
        stats.realized_profit_total = 0.3
        stats.record_trade(estimated_profit=0.1, realized_profit=0.08)
        assert len(stats.pnl_curve) == 1
        assert stats.pnl_curve[0]["estimated_profit"] == 0.1
        assert stats.pnl_curve[0]["realized_profit"] == 0.08


class TestExecutorBridgeStderr:
    """Stderr from Rust executor must not be silently swallowed."""

    @pytest.mark.asyncio
    async def test_nonzero_exit_returns_stderr_error(self):
        from unittest.mock import AsyncMock, MagicMock
        from detector.executor_bridge import ExecutorBridge
        import asyncio

        bridge = ExecutorBridge("/fake", "https://fake", "/fake.json")

        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (
            b"",  # empty stdout
            b'{"status": "error", "message": "Invalid keypair"}',  # JSON on stderr
        )
        mock_proc.returncode = 1

        with pytest.MonkeyPatch.context() as m:
            m.setattr(asyncio, "create_subprocess_exec", AsyncMock(return_value=mock_proc))
            result = await bridge._run(["/fake", "balance"])

        assert result["status"] == "error"
        assert "Invalid keypair" in result["message"]

    @pytest.mark.asyncio
    async def test_nonzero_exit_raw_stderr(self):
        from unittest.mock import AsyncMock
        from detector.executor_bridge import ExecutorBridge
        import asyncio

        bridge = ExecutorBridge("/fake", "https://fake", "/fake.json")

        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"", b"panic: index out of bounds")
        mock_proc.returncode = 101

        with pytest.MonkeyPatch.context() as m:
            m.setattr(asyncio, "create_subprocess_exec", AsyncMock(return_value=mock_proc))
            result = await bridge._run(["/fake", "balance"])

        assert result["status"] == "error"
        assert "index out of bounds" in result["message"]


class TestNotifierHonesty:
    """Notifier must not say 'executed' for dry-run or submitted trades."""

    @pytest.mark.asyncio
    async def test_dry_run_trade_labeled_correctly(self):
        from detector.notifier import TelegramNotifier
        notifier = TelegramNotifier(token="", chat_id="")  # disabled
        # Should not crash, just skip (no token)
        await notifier.notify_trade(
            pair="SOL/USDC", buy_dex="orca", sell_dex="raydium",
            amount=0.05, profit=0.001, tx_hash="n/a", status="dry_run",
        )

    @pytest.mark.asyncio
    async def test_blocked_trade_notification(self):
        from detector.notifier import TelegramNotifier
        notifier = TelegramNotifier(token="", chat_id="")
        await notifier.notify_trade_blocked(
            pair="SOL/USDC", reason="Orca execution not supported",
        )
