"""ML-based opportunity scorer using XGBoost/LightGBM-like gradient boosting.

Uses scikit-learn's GradientBoostingClassifier as a lightweight alternative
to XGBoost that requires no extra dependencies (sklearn is widely available).
Falls back gracefully if sklearn is not installed.
"""

from __future__ import annotations

import json
import logging
import pickle
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

MODEL_PATH = Path("models/opportunity_scorer.pkl")

# Feature extraction
DEX_ENCODING = {"orca": 0, "raydium": 1, "meteora": 2, "lifinity": 3}


def extract_features(opportunity, volatility: float = 0.0) -> list[float]:
    """Extract ML features from an Opportunity object.

    Features:
    - profit_pct: detected spread percentage
    - hour: UTC hour (0-23)
    - day_of_week: 0=Monday, 6=Sunday
    - volatility: current CV from VolatilityTracker
    - buy_dex_id: numeric encoding of buy DEX
    - sell_dex_id: numeric encoding of sell DEX
    - amount: trade amount
    """
    now = datetime.now(timezone.utc)
    return [
        opportunity.profit_pct,
        now.hour,
        now.weekday(),
        volatility,
        DEX_ENCODING.get(opportunity.buy_dex, 4),
        DEX_ENCODING.get(opportunity.sell_dex, 4),
        opportunity.amount,
    ]


FEATURE_NAMES = [
    "profit_pct", "hour", "day_of_week", "volatility",
    "buy_dex_id", "sell_dex_id", "amount",
]


class OpportunityScorer:
    """Scores arbitrage opportunities using a trained ML model.

    If no model is loaded, returns 1.0 (always execute) as fallback.
    """

    def __init__(self, model_path: str | Path = MODEL_PATH) -> None:
        self.model = None
        self.model_path = Path(model_path)
        self._load_model()

    def _load_model(self) -> None:
        if self.model_path.exists():
            try:
                with open(self.model_path, "rb") as f:
                    self.model = pickle.load(f)
                logger.info("ML model loaded from %s", self.model_path)
            except Exception:
                logger.warning("Failed to load ML model from %s", self.model_path)
                self.model = None

    def score(self, opportunity, volatility: float = 0.0) -> float:
        """Return probability (0-1) that this opportunity will be profitable.

        Returns 1.0 if no model is loaded (always execute).
        """
        if self.model is None:
            return 1.0
        try:
            features = [extract_features(opportunity, volatility)]
            proba = self.model.predict_proba(features)[0][1]  # P(profitable)
            return float(proba)
        except Exception:
            logger.warning("ML scoring failed, returning 1.0")
            return 1.0

    def should_execute(self, opportunity, volatility: float = 0.0, threshold: float = 0.6) -> bool:
        """Return True if the model recommends executing this opportunity."""
        return self.score(opportunity, volatility) >= threshold


def train_model(
    training_data: list[dict],
    output_path: str | Path = MODEL_PATH,
) -> dict:
    """Train the opportunity scorer on historical data.

    training_data: list of dicts with keys matching FEATURE_NAMES + "label" (1=profitable, 0=not)

    Returns training metrics.
    """
    try:
        from sklearn.ensemble import GradientBoostingClassifier
        from sklearn.model_selection import train_test_split
        from sklearn.metrics import accuracy_score, precision_score, recall_score
    except ImportError:
        logger.error("scikit-learn not installed. Run: pip install scikit-learn")
        return {"error": "scikit-learn not installed"}

    if len(training_data) < 20:
        return {"error": f"Not enough data: {len(training_data)} samples (need 20+)"}

    X = [[d.get(f, 0) for f in FEATURE_NAMES] for d in training_data]
    y = [d.get("label", 0) for d in training_data]

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    model = GradientBoostingClassifier(
        n_estimators=100,
        max_depth=3,
        learning_rate=0.1,
        random_state=42,
    )
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)
    metrics = {
        "accuracy": round(accuracy_score(y_test, y_pred), 4),
        "precision": round(precision_score(y_test, y_pred, zero_division=0), 4),
        "recall": round(recall_score(y_test, y_pred, zero_division=0), 4),
        "train_size": len(X_train),
        "test_size": len(X_test),
        "features": FEATURE_NAMES,
    }

    # Feature importance
    importances = dict(zip(FEATURE_NAMES, [round(float(v), 4) for v in model.feature_importances_]))
    metrics["feature_importance"] = importances

    # Save model
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        pickle.dump(model, f)
    logger.info("Model saved to %s — accuracy=%.4f", output_path, metrics["accuracy"])
    metrics["model_path"] = str(output_path)

    return metrics


def generate_synthetic_training_data(n_samples: int = 500) -> list[dict]:
    """Generate synthetic training data from realistic distributions.

    Used for initial model training when no real trade data is available.
    """
    import random
    data = []
    for _ in range(n_samples):
        profit_pct = random.uniform(0.05, 2.0)
        hour = random.randint(0, 23)
        dow = random.randint(0, 6)
        vol = random.uniform(0.001, 0.05)
        buy_dex = random.randint(0, 3)
        sell_dex = random.randint(0, 3)
        amount = random.uniform(0.01, 0.1)

        # Label: higher profit + lower vol + good hours = more likely profitable
        score = profit_pct * 2 - vol * 10 + (1 if 8 <= hour <= 20 else 0) * 0.3
        label = 1 if score > random.gauss(1.0, 0.5) else 0

        data.append({
            "profit_pct": profit_pct,
            "hour": hour,
            "day_of_week": dow,
            "volatility": vol,
            "buy_dex_id": buy_dex,
            "sell_dex_id": sell_dex,
            "amount": amount,
            "label": label,
        })
    return data


if __name__ == "__main__":
    """Train a model on synthetic data for initial deployment."""
    import sys
    logging.basicConfig(level=logging.INFO)

    print("Generating synthetic training data...")
    data = generate_synthetic_training_data(1000)
    print(f"Training on {len(data)} samples...")
    metrics = train_model(data)
    print(json.dumps(metrics, indent=2))
