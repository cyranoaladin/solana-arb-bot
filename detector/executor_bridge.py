"""Python-Rust bridge — calls the executor binary via subprocess."""

from __future__ import annotations

import asyncio
import json
import logging

logger = logging.getLogger(__name__)


class ExecutorBridge:
    """Communicates with the Rust executor binary over CLI/subprocess."""

    def __init__(self, executor_path: str, rpc_url: str, keypair_path: str) -> None:
        self.executor_path = executor_path
        self.rpc_url = rpc_url
        self.keypair_path = keypair_path
        self._wallet_pubkey: str | None = None

    def _parse_response(self, raw: str) -> dict:
        """Parse JSON from stdout. Return an error dict on invalid JSON."""
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError) as exc:
            logger.error("Failed to parse executor output: %s", exc)
            return {"status": "error", "message": str(exc)}

    async def _run(self, args: list[str]) -> dict:
        """Run the executor binary with the given args and return parsed JSON."""
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if stderr:
                logger.warning("Executor stderr: %s", stderr.decode().strip())

            return self._parse_response(stdout.decode().strip())
        except Exception as exc:
            logger.error("Executor command failed: %s", exc)
            return {"status": "error", "message": str(exc)}

    async def swap(
        self,
        from_token: str,
        to_token: str,
        amount: float,
        dex: str,
        min_out: float,
        dry_run: bool = False,
        priority_fee: int = 500_000,
    ) -> dict:
        """Execute a swap via the Rust executor binary."""
        args = [
            self.executor_path,
            "swap",
            "--from", from_token,
            "--to", to_token,
            "--amount", str(amount),
            "--dex", dex,
            "--min-out", str(min_out),
            "--rpc-url", self.rpc_url,
            "--keypair-path", self.keypair_path,
            "--priority-fee", str(priority_fee),
        ]
        if dry_run:
            args.append("--dry-run")

        return await self._run(args)

    async def swap_with_retry(
        self,
        from_token: str,
        to_token: str,
        amount: float,
        dex: str,
        min_out: float,
        dry_run: bool = False,
        priority_fee: int = 500_000,
        max_retries: int = 3,
        base_delay: float = 1.0,
    ) -> dict:
        """Execute a swap with exponential backoff retry on failure.

        Retries on transient errors (RPC timeout, network issues).
        Does NOT retry on business logic errors (insufficient balance, slippage exceeded).
        """
        non_retryable = {"insufficient", "slippage", "InsufficientFunds", "custom program error"}

        last_result = {"status": "error", "message": "max retries exceeded"}
        for attempt in range(max_retries + 1):
            result = await self.swap(
                from_token=from_token,
                to_token=to_token,
                amount=amount,
                dex=dex,
                min_out=min_out,
                dry_run=dry_run,
                priority_fee=priority_fee,
            )

            if result.get("status") != "error":
                if attempt > 0:
                    logger.info("Swap succeeded on attempt %d", attempt + 1)
                return result

            last_result = result
            error_msg = result.get("message", "").lower()

            # Don't retry business logic errors
            if any(term in error_msg for term in non_retryable):
                logger.warning("Swap failed with non-retryable error: %s", error_msg)
                return result

            if attempt < max_retries:
                delay = base_delay * (2 ** attempt)
                logger.warning(
                    "Swap attempt %d/%d failed: %s — retrying in %.1fs",
                    attempt + 1, max_retries + 1, error_msg, delay,
                )
                await asyncio.sleep(delay)

        logger.error("Swap failed after %d attempts: %s", max_retries + 1, last_result.get("message"))
        return last_result

    async def sign_and_send(self, tx_base64: str) -> dict:
        """Sign a base64-encoded transaction and send it to the network."""
        args = [
            self.executor_path,
            "sign-and-send",
            "--tx-base64", tx_base64,
            "--rpc-url", self.rpc_url,
            "--keypair-path", self.keypair_path,
        ]
        return await self._run(args)

    async def get_balance(self) -> float:
        """Get the current SOL balance via the executor binary."""
        args = [
            self.executor_path,
            "balance",
            "--rpc-url", self.rpc_url,
            "--keypair-path", self.keypair_path,
        ]
        data = await self._run(args)
        return float(data.get("balance_sol", 0.0))

    async def send_bundle(self, tx_base64_list: list[str], tip_lamports: int = 50_000) -> dict:
        """Send an atomic Jito bundle of transactions (MEV-protected)."""
        transactions_csv = ",".join(tx_base64_list)
        args = [
            self.executor_path,
            "send-bundle",
            "--transactions", transactions_csv,
            "--rpc-url", self.rpc_url,
            "--keypair-path", self.keypair_path,
            "--tip-lamports", str(tip_lamports),
        ]
        return await self._run(args)

    async def get_pubkey(self) -> str:
        """Get the wallet public key from the keypair file."""
        if self._wallet_pubkey:
            return self._wallet_pubkey

        args = [
            self.executor_path,
            "pubkey",
            "--keypair-path", self.keypair_path,
        ]
        data = await self._run(args)
        self._wallet_pubkey = data.get("pubkey", "")
        return self._wallet_pubkey
