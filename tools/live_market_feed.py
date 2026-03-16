"""Fetch live crypto marketplace data and normalize snapshots."""

from __future__ import annotations

import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from typing import Dict, List

from tools.live_universe import eligibility_for, target_symbol_list

COINGECKO_ENDPOINT = "https://api.coingecko.com/api/v3/simple/price"


def fetch_market_data(symbols: List[str]) -> List[Dict[str, object]]:
    ids = ",".join(symbol.lower().split("-")[0] for symbol in symbols)
    params = {"ids": ids, "vs_currencies": "usd"}
    url = f"{COINGECKO_ENDPOINT}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=10) as response:
        body = response.read().decode()
    data = json.loads(body)
    snapshots: List[Dict[str, object]] = []
    timestamp = datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()
    for symbol in symbols:
        slug = symbol.lower().split("-")[0]
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
