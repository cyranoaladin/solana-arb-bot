# Solana Arbitrage Bot — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a hybrid Python/Rust arbitrage bot that detects price discrepancies between Solana DEXs and executes trades automatically on a VPS.

**Architecture:** Python detector polls Jupiter/Raydium/Orca APIs every 3s, calculates net profit, and calls a compiled Rust binary via subprocess for transaction execution. Notifications via Telegram. Deployed as a systemd service on Hetzner VPS 46.224.150.0.

**Tech Stack:** Python 3.11 (httpx, asyncio, python-telegram-bot), Rust (solana-sdk, solana-client, spl-token, clap), systemd, Helius RPC (free tier).

---

## File Structure

```
solana-arb-bot/
├── detector/
│   ├── __init__.py
│   ├── main.py              # Async main loop, orchestration
│   ├── config.py             # Dataclass config, loads .env
│   ├── price_fetcher.py      # Async fetch from Jupiter, Raydium, Orca
│   ├── arbitrage.py          # Compare prices, calculate net profit
│   ├── executor_bridge.py    # Call Rust binary via subprocess
│   ├── notifier.py           # Telegram notifications
│   └── requirements.txt
├── executor/
│   ├── src/
│   │   ├── main.rs           # CLI entry point (clap)
│   │   ├── swap.rs           # Build + sign + send swap transaction
│   │   └── config.rs         # Load keypair, parse CLI args
│   └── Cargo.toml
├── tests/
│   ├── test_config.py
│   ├── test_price_fetcher.py
│   ├── test_arbitrage.py
│   ├── test_executor_bridge.py
│   └── test_notifier.py
├── .env.example
├── .gitignore
├── deploy.sh
├── arb-bot.service           # systemd unit file
└── README.md
```

---

### Task 1: Project Scaffold + Config

**Files:**
- Create: `.gitignore`, `.env.example`, `detector/config.py`, `detector/__init__.py`, `detector/requirements.txt`, `tests/test_config.py`

- [ ] **Step 1: Write .gitignore**

```gitignore
.env
__pycache__/
*.pyc
target/
executor/target/
*.log
.venv/
```

- [ ] **Step 2: Write .env.example**

```env
RPC_URL=https://mainnet.helius-rpc.com/?api-key=YOUR_KEY
KEYPAIR_PATH=./wallet.json
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_chat_id
TRADE_AMOUNT_SOL=0.05
MIN_PROFIT_PCT=0.1
MAX_SLIPPAGE_PCT=0.5
KILL_SWITCH_SOL=0.05
DRY_RUN=true
POLL_INTERVAL_SEC=3
```

- [ ] **Step 3: Write the failing test for config**

```python
# tests/test_config.py
import pytest
from detector.config import BotConfig

def test_config_loads_defaults():
    config = BotConfig(
        rpc_url="https://example.com",
        keypair_path="./wallet.json",
    )
    assert config.trade_amount_sol == 0.05
    assert config.min_profit_pct == 0.1
    assert config.dry_run is True

def test_config_rejects_negative_trade_amount():
    with pytest.raises(ValueError):
        BotConfig(rpc_url="https://example.com", keypair_path="./w.json", trade_amount_sol=-1)
```

- [ ] **Step 4: Run test to verify it fails**

Run: `cd /home/alaeddine/Bureau/solana-arb-bot && python -m pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'detector'`

- [ ] **Step 5: Write config.py**

```python
# detector/config.py
from dataclasses import dataclass, field
from dotenv import load_dotenv
import os

load_dotenv()

@dataclass
class BotConfig:
    rpc_url: str = os.getenv("RPC_URL", "")
    keypair_path: str = os.getenv("KEYPAIR_PATH", "./wallet.json")
    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    telegram_chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "")
    trade_amount_sol: float = float(os.getenv("TRADE_AMOUNT_SOL", "0.05"))
    min_profit_pct: float = float(os.getenv("MIN_PROFIT_PCT", "0.1"))
    max_slippage_pct: float = float(os.getenv("MAX_SLIPPAGE_PCT", "0.5"))
    kill_switch_sol: float = float(os.getenv("KILL_SWITCH_SOL", "0.05"))
    dry_run: bool = os.getenv("DRY_RUN", "true").lower() == "true"
    poll_interval_sec: int = int(os.getenv("POLL_INTERVAL_SEC", "3"))
    executor_path: str = os.getenv("EXECUTOR_PATH", "./executor/target/release/executor")

    def __post_init__(self):
        if self.trade_amount_sol < 0:
            raise ValueError("trade_amount_sol must be >= 0")
        if self.min_profit_pct < 0:
            raise ValueError("min_profit_pct must be >= 0")
        if not self.rpc_url:
            raise ValueError("rpc_url is required")
```

