"""Smart trader analytics — tracks bot performance patterns and identifies optimal conditions."""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


@dataclass
class TradeRecord:
    """A single trade execution record for analytics."""
    timestamp: datetime
    pair: str
    buy_dex: str
    sell_dex: str
    profit_pct: float
    estimated_profit: float
    success: bool
    hour: int
    day_of_week: int  # 0=Monday


class TraderStats:
    """Tracks and analyzes bot trading performance over time.

    Inspired by Mobula's smart trader classification system.
    Identifies:
    - Best hours and days for trading
    - Most profitable DEX combinations
    - Win rate trends
    - Performance metrics (Sharpe-like ratio)
    """

    def __init__(self) -> None:
        self.trades: list[TradeRecord] = []
        self.hourly_profits: dict[int, list[float]] = defaultdict(list)
        self.daily_profits: dict[int, list[float]] = defaultdict(list)
        self.dex_pair_profits: dict[str, list[float]] = defaultdict(list)
        self.consecutive_wins: int = 0
        self.max_consecutive_wins: int = 0
        self.consecutive_losses: int = 0
        self.max_consecutive_losses: int = 0

    def record_trade(
        self,
        pair: str,
        buy_dex: str,
        sell_dex: str,
        profit_pct: float,
        estimated_profit: float,
        success: bool = True,
    ) -> None:
        """Record a trade and update all analytics."""
        now = datetime.now(timezone.utc)
        trade = TradeRecord(
            timestamp=now,
            pair=pair,
            buy_dex=buy_dex,
            sell_dex=sell_dex,
            profit_pct=profit_pct,
            estimated_profit=estimated_profit,
            success=success,
            hour=now.hour,
            day_of_week=now.weekday(),
        )
        self.trades.append(trade)

        # Update hourly/daily stats
        self.hourly_profits[now.hour].append(estimated_profit if success else -estimated_profit)
        self.daily_profits[now.weekday()].append(estimated_profit if success else -estimated_profit)

        # Update DEX pair stats
        dex_key = f"{buy_dex}->{sell_dex}"
        self.dex_pair_profits[dex_key].append(estimated_profit if success else -estimated_profit)

        # Track consecutive wins/losses
        if success:
            self.consecutive_wins += 1
            self.consecutive_losses = 0
            self.max_consecutive_wins = max(self.max_consecutive_wins, self.consecutive_wins)
        else:
            self.consecutive_losses += 1
            self.consecutive_wins = 0
            self.max_consecutive_losses = max(self.max_consecutive_losses, self.consecutive_losses)

    def get_best_hours(self, top_n: int = 5) -> list[dict]:
        """Get the most profitable hours of the day."""
        hour_stats = []
        for hour, profits in self.hourly_profits.items():
            total = sum(profits)
            count = len(profits)
            win_rate = sum(1 for p in profits if p > 0) / count * 100 if count else 0
            hour_stats.append({
                "hour": hour,
                "total_profit": round(total, 6),
                "trade_count": count,
                "avg_profit": round(total / count, 6) if count else 0,
                "win_rate": round(win_rate, 1),
            })
        hour_stats.sort(key=lambda x: x["total_profit"], reverse=True)
        return hour_stats[:top_n]

    def get_best_days(self) -> list[dict]:
        """Get performance by day of week."""
        day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        day_stats = []
        for dow in range(7):
            profits = self.daily_profits.get(dow, [])
            total = sum(profits)
            count = len(profits)
            day_stats.append({
                "day": day_names[dow],
                "total_profit": round(total, 6),
                "trade_count": count,
                "avg_profit": round(total / count, 6) if count else 0,
            })
        return day_stats

    def get_best_dex_pairs(self, top_n: int = 5) -> list[dict]:
        """Get the most profitable DEX routing combinations."""
        dex_stats = []
        for dex_key, profits in self.dex_pair_profits.items():
            total = sum(profits)
            count = len(profits)
            dex_stats.append({
                "route": dex_key,
                "total_profit": round(total, 6),
                "trade_count": count,
                "avg_profit": round(total / count, 6) if count else 0,
            })
        dex_stats.sort(key=lambda x: x["total_profit"], reverse=True)
        return dex_stats[:top_n]

    def get_performance_summary(self) -> dict:
        """Get overall performance metrics."""
        if not self.trades:
            return {"total_trades": 0}

        profits = [t.estimated_profit for t in self.trades if t.success]
        losses = [t.estimated_profit for t in self.trades if not t.success]
        all_pnl = [t.estimated_profit if t.success else -t.estimated_profit for t in self.trades]

        total_profit = sum(profits)
        total_loss = sum(losses)
        win_count = len(profits)
        loss_count = len(losses)
        total = win_count + loss_count

        # Simple Sharpe-like ratio: mean / std_dev
        if len(all_pnl) > 1:
            mean_pnl = sum(all_pnl) / len(all_pnl)
            variance = sum((p - mean_pnl) ** 2 for p in all_pnl) / len(all_pnl)
            std_dev = variance ** 0.5
            sharpe = mean_pnl / std_dev if std_dev > 0 else 0
        else:
            sharpe = 0

        return {
            "total_trades": total,
            "wins": win_count,
            "losses": loss_count,
            "win_rate": round(win_count / total * 100, 1) if total else 0,
            "total_profit": round(total_profit, 6),
            "total_loss": round(total_loss, 6),
            "net_pnl": round(total_profit - total_loss, 6),
            "avg_profit_per_trade": round(sum(all_pnl) / len(all_pnl), 6) if all_pnl else 0,
            "sharpe_ratio": round(sharpe, 4),
            "max_consecutive_wins": self.max_consecutive_wins,
            "max_consecutive_losses": self.max_consecutive_losses,
            "best_hours": self.get_best_hours(3),
            "best_dex_routes": self.get_best_dex_pairs(3),
        }
