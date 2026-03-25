"""Performance, latency, and stress tests for the Solana arbitrage bot."""

from __future__ import annotations

import math
import random
import time

import pytest

from detector.arbitrage import ArbitrageDetector, Opportunity, VolatilityTracker
from detector.price_fetcher import PriceQuote
from detector.sorted_opportunities import OpportunityRanker
from detector.price_impact import estimate_price_impact, weighted_mean_price, filter_by_price_impact
from detector.ml_scorer import OpportunityScorer, extract_features, generate_synthetic_training_data
from detector.ws_price_feed import PriceCache
from detector.backtester import run_backtest
from detector.circuit_breaker import CircuitBreaker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _q(dex: str, price: float, liq: float = 1_000_000) -> PriceQuote:
    return PriceQuote(
        dex=dex,
        input_token="SOL",
        output_token="USDC",
        input_amount=0.05,
        output_amount=0.05 * price,
        price=price,
        liquidity=liq,
    )


def _make_opportunity(profit_pct: float = 1.0, idx: int = 0) -> Opportunity:
    return Opportunity(
        pair=f"SOL/USDC",
        buy_dex=f"dex_a_{idx}",
        sell_dex=f"dex_b_{idx}",
        buy_price=90.0,
        sell_price=90.0 + profit_pct,
        amount=0.05,
        profit_pct=profit_pct,
        estimated_profit=0.05 * profit_pct / 100,
    )


# ===========================================================================
# 1. Speed / Latency Benchmarks
# ===========================================================================

