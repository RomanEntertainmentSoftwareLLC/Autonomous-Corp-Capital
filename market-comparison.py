"""
binance_robinhood_compare.py

Single-file sandbox app:
- Reads BTC price from Binance public API
- Reads BTC price from Robinhood Crypto API
- Compares prices
- Logs timestamps in nanoseconds
- Runs a fake paper-trader loop
- Uses Robinhood price as the simulated execution price
- Uses Binance as the "lead" reference

IMPORTANT:
- This is a sandbox / paper-trading prototype
- No live orders are placed
- Replace placeholder values with your actual credentials or env vars
"""

from __future__ import annotations

import os
import time
import json
import nacl.signing
import base64
import hashlib
import logging
from dataclasses import dataclass, asdict
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Dict, Any

import requests

from tradebot.secrets import load_secrets

# =========================
# CONFIG
# =========================
FORCE_BUY_ON_START = True

BINANCE_SYMBOL = "BTCUSDT"

# Robinhood symbol guess for crypto market data
# Adjust if their API expects a different format.
ROBINHOOD_SYMBOL = "BTC-USD"

POLL_SECONDS = 1.0
RUN_FOREVER = True

# Signal thresholds
GAP_BPS_BUY = 2.0 #10.0   # 10 bps = 0.10%
GAP_BPS_SELL = -5.0 #-10.0
PERSISTENCE_TICKS = 2 #3
COOLDOWN_TICKS = 5

# Paper trading
STARTING_CASH = 10.0
TRADE_FRACTION = 1.0   # 1.0 = all-in for sandbox
STOP_LOSS_PCT = 0.003  # 0.3%
TAKE_PROFIT_PCT = 0.003  # 0.3%
MAX_HOLD_TICKS = 30

# Logging
LOG_FILE = "market_compare_paper_log.jsonl"


# =========================
# PLACEHOLDER CREDS
# =========================

# Prefer .env values first, then environment, then the fallback placeholders.
ROBINHOOD_API_KEY = os.getenv("ROBINHOOD_API_KEY") 
ROBINHOOD_PRIVATE_KEY = os.getenv("ROBINHOOD_PRIVATE_KEY")
ROBINHOOD_PUBLIC_KEY = os.getenv("ROBINHOOD_PUBLIC_KEY")


# =========================
# LOGGING
# =========================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)


# =========================
# DATA STRUCTURES
# =========================

@dataclass
class MarketTick:
    source: str
    symbol: str
    price: float
    bid: Optional[float]
    ask: Optional[float]
    mid: Optional[float]
    ts_source_ms: Optional[int]
    ts_local_ns: int
    ts_local_ms: int
    raw: Dict[str, Any]


@dataclass
class Position:
    side: str  # only "long" in this MVP
    qty: float
    entry_price: float
    entry_tick_index: int


@dataclass
class PaperState:
    cash: float
    position: Optional[Position]
    realized_pnl: float
    tick_index: int
    cooldown_remaining: int


# =========================
# UTILS
# =========================

def now_ns() -> int:
    return time.time_ns()


def ns_to_ms(ns: int) -> int:
    return ns // 1_000_000


def safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def calc_mid(bid: Optional[float], ask: Optional[float], fallback: Optional[float]) -> Optional[float]:
    if bid is not None and ask is not None:
        return (bid + ask) / 2.0
    return fallback


def bps_diff(reference_price: float, compare_price: float) -> float:
    """
    Returns basis points difference of compare_price relative to reference_price.
    Positive means compare_price > reference_price.
    """
    if reference_price <= 0:
        return 0.0
    return ((compare_price - reference_price) / reference_price) * 10_000.0


