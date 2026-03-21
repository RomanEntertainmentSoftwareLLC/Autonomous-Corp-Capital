from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any, Dict

from tools.openclaw_agent_map import resolve_openclaw_agent_id

REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_TIMEOUT = 180
SLOW_AGENT_TIMEOUTS = {
 "main": 420,
 "selene": 300,
 "helena": 300,
 "vivienne": 300,
 "mara": 300,
 "justine": 300,
 "owen": 300,
}

LOCK_RETRY_ATTEMPTS = {
 "main": 4,
}
LOCK_RETRY_SLEEP_SECONDS = {
 "main": 6,
}

def _strip_code_fences(text: str) -> str:
 text = text.strip()
 if text.startswith("```"):
  lines = text.splitlines()
  if lines and lines[0].startswith("```"):
   lines = lines[1:]
  if lines and lines[-1].strip() == "```":
   lines = lines[:-1]
  return "\n".join(lines).strip()
 return text

def _extract_json_object(text: str) -> Dict[str, Any]:
 candidate = _strip_code_fences(text)

 try:
  parsed = json.loads(candidate)
  if isinstance(parsed, dict):
   return parsed
 except Exception:
  pass

 for start in [i for i, ch in enumerate(candidate) if ch == "{"]:
  depth = 0
  in_string = False
  escape = False

  for idx in range(start, len(candidate)):
   ch = candidate[idx]

   if in_string:
    if escape:
     escape = False
    elif ch == "\\":
     escape = True
    elif ch == '"':
     in_string = False
    continue

   if ch == '"':
    in_string = True
   elif ch == "{":
    depth += 1
   elif ch == "}":
    depth -= 1
    if depth == 0:
     blob = candidate[start:idx + 1]
     try:
      parsed = json.loads(blob)
      if isinstance(parsed, dict):
       return parsed
     except Exception:
      break

 raise RuntimeError(f"Could not extract a JSON object from OpenClaw output:\n{candidate}")

def _normalize_result(parsed: Dict[str, Any], prompt: Dict[str, Any]) -> Dict[str, Any]:
 parsed.setdefault("reply_text", "")
 parsed.setdefault("priority", "medium")
 parsed.setdefault(
 "queue_action",
 (prompt.get("structured_output", {}) or {}).get("default_queue_action", "none"),
 )
 parsed.setdefault("packets", [])

 if parsed.get("priority") == "normal":
  parsed["priority"] = "medium"

 return parsed

def _combined_output(stdout: str | None, stderr: str | None) -> str:
 return ((stdout or "") + "\n" + (stderr or "")).strip()

def _looks_like_lock_error(text: str) -> bool:
 lowered = text.lower()
 return "session file locked" in lowered or ".jsonl.lock" in lowered

class OpenClawAdapter:
 def __init__(self, acc_agent_id: str) -> None:
  self.acc_agent_id = acc_agent_id
  self.real_agent_id = resolve_openclaw_agent_id(acc_agent_id)

 def _timeout_seconds(self) -> int:
  return SLOW_AGENT_TIMEOUTS.get(self.real_agent_id, DEFAULT_TIMEOUT)

 def _retry_attempts(self) -> int:
  return LOCK_RETRY_ATTEMPTS.get(self.real_agent_id, 1)

 def _retry_sleep_seconds(self) -> int:
  return LOCK_RETRY_SLEEP_SECONDS.get(self.real_agent_id, 0)

 def _build_message(self, message: str, prompt: Dict[str, Any]) -> str:
  structured = prompt.get("structured_output", {}) or {}
  required_keys = structured.get("required_keys", [])
  default_queue_action = structured.get("default_queue_action", "none")

  payload = {
  "message": message,
  "prompt": prompt,
  }

  instructions = [
  "You are a real OpenClaw agent being invoked by Autonomous Corp Capital.",
  "Return ONLY a valid JSON object.",
  "Do not use markdown fences.",
  "Do not add prose before or after the JSON.",
  f"Required keys: {required_keys}",
  f"Default queue_action if unsure: {default_queue_action}",
  "If a field is unavailable, use an empty string, empty list, empty object, or false as appropriate.",
  "",
  "PAYLOAD:",
  json.dumps(payload, ensure_ascii=False),
  ]
  return "\n".join(instructions)

 def _invoke_once(self, wrapped_message: str, timeout_seconds: int) -> Dict[str, Any]:
  cmd = [
  "openclaw",
  "agent",
  "--agent",
  self.real_agent_id,
  "--message",
  wrapped_message,
  ]

  try:
   result = subprocess.run(
   cmd,
   cwd=REPO_ROOT,
   capture_output=True,
   text=True,
   timeout=timeout_seconds,
   check=False,
   )
  except subprocess.TimeoutExpired as exc:
   partial = _combined_output(exc.stdout, exc.stderr)
   if partial:
    try:
     return _extract_json_object(partial)
    except Exception:
     pass
   raise RuntimeError(
   f"OpenClaw call timed out after {timeout_seconds}s for "
   f"ACC agent '{self.acc_agent_id}' -> '{self.real_agent_id}'"
  ) from exc

  combined = _combined_output(result.stdout, result.stderr)

  # If OpenClaw returned useful JSON despite noise or a nonzero exit, keep it.
  if combined:
   try:
    return _extract_json_object(combined)
   except Exception:
    pass

  if result.returncode != 0:
   raise RuntimeError(
   f"OpenClaw call failed for ACC agent '{self.acc_agent_id}' -> '{self.real_agent_id}'\n"
   f"stdout:\n{result.stdout}\n\nstderr:\n{result.stderr}"
  )

  raise RuntimeError(
   f"OpenClaw call for ACC agent '{self.acc_agent_id}' -> '{self.real_agent_id}' "
   f"returned no parseable JSON."
  )

 def reason(self, message: str, prompt: Dict[str, Any]) -> Dict[str, Any]:
  wrapped_message = self._build_message(message, prompt)
  timeout_seconds = self._timeout_seconds()
  attempts = self._retry_attempts()
  sleep_seconds = self._retry_sleep_seconds()

  last_error: Exception | None = None

  for attempt in range(1, attempts + 1):
   try:
    parsed = self._invoke_once(wrapped_message, timeout_seconds)
    return _normalize_result(parsed, prompt)
   except Exception as exc:
    last_error = exc
    text = str(exc)
    if attempt < attempts and _looks_like_lock_error(text):
     time.sleep(sleep_seconds)
     continue
    raise

  if last_error is not None:
   raise last_error

  raise RuntimeError(
   f"OpenClaw bridge failed unexpectedly for '{self.acc_agent_id}' -> '{self.real_agent_id}'"
  )
