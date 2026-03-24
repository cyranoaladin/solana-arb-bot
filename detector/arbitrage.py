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


# Base tx fee on Solana (5000 lamports). Priority fees added separately.
BASE_TX_FEE_SOL = 0.000005
# We execute 2 transactions per arb (buy + sell), so 2x fee.
FEES_PER_ARB_SOL = BASE_TX_FEE_SOL * 2


class VolatilityTracker:
    """Tracks rolling price volatility to adapt trading thresholds."""

    def __init__(self, window: int = 100, base_min_profit: float = 0.1,
                 low_vol_profit: float = 0.07, high_vol_profit: float = 0.25,
                 vol_threshold_high: float = 0.02, vol_threshold_low: float = 0.005):
        self.window = window
        self.base_min_profit = base_min_profit
        self.low_vol_profit = low_vol_profit
        self.high_vol_profit = high_vol_profit
        self.vol_threshold_high = vol_threshold_high
        self.vol_threshold_low = vol_threshold_low
        self.prices: list[float] = []

    def add_price(self, price: float) -> None:
        self.prices.append(price)
        if len(self.prices) > self.window:
            self.prices.pop(0)

    def get_volatility(self) -> float:
        if len(self.prices) < 10:
            return 0.0
        mean = sum(self.prices) / len(self.prices)
        if mean == 0:
            return 0.0
        variance = sum((p - mean) ** 2 for p in self.prices) / len(self.prices)
        std_dev = variance ** 0.5
        return std_dev / mean  # coefficient of variation

    def get_adaptive_min_profit(self) -> float:
        vol = self.get_volatility()
        if vol >= self.vol_threshold_high:
            return self.high_vol_profit
        elif vol <= self.vol_threshold_low:
            return self.low_vol_profit
        return self.base_min_profit


class ArbitrageDetector:
    """Compares quotes across DEXes and identifies profitable spreads."""

    def __init__(
        self,
        min_profit_pct: float = 0.1,
        priority_fee_sol: float = 0.0001,
    ) -> None:
        self.min_profit_pct = min_profit_pct
        self.total_fee_sol = FEES_PER_ARB_SOL + priority_fee_sol

    def find_opportunities(self, quotes: list[PriceQuote]) -> list[Opportunity]:
        """Return arbitrage opportunities sorted by profit_pct descending.

        Compares quotes for the same token pair across different DEXes.
        A profitable arb exists when one DEX offers more output than another
        for the same input, after accounting for transaction fees.
        """
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

                # Deduct tx fees from profit (convert fee to output token terms)
                # For SOL→USDC trades, fee is in SOL so convert via the buy price
                if buy.input_token == "SOL" and buy.input_amount > 0:
                    fee_in_output = self.total_fee_sol * (buy.output_amount / buy.input_amount)
                else:
                    fee_in_output = 0.0

                net_profit = spread - fee_in_output
                if net_profit <= 0:
                    continue

                profit_pct = (net_profit / buy.output_amount) * 100

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
                    estimated_profit=net_profit,
                )
                opportunities.append(opp)

        opportunities.sort(key=lambda o: o.profit_pct, reverse=True)

        logger.info("Found %d arbitrage opportunities", len(opportunities))
        for opp in opportunities:
            logger.info(
                "  %s: buy@%s sell@%s spread=%.6f net_profit=%.6f profit=%.4f%%",
                opp.pair,
                opp.buy_dex,
                opp.sell_dex,
                opp.sell_price - opp.buy_price,
                opp.estimated_profit,
                opp.profit_pct,
            )

        return opportunities

    def find_triangular_opportunities(
        self, all_quotes: dict[str, list[PriceQuote]], start_token: str = "SOL", start_amount: float = 0.05,
    ) -> list[Opportunity]:
        """Find triangular arb: SOL → A → B → SOL.

        `all_quotes` maps "TOKEN_A/TOKEN_B" to a list of PriceQuote for that pair.
        Example keys: "SOL/USDC", "SOL/USDT", "USDC/USDT".
        """
        opportunities: list[Opportunity] = []
        tokens = {"SOL", "USDC", "USDT"}
        mid_tokens = tokens - {start_token}

        for mid_a in mid_tokens:
            for mid_b in mid_tokens - {mid_a}:
                # Route: start_token → mid_a → mid_b → start_token
                leg1_key = f"{start_token}/{mid_a}"
                leg2_key = f"{mid_a}/{mid_b}"
                leg3_key = f"{mid_b}/{start_token}"

                leg1_quotes = all_quotes.get(leg1_key, [])
                leg2_quotes = all_quotes.get(leg2_key, [])
                leg3_quotes = all_quotes.get(leg3_key, [])

                if not leg1_quotes or not leg2_quotes or not leg3_quotes:
                    continue

                # Pick the best quote for each leg (highest output)
                best1 = max(leg1_quotes, key=lambda q: q.output_amount)
                best2 = max(leg2_quotes, key=lambda q: q.output_amount)
                best3 = max(leg3_quotes, key=lambda q: q.output_amount)

                # Simulate the chain: start_amount → mid_a_amount → mid_b_amount → final_amount
                mid_a_amount = best1.output_amount  # from start_amount of SOL
                # Scale leg 2: best2 is for best2.input_amount → best2.output_amount
                if best2.input_amount <= 0:
                    continue
                mid_b_amount = mid_a_amount * (best2.output_amount / best2.input_amount)
                # Scale leg 3
                if best3.input_amount <= 0:
                    continue
                final_amount = mid_b_amount * (best3.output_amount / best3.input_amount)

                # Deduct fees (3 transactions for triangular)
                fee_sol = BASE_TX_FEE_SOL * 3 + 0.0001  # priority fee estimate
                net_final = final_amount - fee_sol

                profit = net_final - start_amount
                if profit <= 0:
                    continue

                profit_pct = (profit / start_amount) * 100
                if profit_pct < self.min_profit_pct:
                    continue

                route = f"{start_token}→{mid_a}→{mid_b}→{start_token}"
                opp = Opportunity(
                    pair=route,
                    buy_dex=f"{best1.dex}/{best2.dex}/{best3.dex}",
                    sell_dex=route,
                    buy_price=start_amount,
                    sell_price=net_final,
                    amount=start_amount,
                    profit_pct=profit_pct,
                    estimated_profit=profit,
                )
                opportunities.append(opp)
                logger.info(
                    "Triangular arb: %s via %s profit=%.6f (%.4f%%)",
                    route, opp.buy_dex, profit, profit_pct,
                )

        opportunities.sort(key=lambda o: o.profit_pct, reverse=True)
        return opportunities
