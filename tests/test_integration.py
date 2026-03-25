"""Integration tests -- full arbitrage pipeline from price fetch to trade execution."""

from __future__ import annotations

import asyncio
import time

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from detector.arbitrage import ArbitrageDetector, Opportunity, VolatilityTracker
from detector.price_fetcher import PriceQuote
from detector.health import BotStats
from detector.price_impact import (
    estimate_price_impact,
    filter_by_price_impact,
    weighted_mean_price,
)
from detector.sorted_opportunities import OpportunityRanker
from detector.ml_scorer import (
    OpportunityScorer,
    extract_features,
    generate_synthetic_training_data,
    train_model,
)
from detector.executor_bridge import ExecutorBridge


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _q(dex, price, liq=0, input_tok="SOL", output_tok="USDC", amount=0.05):
    """Build a PriceQuote with sensible defaults."""
    return PriceQuote(
        dex=dex,
        input_token=input_tok,
        output_token=output_tok,
        input_amount=amount,
        output_amount=amount * price,
        price=price,
        liquidity=liq,
    )


# ===================================================================
# 1. Full Pipeline Tests
# ===================================================================


class TestFullPipeline:
    """Integration tests that exercise the full detection-to-scoring pipeline."""

    def test_full_pipeline_detect_to_score(self):
        """4 DEXes with different prices/liquidities go through
        ArbitrageDetector -> filter_by_price_impact -> OpportunityRanker -> ML scorer.
        """
        quotes = [
            _q("orca", 100.0, liq=500_000),
            _q("raydium", 100.8, liq=400_000),
            _q("meteora", 100.3, liq=300_000),
            _q("lifinity", 99.5, liq=200_000),
        ]

        # Step 1: detect
        detector = ArbitrageDetector(min_profit_pct=0.05)
        opps = detector.find_opportunities(quotes)
        assert len(opps) > 0, "Should detect at least one opportunity"

        # Step 2: filter by price impact (trade_amount_usd ~ 0.05 SOL * 100 = 5 USD)
        filtered = filter_by_price_impact(quotes, trade_amount_usd=5.0, max_impact_pct=1.0)
        assert len(filtered) == len(quotes), "All quotes should pass with high liquidity"

        # Step 3: rank and dedup
        ranker = OpportunityRanker(max_size=50, ttl_sec=60.0)
        added_count = 0
        for opp in opps:
            if ranker.add(opp.pair, opp.buy_dex, opp.sell_dex,
                          opp.profit_pct, opp.estimated_profit):
                added_count += 1
        assert added_count == len(opps), "All opportunities should be new"
        top = ranker.get_top(10)
        assert top[0]["profit_pct"] >= top[-1]["profit_pct"], "Should be sorted descending"

        # Step 4: ML scorer (no model loaded => score=1.0 => always execute)
        scorer = OpportunityScorer(model_path="/tmp/nonexistent_model.pkl")
        for opp in opps:
            assert scorer.should_execute(opp, volatility=0.01) is True

    def test_pipeline_no_opportunity_equal_prices(self):
        """All 4 DEXes return identical prices -> 0 opportunities."""
        quotes = [
            _q("orca", 100.0, liq=500_000),
            _q("raydium", 100.0, liq=400_000),
            _q("meteora", 100.0, liq=300_000),
            _q("lifinity", 100.0, liq=200_000),
        ]
        detector = ArbitrageDetector(min_profit_pct=0.1)
        opps = detector.find_opportunities(quotes)
        assert len(opps) == 0

    def test_pipeline_filters_low_liquidity_pools(self):
        """One DEX has great price but tiny liquidity (100 USD) -> filtered by price_impact."""
        quotes = [
            _q("orca", 100.0, liq=500_000),
            _q("raydium", 102.0, liq=100),      # great price, tiny pool
            _q("meteora", 100.1, liq=300_000),
        ]
        # trade_amount_usd = 0.05 * 100 = 5 USD; impact on 100 USD pool = 5/(2*100)*100 = 2.5%
        filtered = filter_by_price_impact(quotes, trade_amount_usd=5.0, max_impact_pct=1.0)
        dexes = {q.dex for q in filtered}
        assert "raydium" not in dexes, "Low-liquidity raydium quote should be filtered"
        assert "orca" in dexes
        assert "meteora" in dexes

    def test_triangular_arb_full_pipeline(self):
        """Profitable triangular path SOL->USDC->USDT->SOL is detected."""
        detector = ArbitrageDetector(min_profit_pct=0.05)

        # Leg prices chosen so that the round-trip is profitable:
        # 0.05 SOL -> 7.60 USDC -> 7.70 USDT -> 0.0520 SOL
        all_quotes = {
            "SOL/USDC": [
                PriceQuote(dex="orca", input_token="SOL", output_token="USDC",
                           input_amount=0.05, output_amount=7.60, price=152.0, liquidity=500_000),
            ],
            "USDC/USDT": [
                PriceQuote(dex="raydium", input_token="USDC", output_token="USDT",
                           input_amount=7.60, output_amount=7.70, price=1.0132, liquidity=1_000_000),
            ],
            "USDT/SOL": [
                PriceQuote(dex="meteora", input_token="USDT", output_token="SOL",
                           input_amount=7.70, output_amount=0.0520, price=0.00675, liquidity=500_000),
            ],
        }
        opps = detector.find_triangular_opportunities(all_quotes, start_token="SOL", start_amount=0.05)
        assert len(opps) >= 1, "Should detect triangular arb opportunity"
        assert opps[0].profit_pct > 0

    def test_triangular_arb_no_profit(self):
        """Triangular path that loses money after fees -> 0 opportunities."""
        detector = ArbitrageDetector(min_profit_pct=0.05)

        # Round-trip returns less than started: 0.05 -> 7.50 -> 7.49 -> 0.0498
        all_quotes = {
            "SOL/USDC": [
                PriceQuote(dex="orca", input_token="SOL", output_token="USDC",
                           input_amount=0.05, output_amount=7.50, price=150.0, liquidity=500_000),
            ],
            "USDC/USDT": [
                PriceQuote(dex="raydium", input_token="USDC", output_token="USDT",
                           input_amount=7.50, output_amount=7.49, price=0.9987, liquidity=1_000_000),
            ],
            "USDT/SOL": [
                PriceQuote(dex="meteora", input_token="USDT", output_token="SOL",
                           input_amount=7.49, output_amount=0.0498, price=0.00665, liquidity=500_000),
            ],
        }
        opps = detector.find_triangular_opportunities(all_quotes, start_token="SOL", start_amount=0.05)
        assert len(opps) == 0

    def test_volatility_tracker_adapts_detector(self):
        """50 stable prices then 50 volatile prices shift min_profit_pct from 0.07 to 0.25."""
        tracker = VolatilityTracker(window=100)

        # Phase 1: stable prices
        for _ in range(50):
            tracker.add_price(100.0)
        assert tracker.get_adaptive_min_profit() == pytest.approx(0.07)

        # Phase 2: volatile prices overwrite the stable ones
        for i in range(100):
            tracker.add_price(50.0 if i % 2 == 0 else 150.0)
        assert tracker.get_adaptive_min_profit() == pytest.approx(0.25)

    def test_opportunity_ranker_dedup_across_cycles(self):
        """Dedup prevents re-adding the same opportunity within TTL; allows after expiry."""
        ranker = OpportunityRanker(max_size=50, ttl_sec=0.2)

        assert ranker.add("SOL/USDC", "orca", "raydium", 0.5, 0.001) is True
        assert ranker.add("SOL/USDC", "orca", "raydium", 0.5, 0.001) is False  # dup

        # Wait for TTL expiry
        time.sleep(0.3)
        assert ranker.add("SOL/USDC", "orca", "raydium", 0.5, 0.001) is True  # allowed again

    def test_ml_scorer_filters_bad_opportunities(self, tmp_path):
        """A trained model rejects at least some low-confidence opportunities."""
        model_path = tmp_path / "test_model.pkl"

        # Train on synthetic data
        data = generate_synthetic_training_data(500)
        metrics = train_model(data, output_path=model_path)
        assert "error" not in metrics
        assert model_path.exists()

        scorer = OpportunityScorer(model_path=model_path)
        assert scorer.model is not None

        # Create a range of opportunities: some should be rejected
        results = []
        for profit in [0.05, 0.1, 0.3, 0.5, 1.0, 1.5]:
            opp = Opportunity(
                pair="SOL/USDC", buy_dex="orca", sell_dex="raydium",
                buy_price=100.0, sell_price=100.0 + profit,
                amount=0.05, profit_pct=profit, estimated_profit=profit * 0.05,
            )
            results.append(scorer.should_execute(opp, volatility=0.03))

        # The model should NOT accept every single one (some low-profit should be rejected)
        assert not all(results), "Trained model should reject at least one low-profit opportunity"

    @pytest.mark.asyncio
    async def test_executor_bridge_swap_with_retry_integration(self):
        """Mock _run to fail twice then succeed; swap_with_retry returns success after 3 attempts."""
        bridge = ExecutorBridge(
            executor_path="/fake/executor",
            rpc_url="https://fake.rpc",
            keypair_path="/fake/keypair.json",
        )

        call_count = 0

        async def mock_run(args):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return {"status": "error", "message": "rpc timeout"}
            return {"status": "ok", "tx_hash": "abc123"}

        bridge._run = mock_run

        result = await bridge.swap_with_retry(
            from_token="SOL", to_token="USDC", amount=0.05,
            dex="raydium", min_out=7.0, dry_run=True,
            max_retries=3, base_delay=0.01,
        )
        assert result["status"] == "ok"
        assert result["tx_hash"] == "abc123"
        assert call_count == 3

    def test_bot_stats_full_lifecycle(self):
        """BotStats records multiple trades and to_dict() returns correct aggregated values."""
        stats = BotStats(dry_run=False)
        stats.balance_sol = 10.0

        # Record trades
        profits = [0.001, 0.002, -0.0005, 0.003]
        for p in profits:
            stats.trades_total += 1
            stats.profit_total += p
            stats.record_trade(p)

        stats.opportunities_seen = 15
        stats.errors_total = 2

        d = stats.to_dict()
        assert d["trades_total"] == 4
        assert d["profit_total"] == pytest.approx(sum(profits), abs=1e-9)
        assert d["balance_sol"] == 10.0
        assert d["opportunities_seen"] == 15
        assert d["errors_total"] == 2
        assert d["dry_run"] is False
        assert d["status"] == "running"

        # PnL curve entries
        assert len(stats.pnl_curve) == 4
        assert stats.pnl_curve[0]["profit"] == 0.001
        assert stats.pnl_curve[-1]["profit"] == 0.003

    def test_weighted_mean_favors_high_liquidity(self):
        """Weighted mean is closer to the high-liquidity DEX price."""
        q_high = _q("orca", 100.0, liq=1_000_000)
        q_low = _q("raydium", 110.0, liq=1_000)

        wmean = weighted_mean_price([q_high, q_low])
        # Should be very close to 100.0 since orca has 1000x more liquidity
        assert abs(wmean - 100.0) < abs(wmean - 110.0), "Should favor high-liquidity price"
        assert wmean < 101.0, "Weighted mean should be close to 100.0"

    def test_price_impact_blocks_large_trade_small_pool(self):
        """Trade 1000 USD in a pool with 500 USD liquidity -> >50% impact -> filtered."""
        q = _q("orca", 100.0, liq=500)
        impact = estimate_price_impact(q, trade_amount_usd=1000.0)
        assert impact > 50.0, f"Impact should be >50%, got {impact}"

        filtered = filter_by_price_impact([q], trade_amount_usd=1000.0, max_impact_pct=5.0)
        assert len(filtered) == 0, "Quote should be filtered out"


