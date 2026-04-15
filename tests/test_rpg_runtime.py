from __future__ import annotations

import json
from pathlib import Path

from tools.rpg_state import apply_runtime_rpg_updates, load_rpg_state


def test_apply_runtime_rpg_updates_awards_orion_and_lucian(tmp_path: Path) -> None:
    root = tmp_path
    evidence = tmp_path / "company_packets.jsonl"
    evidence.write_text("\n".join([
        json.dumps({
            "company_id": "company_001",
            "generated_at": "2026-04-15T01:18:01+00:00",
            "packet_generation_mode": "live_committee_sessions",
            "source_agents_consulted": ["Lucian", "Iris", "Vera", "Orion"],
            "committee_sources": {
                "Lucian": {"mode": "live_session", "summary": "Iris: ok | Vera: hold"},
                "Iris": {"mode": "live_session", "summary": "analysis"},
                "Vera": {"mode": "live_session", "summary": "hold"},
                "Orion": {"mode": "live_session", "summary": "research"}
            }
        })
    ]), encoding="utf-8")

    result = apply_runtime_rpg_updates(root, evidence)

    assert "orion_company_001" in result["updated_agents"]
    assert "lucian_company_001" in result["updated_agents"]
    assert load_rpg_state(root / "ai_agents_memory" / "orion_company_001" / "RPG_STATE.md")["xp"] > 0
    assert load_rpg_state(root / "ai_agents_memory" / "lucian_company_001" / "RPG_STATE.md")["sessions"] >= 1
