"""Feed abstraction supporting simulation and Robinhood live quotes."""

from __future__ import annotations

import base64
import binascii
import json
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import requests
from nacl.signing import SigningKey


class FeedError(Exception):
    """Base exception for feed problems."""


class FeedRetryableError(FeedError):
    """Transient error that should trigger a retry."""


class FeedFatalError(FeedError):
    """Irrecoverable error that should stop the feed."""


def _normalize_sim_path(path_like: str | Path, data_dir: Path) -> Path:
    candidate = Path(path_like)
    if candidate.is_absolute():
        return candidate

    text = str(path_like)
    if "/" in text or "\\" in text:
        return candidate

    return data_dir / candidate


def _resolve_sim_feed(symbol_config: Dict[str, Any], feed_config: Dict[str, Any], data_dir: Path) -> Path:
    candidate = symbol_config.get("sim_feed_file") or feed_config.get("sim_feed_file")
    if candidate is None:
        candidate = data_dir / "sim-feed.json"
    return _normalize_sim_path(candidate, data_dir)


class BasePriceFeed(ABC):
    """Minimal price feed contract."""

    def __init__(self, symbol: str, source: str) -> None:
        self.symbol = symbol
        self.source = source

    @abstractmethod
    def next_tick(self) -> Dict[str, Any]:
        """Return the next normalized tick."""


class SimPriceFeed(BasePriceFeed):
    """Simulation feed for offline/backtest mode."""

    def __init__(self, symbol: str, sim_file: Path, loop: bool = False) -> None:
        super().__init__(symbol, source="sim")
        if not sim_file.exists():
            raise FileNotFoundError(f"Simulation feed missing at {sim_file}")

        with sim_file.open("r", encoding="utf-8") as fh:
            self.sim_ticks: List[Dict[str, Any]] = json.load(fh)

        if not self.sim_ticks:
            raise ValueError("Simulation feed contains no ticks")

        self.index = 0
        self.loop = loop

    def next_tick(self) -> Dict[str, Any]:
        if self.index >= len(self.sim_ticks):
            if not self.loop:
                raise StopIteration("Simulation feed exhausted")
            self.index = 0

        raw_tick = self.sim_ticks[self.index]
        self.index += 1
        timestamp = raw_tick.get("timestamp")
        if timestamp:
            tick_time = timestamp
        else:
            tick_time = datetime.now(timezone.utc).isoformat()

        return {
            "symbol": self.symbol,
            "price": float(raw_tick.get("price", 0.0)),
            "timestamp": tick_time,
            "source": self.source,
        }


