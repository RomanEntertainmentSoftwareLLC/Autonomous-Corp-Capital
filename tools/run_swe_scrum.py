from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

ROOT = Path("/opt/openclaw/.openclaw/workspace")
PAM = ROOT / "tools" / "pam.py"
LOG_DIR = ROOT / "logs" / "meetings" / "swe"

SWE_TEAM = [
 ("scrum_master", "Scrum Master"),
 ("product_manager", "Product Manager"),
 ("senior_software_architect", "Senior Software Architect"),
 ("senior_software_engineer", "Senior Software Engineer"),
 ("junior_software_engineer", "Junior Software Engineer"),
 ("tester", "Tester"),
 ("code_reviewer", "Code Reviewer"),
 ("qa", "QA"),
 ("infrastructure", "Infrastructure"),
]

DEFAULT_PROMPT = (
 "You are in a structured SWE scrum meeting for Autonomous Corp Capital. "
 "Give a short update in 3 parts only: "
 "1) what you handled recently, "
 "2) what you are focused on next, "
 "3) blockers or risks. "
 "Keep it concise and role-bound."
)


def run_agent(agent_id: str, message: str, timeout_sec: int = 180) -> Dict[str, str]:
 cmd = ["python3", str(PAM), "--agent", agent_id, message]
 try:
  proc = subprocess.run(
   cmd,
   cwd=str(ROOT),
   capture_output=True,
   text=True,
   timeout=timeout_sec,
  )
 except subprocess.TimeoutExpired:
  return {
   "agent": agent_id,
   "ok": False,
   "stdout": "",
   "stderr": f"Timeout after {timeout_sec}s",
   "reply_text": "",
  }

 stdout = (proc.stdout or "").strip()
 stderr = (proc.stderr or "").strip()

 reply_text = ""
 if stdout:
  try:
   data = json.loads(stdout)
   reply_text = data.get("reply_text", "")
  except Exception:
   reply_text = stdout[:4000]

 return {
  "agent": agent_id,
  "ok": proc.returncode == 0,
  "stdout": stdout,
  "stderr": stderr,
  "reply_text": reply_text,
 }


def build_meeting_record(results: List[Dict[str, str]]) -> Dict[str, object]:
 ts = datetime.now(timezone.utc)
 meeting_id = f"swe_scrum_{ts.strftime('%Y%m%d_%H%M%S')}"
 transcript = []

 for agent_id, role in SWE_TEAM:
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
  "type": "swe_scrum",
  "timestamp": ts.isoformat(),
  "participants": [a for a, _ in SWE_TEAM],
  "summary": "Initial SWE scrum MVP transcript",
  "action_items": action_items,
  "transcript": transcript,
 }


def save_meeting(record: Dict[str, object]) -> Path:
 LOG_DIR.mkdir(parents=True, exist_ok=True)
 out = LOG_DIR / f"{record['meeting_id']}.json"
 out.write_text(json.dumps(record, indent=2), encoding="utf-8")
 return out


def main() -> None:
 results = []
 for agent_id, role in SWE_TEAM:
  message = f"{DEFAULT_PROMPT} Your role is {role}."
  results.append(run_agent(agent_id, message))

 record = build_meeting_record(results)
 out_path = save_meeting(record)

 print(json.dumps({
  "meeting_id": record["meeting_id"],
  "saved_to": str(out_path),
  "participant_count": len(record["participants"]),
  "ok_count": sum(1 for t in record["transcript"] if t["ok"]),
 }, indent=2))


if __name__ == "__main__":
 main()
