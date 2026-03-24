"""Entry point to run the arb-control MCP server over stdio."""

from __future__ import annotations

import asyncio
import logging

from dotenv import load_dotenv

load_dotenv()

from mcp.server.stdio import stdio_server

from detector.arb_control_mcp import server


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
