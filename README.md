# Solana Arbitrage Bot

Bot de détection et d'exécution d'opportunités d'arbitrage sur Solana.

**Status : dry-run / observation ready. Live restreint — voir [Safety Gates](#safety-gates).**

---

## Current execution truth

| Capacité | Statut réel |
|----------|------------|
| Détection de prix Orca | Observation only (pool spot price, pas de swap API) |
| Détection de prix Raydium | Executable (compute/swap API, amount-specific) |
| Détection de prix Meteora | Observation only (pool price, pas de swap API) |
| Détection de prix Lifinity | Best-effort observation (API instable) |
| Exécution swap Raydium | Supporté (seul DEX exécutable) |
| Exécution swap Orca | **Non supporté** — pas d'API HTTP swap |
| Exécution swap Meteora | **Non supporté** |
| Exécution swap Lifinity | **Non supporté** |
| Arbitrage 2-leg | Raydium→Raydium uniquement. **Non atomique** (2 tx séparées) |
| Arbitrage triangulaire | Détection uniquement. **Aucune exécution** |
| Jito bundles | Code présent. **Non branché au flux principal** |
| Atomicité | **Aucune** dans le flux standard |

### Ce que le bot fait réellement

1. Poll les prix toutes les 500ms depuis 4 DEXes (Orca, Raydium, Meteora, Lifinity)
2. Compare les prix — détecte les spreads cross-DEX
3. **En dry-run** : log l'opportunité, notifie Telegram, aucune transaction
4. **En live (si autorisé)** : exécute les deux legs via Raydium API (pas sur le DEX de détection)

### Ce que le bot NE fait PAS

- Pas d'exécution cross-DEX réelle (pas de "buy on Orca, sell on Raydium")
- Pas d'atomicité (les 2 legs sont des transactions séparées)
- Pas de realized PnL (seul l'estimated profit est suivi)
- Pas de réconciliation on-chain des résultats

---

## Architecture

```
Python (détection + orchestration)  ←→  Rust (exécution + signing)

detector/
├── main.py              Main loop
├── price_fetcher.py      4 DEXes (Orca=ref, Raydium=exec, Meteora=ref, Lifinity=ref)
├── arbitrage.py          Spread detection + triangular (observation only)
├── ws_price_feed.py      Background HTTP polling 500ms (pas WebSocket)
├── executor_bridge.py    Python→Rust subprocess bridge
├── config.py             Configuration + safety gates
├── health.py             /health endpoint (127.0.0.1:8080)
├── notifier.py           Telegram notifications
├── db.py                 PostgreSQL persistence
├── helius.py             Priority fees + simulation
├── oracle.py             Pyth oracle cross-check
├── ml_scorer.py          ML scoring (synthetic data, placeholder)
└── ...

executor/src/
├── main.rs               CLI (swap, balance, detect, run, send-bundle)
├── swap.rs               Raydium swap via API (min_out enforced)
├── detector.rs           Rust-native detection
├── jito.rs               Jito bundles (available, not wired to main loop)
└── config.rs             CLI args

dashboard/
└── app.py                Flask dashboard (127.0.0.1:3000, auth required)
```

---

## Supported live execution

| Route | Supporté | Remarques |
|-------|----------|-----------|
| Raydium → Raydium | Oui | Seule route exécutable. Non atomique. |
| Orca → Raydium | **Non** | Orca = observation. Exécution via Raydium. |
| Meteora → Raydium | **Non** | Même limitation. |
| Triangulaire | **Non** | Observation only. |

---

## Observation-only capabilities

Ces fonctionnalités **détectent** mais **n'exécutent pas** :

- **Orca prices** : spot price de pool, pas de swap quote
- **Meteora DLMM prices** : current_price de pool
- **Lifinity prices** : API best-effort
- **Triangular arbitrage** : détection SOL→A→B→SOL, log + Telegram, pas d'exécution
- **DeFiLlama TVL** : contexte marché, pas de signal de trading
- **Pyth oracle** : sanity check, pas de source de pricing

---

## Known limitations

1. **Pas d'atomicité** : les 2 legs d'un arb sont des transactions séparées. Entre les deux, le prix peut bouger. Risque MEV.
2. **Estimated ≠ Realized** : le bot track l'estimated profit (basé sur les quotes avant exécution). Le realized profit (après slippage, fees, MEV) n'est pas encore réconcilié.
3. **Quotes hétérogènes** : Orca/Meteora donnent des prix spot. Raydium donne une quote exécutable. Comparer les deux n'est pas strictement apples-to-apples.
4. **ML scorer** : entraîné sur données synthétiques. Accuracy (89.5%) non significative en conditions réelles.
5. **Backtester** : simule slippage/MEV mais ne modélise pas la latence réseau ni les adversaires.
6. **Jito bundles** : code présent (`send-bundle` CLI), pas branché au flux Python principal.

---

## Safety gates

Le bot ne peut **pas** exécuter en live sans satisfaire :

1. `DRY_RUN=false` dans `.env`
2. `TRADING_ENABLED=true` dans `.env` (crash au démarrage sinon)
3. `LIVE_TRADING_ALLOW_UNSUPPORTED_ROUTES=false` bloque les routes non-Raydium
4. Balance >= `TRADE_AMOUNT_SOL` vérifié à chaque cycle
5. Kill switch si balance < `KILL_SWITCH_SOL`
6. Dashboard credentials fortes (refuse admin/admin)
7. Health/Dashboard bindés sur 127.0.0.1 par défaut
8. Services systemd sous utilisateur `arbbot` (non-root)

### Why live remains restricted

Le live est restreint car :
- L'exécution n'est pas atomique (2 tx séparées = risque d'inventaire)
- Jito bundles ne sont pas branchés au flux standard
- Pas de réconciliation realized PnL
- Quotes de détection (Orca) ≠ quotes d'exécution (Raydium)

---

## Estimated vs Realized

| Métrique | Signification |
|----------|--------------|
| `estimated_profit` | Profit calculé à partir des quotes AVANT exécution |
| `realized_profit` | Profit réel APRÈS exécution on-chain (non implémenté) |

Le dashboard, les logs, et Telegram affichent **estimated_profit**. C'est un indicateur, pas une mesure de performance réelle.

---

## Setup

```bash
git clone https://github.com/cyranoaladin/solana-arb-bot.git
cd solana-arb-bot

cp .env.example .env  # configurer TOUTES les variables

pip install -r detector/requirements.txt
pip install -r dashboard/requirements.txt

cd executor && cargo build --release && cd ..

python -m detector.main  # dry-run par défaut
```

## Configuration (.env)

Voir `.env.example` pour la liste complète. Variables critiques :

| Variable | Obligatoire | Description |
|----------|-------------|-------------|
| `RPC_URL` | Oui | Endpoint Solana RPC |
| `TRADING_ENABLED` | Pour live | Opt-in explicite pour le live |
| `DRY_RUN` | — | `true` par défaut |
| `DASHBOARD_USER` | Oui | Credentials fortes (refuse les faibles) |
| `DASHBOARD_PASS` | Oui | Credentials fortes |

## Deployment

```bash
./deploy.sh  # crée user arbbot, venv, build Rust, restart services
```

Health et dashboard bindés sur 127.0.0.1. Accès distant via SSH tunnel :
```bash
ssh -L 3000:127.0.0.1:3000 -L 8080:127.0.0.1:8080 user@vps
```

## Tests

```bash
python -m pytest tests/ -v       # Python
cd executor && cargo test        # Rust
```

---

## Licence

Projet privé — Alaeddine Ben Rhouma, 2026.
