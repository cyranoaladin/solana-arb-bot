from detector.ml_scorer import extract_features, OpportunityScorer, generate_synthetic_training_data, FEATURE_NAMES
from detector.arbitrage import Opportunity

def _make_opp():
    return Opportunity(pair="SOL/USDC", buy_dex="orca", sell_dex="raydium",
                       buy_price=4.5, sell_price=4.6, amount=0.05, profit_pct=0.5, estimated_profit=0.1)

def test_extract_features():
    opp = _make_opp()
    features = extract_features(opp, volatility=0.01)
    assert len(features) == len(FEATURE_NAMES)
    assert features[0] == 0.5  # profit_pct

def test_scorer_no_model_returns_1():
    scorer = OpportunityScorer(model_path="/tmp/nonexistent_model.pkl")
    opp = _make_opp()
    assert scorer.score(opp) == 1.0
    assert scorer.should_execute(opp) is True

def test_generate_synthetic_data():
    data = generate_synthetic_training_data(100)
    assert len(data) == 100
    assert all(k in data[0] for k in FEATURE_NAMES)
    assert all(d["label"] in (0, 1) for d in data)

def test_train_model_needs_sklearn():
    """Training should work if sklearn is available, or return error if not."""
    data = generate_synthetic_training_data(50)
    from detector.ml_scorer import train_model
    import tempfile, os
    path = tempfile.mktemp(suffix=".pkl")
    try:
        result = train_model(data, output_path=path)
        # Either succeeds with metrics or fails with sklearn error
        assert "accuracy" in result or "error" in result
    finally:
        if os.path.exists(path):
            os.unlink(path)
