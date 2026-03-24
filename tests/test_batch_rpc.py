"""Tests for the batch RPC client."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from detector.batch_rpc import BatchRPCClient


@pytest.fixture
def client():
    return BatchRPCClient("https://fake-rpc.example.com")


@pytest.mark.asyncio
async def test_batch_call_single(client):
    mock_resp = MagicMock()
    mock_resp.json.return_value = [
        {"jsonrpc": "2.0", "id": 1, "result": {"value": 5000000000}},
    ]
    mock_resp.raise_for_status = MagicMock()
    client.client.post = AsyncMock(return_value=mock_resp)

    results = await client.batch_call([("getBalance", ["pubkey1"])])
    assert len(results) == 1
    assert results[0]["result"]["value"] == 5000000000
    await client.close()


@pytest.mark.asyncio
async def test_batch_call_multiple(client):
    mock_resp = MagicMock()
    mock_resp.json.return_value = [
        {"jsonrpc": "2.0", "id": 1, "result": {"value": 1000000000}},
        {"jsonrpc": "2.0", "id": 2, "result": {"value": 2000000000}},
    ]
    mock_resp.raise_for_status = MagicMock()
    client.client.post = AsyncMock(return_value=mock_resp)

    results = await client.batch_call([
        ("getBalance", ["pk1"]),
        ("getBalance", ["pk2"]),
    ])
    assert len(results) == 2
    assert results[0]["result"]["value"] == 1000000000
    assert results[1]["result"]["value"] == 2000000000
    await client.close()


@pytest.mark.asyncio
async def test_get_multiple_balances(client):
    mock_resp = MagicMock()
    mock_resp.json.return_value = [
        {"jsonrpc": "2.0", "id": 1, "result": {"value": 3000000000}},
        {"jsonrpc": "2.0", "id": 2, "result": {"value": 500000000}},
    ]
    mock_resp.raise_for_status = MagicMock()
    client.client.post = AsyncMock(return_value=mock_resp)

    balances = await client.get_multiple_balances(["pk1", "pk2"])
    assert balances["pk1"] == 3.0
    assert balances["pk2"] == 0.5
    await client.close()


@pytest.mark.asyncio
async def test_batch_empty(client):
    results = await client.batch_call([])
    assert results == []
    await client.close()


@pytest.mark.asyncio
async def test_batch_call_error_handling(client):
    import httpx
    client.client.post = AsyncMock(side_effect=httpx.HTTPError("timeout"))

    results = await client.batch_call([("getBalance", ["pk1"])])
    assert len(results) == 1
    assert "error" in results[0]
    await client.close()
