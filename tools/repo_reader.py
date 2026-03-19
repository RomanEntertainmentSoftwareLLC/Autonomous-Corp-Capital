from __future__ import annotations

from pathlib import Path
from typing import List

BASE_PATH = Path("/opt/openclaw/.openclaw/workspace").resolve()

BLOCKED_PARTS = {
 ".git",
 ".venv",
 "__pycache__",
 "state",
}

DEFAULT_MAX_CHARS = 12000
DEFAULT_MAX_RESULTS = 200


def _resolve_safe_path(relative_path: str = "") -> Path:
 target = (BASE_PATH / relative_path).resolve()
 try:
  target.relative_to(BASE_PATH)
 except ValueError as exc:
  raise ValueError(f"Path escapes repo base: {relative_path}") from exc
 return target


def _is_blocked(path: Path) -> bool:
 return any(part in BLOCKED_PARTS for part in path.parts)


def list_files(relative_path: str = "") -> List[str]:
 """
 List visible files/dirs directly under a repo-relative directory.
 Read-only, non-recursive, bounded, and blocked from sensitive dirs.
 """
 target = _resolve_safe_path(relative_path)

 if not target.exists():
  return ["Path does not exist"]

 if not target.is_dir():
  return ["Path is not a directory"]

 if _is_blocked(target):
  return ["Path is blocked"]

 entries = []
 for child in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
  if _is_blocked(child):
   continue
  marker = "/" if child.is_dir() else ""
  entries.append(f"{child.name}{marker}")
  if len(entries) >= DEFAULT_MAX_RESULTS:
   entries.append("... truncated ...")
   break
 return entries


def read_file(relative_path: str, max_chars: int = DEFAULT_MAX_CHARS) -> str:
 """
 Read a repo-relative text file safely with bounded output.
 """
 target = _resolve_safe_path(relative_path)

 if not target.exists():
  return "File does not exist"

 if not target.is_file():
  return "Path is not a file"

 if _is_blocked(target):
  return "Path is blocked"

 try:
  text = target.read_text(encoding="utf-8", errors="replace")
 except Exception as exc:
  return f"Error reading file: {exc}"

 if max_chars < 1:
  max_chars = DEFAULT_MAX_CHARS

 if len(text) > max_chars:
  return text[:max_chars] + "\n... [truncated] ..."
 return text


def read_file_window(relative_path: str, start_line: int = 1, max_lines: int = 200) -> str:
 """
 Read a bounded line window from a repo-relative file.
 """
 target = _resolve_safe_path(relative_path)

 if not target.exists():
  return "File does not exist"

 if not target.is_file():
  return "Path is not a file"

 if _is_blocked(target):
  return "Path is blocked"

 try:
  lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
 except Exception as exc:
  return f"Error reading file: {exc}"

 start_line = max(1, start_line)
 max_lines = max(1, min(max_lines, 500))

 start_idx = start_line - 1
 end_idx = min(len(lines), start_idx + max_lines)

 if start_idx >= len(lines):
  return "Start line is past end of file"

 window = [
  f"{i + 1}: {lines[i]}"
  for i in range(start_idx, end_idx)
 ]
 return "\n".join(window)


def search_in_file(relative_path: str, keyword: str, max_hits: int = 100) -> List[str]:
 """
 Search for a keyword inside a repo-relative file and return bounded line hits.
 """
 target = _resolve_safe_path(relative_path)

 if not target.exists():
  return ["File does not exist"]

 if not target.is_file():
  return ["Path is not a file"]

 if _is_blocked(target):
  return ["Path is blocked"]

 if not keyword:
  return ["Keyword is empty"]

 try:
  lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
 except Exception as exc:
  return [f"Error reading file: {exc}"]

 hits = []
 needle = keyword.lower()
 for idx, line in enumerate(lines, start=1):
  if needle in line.lower():
   hits.append(f"{idx}: {line}")
  if len(hits) >= max_hits:
   hits.append("... truncated ...")
   break

 return hits if hits else ["No matches found"]
