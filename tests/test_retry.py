"""Tests for swap retry with exponential backoff."""
import pytest
from unittest.mock import AsyncMock, patch
from detector.executor_bridge import ExecutorBridge


@pytest.fixture
def bridge():
    return ExecutorBridge("/fake/executor", "https://fake-rpc", "/fake/keypair.json")


@pytest.mark.asyncio
async def test_swap_succeeds_first_try(bridge):
    bridge.swap = AsyncMock(return_value={"status": "ok", "tx_hash": "abc123"})
    result = await bridge.swap_with_retry("SOL", "USDC", 0.05, "raydium", 4.5)
    assert result["status"] == "ok"
    assert bridge.swap.call_count == 1


@pytest.mark.asyncio
async def test_swap_retries_on_transient_error(bridge):
    bridge.swap = AsyncMock(side_effect=[
        {"status": "error", "message": "RPC timeout"},
        {"status": "error", "message": "connection reset"},
        {"status": "ok", "tx_hash": "abc123"},
    ])
    result = await bridge.swap_with_retry("SOL", "USDC", 0.05, "raydium", 4.5,
                                           max_retries=3, base_delay=0.01)
    assert result["status"] == "ok"
    assert bridge.swap.call_count == 3


@pytest.mark.asyncio
async def test_swap_no_retry_on_business_error(bridge):
    bridge.swap = AsyncMock(return_value={"status": "error", "message": "InsufficientFunds"})
    result = await bridge.swap_with_retry("SOL", "USDC", 0.05, "raydium", 4.5,
                                           max_retries=3, base_delay=0.01)
    assert result["status"] == "error"
    assert bridge.swap.call_count == 1  # no retry


@pytest.mark.asyncio
async def test_swap_max_retries_exceeded(bridge):
    bridge.swap = AsyncMock(return_value={"status": "error", "message": "network error"})
    result = await bridge.swap_with_retry("SOL", "USDC", 0.05, "raydium", 4.5,
                                           max_retries=2, base_delay=0.01)
    assert result["status"] == "error"
    assert bridge.swap.call_count == 3  # initial + 2 retries
