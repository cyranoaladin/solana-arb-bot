# Solana Arbitrage Bot — Design Spec

**Date** : 23 mars 2026
**Auteur** : Alaeddine Ben Rhouma
**Statut** : Approuvé (brainstorming)

---

## 1. Objectif

Bot d'arbitrage automatique sur Solana exploitant les écarts de prix entre DEX (Jupiter agrégateur vs Raydium/Orca en direct). Détection en Python, exécution en Rust. Déployé sur VPS Hetzner (46.224.150.0).

## 2. Contraintes

| Paramètre | Valeur |
|-----------|--------|
| Capital initial | 50$ (~0.35 SOL) |
| RPC | Helius free tier (30 req/s, 1M req/mois) |
| Paires | SOL/USDC, SOL/USDT |
| Seuil de profit | > 0.1% net après frais |
| Montant max par trade | 0.1 SOL |
| Kill switch | Arrêt si solde < 0.05 SOL |
| Mode | Full automatique 24/7 + dry-run pour tests |

## 3. Architecture

### 3.1 Structure du projet

```
solana-arb-bot/
├── detector/                # Python — détection des opportunités
│   ├── main.py              # Boucle principale, orchestration
│   ├── price_fetcher.py     # Fetch prix Jupiter + Raydium + Orca
│   ├── arbitrage.py         # Calcul des écarts, décision go/no-go
│   ├── config.py            # Paramètres (seuil, paires, montants)
│   ├── notifier.py          # Alertes Telegram
│   └── requirements.txt
│
├── executor/                # Rust — exécution des transactions
│   ├── src/
│   │   ├── main.rs          # CLI : reçoit les ordres du Python
│   │   ├── swap.rs          # Construction + envoi des transactions
│   │   └── config.rs        # Lecture .env, paramètres
│   └── Cargo.toml
│
├── .env                     # Clé wallet + token Telegram + RPC URL
├── .env.example             # Template sans secrets
├── .gitignore
├── deploy.sh                # Script de déploiement VPS
└── README.md
```

### 3.2 Flux de données

1. `price_fetcher.py` interroge en parallèle :
   - Jupiter Quote API (meilleur prix agrégé)
   - Raydium API (prix direct du pool)
   - Orca API (prix direct du pool)
2. `arbitrage.py` compare les prix pour chaque paire (SOL/USDC, SOL/USDT) :
   - Calcule le profit net = prix de vente - prix d'achat - frais tx (~0.000005 SOL) - slippage estimé (0.5%)
   - Si profit > 0.1% → déclenche l'exécution
3. Python appelle le binaire Rust via `subprocess`
4. Rust construit la transaction, signe avec le wallet jetable, envoie via Helius RPC
5. Python reçoit le résultat JSON et notifie via Telegram

### 3.3 Communication Python → Rust

Interface CLI du binaire Rust :

```bash
./executor swap \
  --from SOL --to USDC \
  --amount 0.1 \
  --dex raydium \
  --min-out 14.5 \
  --rpc-url $RPC_URL \
  --keypair-path $KEYPAIR_PATH
```

Retour JSON sur stdout :

```json
{
  "status": "ok",
  "tx_hash": "5xK...",
  "amount_in": 0.1,
  "amount_out": 14.52,
  "fee": 0.000005,
  "dex": "raydium"
}
```

En cas d'erreur :

```json
{
  "status": "error",
  "error": "insufficient funds",
  "details": "balance 0.04 SOL < required 0.1 SOL"
}
```

### 3.4 Dry-run mode

En mode dry-run (`--dry-run` flag), le Rust simule la transaction sans l'envoyer, retourne le résultat estimé. Permet de valider la stratégie sans risque.

## 4. Sécurité

- Wallet jetable dédié au bot, financé avec le strict minimum
- Clé privée dans `.env`, fichier dans `.gitignore`
- Montant max par trade : configurable, défaut 0.1 SOL
- Kill switch : le bot s'arrête et envoie une alerte Telegram si le solde passe sous 0.05 SOL
- Aucune clé en dur dans le code

## 5. Notifications Telegram

| Événement | Contenu |
|-----------|---------|
| Trade exécuté | Paire, direction, montant, profit net, tx hash, lien Solscan |
| Erreur de transaction | Type d'erreur, contexte, action prise |
| Résumé périodique (6h) | Nombre de trades, profit total, solde actuel |
| Alerte critique | Solde sous le seuil, bot arrêté, RPC down |

## 6. Déploiement VPS

- VPS : Hetzner 46.224.150.0
- Service `systemd` : `arb-bot.service` avec auto-restart
- Logs : `/var/log/arb-bot/` avec rotation
- Binaire Rust cross-compilé ou compilé sur le VPS
- Mise à jour : `git pull` + rebuild Rust + restart service

## 7. Dépendances

### Python (detector)

- `httpx` — requêtes HTTP async
- `python-dotenv` — chargement .env
- `python-telegram-bot` — notifications
- `asyncio` — boucle événementielle

### Rust (executor)

- `solana-sdk` — interaction blockchain
- `solana-client` — RPC client
- `spl-token` — opérations sur tokens SPL
- `serde` + `serde_json` — sérialisation JSON
- `clap` — parsing arguments CLI
- `dotenv` — chargement .env
- `anyhow` — gestion d'erreurs

## 8. Limites connues

- Helius free tier : 30 req/s, polling toutes les 3s (pas de WebSocket)
- Pas de Jito bundles : transactions standard, vulnérable au front-running
- Latence Python ~50ms pour la détection, compensée par Rust ~5ms pour l'exécution
- Capital limité (0.35 SOL) : les profits seront modestes
- Les bots pro en Rust pur avec Jito capteront les gros arbitrages avant nous

## 9. Évolutions futures (hors scope V1)

- Migration complète en Rust si la stratégie est rentable
- Ajout de Jito bundles pour la protection MEV
- WebSocket pour le prix en temps réel (RPC payant)
- Paires supplémentaires (Meteora, autres tokens)
- Arbitrage triangulaire (SOL → A → B → SOL)
