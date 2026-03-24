"""VPS Operations MCP server — system management tools without SSH."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil

from mcp.server import Server
from mcp.types import TextContent, Tool

logger = logging.getLogger(__name__)

server = Server("vps-ops")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="restart_service",
            description="Restart a systemd service (arb-bot or arb-dashboard).",
            inputSchema={
                "type": "object",
                "properties": {
                    "service": {"type": "string", "enum": ["arb-bot", "arb-dashboard"], "description": "Service name"},
                },
                "required": ["service"],
            },
        ),
        Tool(
            name="get_logs",
            description="Get the last N lines from the bot or dashboard log.",
            inputSchema={
                "type": "object",
                "properties": {
                    "service": {"type": "string", "enum": ["bot", "dashboard", "error"], "default": "bot"},
                    "lines": {"type": "integer", "default": 50},
                },
            },
        ),
        Tool(
            name="get_system_metrics",
            description="Get current CPU, memory, disk usage of the VPS.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="deploy_update",
            description="Pull latest code from git, rebuild Rust, and restart services.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="get_disk_usage",
            description="Get disk usage for key directories.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="get_service_status",
            description="Get systemd service status for bot and dashboard.",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    import json
    try:
        result = await _dispatch(name, arguments)
        return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]
    except Exception as exc:
        return [TextContent(type="text", text=json.dumps({"error": str(exc)}))]


async def _run_cmd(cmd: str, timeout: int = 30) -> str:
    """Run a shell command and return stdout."""
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        output = stdout.decode().strip()
        if stderr:
            output += "\n" + stderr.decode().strip()
        return output
    except asyncio.TimeoutError:
        proc.kill()
        return "Command timed out"


LOG_FILES = {
    "bot": "/var/log/arb-bot/bot.log",
    "dashboard": "/var/log/arb-bot/dashboard.log",
    "error": "/var/log/arb-bot/error.log",
}

ALLOWED_SERVICES = {"arb-bot", "arb-dashboard"}


async def _dispatch(name: str, args: dict) -> dict:
    if name == "restart_service":
        service = args.get("service", "")
        if service not in ALLOWED_SERVICES:
            return {"error": f"Service '{service}' not allowed. Use: {ALLOWED_SERVICES}"}
        output = await _run_cmd(f"systemctl restart {service}")
        logger.info("VPS MCP: restarted %s", service)
        return {"ok": True, "service": service, "output": output}

    elif name == "get_logs":
        service = args.get("service", "bot")
        lines = args.get("lines", 50)
        log_path = LOG_FILES.get(service)
        if not log_path:
            return {"error": f"Unknown log: {service}"}
        try:
            from pathlib import Path
            p = Path(log_path)
            if not p.exists():
                return {"error": f"Log file not found: {log_path}"}
            all_lines = p.read_text().strip().split("\n")
            return {"lines": all_lines[-lines:], "count": len(all_lines[-lines:]), "file": log_path}
        except Exception as e:
            return {"error": str(e)}

    elif name == "get_system_metrics":
        cpu = await _run_cmd("grep 'cpu ' /proc/stat | awk '{usage=($2+$4)*100/($2+$4+$5)} END {printf \"%.1f\", usage}'")
        mem = await _run_cmd("free -m | awk 'NR==2{printf \"%d/%dMB (%.1f%%)\", $3, $2, $3*100/$2}'")
        disk = await _run_cmd("df -h / | awk 'NR==2{printf \"%s/%s (%s)\", $3, $2, $5}'")
        uptime = await _run_cmd("uptime -p")
        load = await _run_cmd("cat /proc/loadavg | awk '{print $1, $2, $3}'")
        return {
            "cpu_usage": cpu,
            "memory": mem,
            "disk": disk,
            "uptime": uptime,
            "load_avg": load,
        }

    elif name == "deploy_update":
        logger.info("VPS MCP: starting deploy_update")
        steps = []
        # Git pull
        out = await _run_cmd("cd /opt/solana-arb-bot && git pull", timeout=60)
        steps.append({"step": "git_pull", "output": out})
        # Pip install
        out = await _run_cmd("cd /opt/solana-arb-bot && pip3 install --break-system-packages -q -r detector/requirements.txt", timeout=120)
        steps.append({"step": "pip_install", "output": out})
        # Cargo build
        out = await _run_cmd("cd /opt/solana-arb-bot/executor && source $HOME/.cargo/env && cargo build --release 2>&1", timeout=300)
        steps.append({"step": "cargo_build", "output": out[-500:]})  # last 500 chars
        # Restart services
        out = await _run_cmd("systemctl restart arb-bot && sleep 2 && systemctl restart arb-dashboard")
        steps.append({"step": "restart", "output": out})
        return {"ok": True, "steps": steps}

    elif name == "get_disk_usage":
        bot_size = await _run_cmd("du -sh /opt/solana-arb-bot --exclude=target 2>/dev/null | awk '{print $1}'")
        rust_target = await _run_cmd("du -sh /opt/solana-arb-bot/executor/target 2>/dev/null | awk '{print $1}'")
        logs = await _run_cmd("du -sh /var/log/arb-bot 2>/dev/null | awk '{print $1}'")
        root_free = await _run_cmd("df -h / | awk 'NR==2{print $4}'")
        return {
            "bot_code": bot_size,
            "rust_target": rust_target,
            "logs": logs,
            "disk_free": root_free,
        }

    elif name == "get_service_status":
        bot = await _run_cmd("systemctl is-active arb-bot")
        dash = await _run_cmd("systemctl is-active arb-dashboard")
        ollama = await _run_cmd("systemctl is-active ollama")
        return {
            "arb-bot": bot,
            "arb-dashboard": dash,
            "ollama": ollama,
        }

    return {"error": f"Unknown tool: {name}"}
