"""Fetch live crypto marketplace data and normalize snapshots."""
from __future__ import annotations

import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from typing import Dict, List

from tools.live_universe import eligibility_for

COINGECKO_ENDPOINT = "https://api.coingecko.com/api/v3/simple/price"
COIN_ID_MAP = {
    "BTC-USD": "bitcoin",
    "ETH-USD": "ethereum",
    "XRP-USD": "ripple",
    "SOL-USD": "solana",
    "ADA-USD": "cardano",
    "DOGE-USD": "dogecoin",
    "LTC-USD": "litecoin",
    "AVAX-USD": "avalanche-2",
    "LINK-USD": "chainlink",
    "SHIB-USD": "shiba-inu",
    "PEPE-USD": "pepe",
    "BONK-USD": "bonk",
}

def fetch_market_data(symbols: List[str]) -> List[Dict[str, object]]:
    ids = ",".join(COIN_ID_MAP.get(symbol, symbol).replace("-usd","") for symbol in symbols)
    params = {"ids": ids, "vs_currencies": "usd"}
    url = f"{COINGECKO_ENDPOINT}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=10) as response:
        body = response.read().decode()
    data = json.loads(body)
    snapshots: List[Dict[str, object]] = []
    timestamp = datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()
    for symbol in symbols:
        slug = COIN_ID_MAP.get(symbol, symbol).lower().replace("-usd","")
        price_info = data.get(slug)
        price = price_info.get("usd") if price_info else None
        meta = eligibility_for(symbol)
        snapshot = {
            "timestamp": timestamp,
            "symbol": symbol,
            "price": price,
            "source": "coingecko",
            "tier": meta["tier"],
            "watch_ok": meta["watch_ok"],
            "paper_ok": meta["paper_ok"],
            "real_money_ok": meta["real_money_ok"],
        }
        snapshots.append(snapshot)
    return snapshots
