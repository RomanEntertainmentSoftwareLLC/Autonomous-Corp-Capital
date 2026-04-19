from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
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

def _bridge_search_path() -> str:
 env_path = os.environ.get("PATH", "")
 preferred = [
  str(Path.home() / ".npm-global" / "bin"),
  str(Path.home() / ".local" / "bin"),
  str(Path(sys.executable).resolve().parent),
  str(REPO_ROOT / ".venv" / "bin"),
  "/usr/local/bin",
  "/usr/bin",
  "/bin",
 ]
 parts = []
 for entry in preferred + env_path.split(os.pathsep):
  if not entry:
   continue
  if entry not in parts:
   parts.append(entry)
 return os.pathsep.join(parts)


def _resolve_openclaw_command() -> list[str]:
 override = os.environ.get("OPENCLAW_BIN", "").strip()
 if override:
  return [override]

 hardcoded = str(Path.home() / ".npm-global" / "bin" / "openclaw")
 if Path(hardcoded).exists():
  return [hardcoded]

 resolved = shutil.which("openclaw", path=_bridge_search_path())
 if resolved:
  return [resolved]

 raise RuntimeError(
  "Could not resolve the 'openclaw' executable for bridge calls. "
  "Set OPENCLAW_BIN to the full binary path or fix PATH. "
  f"Bridge search PATH was: {_bridge_search_path()}"
 )


def _bridge_env() -> Dict[str, str]:
 env = dict(os.environ)
 env["PATH"] = _bridge_search_path()
 if not env.get("OPENCLAW_HOME"):
  repo_parent = REPO_ROOT.parent
  if repo_parent.name == ".openclaw":
   env["OPENCLAW_HOME"] = str(repo_parent.parent)
 return env

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

def _append_jsonl(path: Path, payload: Dict[str, Any]) -> None:
 path.parent.mkdir(parents=True, exist_ok=True)
 with path.open("a", encoding="utf-8") as fh:
  fh.write(json.dumps(payload) + "\n")


def _append_usage_telemetry(
    acc_agent_id: str,
    real_agent_id: str,
    prompt: Dict[str, Any],
    outcome: str,
    bridge_error: str | None = None,
    bridge_command: list[str] | None = None,
) -> None:
    target_scope = prompt.get("target_scope")
    company = target_scope if isinstance(target_scope, str) and target_scope.startswith("company_") else None
    run_id = prompt.get("run_id") or os.environ.get("ACC_RUN_ID")

    telemetry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent": prompt.get("agent_id") or acc_agent_id,
        "company": company,
        "run_id": run_id,
        "cycle": prompt.get("cycle"),
        "model": f"openclaw_agent:{real_agent_id}",
        "provider": "openclaw_bridge",
        "prompt_tokens": None,
        "completion_tokens": None,
        "total_tokens": None,
        "estimated_cost": None,
        "outcome": outcome,
    }

    if bridge_error is not None:
        telemetry["bridge_error"] = bridge_error

    if bridge_command is not None:
        telemetry["bridge_command"] = bridge_command

    usage_path = REPO_ROOT / "state" / "agents" / "ledger" / "usage.jsonl"
    _append_jsonl(usage_path, telemetry)

    if isinstance(run_id, str) and run_id:
        run_ledger_path = REPO_ROOT / "state" / "live_runs" / run_id / "artifacts" / "ledger_usage.jsonl"
        _append_jsonl(run_ledger_path, telemetry)

        run_usage_path = REPO_ROOT / "state" / "live_runs" / run_id / "artifacts" / "bridge_usage.jsonl"
        _append_jsonl(run_usage_path, telemetry)

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
  bridge_base_cmd = _resolve_openclaw_command()
  cmd = bridge_base_cmd + [
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
   env=_bridge_env(),
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
  _append_usage_telemetry(
      self.acc_agent_id,
      self.real_agent_id,
      prompt,
      "entered_bridge",
      bridge_command=None,
  )
  wrapped_message = self._build_message(message, prompt)
  timeout_seconds = self._timeout_seconds()
  attempts = self._retry_attempts()
  sleep_seconds = self._retry_sleep_seconds()

  last_error: Exception | None = None
  bridge_command_for_log: list[str] | None = None

  try:
   bridge_command_for_log = _resolve_openclaw_command()
  except Exception as exc:
   text = str(exc)
   _append_usage_telemetry(
    self.acc_agent_id,
    self.real_agent_id,
    prompt,
    "error",
    bridge_error=text,
    bridge_command=None,
   )
   raise

  for attempt in range(1, attempts + 1):
   try:
    parsed = self._invoke_once(wrapped_message, timeout_seconds)
    _append_usage_telemetry(
     self.acc_agent_id,
     self.real_agent_id,
     prompt,
     "success",
     bridge_command=bridge_command_for_log,
    )
    return _normalize_result(parsed, prompt)
   except Exception as exc:
    last_error = exc
    text = str(exc)
    if attempt < attempts and _looks_like_lock_error(text):
     time.sleep(sleep_seconds)
     continue
    _append_usage_telemetry(
     self.acc_agent_id,
     self.real_agent_id,
     prompt,
     "error",
     bridge_error=text,
     bridge_command=bridge_command_for_log,
    )
    raise

  if last_error is not None:
   raise last_error

  raise RuntimeError(
   f"OpenClaw bridge failed unexpectedly for '{self.acc_agent_id}' -> '{self.real_agent_id}'"
  )
