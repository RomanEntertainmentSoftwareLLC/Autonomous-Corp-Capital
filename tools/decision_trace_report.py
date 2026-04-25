#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

ROOT = Path('/opt/openclaw/.openclaw/workspace')
RUNS_DIR = ROOT / 'state' / 'live_runs'
REPORTS_DIR = ROOT / 'reports'


def _latest_run_dir() -> Path:
    runs = [p for p in RUNS_DIR.glob('run_*') if p.is_dir()]
    if not runs:
        raise SystemExit(f'No run folders found under {RUNS_DIR}')
    return max(runs, key=lambda p: p.stat().st_mtime)


def _run_dir_from_arg(run_id: str | None) -> Path:
    if not run_id or run_id == 'latest':
        return _latest_run_dir()
    p = Path(run_id)
    if p.exists():
        return p
    candidate = RUNS_DIR / run_id
    if candidate.exists():
        return candidate
    raise SystemExit(f'Run not found: {run_id}')


def _jsonl(path: Path) -> Iterable[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for raw in path.read_text(encoding='utf-8', errors='replace').splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            row = json.loads(raw)
        except Exception:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _action(row: dict[str, Any]) -> str:
    for key in ('action', 'decision', 'final_decision', 'execution_action'):
        value = row.get(key)
        if value:
            return str(value).upper()
    state = str(row.get('execution_state') or '').lower()
    if state == 'executed':
        return str(row.get('signal') or 'EXECUTED').upper()
    return 'UNKNOWN'


def _trace(row: dict[str, Any]) -> list[dict[str, Any]]:
    trace = row.get('decision_path_trace') or row.get('decision_trace') or []
    if isinstance(trace, list):
        return [x for x in trace if isinstance(x, dict)]
    return []


def _stage_value(stage: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in stage:
            return stage.get(key)
    return None


def summarize(run_dir: Path, max_examples: int = 12) -> dict[str, Any]:
    decisions_path = run_dir / 'artifacts' / 'paper_decisions.jsonl'
    decisions = list(_jsonl(decisions_path))

    action_counts: Counter[str] = Counter()
    stage_counts: Counter[str] = Counter()
    wait_reasons: Counter[str] = Counter()
    symbol_actions: Counter[str] = Counter()
    company_actions: Counter[str] = Counter()
    evidence_winners: Counter[str] = Counter()
    ml_active = 0
    ml_scores = 0
    ml_coverage_values: list[float] = []
    pattern_gate_demotions = 0
    bootstrap_recoveries = 0
    flat_sell_blocks = 0
    margin_failures = 0
    no_trace = 0
    examples: list[dict[str, Any]] = []

    for row in decisions:
        action = _action(row)
        action_counts[action] += 1
        company = str(row.get('company_id') or row.get('company') or 'unknown')
        symbol = str(row.get('symbol') or 'unknown')
        symbol_actions[f'{symbol}:{action}'] += 1
        company_actions[f'{company}:{action}'] += 1

        if row.get('ml_scoring_active'):
            ml_active += 1
        if row.get('ml_signal_score') is not None:
            ml_scores += 1
        try:
            if row.get('ml_feature_coverage') is not None:
                ml_coverage_values.append(float(row.get('ml_feature_coverage') or 0.0))
        except Exception:
            pass
        if row.get('evidence_winner'):
            evidence_winners[str(row.get('evidence_winner')).upper()] += 1
        try:
            if abs(float(row.get('evidence_margin') or 0.0)) < 0.15:
                margin_failures += 1
        except Exception:
            pass

        trace = _trace(row)
        if not trace:
            no_trace += 1
        for stage in trace:
            name = str(stage.get('stage') or 'unknown')
            stage_counts[name] += 1
            lowered = name.lower()
            reason = str(stage.get('reason') or stage.get('outcome') or '').strip()
            if 'pattern' in lowered and str(stage.get('decision_after') or '').upper() == 'WAIT':
                pattern_gate_demotions += 1
            if 'bootstrap' in lowered and bool(stage.get('triggered')):
                bootstrap_recoveries += 1
            if 'flat' in lowered and 'sell' in lowered:
                flat_sell_blocks += 1
            if action in {'WAIT', 'HOLD', 'HOLD_POSITION', 'NOT_INTERESTED', 'UNKNOWN'} and reason:
                wait_reasons[reason[:140]] += 1

        if len(examples) < max_examples:
            examples.append({
                'company': company,
                'symbol': symbol,
                'action': action,
                'decision_path': row.get('decision_path'),
                'evidence_winner': row.get('evidence_winner'),
                'evidence_margin': row.get('evidence_margin'),
                'ml_signal_score': row.get('ml_signal_score'),
                'ml_feature_coverage': row.get('ml_feature_coverage'),
                'trace_summary': row.get('decision_trace_summary'),
            })

    avg_ml_coverage = round(sum(ml_coverage_values) / len(ml_coverage_values), 4) if ml_coverage_values else None
    return {
        'run_id': run_dir.name,
        'decisions_path': str(decisions_path),
        'decision_rows': len(decisions),
        'rows_without_trace': no_trace,
        'action_counts': dict(action_counts),
        'evidence_winners': dict(evidence_winners),
        'ml': {
            'ml_active_rows': ml_active,
            'ml_score_rows': ml_scores,
            'avg_ml_feature_coverage': avg_ml_coverage,
            'coverage_rows': len(ml_coverage_values),
        },
        'trace_stage_counts': dict(stage_counts),
        'pattern_gate_demotions_estimate': pattern_gate_demotions,
        'bootstrap_recoveries_estimate': bootstrap_recoveries,
        'flat_sell_blocks_estimate': flat_sell_blocks,
        'low_margin_rows_estimate': margin_failures,
        'top_wait_or_skip_reasons': dict(wait_reasons.most_common(12)),
        'top_symbol_actions': dict(symbol_actions.most_common(12)),
        'top_company_actions': dict(company_actions.most_common(12)),
        'examples': examples,
    }


def write_report(summary: dict[str, Any]) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / f"decision_trace_report_{summary['run_id']}.txt"
    latest = REPORTS_DIR / 'decision_trace_report_latest.txt'
    lines = [
        'ACC Decision Trace Report',
        '=' * 25,
        f"Run: {summary['run_id']}",
        f"Decision rows: {summary['decision_rows']}",
        f"Rows without trace: {summary['rows_without_trace']}",
        '',
        'Actions:',
    ]
    for key, val in sorted(summary['action_counts'].items()):
        lines.append(f'- {key}: {val}')
    lines += ['', 'ML:',]
    for key, val in summary['ml'].items():
        lines.append(f'- {key}: {val}')
    lines += ['', 'Evidence winners:']
    for key, val in sorted(summary['evidence_winners'].items()):
        lines.append(f'- {key}: {val}')
    lines += [
        '',
        f"Pattern gate demotions estimate: {summary['pattern_gate_demotions_estimate']}",
        f"Bootstrap recoveries estimate: {summary['bootstrap_recoveries_estimate']}",
        f"Flat SELL blocks estimate: {summary['flat_sell_blocks_estimate']}",
        f"Low-margin rows estimate: {summary['low_margin_rows_estimate']}",
        '',
        'Top trace stages:',
    ]
    for key, val in sorted(summary['trace_stage_counts'].items(), key=lambda kv: (-kv[1], kv[0]))[:20]:
        lines.append(f'- {key}: {val}')
    lines += ['', 'Top WAIT/skip reasons:']
    for key, val in summary['top_wait_or_skip_reasons'].items():
        lines.append(f'- {val}x {key}')
    lines += ['', 'Examples:']
    for ex in summary['examples']:
        lines.append(f"- {ex['company']} {ex['symbol']} {ex['action']} | winner={ex['evidence_winner']} margin={ex['evidence_margin']} ml={ex['ml_signal_score']} coverage={ex['ml_feature_coverage']} | trace={ex['trace_summary']}")
    text = '\n'.join(lines).rstrip() + '\n'
    path.write_text(text, encoding='utf-8')
    latest.write_text(text, encoding='utf-8')
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description='Summarize ACC decision_path_trace breadcrumbs for a run.')
    parser.add_argument('--run-id', default='latest', help='Run id, run path, or latest.')
    parser.add_argument('--json', action='store_true', help='Print JSON summary instead of text summary.')
    args = parser.parse_args()
    run_dir = _run_dir_from_arg(args.run_id)
    summary = summarize(run_dir)
    path = write_report(summary)
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        print(path.read_text(encoding='utf-8'))
        print(f'Report saved to: {path}')
        print(f'Latest report saved to: {REPORTS_DIR / "decision_trace_report_latest.txt"}')


if __name__ == '__main__':
    main()
