from __future__ import annotations

from pathlib import Path

from tools.live_run import _live_committee_payload_failed
from tools.openclaw_agent_bridge import _bridge_search_path, _resolve_openclaw_command


def test_resolve_openclaw_command_honors_openclaw_bin(monkeypatch, tmp_path: Path) -> None:
    fake = tmp_path / "openclaw"
    fake.write_text("#!/bin/sh\nexit 0\n")
    fake.chmod(0o755)
    monkeypatch.setenv("OPENCLAW_BIN", str(fake))
    monkeypatch.setenv("PATH", "")

    assert _resolve_openclaw_command() == [str(fake)]


def test_bridge_search_path_includes_user_local_bin(monkeypatch) -> None:
    monkeypatch.setenv("PATH", "/usr/bin")
    search_path = _bridge_search_path().split(":")

    assert "/usr/bin" in search_path
    assert str(Path.home() / ".local" / "bin") in search_path


def test_live_committee_payload_failed_detects_bridge_failures() -> None:
    assert _live_committee_payload_failed({"bridge_failed": True}) is True
    assert _live_committee_payload_failed({"bridge_error": "no such file"}) is True
    assert _live_committee_payload_failed({"reply_text": "Bridge call failed for iris_company_001; escalated without Python role fallback."}) is True
    assert _live_committee_payload_failed({"reply_text": "All good.", "analysis_summary": "healthy"}) is False