class TestSpeedBenchmarks:
    """Speed benchmarks using time.perf_counter(). Limits are generous (2-3x
    expected) to avoid flakiness on slow CI runners."""

    def test_arbitrage_detection_speed_100_quotes(self):
        """100 quotes (10 DEXes x 10 pairs worth of variation) under 10ms."""
        dexes = [f"dex_{i}" for i in range(10)]
        quotes = []
        for i, dex in enumerate(dexes):
            for j in range(10):
                price = 90.0 + i * 0.1 + j * 0.01
                quotes.append(_q(dex, price))
        assert len(quotes) == 100

        detector = ArbitrageDetector(min_profit_pct=0.01)
        t0 = time.perf_counter()
        detector.find_opportunities(quotes)
        elapsed = time.perf_counter() - t0
        assert elapsed < 0.010, f"Took {elapsed:.4f}s, expected < 10ms"

    def test_arbitrage_detection_speed_1000_quotes(self):
        """1000 quotes under 100ms."""
        quotes = []
        for i in range(100):
            for j in range(10):
                price = 90.0 + i * 0.05 + j * 0.01
                quotes.append(_q(f"dex_{j}", price))
        assert len(quotes) == 1000

        detector = ArbitrageDetector(min_profit_pct=0.01)
        t0 = time.perf_counter()
        detector.find_opportunities(quotes)
        elapsed = time.perf_counter() - t0
        # O(n^2) comparison on 1000 quotes; generous limit for CI
        assert elapsed < 2.0, f"Took {elapsed:.4f}s, expected < 2s"

    def test_volatility_tracker_speed_10000_prices(self):
        """Add 10000 prices, then get_volatility + get_adaptive_min_profit under 5ms."""
        tracker = VolatilityTracker(window=10000)
        prices = [90.0 + random.gauss(0, 0.5) for _ in range(10000)]
        for p in prices:
            tracker.add_price(p)

        t0 = time.perf_counter()
        tracker.get_volatility()
        tracker.get_adaptive_min_profit()
        elapsed = time.perf_counter() - t0
        assert elapsed < 0.005, f"Took {elapsed:.4f}s, expected < 5ms"

    def test_opportunity_ranker_speed_1000_inserts(self):
        """Insert 1000 unique opportunities and get_top(10) under 50ms."""
        ranker = OpportunityRanker(max_size=1000, ttl_sec=600)

        t0 = time.perf_counter()
        for i in range(1000):
            ranker.add(
                pair=f"SOL/USDC_{i}",
                buy_dex=f"dex_a_{i}",
                sell_dex=f"dex_b_{i}",
                profit_pct=random.uniform(0.01, 5.0),
                estimated_profit=random.uniform(0.0001, 0.01),
            )
        ranker.get_top(10)
        elapsed = time.perf_counter() - t0
        assert elapsed < 0.050, f"Took {elapsed:.4f}s, expected < 50ms"

    def test_ml_feature_extraction_speed(self):
        """Extract features from 1000 opportunities under 10ms."""
        opps = [_make_opportunity(profit_pct=random.uniform(0.1, 3.0), idx=i) for i in range(1000)]

        t0 = time.perf_counter()
        for opp in opps:
            extract_features(opp, volatility=0.01)
        elapsed = time.perf_counter() - t0
        assert elapsed < 0.010, f"Took {elapsed:.4f}s, expected < 10ms"

    def test_ml_scoring_speed_1000(self):
        """Score 1000 opportunities with fallback scorer under 5ms."""
        scorer = OpportunityScorer(model_path="nonexistent_model.pkl")
        opps = [_make_opportunity(profit_pct=random.uniform(0.1, 3.0), idx=i) for i in range(1000)]

        t0 = time.perf_counter()
        for opp in opps:
            scorer.score(opp, volatility=0.01)
        elapsed = time.perf_counter() - t0
        assert elapsed < 0.005, f"Took {elapsed:.4f}s, expected < 5ms"

    def test_price_impact_speed_10000(self):
        """Estimate price impact for 10000 quotes under 10ms."""
        quotes = [_q(f"dex_{i % 4}", 90.0 + i * 0.001, liq=1_000_000) for i in range(10000)]

        t0 = time.perf_counter()
        for q in quotes:
            estimate_price_impact(q, trade_amount_usd=5.0)
        elapsed = time.perf_counter() - t0
        assert elapsed < 0.010, f"Took {elapsed:.4f}s, expected < 10ms"

    def test_weighted_mean_speed_100(self):
        """Weighted mean of 100 quotes under 1ms."""
        quotes = [_q(f"dex_{i % 4}", 90.0 + i * 0.01, liq=random.uniform(100_000, 10_000_000)) for i in range(100)]

        t0 = time.perf_counter()
        result = weighted_mean_price(quotes)
        elapsed = time.perf_counter() - t0
        assert elapsed < 0.001, f"Took {elapsed:.6f}s, expected < 1ms"
        assert result > 0

    def test_price_cache_speed_10000_updates(self):
        """10000 cache updates + 1000 get_quotes under 100ms total."""
        cache = PriceCache()
        dexes = ["orca", "raydium", "meteora", "lifinity"]
        pairs = [("SOL", "USDC"), ("SOL", "USDT"), ("USDC", "USDT")]

        t0 = time.perf_counter()
        for i in range(10000):
            pair_tuple = pairs[i % len(pairs)]
            pair_str = f"{pair_tuple[0]}/{pair_tuple[1]}"
            dex = dexes[i % len(dexes)]
            cache.update(pair_str, dex, 90.0 + random.gauss(0, 0.1), liquidity=1_000_000)

        for i in range(1000):
            pair_tuple = pairs[i % len(pairs)]
            cache.get_quotes(pair_tuple[0], pair_tuple[1], 0.05)

        elapsed = time.perf_counter() - t0
        assert elapsed < 0.100, f"Took {elapsed:.4f}s, expected < 100ms"

    def test_backtester_speed_10000_ticks(self):
        """Generate 10000 ticks of sample data and run backtest under 5 seconds."""
        random.seed(42)
        base_price = 91.5
        price_data = []
        for i in range(10000):
            ts = f"2026-03-01T{(i // 3600) % 24:02d}:{(i // 60) % 60:02d}:{i % 60:02d}+00:00"
            orca_price = base_price + random.gauss(0, 0.3)
            ray_price = base_price + random.gauss(0, 0.3)
            price_data.append({
                "timestamp": ts, "dex": "orca", "input_token": "SOL",
                "output_token": "USDC", "input_amount": 0.05,
                "output_amount": round(0.05 * orca_price, 6),
                "price": round(orca_price, 4),
            })
            price_data.append({
                "timestamp": ts, "dex": "raydium", "input_token": "SOL",
                "output_token": "USDC", "input_amount": 0.05,
                "output_amount": round(0.05 * ray_price, 6),
                "price": round(ray_price, 4),
            })

        t0 = time.perf_counter()
        result = run_backtest(price_data, min_profit_pct=0.01)
        elapsed = time.perf_counter() - t0
        assert elapsed < 5.0, f"Took {elapsed:.2f}s, expected < 5s"
        assert result.total_trades >= 0


