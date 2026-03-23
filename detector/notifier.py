"""Telegram notifier for Solana arbitrage bot."""

import logging

import httpx

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Sends trade notifications, alerts, and summaries via Telegram."""

    def __init__(self, token: str, chat_id: str) -> None:
        self.token = token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{token}"

    async def _send(self, text: str) -> None:
        """Send a message via Telegram Bot API."""
        if not self.token or not self.chat_id:
            logger.warning("Telegram token or chat_id not configured; skipping message.")
            return

        url = f"{self.base_url}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
        }

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.error("Telegram send failed: %s", exc)

    async def notify_trade(
        self,
        pair: str,
        buy_dex: str,
        sell_dex: str,
        amount: float,
        profit: float,
        tx_hash: str,
    ) -> None:
        """Send a trade execution notification."""
        text = (
            f"<b>Trade Executed</b>\n"
            f"Pair: {pair}\n"
            f"Buy: {buy_dex} | Sell: {sell_dex}\n"
            f"Amount: {amount}\n"
            f"Profit: {profit}\n"
            f'<a href="https://solscan.io/tx/{tx_hash}">View on Solscan</a>'
        )
        await self._send(text)

    async def alert(self, message: str) -> None:
        """Send an alert message."""
        text = f"<b>ALERT</b>\n{message}"
        await self._send(text)

    async def summary(self, trades: int, total_profit: float, balance: float) -> None:
        """Send a 6-hour summary."""
        text = (
            f"<b>6h Summary</b>\n"
            f"Trades: {trades}\n"
            f"Total Profit: {total_profit}\n"
            f"Balance: {balance}"
        )
        await self._send(text)
