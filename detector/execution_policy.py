"""Execution policy — hard-stop unsafe live routes.

This module decides whether an opportunity can be executed live,
simulated, or must remain observation-only.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)

# DEXes that have a real swap execution path in this build
EXECUTABLE_DEXES = frozenset({"raydium"})


class TradeDecision(str, Enum):
    """Possible decisions for an opportunity."""
    OBSERVED_ONLY = "observed_only"
    BLOCKED_UNSUPPORTED_ROUTE = "blocked_unsupported_route"
    BLOCKED_NON_ATOMIC = "blocked_non_atomic"
    BLOCKED_MISSING_ACTUAL_OUTPUT = "blocked_missing_actual_output"
    BLOCKED_REFERENCE_QUOTE = "blocked_reference_quote"
    SIMULATED = "simulated"
    SUBMITTED = "submitted"
    CONFIRMED = "confirmed"
    FAILED = "failed"


@dataclass
class ExecutionPlan:
    """What the engine plans to do with an opportunity."""
    decision: TradeDecision
    block_reason: str = ""
    execution_dex: str = "raydium"
    is_dry_run: bool = True
    route_supported: bool = False
    atomic: bool = False

    @property
    def can_execute(self) -> bool:
        return self.decision in (TradeDecision.SIMULATED, TradeDecision.SUBMITTED)


@dataclass
class ExecutionResult:
    """Result of an execution attempt."""
    decision: TradeDecision
    tx_hash_leg1: str = ""
    tx_hash_leg2: str = ""
    estimated_profit: float = 0.0
    realized_profit: float = 0.0  # 0 until on-chain reconciliation
    output_amount_leg1: Optional[float] = None
    error_message: str = ""


def evaluate_opportunity(
    opp,
    config,
    quotes: list = None,
) -> ExecutionPlan:
    """Evaluate whether an opportunity can be executed.

    Returns an ExecutionPlan with the decision and reason.
    """
    is_dry = config.dry_run or not config.trading_enabled

    # Dry-run: always simulate
    if is_dry:
        return ExecutionPlan(
            decision=TradeDecision.SIMULATED,
            execution_dex="raydium",
            is_dry_run=True,
            route_supported=True,
        )

    # Live: check route support
    if not config.live_trading_allow_unsupported_routes:
        buy_executable = opp.buy_dex in EXECUTABLE_DEXES
        sell_executable = opp.sell_dex in EXECUTABLE_DEXES

        if not buy_executable or not sell_executable:
            reason = (
                f"Route {opp.buy_dex}->{opp.sell_dex} not supported for live execution. "
                f"Only {EXECUTABLE_DEXES} DEXes are executable. "
                f"Opportunity is observation-only."
            )
            return ExecutionPlan(
                decision=TradeDecision.BLOCKED_UNSUPPORTED_ROUTE,
                block_reason=reason,
                route_supported=False,
            )

    # Live: check quote types if quotes provided
    if quotes:
        for q in quotes:
            if hasattr(q, "quote_kind") and q.quote_kind == "reference" and hasattr(q, "executable") and not q.executable:
                if q.dex == opp.buy_dex or q.dex == opp.sell_dex:
                    reason = (
                        f"Quote from {q.dex} is reference-only (not executable). "
                        f"Cannot use reference quotes for live trading decisions."
                    )
                    return ExecutionPlan(
                        decision=TradeDecision.BLOCKED_REFERENCE_QUOTE,
                        block_reason=reason,
                        route_supported=False,
                    )

    # Live: allowed (non-atomic — documented limitation)
    return ExecutionPlan(
        decision=TradeDecision.SUBMITTED,
        execution_dex="raydium",
        is_dry_run=False,
        route_supported=True,
        atomic=False,  # honest: not atomic in current build
    )
