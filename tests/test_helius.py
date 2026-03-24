"""Tests for the Helius client module."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from detector.helius import HeliusClient


@pytest.mark.asyncio
async def test_get_priority_fee_success():
    client = HeliusClient(rpc_url="https://fake-rpc.example.com")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "jsonrpc": "2.0",
        "result": {"priorityFeeEstimate": 150000},
        "id": "fee-estimate",
    }
    mock_resp.raise_for_status = MagicMock()
    client.client.post = AsyncMock(return_value=mock_resp)

    fee = await client.get_priority_fee()
    assert fee == 150000
    await client.close()


@pytest.mark.asyncio
async def test_get_priority_fee_fallback_on_error():
    import httpx
    client = HeliusClient(rpc_url="https://fake-rpc.example.com")
    client.client.post = AsyncMock(side_effect=httpx.HTTPError("timeout"))

    fee = await client.get_priority_fee()
    assert fee == 500_000  # fallback
    await client.close()


@pytest.mark.asyncio
async def test_simulate_transaction_success():
    client = HeliusClient(rpc_url="https://fake-rpc.example.com")
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "jsonrpc": "2.0",
        "result": {"value": {"err": None, "logs": ["Program log: success"]}},
    }
    mock_resp.raise_for_status = MagicMock()
    client.client.post = AsyncMock(return_value=mock_resp)

    result = await client.simulate_transaction("base64tx")
    assert result["success"] is True
    assert result["error"] is None
    await client.close()


@pytest.mark.asyncio
async def test_simulate_transaction_failure():
    client = HeliusClient(rpc_url="https://fake-rpc.example.com")
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "jsonrpc": "2.0",
        "result": {"value": {"err": {"InstructionError": [0, "Custom"]}, "logs": []}},
    }
    mock_resp.raise_for_status = MagicMock()
    client.client.post = AsyncMock(return_value=mock_resp)

    result = await client.simulate_transaction("base64tx")
    assert result["success"] is False
    assert "InstructionError" in result["error"]
    await client.close()
