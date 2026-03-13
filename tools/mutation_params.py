"""Shared parameter bounds for mutation & validation."""

from typing import Dict, Tuple

SAFE_SYMBOL_PARAMS: Dict[str, Tuple[float, float]] = {
    "ema_fast": (3, 30),
    "ema_slow": (10, 60),
    "rsi_period": (5, 30),
    "rsi_buy": (10, 50),
    "rsi_sell": (60, 90),
    "order_size": (0.1, 10.0),
}

SAFE_RISK_PARAMS: Dict[str, Tuple[float, float]] = {
    "max_position_size": (0.1, 1.0),
    "max_daily_trades": (1, 50),
    "cooldown_seconds": (10, 600),
}
