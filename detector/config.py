"""Bot configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class BotConfig:
    """Solana arbitrage bot configuration.

    All values can be overridden via environment variables.
    """

    rpc_url: str = field(default_factory=lambda: os.getenv("RPC_URL", ""))
    keypair_path: str = field(default_factory=lambda: os.getenv("KEYPAIR_PATH", "./wallet.json"))
    telegram_bot_token: str = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    telegram_chat_id: str = field(default_factory=lambda: os.getenv("TELEGRAM_CHAT_ID", ""))
    trade_amount_sol: float = field(default_factory=lambda: float(os.getenv("TRADE_AMOUNT_SOL", "0.05")))
    min_profit_pct: float = field(default_factory=lambda: float(os.getenv("MIN_PROFIT_PCT", "0.1")))
    max_slippage_pct: float = field(default_factory=lambda: float(os.getenv("MAX_SLIPPAGE_PCT", "0.5")))
    kill_switch_sol: float = field(default_factory=lambda: float(os.getenv("KILL_SWITCH_SOL", "0.05")))
    dry_run: bool = field(default_factory=lambda: os.getenv("DRY_RUN", "true").lower() in ("true", "1", "yes"))
    poll_interval_sec: int = field(default_factory=lambda: int(os.getenv("POLL_INTERVAL_SEC", "3")))
    executor_path: str = field(default_factory=lambda: os.getenv("EXECUTOR_PATH", "./executor/target/release/executor"))
    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    log_path: str = field(default_factory=lambda: os.getenv("LOG_PATH", "/var/log/arb-bot/bot.log"))

    def __post_init__(self) -> None:
        if self.trade_amount_sol < 0:
            raise ValueError("trade_amount_sol must be >= 0")
        if self.min_profit_pct < 0:
            raise ValueError("min_profit_pct must be >= 0")
        if not self.rpc_url:
            raise ValueError("rpc_url must not be empty")
