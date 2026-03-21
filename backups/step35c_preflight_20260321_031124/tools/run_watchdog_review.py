from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

ROOT = Path("/opt/openclaw/.openclaw/workspace")
PAM = ROOT / "tools" / "pam.py"
BOARD_LOG_DIR = ROOT / "logs" / "meetings" / "board"
WATCHDOG_LOG_DIR = ROOT / "logs" / "meetings" / "watchdog"

WATCHDOGS = [
 ("mara", "Inspector General"),
 ("justine", "Constitutional Arbiter"),
 ("owen", "Ombudsman / Appeals Officer"),
]

DEFAULT_PROMPT = (
 "You are reviewing the completed Autonomous Corp Capital board meeting transcript. "
 "Return a concise oversight review in 3 parts only: "
 "1) your main finding in your lane, "
 "2) the most important next caution or action, "
 "3) evidence gaps, procedural concerns, or fairness concerns. "
 "Stay role-bound. Do not ramble."
)


def _extract_reply_text(raw: str) -> str:
 raw = (raw or "").strip()
 if not raw:
  return ""
 try:
  data = json.loads(raw)
  return data.get("reply_text", "")
 except Exception:
  start = raw.find("{")
  end = raw.rfind("}")
  if start != -1 and end != -1 and end > start:
   candidate = raw[start : end + 1]
   try:
    data = json.loads(candidate)
    return data.get("reply_text", "")
   except Exception:
    pass
  return raw[:4000]


def run_agent(agent_id: str, message: str, timeout_sec: int = 300) -> Dict[str, str]:
 cmd = ["python3", str(PAM), "--agent", agent_id, message]
 try:
  proc = subprocess.run(
   cmd,
   cwd=str(ROOT),
   capture_output=True,
   text=True,
   timeout=timeout_sec,
  )
  stdout = (proc.stdout or "").strip()
  stderr = (proc.stderr or "").strip()
  reply_text = _extract_reply_text(stdout)
  return {
   "agent": agent_id,
   "ok": proc.returncode == 0,
   "stdout": stdout,
   "stderr": stderr,
   "reply_text": reply_text,
  }
 except subprocess.TimeoutExpired as exc:
  if isinstance(exc.stdout, bytes):
   stdout = exc.stdout.decode("utf-8", errors="replace").strip()
  else:
   stdout = (exc.stdout or "").strip()

  if isinstance(exc.stderr, bytes):
   stderr = exc.stderr.decode("utf-8", errors="replace").strip()
  else:
   stderr = (exc.stderr or "").strip()

  reply_text = _extract_reply_text(stdout)
  return {
   "agent": agent_id,
   "ok": bool(reply_text),
   "stdout": stdout,
   "stderr": ((stderr + f" | Timeout after {timeout_sec}s").strip(" |")),
   "reply_text": reply_text,
  }


def load_newest_board_log() -> Dict[str, object]:
 files = sorted(BOARD_LOG_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
 if not files:
  raise FileNotFoundError("No board meeting logs found")
 newest = files[0]
 data = json.loads(newest.read_text(encoding="utf-8"))
 data["_source_path"] = str(newest)
 return data


def build_board_transcript_blob(board_data: Dict[str, object]) -> str:
 lines: List[str] = []
 for entry in board_data.get("transcript", []):
  agent_id = entry.get("agent_id", "")
  ok = entry.get("ok", False)
  reply_text = entry.get("reply_text", "")
  lines.append(f"{agent_id}: ok={ok} | reply={reply_text}")
 return "\n".join(lines)


def build_watchdog_record(board_data: Dict[str, object], results: List[Dict[str, str]]) -> Dict[str, object]:
 ts = datetime.now(timezone.utc)
 meeting_id = f"watchdog_review_{ts.strftime('%Y%m%d_%H%M%S')}"
 transcript = []

 for agent_id, role in WATCHDOGS:
  result = next((r for r in results if r["agent"] == agent_id), None)
  transcript.append(
   {
    "agent_id": agent_id,
    "role": role,
    "ok": bool(result and result["ok"]),
    "reply_text": (result or {}).get("reply_text", ""),
    "stderr": (result or {}).get("stderr", ""),
   }
  )

 action_items = []
 for t in transcript:
  if t["reply_text"]:
   action_items.append(
    {
     "owner": t["agent_id"],
     "note": t["reply_text"][:240],
    }
   )

 return {
  "meeting_id": meeting_id,
  "type": "watchdog_review",
  "timestamp": ts.isoformat(),
  "source_board_meeting_id": board_data.get("meeting_id", ""),
  "source_board_log": board_data.get("_source_path", ""),
  "participants": [a for a, _ in WATCHDOGS],
  "summary": "Watchdog review of the latest board meeting transcript",
  "action_items": action_items,
  "transcript": transcript,
 }


def save_watchdog_record(record: Dict[str, object]) -> Path:
 WATCHDOG_LOG_DIR.mkdir(parents=True, exist_ok=True)
 out = WATCHDOG_LOG_DIR / f"{record['meeting_id']}.json"
 out.write_text(json.dumps(record, indent=2), encoding="utf-8")
 return out


def main() -> None:
 board_data = load_newest_board_log()
 transcript_blob = build_board_transcript_blob(board_data)

 results = []
 for agent_id, role in WATCHDOGS:
  message = (
   DEFAULT_PROMPT
   + "\n\nBOARD TRANSCRIPT:\n"
   + transcript_blob
   + f"\n\nYour role is {role}."
  )
  results.append(run_agent(agent_id, message))

 record = build_watchdog_record(board_data, results)
 out_path = save_watchdog_record(record)

 print(
  json.dumps(
   {
    "meeting_id": record["meeting_id"],
    "saved_to": str(out_path),
    "source_board_meeting_id": record["source_board_meeting_id"],
    "participant_count": len(record["participants"]),
    "ok_count": sum(1 for t in record["transcript"] if t["ok"]),
   },
   indent=2,
  )
 )


if __name__ == "__main__":
 main()
