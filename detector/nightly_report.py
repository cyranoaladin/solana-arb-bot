"""Nightly AI analysis report — Ollama local (primary) or Claude Haiku (fallback)."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

REPORT_PROMPT = """Tu es un analyste de trading algorithmique. Analyse ces logs JSON d'un bot d'arbitrage Solana des dernières 24h et produis un rapport concis en français.

Logs:
{logs}

Stats:
{stats}

Produis un rapport avec:
1. **Résumé** — trades exécutés, profit/perte, taux de réussite
2. **Heures de pic** — quand les meilleures opportunités apparaissent
3. **Anomalies** — erreurs récurrentes, patterns suspects
4. **Recommandations** — ajustements de paramètres (min_profit_pct, trade_amount_sol, poll_interval)

Sois direct et actionnable. Max 400 mots."""

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:1.5b")

# Runtime-switchable AI provider: "ollama" (default) or "anthropic"
ai_provider: str = "ollama"


def _read_recent_logs(log_path: str, max_lines: int = 200) -> str | None:
    """Read the last N lines from the bot log file.

    Falls back to error.log in the same directory if the primary log is empty.
    """
    try:
        log_file = Path(log_path)
        # Try primary log
        if log_file.exists() and log_file.stat().st_size > 0:
            lines = log_file.read_text().strip().split("\n")[-max_lines:]
            return "\n".join(lines)
        # Fallback to error.log (systemd may route stderr there)
        error_log = log_file.parent / "error.log"
        if error_log.exists() and error_log.stat().st_size > 0:
            logger.info("Primary log empty, reading from %s", error_log)
            lines = error_log.read_text().strip().split("\n")[-max_lines:]
            return "\n".join(lines)
        logger.warning("No log data found at %s", log_path)
        return None
    except Exception:
        logger.exception("Failed to read logs")
        return None


async def _call_ollama(prompt: str) -> str | None:
    """Call local Ollama API for inference.

    Uses sync httpx to avoid asyncio timeout issues with long CPU inference.
    """
    try:
        resp = httpx.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"num_predict": 512},
            },
            timeout=300,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data.get("response", "")
        if content:
            logger.info("Ollama (%s) report generated successfully", OLLAMA_MODEL)
            return content
        return None
    except Exception:
        logger.warning("Ollama call failed, will try Anthropic fallback")
        return None


async def _call_anthropic(prompt: str) -> str | None:
    """Call Anthropic Claude Haiku API as fallback."""
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        return None

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 1024,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            resp.raise_for_status()
            data = resp.json()
            content = data.get("content", [{}])[0].get("text", "")
            if content:
                logger.info("Anthropic Haiku report generated successfully")
            return content or None
    except Exception:
        logger.exception("Anthropic API call failed")
        return None


async def generate_nightly_report(
    log_path: str = "/var/log/arb-bot/bot.log",
    stats: dict | None = None,
) -> str | None:
    """Generate a nightly analysis report.

    Priority: Ollama local → Anthropic API → None.
    """
    logs_text = _read_recent_logs(log_path, max_lines=20)
    if not logs_text:
        return None

    stats_text = json.dumps(stats or {}, indent=2)
    prompt = REPORT_PROMPT.format(logs=logs_text, stats=stats_text)

    if ai_provider == "anthropic":
        # Use Anthropic API first, Ollama as fallback
        report = await _call_anthropic(prompt)
        if report:
            return report
        report = await _call_ollama(prompt)
        if report:
            return report
    else:
        # Use Ollama first (local, free, private), Anthropic as fallback
        report = await _call_ollama(prompt)
        if report:
            return report
        report = await _call_anthropic(prompt)
        if report:
            return report

    logger.warning("All AI providers failed for nightly report")
    return None


async def run_nightly_report(
    notifier,
    stats: dict | None = None,
    log_path: str = "/var/log/arb-bot/bot.log",
) -> None:
    """Generate and send the nightly report via Telegram."""
    logger.info("Starting nightly AI report generation...")
    report = await generate_nightly_report(log_path=log_path, stats=stats)
    if report:
        await notifier.alert(f"\U0001f4ca <b>Bilan IA nocturne</b>\n\n{report}")
        logger.info("Nightly report sent to Telegram")
    else:
        logger.warning("Nightly report generation failed or skipped")
