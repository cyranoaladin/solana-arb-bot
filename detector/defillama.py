"""DeFiLlama integration — free TVL and yield data for market context."""

from __future__ import annotations

import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

DEFILLAMA_BASE = "https://api.llama.fi"
YIELDS_BASE = "https://yields.llama.fi"


class DeFiLlamaClient:
    """Client for DeFiLlama public API (free, no key required)."""

    def __init__(self) -> None:
        self.client = httpx.AsyncClient(timeout=15)

    async def get_protocol_tvl(self, protocol: str) -> Optional[dict]:
        """Get TVL data for a protocol (e.g., 'raydium', 'orca', 'meteora')."""
        try:
            resp = await self.client.get(f"{DEFILLAMA_BASE}/protocol/{protocol}")
            resp.raise_for_status()
            data = resp.json()
            return {
                "name": data.get("name"),
                "tvl": data.get("currentChainTvls", {}).get("Solana", data.get("tvl")),
                "change_1d": data.get("change_1d"),
                "change_7d": data.get("change_7d"),
                "mcap": data.get("mcap"),
            }
        except Exception:
            logger.warning("Failed to get TVL for %s", protocol)
            return None

    async def get_solana_tvl(self) -> Optional[float]:
        """Get total TVL for Solana chain."""
        try:
            resp = await self.client.get(f"{DEFILLAMA_BASE}/v2/chains")
            resp.raise_for_status()
            chains = resp.json()
            for chain in chains:
                if chain.get("name") == "Solana":
                    return chain.get("tvl")
            return None
        except Exception:
            logger.warning("Failed to get Solana TVL")
            return None

    async def get_dex_tvl_comparison(self) -> dict:
        """Get TVL for all DEXes the bot uses, for context."""
        protocols = ["raydium", "orca", "meteora", "lifinity-v2"]
        results = {}
        for p in protocols:
            data = await self.get_protocol_tvl(p)
            if data:
                results[p] = data
        return results

    async def get_top_solana_yields(self, min_tvl: float = 100000) -> list[dict]:
        """Get top yield pools on Solana (useful for market context)."""
        try:
            resp = await self.client.get(f"{YIELDS_BASE}/pools")
            resp.raise_for_status()
            data = resp.json()
            pools = data.get("data", [])
            solana_pools = [
                {
                    "pool": p.get("pool"),
                    "project": p.get("project"),
                    "symbol": p.get("symbol"),
                    "tvlUsd": p.get("tvlUsd"),
                    "apy": p.get("apy"),
                    "apyBase": p.get("apyBase"),
                }
                for p in pools
                if p.get("chain") == "Solana"
                and (p.get("tvlUsd") or 0) >= min_tvl
                and p.get("project") in ("raydium", "orca", "meteora", "lifinity-v2")
            ]
            solana_pools.sort(key=lambda x: x.get("tvlUsd", 0), reverse=True)
            return solana_pools[:20]
        except Exception:
            logger.warning("Failed to get Solana yields")
            return []

    async def close(self) -> None:
        await self.client.aclose()
