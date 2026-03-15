"""Manage company-local agent rosters."""

from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

ROOT = Path(__file__).resolve().parent.parent
COMPANIES_DIR = ROOT / "companies"
CONFIG_AGENTS = ROOT / "config" / "agents.yaml"
STATE_AGENTS = ROOT / "state" / "agents"
ARCHIVE_ROOT = ROOT / "state" / "archive"
ARCHIVE_AGENTS = ARCHIVE_ROOT / "agents"
ARCHIVE_COMPANIES = ARCHIVE_ROOT / "companies"
RETIRE_MANIFESTS = ARCHIVE_ROOT / "retire_manifests"
ARCHIVE_AGENTS.mkdir(parents=True, exist_ok=True)
ARCHIVE_COMPANIES.mkdir(parents=True, exist_ok=True)
RETIRE_MANIFESTS.mkdir(parents=True, exist_ok=True)

REQUIRED_STAFF = [
    {
        "persona": "pam",
        "display_name": "Pam",
        "role": "administrative_coordinator",
        "description": "Pam keeps the queue tidy for the company",
    },
    {
        "persona": "iris",
        "display_name": "Iris",
        "role": "Analyst",
        "description": "Iris analyzes company data",
    },
    {
        "persona": "vera",
        "display_name": "Vera",
        "role": "Manager",
        "description": "Vera recommends next steps",
    },
    {
        "persona": "rowan",
        "display_name": "Rowan",
        "role": "Researcher",
        "description": "Rowan explores strategic ideas",
    },
    {
        "persona": "bianca",
        "display_name": "Bianca",
        "role": "CFO",
        "description": "Bianca watches the financial health",
    },
    {
        "persona": "lucian",
        "display_name": "Lucian",
        "role": "CEO",
        "description": "Lucian makes the final call",
    },
    {
        "persona": "bob",
        "display_name": "Bob",
        "role": "Low Tier Operations Worker",
        "description": "Bob handles safe operational chores",
    },
]

COMPANY_STATUS_ACTIVE = "active"
COMPANY_STATUS_RETIRED = "retired"
COMPANY_STATUS_ARCHIVED = "archived"
COMPANY_STATUS_DELETED = "deleted"
AGENT_STATUS_ACTIVE = "active"
AGENT_STATUS_DISABLED = "disabled"
AGENT_STATUS_ARCHIVED = "archived"


def _load_agents_config() -> Dict[str, Any]:
    if not CONFIG_AGENTS.exists():
        return {"agents": []}
    with CONFIG_AGENTS.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if "agents" not in data or data["agents"] is None:
        data["agents"] = []
    return data


def _save_agents_config(data: Dict[str, Any]) -> None:
    CONFIG_AGENTS.parent.mkdir(parents=True, exist_ok=True)
    with CONFIG_AGENTS.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, sort_keys=False)


def _agent_id(persona: str, company: str) -> str:
    return f"{persona}_{company}"


def _ensure_agent_dirs(agent_id: str) -> Path:
    path = STATE_AGENTS / agent_id
    path.mkdir(parents=True, exist_ok=True)
    requires = ["inbox.jsonl", "outbox.jsonl", "queue.json", "escalations.jsonl", "meetings.jsonl"]
    for name in requires:
        file_path = path / name
        if not file_path.exists():
            if name == "queue.json":
                file_path.write_text(json.dumps({"new": [], "assigned": [], "in_progress": [], "blocked": [], "completed": [], "escalated": []}, indent=2))
            else:
                file_path.write_text("")
    meta_path = path / "meta.json"
    if not meta_path.exists():
        meta_path.write_text(json.dumps({"status": AGENT_STATUS_ACTIVE}, indent=2))
    return path


def _write_agent_meta(agent_id: str, meta: Dict[str, Any]) -> None:
    path = STATE_AGENTS / agent_id / "meta.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(meta, indent=2))


def _read_agent_meta(agent_id: str) -> Dict[str, Any]:
    path = STATE_AGENTS / agent_id / "meta.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}


