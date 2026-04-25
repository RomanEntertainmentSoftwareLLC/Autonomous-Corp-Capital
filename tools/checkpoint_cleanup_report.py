#!/usr/bin/env python3
"""Read-only ACC checkpoint cleanup report.

This reports visual clutter and backup health. It intentionally does not delete or
move files; it prints suggested archive commands for human review.
"""
from __future__ import annotations

import os
from collections import Counter
from pathlib import Path

ROOT = Path(os.environ.get("ACC_ROOT", "/opt/openclaw/.openclaw/workspace"))
REPORTS = ROOT / "reports"
BACKUP_ROOT = ROOT / "ai_agents_backup"

PATTERNS = [
    ("yam_rpg_step*.txt", "docs/archive/yam_rpg_steps"),
    ("step*.out", "docs/archive/old_runtime_outputs"),
    ("*.tmp", "docs/archive/tmp"),
    ("*.bak", "docs/archive/bak_files"),
    ("tools/*.broken.py", "docs/archive/old_runtime_files"),
    ("acc_backup_*.tar.gz", "docs/archive/old_backups"),
    ("ai_agents_backup_broken_*", "docs/archive/old_agent_backups"),
]


def _count(name: str) -> int:
    return len(list(BACKUP_ROOT.rglob(name))) if BACKUP_ROOT.exists() else 0


def _find_nested_company004() -> list[Path]:
    if not BACKUP_ROOT.exists():
        return []
    return sorted(p for p in BACKUP_ROOT.rglob("company004_branch") if "company004_branch/company004_branch" in str(p))


def main() -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)
    report = REPORTS / "checkpoint_cleanup_report.txt"

    backup_counts = {
        "AGENTS.md": _count("AGENTS.md"),
        "IDENTITY.md": _count("IDENTITY.md"),
        "SOUL.md": _count("SOUL.md"),
        "MEMORY.md": _count("MEMORY.md"),
        "USER.md": _count("USER.md"),
        "TOOLS.md": _count("TOOLS.md"),
        "BOOTSTRAP.md": _count("BOOTSTRAP.md"),
        "HEARTBEAT.md": _count("HEARTBEAT.md"),
    }

    clutter: list[tuple[str, str, list[Path]]] = []
    for pattern, archive_dir in PATTERNS:
        matches = sorted(ROOT.glob(pattern))
        if matches:
            clutter.append((pattern, archive_dir, matches))

    suffix_counts = Counter(p.suffix for p in ROOT.iterdir() if p.is_file()) if ROOT.exists() else Counter()
    nested_004 = _find_nested_company004()

    lines = [
        "ACC CHECKPOINT CLEANUP REPORT",
        "=============================",
        f"Root: {ROOT}",
        "",
        "Backup health counts:",
    ]
    for key, value in backup_counts.items():
        lines.append(f"- {key}: {value}")
    lines.extend([
        "",
        "Expected: AGENTS/IDENTITY/SOUL/MEMORY should not be zero if ai_agents_backup is a true backup.",
        "",
        "Nested company004 duplicate check:",
    ])
    if nested_004:
        for p in nested_004[:20]:
            lines.append(f"- suspicious nested path: {p}")
        if len(nested_004) > 20:
            lines.append(f"- ... {len(nested_004) - 20} more")
    else:
        lines.append("- no nested company004_branch/company004_branch paths detected")

    lines.extend(["", "Root file suffix summary:"])
    for suffix, count in suffix_counts.most_common():
        lines.append(f"- {suffix or '[no suffix]'}: {count}")

    lines.extend(["", "Potential visual cleanup candidates:"])
    if not clutter:
        lines.append("- no obvious clutter patterns found")
    for pattern, archive_dir, matches in clutter:
        lines.append(f"\nPattern: {pattern} -> {archive_dir}")
        for p in matches[:25]:
            lines.append(f"- {p.relative_to(ROOT)}")
        if len(matches) > 25:
            lines.append(f"- ... {len(matches) - 25} more")
        lines.append("Suggested safe archive command:")
        lines.append(f"mkdir -p {archive_dir}")
        lines.append(f"git mv {pattern} {archive_dir}/ 2>/dev/null || true")

    lines.extend([
        "",
        "Do not delete ai_agents_backup blindly. If it is wrong, rebuild from /opt/openclaw/.openclaw/workspaces/ai_agents first.",
    ])
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\nWrote: {report}")


if __name__ == "__main__":
    main()
