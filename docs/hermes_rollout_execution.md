# Hermes Rollout Execution Patch

This patch adds controlled Hermes rollout execution for ACC/OpenClaw agent model routing.

## Files

- `tools/hermes_config_rollout.py`
- `tools/hermes_smoke_test.py`
- `docs/hermes_rollout_execution.md`

## Purpose

The previous Hermes tools were audit/plan only. This patch adds a safe execution step that can inspect, dry-run, and apply phased `openclaw.json` model routing changes without mass-flipping the whole org.

Default routing:

- Rowan agents use `hermes_rowan/hermes-agent`.
- All other selected agents use `hermes/hermes-agent`.

The tool intentionally updates explicit per-agent `model` fields only. It does not change the global default model because that could accidentally route unreviewed agents to Hermes.

## Phase map

| Phase | Agents |
| --- | --- |
| `phase0` | `main` / Yam Yam |
| `phase1` | `axiom`, `vivienne`, `helena`, `ledger` |
| `phase2` | `grant_cardone`, `ariadne`, `selene` |
| `company_core` | `lucian`, `bianca`, `iris`, `vera`, `orion`, `rowan` for companies 001-004 |
| `company_support` | `pam`, `bob`, `sloane`, `atlas`, `june` for companies 001-004 |
| `watchdogs` | `mara`, `justine`, `owen` |
| `swe` | `nadia`, `tessa`, `marek`, `eli`, `noah`, `mina`, `gideon`, `sabine`, `rhea` |
| `all_non_swe` | master + watchdog + company phases, excluding SWE |
| `all` | all supported phases |

## Basic install

From the ACC repo root:

```bash
unzip -o /path/to/acc_hermes_rollout_execution_patch_v1.zip

python3 -m py_compile \
  tools/hermes_config_rollout.py \
  tools/hermes_smoke_test.py
```

## Recommended rollout sequence

Audit first:

```bash
python3 tools/hermes_config_rollout.py --audit
```

Dry-run phase 0:

```bash
python3 tools/hermes_config_rollout.py --phase phase0
```

Apply phase 0:

```bash
python3 tools/hermes_config_rollout.py --phase phase0 --apply
```

Smoke-test Yam Yam/main:

```bash
python3 tools/hermes_smoke_test.py --agent main
```

Then phase 1:

```bash
python3 tools/hermes_config_rollout.py --phase phase1
python3 tools/hermes_config_rollout.py --phase phase1 --apply
python3 tools/hermes_smoke_test.py --phase1
```

Do not continue to larger phases until the current phase responds normally and does not create unacceptable runtime/cost behavior.

## Config path override

By default, the rollout tool reads and writes:

```text
/opt/openclaw/.openclaw/openclaw.json
```

Override it when testing:

```bash
python3 tools/hermes_config_rollout.py --config /tmp/openclaw.json --audit
```

The same override works for the smoke tester when it reports configured models:

```bash
python3 tools/hermes_smoke_test.py --config /tmp/openclaw.json --phase1 --dry-run
```

## Backup behavior

When `--apply` makes at least one model change, the rollout tool writes a backup next to the config first:

```text
openclaw.json.bak.hermes_rollout_YYYYMMDDTHHMMSSZ
```

If no changes are required, the config is not rewritten and no backup is created.

## Commit message

```bash
git add tools/hermes_config_rollout.py tools/hermes_smoke_test.py docs/hermes_rollout_execution.md

git commit -m "Add phased Hermes rollout execution tools" \
  -m "Adds controlled OpenClaw config tooling to audit and apply phased Hermes routing for ACC agents, including phase0 Yam Yam, phase1 governance agents, later company/watchdog/SWE phases, automatic openclaw.json backups, Rowan-specific Hermes routing, and smoke tests for selected agents after rollout."
```
