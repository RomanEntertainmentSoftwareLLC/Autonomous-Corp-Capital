# CHANGE_HISTORY

## Entry Template
- Timestamp:
- Agent:
- Role:
- Target File:
- Intended Change:
- Proof Snippet:
- Risk Notes:
- Status:

## History
- Timestamp: 2026-04-12T05:56:00-04:00
  - Agent: Hermes
  - Role: executive cognition
  - Target File: /opt/openclaw/.openclaw/workspace/tools/live_run.py
  - Intended Change: Stop path now verifies the worker PID actually dies, and escalates with SIGKILL if the process group exits but the worker survives.
  - Proof Snippet: if _pid_is_alive(worker_pid): ... os.kill(worker_pid, signal.SIGKILL) ... if not _wait_for_pid_exit(worker_pid, 5.0): raise SystemExit(...)
  - Risk Notes: Paper mode unchanged; safe-stop path now requires real worker death before claiming success.
  - Status: CHANGED
- Timestamp: 2026-04-12T05:01:00-04:00
  - Agent: Hermes
  - Role: executive cognition
  - Target File: /opt/openclaw/.openclaw/workspace/tools/live_run.py
  - Intended Change: Loosen WAIT promotion so flat candidates with positive ranking_score and at least one aligned evidence source can become BUY/SELL more often.
  - Proof Snippet: if not evidence_votes: return False; if not any(direction == signal_dir for direction in evidence_votes): return False
  - Risk Notes: Zero-score and empty-evidence candidates still block; owned positions still remain HOLD_POSITION.
  - Status: CHANGED
