"""Helius Enhanced RPC client for priority fees and tx simulation."""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)


class HeliusClient:
    """Client for Helius Enhanced RPC API (priority fees, simulation)."""

    def __init__(self, rpc_url: str) -> None:
        self.rpc_url = rpc_url
        self.client = httpx.AsyncClient(timeout=10)

    async def get_priority_fee(self, account_keys: list[str] | None = None) -> int:
        """Get estimated priority fee in microLamports via Helius getPriorityFeeEstimate.

        Returns a fee estimate suitable for passing to the Rust executor.
        Falls back to 500_000 microLamports on error.
        """
        fallback = 500_000
        try:
            body = {
                "jsonrpc": "2.0",
                "id": "fee-estimate",
                "method": "getPriorityFeeEstimate",
                "params": [
                    {
                        "options": {"priorityLevel": "High"},
                    }
                ],
            }
            if account_keys:
                body["params"][0]["accountKeys"] = account_keys

            resp = await self.client.post(self.rpc_url, json=body)
            resp.raise_for_status()
            data = resp.json()

            fee = data.get("result", {}).get("priorityFeeEstimate")
            if fee is not None:
                fee = int(fee)
                logger.info("Helius priority fee estimate: %d microLamports", fee)
                return max(fee, 1000)  # minimum floor
            return fallback
        except Exception:
            logger.warning("Failed to get priority fee estimate, using fallback %d", fallback)
            return fallback

    async def simulate_transaction(self, tx_base64: str) -> dict:
        """Simulate a transaction via Solana RPC simulateTransaction.

        Returns {"success": True/False, "error": str|None, "logs": list}.
        """
        try:
            body = {
                "jsonrpc": "2.0",
                "id": "sim",
                "method": "simulateTransaction",
                "params": [
                    tx_base64,
                    {
                        "encoding": "base64",
                        "commitment": "confirmed",
                        "replaceRecentBlockhash": True,
                    },
                ],
            }
            resp = await self.client.post(self.rpc_url, json=body)
            resp.raise_for_status()
            data = resp.json()

            result = data.get("result", {})
            value = result.get("value", {})
            err = value.get("err")
            logs = value.get("logs", [])

            if err:
                logger.warning("Simulation failed: %s", err)
                return {"success": False, "error": str(err), "logs": logs}

            return {"success": True, "error": None, "logs": logs}
        except Exception as exc:
            logger.warning("Simulation request failed: %s", exc)
            return {"success": False, "error": str(exc), "logs": []}

    async def close(self) -> None:
        await self.client.aclose()
