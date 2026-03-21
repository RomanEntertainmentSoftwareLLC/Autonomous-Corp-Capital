#!/usr/bin/env bash
set -u -o pipefail

# Batch-set session thinking levels for ACC/OpenClaw agents.
# Uses live OpenClaw agent IDs from `openclaw agents list`.
#
# Dry-run:
#   DRY_RUN=1 bash set_acc_thinking.sh
# Real run (fastest practical version):
#   VERIFY=0 bash set_acc_thinking.sh
#
# Notes:
# - This uses directive-only messages (/think:<level>) because that is what Jacob explicitly wants.
# - VERIFY defaults to 0 here because /think reporting is not reliable on this install and doubles runtime.
# - All responses are logged to logs/thinking-rollout/.

DRY_RUN="${DRY_RUN:-0}"
VERIFY="${VERIFY:-0}"
TIMEOUT="${TIMEOUT:-180}"
ROOT="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="${ROOT}/logs/thinking-rollout"
mkdir -p "$LOG_DIR"
STAMP="$(date -u +%Y%m%d_%H%M%S)"
LOG_FILE="${LOG_DIR}/thinking_rollout_${STAMP}.log"
JSONL_FILE="${LOG_DIR}/thinking_rollout_${STAMP}.jsonl"
SUMMARY_FILE="${LOG_DIR}/thinking_rollout_${STAMP}_summary.txt"

ok_count=0
fail_count=0
verify_fail_count=0

declare -a failures=()
declare -a verify_failures=()

log() {
  printf '%s\n' "$*" | tee -a "$LOG_FILE"
}

run_agent_msg() {
  local agent_id="$1"
  local msg="$2"
  log
  log "=== ${agent_id} :: ${msg} ==="
  if [[ "$DRY_RUN" == "1" ]]; then
    log "[dry-run] openclaw agent --agent ${agent_id} --message ${msg@Q} --json --timeout ${TIMEOUT}"
    return 0
  fi

  local out
  if out=$(openclaw agent --agent "$agent_id" --message "$msg" --json --timeout "$TIMEOUT" 2>&1); then
    printf '%s\n' "$out" >> "$JSONL_FILE"
    log "$out"
    return 0
  else
    local rc=$?
    printf '%s\n' "$out" >> "$JSONL_FILE"
    log "$out"
    log "[error] exit=${rc} agent=${agent_id} msg=${msg}"
    return "$rc"
  fi
}

set_level() {
  local agent_id="$1"
  local level="$2"
  if run_agent_msg "$agent_id" "/think:${level}"; then
    ((ok_count+=1))
  else
    ((fail_count+=1))
    failures+=("${agent_id}:/think:${level}")
  fi

  if [[ "$VERIFY" == "1" ]]; then
    if ! run_agent_msg "$agent_id" "/think"; then
      ((verify_fail_count+=1))
      verify_failures+=("${agent_id}:/think")
    fi
  fi
}

declare -A THINK=()

# ---- Watchdog / republic branch ----
THINK["justine"]="high"
THINK["mara"]="high"
THINK["owen"]="medium"

# ---- Master / global branch ----
THINK["main"]="high"
THINK["selene"]="high"
THINK["helena"]="high"
THINK["vivienne"]="high"
THINK["ariadne"]="high"
THINK["ledger"]="high"

# ---- SWE branch ----
THINK["nadia"]="medium"
THINK["tessa"]="low"
THINK["marek"]="high"
THINK["eli"]="high"
THINK["noah"]="low"
THINK["mina"]="low"
THINK["gideon"]="low"
THINK["sabine"]="low"
THINK["rhea"]="high"

# ---- Company-local roles (all 4 companies) ----
for n in 001 002 003 004; do
  THINK["pam_company_${n}"]="low"
  THINK["iris_company_${n}"]="medium"
  THINK["vera_company_${n}"]="medium"
  THINK["rowan_company_${n}"]="low"
  THINK["bianca_company_${n}"]="medium"
  THINK["lucian_company_${n}"]="high"
  THINK["bob_company_${n}"]="low"
  THINK["sloane_company_${n}"]="medium"
  THINK["atlas_company_${n}"]="medium"
  THINK["june_company_${n}"]="low"
  THINK["orion_company_${n}"]="high"
done

ORDER=(
  justine mara owen
  main selene helena vivienne ariadne ledger
  nadia tessa marek eli noah mina gideon sabine rhea
  pam_company_001 iris_company_001 vera_company_001 rowan_company_001 bianca_company_001 lucian_company_001 bob_company_001 sloane_company_001 atlas_company_001 june_company_001 orion_company_001
  pam_company_002 iris_company_002 vera_company_002 rowan_company_002 bianca_company_002 lucian_company_002 bob_company_002 sloane_company_002 atlas_company_002 june_company_002 orion_company_002
  pam_company_003 iris_company_003 vera_company_003 rowan_company_003 bianca_company_003 lucian_company_003 bob_company_003 sloane_company_003 atlas_company_003 june_company_003 orion_company_003
  pam_company_004 iris_company_004 vera_company_004 rowan_company_004 bianca_company_004 lucian_company_004 bob_company_004 sloane_company_004 atlas_company_004 june_company_004 orion_company_004
)

log "thinking rollout stamp=${STAMP} dry_run=${DRY_RUN} verify=${VERIFY} timeout=${TIMEOUT}"
log "log_file=${LOG_FILE}"
log "jsonl_file=${JSONL_FILE}"
log "summary_file=${SUMMARY_FILE}"

for agent_id in "${ORDER[@]}"; do
  if [[ -z "${THINK[$agent_id]:-}" ]]; then
    ((fail_count+=1))
    failures+=("${agent_id}:missing-level")
    log "[error] missing thinking level for ${agent_id}"
    continue
  fi
  set_level "$agent_id" "${THINK[$agent_id]}"
done

{
  echo "stamp=${STAMP}"
  echo "dry_run=${DRY_RUN}"
  echo "verify=${VERIFY}"
  echo "timeout=${TIMEOUT}"
  echo "ok_count=${ok_count}"
  echo "fail_count=${fail_count}"
  echo "verify_fail_count=${verify_fail_count}"
  echo
  echo "failures:"
  if [[ ${#failures[@]} -eq 0 ]]; then
    echo "(none)"
  else
    printf '%s\n' "${failures[@]}"
  fi
  echo
  echo "verify_failures:"
  if [[ ${#verify_failures[@]} -eq 0 ]]; then
    echo "(none)"
  else
    printf '%s\n' "${verify_failures[@]}"
  fi
} | tee "$SUMMARY_FILE"

log
log "Done."
