"""Tests for the health check HTTP endpoint (BotStats + start_health_server)."""

from __future__ import annotations

import asyncio
import json
import time

import pytest

from detector.health import BotStats, start_health_server


@pytest.fixture()
def stats() -> BotStats:
    return BotStats()


def _free_port() -> int:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


async def _http_get(port: int) -> dict:
    """Minimal raw-socket HTTP GET and return parsed JSON body."""
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(b"GET /health HTTP/1.1\r\nHost: localhost\r\n\r\n")
    await writer.drain()
    data = await asyncio.wait_for(reader.read(4096), timeout=5.0)
    writer.close()
    body = data.decode().split("\r\n\r\n", 1)[1]
    return json.loads(body)


# ---------- 1. test_health_server_responds ----------

@pytest.mark.asyncio
async def test_health_server_responds(stats: BotStats) -> None:
    port = _free_port()
    server = await start_health_server(stats, port=port)
    try:
        result = await _http_get(port)
        assert "status" in result
        assert "uptime_sec" in result
        assert "dry_run" in result
        assert "balance_sol" in result
        assert "trades_total" in result
        assert "estimated_profit_total" in result
        assert "opportunities_seen" in result
        assert "errors_total" in result
        assert "last_scan_sec_ago" in result
    finally:
        server.close()
        await server.wait_closed()


# ---------- 2. test_health_returns_paused_status ----------

@pytest.mark.asyncio
async def test_health_returns_paused_status(stats: BotStats) -> None:
    stats.paused = True
    port = _free_port()
    server = await start_health_server(stats, port=port)
    try:
        result = await _http_get(port)
        assert result["status"] == "paused"
    finally:
        server.close()
        await server.wait_closed()


# ---------- 3. test_health_returns_correct_uptime ----------

@pytest.mark.asyncio
async def test_health_returns_correct_uptime(stats: BotStats) -> None:
    stats.started_at = time.time() - 120  # pretend started 120s ago
    port = _free_port()
    server = await start_health_server(stats, port=port)
    try:
        result = await _http_get(port)
        # Allow a 3-second tolerance
        assert 117 <= result["uptime_sec"] <= 125
    finally:
        server.close()
        await server.wait_closed()


# ---------- 4. test_health_returns_trade_data ----------

@pytest.mark.asyncio
async def test_health_returns_trade_data(stats: BotStats) -> None:
    stats.trades_total = 5
    stats.estimated_profit_total = 0.001
    port = _free_port()
    server = await start_health_server(stats, port=port)
    try:
        result = await _http_get(port)
        assert result["trades_total"] == 5
        assert result["estimated_profit_total"] == 0.001
    finally:
        server.close()
        await server.wait_closed()
