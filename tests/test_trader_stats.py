"""Tests for detector.trader_stats — smart trader analytics."""

from detector.trader_stats import TraderStats


class TestRecordAndSummarize:
    def test_record_and_summarize(self):
        ts = TraderStats()
        # Record 5 trades: 3 wins, 2 losses
        ts.record_trade("SOL/USDC", "orca", "raydium", 0.5, 0.01)
        ts.record_trade("SOL/USDC", "raydium", "orca", 0.3, 0.005)
        ts.record_trade("SOL/USDT", "orca", "raydium", 0.4, 0.008)
        ts.record_trade("SOL/USDC", "orca", "raydium", 0.2, 0.003, success=False)
        ts.record_trade("SOL/USDT", "raydium", "orca", 0.1, 0.002, success=False)

        summary = ts.get_performance_summary()
        assert summary["total_trades"] == 5
        assert summary["wins"] == 3
        assert summary["losses"] == 2
        assert summary["win_rate"] == 60.0
        assert summary["total_profit"] > 0
        assert summary["total_loss"] > 0
        assert summary["net_pnl"] == round(0.01 + 0.005 + 0.008 - 0.003 - 0.002, 6)
        assert "sharpe_ratio" in summary
        assert "best_hours" in summary
        assert "best_dex_routes" in summary

    def test_empty_summary(self):
        ts = TraderStats()
        summary = ts.get_performance_summary()
        assert summary == {"total_trades": 0}


class TestBestHours:
    def test_best_hours(self):
        ts = TraderStats()
        # Manually inject hourly data to avoid time dependency
        ts.hourly_profits[10] = [0.01, 0.02, 0.03]
        ts.hourly_profits[14] = [0.05]
        ts.hourly_profits[3] = [-0.01, -0.02]

        best = ts.get_best_hours(top_n=3)
        assert len(best) == 3
        # Hour 10 total=0.06, hour 14 total=0.05, hour 3 total=-0.03
        assert best[0]["hour"] == 10
        assert best[0]["total_profit"] == round(0.06, 6)
        assert best[1]["hour"] == 14
        assert best[2]["hour"] == 3

    def test_best_hours_empty(self):
        ts = TraderStats()
        assert ts.get_best_hours() == []


class TestConsecutiveTracking:
    def test_consecutive_wins(self):
        ts = TraderStats()
        ts.record_trade("SOL/USDC", "orca", "raydium", 0.5, 0.01)
        ts.record_trade("SOL/USDC", "orca", "raydium", 0.3, 0.005)
        ts.record_trade("SOL/USDC", "orca", "raydium", 0.4, 0.008)
        assert ts.consecutive_wins == 3
        assert ts.max_consecutive_wins == 3
        assert ts.consecutive_losses == 0

    def test_consecutive_losses(self):
        ts = TraderStats()
        ts.record_trade("SOL/USDC", "orca", "raydium", 0.5, 0.01, success=False)
        ts.record_trade("SOL/USDC", "orca", "raydium", 0.3, 0.005, success=False)
        assert ts.consecutive_losses == 2
        assert ts.max_consecutive_losses == 2
        assert ts.consecutive_wins == 0

    def test_streak_reset_and_max_preserved(self):
        ts = TraderStats()
        # 3 wins
        ts.record_trade("SOL/USDC", "orca", "raydium", 0.5, 0.01)
        ts.record_trade("SOL/USDC", "orca", "raydium", 0.3, 0.005)
        ts.record_trade("SOL/USDC", "orca", "raydium", 0.4, 0.008)
        assert ts.max_consecutive_wins == 3
        # 1 loss resets current streak
        ts.record_trade("SOL/USDC", "orca", "raydium", 0.2, 0.003, success=False)
        assert ts.consecutive_wins == 0
        assert ts.consecutive_losses == 1
        # max_consecutive_wins preserved
        assert ts.max_consecutive_wins == 3
        # 2 more wins — new streak is shorter
        ts.record_trade("SOL/USDC", "orca", "raydium", 0.5, 0.01)
        ts.record_trade("SOL/USDC", "orca", "raydium", 0.5, 0.01)
        assert ts.consecutive_wins == 2
        assert ts.max_consecutive_wins == 3  # still the old max


class TestBestDexPairs:
    def test_best_dex_pairs(self):
        ts = TraderStats()
        ts.record_trade("SOL/USDC", "orca", "raydium", 0.5, 0.01)
        ts.record_trade("SOL/USDC", "orca", "raydium", 0.3, 0.02)
        ts.record_trade("SOL/USDC", "raydium", "orca", 0.4, 0.005)

        best = ts.get_best_dex_pairs(top_n=2)
        assert len(best) == 2
        assert best[0]["route"] == "orca->raydium"
        assert best[0]["trade_count"] == 2
        assert best[1]["route"] == "raydium->orca"


class TestBestDays:
    def test_best_days_returns_all_seven(self):
        ts = TraderStats()
        days = ts.get_best_days()
        assert len(days) == 7
        assert days[0]["day"] == "Monday"
        assert days[6]["day"] == "Sunday"
        # All zeros when no trades
        for d in days:
            assert d["trade_count"] == 0
