# Live Run Process Timeout Fix v2

This patch replaces the failed in-process signal timeout in `scripts/live_run_systemd.py` with a parent/child process supervisor.

## Why

`run_worker()` can block long enough that `ACC_DURATION_HOURS` is not a reliable wall-clock boundary. The previous signal-based timeout was not sufficient in real testing.

## What changed

- `live_run_systemd.py` now starts a supervised child worker process.
- The parent process owns the hard wall-clock timeout.
- If the child exceeds `ACC_DURATION_HOURS * 3600 + ACC_RUN_HARD_TIMEOUT_GRACE_SECONDS`, the parent marks the run `timed_out` and terminates the child process group.
- If the child ignores `SIGTERM`, the parent escalates to `SIGKILL` after `ACC_RUN_TERMINATE_GRACE_SECONDS`.
- The parent remains alive to run warehouse ingest after completion, interruption, failure, or timeout.
- Timestamps are timezone-aware UTC.

## Environment variables

```bash
ACC_DURATION_HOURS=0.005
ACC_RUN_HARD_TIMEOUT_GRACE_SECONDS=15
ACC_RUN_TERMINATE_GRACE_SECONDS=20
ACC_VIRTUAL_CURRENCY=250
```

## Tiny proof test

```bash
cd /opt/openclaw/.openclaw/workspace

PYTHONNOUSERSITE=1 \
ACC_DURATION_HOURS=0.005 \
ACC_RUN_HARD_TIMEOUT_GRACE_SECONDS=15 \
ACC_RUN_TERMINATE_GRACE_SECONDS=10 \
ACC_VIRTUAL_CURRENCY=250 \
python3 scripts/live_run_systemd.py
```

Expected: the command exits by itself around the hard deadline instead of running forever. It may finish normally or time out, but it must not haunt the terminal.
