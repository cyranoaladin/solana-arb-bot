"""Tests for the circuit breaker module."""

from __future__ import annotations

import pytest
from detector.circuit_breaker import CircuitBreaker, CircuitBreakerOpen


def test_closed_by_default():
    cb = CircuitBreaker("test", failure_threshold=3)
    assert cb.state == "CLOSED"
    assert cb.can_call()


def test_opens_after_threshold_failures():
    cb = CircuitBreaker("test", failure_threshold=3, cooldown_sec=60)
    cb.record_failure()
    cb.record_failure()
    assert cb.state == "CLOSED"
    cb.record_failure()
    assert cb.state == "OPEN"
    assert not cb.can_call()


def test_success_resets_failures():
    cb = CircuitBreaker("test", failure_threshold=3)
    cb.record_failure()
    cb.record_failure()
    cb.record_success()
    assert cb.consecutive_failures == 0
    assert cb.state == "CLOSED"


def test_reopens_after_cooldown():
    cb = CircuitBreaker("test", failure_threshold=1, cooldown_sec=0.0)
    cb.record_failure()
    assert cb.state == "OPEN"
    # Cooldown is 0s so it should immediately allow
    assert cb.can_call()
    assert cb.state == "HALF_OPEN"


def test_half_open_success_closes():
    cb = CircuitBreaker("test", failure_threshold=1, cooldown_sec=0.0)
    cb.record_failure()
    cb.can_call()  # transitions to HALF_OPEN
    cb.record_success()
    assert cb.state == "CLOSED"
    assert cb.trip_count == 0


@pytest.mark.asyncio
async def test_call_raises_when_open():
    cb = CircuitBreaker("test", failure_threshold=1, cooldown_sec=999)
    cb.record_failure()

    async def dummy():
        return 42

    with pytest.raises(CircuitBreakerOpen):
        await cb.call(dummy)


@pytest.mark.asyncio
async def test_call_passes_when_closed():
    cb = CircuitBreaker("test", failure_threshold=3)

    async def dummy():
        return 42

    result = await cb.call(dummy)
    assert result == 42
    assert cb.consecutive_failures == 0
