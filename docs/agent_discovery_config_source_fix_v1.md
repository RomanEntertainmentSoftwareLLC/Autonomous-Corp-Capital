# ACC Agent Discovery Config Source Fix v1

This patch fixes discovery tools that were still using `ai_agents_backup` or loose filesystem scans as if they were authoritative.

## Problem

After a duplicate nested folder cleanup, the live workspace correctly returned 63 `AGENTS.md` files, but `agent_activation_queue.py` still reported 102 agents and surfaced fake candidates such as `bianca_cfo_company_001`.

That happened because the older discovery logic scanned backup folders and converted folder names into agent ids. Backup folders are useful for archival comparison, but they are not proof that an agent is registered or live.

## Fix

Updated tools:

- `tools/agent_activation_queue.py`
- `tools/rpg_initialize_missing_agents.py`

Both now use `/opt/openclaw/.openclaw/openclaw.json` registered agents as the source of truth.

## Expected behavior

- `agent_activation_queue.py` should consider 55 agents by default because SWE is excluded.
- `agent_activation_queue.py --include-swe` should consider 64 agents.
- Fake backup-derived ids like `bianca_cfo_company_001` should disappear.
- `rpg_initialize_missing_agents.py --dry-run` should discover 64 agents by default, or 55 with `--exclude-swe`.

## Recommended sequence

```bash
cd /opt/openclaw/.openclaw/workspace

python3 -m py_compile \
  tools/agent_activation_queue.py \
  tools/rpg_initialize_missing_agents.py

python3 tools/agent_activation_queue.py
python3 tools/agent_activation_queue.py --include-swe --limit 80
python3 tools/rpg_initialize_missing_agents.py --dry-run
python3 tools/rpg_initialize_missing_agents.py --dry-run --exclude-swe
```

Only apply the RPG initializer after the dry-run shows real registered agents only.
