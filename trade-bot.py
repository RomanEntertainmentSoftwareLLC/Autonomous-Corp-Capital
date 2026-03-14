"""Entry point for trading experiment prototype."""

import argparse
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from tradebot.config import load_config
from tradebot.execution import ExecutionEngine
from tradebot.feed import build_price_feed
from tradebot.features import FeatureLogger
from tradebot.logger import TradeLogger
from tradebot.portfolio import Portfolio
from tradebot.risk import RiskManager
from tradebot.secrets import load_secrets
from tradebot.strategies.base import StrategyProtocol
from tradebot.strategies.factory import build_strategy, resolve_strategy_name


@dataclass
class SymbolRunner:
    symbol_config: Dict[str, Any]
    feed: Any
    strategy: StrategyProtocol
    strategy_name: str
    risk_manager: RiskManager
    execution_engine: ExecutionEngine
    summary_ticks: int = 0
    finished: bool = False


def resolve_config_path(company: str, explicit_config: Optional[str]) -> Path:
    if explicit_config:
        return Path(explicit_config)
    return Path("companies") / company / "config.yaml"


def normalize_mode(mode: str) -> str:
    mode = (mode or "").strip().lower()
    valid = {"backtest", "paper", "live"}
    if mode not in valid:
        raise ValueError(f"Invalid mode '{mode}'. Valid modes: backtest, paper, live")
    return mode


