"""Arbitrage detection engine for cross-DEX spread opportunities."""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Try importing PriceQuote from the price_fetcher module; define locally if unavailable.
try:
    from detector.price_fetcher import PriceQuote
except ImportError:

    @dataclass
    class PriceQuote:
        """Lightweight quote returned by a DEX price source."""

        dex: str
        input_token: str
        output_token: str
        input_amount: float
        output_amount: float
        price: float


@dataclass
class Opportunity:
    """A detected arbitrage opportunity between two DEXes."""

    pair: str
    buy_dex: str
    sell_dex: str
    buy_price: float
    sell_price: float
    amount: float
    profit_pct: float
    estimated_profit: float


class ArbitrageDetector:
    """Compares quotes across DEXes and identifies profitable spreads."""

    def __init__(self, min_profit_pct: float = 0.1, tx_fee_sol: float = 0.000005) -> None:
        self.min_profit_pct = min_profit_pct
        self.tx_fee_sol = tx_fee_sol

    def find_opportunities(self, quotes: list[PriceQuote]) -> list[Opportunity]:
        """Return arbitrage opportunities sorted by profit_pct descending."""
        if len(quotes) < 2:
            return []

        opportunities: list[Opportunity] = []

        for buy in quotes:
            for sell in quotes:
                if buy is sell:
                    continue
                if sell.output_amount <= buy.output_amount:
                    continue

                spread = sell.output_amount - buy.output_amount
                profit_pct = (spread / buy.output_amount) * 100

                if profit_pct < self.min_profit_pct:
                    continue

                opp = Opportunity(
                    pair=f"{buy.input_token}/{buy.output_token}",
                    buy_dex=buy.dex,
                    sell_dex=sell.dex,
                    buy_price=buy.output_amount,
                    sell_price=sell.output_amount,
                    amount=buy.input_amount,
                    profit_pct=profit_pct,
                    estimated_profit=spread,
                )
                opportunities.append(opp)

        opportunities.sort(key=lambda o: o.profit_pct, reverse=True)

        logger.info("Found %d arbitrage opportunities", len(opportunities))
        for opp in opportunities:
            logger.info(
                "  %s: buy@%s sell@%s spread=%.4f profit=%.4f%%",
                opp.pair,
                opp.buy_dex,
                opp.sell_dex,
                opp.estimated_profit,
                opp.profit_pct,
            )

        return opportunities
