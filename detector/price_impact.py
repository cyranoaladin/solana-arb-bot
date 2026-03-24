"""Price impact estimation based on pool liquidity and trade size."""

from __future__ import annotations
import logging
from detector.price_fetcher import PriceQuote

logger = logging.getLogger(__name__)


def estimate_price_impact(quote: PriceQuote, trade_amount_usd: float) -> float:
    """Estimate price impact as a percentage based on trade size vs pool liquidity.

    Uses a simplified constant-product model: impact ~ trade_size / (2 * liquidity)
    Returns 0.0 if liquidity is unknown.
    """
    if quote.liquidity <= 0:
        return 0.0
    # For constant-product AMMs: price_impact ~ amount / (2 * pool_liquidity)
    impact = (trade_amount_usd / (2 * quote.liquidity)) * 100
    return impact


def compute_confidence(quote: PriceQuote, all_quotes: list[PriceQuote]) -> float:
    """Compute a confidence score (0-1) for a price quote.

    Based on:
    - Liquidity weight: higher TVL = more reliable price
    - Deviation from weighted mean: outlier prices get lower confidence
    """
    if not all_quotes:
        return 0.5

    # Liquidity-weighted mean price
    total_liq = sum(q.liquidity for q in all_quotes if q.liquidity > 0)
    if total_liq > 0:
        weighted_price = sum(q.price * q.liquidity for q in all_quotes if q.liquidity > 0) / total_liq
    else:
        weighted_price = sum(q.price for q in all_quotes) / len(all_quotes)

    # Deviation from weighted mean
    if weighted_price > 0:
        deviation = abs(quote.price - weighted_price) / weighted_price
    else:
        deviation = 0.0

    # Liquidity score (0-1): sigmoid-like based on TVL
    if total_liq > 0 and quote.liquidity > 0:
        liq_score = min(quote.liquidity / total_liq * 2, 1.0)
    else:
        liq_score = 0.5

    # Confidence: high liquidity + low deviation = high confidence
    confidence = liq_score * max(0, 1 - deviation * 10)
    return max(0.0, min(1.0, confidence))


def weighted_mean_price(quotes: list[PriceQuote]) -> float:
    """Compute liquidity-weighted mean price across all DEXes."""
    liq_quotes = [q for q in quotes if q.liquidity > 0]
    if liq_quotes:
        total_liq = sum(q.liquidity for q in liq_quotes)
        return sum(q.price * q.liquidity for q in liq_quotes) / total_liq
    if quotes:
        return sum(q.price for q in quotes) / len(quotes)
    return 0.0


def filter_by_price_impact(quotes: list[PriceQuote], trade_amount_usd: float, max_impact_pct: float = 1.0) -> list[PriceQuote]:
    """Filter out quotes where estimated price impact exceeds threshold."""
    result = []
    for q in quotes:
        impact = estimate_price_impact(q, trade_amount_usd)
        if impact <= max_impact_pct:
            result.append(q)
        else:
            logger.debug("Filtered %s on %s: impact=%.2f%% > max=%.2f%%",
                        f"{q.input_token}/{q.output_token}", q.dex, impact, max_impact_pct)
    return result
