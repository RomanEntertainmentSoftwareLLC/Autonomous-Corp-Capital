"""Logging helpers for the trading prototype."""

import json
from pathlib import Path
from typing import Any, Dict


class TradeLogger:
    def __init__(self, results_dir: Path) -> None:
        self.results_dir = results_dir
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.signal_log = self.results_dir / "signal-log.jsonl"
        self.trade_log = self.results_dir / "trade-log.jsonl"

    def _append(self, path: Path, payload: Dict[str, Any]) -> None:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload) + "\n")

    @staticmethod
    def _base_entry(tick: Dict[str, Any], signal: Dict[str, Any], decision: Dict[str, Any]) -> Dict[str, Any]:
        allowed = bool(decision.get("allowed", False))
        block_reason = decision.get("block_reason", "Signal blocked or not yet executed")
        return {
            "timestamp": tick["timestamp"],
            "symbol": tick["symbol"],
            "price": tick["price"],
            "source": tick.get("source", "unknown"),
            "signal": signal.get("direction"),
            "reason": signal.get("reason", ""),
            "allowed_blocked": allowed,
            "allowed": allowed,
            "block_reason": block_reason,
            "cash_before": decision.get("cash_before"),
            "cash_after": decision.get("cash_after"),
            "position_before": decision.get("position_before"),
            "position_after": decision.get("position_after"),
            "unrealized_pnl": decision.get("unrealized_pnl"),
            "strategy": decision.get("strategy_name"),
            "account_value": decision.get("account_value"),
            "realized_pnl_total": decision.get("realized_pnl_total"),
            "max_drawdown_percent": decision.get("max_drawdown_percent"),
            "trade_units": decision.get("trade_units"),
            "win_rate_percent": decision.get("win_rate_percent"),
        }

    def log_signal(self, tick: Dict[str, Any], signal: Dict[str, Any], decision: Dict[str, Any]) -> None:
        payload = self._base_entry(tick, signal, decision)
        self._append(self.signal_log, payload)

    def _structured_entry(self, tick: Dict[str, Any], signal: Dict[str, Any], decision: Dict[str, Any]) -> Dict[str, Any]:
        payload = self._base_entry(tick, signal, decision)
        payload.update(
            {
                "executed": decision.get("executed", False),
                "pnl": decision.get("pnl"),
                "trade_count": decision.get("trade_count", 0),
                "source": tick.get("source", "unknown"),
            }
        )
        return payload

    def log_trade(self, tick: Dict[str, Any], signal: Dict[str, Any], decision: Dict[str, Any]) -> None:
        payload = self._structured_entry(tick, signal, decision)
        self._append(self.trade_log, payload)

    def build_structured_line(self, tick: Dict[str, Any], signal: Dict[str, Any], decision: Dict[str, Any]) -> Dict[str, Any]:
        return self._structured_entry(tick, signal, decision)
