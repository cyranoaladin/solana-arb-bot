"""Tests for TelegramNotifier."""

import pytest
from unittest.mock import AsyncMock, patch

from detector.notifier import TelegramNotifier


@pytest.mark.asyncio
async def test_send_trade_notification():
    notifier = TelegramNotifier(token="fake-token", chat_id="123")
    notifier._send = AsyncMock()

    await notifier.notify_trade(
        pair="SOL/USDC",
        buy_dex="Raydium",
        sell_dex="Orca",
        amount=10.0,
        profit=0.5,
        tx_hash="abc123hash",
    )

    notifier._send.assert_called_once()
    msg = notifier._send.call_args[0][0]
    assert "SOL/USDC" in msg
    assert "abc123hash" in msg


@pytest.mark.asyncio
async def test_send_alert():
    notifier = TelegramNotifier(token="fake-token", chat_id="123")
    notifier._send = AsyncMock()

    await notifier.alert("Low balance warning")

    notifier._send.assert_called_once()
    msg = notifier._send.call_args[0][0]
    assert "Low balance warning" in msg
    assert "ALERT" in msg


@pytest.mark.asyncio
async def test_send_summary():
    notifier = TelegramNotifier(token="fake-token", chat_id="123")
    notifier._send = AsyncMock()

    await notifier.summary(trades=42, total_profit=3.14, balance=100.0)

    notifier._send.assert_called_once()
    msg = notifier._send.call_args[0][0]
    assert "42" in msg


@pytest.mark.asyncio
async def test_disabled_when_no_token():
    notifier = TelegramNotifier(token="", chat_id="123")

    with patch("httpx.AsyncClient") as mock_client:
        await notifier._send("should not send")
        mock_client.assert_not_called()
