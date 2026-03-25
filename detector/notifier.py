"""Telegram notifier for Solana arbitrage bot — honest trade status messages."""

import logging

import httpx

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Sends trade notifications, alerts, and summaries via Telegram."""

    def __init__(self, token: str, chat_id: str) -> None:
        self.token = token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{token}"
        self._disabled = False

    async def _send(self, text: str) -> None:
        """Send a message via Telegram Bot API."""
        if self._disabled or not self.token or not self.chat_id:
            return

        url = f"{self.base_url}/sendMessage"
        payload = {"chat_id": self.chat_id, "text": text, "parse_mode": "HTML"}

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (401, 403):
                logger.critical("Telegram auth failed (status %d) — disabling notifications", exc.response.status_code)
                self._disabled = True
            else:
                logger.error("Telegram send failed: %s", exc)
        except httpx.HTTPError as exc:
            logger.error("Telegram network error: %s", exc)

    async def notify_opportunity_observed(
        self, pair: str, buy_dex: str, sell_dex: str, profit_pct: float,
    ) -> None:
        """Notify that an opportunity was observed (not necessarily executed)."""
        text = (
            f"<b>Opportunity Observed</b>\n"
            f"Pair: {pair}\n"
            f"Buy: {buy_dex} | Sell: {sell_dex}\n"
            f"Estimated spread: {profit_pct:.4f}%"
        )
        await self._send(text)

    async def notify_trade(
        self,
        pair: str,
        buy_dex: str,
        sell_dex: str,
        amount: float,
        profit: float,
        tx_hash: str,
        status: str = "submitted",
    ) -> None:
        """Send a trade notification with explicit status.

        status should be: 'submitted', 'confirmed', 'simulated', 'dry_run'
        """
        status_label = {
            "submitted": "Trade Submitted (pending confirmation)",
            "confirmed": "Trade Confirmed",
            "simulated": "Trade Simulated (dry-run)",
            "dry_run": "Trade Simulated (dry-run)",
        }.get(status, f"Trade ({status})")

        text = (
            f"<b>{status_label}</b>\n"
            f"Pair: {pair}\n"
            f"Buy: {buy_dex} | Sell: {sell_dex}\n"
            f"Amount: {amount}\n"
            f"Estimated profit: {profit:.6f} (not realized)\n"
        )
        if tx_hash and tx_hash != "n/a":
            text += f'<a href="https://solscan.io/tx/{tx_hash}">View on Solscan</a>'
        await self._send(text)

    async def notify_trade_blocked(self, pair: str, reason: str) -> None:
        """Notify that a trade was blocked by safety gates."""
        text = f"<b>Trade Blocked</b>\nPair: {pair}\nReason: {reason}"
        await self._send(text)

    async def alert(self, message: str) -> None:
        """Send an alert message."""
        text = f"<b>ALERT</b>\n{message}"
        await self._send(text)

    async def summary(
        self, trades: int, total_profit: float, balance: float,
        realized_profit: float = 0.0,
    ) -> None:
        """Send a 6-hour summary distinguishing estimated from realized."""
        text = (
            f"<b>6h Summary</b>\n"
            f"Trades: {trades}\n"
            f"Estimated profit: {total_profit:.6f}\n"
            f"Realized profit: {realized_profit:.6f}\n"
            f"Balance: {balance:.6f}"
        )
        await self._send(text)
