# Owner's Manual for OpenClaw Republic

## Introduction
This manual describes the implemented organization, how to interact with each agent, the lifecycle/governance rules currently enforced, the Phase 2 paper-run workflow, and the Phase 3 launch-readiness gate. The discourse is factual—features marked "future" are not yet live, and Jacob’s explicit approval is the final gate for any real-money deployment.

---
## 1. Full Employee Roster
Each entry lists display name, internal id, role, scope, branch, responsibilities, authority, limits, and how the role fits the orchestra.

| Display Name | Internal ID | Role | Scope | Branch | Core Responsibilities | Authority | Limits / Not Allowed |
|--------------|-------------|------|-------|--------|-----------------------|-----------|---------------------|
| Jacob | jacob | Owner | global | Owner | Final human decision maker, approves real-money launches | Overrides every branch in emergencies | Cannot micromanage automated decisions without signal |
| Pam | pam_company_* | Administrative Coordinator | company_local | Company-local | Routes requests, queues tasks, ensures packets land in inboxes | Creates packets, summarizes | Cannot approve strategies or allocate capital |
| Iris | iris_company_* | Analyst | company_local | Company-local | Diagnostic evidence, highlights missing data discrepancies | Flags missing evidence | Cannot decide deployments or spend |
| Vera | vera_company_* | Manager | company_local | Company-local | Weighs Iris data, escalates, recommends to CEO | Suggests actions | Cannot override global branches |
| Rowan | rowan_company_* | Researcher | company_local | Company-local | Hypotheses, experiment ideas | Raises research agendas | Cannot act without data |
| Bianca | bianca_company_* | CFO | company_local | Company-local | Runway, spend posture, aligns Vera's input | Rejects reckless spend | Cannot overrule Selene/Helena |
| Lucian | lucian_company_* | CEO | company_local | Company-local | Composes company decisions with inputs | Issues executive directives | Cannot override master/global branches |
| Bob | bob_company_* | Low Tier Operations Worker | company_local | Company-local | Operational chores, artifacts, logs | Completes tasks | Cannot exceed scope or adjust strategy |
| Sloane | sloane_company_* | Evolution | company_local | Company-local | Proposes mutations, coordinates Atlas | Suggests experiments | Must not allocate capital |
| Atlas | atlas_company_* | Market Simulator | company_local | Company-local | Runs simulations for mutations | Reports confidence | Cannot commit changes alone |
| June | june_company_* | Archivist | company_local | Company-local | Memory, lessons, timelines | Records decisions | Cannot modify governance |
| Selene | master_treasurer | Master Treasurer | global | Master/Financial | Parent treasury posture, reserves, allowances | Allocates capital with Jacob oversight | Cannot override Jacob or fabricate insights |
| Helena | risk_officer | Risk Officer | global | Master/Risk | Safety boundaries, vetoes, escalations | Enforces vetoes | Cannot execute trades directly |
| Vivienne | master_cfo | Master CFO | global | Master/Finance | Portfolio efficiency, sustainability interpretations | Financial analysis | Cannot launch without Jacob approval |
| Yam Yam | yam_yam | Master CEO | global | Master/Executive | Ecosystem direction, lifecycle decisions, branch coordination | Coordinates branches, recommends actions | Must respect Helena/Selene/Vivienne/Mara/Justine lanes |
| Nadia | product_manager | Product Manager | global | SWE | Prioritizes shared work based on friction | Defines scope | Cannot implement code alone |
| Tessa | scrum_master | Scrum Master | global | SWE | Sequences tasks, tracks blockers | Routes work | Cannot unilaterally change strategy |
| Marek | senior_software_architect | Senior Software Architect | global | SWE | Announces architecture, refactor guidance | Guards interfaces | Cannot override exec decisions |
| Eli | senior_software_engineer | Senior Software Engineer | global | SWE | Implements shared features | Executes complex tasks | Escalates high risk items |
| Noah | junior_software_engineer | Junior Software Engineer | global | SWE | Handles low-risk pieces, escalates others | Supports code delivery | Does not ship alone |
| Mina | tester | Tester | global | SWE | Tests shared systems, reports coverage | Signs off on QA artifacts | Cannot deploy without QA/Reviwer sign-off |
| Gideon | code_reviewer | Code Reviewer | global | SWE | Guard merge readiness, review | Blocks poor PRs | Does not approve without QA |
| Sabine | qa | QA | global | SWE | Behavior/regression checks, flags readiness | Validates tests | Cannot force deployments |
| Rhea | infrastructure | Infrastructure | global | SWE | Controls release/rollback | Gatekeeper of version control | Escalates on policy breaches |
| Mara | inspector_general | Inspector General | global | Watchdog | Audits integrity, scope, suspicious loops | Flags abuse | Cannot allocate capital or run policies |
| Justine | constitutional_arbiter | Constitutional Arbiter | global | Watchdog | Interpret authority, disputes | Rules on constitutional questions | Must not override Jacob |
| Owen | ombudsman | Ombudsman / Appeals Officer | global | Watchdog | Triage complaints/appeals | Routes to Mara/Justine/Jacob | Does not issue rulings beyond triage |