def write_jsonl(record: Dict[str, Any], filepath: str = LOG_FILE) -> None:
    with open(filepath, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


# =========================
# BINANCE PUBLIC PRICE
# =========================

def fetch_binance_tick(session: requests.Session) -> MarketTick:
    # Public ticker price endpoint
    url = "https://data-api.binance.vision/api/v3/ticker/bookTicker"
    params = {"symbol": BINANCE_SYMBOL}

    ts_local_ns = now_ns()
    resp = session.get(url, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    bid = safe_float(data.get("bidPrice"))
    ask = safe_float(data.get("askPrice"))
    mid = calc_mid(bid, ask, None)

    return MarketTick(
        source="binance",
        symbol=BINANCE_SYMBOL,
        price=mid if mid is not None else (bid or ask or 0.0),
        bid=bid,
        ask=ask,
        mid=mid,
        ts_source_ms=None,  # not provided by this endpoint
        ts_local_ns=ts_local_ns,
        ts_local_ms=ns_to_ms(ts_local_ns),
        raw=data,
    )


# =========================
# ROBINHOOD HELPERS
# =========================

def build_robinhood_headers(method: str, path: str, body: str = "") -> dict[str, str]:
    timestamp = str(int(time.time()))
    message = f"{ROBINHOOD_API_KEY}{timestamp}{path}{method.upper()}{body}".encode("utf-8")

    private_key_bytes = base64.b64decode(ROBINHOOD_PRIVATE_KEY)
    signing_key = nacl.signing.SigningKey(private_key_bytes[:32])
    signature = signing_key.sign(message).signature
    signature_b64 = base64.b64encode(signature).decode("utf-8")

    return {
        "x-api-key": ROBINHOOD_API_KEY,
        "x-timestamp": timestamp,
        "x-signature": signature_b64,
        "Content-Type": "application/json",
    }


def fetch_robinhood_tick(session: requests.Session) -> MarketTick:
    path = f"/api/v1/crypto/marketdata/best_bid_ask/?symbol={ROBINHOOD_SYMBOL}"
    url = f"https://trading.robinhood.com{path}"

    headers = build_robinhood_headers("GET", path, "")
    ts_local_ns = now_ns()

    resp = session.get(url, headers=headers, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    result = {}
    if isinstance(data.get("results"), list) and data["results"]:
        result = data["results"][0]

    bid = safe_float(
        result.get("bid_inclusive_of_sell_spread")
        or data.get("bid_inclusive_of_sell_spread")
        or data.get("bid")
        or data.get("best_bid")
    )
    ask = safe_float(
        result.get("ask_inclusive_of_buy_spread")
        or data.get("ask_inclusive_of_buy_spread")
        or data.get("ask")
        or data.get("best_ask")
    )
    last = safe_float(
        result.get("price")
        or data.get("price")
        or data.get("mark_price")
        or data.get("last_trade_price")
    )

    ts_source_ms = None
    source_ts = result.get("timestamp") or data.get("timestamp")

    mid = calc_mid(bid, ask, last)
    price = mid if mid is not None else (last or bid or ask or 0.0)

    return MarketTick(
        source="robinhood",
        symbol=result.get("symbol", ROBINHOOD_SYMBOL),
        price=price,
        bid=bid,
        ask=ask,
        mid=mid,
        ts_source_ms=ts_source_ms,
        ts_local_ns=ts_local_ns,
        ts_local_ms=ns_to_ms(ts_local_ns),
        raw=data,
    )


# =========================
# SIGNAL ENGINE
# =========================

class SignalEngine:
    def __init__(self, persistence_ticks: int) -> None:
        self.persistence_ticks = persistence_ticks
        self.up_count = 0
        self.down_count = 0

    def update(self, robinhood_price: float, binance_price: float) -> Dict[str, Any]:
        gap_dollars = binance_price - robinhood_price
        gap_bps = bps_diff(robinhood_price, binance_price)

        if gap_bps >= GAP_BPS_BUY:
            self.up_count += 1
            self.down_count = 0
        elif gap_bps <= GAP_BPS_SELL:
            self.down_count += 1
            self.up_count = 0
        else:
            self.up_count = 0
            self.down_count = 0

        signal = "wait"
        confidence = 0.0

        if self.up_count >= self.persistence_ticks:
            signal = "buy"
            confidence = min(1.0, abs(gap_bps) / 50.0)
        elif self.down_count >= self.persistence_ticks:
            signal = "sell"
            confidence = min(1.0, abs(gap_bps) / 50.0)

        return {
            "signal": signal,
            "confidence": confidence,
            "gap_dollars": gap_dollars,
            "gap_bps": gap_bps,
            "up_count": self.up_count,
            "down_count": self.down_count,
        }


# =========================
# PAPER BROKER
# =========================

class PaperBroker:
    def __init__(self) -> None:
        self.state = PaperState(
            cash=STARTING_CASH,
            position=None,
            realized_pnl=0.0,
            tick_index=0,
            cooldown_remaining=0,
        )

    def resolve_action(self, market_signal: str) -> str:
        """
        Convert market opinion into portfolio action using the user's preferred words:
        - flat account: buy or wait
        - holding coin: hold or sell
        """
        has_position = self.state.position is not None

        if has_position:
            if market_signal == "sell":
                return "sell"
            return "hold"

        if market_signal == "buy":
            return "buy"
        return "wait"

    def mark_to_market(self, robinhood_price: float) -> Dict[str, Any]:
        unrealized = 0.0
        equity = self.state.cash
        if self.state.position is not None:
            unrealized = (robinhood_price - self.state.position.entry_price) * self.state.position.qty
            equity += self.state.position.qty * robinhood_price
        return {
            "cash": self.state.cash,
            "unrealized_pnl": unrealized,
            "realized_pnl": self.state.realized_pnl,
            "equity": equity,
        }

    def maybe_open_long(self, robinhood_price: float, action: str) -> Optional[Dict[str, Any]]:
        if action != "buy":
            return None
        if self.state.position is not None:
            return None
        if self.state.cooldown_remaining > 0:
            return None
        if self.state.cash <= 0:
            return None

        spend = self.state.cash * TRADE_FRACTION
        qty = spend / robinhood_price
        self.state.cash -= spend
        self.state.position = Position(
            side="long",
            qty=qty,
            entry_price=robinhood_price,
            entry_tick_index=self.state.tick_index,
        )

        return {
            "action": "open_long",
            "qty": qty,
            "entry_price": robinhood_price,
            "spent": spend,
        }

    def maybe_close_long(self, robinhood_price: float, action: str) -> Optional[Dict[str, Any]]:
        pos = self.state.position
        if pos is None:
            return None

        pnl_pct = (robinhood_price - pos.entry_price) / pos.entry_price
        held_ticks = self.state.tick_index - pos.entry_tick_index

        close_reason = None
        if pnl_pct <= -STOP_LOSS_PCT:
            close_reason = "stop_loss"
        elif pnl_pct >= TAKE_PROFIT_PCT:
            close_reason = "take_profit"
        elif action == "sell":
            close_reason = "signal_sell"
        elif held_ticks >= MAX_HOLD_TICKS:
            close_reason = "max_hold"

        if close_reason is None:
            return None

        proceeds = pos.qty * robinhood_price
        pnl = proceeds - (pos.qty * pos.entry_price)
        self.state.cash += proceeds
        self.state.realized_pnl += pnl
        self.state.position = None
        self.state.cooldown_remaining = COOLDOWN_TICKS

        return {
            "action": "close_long",
            "qty": pos.qty,
            "exit_price": robinhood_price,
            "pnl": pnl,
            "reason": close_reason,
        }

    def tick(self) -> None:
        self.state.tick_index += 1
        if self.state.cooldown_remaining > 0:
            self.state.cooldown_remaining -= 1




def fetch_both_ticks(
    executor: ThreadPoolExecutor,
    binance_session: requests.Session,
    robinhood_session: requests.Session,
) -> tuple[MarketTick, MarketTick]:
    """
    Fetch Binance and Robinhood in parallel so our collector induces less fake lag.
    """
    future_binance = executor.submit(fetch_binance_tick, binance_session)
    future_robinhood = executor.submit(fetch_robinhood_tick, robinhood_session)
    return future_binance.result(), future_robinhood.result()


# =========================
# MAIN LOOP
# =========================

def main() -> None:
    session = requests.Session()
    signal_engine = SignalEngine(persistence_ticks=PERSISTENCE_TICKS)
    broker = PaperBroker()

    print("Starting Binance vs Robinhood comparison sandbox...")
    print(f"Starting cash: ${STARTING_CASH:.2f}")
    print("Logging to:", LOG_FILE)

    try:
        while True:
            loop_ts_ns = now_ns()

            try:
                with ThreadPoolExecutor(max_workers=2) as executor:
                    binance_tick, robinhood_tick = fetch_both_ticks(
                        executor,
                        session,
                        session,
                    )
            except Exception as e:
                logging.error("Parallel market fetch failed: %s", e)
                time.sleep(POLL_SECONDS)
                continue

            signal_info = signal_engine.update(
                robinhood_price=robinhood_tick.price,
                binance_price=binance_tick.price,
            )

            market_signal = signal_info["signal"]
            action = broker.resolve_action(market_signal)
            if FORCE_BUY_ON_START and broker.state.position is None and broker.state.tick_index == 0:
                action="buy"
            close_event = broker.maybe_close_long(
                robinhood_price=robinhood_tick.price,
                action=action,
            )
            open_event = broker.maybe_open_long(
                robinhood_price=robinhood_tick.price,
                action=action,
            )
            
            display_action = action
            
            if close_event is not None:
                 display_action = "sell"
            elif open_event is not None:
                 display_action = "buy"
            elif broker.state.position is not None:
                 display_action = "hold"
            else:
                display_action = "wait"
                
            mtm = broker.mark_to_market(robinhood_tick.price)

            record = {
                "loop_ts_ns": loop_ts_ns,
                "loop_ts_ms": ns_to_ms(loop_ts_ns),
                "binance": asdict(binance_tick),
                "robinhood": asdict(robinhood_tick),
                "market_signal": signal_info,
                "action": display_action,
                "paper_state": {
                    "tick_index": broker.state.tick_index,
                    "cooldown_remaining": broker.state.cooldown_remaining,
                    "position": asdict(broker.state.position) if broker.state.position else None,
                    **mtm,
                },
                "events": {
                    "open": open_event,
                    "close": close_event,
                },
            }

            write_jsonl(record)

            logging.info(
                "RH=%0.2f BIN=%0.2f gap=$%0.2f (%0.2f bps) action=%s equity=%0.4f",
                robinhood_tick.price,
                binance_tick.price,
                signal_info["gap_dollars"],
                signal_info["gap_bps"],
                display_action,
                mtm["equity"],
            )

            broker.tick()
            time.sleep(POLL_SECONDS)

    except KeyboardInterrupt:
        print("\nStopping market comparison sandbox...")

    finally:
        session.close()
        print("Session closed. Bye.")


if __name__ == "__main__":
    main()