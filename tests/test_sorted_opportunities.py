"""Tests for the sorted opportunities ranker."""

from detector.sorted_opportunities import OpportunityRanker


def test_add_and_get_top():
    ranker = OpportunityRanker(max_size=10)
    ranker.add("SOL/USDC", "orca", "raydium", profit_pct=0.5, estimated_profit=0.01)
    ranker.add("SOL/USDT", "raydium", "orca", profit_pct=0.8, estimated_profit=0.02)

    top = ranker.get_top(5)
    assert len(top) == 2
    assert top[0]["profit_pct"] == 0.8  # best first
    assert top[1]["profit_pct"] == 0.5


def test_deduplication():
    ranker = OpportunityRanker()
    assert ranker.add("SOL/USDC", "orca", "raydium", 0.5) is True
    assert ranker.add("SOL/USDC", "orca", "raydium", 0.6) is False  # duplicate
    assert ranker.size == 1


def test_max_size_cap():
    ranker = OpportunityRanker(max_size=3)
    ranker.add("A", "d1", "d2", 0.1)
    ranker.add("B", "d1", "d2", 0.5)
    ranker.add("C", "d1", "d2", 0.3)
    ranker.add("D", "d1", "d2", 0.9)  # should evict worst
    assert ranker.size == 3
    top = ranker.get_top(10)
    profits = [t["profit_pct"] for t in top]
    assert 0.1 not in profits  # worst should be evicted


def test_has_recent():
    ranker = OpportunityRanker(ttl_sec=60)
    ranker.add("SOL/USDC", "orca", "raydium", 0.5)
    assert ranker.has_recent("SOL/USDC", "orca", "raydium") is True
    assert ranker.has_recent("SOL/USDT", "orca", "raydium") is False


def test_ttl_expiry():
    ranker = OpportunityRanker(ttl_sec=0.0)  # expire immediately
    ranker.add("SOL/USDC", "orca", "raydium", 0.5)
    import time
    time.sleep(0.01)
    top = ranker.get_top(10)
    assert len(top) == 0  # expired


def test_stats():
    ranker = OpportunityRanker()
    ranker.add("SOL/USDC", "orca", "raydium", 0.3)
    ranker.add("SOL/USDT", "meteora", "raydium", 0.7)
    s = ranker.stats()
    assert s["count"] == 2
    assert s["best_profit_pct"] == 0.7
    assert s["unique_pairs"] == 2