- [ ] **Step 6: Write requirements.txt and __init__.py**

```
# detector/requirements.txt
httpx>=0.27
python-dotenv>=1.0
python-telegram-bot>=21.0
pytest>=8.0
```

```python
# detector/__init__.py
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd /home/alaeddine/Bureau/solana-arb-bot && pip install -e . 2>/dev/null; python -m pytest tests/test_config.py -v`
Expected: 2 PASSED

- [ ] **Step 8: Commit**

```bash
git add -A && git commit -m "feat: project scaffold + config dataclass with validation"
```

---

### Task 2: Price Fetcher

**Files:**
- Create: `detector/price_fetcher.py`, `tests/test_price_fetcher.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_price_fetcher.py
import pytest
import httpx
from unittest.mock import AsyncMock, patch
from detector.price_fetcher import PriceFetcher

MOCK_JUPITER_RESPONSE = {
    "outAmount": "14500000",  # 14.5 USDC (6 decimals)
    "otherAmountThreshold": "14400000",
}

MOCK_RAYDIUM_RESPONSE = {
    "data": [{"price": 145.2}]
}

@pytest.mark.asyncio
async def test_fetch_jupiter_quote():
    fetcher = PriceFetcher(rpc_url="https://example.com")
    with patch.object(fetcher.client, "get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = httpx.Response(200, json=MOCK_JUPITER_RESPONSE)
        price = await fetcher.get_jupiter_price("SOL", "USDC", 0.1)
        assert price == pytest.approx(14.5, rel=0.01)

@pytest.mark.asyncio
async def test_fetch_returns_none_on_error():
    fetcher = PriceFetcher(rpc_url="https://example.com")
    with patch.object(fetcher.client, "get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = httpx.HTTPError("timeout")
        price = await fetcher.get_jupiter_price("SOL", "USDC", 0.1)
        assert price is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_price_fetcher.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'detector.price_fetcher'`

- [ ] **Step 3: Write price_fetcher.py**

```python
# detector/price_fetcher.py
import httpx
from dataclasses import dataclass
from typing import Optional
import logging

logger = logging.getLogger(__name__)

TOKEN_MINTS = {
    "SOL": "So11111111111111111111111111111111111111112",
    "USDC": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "USDT": "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
}

TOKEN_DECIMALS = {"SOL": 9, "USDC": 6, "USDT": 6}

@dataclass
class PriceQuote:
    dex: str
    input_token: str
    output_token: str
    input_amount: float
    output_amount: float
    price: float  # output per 1 input

class PriceFetcher:
    def __init__(self, rpc_url: str):
        self.rpc_url = rpc_url
        self.client = httpx.AsyncClient(timeout=5.0)

    async def get_jupiter_price(
        self, input_token: str, output_token: str, amount: float
    ) -> Optional[float]:
        try:
            input_mint = TOKEN_MINTS[input_token]
            output_mint = TOKEN_MINTS[output_token]
            input_decimals = TOKEN_DECIMALS[input_token]
            output_decimals = TOKEN_DECIMALS[output_token]
            raw_amount = int(amount * (10 ** input_decimals))

            resp = await self.client.get(
                "https://quote-api.jup.ag/v6/quote",
                params={
                    "inputMint": input_mint,
                    "outputMint": output_mint,
                    "amount": str(raw_amount),
                    "slippageBps": 50,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            out_raw = int(data["outAmount"])
            return out_raw / (10 ** output_decimals)
        except Exception as e:
            logger.warning(f"Jupiter fetch failed: {e}")
            return None

    async def get_all_prices(
        self, input_token: str, output_token: str, amount: float
    ) -> list[PriceQuote]:
        quotes = []
        jupiter = await self.get_jupiter_price(input_token, output_token, amount)
        if jupiter is not None:
            quotes.append(PriceQuote(
                dex="jupiter", input_token=input_token,
                output_token=output_token, input_amount=amount,
                output_amount=jupiter, price=jupiter / amount,
            ))
        return quotes

    async def close(self):
        await self.client.aclose()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pip install httpx pytest-asyncio && python -m pytest tests/test_price_fetcher.py -v`