def run(
    company: str = "company_001",
    config_path: Optional[str] = None,
    mode_override: Optional[str] = None,
    interval_override: Optional[float] = None,
    iterations: int = 20,
    loop_feed: bool = False,
    run_forever: bool = False,
    confirm_live: bool = False,
) -> None:
    resolved_config_path = resolve_config_path(company, config_path)
    config = load_config(resolved_config_path)

    feed_config = config.get("feed", {}) or {}
    execution_config = config.get("execution", {}) or {}
    reporting_config = config.get("reporting", {}) or {}

    configured_mode = execution_config.get("mode", "paper")
    mode = normalize_mode(mode_override or configured_mode)

    live_enabled = bool(config.get("live_trading_enabled", False))
    if mode == "live" and not live_enabled:
        raise ValueError(
            "Live mode is disabled in the config (live_trading_enabled: false). "
            "Set live_trading_enabled: true and pass --confirm-live if you really mean to run live."
        )

    if mode == "live" and not confirm_live:
        raise ValueError(
            "Refusing live mode without --confirm-live. "
            "Use: --mode live --confirm-live"
        )

    # Safety gate: live mode is intentionally blocked until real execution is implemented.
    if mode == "live":
        raise ValueError(
            "Live mode CLI is wired, but real broker execution is not implemented yet. "
            "Stay on --mode paper or --mode backtest for now."
        )

    summary_interval = int(reporting_config.get("summary_interval_ticks", 30))

    secrets = load_secrets()
    if (
        secrets.get("ROBINHOOD_API_KEY")
        and secrets.get("ROBINHOOD_PRIVATE_KEY")
        and secrets.get("ROBINHOOD_PUBLIC_KEY")
    ):
        print("Robinhood API credentials read from .env.")

    symbols = config.get("symbols", [])
    if not symbols:
        raise ValueError("Configuration must provide at least one symbol")

    base_dir = Path(__file__).resolve().parent
    data_dir = Path(config.get("data_dir", base_dir / "tradebot" / "data"))
    results_dir = Path(config.get("results_dir", base_dir / "results")) / company / mode

    if mode == "backtest":
        feed_config = {**feed_config, "mode": "sim"}

    poll_interval = float(
        feed_config.get("poll_interval_seconds", config.get("timing", {}).get("loop_interval_seconds", 5))
    )
    default_interval = 0.01 if mode == "backtest" else poll_interval
    loop_interval = (
        interval_override
        if interval_override is not None
        else default_interval
    )
    if loop_interval <= 0:
        raise ValueError("Loop interval must be greater than zero")

    max_iterations = None if run_forever else (iterations if iterations >= 0 else None)

    logger = TradeLogger(results_dir)
    runners: list[SymbolRunner] = []
    for symbol_config in symbols:
        portfolio = Portfolio(cash=symbol_config.get("starting_balance", 100.0))
        strategy_name = resolve_strategy_name(symbol_config)
        runners.append(
            SymbolRunner(
                symbol_config=symbol_config,
                feed=build_price_feed(
                    symbol_config,
                    feed_config,
                    data_dir,
                    loop_feed or feed_config.get("loop_sim_feed", False),
                    secrets,
                ),
                strategy=build_strategy(symbol_config),
                strategy_name=strategy_name,
                risk_manager=RiskManager(symbol_config, config.get("risk", {}) or {}, portfolio),
                execution_engine=ExecutionEngine(portfolio),
            )
        )
    feature_logger = FeatureLogger(results_dir)

    structured_console = config.get("logging", {}).get("structured_console", True)

    iteration = 0
    active_runners = len(runners)
    symbol_names = [
        f"{runner.symbol_config.get('name')} ({runner.strategy_name})"
        for runner in runners
    ]
    print(
        f"Starting trade-bot | company={company} | mode={mode} | "
        f"feed={feed_config.get('mode', 'sim')} | symbols={symbol_names}"
    )

    governor_path = Path("state/risk_governor.json")

    def is_governor_halted() -> Optional[str]:
        if not governor_path.exists():
            return None
        try:
            data = json.loads(governor_path.read_text())
        except json.JSONDecodeError:
            return None
        if data.get("status") == "HALTED":
            return data.get("halt_reason") or "governor triggered HALT"
        return None

    while True:
        halt_reason = is_governor_halted()
        if halt_reason:
            print("SYSTEM HALT:", halt_reason)
            print("Stopping active run to respect the risk governor.")
            break
        if max_iterations is not None and iteration >= max_iterations:
            print("Reached configured iteration limit; shutting down.")
            break

        if active_runners == 0:
            print("All symbol feeds exhausted; shutting down.")
            break

        loop_broken = False
        for runner in runners:
            if runner.finished:
                continue

            try:
                tick = runner.feed.next_tick()
            except StopIteration:
                print(f"Simulation feed exhausted for {runner.symbol_config.get('name')}")
                runner.finished = True
                active_runners -= 1
                continue

            signal = runner.strategy.update(tick["price"])
            risk_decision = runner.risk_manager.evaluate_signal(signal.__dict__, tick)
            decision = runner.execution_engine.apply(risk_decision, tick)

            logger.log_signal(tick, signal.__dict__, decision.__dict__)
            logger.log_trade(tick, signal.__dict__, decision.__dict__)

            structured = logger.build_structured_line(tick, signal.__dict__, decision.__dict__)
            structured["company"] = company
            structured["mode"] = mode
            structured["strategy"] = runner.strategy_name

            if structured_console:
                print(json.dumps(structured, default=str))
            else:
                print(
                    f"[{tick['timestamp']}] {company} {mode} {tick['source']} {tick['symbol']} "
                    f"{signal.direction} -> {decision.action} | "
                    f"price={tick['price']:.2f} cash={decision.cash_after:.2f} "
                    f"position={decision.position_after:.4f} unrealized={decision.unrealized_pnl:.2f}"
                )

            feature_logger.record_tick(tick, signal, decision, runner.strategy)

            runner.summary_ticks += 1
            if summary_interval > 0 and runner.summary_ticks >= summary_interval:
                summary = runner.execution_engine.portfolio_snapshot(tick["price"])
                summary_payload = {
                    "type": "portfolio_summary",
                    "timestamp": tick["timestamp"],
                    "company": company,
                    "mode": mode,
                    "symbol": tick["symbol"],
                    "source": tick["source"],
                    "iteration": iteration + 1,
                    **summary,
                }
                print(json.dumps(summary_payload, default=str))
                runner.summary_ticks = 0

            iteration += 1
            if max_iterations is not None and iteration >= max_iterations:
                print("Reached configured iteration limit; shutting down.")
                loop_broken = True
                break

        if loop_broken:
            break

        time.sleep(loop_interval)


def main() -> None:
    parser = argparse.ArgumentParser(description="Simple trade-bot prototype")
    parser.add_argument("--company", default="company_001", help="Company folder name under companies/")
    parser.add_argument("--config", help="Path to config YAML (overrides --company default)", default=None)
    parser.add_argument(
        "--mode",
        choices=["backtest", "paper", "live"],
        default=None,
        help="Runtime mode override",
    )
    parser.add_argument("--confirm-live", action="store_true", help="Required safety switch for live mode")
    parser.add_argument("--interval", type=float, help="Loop interval in seconds")
    parser.add_argument("--iterations", type=int, default=20, help="How many ticks to process (-1 = infinite)")
    parser.add_argument("--loop-feed", action="store_true", help="Restart the feed when it ends")
    parser.add_argument("--run-forever", action="store_true", help="Override iterations and run until manual stop")
    args = parser.parse_args()

    run(
        company=args.company,
        config_path=args.config,
        mode_override=args.mode,
        interval_override=args.interval,
        iterations=args.iterations,
        loop_feed=args.loop_feed,
        run_forever=args.run_forever,
        confirm_live=args.confirm_live,
    )


if __name__ == "__main__":
    main()