"""Tiered live-market symbol universes and eligibility helpers."""

from __future__ import annotations

from typing import Dict, List

SYMBOL_CATALOG: Dict[str, Dict[str, object]] = {
    "BTC-USD": {"tier": "core", "paper": True, "real_money": True, "min_volume": 1_000_000},
    "ETH-USD": {"tier": "core", "paper": True, "real_money": True, "min_volume": 800_000},
    "XRP-USD": {"tier": "liquid", "paper": True, "real_money": False, "min_volume": 400_000},
    "SOL-USD": {"tier": "liquid", "paper": True, "real_money": False, "min_volume": 350_000},
    "ADA-USD": {"tier": "liquid", "paper": True, "real_money": False, "min_volume": 300_000},
    "DOGE-USD": {"tier": "liquid", "paper": True, "real_money": False, "min_volume": 250_000},
    "LTC-USD": {"tier": "liquid", "paper": True, "real_money": False, "min_volume": 200_000},
    "AVAX-USD": {"tier": "liquid", "paper": True, "real_money": False, "min_volume": 180_000},
    "LINK-USD": {"tier": "liquid", "paper": True, "real_money": False, "min_volume": 160_000},
    "SHIB-USD": {"tier": "speculative", "paper": True, "real_money": False, "min_volume": 30_000},
    "PEPE-USD": {"tier": "speculative", "paper": True, "real_money": False, "min_volume": 25_000},
    "BONK-USD": {"tier": "speculative", "paper": True, "real_money": False, "min_volume": 20_000},
}
CORE_MAJORS = [symbol for symbol, meta in SYMBOL_CATALOG.items() if meta["tier"] == "core"]
LIQUID_ALTS = [symbol for symbol, meta in SYMBOL_CATALOG.items() if meta["tier"] == "liquid"]
SPECULATIVE_TIER = [symbol for symbol, meta in SYMBOL_CATALOG.items() if meta["tier"] == "speculative"]
WATCH_UNIVERSE: List[str] = list(SYMBOL_CATALOG.keys())
PAPER_TRADE_UNIVERSE: List[str] = [s for s, meta in SYMBOL_CATALOG.items() if meta["paper"]]
REAL_MONEY_ELIGIBLE_UNIVERSE: List[str] = [s for s, meta in SYMBOL_CATALOG.items() if meta.get("real_money") and meta.get("min_volume", 0) >= 1_000_000]


def eligibility_for(symbol: str) -> Dict[str, object]:
    meta = SYMBOL_CATALOG.get(symbol, {})
    return {
        "tier": meta.get("tier", "watch"),
        "watch_ok": symbol in WATCH_UNIVERSE,
        "paper_ok": meta.get("paper", False),
        "real_money_ok": symbol in REAL_MONEY_ELIGIBLE_UNIVERSE,
        "min_volume": meta.get("min_volume", 0),
    }


def target_symbol_list(preferred: str | None = None) -> List[str]:
    if preferred:
        return [sym for sym in preferred.split(",") if sym in WATCH_UNIVERSE]
    return PAPER_TRADE_UNIVERSE
