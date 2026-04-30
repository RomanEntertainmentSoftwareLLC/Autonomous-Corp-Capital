import json
from pathlib import Path

from tools.v3a_regime_posture_report import build_report_payload, render_text_report


def write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def test_v3a_report_reads_latest_candidate_rows(tmp_path):
    root = tmp_path
    run_dir = root / "state" / "live_runs" / "run_001"
    (root / "state" / "live_runs").mkdir(parents=True)
    (root / "state" / "live_runs" / "current_run.json").write_text(
        json.dumps({"run_id": "run_001"}),
        encoding="utf-8",
    )
    write_jsonl(
        run_dir / "artifacts" / "candidate_decisions.jsonl",
        [
            {
                "company_id": "company_001",
                "symbol": "BTC-USD",
                "decision": "WAIT",
                "change_pct": -0.01,
                "policy_signal_score": -0.01,
                "model_score": 0.25,
                "wait_reason": "WAIT_MARKET_HOSTILE",
            },
            {
                "company_id": "company_002",
                "symbol": "ETH-USD",
                "decision": "WAIT",
                "change_pct": -0.012,
                "policy_signal_score": -0.012,
                "model_score": 0.3,
                "wait_reason": "WAIT_MARKET_HOSTILE",
            },
            {
                "company_id": "company_003",
                "symbol": "SOL-USD",
                "decision": "BUY",
                "change_pct": 0.002,
                "policy_signal_score": 0.002,
                "model_score": 0.55,
            },
        ],
    )

    payload = build_report_payload(root, "latest")

    assert payload["status"] == "ok"
    assert payload["candidate_rows"] == 3
    assert payload["run_id"] == "run_001"
    assert payload["decision_counts"]["WAIT"] == 2
    assert payload["wait_reason_counts"]["WAIT_MARKET_HOSTILE"] == 2
    assert payload["top_ranked"]


def test_v3a_report_handles_missing_run_dir(tmp_path):
    payload = build_report_payload(tmp_path, "latest")

    assert payload["status"] == "missing_run_dir"
    assert payload["candidate_rows"] == 0
    assert payload["market_regime"]["market_regime"] == "unknown"


def test_v3a_text_report_contains_operator_sections(tmp_path):
    root = tmp_path
    run_dir = root / "state" / "live_runs" / "run_002"
    write_jsonl(
        run_dir / "artifacts" / "candidate_decisions.jsonl",
        [
            {
                "company_id": "company_001",
                "symbol": "BTC-USD",
                "decision": "BUY",
                "change_pct": 0.01,
                "policy_signal_score": 0.01,
                "model_score": 0.8,
            }
        ],
    )

    payload = build_report_payload(root, "run_002")
    text = render_text_report(payload)

    assert "ACC V3-A Regime + Market Posture Report" in text
    assert "Market Weather" in text
    assert "Decision Counts" in text
    assert "Top Ranked Candidates" in text
    assert "BTC-USD" in text


def test_v3a_regime_posture_report_runs_as_direct_script(tmp_path):
    import subprocess
    import sys
    from pathlib import Path

    root = tmp_path
    run_dir = root / "state" / "live_runs" / "run_direct"
    write_jsonl(
        run_dir / "artifacts" / "candidate_decisions.jsonl",
        [
            {
                "company_id": "company_001",
                "symbol": "BTC-USD",
                "decision": "WAIT",
                "change_pct": 0.001,
                "policy_signal_score": 0.001,
                "model_score": 0.55,
                "wait_reason": "WAIT_NEEDS_CONFIRMATION",
            }
        ],
    )

    repo_root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [
            sys.executable,
            "tools/v3a_regime_posture_report.py",
            "--root",
            str(root),
            "--run-id",
            "run_direct",
        ],
        cwd=repo_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    assert completed.returncode == 0, completed.stdout
    assert "ACC V3-A Regime + Market Posture Report" in completed.stdout
    assert "BTC-USD" in completed.stdout
