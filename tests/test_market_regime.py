from tools.market_regime import (
    REGIME_BROAD_RED_MARKET,
    REGIME_SIDEWAYS_CHOP,
    REGIME_UPTREND,
    REGIME_UNKNOWN,
    classify_market_regime,
)


def row(symbol, change):
    return {"symbol": symbol, "change_pct": change}


def test_unknown_when_no_snapshots():
    regime = classify_market_regime([])
    assert regime.regime == REGIME_UNKNOWN
    assert regime.confidence == 0.0


def test_broad_red_requires_negative_breadth_and_majors():
    regime = classify_market_regime([
        row("BTC-USD", -0.01),
        row("ETH-USD", -0.012),
        row("SOL-USD", -0.009),
        row("DOGE-USD", -0.006),
        row("ADA-USD", 0.001),
    ])
    assert regime.regime == REGIME_BROAD_RED_MARKET
    assert regime.posture == "restricted"


def test_uptrend_requires_green_breadth_and_majors():
    regime = classify_market_regime([
        row("BTC-USD", 0.01),
        row("ETH-USD", 0.008),
        row("SOL-USD", 0.006),
        row("DOGE-USD", 0.004),
        row("ADA-USD", -0.001),
    ])
    assert regime.regime == REGIME_UPTREND
    assert regime.posture == "selective_long"


def test_mixed_low_conviction_becomes_chop():
    regime = classify_market_regime([
        row("BTC-USD", 0.001),
        row("ETH-USD", -0.001),
        row("SOL-USD", 0.0005),
        row("DOGE-USD", -0.0004),
    ])
    assert regime.regime == REGIME_SIDEWAYS_CHOP
    assert regime.posture == "wait"
