"""Backtesting engine — replay historical price data through the arbitrage detector."""

from __future__ import annotations

import csv
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from detector.arbitrage import ArbitrageDetector, Opportunity, VolatilityTracker
from detector.price_fetcher import PriceQuote

logger = logging.getLogger(__name__)


@dataclass
class BacktestTrade:
    """A simulated trade from backtesting."""
    timestamp: str
    pair: str
    buy_dex: str
    sell_dex: str
    amount: float
    profit_pct: float
    estimated_profit: float
    fees: float


@dataclass
class BacktestResult:
    """Summary of a backtest run."""
    total_trades: int = 0
    total_profit: float = 0.0
    total_fees: float = 0.0
    net_profit: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    best_hour: int = -1
    worst_hour: int = -1
    trades: list[BacktestTrade] = field(default_factory=list)
    hourly_profit: dict[int, float] = field(default_factory=lambda: {h: 0.0 for h in range(24)})

    def summary(self) -> str:
        """Generate a human-readable summary."""
        lines = [
            "=== Backtest Results ===",
            f"Total trades:    {self.total_trades}",
            f"Total profit:    {self.total_profit:.6f}",
            f"Total fees:      {self.total_fees:.6f}",
            f"Net profit:      {self.net_profit:.6f}",
            f"Max drawdown:    {self.max_drawdown:.6f}",
            f"Win rate:        {self.win_rate:.1f}%",
            f"Best hour (UTC): {self.best_hour}:00",
            f"Worst hour (UTC):{self.worst_hour}:00",
            "",
            "Hourly profit distribution:",
        ]
        for hour in range(24):
            p = self.hourly_profit.get(hour, 0)
            bar = "\u2588" * max(0, int(p * 10000)) if p > 0 else ""
            lines.append(f"  {hour:02d}:00  {p:+.6f}  {bar}")
        return "\n".join(lines)


