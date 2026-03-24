"""PostgreSQL integration — trade storage and analytics queries."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://arbbot:arbbot123@localhost:5432/arbbot")

# Schema
CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS trades (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    pair VARCHAR(20) NOT NULL,
    buy_dex VARCHAR(20) NOT NULL,
    sell_dex VARCHAR(20) NOT NULL,
    amount DOUBLE PRECISION NOT NULL,
    profit_pct DOUBLE PRECISION NOT NULL,
    estimated_profit DOUBLE PRECISION NOT NULL,
    fee DOUBLE PRECISION DEFAULT 0,
    tx_hash_1 VARCHAR(100),
    tx_hash_2 VARCHAR(100),
    status VARCHAR(20) DEFAULT 'executed',
    dry_run BOOLEAN DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS price_snapshots (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    pair VARCHAR(20) NOT NULL,
    dex VARCHAR(20) NOT NULL,
    price DOUBLE PRECISION NOT NULL,
    output_amount DOUBLE PRECISION NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trades(timestamp);
CREATE INDEX IF NOT EXISTS idx_trades_pair ON trades(pair);
CREATE INDEX IF NOT EXISTS idx_price_snapshots_timestamp ON price_snapshots(timestamp);
"""


class TradeDB:
    """PostgreSQL trade storage with analytics queries."""

    def __init__(self, database_url: str = DATABASE_URL) -> None:
        self.database_url = database_url
        self._conn = None

    def _get_conn(self):
        if self._conn is None or self._conn.closed:
            try:
                import psycopg2
                self._conn = psycopg2.connect(self.database_url)
                self._conn.autocommit = True
                logger.info("Connected to PostgreSQL")
            except Exception:
                logger.warning("Failed to connect to PostgreSQL — trades will not be persisted")
                self._conn = None
        return self._conn

    def init_schema(self) -> bool:
        """Create tables if they don't exist."""
        conn = self._get_conn()
        if not conn:
            return False
        try:
            with conn.cursor() as cur:
                cur.execute(CREATE_TABLES_SQL)
            logger.info("PostgreSQL schema initialized")
            return True
        except Exception:
            logger.exception("Failed to initialize schema")
            return False

    def insert_trade(
        self,
        pair: str,
        buy_dex: str,
        sell_dex: str,
        amount: float,
        profit_pct: float,
        estimated_profit: float,
        fee: float = 0.0,
        tx_hash_1: str = "",
        tx_hash_2: str = "",
        status: str = "executed",
        dry_run: bool = True,
    ) -> Optional[int]:
        """Insert a trade record. Returns the trade ID or None."""
        conn = self._get_conn()
        if not conn:
            return None
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO trades
                    (pair, buy_dex, sell_dex, amount, profit_pct, estimated_profit, fee, tx_hash_1, tx_hash_2, status, dry_run)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id""",
                    (pair, buy_dex, sell_dex, amount, profit_pct, estimated_profit, fee, tx_hash_1, tx_hash_2, status, dry_run),
                )
                row = cur.fetchone()
                return row[0] if row else None
        except Exception:
            logger.exception("Failed to insert trade")
            return None

    def insert_price_snapshot(self, pair: str, dex: str, price: float, output_amount: float) -> None:
        """Insert a price snapshot for analytics."""
        conn = self._get_conn()
        if not conn:
            return
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO price_snapshots (pair, dex, price, output_amount) VALUES (%s, %s, %s, %s)",
                    (pair, dex, price, output_amount),
                )
        except Exception:
            pass  # non-critical

    def get_stats_by_hour(self) -> list[dict]:
        """Get trade stats grouped by hour of day."""
        conn = self._get_conn()
        if not conn:
            return []
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT EXTRACT(HOUR FROM timestamp) as hour,
                           COUNT(*) as trades,
                           SUM(estimated_profit) as total_profit,
                           AVG(profit_pct) as avg_profit_pct
                    FROM trades
                    GROUP BY hour ORDER BY hour
                """)
                return [
                    {"hour": int(r[0]), "trades": r[1], "total_profit": float(r[2] or 0), "avg_profit_pct": float(r[3] or 0)}
                    for r in cur.fetchall()
                ]
        except Exception:
            return []

    def get_dex_performance(self) -> list[dict]:
        """Get performance stats per DEX pair."""
        conn = self._get_conn()
        if not conn:
            return []
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT buy_dex, sell_dex,
                           COUNT(*) as trades,
                           SUM(estimated_profit) as total_profit,
                           AVG(profit_pct) as avg_profit_pct
                    FROM trades
                    GROUP BY buy_dex, sell_dex ORDER BY total_profit DESC
                """)
                return [
                    {"buy_dex": r[0], "sell_dex": r[1], "trades": r[2],
                     "total_profit": float(r[3] or 0), "avg_profit_pct": float(r[4] or 0)}
                    for r in cur.fetchall()
                ]
        except Exception:
            return []

    def get_recent_trades(self, limit: int = 20) -> list[dict]:
        """Get the most recent trades."""
        conn = self._get_conn()
        if not conn:
            return []
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, timestamp, pair, buy_dex, sell_dex, amount, profit_pct, estimated_profit, status, dry_run FROM trades ORDER BY timestamp DESC LIMIT %s",
                    (limit,),
                )
                return [
                    {"id": r[0], "timestamp": r[1].isoformat(), "pair": r[2], "buy_dex": r[3], "sell_dex": r[4],
                     "amount": r[5], "profit_pct": r[6], "estimated_profit": r[7], "status": r[8], "dry_run": r[9]}
                    for r in cur.fetchall()
                ]
        except Exception:
            return []

    def query(self, sql: str) -> list[dict]:
        """Execute a read-only SQL query (for MCP analytics)."""
        conn = self._get_conn()
        if not conn:
            return []
        if not sql.strip().upper().startswith("SELECT"):
            return [{"error": "Only SELECT queries are allowed"}]
        try:
            with conn.cursor() as cur:
                cur.execute(sql)
                cols = [desc[0] for desc in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
        except Exception as e:
            return [{"error": str(e)}]

    def close(self) -> None:
        if self._conn and not self._conn.closed:
            self._conn.close()
