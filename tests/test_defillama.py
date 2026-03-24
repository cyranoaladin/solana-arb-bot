import pytest
from unittest.mock import AsyncMock, MagicMock
from detector.defillama import DeFiLlamaClient


@pytest.mark.asyncio
async def test_get_protocol_tvl_success():
    client = DeFiLlamaClient()
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "name": "Raydium",
        "tvl": 500000000,
        "currentChainTvls": {"Solana": 450000000},
        "change_1d": 2.5,
        "change_7d": -1.3,
    }
    mock_resp.raise_for_status = MagicMock()
    client.client.get = AsyncMock(return_value=mock_resp)

    result = await client.get_protocol_tvl("raydium")
    assert result is not None
    assert result["name"] == "Raydium"
    assert result["tvl"] == 450000000
    await client.close()


@pytest.mark.asyncio
async def test_get_protocol_tvl_error():
    import httpx
    client = DeFiLlamaClient()
    client.client.get = AsyncMock(side_effect=httpx.HTTPError("timeout"))
    result = await client.get_protocol_tvl("raydium")
    assert result is None
    await client.close()


def test_client_instantiation():
    client = DeFiLlamaClient()
    assert client.client is not None
