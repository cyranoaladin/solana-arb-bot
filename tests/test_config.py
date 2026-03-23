"""Tests for BotConfig dataclass."""

import pytest

from detector.config import BotConfig


def test_config_loads_defaults():
    """BotConfig should populate sensible defaults for optional fields."""
    cfg = BotConfig(rpc_url="https://rpc.example.com", keypair_path="./wallet.json")
    assert cfg.trade_amount_sol == 0.05
    assert cfg.min_profit_pct == 0.1
    assert cfg.max_slippage_pct == 0.5
    assert cfg.kill_switch_sol == 0.05
    assert cfg.poll_interval_sec == 3
    assert cfg.executor_path == "./executor/target/release/executor"


def test_config_rejects_negative_trade_amount():
    """BotConfig should raise ValueError when trade_amount_sol is negative."""
    with pytest.raises(ValueError, match="trade_amount_sol"):
        BotConfig(rpc_url="https://rpc.example.com", trade_amount_sol=-1.0)


def test_config_rejects_empty_rpc_url():
    """BotConfig should raise ValueError when rpc_url is empty."""
    with pytest.raises(ValueError, match="rpc_url"):
        BotConfig(rpc_url="")


def test_config_dry_run_default_true():
    """dry_run should default to True."""
    cfg = BotConfig(rpc_url="https://rpc.example.com")
    assert cfg.dry_run is True
