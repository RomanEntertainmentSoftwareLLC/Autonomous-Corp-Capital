#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path("/opt/openclaw/.openclaw/workspace")
MEM = ROOT / "ai_agents_memory"
CONFIG = Path("/opt/openclaw/.openclaw/openclaw.json")
REPORTS = ROOT / "reports"


def parse_rpg(path: Path) -> dict[str, float]:
    text = path.read_text(errors="replace")
    values: dict[str, str] = {}
    for line in text.splitlines():
        m = re.match(r"^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|$", line)
        if m:
            key = m.group(1).strip().lower().replace(" ", "_")
            if key in {"field", "-------"}:
                continue
            values[key] = m.group(2).strip()
            continue
        m = re.match(r"^\s*([A-Za-z][A-Za-z _/-]+?)\s*:\s*(.*?)\s*$", line)
        if m:
            values[m.group(1).strip().lower().replace(" ", "_")] = m.group(2).strip()

    def num(k: str) -> float:
        raw = str(values.get(k, "")).split("/", 1)[0].strip()
        try:
            return float(raw)
        except Exception:
            return 0.0

    return {
        "level": num("level"),
        "xp": num("xp"),
        "sessions": num("sessions"),
        "intelligence": num("intelligence"),
        "usefulness": num("usefulness"),
        "judgment": num("judgment"),
        "evidence_quality": num("evidence_quality"),
        "waste_penalty": num("waste_penalty"),
        "fake_productivity_penalty": num("fake_productivity_penalty"),
    }


def registered_agents() -> list[str]:
    try:
        data = json.loads(CONFIG.read_text())
    except Exception:
        return []
    agents_section = data.get("agents", {})
    agents = []
    if isinstance(agents_section, dict) and isinstance(agents_section.get("list"), list):
        agents = agents_section["list"]
    elif isinstance(agents_section, list):
        agents = agents_section
    ids: list[str] = []
    for item in agents:
        if isinstance(item, dict):
            aid = item.get("id") or item.get("name")
            if aid:
                ids.append(aid)
    return sorted(set(ids))


def build_rows() -> list[dict]:
    rows: list[dict] = []
    for aid in registered_agents():
        alias = {"yam_yam": "main"}.get(aid, aid)
        p = MEM / alias / "RPG_STATE.md"
        stats = parse_rpg(p) if p.exists() else {
            "level": 0.0,
            "xp": 0.0,
            "sessions": 0.0,
            "intelligence": 0.0,
            "usefulness": 0.0,
            "judgment": 0.0,
            "evidence_quality": 0.0,
            "waste_penalty": 0.0,
            "fake_productivity_penalty": 0.0,
        }
        rows.append({"agent": aid, **stats, "rpg_exists": p.exists()})
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description="Write full agent RPG stats report to file.")
    ap.add_argument("--filter", choices=["zero", "active", "master", "company_001", "company_002", "company_003", "company_004", "all"], default="all")
    ap.add_argument("--output", default=None)
    args = ap.parse_args()

    rows = build_rows()
    if args.filter == "zero":
        rows = [r for r in rows if r["xp"] <= 0]
    elif args.filter == "active":
        rows = [r for r in rows if r["sessions"] > 0]
    elif args.filter == "master":
        rows = [r for r in rows if r["agent"] in {"main", "selene", "helena", "vivienne", "ariadne", "ledger", "axiom", "grant_cardone"}]
    elif args.filter.startswith("company_"):
        rows = [r for r in rows if args.filter in r["agent"]]

    rows.sort(key=lambda r: (-r["xp"], r["agent"]))
    REPORTS.mkdir(parents=True, exist_ok=True)
    out = Path(args.output) if args.output else REPORTS / f"agent_stats_{args.filter}.txt"
    lines = [f"AGENT STATS REPORT ({args.filter})", "=" * 80, f"count: {len(rows)}", ""]
    for r in rows:
        lines.append(
            f"{r['agent']}: xp={r['xp']} sessions={r['sessions']} level={r['level']} usefulness={r['usefulness']} judgment={r['judgment']} evidence={r['evidence_quality']} rpg_exists={r['rpg_exists']}"
        )
    out.write_text("\n".join(lines) + "\n")
    print(f"Wrote: {out}")
    for line in lines[:20]:
        print(line)


if __name__ == "__main__":
    main()