def _remove_agent_entry(agent_id: str, config: Dict[str, Any]) -> bool:
    agents = config.get("agents", [])
    for idx, entry in enumerate(agents):
        if entry.get("id") == agent_id:
            agents.pop(idx)
            return True
    return False


def _add_agent_entry(company: str, persona_info: Dict[str, str], config: Dict[str, Any]) -> bool:
    agent_id = _agent_id(persona_info["persona"], company)
    agents = config.setdefault("agents", [])
    for entry in agents:
        if entry.get("id") == agent_id:
            if entry.get("scope") != company:
                entry["scope"] = company
            return False
    entry = {
        "id": agent_id,
        "name": persona_info["display_name"],
        "persona": persona_info["persona"],
        "role": persona_info["role"],
        "scope": company,
        "description": persona_info.get("description", ""),
    }
    agents.append(entry)
    return True


def _agent_lineage(company: str, parent_company: Optional[str], generation: int, event_id: str) -> Dict[str, Any]:
    return {
        "company_id": company,
        "parent_company_id": parent_company,
        "lifecycle_generation": generation,
        "cloned_from_company": parent_company,
        "created_by_mutation_event_id": event_id,
    }


def ensure_company_roster(
    company: str,
    parent_company: Optional[str] = None,
    generation: Optional[int] = None,
    event_id: Optional[str] = None,
) -> None:
    config = _load_agents_config()
    updated = False
    event_id = event_id or str(uuid.uuid4())
    generation = generation or 0
    lineage = _agent_lineage(company, parent_company, generation, event_id)
    for persona_info in REQUIRED_STAFF:
        agent_id = _agent_id(persona_info["persona"], company)
        if _add_agent_entry(company, persona_info, config):
            updated = True
        agent_path = _ensure_agent_dirs(agent_id)
        meta = _read_agent_meta(agent_id)
        meta.update(
            {
                "company_id": company,
                "persona": persona_info["persona"],
                "role": persona_info["role"],
                "status": AGENT_STATUS_ACTIVE,
                "lineage": lineage,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        _write_agent_meta(agent_id, meta)
    if updated:
        _save_agents_config(config)


def roster_sync() -> None:
    config = _load_agents_config()
    active_companies = set()
    for company_dir in COMPANIES_DIR.iterdir():
        if not company_dir.is_dir():
            continue
        metadata_path = company_dir / "metadata.yaml"
        status = COMPANY_STATUS_ACTIVE
        if metadata_path.exists():
            data = yaml.safe_load(metadata_path.open("r", encoding="utf-8")) or {}
            status = data.get("company_status", COMPANY_STATUS_ACTIVE)
        if status == COMPANY_STATUS_ACTIVE:
            active_companies.add(company_dir.name)
    changed = False
    for company in sorted(active_companies):
        for persona_info in REQUIRED_STAFF:
            agent_id = _agent_id(persona_info["persona"], company)
            if not any(entry.get("id") == agent_id for entry in config.get("agents", [])):
                if _add_agent_entry(company, persona_info, config):
                    changed = True
            _ensure_agent_dirs(agent_id)
            meta = _read_agent_meta(agent_id)
            if meta.get("status") != AGENT_STATUS_ACTIVE:
                meta["status"] = AGENT_STATUS_ACTIVE
                meta["updated_at"] = datetime.now(timezone.utc).isoformat()
                _write_agent_meta(agent_id, meta)
    active_agent_ids = {entry.get("id") for entry in config.get("agents", []) if entry.get("scope") in active_companies}
    to_remove = []
    for entry in list(config.get("agents", [])):
        scope = entry.get("scope")
        if scope not in active_companies:
            to_remove.append(entry.get("id"))
    for agent_id in to_remove:
        if _remove_agent_entry(agent_id, config):
            changed = True
            meta = _read_agent_meta(agent_id)
            meta["status"] = AGENT_STATUS_DISABLED
            meta["updated_at"] = datetime.now(timezone.utc).isoformat()
            _write_agent_meta(agent_id, meta)
    if changed:
        _save_agents_config(config)


def _archive_agent(agent_id: str) -> Path:
    src = STATE_AGENTS / agent_id
    dst = ARCHIVE_AGENTS / agent_id
    meta = _read_agent_meta(agent_id)
    if dst.exists():
        shutil.rmtree(dst)
    if src.exists():
        shutil.move(str(src), str(dst))
    else:
        dst.mkdir(parents=True, exist_ok=True)
    meta["status"] = AGENT_STATUS_ARCHIVED
    meta["archived_at"] = datetime.now(timezone.utc).isoformat()
    dst_meta = dst / "meta.json"
    dst_meta.write_text(json.dumps(meta, indent=2))
    return dst


def _restore_agent(agent_id: str, archived_path: Path) -> None:
    dst = STATE_AGENTS / agent_id
    if dst.exists():
        shutil.rmtree(dst)
    if archived_path.exists():
        shutil.move(str(archived_path), str(dst))
    meta = _read_agent_meta(agent_id)
    meta["status"] = AGENT_STATUS_ACTIVE
    meta["restored_at"] = datetime.now(timezone.utc).isoformat()
    _write_agent_meta(agent_id, meta)


def archive_company_state(company: str) -> Path:
    src = COMPANIES_DIR / company
    dst = ARCHIVE_COMPANIES / company
    if dst.exists():
        shutil.rmtree(dst)
    if src.exists():
        shutil.copytree(src, dst)
    return dst


def retire_company(
    company: str,
    retire_mode: str = "retire",
    event_id: Optional[str] = None,
    test_mode: bool = False,
) -> Path:
    event_id = event_id or str(uuid.uuid4())
    config = _load_agents_config()
    metadata_path = COMPANIES_DIR / company / "metadata.yaml"
    metadata = {}
    if metadata_path.exists():
        metadata = yaml.safe_load(metadata_path.open("r", encoding="utf-8")) or {}
    prior_metadata = json.loads(json.dumps(metadata))
    metadata.setdefault("company_id", company)
    metadata["company_status"] = COMPANY_STATUS_RETIRED
    metadata["retired_at"] = datetime.now(timezone.utc).isoformat()
    with metadata_path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(metadata, fh, sort_keys=False)
    archive_company_state(company)
    manifest: Dict[str, Any] = {
        "company_id": company,
        "event_id": event_id,
        "mode": "test" if test_mode else retire_mode,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "prior_metadata": prior_metadata,
        "agents": [],
    }
    for persona_info in REQUIRED_STAFF:
        agent_id = _agent_id(persona_info["persona"], company)
        entry = next((entry for entry in config.get("agents", []) if entry.get("id") == agent_id), None)
        if entry:
            _remove_agent_entry(agent_id, config)
        archive_path = _archive_agent(agent_id)
        manifest["agents"].append(
            {
                "agent_id": agent_id,
                "archived_path": str(archive_path),
                "persona": persona_info["persona"],
                "role": persona_info["role"],
            }
        )
    roster_sync()
    RETIRE_MANIFESTS.mkdir(parents=True, exist_ok=True)
    manifest_path = RETIRE_MANIFESTS / f"{company}_{event_id}.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    return manifest_path


def restore_company(manifest_path: Path) -> None:
    data = json.loads(manifest_path.read_text())
    company = data.get("company_id")
    metadata_path = COMPANIES_DIR / company / "metadata.yaml"
    prior_metadata = data.get("prior_metadata") or {}
    prior_metadata["company_status"] = COMPANY_STATUS_ACTIVE
    with metadata_path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(prior_metadata, fh, sort_keys=False)
    for agent_data in data.get("agents", []):
        agent_id = agent_data.get("agent_id")
        archived_path = Path(agent_data.get("archived_path"))
        if archived_path.exists():
            _restore_agent(agent_id, archived_path)
    ensure_company_roster(company)
    roster_sync()


def ensure_company_active(company: str) -> None:
    path = COMPANIES_DIR / company / "metadata.yaml"
    metadata = {}
    if path.exists():
        metadata = yaml.safe_load(path.open("r", encoding="utf-8")) or {}
    metadata["company_status"] = COMPANY_STATUS_ACTIVE
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(metadata, fh, sort_keys=False)