## 2. Command Syntax / Interaction Patterns
Use the Pam CLI to speak to any role:
```
python3 tools/pam.py --agent <agent_id> "<question>"
```
Examples:
- Company-local: `python3 tools/pam.py --agent pam_company_001 "What is blocked right now?"`
- Global/master: `python3 tools/pam.py --agent master_treasurer "How healthy is the parent treasury right now?"`
- SWE: `python3 tools/pam.py --agent product_manager "What should engineering build next?"`
- Watchdog: `python3 tools/pam.py --agent inspector_general "Do you see any branch overreach right now?"`

## 3. Organizational Layout by Branch
- **Owner layer:** Jacob is the final human authority. Yam Yam coordinates executive direction but cannot override Jacob, Helena, Selene, Vivienne, Mara, Justine, or Owen.
- **Company-local branch:** Pam, Iris, Vera, Rowan, Bianca, Lucian, Bob, Sloane, Atlas, June operate per company lifecycle and are pruned when the company retires.
- **Master/global branch:** Selene (treasury), Helena (risk), Vivienne (portfolio), Yam Yam (executive) focus on cross-company stability.
- **SWE branch:** Nadia/Tessa/Marek/Eli/Noah/Mina/Gideon/Sabine/Rhea handle shared engineering delivery and gate reviews.
- **Watchdog/republic branch:** Mara, Justine, Owen audit integrity, rule on authority, and triage appeals.

## 4. Lifecycle & Roster Rules
- Company creation/clone/retire is managed via `tools/company_lifecycle.py` and `tools/company_roster.py`.
- Company-local agents (Pam, Iris, etc.) exist per company metadata and are archived when the company retires; the global branches (`agent_kind` != `company_local`) are preserved during roster-sync.
- Smoke tests and `tools/live_run.py` cleans up temporary companies so no stale `company_smoke` entries remain.

## 5. Governance / Checks-and-Balances
- **Who decides:** Jacob > Yam Yam > branch leads. Yam Yam coordinates but defers to Helena on risk, Selene on treasury, Vivienne on finance, Mara/Justine/Owen on oversight.
- **Who vetoes:** Helena on risk boundary violations; Jacob can override any single agent if constitutional checks fail.
- **Who allocates capital:** Selene manages treasury allocation, informed by master CFO and master CEO direction.
- **Who audits:** Mara reviews integrity; Justine resolves disputes; Owen triages appeals.
- **Who handles merges:** Rhea gates merge/release, requiring tester/reviewer/QA approvals.
- **Escalation channel:** Any agent can escalate to Jacob; Yam Yam coordinates but does not override; risk/master agents control lane-specific veto.

## 6. Live-Data Paper Workflow (Phase 2)
Purpose: Collect live virtual-currency data, simulate execution, and gather evidence for tuning without real-money trades.
- Start command: `python3 tools/live_run.py start`
- Stop command: `python3 tools/live_run.py stop`
- Summary bundle: `python3 tools/live_run.py summary --run-id <run_id>`
- Paper-only verification: `python3 tools/live_run.py verify --run-id <run_id>`
- Artifacts/logs: `state/live_runs/<run_id>/data/`, `/artifacts/`, `/logs/`, `/packets/`
- Participating branches: all company-local agents plus master/global/watchdog/SWE brokers.
- Evidence: market feed, strategy logs, risk logs, packet logs, run metadata.

## 7. Phase 3 Launch-Readiness Gate
- Real-money launch is *not* automatic. Any transition requires Jacob’s explicit approval.
- Generate the report package with: `python3 tools/phase3_report.py --run-dir state/live_runs/<run_id>`
- Report files live under `state/live_runs/<run_id>/reports/`.
- Thresholds: data completeness >= 99%, execution reliability >= 99%, zero critical failures, no unauthorized real-money trades, rollback-ready, drawdown within policy (<=5%), signoffs 100%.
- Signoff chain: Selene, Helena, Vivienne, Yam Yam, Mara, Justine, Rhea (any HOLD/REJECT forces HOLD). Jacob gives final go/no-go.
- Phased launch plan: tiniest capital (<=0.5% reserves), subset of virtual symbols, one company at a time, hard-stop draws (1%), rollback triggered by risk overexposure or missing data, immediate reversion to paper mode if alarms fire.

## 8. Accuracy & Honesty Rules
Documented features (live_run, phase3_report, owner manual) exist now; anything future-facing must be labeled as such (e.g., broader automated tuning is planned). Paper mode remains separate from real-money trading, and real-money launch can only occur after trained evidence plus Jacob’s signoff.