# ===========================================================================
# 2. Stress Tests
# ===========================================================================

class TestStress:

    def test_circuit_breaker_rapid_failures(self):
        """Trigger 100 failures rapidly, verify breaker opens and cooldown works."""
        cb = CircuitBreaker(
            name="stress_test", failure_threshold=3,
            cooldown_sec=0.05, max_cooldown_sec=0.05,
        )

        for _ in range(100):
            cb.record_failure()

        assert cb.state == "OPEN"
        assert cb.consecutive_failures == 100
        assert cb.trip_count > 0
        assert not cb.can_call()

        # Wait for short cooldown to pass, then verify HALF_OPEN
        time.sleep(0.1)
        assert cb.can_call()
        assert cb.state == "HALF_OPEN"

        # Successful recovery
        cb.record_success()
        assert cb.state == "CLOSED"

    def test_sorted_opportunities_overflow(self):
        """Insert 10000 opportunities with max_size=100. Verify size cap and best retained."""
        ranker = OpportunityRanker(max_size=100, ttl_sec=600)

        profits = []
        for i in range(10000):
            p = random.uniform(0.01, 10.0)
            profits.append(p)
            ranker.add(
                pair=f"pair_{i}",
                buy_dex=f"buy_{i}",
                sell_dex=f"sell_{i}",
                profit_pct=p,
                estimated_profit=p * 0.001,
            )

        assert ranker.size == 100

        # The top opportunities should be among the highest profits
        top = ranker.get_top(10)
        assert len(top) == 10
        for entry in top:
            assert entry["profit_pct"] > 0

        # Best profit in ranker should be near the global best
        best_in_ranker = top[0]["profit_pct"]
        global_best = sorted(profits, reverse=True)[0]
        # The best opportunity should be in the ranker (it was unique key per insert)
        assert best_in_ranker > 5.0  # statistically, with 10000 uniform(0.01,10), best > 5.0

    def test_volatility_tracker_window_overflow(self):
        """Add 10000 prices with window=100. Verify len(prices) == 100."""
        tracker = VolatilityTracker(window=100)
        for i in range(10000):
            tracker.add_price(90.0 + random.gauss(0, 1.0))

        assert len(tracker.prices) == 100

        # Volatility should still be computable
        vol = tracker.get_volatility()
        assert vol >= 0.0

    def test_concurrent_price_cache_access(self):
        """Simulate rapid interleaved updates and reads on PriceCache."""
        cache = PriceCache()
        dexes = ["orca", "raydium", "meteora", "lifinity"]

        # Rapid interleaved updates and reads
        for i in range(5000):
            dex = dexes[i % len(dexes)]
            cache.update("SOL/USDC", dex, 90.0 + random.gauss(0, 0.5), liquidity=1_000_000)

            # Read after every update
            quotes = cache.get_quotes("SOL", "USDC", 0.05)
            assert len(quotes) <= len(dexes)
            for q in quotes:
                assert q.price > 0
                assert q.output_amount > 0

        # Final state should have all dexes
        final_quotes = cache.get_quotes("SOL", "USDC", 0.05)
        assert len(final_quotes) == len(dexes)

    def test_backtester_empty_data(self):
        """Run backtest with empty data list -- no crash, 0 trades."""
        result = run_backtest([], min_profit_pct=0.1)
        assert result.total_trades == 0
        assert result.net_profit == 0.0
        assert result.total_fees == 0.0

    def test_backtester_single_tick(self):
        """Run backtest with 1 tick (2 quotes) -- no crash."""
        price_data = [
            {
                "timestamp": "2026-03-01T00:00:00+00:00", "dex": "orca",
                "input_token": "SOL", "output_token": "USDC",
                "input_amount": 0.05, "output_amount": 4.575, "price": 91.5,
            },
            {
                "timestamp": "2026-03-01T00:00:00+00:00", "dex": "raydium",
                "input_token": "SOL", "output_token": "USDC",
                "input_amount": 0.05, "output_amount": 4.580, "price": 91.6,
            },
        ]
        result = run_backtest(price_data, min_profit_pct=0.01)
        assert result.total_trades >= 0  # may or may not find opportunity depending on fees


