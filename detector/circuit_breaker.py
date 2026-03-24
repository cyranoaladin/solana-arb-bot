"""Circuit breaker for RPC/API calls with exponential backoff."""

from __future__ import annotations

import asyncio
import logging
import time

logger = logging.getLogger(__name__)


class CircuitBreaker:
    """Circuit breaker that opens after consecutive failures and retries with backoff.

    States:
    - CLOSED: normal operation, calls pass through
    - OPEN: too many failures, calls are rejected for a cooldown period
    - HALF_OPEN: after cooldown, allows one test call to check recovery
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 3,
        cooldown_sec: float = 30.0,
        max_cooldown_sec: float = 300.0,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.base_cooldown = cooldown_sec
        self.max_cooldown = max_cooldown_sec
        self.consecutive_failures = 0
        self.state = "CLOSED"
        self.open_until = 0.0
        self.trip_count = 0

    def _cooldown(self) -> float:
        """Exponential backoff: base * 2^(trip_count - 1), capped."""
        return min(self.base_cooldown * (2 ** max(0, self.trip_count - 1)), self.max_cooldown)

    def can_call(self) -> bool:
        """Check if a call is allowed."""
        if self.state == "CLOSED":
            return True
        if self.state == "OPEN":
            if time.monotonic() >= self.open_until:
                self.state = "HALF_OPEN"
                logger.info("Circuit breaker '%s' entering HALF_OPEN", self.name)
                return True
            return False
        # HALF_OPEN: allow one test call
        return True

    def record_success(self) -> None:
        """Record a successful call."""
        if self.state == "HALF_OPEN":
            logger.info("Circuit breaker '%s' CLOSED (recovery successful)", self.name)
            self.trip_count = 0
        self.consecutive_failures = 0
        self.state = "CLOSED"

    def record_failure(self) -> None:
        """Record a failed call."""
        self.consecutive_failures += 1
        if self.state == "HALF_OPEN" or self.consecutive_failures >= self.failure_threshold:
            self.trip_count += 1
            cooldown = self._cooldown()
            self.state = "OPEN"
            self.open_until = time.monotonic() + cooldown
            logger.warning(
                "Circuit breaker '%s' OPEN — %d failures, cooldown %.0fs",
                self.name,
                self.consecutive_failures,
                cooldown,
            )

    async def call(self, coro_fn, *args, **kwargs):
        """Execute an async function through the circuit breaker.

        Raises CircuitBreakerOpen if the circuit is open.
        """
        if not self.can_call():
            remaining = self.open_until - time.monotonic()
            raise CircuitBreakerOpen(
                f"Circuit breaker '{self.name}' is OPEN, retry in {remaining:.0f}s"
            )

        try:
            result = await coro_fn(*args, **kwargs)
            self.record_success()
            return result
        except CircuitBreakerOpen:
            raise
        except Exception:
            self.record_failure()
            raise


class CircuitBreakerOpen(Exception):
    """Raised when the circuit breaker is open and calls are rejected."""
