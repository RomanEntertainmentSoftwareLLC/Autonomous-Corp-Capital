# OpenClaw Systems Manual

## Table of Contents
1. [Overview](#overview)
2. [SWE Task Workflow](#swe-task-workflow)
3. [Strategy & Genome Toolbox](#strategy--genome-toolbox)
4. [Lifecycle & Governance](#lifecycle--governance)
5. [Synthetic Self-Play](#synthetic-self-play)
6. [Warehouse & Analytics](#warehouse--analytics)
7. [Treasury & Economy](#treasury--economy)
8. [Automation Utilities](#automation-utilities)
9. [Generating a PDF](#generating-a-pdf)

---

## Overview
This workspace now contains a comprehensive autonomous trading lab:
- Use `python3 ...` commands (activate your venv first if you rely on python3 aliases).

- **Genome-based strategy evolution** across EMA/RSI/ML/breakout hybrids.
- **Lifecycle governance** with promotions, decline tracking, retirement, and capital allocations.
- **Synthetic self-play tournaments** with optional interaction effects.
- **SWE task framework** (task creation, sandboxing, testing, reviews, approval gate).
- **Warehouse analytics, treasury management, and economy reports**.

Use the sections below as your quick-start reference.

---

## SWE Task Workflow
### Task Format
- Template: `tasks/swe_task_template.yaml` (fields: `task_id`, `title`, `description`, `allowed_files`, `forbidden_files`, `acceptance_criteria`, `test_commands`, `reviewer_notes`).
- Convert backlog items via `tools/backlog_to_task.py tasks/backlog_example.json backlog-101`.

### Sandbox Preparation
```
python3 tools/run_swe_task.py tasks/SWE-001.yaml
```
- Validates required fields, prints allowed/forbidden files, creates a sandbox worktree, logs metadata.

### Testing, Coverage & Review
```
python3 tools/test_swe_task.py tasks/SWE-001.yaml
python3 tools/summarize_patch.py
python3 tools/review_swe_task.py SWE-001
```
- Tests are defined per task. Patch summary shows files + failed commands. Review report notes status/notes.

### Approval & Apply
- Record approval via `tasks/approval_manifest.json` (status: `approved/needs_changes/rejected`).
- Apply only when tests pass and review exists:
```
python3 tools/apply_swe_task.py SWE-001
```

---

## Strategy & Genome Toolbox
### Strategy Plugins
- `tradebot/strategies/` contains EMA, RSI, ML, breakout, hybrid plugins with metadata in `strategies/manifest.py`.
- List strategies: `python3 tools/list_strategies.py`.

### Genomes & Evolution
- Genomes stored at `companies/<name>/genome.yaml` (strategy, indicators, features, models, risk knobs).
- Validate and compile genomes:
```
python3 tools/validate_genome.py company_001
python3 tools/compile_genome.py company_001
```
- Mutate genomes (strategy, indicators, features, models) via `tools/mutate_company.py company_001 --seed 42 --strategy-switch`.
- Evolution workflow:
```
python3 tools/evolve_genome.py company_001 company_005 --strategy-switch --seed 123
```
- The command validates, compiles, updates metadata, and prints a mutation summary.

### Mutation Summary
- `companies/<child>/mutation_summary.json` records the old/new strategy and mutations for traceability.

### Genome Feature/Model Tuning
- `tools/mutate_company.py` toggles indicator flags, adjusts indicator params, flips ML feature flags, switches between logistic/random forest models, and tweaks confidence thresholds.
- Mutations auto-update `genome.yaml` and are recorded in summary logs.

---

## Lifecycle & Governance
### Configs & Metadata
- Lifecycle rules: `config/lifecycle.yaml` (promotion/retirement thresholds, strike counts).
- Company metadata tracks `lifecycle_state`, strikes, promotions, allocation status, etc.

### Evaluator & Summary
```
python3 tools/evaluate_lifecycle.py
python3 tools/lifecycle_summary.py
```
- Updates metadata, writes transition notes, exports JSON if requested.

### Manager Decisions
- Tool `tools/manager_decide.py` outputs strategy-aware recommendations plus capital guidance.
- Board summary includes top/worst companies, clone/retire targets, and allocation hints.
- Allocation notes derived from treasury data (`state/treasury.yaml`).

---

## Synthetic Self-Play
### Market Generator
- `tradebot/sim_market.py`: generates deterministic ticks for regimes (`trending_up`, `ranging`, `high_volatility`, etc.).
- Optional crowding effects: slippage/crowding/spread adjustments.

### Self-Play Runner
```
python3 tools/self_play.py --manifest tools/self_play_manifest.yaml --regime high_volatility --interaction --include-paused
```
- Writes run summary JSON in `results/self_play/` (regime, seed, participants, metrics).
- Mutation-aware lifecycle filters skip retired/archived companies unless `--include-paused` is specified.

### Batch Tournament
```
python3 tools/self_play_batch.py --manifest tools/self_play_manifest.yaml --regimes trending_up ranging high_volatility --iterations 50
```
- Runs same participant set across multiple regimes and prints aggregated fitness metrics.

---

## Warehouse & Analytics
- Manager, leaderboard, and boardroom reports now read from `data/warehouse.sqlite` (with a log file fallback) so the analytics you see are the canonical source of truth.
### Setup
```
python3 tools/init_warehouse.py
python3 tools/ingest_results_to_db.py
```
- Creates `data/warehouse.sqlite` with tables/views (`latest_company_results`, `leaderboard_basis`, `latest_run_summary`).

### Queries
```
python3 tools/query_warehouse.py strategy_performance
python3 tools/query_warehouse.py best_strategy_by_symbol
python3 tools/query_warehouse.py ema_param_profitability
python3 tools/query_warehouse.py mutation_performance
```
- Outputs readable tables for strategy analyses and mutation tracking.

### Leaderboard
```
python3 tools/leaderboard.py --json-output leaderboard.json
```
- Prints fitness/alpha/regime/recommendation + optional JSON export.

### Economy Report
```
python3 tools/economy_report.py
python3 tools/db_status.py
```
- Reports capital, allocations, fitness, and table counts.

---

## Treasury & Economy
### Treasury Files
- `state/treasury.yaml`: total/reserve/allocatable/unallocated capital plus allocations.
- `state/allocation_history.jsonl`: timestamped log of allocation adjustments.

### Allocation Policy
- Configurable via `config/allocation.yaml` (preserve reserve, min/max caps, bonuses, penalties, retired defunding).
- Run allocations:
```
python3 tools/allocate_capital.py
```
- Updates treasury and company metadata with new percentages/amounts and logs history.
- Manager decisions now include capital hints (e.g., `allocate +10% (promoted)`).

---


## Vector Memory Retrieval
- Run a local Qdrant instance (e.g., `docker run --rm -d --name qdrant -p 6333:6333 qdrant/qdrant`).
- Chunk & index files with embeddings in one pass:
```
python3 tools/index_memory.py
```
  This writes `memory/index_chunks.jsonl` plus populates the `memory_chunks` collection in Qdrant using `sentence-transformers/all-MiniLM-L6-v2`.
- Query semantically relevant passages via:
- Build memory-aware prompts with `tools/build_agent_prompt.py` (or import `tools.prompt_builder.MemoryPromptBuilder`) so only the retrieved chunks become part of the user or system instructions.
- Use the Control Center menu option "Build memory-aware prompt" to interactively craft prompts that include the retrieved stretch of context.
- Context retrieval is cached in `state/memory_retrieval_cache.json`, and each prompt use is recorded in `state/memory_usage_log.jsonl` for auditing.

```
python3 tools/query_memory.py "your question"
```
  The tool uses `tradebot/memory_store.py` to call Qdrant first and fall back to the JSONL store if the vector backend is unavailable.
- The abstraction (`tradebot/memory_store.py`) also exposes `query_chunks(...)` for future prompt builder integration so you can inject just the retrieved snippets (with source attribution) into any conversation context.

## Automation Utilities
- Run `python3 tools/smoke_test_platform.py` (add `--skip-trade` to avoid the long backtest) to exercise compile, validation, ingestion, leaderboard, manager, and backlog scripts in one go.
- `tools/scan_repo.py`: scans for TODO/FIXME, missing help text, missing logs, and missing config files.
- Task governance: creation (`tools/run_swe_task.py`), testing (`tools/test_swe_task.py`), patch summary/update (`tools/summarize_patch.py`), review report (`tools/review_swe_task.py`), gatekeeper manifest (`tasks/approval_manifest.json`), and safe apply (`tools/apply_swe_task.py`).
- `tools/backlog_to_task.py` converts backlog JSON to structured task YAML, while `tasks/backlog_example.json` illustrates the format.
- `tools/treasury_report.py` + `tools/lifecycle_summary.py` deepen economy/lifecycle visibility.

---

## Generating a PDF
Use `pandoc` to convert `USAGE.md` to PDF:
```
pandoc USAGE.md -o OpenClaw-Manual.pdf
```
Ensure Pandoc is installed in the environment first. The same markdown can also feed documentation generators or be shared with the team.

---

This manual helps you operate the autonomous refactor stack end-to-end. Let me know if you’d like the PDF produced automatically or want a condensed version for stakeholders.