Expected: 2 PASSED

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: price fetcher with Jupiter API integration"
```

---

### Task 3: Arbitrage Engine

**Files:**
- Create: `detector/arbitrage.py`, `tests/test_arbitrage.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_arbitrage.py
import pytest
from detector.arbitrage import ArbitrageDetector, Opportunity
from detector.price_fetcher import PriceQuote

def test_detect_profitable_opportunity():
    detector = ArbitrageDetector(min_profit_pct=0.1, tx_fee_sol=0.000005)
    quotes = [
        PriceQuote("jupiter", "SOL", "USDC", 0.1, 14.50, 145.0),
        PriceQuote("raydium", "SOL", "USDC", 0.1, 14.70, 147.0),
    ]
    opps = detector.find_opportunities(quotes)
    assert len(opps) == 1
    assert opps[0].buy_dex == "jupiter"
    assert opps[0].sell_dex == "raydium"
    assert opps[0].profit_pct > 0.1

def test_no_opportunity_when_spread_too_small():
    detector = ArbitrageDetector(min_profit_pct=0.1, tx_fee_sol=0.000005)
    quotes = [
        PriceQuote("jupiter", "SOL", "USDC", 0.1, 14.50, 145.0),
        PriceQuote("raydium", "SOL", "USDC", 0.1, 14.51, 145.1),
    ]
    opps = detector.find_opportunities(quotes)
    assert len(opps) == 0

def test_no_opportunity_with_single_quote():
    detector = ArbitrageDetector(min_profit_pct=0.1, tx_fee_sol=0.000005)
    quotes = [PriceQuote("jupiter", "SOL", "USDC", 0.1, 14.50, 145.0)]
    opps = detector.find_opportunities(quotes)
    assert len(opps) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_arbitrage.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write arbitrage.py**

```python
# detector/arbitrage.py
from dataclasses import dataclass
from detector.price_fetcher import PriceQuote
import logging

logger = logging.getLogger(__name__)

@dataclass
class Opportunity:
    pair: str
    buy_dex: str
    sell_dex: str
    buy_price: float
    sell_price: float
    amount: float
    profit_pct: float
    estimated_profit: float

class ArbitrageDetector:
    def __init__(self, min_profit_pct: float = 0.1, tx_fee_sol: float = 0.000005):
        self.min_profit_pct = min_profit_pct
        self.tx_fee_sol = tx_fee_sol

    def find_opportunities(self, quotes: list[PriceQuote]) -> list[Opportunity]:
        if len(quotes) < 2:
            return []

        opportunities = []
        for i, buy in enumerate(quotes):
            for j, sell in enumerate(quotes):
                if i == j:
                    continue
                if sell.output_amount <= buy.output_amount:
                    continue

                spread = sell.output_amount - buy.output_amount
                profit_pct = (spread / buy.output_amount) * 100

                if profit_pct >= self.min_profit_pct:
                    opportunities.append(Opportunity(
                        pair=f"{buy.input_token}/{buy.output_token}",
                        buy_dex=buy.dex,
                        sell_dex=sell.dex,
                        buy_price=buy.price,
                        sell_price=sell.price,
                        amount=buy.input_amount,
                        profit_pct=profit_pct,
                        estimated_profit=spread,
                    ))
                    logger.info(
                        f"Opportunity: buy {buy.dex} @ {buy.price:.4f}, "
                        f"sell {sell.dex} @ {sell.price:.4f}, "
                        f"profit {profit_pct:.3f}%"
                    )

        return sorted(opportunities, key=lambda o: o.profit_pct, reverse=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_arbitrage.py -v`
Expected: 3 PASSED

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: arbitrage detector with spread calculation"
```

---

### Task 4: Telegram Notifier

**Files:**
- Create: `detector/notifier.py`, `tests/test_notifier.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_notifier.py
import pytest
from unittest.mock import AsyncMock, patch
from detector.notifier import TelegramNotifier

