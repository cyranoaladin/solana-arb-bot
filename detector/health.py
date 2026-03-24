"""HTTP health check server on port 8080."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class BotStats:
    """Shared mutable state for the bot, read by health endpoint."""

    started_at: float = field(default_factory=time.time)
    balance_sol: float = 0.0
    trades_total: int = 0
    profit_total: float = 0.0
    last_scan_ts: float = 0.0
    opportunities_seen: int = 0
    errors_total: int = 0
    dry_run: bool = True
    paused: bool = False
    pnl_curve: list[dict] = field(default_factory=list)

    def record_trade(self, profit: float) -> None:
        """Record a trade and append to PnL curve."""
        self.pnl_curve.append({
            "ts": time.time(),
            "profit": profit,
            "cumulative": self.profit_total,
        })

    def to_dict(self) -> dict:
        uptime = time.time() - self.started_at
        return {
            "status": "paused" if self.paused else "running",
            "uptime_sec": round(uptime),
            "dry_run": self.dry_run,
            "balance_sol": self.balance_sol,
            "trades_total": self.trades_total,
            "profit_total": round(self.profit_total, 6),
            "opportunities_seen": self.opportunities_seen,
            "errors_total": self.errors_total,
            "last_scan_sec_ago": round(time.time() - self.last_scan_ts, 1) if self.last_scan_ts else None,
        }


async def _handle_health(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, stats: BotStats) -> None:
    """Handle a single HTTP request on the health endpoint."""
    try:
        await asyncio.wait_for(reader.readline(), timeout=5.0)
        # Consume remaining headers
        while True:
            line = await asyncio.wait_for(reader.readline(), timeout=2.0)
            if line == b"\r\n" or line == b"\n" or not line:
                break

        body = json.dumps(stats.to_dict(), indent=2)
        response = (
            f"HTTP/1.1 200 OK\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"Connection: close\r\n"
            f"\r\n"
            f"{body}"
        )
        writer.write(response.encode())
        await writer.drain()
    except Exception:
        pass
    finally:
        writer.close()


async def start_health_server(stats: BotStats, port: int = 8080) -> asyncio.Server:
    """Start the health check HTTP server."""
    async def handler(reader, writer):
        await _handle_health(reader, writer, stats)

    server = await asyncio.start_server(handler, "0.0.0.0", port)
    logger.info("Health check server listening on port %d", port)
    return server
