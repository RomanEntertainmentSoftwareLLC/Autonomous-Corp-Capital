import importlib.util
import json
import sys
from pathlib import Path


def load_live_run_systemd():
    script = Path(__file__).resolve().parents[1] / "scripts" / "live_run_systemd.py"
    spec = importlib.util.spec_from_file_location("live_run_systemd_under_test", script)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_supervisor_main_uses_cli_duration_for_timeout_and_child_command(monkeypatch, tmp_path):
    module = load_live_run_systemd()

    run_dir = tmp_path / "state" / "live_runs" / "run_cli_duration"
    popen_instances = []

    class FakeProc:
        pid = 4242
        returncode = 0

        def __init__(self, cmd, **kwargs):
            self.cmd = cmd
            self.kwargs = kwargs
            self.timeout_seen = None
            popen_instances.append(self)

        def wait(self, timeout=None):
            self.timeout_seen = timeout
            self.returncode = 0
            return 0

        def poll(self):
            return self.returncode

    def fake_popen(cmd, **kwargs):
        return FakeProc(cmd, **kwargs)

    monkeypatch.setenv("ACC_DURATION_HOURS", "24")
    monkeypatch.setenv("ACC_VIRTUAL_CURRENCY", "999")

    monkeypatch.setattr(module, "ensure_directories", lambda: run_dir.mkdir(parents=True, exist_ok=True))
    monkeypatch.setattr(module, "create_run_id", lambda: "run_cli_duration")
    monkeypatch.setattr(module, "run_directory", lambda run_id: run_dir)
    monkeypatch.setattr(module, "write_current_run", lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "virtual_currency_context", lambda amount: {"parent_virtual_currency": amount})
    monkeypatch.setattr(module, "target_symbol_list", lambda: ["BTC-USD"])
    monkeypatch.setattr(module, "run_warehouse_ingest", lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "run_post_run_reports", lambda *args, **kwargs: None)
    monkeypatch.setattr(module.subprocess, "Popen", fake_popen)

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "live_run_systemd.py",
            "--duration-hours",
            "0.03",
            "--virtual-currency",
            "123.45",
        ],
    )

    rc = module.main()

    assert rc == 0
    assert popen_instances

    proc = popen_instances[0]
    assert proc.timeout_seen == 228.0

    duration_index = proc.cmd.index("--duration-hours")
    assert proc.cmd[duration_index + 1] == "0.03"

    currency_index = proc.cmd.index("--virtual-currency")
    assert proc.cmd[currency_index + 1] == "123.45"

    metadata = json.loads((run_dir / "run_metadata.json").read_text(encoding="utf-8"))
    assert metadata["duration_hours"] == 0.03
    assert metadata["hard_timeout_seconds"] == 228.0
    assert metadata["parent_virtual_currency"] == 123.45
