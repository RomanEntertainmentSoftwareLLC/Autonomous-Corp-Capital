from pathlib import Path

from tools.rpg_state import apply_runtime_packet_rpg_updates, format_runtime_rpg_event, load_rpg_state


def test_live_committee_packet_awards_xp_and_writes_history(tmp_path: Path):
    packet = {
        "timestamp": "2026-04-15T02:49:39.973333+00:00",
        "company_id": "company_001",
        "packet_generation_mode": "live_committee_sessions",
        "approval_posture": "hold",
        "top_ranked_candidates": [
            {"symbol": "AVAX-USD", "execution_state": "executed"},
        ],
        "committee_sources": {
            "Lucian": {"mode": "live_session", "agent_id": "lucian_company_001", "summary": "Iris: lifecycle. | Vera: Hold | Bianca posture: justify"},
            "Orion": {"mode": "live_session", "agent_id": "orion_company_001", "summary": "Recommendation: Lean into the highest-ranked BUY only if it already survived portfolio and risk checks. Queue pressure: 2 new item(s)."},
        },
    }

    events = apply_runtime_packet_rpg_updates(packet, workspace_root=tmp_path)
    assert len(events) == 2

    lucian_state = load_rpg_state(tmp_path / "ai_agents_memory" / "lucian_company_001" / "RPG_STATE.md")
    orion_state = load_rpg_state(tmp_path / "ai_agents_memory" / "orion_company_001" / "RPG_STATE.md")
    assert lucian_state["xp"] > 0
    assert orion_state["xp"] > 0
    assert lucian_state["sessions"] == 1
    assert orion_state["sessions"] == 1

    history_text = (tmp_path / "ai_agents_memory" / "orion_company_001" / "RPG_HISTORY.md").read_text(encoding="utf-8")
    assert "orion_company_001" in history_text
    assert "+" in history_text

    lines = [format_runtime_rpg_event(event) for event in events]
    assert all(line.startswith("[RPG]") for line in lines)


def test_fallback_packet_does_not_award_xp(tmp_path: Path):
    packet = {
        "timestamp": "2026-04-15T02:45:57.258214+00:00",
        "company_id": "company_002",
        "packet_generation_mode": "fallback",
        "committee_sources": {
            "Lucian": {"mode": "fallback_saved", "summary": "historical only"},
        },
    }

    events = apply_runtime_packet_rpg_updates(packet, workspace_root=tmp_path)
    assert events == []
    state_path = tmp_path / "ai_agents_memory" / "lucian_company_002" / "RPG_STATE.md"
    assert not state_path.exists()
