#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import re

ROOT = Path("/opt/openclaw/.openclaw/workspace")
LIVE_RUN = ROOT / "tools" / "live_run.py"

FUNCTION_BLOCK = """
def run_external_plan_context_snapshot(run_id):
    \"\"\"Bind roadmap/planning docs into the live-run artifact stream.

    This is intentionally non-fatal. The external plan context helps governance
    agents remember roadmap/V2/V3/Hermes/Grant doctrine, but a snapshot failure
    must never kill a trading run.
    \"\"\"
    if os.environ.get("DISABLE_EXTERNAL_PLAN_CONTEXT") == "1":
        print("External plan context snapshot disabled via DISABLE_EXTERNAL_PLAN_CONTEXT=1")
        return

    try:
        project_root = globals().get("ROOT", Path("/opt/openclaw/.openclaw/workspace"))
        cmd = [sys.executable, "tools/external_plan_context_snapshot.py"]
        if run_id:
            cmd.extend(["--run-id", str(run_id)])

        proc = subprocess.run(
            cmd,
            cwd=str(project_root),
            text=True,
            capture_output=True,
            timeout=120,
        )

        out_dir = Path("state") / "external_plan_context"
        out_dir.mkdir(parents=True, exist_ok=True)

        hook_log = out_dir / f"{run_id or 'NO_RUN'}_external_plan_context_hook.log"
        hook_log.write_text(
            (proc.stdout or "") + ("\\nSTDERR:\\n" + proc.stderr if proc.stderr else ""),
            encoding="utf-8",
        )

        if proc.returncode != 0:
            print(f"External plan context snapshot failed: {proc.returncode}; see {hook_log}")
        else:
            print(f"External plan context snapshot completed; see {hook_log}")

    except Exception as exc:
        try:
            out_dir = Path("state") / "external_plan_context"
            out_dir.mkdir(parents=True, exist_ok=True)
            error_log = out_dir / f"{run_id or 'NO_RUN'}_external_plan_context_hook_error.log"
            error_log.write_text(str(exc), encoding="utf-8")
        except Exception:
            pass

        print(f"External plan context snapshot skipped after error: {exc}")
""".strip() + "\n\n"


def _ensure_import(text: str, module_name: str) -> tuple[str, bool]:
    if re.search(rf"^\s*import\s+{re.escape(module_name)}\b", text, flags=re.M):
        return text, False
    return f"import {module_name}\n" + text, True


def main() -> None:
    if not LIVE_RUN.exists():
        raise SystemExit(f"Missing live_run.py at {LIVE_RUN}")

    original = LIVE_RUN.read_text(encoding="utf-8", errors="replace")
    text = original
    changed = False

    for mod in ["os", "subprocess", "sys"]:
        text, did_change = _ensure_import(text, mod)
        changed = changed or did_change

    if "from pathlib import Path" not in text:
        text = "from pathlib import Path\n" + text
        changed = True

    if "def run_external_plan_context_snapshot(" not in text:
        markers = [
            "def run_ledger_post_run_review",
            "def run_helena_post_run_review",
            "def run_axiom_post_run_review",
            "def run_vivienne_post_run_review",
            "def run_yam_yam_post_run_review",
        ]

        inserted = False
        for marker in markers:
            idx = text.find(marker)
            if idx != -1:
                text = text[:idx] + FUNCTION_BLOCK + text[idx:]
                inserted = True
                changed = True
                break

        if not inserted:
            text = text.rstrip() + "\n\n" + FUNCTION_BLOCK
            changed = True

    call = "run_external_plan_context_snapshot(run_id)"

    if call not in text:
        target = "write_daily_digest(run_id)"
        idx = text.find(target)

        if idx != -1:
            line_end = text.find("\n", idx)
            if line_end == -1:
                line_end = len(text)

            indent_start = text.rfind("\n", 0, idx) + 1
            indent_match = re.match(r"\s*", text[indent_start:idx])
            indent = indent_match.group(0) if indent_match else ""

            text = text[:line_end] + f"\n{indent}{call}" + text[line_end:]
            changed = True
        else:
            fallback = "run_ledger_post_run_review(run_id)"
            idx = text.find(fallback)

            if idx == -1:
                raise SystemExit(
                    "Could not find finalization insertion point. "
                    "Expected write_daily_digest(run_id) or run_ledger_post_run_review(run_id)."
                )

            indent_start = text.rfind("\n", 0, idx) + 1
            indent_match = re.match(r"\s*", text[indent_start:idx])
            indent = indent_match.group(0) if indent_match else ""

            text = text[:idx] + f"{indent}{call}\n" + text[idx:]
            changed = True

    if changed:
        backup = LIVE_RUN.with_suffix(".py.before_external_context_hook")
        if not backup.exists():
            backup.write_text(original, encoding="utf-8")

        LIVE_RUN.write_text(text, encoding="utf-8")
        print(f"Patched {LIVE_RUN}")
        print(f"Backup saved to {backup}")
    else:
        print("No changes needed; external plan context hook already installed.")


if __name__ == "__main__":
    main()
