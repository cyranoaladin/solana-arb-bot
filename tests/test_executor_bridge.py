"""Tests for the Python-Rust executor bridge."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from detector.executor_bridge import ExecutorBridge


@pytest.fixture
def bridge():
    return ExecutorBridge(
        executor_path="/fake/executor",
        rpc_url="https://fake-rpc.example.com",
        keypair_path="/fake/wallet.json",
    )


def test_parse_valid_json(bridge):
    raw = json.dumps({"status": "ok", "tx_hash": "abc123"})
    result = bridge._parse_response(raw)
    assert result == {"status": "ok", "tx_hash": "abc123"}


def test_parse_invalid_json(bridge):
    result = bridge._parse_response("this is not json at all")
    assert result["status"] == "error"
    assert "message" in result


@pytest.mark.asyncio
async def test_swap_dry_run(bridge):
    fake_output = json.dumps({"status": "ok", "tx_hash": "dry_abc"})
    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (fake_output.encode(), b"")
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
        result = await bridge.swap(
            from_token="SOL",
            to_token="USDC",
            amount=0.05,
            dex="jupiter",
            min_out=7.5,
            dry_run=True,
        )

    # Verify the CLI args include --dry-run
    call_args = mock_exec.call_args[0]
    assert call_args[0] == "/fake/executor"
    assert "swap" in call_args
    assert "--dry-run" in call_args
    assert result["status"] == "ok"
    assert result["tx_hash"] == "dry_abc"


@pytest.mark.asyncio
async def test_get_balance_returns_float(bridge):
    fake_output = json.dumps({"balance": 1.234})
    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (fake_output.encode(), b"")
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
        balance = await bridge.get_balance()

    assert isinstance(balance, float)
    assert balance == 1.234