class RobinhoodPriceFeed(BasePriceFeed):
    """Price feed backed by Robinhood crypto quotes."""

    BASE_URL = "https://trading.robinhood.com"
    PATH = "/api/v1/crypto/marketdata/best_bid_ask/"

    def __init__(
        self,
        symbol_config: Dict[str, Any],
        feed_config: Dict[str, Any],
        secrets: Dict[str, str],
    ) -> None:
        symbol = symbol_config.get("name", "UNKNOWN")
        super().__init__(symbol=symbol, source="robinhood")

        self.poll_interval = float(feed_config.get("poll_interval_seconds", 5))
        self.max_tick_age_seconds = float(feed_config.get("max_tick_age_seconds", 30))
        self.retry_backoff_seconds = float(feed_config.get("retry_backoff_seconds", 5))
        self.timeout_seconds = float(feed_config.get("request_timeout_seconds", 5))

        self.query_symbols = self._build_query_symbols(symbol_config)
        if not self.query_symbols:
            raise FeedFatalError("Symbol name cannot be empty for Robinhood feed")

        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})

        self.api_key = secrets.get("ROBINHOOD_API_KEY")
        private_key = secrets.get("ROBINHOOD_PRIVATE_KEY")
        self.public_key = secrets.get("ROBINHOOD_PUBLIC_KEY")

        if not self.api_key:
            raise FeedFatalError("Missing ROBINHOOD_API_KEY for Robinhood data feed")
        if not private_key:
            raise FeedFatalError("Missing ROBINHOOD_PRIVATE_KEY for Robinhood data feed")
        if not self.public_key:
            raise FeedFatalError("Missing ROBINHOOD_PUBLIC_KEY for Robinhood data feed")

        try:
            private_bytes = base64.b64decode(private_key.strip())
        except (binascii.Error, ValueError) as exc:
            raise FeedFatalError("ROBINHOOD_PRIVATE_KEY must be base64 encoded") from exc

        seed = private_bytes[:32]
        try:
            self.signing_key = SigningKey(seed)
        except Exception as exc:
            raise FeedFatalError("Unable to initialize Robinhood signing key") from exc

        self.path_with_query = self._build_path_with_query()

    def _build_query_symbols(self, symbol_config: Dict[str, Any]) -> List[str]:
        primary = symbol_config.get("name")
        extras = symbol_config.get("additional_symbols") or symbol_config.get("extra_symbols") or []
        symbols = [primary] if primary else []
        for extra in extras:
            if extra:
                symbols.append(extra)
        return symbols

    def _build_path_with_query(self) -> str:
        encoded_parts = []
        for symbol in self.query_symbols:
            clean = symbol.strip()
            if not clean:
                continue
            encoded = quote(clean, safe="")
            encoded_parts.append(f"symbol={encoded}")
        if not encoded_parts:
            raise FeedFatalError("No valid symbols configured for Robinhood feed")
        query = "&".join(encoded_parts)
        return f"{self.PATH}?{query}"

    def _sign_request(self, method: str, url_path: str, timestamp: str) -> str:
        if not hasattr(self, "signing_key"):
            raise FeedFatalError("Signing key unavailable for Robinhood feed")
        body = ""
        message = f"{self.api_key}{timestamp}{url_path}{method.upper()}{body}".encode("utf-8")
        try:
            signed = self.signing_key.sign(message)
        except Exception as exc:
            raise FeedFatalError("Robinhood request signing failed") from exc
        return base64.b64encode(signed.signature).decode("utf-8")

    def next_tick(self) -> Dict[str, Any]:
        while True:
            try:
                return self._fetch_tick()
            except FeedRetryableError as exc:
                print(
                    f"[feed][{self.symbol}] transient error: {exc}. retrying in {self.retry_backoff_seconds}s"
                )
                time.sleep(self.retry_backoff_seconds)
            except FeedFatalError:
                raise

    def _fetch_tick(self) -> Dict[str, Any]:
        url = f"{self.BASE_URL}{self.path_with_query}"
        response = self.session.get(
            url,
            headers=self._build_auth_headers("GET"),
            timeout=self.timeout_seconds,
        )

        if response.status_code == 401:
            raise FeedFatalError(
                "Robinhood authentication failed (401). Check API key, signing, and path/query."
            )
        if response.status_code == 404:
            raise FeedFatalError(
                "Robinhood endpoint not found (404). Verify host, path, and repeated symbol= parameters."
            )
        if response.status_code == 429:
            raise FeedRetryableError("Robinhood rate limit hit")
        if response.status_code >= 500:
            raise FeedRetryableError(f"Robinhood server error {response.status_code}")
        if response.status_code != 200:
            raise FeedRetryableError(f"Unexpected Robinhood status {response.status_code}")

        try:
            payload = response.json()
        except ValueError as exc:
            raise FeedRetryableError(f"Malformed JSON from Robinhood: {exc}")

        results = payload.get("results") or []
        if not results:
            raise FeedRetryableError("Robinhood returned no quotes")

        quote = results[0]
        price = self._extract_price(quote)
        if price is None:
            raise FeedRetryableError("Robinhood quote missing price")

        timestamp = self._extract_timestamp(
            quote.get("timestamp") or quote.get("updated_at") or quote.get("created_at")
        )
        now = datetime.now(timezone.utc)
        if timestamp is None:
            timestamp = now

        age = (now - timestamp).total_seconds()
        if self.max_tick_age_seconds and age > self.max_tick_age_seconds:
            raise FeedRetryableError(f"Robinhood tick too old ({int(age)}s ago)")

        return {
            "symbol": self.symbol,
            "price": price,
            "timestamp": timestamp.isoformat(),
            "source": self.source,
        }

    def _build_auth_headers(self, method: str) -> Dict[str, str]:
        timestamp = str(int(time.time()))
        signature = self._sign_request(method, self.path_with_query, timestamp)

        headers = {
            "Accept": "application/json",
            "x-api-key": self.api_key,
            "x-timestamp": timestamp,
            "x-signature": signature,
        }
        return headers

    @staticmethod
    def _extract_price(quote: Dict[str, Any]) -> Optional[float]:
        def _safe_cast(key: str) -> Optional[float]:
            raw_value = quote.get(key)
            if raw_value is None:
                return None
            try:
                return float(raw_value)
            except (TypeError, ValueError):
                return None

        priority = ["price", "mid_price"]
        for candidate in priority:
            value = _safe_cast(candidate)
            if value is not None and value > 0:
                return value

        bid = _safe_cast("bid_inclusive_of_sell_spread")
        ask = _safe_cast("ask_inclusive_of_buy_spread")
        if bid is not None and ask is not None and bid > 0 and ask > 0:
            return (bid + ask) / 2

        bid = _safe_cast("bid_price")
        ask = _safe_cast("ask_price")
        if bid is not None and ask is not None and bid > 0 and ask > 0:
            return (bid + ask) / 2

        return None

    @staticmethod
    def _extract_timestamp(raw: Optional[str]) -> Optional[datetime]:
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed


def build_price_feed(
    symbol_config: Dict[str, Any],
    feed_config: Dict[str, Any],
    data_dir: Path,
    loop_feed: bool,
    secrets: Dict[str, str],
) -> BasePriceFeed:
    mode = (feed_config or {}).get("mode", "sim")

    if mode == "sim":
        sim_file = _resolve_sim_feed(symbol_config, feed_config, data_dir)
        return SimPriceFeed(
            symbol_config.get("name", "CRYPTO"),
            sim_file,
            loop=loop_feed or feed_config.get("loop_sim_feed", False),
        )

    if mode == "robinhood":
        return RobinhoodPriceFeed(symbol_config, feed_config, secrets)

    raise ValueError(f"Unsupported feed mode: {mode}")
