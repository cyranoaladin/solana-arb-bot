"""Batch RPC client — groups multiple Solana RPC calls into a single HTTP request.

Inspired by Mobula's batch processing pattern. Solana JSON-RPC supports
batch requests: send an array of requests, get an array of responses.
Reduces network round-trips from N to 1.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class BatchRPCClient:
    """Batches multiple Solana RPC calls into a single HTTP request."""

    def __init__(self, rpc_url: str, timeout: float = 15.0) -> None:
        self.rpc_url = rpc_url
        self.client = httpx.AsyncClient(timeout=timeout)
        self._id_counter = 0

    def _next_id(self) -> int:
        self._id_counter += 1
        return self._id_counter

    async def batch_call(self, calls: list[tuple[str, list]]) -> list[dict]:
        """Execute multiple RPC calls in a single HTTP request.

        Args:
            calls: list of (method, params) tuples.
                   e.g., [("getBalance", [pubkey]), ("getLatestBlockhash", [])]

        Returns:
            list of result dicts in the same order as input calls.
            Each dict has "result" on success or "error" on failure.
        """
        if not calls:
            return []

        batch = []
        for method, params in calls:
            batch.append({
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": method,
                "params": params,
            })

        try:
            resp = await self.client.post(self.rpc_url, json=batch)
            resp.raise_for_status()
            responses = resp.json()

            # Sort by id to match input order
            if isinstance(responses, list):
                id_map = {r["id"]: r for r in responses}
                return [id_map.get(b["id"], {"error": "missing response"}) for b in batch]
            else:
                # Single response (shouldn't happen with batch, but handle it)
                return [responses]
        except Exception as exc:
            logger.error("Batch RPC call failed: %s", exc)
            return [{"error": str(exc)}] * len(calls)

    async def get_multiple_balances(self, pubkeys: list[str]) -> dict[str, float]:
        """Get SOL balances for multiple accounts in a single batch call.

        Returns: {pubkey: balance_sol}
        """
        calls = [("getBalance", [pk]) for pk in pubkeys]
        results = await self.batch_call(calls)

        balances = {}
        for pk, resp in zip(pubkeys, results):
            if "result" in resp:
                lamports = resp["result"].get("value", 0)
                balances[pk] = lamports / 1_000_000_000.0
            else:
                balances[pk] = 0.0
        return balances

    async def get_balance_and_fee(self, pubkey: str) -> tuple[float, int]:
        """Get balance and priority fee estimate in a single batch call.

        Returns: (balance_sol, priority_fee_micro_lamports)
        """
        calls = [
            ("getBalance", [pubkey]),
            ("getPriorityFeeEstimate", [{"options": {"priorityLevel": "High"}}]),
        ]
        results = await self.batch_call(calls)

        # Parse balance
        balance = 0.0
        if "result" in results[0]:
            lamports = results[0]["result"].get("value", 0)
            balance = lamports / 1_000_000_000.0

        # Parse priority fee
        fee = 500_000  # fallback
        if "result" in results[1]:
            fee_est = results[1]["result"]
            if isinstance(fee_est, dict):
                fee = int(fee_est.get("priorityFeeEstimate", fee))
            elif isinstance(fee_est, (int, float)):
                fee = int(fee_est)

        return balance, fee

    async def get_recent_blockhash_and_balance(self, pubkey: str) -> tuple[str, float]:
        """Get latest blockhash and balance in a single batch.

        Returns: (blockhash_str, balance_sol)
        """
        calls = [
            ("getLatestBlockhash", [{"commitment": "confirmed"}]),
            ("getBalance", [pubkey]),
        ]
        results = await self.batch_call(calls)

        blockhash = ""
        if "result" in results[0]:
            blockhash = results[0]["result"].get("value", {}).get("blockhash", "")

        balance = 0.0
        if "result" in results[1]:
            balance = results[1]["result"].get("value", 0) / 1_000_000_000.0

        return blockhash, balance

    async def close(self) -> None:
        await self.client.aclose()
