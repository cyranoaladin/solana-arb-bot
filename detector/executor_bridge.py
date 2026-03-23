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

    def _parse_response(self, raw: str) -> dict:
        """Parse JSON from stdout. Return an error dict on invalid JSON."""
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError) as exc:
            logger.error("Failed to parse executor output: %s", exc)
            return {"status": "error", "message": str(exc)}

    async def swap(
        self,
        from_token: str,
        to_token: str,
        amount: float,
        dex: str,
        min_out: float,
        dry_run: bool = False,
    ) -> dict:
        """Execute a swap via the Rust executor binary.

        Returns the parsed JSON response from the executor.
        """
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
        ]
        if dry_run:
            args.append("--dry-run")

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
            logger.error("Executor swap failed: %s", exc)
            return {"status": "error", "message": str(exc)}

    async def get_balance(self) -> float:
        """Get the current SOL balance via the executor binary."""
        args = [
            self.executor_path,
            "balance",
            "--rpc-url", self.rpc_url,
            "--keypair-path", self.keypair_path,
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if stderr:
                logger.warning("Executor stderr: %s", stderr.decode().strip())

            data = self._parse_response(stdout.decode().strip())
            return float(data.get("balance", 0.0))
        except Exception as exc:
            logger.error("Executor get_balance failed: %s", exc)
            return 0.0
