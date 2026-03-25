"""Bot configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class BotConfig:
    """Solana arbitrage bot configuration.

    All values can be overridden via environment variables.
    TRADING_ENABLED must be explicitly set to 'true' for live execution.
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

    # Safety gates
    trading_enabled: bool = field(
        default_factory=lambda: os.getenv("TRADING_ENABLED", "false").lower() in ("true", "1", "yes")
    )
    live_trading_allow_unsupported_routes: bool = field(
        default_factory=lambda: os.getenv("LIVE_TRADING_ALLOW_UNSUPPORTED_ROUTES", "false").lower() == "true"
    )

    # Jito atomic bundles for live trades
    use_jito_bundles: bool = field(
        default_factory=lambda: os.getenv("USE_JITO_BUNDLES", "true").lower() in ("true", "1", "yes")
    )
    jito_tip_lamports: int = field(
        default_factory=lambda: int(os.getenv("JITO_TIP_LAMPORTS", "50000"))
    )

    # Bind hosts (127.0.0.1 = internal only, 0.0.0.0 = public)
    health_bind_host: str = field(default_factory=lambda: os.getenv("HEALTH_BIND_HOST", "127.0.0.1"))
    dashboard_bind_host: str = field(default_factory=lambda: os.getenv("DASHBOARD_BIND_HOST", "127.0.0.1"))

    # Database (no weak default — must be explicitly configured)
    database_url: str = field(default_factory=lambda: os.getenv("DATABASE_URL", ""))

    def __post_init__(self) -> None:
        if self.trade_amount_sol < 0:
            raise ValueError("trade_amount_sol must be >= 0")
        if self.min_profit_pct < 0:
            raise ValueError("min_profit_pct must be >= 0")
        if not self.rpc_url:
            raise ValueError("RPC_URL must not be empty")

        # Safety: if DRY_RUN is false, TRADING_ENABLED must be explicitly true
        if not self.dry_run and not self.trading_enabled:
            raise ValueError(
                "FATAL: DRY_RUN=false but TRADING_ENABLED is not set to 'true'. "
                "Live trading requires explicit opt-in via TRADING_ENABLED=true. "
                "This is a safety gate to prevent accidental live execution."
            )

    @property
    def live_execution_allowed(self) -> bool:
        """True only if both DRY_RUN=false AND TRADING_ENABLED=true."""
        return not self.dry_run and self.trading_enabled

    @property
    def live_block_reason(self) -> str:
        """Human-readable reason why live trading is blocked."""
        if self.dry_run:
            return "DRY_RUN=true"
        if not self.trading_enabled:
            return "TRADING_ENABLED not set to true"
        return ""
