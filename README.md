# Solana Arbitrage Bot

Bot d'arbitrage automatisé sur Solana — détection cross-DEX, exécution atomique via Jito bundles, supervision IA, dashboard temps réel.

**Stack** : Python 3.12 + Rust 1.78 + PostgreSQL 16 + Ollama
**DEXes** : Orca Whirlpool, Raydium, Meteora DLMM, Lifinity
**Infra** : VPS Hetzner, systemd, GitHub Actions CI

---

## Table des matières

- [Architecture](#architecture)
- [Flux d'arbitrage](#flux-darbitrage)
- [Modules Python](#modules-python)
- [Modules Rust](#modules-rust)
- [Dashboard web](#dashboard-web)
- [MCP Server (supervision IA)](#mcp-server-supervision-ia)
- [Installation](#installation)
- [Configuration](#configuration)
- [Déploiement VPS](#déploiement-vps)
- [Tests](#tests)
- [Production](#production)
- [Sécurité](#sécurité)

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│  AGENT LAYER  (Telegram / Claude.ai / Nexus)                           │
│                                                                          │
│   arb-control MCP (15 tools)  ←→  Ollama qwen2.5 (bilan nocturne)     │
│   set_param · pause · dry_run      Anthropic Claude (fallback)         │
└───────────────────────┬──────────────────────────────────────────────────┘
                        │  MCP over stdio
┌───────────────────────▼──────────────────────────────────────────────────┐
│  VPS Hetzner  ·  systemd arb-bot.service                                │
│                                                                          │
│   WebSocket Price Feed (500ms background polling)                       │
│   ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐              │
│   │   Orca   │  │ Raydium  │  │ Meteora  │  │ Lifinity │              │
│   │ pool API │  │ compute  │  │ DLMM API │  │   (best  │              │
│   │ + TVL    │  │ swap API │  │ + TVL    │  │  effort) │              │
│   └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘              │
│        └──────────────┼────────────┼──────────────┘                     │
│                       ▼                                                  │
│              ┌─────────────────┐                                        │
│              │  PriceCache     │  prix pondérés par liquidité TVL       │
│              │  (in-memory)    │  price impact estimation               │
│              └────────┬────────┘                                        │
│                       ▼                                                  │
│         ┌──────────────────────────┐                                    │
│         │  ArbitrageDetector       │                                    │
│         │  · spread cross-DEX      │                                    │
│         │  · triangulaire A→B→C    │                                    │
│         │  · seuils adaptatifs     │                                    │
│         │    (VolatilityTracker)   │                                    │
│         └────────────┬─────────────┘                                    │
│                      ▼                                                   │
│    ┌───────────┐ ┌───────────┐ ┌────────────┐ ┌───────────────┐        │
│    │ ML Scorer │ │ Pyth      │ │ Dedup      │ │ Dynamic       │        │
│    │ XGBoost   │ │ Oracle    │ │ SortedSet  │ │ Slippage      │        │
│    │ 89.5% acc │ │ cross-chk │ │ 60s TTL    │ │ (spread-based)│        │
│    └─────┬─────┘ └─────┬─────┘ └──────┬─────┘ └───────┬───────┘        │
│          └──────────────┼──────────────┘               │                │
│                         ▼                               │                │
│              ┌───────────────────┐                      │                │
│              │  Rust Executor    │◄─────────────────────┘                │
│              │  · Raydium swap   │                                       │
│              │  · sign & send    │                                       │
│              │  · Jito bundles   │  ◄── MEV protection                  │
│              │  · retry backoff  │                                       │
│              └────────┬──────────┘                                       │
│     ┌─────────────────┼──────────────────────────┐                      │
│     ▼                 ▼                          ▼                      │
│  PostgreSQL     Telegram           /health :8080                        │
│  trades DB      alerts/trades      Dashboard :3000                      │
│  analytics      bilan nocturne     SSE temps réel                       │
└──────────────────────────────────────────────────────────────────────────┘
                        │
              Solana Mainnet
              Helius RPC · Jito Block Engine · DEX pools
```

---

## Flux d'arbitrage

### Arbitrage direct (2-leg)

```
1. Le WebSocket feed poll les 4 DEXes toutes les 500ms
2. PriceCache stocke les prix + TVL par paire/DEX
3. ArbitrageDetector compare les quotes N×N
4. Spread > min_profit_pct (adaptatif 0.07–0.25%) ?
   → Oui: passe les filtres (ML scorer, Pyth oracle, dedup, price impact)
   → Exécute via Rust: Leg 1 SOL→USDC + Leg 2 USDC→SOL via Raydium API
   → Retry avec backoff si erreur transitoire (max 3 retries)
   → Enregistre dans PostgreSQL + notifie Telegram
```

### Arbitrage triangulaire (3-leg)

```
SOL → USDC (via meilleur DEX)
     → USDT (via meilleur DEX)
          → SOL (via meilleur DEX)

Profitable si: SOL_final > SOL_initial + fees (3 tx × base_fee + priority_fee)
```

---

## Modules Python

### Coeur du bot (`detector/`)

| Module | Rôle | Lignes |
|--------|------|--------|
| `main.py` | Boucle principale, orchestration de tous les composants | ~330 |
| `price_fetcher.py` | Fetch prix depuis Orca, Raydium, Meteora, Lifinity + TVL | ~300 |
| `arbitrage.py` | Détection d'opportunités cross-DEX + triangulaire + VolatilityTracker | ~210 |
| `executor_bridge.py` | Pont Python→Rust via subprocess, `swap_with_retry` | ~160 |
| `ws_price_feed.py` | Background polling 500ms avec PriceCache in-memory | ~120 |
| `price_impact.py` | Estimation price impact (constant-product), confidence score, weighted mean | ~80 |
| `sorted_opportunities.py` | SortedSet avec dedup et TTL pour ranking des opportunités | ~120 |

### Intelligence artificielle

| Module | Rôle |
|--------|------|
| `ml_scorer.py` | GradientBoosting scorer (89.5% accuracy), features: spread, heure, volatilité, DEX |
| `nightly_report.py` | Bilan IA nocturne (2h AM) via Ollama local ou Anthropic fallback |
| `oracle.py` | Cross-check Pyth Network vs prix DEX (anti-manipulation) |
| `trader_stats.py` | Analytics: best hours, best DEX routes, Sharpe ratio, streaks |

### Infrastructure

| Module | Rôle |
|--------|------|
| `helius.py` | Priority fees dynamiques + simulation tx avant envoi |
| `circuit_breaker.py` | Circuit breaker avec backoff exponentiel (3 états: CLOSED/OPEN/HALF_OPEN) |
| `batch_rpc.py` | Batch multiple appels Solana RPC en une seule requête HTTP |
| `health.py` | Serveur HTTP /health sur port 8080 + BotStats partagé |
| `db.py` | PostgreSQL: trades, price_snapshots, analytics queries |
| `config.py` | Chargement .env avec validation |
| `notifier.py` | Notifications Telegram (trades, alertes, résumés 6h) |
| `backtester.py` | Replay de données historiques (CSV/JSONL) avec métriques |

### MCP & supervision

| Module | Rôle |
|--------|------|
| `arb_control_mcp.py` | Serveur MCP avec 15 tools (voir section dédiée) |
| `mcp_runner.py` | Point d'entrée stdio pour agents IA externes |
| `vps_ops_mcp.py` | MCP pour opérations VPS (restart, deploy, metrics) |
| `defillama.py` | Client DeFiLlama (TVL cross-protocol, yields Solana) |

### Dashboard

| Module | Rôle |
|--------|------|
| `dashboard/app.py` | Flask + SSE, dark theme, auth basique, switch AI provider |

---

## Modules Rust (`executor/src/`)

| Module | Rôle |
|--------|------|
| `main.rs` | CLI clap avec 6 commandes: `swap`, `balance`, `sign-and-send`, `pubkey`, `send-bundle`, `detect`, `run` |
| `swap.rs` | Exécution swap via Raydium API (compute→transaction→sign→send) |
| `detector.rs` | Détection Rust native (Orca + Raydium fetch + find_opportunities) |
| `jito.rs` | Envoi de bundles Jito atomiques (HTTP API, tip accounts, MEV protection) |
| `config.rs` | Définition CLI args (clap) |

### Commandes Rust

```bash
# Vérifier le solde
./executor/target/release/executor balance --rpc-url $RPC_URL --keypair-path ./wallet.json

# Obtenir la clé publique
./executor/target/release/executor pubkey --keypair-path ./wallet.json

# Swap via Raydium (avec priority fee dynamique)
./executor/target/release/executor swap \
  --from SOL --to USDC --amount 0.05 --dex raydium \
  --min-out 4.5 --rpc-url $RPC_URL --keypair-path ./wallet.json \
  --priority-fee 50000

# Détection Rust native (scan unique)
./executor/target/release/executor detect \
  --input-token SOL --output-token USDC --amount 0.05

# Bot Rust autonome (boucle complète)
./executor/target/release/executor run \
  --rpc-url $RPC_URL --keypair-path ./wallet.json \
  --amount 0.05 --dry-run --poll-interval-sec 1

# Envoyer un Jito bundle (MEV-protected)
./executor/target/release/executor send-bundle \
  --transactions "base64tx1,base64tx2" \
  --rpc-url $RPC_URL --keypair-path ./wallet.json \
  --tip-lamports 50000
```

---

## Dashboard web

**URL** : `http://<VPS_IP>:3000` (auth: admin/admin par défaut)

Fonctionnalités :
- Métriques temps réel via Server-Sent Events (refresh 2s)
- Balance SOL, trades total, profit total, uptime, erreurs
- Mode (Dry Run / Live), opportunités vues, dernier scan
- Switch AI provider (Ollama ↔ Anthropic) depuis l'interface
- Dark theme (bg #0a0c10, accent #14f195)

---

## MCP Server (supervision IA)

Le serveur `arb-control` expose 15 tools appelables par tout agent MCP-compatible (Claude, Nexus, etc.).

```bash
# Lancer le serveur MCP
python -m detector.mcp_runner
```

### Tools disponibles

| Tool | Description |
|------|-------------|
| `get_live_state` | État temps réel: balance, trades, profit, uptime, erreurs |
| `get_session_stats` | Stats détaillées + volatilité + seuils adaptatifs |
| `get_recent_logs` | Dernières N lignes de log (paramétrable) |
| `set_param` | Modifier un paramètre en live (min_profit_pct, trade_amount_sol, etc.) |
| `pause_trading` | Pause le loop de trading |
| `resume_trading` | Reprend le trading |
| `force_dry_run` | Bascule en mode simulation |
| `set_ai_provider` | Switch Ollama ↔ Anthropic pour le bilan nocturne |
| `get_opportunities` | Prix récents et opportunités détectées |
| `get_pnl_curve` | Courbe P&L cumulative (liste de points) |
| `get_trader_stats` | Performance: Sharpe, best hours, best DEX routes, streaks |
| `get_market_context` | TVL DeFiLlama pour Raydium, Orca, Meteora (gratuit) |
| `db_stats_by_hour` | Trades par heure (PostgreSQL) |
| `db_dex_performance` | Performance par route DEX (PostgreSQL) |
| `db_recent_trades` | Derniers N trades (PostgreSQL) |
| `db_query` | Requête SQL SELECT libre (read-only) |

### VPS Operations MCP (`vps-ops`)

| Tool | Description |
|------|-------------|
| `restart_service` | Redémarrer arb-bot ou arb-dashboard |
| `get_logs` | Lire les logs bot/dashboard/error |
| `get_system_metrics` | CPU, RAM, disque, uptime, load |
| `deploy_update` | git pull → pip install → cargo build → restart |
| `get_disk_usage` | Taille du code, target, logs, espace libre |
| `get_service_status` | Statut systemd de tous les services |

---

## Installation

### Prérequis

- Python 3.12+
- Rust 1.78+ (cargo)
- PostgreSQL 16 (optionnel, pour analytics)
- Ollama (optionnel, pour bilan IA nocturne)

### Étapes

```bash
git clone https://github.com/cyranoaladin/solana-arb-bot.git
cd solana-arb-bot

# 1. Configuration
cp .env.example .env
# Éditer .env avec vos valeurs (RPC_URL, TELEGRAM_*, etc.)

# 2. Dépendances Python
pip install -r detector/requirements.txt
pip install -r dashboard/requirements.txt

# 3. Compilation Rust
cd executor && cargo build --release && cd ..

# 4. Lancer en dry-run
python -m detector.main
```

---

## Configuration

### Variables d'environnement (.env)

| Variable | Description | Défaut |
|----------|-------------|--------|
| `RPC_URL` | Endpoint Solana RPC (Helius recommandé) | _(requis)_ |
| `KEYPAIR_PATH` | Chemin vers le fichier keypair JSON | `./wallet.json` |
| `TELEGRAM_BOT_TOKEN` | Token du bot Telegram | _(requis)_ |
| `TELEGRAM_CHAT_ID` | Chat ID pour notifications | _(requis)_ |
| `TRADE_AMOUNT_SOL` | Montant SOL par trade | `0.05` |
| `MIN_PROFIT_PCT` | Seuil minimum de profit % | `0.1` |
| `MAX_SLIPPAGE_PCT` | Slippage maximum % | `0.5` |
| `KILL_SWITCH_SOL` | Arrêt si balance < ce seuil | `0.05` |
| `DRY_RUN` | Mode simulation (true/false) | `true` |
| `POLL_INTERVAL_SEC` | Intervalle du main loop (secondes) | `3` |
| `EXECUTOR_PATH` | Chemin du binaire Rust | `./executor/target/release/executor` |
| `ANTHROPIC_API_KEY` | Clé API Anthropic (bilan IA, optionnel) | _(vide)_ |
| `LOG_PATH` | Chemin des logs | `/var/log/arb-bot/bot.log` |
| `OLLAMA_URL` | URL du serveur Ollama | `http://localhost:11434` |
| `OLLAMA_MODEL` | Modèle Ollama pour le bilan | `qwen2.5:1.5b` |
| `DATABASE_URL` | URL PostgreSQL | `postgresql://arbbot:arbbot123@localhost:5432/arbbot` |
| `DASHBOARD_USER` | Login dashboard | `admin` |
| `DASHBOARD_PASS` | Mot de passe dashboard | `admin` |

---

## Déploiement VPS

```bash
# Déploiement automatique (rsync + build + restart)
./deploy.sh
```

Le script :
1. Rsync le projet vers `/opt/solana-arb-bot` sur le VPS
2. Installe les dépendances Python + dashboard
3. Compile le Rust executor (installe Rust si absent)
4. Installe les services systemd
5. Redémarre le bot + dashboard
6. Vérifie le /health endpoint

### Services systemd

| Service | Description | Port |
|---------|-------------|------|
| `arb-bot` | Bot principal (Python) | 8080 (/health) |
| `arb-dashboard` | Dashboard web (Flask) | 3000 |

```bash
# Gestion
sudo systemctl start|stop|restart arb-bot
sudo systemctl start|stop|restart arb-dashboard

# Logs
tail -f /var/log/arb-bot/bot.log      # logs JSON structurés
tail -f /var/log/arb-bot/error.log     # stderr
tail -f /var/log/arb-bot/dashboard.log # dashboard
```

---

## Tests

### Suite de tests — 185 tests

```bash
# Python (166 tests)
python -m pytest tests/ -v

# Rust (19 tests)
cd executor && cargo test

# Couverture Python
python -m pytest tests/ --cov=detector --cov-report=term-missing

# Tests par catégorie
python -m pytest tests/test_integration.py -v    # 18 tests E2E
python -m pytest tests/test_performance.py -v    # 21 tests perf/stress
python -m pytest tests/test_mcp_tools.py -v      # 15 tests MCP
python -m pytest tests/test_dashboard.py -v      # 6 tests Flask
python -m pytest tests/test_api_endpoints.py -v  # 4 tests /health
```

### Catégories de tests

| Catégorie | Tests | Ce qui est couvert |
|-----------|-------|-------------------|
| Unitaires | 80+ | Chaque module indépendamment |
| Intégration | 18 | Pipeline complet, triangulaire, edge cases |
| API/Endpoints | 25 | /health HTTP, MCP tools, dashboard Flask |
| Performance | 21 | Vitesse détection, stress circuit breaker, limites |
| Rust | 19 | detector.rs, swap.rs, jito.rs |

### CI GitHub Actions

Le pipeline CI tourne à chaque push/PR :
1. **Python** : install deps → pytest → py_compile lint
2. **Rust** : cargo check → cargo clippy -D warnings → cargo build --release

---

## Production

### Mise en production

```bash
# 1. Vérifier l'adresse du wallet
./executor/target/release/executor pubkey --keypair-path ./wallet.json

# 2. Funder le wallet avec SOL (min 0.1 SOL recommandé)

# 3. Basculer en mode live
ssh root@<VPS_IP> 'sed -i "s/DRY_RUN=true/DRY_RUN=false/" /opt/solana-arb-bot/.env'
ssh root@<VPS_IP> 'systemctl restart arb-bot'

# 4. Surveiller
# Dashboard: http://<VPS_IP>:3000
# Health: curl http://<VPS_IP>:8080/health
# Telegram: notifications automatiques
# Logs: ssh root@<VPS_IP> 'tail -f /var/log/arb-bot/bot.log'
```

### Backtesting

```bash
# Générer des données de test
python -m detector.backtester --generate-sample sample.jsonl

# Lancer un backtest
python -m detector.backtester sample.jsonl
```

### Entraîner le modèle ML

```bash
python -m detector.ml_scorer
# Génère models/opportunity_scorer.pkl (89.5% accuracy sur données synthétiques)
# Le modèle s'améliore avec des données réelles après quelques semaines de trades
```

---

## Sécurité

| Mesure | Détail |
|--------|--------|
| `wallet.json` exclu de git | `.gitignore` + supprimé du tracking |
| `.env` exclu de git | Jamais commité, contient les secrets |
| Kill switch | Arrêt automatique si balance < `KILL_SWITCH_SOL` |
| Dry run par défaut | `DRY_RUN=true` — aucun trade réel sans activation explicite |
| DB queries read-only | MCP `db_query` n'accepte que les SELECT |
| MCP params bornés | `set_param` valide min/max pour chaque paramètre |
| Dashboard auth | Basic auth requis (configurable) |
| Pyth oracle check | Skip les trades si DEX-oracle divergence > 1% |
| Simulation pre-trade | `simulateTransaction` avant envoi réel |
| Circuit breaker | Pause automatique après 3-5 échecs RPC consécutifs |
| Jito bundles | Transactions invisibles dans le mempool (anti front-run) |
| Wallet jetable | Capital limité, max 0.5 SOL recommandé en V1 |

---

## Licence

Projet privé — Alaeddine Ben Rhouma, 2026.
