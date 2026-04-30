import json
from pathlib import Path

from tools.v3a_trace_field_audit import build_trace_field_audit, render_text_report


def write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def complete_row(symbol="BTC-USD", decision="WAIT"):
    row = {
        "company_id": "company_001",
        "symbol": symbol,
        "decision": decision,
        "v3a_market_regime": "sideways_chop",
        "v3a_risk_posture": "wait",
        "v3a_best_posture": "wait_for_confirmation",
        "v3a_market_weather": {"market_regime": "sideways_chop"},
        "v3a_universe_rank": 1,
        "v3a_universe_rank_score": 0.25,
        "v3a_rank_reasons": ["policy=0.010000"],
    }
    if decision == "WAIT":
        row["wait_reason"] = "WAIT_NEEDS_CONFIRMATION"
        row["wait_reason_detail"] = "wait_needs_confirmation"
    return row


def test_trace_field_audit_passes_when_v3a_fields_are_present(tmp_path):
    root = tmp_path
    run_dir = root / "state" / "live_runs" / "run_001"
    (root / "state" / "live_runs").mkdir(parents=True)
    (root / "state" / "live_runs" / "current_run.json").write_text(
        json.dumps({"run_id": "run_001"}),
        encoding="utf-8",
    )
    write_jsonl(run_dir / "artifacts" / "candidate_decisions.jsonl", [
        complete_row("BTC-USD", "WAIT"),
        complete_row("ETH-USD", "BUY"),
    ])

    payload = build_trace_field_audit(root, "latest")

    assert payload["status"] == "PASS"
    assert payload["candidate_rows"] == 2
    assert payload["missing_v3a_field_counts"] == {}
    assert payload["wait_rows_missing_wait_reason"] == 0


def test_trace_field_audit_fails_when_v3a_field_is_missing(tmp_path):
    root = tmp_path
    run_dir = root / "state" / "live_runs" / "run_002"
    row = complete_row()
    del row["v3a_market_regime"]
    write_jsonl(run_dir / "artifacts" / "candidate_decisions.jsonl", [row])

    payload = build_trace_field_audit(root, "run_002")

    assert payload["status"] == "FAIL"
    assert payload["reason"] == "missing_v3a_fields"
    assert payload["missing_v3a_field_counts"]["v3a_market_regime"] == 1


def test_trace_field_audit_fails_when_wait_reason_is_missing(tmp_path):
    root = tmp_path
    run_dir = root / "state" / "live_runs" / "run_003"
    row = complete_row(decision="WAIT")
    del row["wait_reason"]
    write_jsonl(run_dir / "artifacts" / "candidate_decisions.jsonl", [row])

    payload = build_trace_field_audit(root, "run_003")

    assert payload["status"] == "FAIL"
    assert payload["reason"] == "wait_rows_missing_wait_reason_fields"


def test_trace_field_audit_text_report_contains_status(tmp_path):
    root = tmp_path
    run_dir = root / "state" / "live_runs" / "run_004"
    write_jsonl(run_dir / "artifacts" / "candidate_decisions.jsonl", [complete_row()])

    payload = build_trace_field_audit(root, "run_004")
    text = render_text_report(payload)

    assert "ACC V3-A Trace Field Audit" in text
    assert "Status: PASS" in text
    assert "Missing V3-A Field Counts" in text
