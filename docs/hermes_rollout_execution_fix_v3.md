# Hermes smoke/inventory fix v3

This patch fixes the Hermes follow-up tools from the phased rollout work.

## Files changed

- `tools/hermes_smoke_test.py`
- `tools/hermes_inventory_audit.py`
- `tools/hermes_rollout_plan.py`

## Fixes

1. `hermes_smoke_test.py` now runs OpenClaw subprocesses with `stdin=subprocess.DEVNULL` so operator keystrokes such as `hi` or `hello` cannot leak back into Bash as shell commands.
2. `hermes_inventory_audit.py` now reads the modern OpenClaw config shape: `agents.list` and `models.providers`.
3. `hermes_rollout_plan.py` now treats configured agents from `openclaw.json` as the source of truth instead of over-discovering backup/template folders as fake extra agents.
4. The rollout plan now reports real configured model strings instead of `unknown` when the config contains per-agent models.

## After applying

```bash
cd /opt/openclaw/.openclaw/workspace

python3 -m py_compile \
  tools/hermes_smoke_test.py \
  tools/hermes_inventory_audit.py \
  tools/hermes_rollout_plan.py

python3 tools/hermes_smoke_test.py --phase1
python3 tools/hermes_inventory_audit.py
python3 tools/hermes_rollout_plan.py
git status --short
```