def load_price_csv(path: str) -> list[dict]:
    """Load historical price data from CSV.

    Expected CSV columns: timestamp, dex, input_token, output_token, input_amount, output_amount, price
    """
    rows = []
    csv_path = Path(path)
    if not csv_path.exists():
        raise FileNotFoundError(f"Price data file not found: {path}")

    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def load_price_jsonl(path: str) -> list[dict]:
    """Load historical price data from JSON lines format.

    Each line: {"timestamp": "...", "dex": "...", "input_token": "...", "output_token": "...",
                "input_amount": 0.05, "output_amount": 4.58, "price": 91.6}
    """
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def run_backtest(
    price_data: list[dict],
    min_profit_pct: float = 0.1,
    trade_amount: float = 0.05,
    fee_per_trade_sol: float = 0.00015,
    use_adaptive_thresholds: bool = True,
    simulated_slippage_pct: float = 0.15,
    simulated_mev_pct: float = 0.05,
) -> BacktestResult:
    """Run a backtest on historical price data.

    Groups price rows by timestamp, then runs the arbitrage detector on each group.

    simulated_slippage_pct: average slippage per leg (0.15% default)
    simulated_mev_pct: average MEV extraction per trade (0.05% default)

    NOTE: Real-world results will likely be WORSE than backtest results.
    This simulation adds random slippage and MEV but cannot model:
    - Network latency between detection and execution
    - Price movement during block confirmation
    - Adversarial MEV strategies (sandwich attacks)
    """
    import random
    detector = ArbitrageDetector(min_profit_pct=min_profit_pct)
    vol_tracker = VolatilityTracker() if use_adaptive_thresholds else None
    result = BacktestResult()

    # Group rows by timestamp
    groups: dict[str, list[dict]] = {}
    for row in price_data:
        ts = row["timestamp"]
        groups.setdefault(ts, []).append(row)

    cumulative_profit = 0.0
    peak_profit = 0.0

    for ts in sorted(groups.keys()):
        rows = groups[ts]
        quotes = []
        for r in rows:
            q = PriceQuote(
                dex=r["dex"],
                input_token=r["input_token"],
                output_token=r["output_token"],
                input_amount=float(r.get("input_amount", trade_amount)),
                output_amount=float(r["output_amount"]),
                price=float(r["price"]),
            )
            quotes.append(q)
            if vol_tracker:
                vol_tracker.add_price(q.price)

        if vol_tracker:
            detector.min_profit_pct = vol_tracker.get_adaptive_min_profit()

        opportunities = detector.find_opportunities(quotes)

        for opp in opportunities:
            # Parse hour from timestamp for hourly stats
            try:
                hour = datetime.fromisoformat(ts.replace("Z", "+00:00")).hour
            except (ValueError, AttributeError):
                hour = 0

            # Apply simulated slippage + MEV (realistic estimate)
            slippage_cost = opp.estimated_profit * random.uniform(0, simulated_slippage_pct * 2) / 100
            mev_cost = opp.estimated_profit * random.uniform(0, simulated_mev_pct * 2) / 100
            realized_profit = opp.estimated_profit - slippage_cost - mev_cost

            trade = BacktestTrade(
                timestamp=ts,
                pair=opp.pair,
                buy_dex=opp.buy_dex,
                sell_dex=opp.sell_dex,
                amount=opp.amount,
                profit_pct=opp.profit_pct,
                estimated_profit=opp.estimated_profit,
                fees=fee_per_trade_sol * 2,
            )
            result.trades.append(trade)
            result.total_trades += 1
            result.total_profit += realized_profit
            result.total_fees += trade.fees
            result.hourly_profit[hour] = result.hourly_profit.get(hour, 0) + realized_profit

            cumulative_profit += realized_profit - trade.fees
            peak_profit = max(peak_profit, cumulative_profit)
            drawdown = peak_profit - cumulative_profit
            result.max_drawdown = max(result.max_drawdown, drawdown)

    result.net_profit = result.total_profit - result.total_fees
    if result.total_trades > 0:
        winning = sum(1 for t in result.trades if t.estimated_profit > t.fees)
        result.win_rate = (winning / result.total_trades) * 100

    if result.hourly_profit:
        result.best_hour = max(result.hourly_profit, key=result.hourly_profit.get)
        result.worst_hour = min(result.hourly_profit, key=result.hourly_profit.get)

    return result


def generate_sample_data(output_path: str, num_ticks: int = 1000) -> None:
    """Generate sample historical price data for testing the backtester."""
    import random
    from datetime import timedelta, timezone

    base_price = 91.5
    start = datetime(2026, 3, 1, tzinfo=timezone.utc)

    with open(output_path, "w") as f:
        for i in range(num_ticks):
            ts = (start + timedelta(seconds=i * 3)).isoformat()
            # Orca price with some noise
            orca_price = base_price + random.gauss(0, 0.3)
            orca_out = 0.05 * orca_price
            # Raydium price with slightly different noise
            ray_price = base_price + random.gauss(0, 0.3)
            ray_out = 0.05 * ray_price

            f.write(json.dumps({"timestamp": ts, "dex": "orca", "input_token": "SOL",
                               "output_token": "USDC", "input_amount": 0.05,
                               "output_amount": round(orca_out, 6), "price": round(orca_price, 4)}) + "\n")
            f.write(json.dumps({"timestamp": ts, "dex": "raydium", "input_token": "SOL",
                               "output_token": "USDC", "input_amount": 0.05,
                               "output_amount": round(ray_out, 6), "price": round(ray_price, 4)}) + "\n")


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m detector.backtester <price_data.jsonl>")
        print("       python -m detector.backtester --generate-sample sample_data.jsonl")
        sys.exit(1)

    if sys.argv[1] == "--generate-sample":
        out = sys.argv[2] if len(sys.argv) > 2 else "sample_prices.jsonl"
        generate_sample_data(out)
        print(f"Generated sample data: {out}")
    else:
        data = load_price_jsonl(sys.argv[1])
        result = run_backtest(data)
        print(result.summary())
