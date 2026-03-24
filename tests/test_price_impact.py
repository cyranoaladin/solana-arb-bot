from detector.price_impact import estimate_price_impact, compute_confidence, weighted_mean_price, filter_by_price_impact
from detector.price_fetcher import PriceQuote

def _q(dex, price, liq=0):
    return PriceQuote(dex=dex, input_token="SOL", output_token="USDC",
                      input_amount=1.0, output_amount=price, price=price, liquidity=liq)

def test_price_impact_zero_liquidity():
    q = _q("orca", 90, liq=0)
    assert estimate_price_impact(q, 100) == 0.0

def test_price_impact_large_pool():
    q = _q("orca", 90, liq=10_000_000)
    impact = estimate_price_impact(q, 100)
    assert impact < 0.01  # negligible impact

def test_price_impact_small_pool():
    q = _q("orca", 90, liq=1000)
    impact = estimate_price_impact(q, 100)
    assert impact > 1.0  # significant impact

def test_weighted_mean_price():
    quotes = [_q("orca", 90, liq=10_000_000), _q("raydium", 92, liq=1_000_000)]
    wmean = weighted_mean_price(quotes)
    # Should be closer to 90 (weighted by 10x liquidity)
    assert 90 < wmean < 91

def test_confidence_high_liquidity():
    quotes = [_q("orca", 90, liq=10_000_000), _q("raydium", 90.1, liq=1_000_000)]
    conf = compute_confidence(quotes[0], quotes)
    assert conf > 0.5

def test_filter_by_price_impact():
    quotes = [_q("orca", 90, liq=10_000_000), _q("tiny", 91, liq=500)]
    filtered = filter_by_price_impact(quotes, trade_amount_usd=100, max_impact_pct=1.0)
    assert len(filtered) == 1
    assert filtered[0].dex == "orca"
