from tools.market_weather import build_market_weather


def row(symbol, change):
    return {"symbol": symbol, "change_pct": change}


def test_weather_exposes_operator_friendly_fields():
    weather = build_market_weather([
        row("BTC-USD", -0.01),
        row("ETH-USD", -0.011),
        row("SOL-USD", -0.004),
        row("ADA-USD", 0.001),
    ])
    payload = weather.to_dict()
    assert payload["market_regime"] in {"broad_red_market", "downtrend"}
    assert payload["risk_posture"] in {"restricted", "defensive"}
    assert payload["btc_direction"] == "down"
    assert payload["eth_direction"] == "down"
    assert payload["breadth_total"] == 4
