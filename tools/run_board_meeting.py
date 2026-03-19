from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

ROOT = Path("/opt/openclaw/.openclaw/workspace")
PAM = ROOT / "tools" / "pam.py"
LOG_DIR = ROOT / "logs" / "meetings" / "board"

# Phase 1: board speaks first
BOARD = [
 ("master_treasurer", "Master Treasurer"),
 ("risk_officer", "Risk Officer"),
 ("master_cfo", "Master CFO"),
 ("aiar", "AI Agent Resources Director"),
 ("ledger", "Token & Cost Controller"),
 ("lucian_company_001", "CEO"),
 ("lucian_company_002", "CEO"),
 ("lucian_company_003", "CEO"),
 ("lucian_company_004", "CEO"),
]

DEFAULT_PROMPT = (
 "You are in a structured Autonomous Corp Capital board meeting. "
 "Give a concise board update in 3 parts only: "
 "1) current posture in your lane, "
 "2) what decision or caution matters most next, "
 "3) blockers, risks, or evidence gaps. "
 "Stay role-bound. Do not ramble."
)

YAM_YAM_SYNTHESIS_PROMPT = (
 "You are the Master CEO of Autonomous Corp Capital. "
 "You are reviewing the completed board meeting transcript below. "
 "Return a concise executive synthesis in 3 parts only: "
 "1) ecosystem posture, "
 "2) most important next executive decision or caution, "
 "3) blockers, risks, or evidence gaps. "
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


def run_agent(agent_id: str, message: str, timeout_sec: int = 240) -> Dict[str, str]:
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


def run_yam_yam_synthesis(transcript: List[Dict[str, object]], timeout_sec: int = 900) -> Dict[str, object]:
 transcript_blob = []
 for entry in transcript:
  transcript_blob.append(
   f"{entry.get('agent_id')}: ok={entry.get('ok')} | reply={entry.get('reply_text', '')}"
  )

 message = (
  YAM_YAM_SYNTHESIS_PROMPT
  + "\n\nBOARD TRANSCRIPT:\n"
  + "\n".join(transcript_blob)
 )

 result = run_agent("yam_yam", message, timeout_sec=timeout_sec)
 return {
  "agent_id": "yam_yam",
  "role": "Master CEO",
  "ok": bool(result.get("ok")),
  "reply_text": result.get("reply_text", ""),
  "stderr": result.get("stderr", ""),
 }


def build_meeting_record(results: List[Dict[str, str]]) -> Dict[str, object]:
 ts = datetime.now(timezone.utc)
 meeting_id = f"board_meeting_{ts.strftime('%Y%m%d_%H%M%S')}"

 transcript: List[Dict[str, object]] = []
 for agent_id, role in BOARD:
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

 # Phase 2: Yam Yam synthesizes after the board has spoken
 transcript.append(run_yam_yam_synthesis(transcript))

 action_items = []
 for t in transcript:
  if t["reply_text"]:
   action_items.append(
    {
     "owner": t["agent_id"],
     "note": str(t["reply_text"])[:240],
    }
   )

 return {
  "meeting_id": meeting_id,
  "type": "board_meeting",
  "timestamp": ts.isoformat(),
  "participants": [a for a, _ in BOARD] + ["yam_yam"],
  "summary": "Board meeting transcript with post-board Master CEO synthesis",
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
 for agent_id, role in BOARD:
  message = f"{DEFAULT_PROMPT} Your role is {role}."
  results.append(run_agent(agent_id, message))

 record = build_meeting_record(results)
 out_path = save_meeting(record)

 print(
  json.dumps(
   {
    "meeting_id": record["meeting_id"],
    "saved_to": str(out_path),
    "participant_count": len(record["participants"]),
    "ok_count": sum(1 for t in record["transcript"] if t["ok"]),
   },
   indent=2,
  )
 )


if __name__ == "__main__":
 main()