@pytest.mark.asyncio
async def test_send_trade_notification():
    notifier = TelegramNotifier(token="fake", chat_id="123")
    with patch.object(notifier, "_send", new_callable=AsyncMock) as mock_send:
        await notifier.notify_trade(
            pair="SOL/USDC", buy_dex="jupiter", sell_dex="raydium",
            amount=0.1, profit=0.015, tx_hash="5xKabc123"
        )
        mock_send.assert_called_once()
        msg = mock_send.call_args[0][0]
        assert "SOL/USDC" in msg
        assert "5xKabc123" in msg

@pytest.mark.asyncio
async def test_send_alert():
    notifier = TelegramNotifier(token="fake", chat_id="123")
    with patch.object(notifier, "_send", new_callable=AsyncMock) as mock_send:
        await notifier.alert("Bot stopped: balance too low")
        mock_send.assert_called_once()
        assert "balance too low" in mock_send.call_args[0][0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_notifier.py -v`
Expected: FAIL

- [ ] **Step 3: Write notifier.py**

```python
# detector/notifier.py
import httpx
import logging

logger = logging.getLogger(__name__)

class TelegramNotifier:
    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{token}"

    async def _send(self, text: str):
        if not self.token or not self.chat_id:
            logger.debug(f"Telegram disabled, would send: {text[:80]}")
            return
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(
                    f"{self.base_url}/sendMessage",
                    json={"chat_id": self.chat_id, "text": text, "parse_mode": "HTML"},
                )
        except Exception as e:
            logger.warning(f"Telegram send failed: {e}")

    async def notify_trade(self, pair: str, buy_dex: str, sell_dex: str,
                           amount: float, profit: float, tx_hash: str):
        msg = (
            f"<b>Trade executed</b>\n"
            f"Pair: {pair}\n"
            f"Buy: {buy_dex} | Sell: {sell_dex}\n"
            f"Amount: {amount} SOL\n"
            f"Profit: {profit:.6f} USDC\n"
            f"Tx: <a href='https://solscan.io/tx/{tx_hash}'>{tx_hash[:12]}...</a>"
        )
        await self._send(msg)

    async def alert(self, message: str):
        await self._send(f"<b>ALERT</b>\n{message}")

    async def summary(self, trades: int, total_profit: float, balance: float):
        msg = (
            f"<b>Summary (6h)</b>\n"
            f"Trades: {trades}\n"
            f"Profit: {total_profit:.6f} USDC\n"
            f"Balance: {balance:.4f} SOL"
        )
        await self._send(msg)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_notifier.py -v`
Expected: 2 PASSED

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: Telegram notifier with trade/alert/summary"
```

---

### Task 5: Rust Executor — Scaffold + CLI

**Files:**
- Create: `executor/Cargo.toml`, `executor/src/main.rs`, `executor/src/config.rs`

- [ ] **Step 1: Write Cargo.toml**

```toml
[package]
name = "executor"
version = "0.1.0"
edition = "2021"

[dependencies]
solana-sdk = "1.18"
solana-client = "1.18"
spl-token = "4"
serde = { version = "1", features = ["derive"] }
serde_json = "1"
clap = { version = "4", features = ["derive"] }
anyhow = "1"
dotenv = "0.15"

[profile.release]
opt-level = 3
lto = true
```

- [ ] **Step 2: Write config.rs**

```rust
// executor/src/config.rs
use clap::Parser;

#[derive(Parser, Debug)]
#[command(name = "executor", about = "Solana swap executor")]
pub struct Cli {
    #[command(subcommand)]
    pub command: Commands,
}

#[derive(clap::Subcommand, Debug)]
pub enum Commands {
    Swap {
        #[arg(long)]
        from: String,
        #[arg(long)]
        to: String,
        #[arg(long)]
        amount: f64,
        #[arg(long)]
        dex: String,
        #[arg(long)]
        min_out: f64,
        #[arg(long)]
        rpc_url: String,
        #[arg(long)]
        keypair_path: String,
        #[arg(long, default_value_t = false)]
        dry_run: bool,
    },
    Balance {
        #[arg(long)]
        rpc_url: String,
        #[arg(long)]
        keypair_path: String,
    },
}
```

- [ ] **Step 3: Write main.rs (with dry-run)**

```rust
// executor/src/main.rs
mod config;
mod swap;

use clap::Parser;
use config::{Cli, Commands};
use serde_json::json;

fn main() {
    let cli = Cli::parse();

    let result = match cli.command {
        Commands::Swap {
            from, to, amount, dex, min_out, rpc_url, keypair_path, dry_run,
        } => {
            if dry_run {
                json!({
                    "status": "dry_run",
                    "from": from,
                    "to": to,
                    "amount_in": amount,
                    "amount_out": min_out,
                    "dex": dex,
                    "tx_hash": "DRY_RUN_NO_TX"
                })
            } else {
                match swap::execute_swap(&from, &to, amount, &dex, min_out, &rpc_url, &keypair_path) {
                    Ok(result) => result,
                    Err(e) => json!({"status": "error", "error": e.to_string()}),
                }
            }
        }
        Commands::Balance { rpc_url, keypair_path } => {
            match swap::get_balance(&rpc_url, &keypair_path) {
                Ok(bal) => json!({"status": "ok", "balance_sol": bal}),
                Err(e) => json!({"status": "error", "error": e.to_string()}),
            }
        }
    };

    println!("{}", serde_json::to_string(&result).unwrap());
}
```

- [ ] **Step 4: Write swap.rs (placeholder)**

```rust
// executor/src/swap.rs
use anyhow::Result;
use serde_json::{json, Value};
use solana_client::rpc_client::RpcClient;
use solana_sdk::signature::read_keypair_file;

pub fn get_balance(rpc_url: &str, keypair_path: &str) -> Result<f64> {
    let client = RpcClient::new(rpc_url.to_string());
    let keypair = read_keypair_file(keypair_path)
        .map_err(|e| anyhow::anyhow!("Failed to read keypair: {}", e))?;
    let balance = client.get_balance(&keypair.pubkey())?;
    Ok(balance as f64 / 1_000_000_000.0)
}

pub fn execute_swap(
    from: &str, to: &str, amount: f64, dex: &str,
    min_out: f64, rpc_url: &str, keypair_path: &str,
) -> Result<Value> {
    // TODO: Implement actual swap via Jupiter/Raydium SDK
    // For now, return a structured placeholder
    Ok(json!({
        "status": "ok",
        "from": from,
        "to": to,
        "amount_in": amount,
        "amount_out": min_out,
        "dex": dex,
        "tx_hash": "PLACEHOLDER_IMPLEMENT_SWAP",
        "fee": 0.000005
    }))
}
```

- [ ] **Step 5: Build and test**

Run: `cd executor && cargo build --release 2>&1 && echo "BUILD OK" && ./target/release/executor swap --from SOL --to USDC --amount 0.1 --dex jupiter --min-out 14.5 --rpc-url https://example.com --keypair-path /tmp/fake.json --dry-run`
Expected: JSON output with `"status": "dry_run"`

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat: Rust executor scaffold with CLI, dry-run, balance check"
```

---

### Task 6: Python ↔ Rust Bridge

**Files:**
- Create: `detector/executor_bridge.py`, `tests/test_executor_bridge.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_executor_bridge.py
import pytest
import json
from unittest.mock import patch, MagicMock
from detector.executor_bridge import ExecutorBridge

@pytest.mark.asyncio
async def test_execute_swap_dry_run():
    bridge = ExecutorBridge(
        executor_path="/usr/bin/echo",
        rpc_url="https://example.com",
        keypair_path="./wallet.json",
    )
    mock_result = json.dumps({"status": "dry_run", "tx_hash": "DRY_RUN_NO_TX"})
    with patch("asyncio.create_subprocess_exec") as mock_proc:
        proc = MagicMock()
        proc.communicate = MagicMock(return_value=(mock_result.encode(), b""))
        proc.returncode = 0
        mock_proc.return_value = proc
        result = await bridge.swap("SOL", "USDC", 0.1, "jupiter", 14.5, dry_run=True)
        assert result["status"] == "dry_run"

def test_parse_executor_response():
    bridge = ExecutorBridge("/fake", "https://x", "./w.json")
    raw = '{"status": "ok", "tx_hash": "abc123", "amount_out": 14.5}'
    result = bridge._parse_response(raw)
    assert result["status"] == "ok"
    assert result["tx_hash"] == "abc123"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_executor_bridge.py -v`
Expected: FAIL

- [ ] **Step 3: Write executor_bridge.py**

```python
# detector/executor_bridge.py
import asyncio
import json
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

class ExecutorBridge:
    def __init__(self, executor_path: str, rpc_url: str, keypair_path: str):
        self.executor_path = executor_path
        self.rpc_url = rpc_url
        self.keypair_path = keypair_path

    def _parse_response(self, raw: str) -> dict:
        try:
            return json.loads(raw.strip())
        except json.JSONDecodeError:
            return {"status": "error", "error": f"Invalid JSON: {raw[:200]}"}

    async def swap(self, from_token: str, to_token: str, amount: float,
                   dex: str, min_out: float, dry_run: bool = False) -> dict:
        cmd = [
            self.executor_path, "swap",
            "--from", from_token,
            "--to", to_token,
            "--amount", str(amount),
            "--dex", dex,
            "--min-out", str(min_out),
            "--rpc-url", self.rpc_url,
            "--keypair-path", self.keypair_path,
        ]
        if dry_run:
            cmd.append("--dry-run")

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                return {"status": "error", "error": stderr.decode()[:500]}
            return self._parse_response(stdout.decode())
        except Exception as e:
            logger.error(f"Executor call failed: {e}")
            return {"status": "error", "error": str(e)}

    async def get_balance(self) -> float:
        try:
            proc = await asyncio.create_subprocess_exec(
                self.executor_path, "balance",
                "--rpc-url", self.rpc_url,
                "--keypair-path", self.keypair_path,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            result = self._parse_response(stdout.decode())
            return result.get("balance_sol", 0.0)
        except Exception:
            return 0.0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_executor_bridge.py -v`
Expected: 2 PASSED

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: Python-Rust bridge via subprocess"
```

---

### Task 7: Main Loop

**Files:**
- Create: `detector/main.py`

- [ ] **Step 1: Write main.py**

```python
# detector/main.py
import asyncio
import logging
import sys
from datetime import datetime, timedelta
from detector.config import BotConfig
from detector.price_fetcher import PriceFetcher
from detector.arbitrage import ArbitrageDetector
from detector.executor_bridge import ExecutorBridge
from detector.notifier import TelegramNotifier

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("arb-bot")

PAIRS = [("SOL", "USDC"), ("SOL", "USDT")]

async def run_bot():
    config = BotConfig()
    fetcher = PriceFetcher(rpc_url=config.rpc_url)
    detector = ArbitrageDetector(min_profit_pct=config.min_profit_pct)
    bridge = ExecutorBridge(config.executor_path, config.rpc_url, config.keypair_path)
    notifier = TelegramNotifier(config.telegram_bot_token, config.telegram_chat_id)

    trades_count = 0
    total_profit = 0.0
    last_summary = datetime.now()

    logger.info(f"Bot started | dry_run={config.dry_run} | amount={config.trade_amount_sol} SOL")
    await notifier.alert(f"Bot started | dry_run={config.dry_run}")

    try:
        while True:
            # Kill switch
            balance = await bridge.get_balance()
            if balance < config.kill_switch_sol and not config.dry_run:
                msg = f"Kill switch: balance {balance:.4f} SOL < {config.kill_switch_sol}"
                logger.warning(msg)
                await notifier.alert(msg)
                break

            # Fetch prices for all pairs
            for input_token, output_token in PAIRS:
                quotes = await fetcher.get_all_prices(
                    input_token, output_token, config.trade_amount_sol
                )

                if len(quotes) < 2:
                    continue

                opportunities = detector.find_opportunities(quotes)

                for opp in opportunities:
                    logger.info(f"Executing: {opp.pair} buy@{opp.buy_dex} sell@{opp.sell_dex} +{opp.profit_pct:.3f}%")

                    result = await bridge.swap(
                        input_token, output_token, config.trade_amount_sol,
                        opp.buy_dex, opp.estimated_profit,
                        dry_run=config.dry_run,
                    )

                    if result.get("status") in ("ok", "dry_run"):
                        trades_count += 1
                        total_profit += opp.estimated_profit
                        await notifier.notify_trade(
                            pair=opp.pair, buy_dex=opp.buy_dex,
                            sell_dex=opp.sell_dex, amount=config.trade_amount_sol,
                            profit=opp.estimated_profit,
                            tx_hash=result.get("tx_hash", "N/A"),
                        )
                    else:
                        await notifier.alert(f"Trade failed: {result.get('error', 'unknown')}")

            # Periodic summary
            if datetime.now() - last_summary > timedelta(hours=6):
                await notifier.summary(trades_count, total_profit, balance)
                last_summary = datetime.now()

            await asyncio.sleep(config.poll_interval_sec)

    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    finally:
        await fetcher.close()
        await notifier.alert(f"Bot stopped | trades={trades_count} profit={total_profit:.6f}")

if __name__ == "__main__":
    asyncio.run(run_bot())
```

- [ ] **Step 2: Test manually in dry-run**

Run: `DRY_RUN=true RPC_URL=https://mainnet.helius-rpc.com/?api-key=test python -m detector.main`
Expected: Bot starts, logs price fetches, no actual trades. Ctrl+C to stop.

- [ ] **Step 3: Commit**

```bash
git add -A && git commit -m "feat: main loop with kill switch, periodic summary, dry-run"
```

---

### Task 8: VPS Deployment

**Files:**
- Create: `arb-bot.service`, `deploy.sh`

- [ ] **Step 1: Write systemd service**

```ini
# arb-bot.service
[Unit]
Description=Solana Arbitrage Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/solana-arb-bot
EnvironmentFile=/opt/solana-arb-bot/.env
ExecStart=/usr/bin/python3 -m detector.main
Restart=on-failure
RestartSec=10
StandardOutput=append:/var/log/arb-bot/bot.log
StandardError=append:/var/log/arb-bot/error.log

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 2: Write deploy.sh**

```bash
#!/bin/bash
set -e
VPS="root@46.224.150.0"
REMOTE_DIR="/opt/solana-arb-bot"

echo "=== Deploying Solana Arb Bot ==="

# Sync code
rsync -avz --exclude '.env' --exclude 'target/' --exclude '__pycache__/' \
  --exclude '.git/' --exclude '.venv/' \
  ./ "$VPS:$REMOTE_DIR/"

# Build Rust on VPS and setup
ssh "$VPS" bash <<'EOF'
  set -e
  cd /opt/solana-arb-bot

  # Install deps if needed
  pip3 install -r detector/requirements.txt 2>/dev/null

  # Build Rust executor
  cd executor && cargo build --release && cd ..

  # Setup logging
  mkdir -p /var/log/arb-bot

  # Install and start service
  cp arb-bot.service /etc/systemd/system/
  systemctl daemon-reload
  systemctl enable arb-bot
  systemctl restart arb-bot

  echo "Status:"
  systemctl status arb-bot --no-pager | head -10
EOF

echo "=== Deployed ==="
```

- [ ] **Step 3: Commit**

```bash
chmod +x deploy.sh
git add -A && git commit -m "feat: VPS deployment with systemd service"
```

---

### Task 9: Wallet Setup + First Dry Run on VPS

- [ ] **Step 1: Generate jetable wallet**

```bash
solana-keygen new --outfile wallet.json --no-passphrase
# Fund with 50$ of SOL from your Phantom
```

- [ ] **Step 2: Create .env on VPS**

```bash
scp .env.example root@46.224.150.0:/opt/solana-arb-bot/.env
# Edit with real values: RPC key, Telegram token, keypair path
```

- [ ] **Step 3: Deploy and test dry-run**

```bash
./deploy.sh
ssh root@46.224.150.0 "journalctl -u arb-bot -f"
```
Expected: Bot logs price fetches, detects (or not) opportunities, no real trades.

- [ ] **Step 4: Switch to live when ready**

```bash
ssh root@46.224.150.0 "sed -i 's/DRY_RUN=true/DRY_RUN=false/' /opt/solana-arb-bot/.env && systemctl restart arb-bot"
```

- [ ] **Step 5: Commit README**

```bash
git add -A && git commit -m "docs: README with setup, deployment, and usage instructions"
```

---

## Execution Order

| Task | Durée estimée | Dépendances |
|------|---------------|-------------|
| 1. Scaffold + Config | 5 min | Aucune |
| 2. Price Fetcher | 10 min | Task 1 |
| 3. Arbitrage Engine | 10 min | Task 2 |
| 4. Telegram Notifier | 5 min | Task 1 |
| 5. Rust Executor | 15 min | Aucune (parallélisable) |
| 6. Python ↔ Rust Bridge | 10 min | Task 1 + Task 5 |
| 7. Main Loop | 10 min | Task 2 + 3 + 4 + 6 |
| 8. VPS Deployment | 10 min | Task 7 |
| 9. Wallet + Dry Run | 10 min | Task 8 |
| **Total** | **~85 min** | |
