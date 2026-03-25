"""Tests for execution policy — hard-stop unsafe live routes."""

import pytest
from unittest.mock import MagicMock
from detector.execution_policy import (
    evaluate_opportunity, TradeDecision, ExecutionPlan, EXECUTABLE_DEXES,
)


def _mock_config(dry_run=True, trading_enabled=False, allow_unsupported=False):
    cfg = MagicMock()
    cfg.dry_run = dry_run
    cfg.trading_enabled = trading_enabled
    cfg.live_trading_allow_unsupported_routes = allow_unsupported
    return cfg


def _mock_opp(buy_dex="orca", sell_dex="raydium"):
    opp = MagicMock()
    opp.buy_dex = buy_dex
    opp.sell_dex = sell_dex
    opp.pair = "SOL/USDC"
    return opp


def _mock_quote(dex, quote_kind="reference", executable=False):
    q = MagicMock()
    q.dex = dex
    q.quote_kind = quote_kind
    q.executable = executable
    return q


class TestDryRunAlwaysSimulates:
    def test_dry_run_default(self):
        plan = evaluate_opportunity(_mock_opp(), _mock_config(dry_run=True))
        assert plan.decision == TradeDecision.SIMULATED
        assert plan.is_dry_run is True

    def test_trading_disabled_simulates(self):
        plan = evaluate_opportunity(_mock_opp(), _mock_config(dry_run=False, trading_enabled=False))
        assert plan.decision == TradeDecision.SIMULATED


class TestLiveRouteBlocking:
    def test_orca_buy_blocked(self):
        plan = evaluate_opportunity(
            _mock_opp(buy_dex="orca", sell_dex="raydium"),
            _mock_config(dry_run=False, trading_enabled=True, allow_unsupported=False),
        )
        assert plan.decision == TradeDecision.BLOCKED_UNSUPPORTED_ROUTE
        assert "orca" in plan.block_reason.lower()

    def test_meteora_sell_blocked(self):
        plan = evaluate_opportunity(
            _mock_opp(buy_dex="raydium", sell_dex="meteora"),
            _mock_config(dry_run=False, trading_enabled=True, allow_unsupported=False),
        )
        assert plan.decision == TradeDecision.BLOCKED_UNSUPPORTED_ROUTE

    def test_raydium_raydium_allowed(self):
        plan = evaluate_opportunity(
            _mock_opp(buy_dex="raydium", sell_dex="raydium"),
            _mock_config(dry_run=False, trading_enabled=True, allow_unsupported=False),
        )
        assert plan.decision == TradeDecision.SUBMITTED
        assert plan.route_supported is True
        assert plan.atomic is False  # honest: not atomic

    def test_unsupported_allowed_if_flag_set(self):
        plan = evaluate_opportunity(
            _mock_opp(buy_dex="orca", sell_dex="raydium"),
            _mock_config(dry_run=False, trading_enabled=True, allow_unsupported=True),
        )
        assert plan.decision == TradeDecision.SUBMITTED


class TestReferenceQuoteBlocking:
    def test_reference_quote_blocks_live(self):
        quotes = [
            _mock_quote("orca", quote_kind="reference", executable=False),
            _mock_quote("raydium", quote_kind="executable", executable=True),
        ]
        plan = evaluate_opportunity(
            _mock_opp(buy_dex="orca", sell_dex="raydium"),
            _mock_config(dry_run=False, trading_enabled=True, allow_unsupported=False),
            quotes=quotes,
        )
        # Blocked by unsupported route first (before reference quote check)
        assert plan.decision in (
            TradeDecision.BLOCKED_UNSUPPORTED_ROUTE,
            TradeDecision.BLOCKED_REFERENCE_QUOTE,
        )

    def test_executable_quotes_pass(self):
        quotes = [
            _mock_quote("raydium", quote_kind="executable", executable=True),
        ]
        plan = evaluate_opportunity(
            _mock_opp(buy_dex="raydium", sell_dex="raydium"),
            _mock_config(dry_run=False, trading_enabled=True, allow_unsupported=False),
            quotes=quotes,
        )
        assert plan.decision == TradeDecision.SUBMITTED


class TestExecutionPlanProperties:
    def test_simulated_can_execute(self):
        plan = ExecutionPlan(decision=TradeDecision.SIMULATED)
        assert plan.can_execute is True

    def test_blocked_cannot_execute(self):
        plan = ExecutionPlan(decision=TradeDecision.BLOCKED_UNSUPPORTED_ROUTE)
        assert plan.can_execute is False

    def test_submitted_can_execute(self):
        plan = ExecutionPlan(decision=TradeDecision.SUBMITTED)
        assert plan.can_execute is True

    def test_observed_cannot_execute(self):
        plan = ExecutionPlan(decision=TradeDecision.OBSERVED_ONLY)
        assert plan.can_execute is False
