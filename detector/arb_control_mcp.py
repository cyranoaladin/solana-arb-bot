"""arb-control MCP server — exposes bot state and controls to AI agents."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from mcp.server import Server
from mcp.types import TextContent, Tool

logger = logging.getLogger(__name__)

# Singleton reference set by main.py at startup
_bot_state: dict[str, Any] = {}


def set_bot_state(
    stats,
    config,
    detector,
    vol_tracker,
    notifier,
    trader_stats=None,
) -> None:
    """Register the bot's live objects so MCP tools can access them."""
    _bot_state["stats"] = stats
    _bot_state["config"] = config
    _bot_state["detector"] = detector
    _bot_state["vol_tracker"] = vol_tracker
    _bot_state["notifier"] = notifier
    if trader_stats is not None:
        _bot_state["trader_stats"] = trader_stats


# Allowed params and their (min, max) bounds
ALLOWED_PARAMS = {
    "min_profit_pct": (0.01, 5.0),
    "trade_amount_sol": (0.001, 1.0),
    "max_slippage_pct": (0.05, 5.0),
    "poll_interval_sec": (1, 60),
    "kill_switch_sol": (0.01, 10.0),
}

server = Server("arb-control")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="get_live_state",
            description="Get the bot's current live state: balance, trades, profit, uptime, errors.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="get_session_stats",
            description="Get detailed session statistics including volatility and adaptive threshold.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="get_recent_logs",
            description="Get the N most recent log lines from the bot log file.",
            inputSchema={
                "type": "object",
                "properties": {
                    "n": {"type": "integer", "description": "Number of lines", "default": 50},
                    "log_path": {"type": "string", "default": "/var/log/arb-bot/bot.log"},
                },
            },
        ),
        Tool(
            name="set_param",
            description=f"Set a bot parameter in real-time. Allowed: {list(ALLOWED_PARAMS.keys())}",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Parameter name"},
                    "value": {"type": "number", "description": "New value"},
                },
                "required": ["name", "value"],
            },
        ),
        Tool(
            name="pause_trading",
            description="Pause the bot's trading loop. Price scanning continues but no trades are executed.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="resume_trading",
            description="Resume the bot's trading loop after a pause.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="force_dry_run",
            description="Force the bot into dry-run mode (no real trades). Set enable=false to disable.",
            inputSchema={
                "type": "object",
                "properties": {
                    "enable": {"type": "boolean", "default": True},
                },
            },
        ),
        Tool(
            name="set_ai_provider",
            description="Switch the nightly report AI provider. 'ollama' = local free, 'anthropic' = Claude Haiku API.",
            inputSchema={
                "type": "object",
                "properties": {
                    "provider": {"type": "string", "enum": ["ollama", "anthropic"]},
                },
                "required": ["provider"],
            },
        ),
        Tool(
            name="get_opportunities",
            description="Get the current price quotes and potential arbitrage opportunities.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="get_pnl_curve",
            description="Get the cumulative P&L curve (list of {ts, profit, cumulative} for each trade).",
            inputSchema={
                "type": "object",
                "properties": {
                    "last_n": {"type": "integer", "description": "Return only the last N data points", "default": 100},
                },
            },
        ),
        Tool(
            name="get_market_context",
            description="Get DeFiLlama market context: TVL comparison for DEXes the bot trades on (Raydium, Orca, Meteora, Lifinity) and Solana chain TVL. Free, no API key needed.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="db_stats_by_hour",
            description="Get trade statistics grouped by hour of day from PostgreSQL.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="db_dex_performance",
            description="Get performance stats per DEX pair from PostgreSQL.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="db_recent_trades",
            description="Get the N most recent trades from PostgreSQL.",
            inputSchema={
                "type": "object",
                "properties": {"limit": {"type": "integer", "default": 20}},
            },
        ),
        Tool(
            name="db_query",
            description="Execute a read-only SQL SELECT query against the trades database.",
            inputSchema={
                "type": "object",
                "properties": {"sql": {"type": "string", "description": "SELECT query"}},
                "required": ["sql"],
            },
        ),
        Tool(
            name="get_trader_stats",
            description="Get smart trader analytics: win rate, best hours/days, best DEX routes, Sharpe ratio, streak tracking.",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        result = await _dispatch(name, arguments)
        return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]
    except Exception as exc:
        return [TextContent(type="text", text=json.dumps({"error": str(exc)}))]


