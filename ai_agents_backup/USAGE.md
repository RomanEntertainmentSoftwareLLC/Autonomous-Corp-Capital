# USAGE.md

## Interactive Quick Start

Talk to the orchestra with the Pam CLI:
```bash
python3 tools/pam.py --agent <agent_id> "<question>"
```
Example patterns:
- `python3 tools/pam.py --agent pam_company_001 "What is blocked right now?"`
- `python3 tools/pam.py --agent iris_company_001 "Summarize company_001 health."`
- `python3 tools/pam.py --agent master_treasurer "How healthy is the parent treasury right now?"`
- `python3 tools/pam.py --agent product_manager "What should engineering build next?"`
- `python3 tools/pam.py --agent inspector_general "Do you see any branch overreach right now?"`

## Toolchain Commands
- Run the live virtual-currency paper simulation: `python3 tools/live_run.py start` (stops with `python3 tools/live_run.py stop`).
- Summaries and verification: `python3 tools/live_run.py summary --run-id <run_id>` and `python3 tools/live_run.py verify --run-id <run_id>`.
- Phase 3 launch-readiness package generation: `python3 tools/phase3_report.py --run-dir <state/live_runs/<run_id>>`.
- Owner's manual regeneration (PDF): `pandoc docs/owner_manual.md -o docs/owner_manual.pdf` (remain in markdown until that command is run).

## Documentation
The owner’s manual (`docs/owner_manual.md`) contains the full roster, governance rules, live-data procedures, and Phase 3 launch gate. Regenerate it with the pandoc command above when changes are made.
