"""SortedSet for opportunity ranking — inspired by Mobula's SortedSet data structure.

Maintains a sorted collection of the best N arbitrage opportunities seen,
enabling quick comparison and deduplication. Used to:
- Track the best opportunities over a time window
- Avoid executing duplicate opportunities
- Provide historical context for strategy tuning
"""

from __future__ import annotations

import bisect
import time
from dataclasses import dataclass, field


@dataclass(order=True)
class RankedOpportunity:
    """An opportunity ranked by profit, with dedup key and expiry."""
    profit_pct: float  # sort key (descending via negation)
    key: str = field(compare=False)  # dedup key: "pair:buy_dex:sell_dex"
    timestamp: float = field(compare=False, default_factory=time.time)
    estimated_profit: float = field(compare=False, default=0.0)
    pair: str = field(compare=False, default="")
    buy_dex: str = field(compare=False, default="")
    sell_dex: str = field(compare=False, default="")


class OpportunityRanker:
    """Maintains a sorted set of top opportunities with TTL-based expiry.

    - O(log n) insert via bisect
    - Deduplication by key (pair + dex combo)
    - Automatic expiry of stale entries
    - Max size cap to bound memory
    """

    def __init__(self, max_size: int = 100, ttl_sec: float = 60.0) -> None:
        self.max_size = max_size
        self.ttl_sec = ttl_sec
        self._items: list[RankedOpportunity] = []
        self._keys: set[str] = set()

    def add(self, pair: str, buy_dex: str, sell_dex: str,
            profit_pct: float, estimated_profit: float = 0.0) -> bool:
        """Add an opportunity. Returns True if it's new (not a duplicate)."""
        self._expire_old()

        key = f"{pair}:{buy_dex}:{sell_dex}"
        if key in self._keys:
            return False  # duplicate

        item = RankedOpportunity(
            profit_pct=-profit_pct,  # negate for descending sort
            key=key,
            estimated_profit=estimated_profit,
            pair=pair,
            buy_dex=buy_dex,
            sell_dex=sell_dex,
        )
        bisect.insort(self._items, item)
        self._keys.add(key)

        # Cap size
        if len(self._items) > self.max_size:
            removed = self._items.pop()  # remove worst (highest negated = lowest profit)
            self._keys.discard(removed.key)

        return True

    def get_top(self, n: int = 10) -> list[dict]:
        """Get the top N opportunities sorted by profit descending."""
        self._expire_old()
        results = []
        for item in self._items[:n]:
            results.append({
                "pair": item.pair,
                "buy_dex": item.buy_dex,
                "sell_dex": item.sell_dex,
                "profit_pct": -item.profit_pct,
                "estimated_profit": item.estimated_profit,
                "age_sec": round(time.time() - item.timestamp, 1),
            })
        return results

    def has_recent(self, pair: str, buy_dex: str, sell_dex: str) -> bool:
        """Check if this opportunity was recently seen (within TTL)."""
        key = f"{pair}:{buy_dex}:{sell_dex}"
        return key in self._keys

    def clear(self) -> None:
        self._items.clear()
        self._keys.clear()

    def _expire_old(self) -> None:
        """Remove entries older than TTL."""
        now = time.time()
        cutoff = now - self.ttl_sec
        expired = [i for i in self._items if i.timestamp < cutoff]
        for item in expired:
            self._items.remove(item)
            self._keys.discard(item.key)

    @property
    def size(self) -> int:
        return len(self._items)

    def stats(self) -> dict:
        """Return summary stats."""
        self._expire_old()
        if not self._items:
            return {"count": 0, "best_profit_pct": 0, "worst_profit_pct": 0}
        return {
            "count": len(self._items),
            "best_profit_pct": round(-self._items[0].profit_pct, 4),
            "worst_profit_pct": round(-self._items[-1].profit_pct, 4),
            "unique_pairs": len({i.pair for i in self._items}),
        }