async def _dispatch(name: str, args: dict) -> dict:
    stats = _bot_state.get("stats")
    config = _bot_state.get("config")
    detector = _bot_state.get("detector")
    vol_tracker = _bot_state.get("vol_tracker")

    if name == "get_live_state":
        if not stats:
            return {"error": "Bot not initialized"}
        return stats.to_dict()

    elif name == "get_session_stats":
        result = {}
        if stats:
            result.update(stats.to_dict())
        if vol_tracker:
            result["volatility"] = round(vol_tracker.get_volatility(), 6)
            result["adaptive_min_profit_pct"] = vol_tracker.get_adaptive_min_profit()
            result["price_samples"] = len(vol_tracker.prices)
        if detector:
            result["current_min_profit_pct"] = detector.min_profit_pct
        if config:
            result["trade_amount_sol"] = config.trade_amount_sol
            result["max_slippage_pct"] = config.max_slippage_pct
            result["poll_interval_sec"] = config.poll_interval_sec
        return result

    elif name == "get_recent_logs":
        n = args.get("n", 50)
        log_path = args.get("log_path", "/var/log/arb-bot/bot.log")
        try:
            from pathlib import Path
            lines = Path(log_path).read_text().strip().split("\n")[-n:]
            return {"lines": lines, "count": len(lines)}
        except FileNotFoundError:
            return {"error": f"Log file not found: {log_path}"}

    elif name == "set_param":
        param_name = args["name"]
        value = args["value"]
        if param_name not in ALLOWED_PARAMS:
            return {"error": f"Unknown param '{param_name}'. Allowed: {list(ALLOWED_PARAMS.keys())}"}
        lo, hi = ALLOWED_PARAMS[param_name]
        if not (lo <= value <= hi):
            return {"error": f"Value {value} out of range [{lo}, {hi}]"}

        if config and hasattr(config, param_name):
            setattr(config, param_name, type(getattr(config, param_name))(value))
        if param_name == "min_profit_pct" and detector:
            detector.min_profit_pct = value

        logger.info("MCP set_param: %s = %s", param_name, value)
        return {"ok": True, "param": param_name, "value": value}

    elif name == "pause_trading":
        if stats:
            stats.paused = True
            logger.info("MCP: trading paused")
        return {"ok": True, "paused": True}

    elif name == "resume_trading":
        if stats:
            stats.paused = False
            logger.info("MCP: trading resumed")
        return {"ok": True, "paused": False}

    elif name == "force_dry_run":
        enable = args.get("enable", True)
        if config:
            config.dry_run = enable
        if stats:
            stats.dry_run = enable
        logger.info("MCP: dry_run = %s", enable)
        return {"ok": True, "dry_run": enable}

    elif name == "set_ai_provider":
        import detector.nightly_report as nr
        provider = args.get("provider", "ollama")
        if provider not in ("ollama", "anthropic"):
            return {"error": f"Unknown provider '{provider}'. Use 'ollama' or 'anthropic'."}
        nr.ai_provider = provider
        logger.info("MCP: AI provider set to %s", provider)
        return {"ok": True, "ai_provider": provider}

    elif name == "get_opportunities":
        # Return current vol tracker data + recent price info
        result: dict = {"opportunities": []}
        if vol_tracker and vol_tracker.prices:
            result["latest_prices"] = vol_tracker.prices[-10:]
            result["volatility"] = round(vol_tracker.get_volatility(), 6)
        return result

    elif name == "get_pnl_curve":
        if not stats or not hasattr(stats, "pnl_curve"):
            return {"error": "No PnL data available"}
        last_n = args.get("last_n", 100)
        curve = stats.pnl_curve[-last_n:]
        return {"pnl_curve": curve, "count": len(curve)}

    elif name == "get_market_context":
        from detector.defillama import DeFiLlamaClient
        llama = DeFiLlamaClient()
        try:
            dex_tvls = await llama.get_dex_tvl_comparison()
            solana_tvl = await llama.get_solana_tvl()
            return {
                "solana_chain_tvl": solana_tvl,
                "dex_tvls": dex_tvls,
            }
        finally:
            await llama.close()

    elif name == "db_stats_by_hour":
        from detector.db import TradeDB
        db = TradeDB()
        return {"hourly_stats": db.get_stats_by_hour()}

    elif name == "db_dex_performance":
        from detector.db import TradeDB
        db = TradeDB()
        return {"dex_performance": db.get_dex_performance()}

    elif name == "db_recent_trades":
        from detector.db import TradeDB
        db = TradeDB()
        limit = args.get("limit", 20)
        return {"trades": db.get_recent_trades(limit)}

    elif name == "db_query":
        from detector.db import TradeDB
        db = TradeDB()
        sql = args.get("sql", "")
        return {"results": db.query(sql)}

    elif name == "get_trader_stats":
        trader_stats = _bot_state.get("trader_stats")
        if not trader_stats:
            return {"error": "TraderStats not initialized"}
        return trader_stats.get_performance_summary()

    return {"error": f"Unknown tool: {name}"}