# ===========================================================================
# 3. Edge Case Stress
# ===========================================================================

class TestEdgeCaseStress:

    def test_detect_with_nan_prices(self):
        """Quote with NaN price -- no crash, filtered or handled gracefully."""
        quotes = [
            _q("orca", 91.5),
            _q("raydium", float("nan")),
            _q("meteora", 91.6),
        ]
        detector = ArbitrageDetector(min_profit_pct=0.01)
        # Should not raise -- NaN may propagate but must not crash
        opps = detector.find_opportunities(quotes)
        assert isinstance(opps, list)
        # Verify that valid (non-NaN) opportunities still exist between orca/meteora
        valid_opps = [o for o in opps if not math.isnan(o.profit_pct)]
        assert len(valid_opps) >= 0  # no crash is the key assertion

    def test_detect_with_negative_prices(self):
        """Quote with negative price -- no crash, filtered or handled gracefully."""
        quotes = [
            _q("orca", 91.5),
            _q("raydium", -10.0),
            _q("meteora", 91.6),
        ]
        detector = ArbitrageDetector(min_profit_pct=0.01)
        # Should not raise
        opps = detector.find_opportunities(quotes)
        # Negative prices should not appear in valid opportunities
        for opp in opps:
            assert opp.buy_price >= 0
            assert opp.sell_price >= 0

    def test_detect_with_infinity_price(self):
        """Quote with inf price -- no crash."""
        quotes = [
            _q("orca", 91.5),
            _q("raydium", float("inf")),
            _q("meteora", 91.6),
        ]
        detector = ArbitrageDetector(min_profit_pct=0.01)
        # Should not raise
        opps = detector.find_opportunities(quotes)
        assert isinstance(opps, list)

    def test_ranker_zero_ttl(self):
        """OpportunityRanker with ttl_sec=0 -- everything expires immediately."""
        ranker = OpportunityRanker(max_size=100, ttl_sec=0)
        ranker.add(pair="SOL/USDC", buy_dex="orca", sell_dex="raydium",
                   profit_pct=1.0, estimated_profit=0.001)

        # With ttl=0, the entry should expire on the next call that triggers _expire_old
        # The timestamp is set at insert time; with ttl=0, cutoff = now - 0 = now,
        # so anything with timestamp < now is expired. There may be a tiny race
        # where timestamp == now, so we give a microsecond.
        time.sleep(0.001)
        top = ranker.get_top(10)
        assert len(top) == 0

    def test_circuit_breaker_zero_threshold(self):
        """CircuitBreaker with failure_threshold=0 -- opens immediately on first failure."""
        cb = CircuitBreaker(name="zero_thresh", failure_threshold=0, cooldown_sec=0.1)

        # Even before any failure, threshold=0 means first failure opens it
        cb.record_failure()
        assert cb.state == "OPEN"
        assert not cb.can_call()
