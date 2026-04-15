from __future__ import annotations

from tools.live_paper_portfolio import PortfolioState


def decision(company: str, symbol: str, side: str, price: float, cycle: int = 1, confidence: float = 0.8) -> dict[str, object]:
    return {
        "timestamp": "2026-04-15T01:00:00+00:00",
        "company_id": company,
        "symbol": symbol,
        "decision": side,
        "price": price,
        "confidence": confidence,
        "size_multiplier": 1.0,
        "policy_name": "balanced_baseline",
        "company_posture": "balanced baseline",
        "sizing_rationale": "test",
        "cycle": cycle,
        "held_ticks": 0,
        "pnl_pct": 0.0,
        "forced_exit_reason": None,
    }


def test_sell_realizes_against_entry_price(tmp_path):
    portfolio = PortfolioState(tmp_path, parent_total=250.0, companies=["company_001"])
    buy = decision("company_001", "BTC-USD", "BUY", 100.0, cycle=1, confidence=0.5)
    portfolio.apply_decision(buy)
    qty = portfolio.positions["company_001"]["BTC-USD"]

    sell = decision("company_001", "BTC-USD", "SELL", 110.0, cycle=2, confidence=0.5)
    portfolio.apply_decision(sell)

    assert portfolio.positions["company_001"].get("BTC-USD", 0.0) == 0.0
    assert portfolio.realized["company_001"] == qty * 10.0


def test_position_snapshot_exposes_entry_and_held_ticks(tmp_path):
    portfolio = PortfolioState(tmp_path, parent_total=250.0, companies=["company_001"])
    buy = decision("company_001", "ETH-USD", "BUY", 50.0, cycle=3, confidence=0.5)
    portfolio.apply_decision(buy)
    portfolio.mark_price("company_001", "ETH-USD", 55.0)

    snap = portfolio.get_position_snapshot("company_001", "ETH-USD")

    assert snap["entry_price"] == 50.0
    assert snap["held_ticks"] >= 0
    assert snap["unrealized_pnl"] > 0.0