# ===================================================================
# 2. Edge Cases
# ===================================================================


class TestEdgeCases:
    """Edge cases that must not crash and must produce sane results."""

    def test_single_quote_no_crash(self):
        """1 quote -> empty list, no error."""
        detector = ArbitrageDetector(min_profit_pct=0.1)
        opps = detector.find_opportunities([_q("orca", 100.0)])
        assert opps == []

    def test_empty_quotes_no_crash(self):
        """Empty list -> empty list, no error."""
        detector = ArbitrageDetector(min_profit_pct=0.1)
        opps = detector.find_opportunities([])
        assert opps == []

    def test_negative_profit_filtered(self):
        """Quotes where spread < fees -> 0 opportunities."""
        detector = ArbitrageDetector(min_profit_pct=0.1)
        # Tiny spread: 100.0 vs 100.001 -- well below any fee
        quotes = [
            _q("orca", 100.0, liq=500_000),
            _q("raydium", 100.001, liq=500_000),
        ]
        opps = detector.find_opportunities(quotes)
        assert len(opps) == 0

    def test_extreme_price_difference(self):
        """One DEX returns 100, another 0.01 -> no crash, opportunity detected."""
        detector = ArbitrageDetector(min_profit_pct=0.1)
        quotes = [
            _q("orca", 0.01, liq=500_000),
            _q("raydium", 100.0, liq=500_000),
        ]
        opps = detector.find_opportunities(quotes)
        # The huge spread should produce an opportunity (buy low, sell high)
        assert len(opps) >= 1
        assert opps[0].profit_pct > 0

    def test_zero_liquidity_quotes_handled(self):
        """All quotes have liquidity=0 -> weighted_mean falls back to simple mean."""
        q1 = _q("orca", 100.0, liq=0)
        q2 = _q("raydium", 110.0, liq=0)
        wmean = weighted_mean_price([q1, q2])
        expected = (100.0 + 110.0) / 2.0
        assert wmean == pytest.approx(expected)

    def test_zero_amount_trade(self):
        """Amount=0 -> no crash."""
        q = _q("orca", 100.0, liq=500_000, amount=0)
        # price_impact should not crash
        impact = estimate_price_impact(q, trade_amount_usd=0)
        assert impact == 0.0

        # find_opportunities should not crash
        detector = ArbitrageDetector(min_profit_pct=0.1)
        quotes = [
            _q("orca", 100.0, amount=0),
            _q("raydium", 101.0, amount=0),
        ]
        opps = detector.find_opportunities(quotes)
        # With amount=0, output_amount=0 for both => no spread => 0 opportunities
        assert isinstance(opps, list)
