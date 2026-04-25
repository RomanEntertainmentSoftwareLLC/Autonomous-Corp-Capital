#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import importlib.util
import json
from pathlib import Path
from typing import Any

ROOT = Path('/opt/openclaw/.openclaw/workspace')
RUNS_DIR = ROOT / 'state' / 'live_runs'
REPORTS_DIR = ROOT / 'reports'


def _latest_run_dir() -> Path | None:
    runs = [p for p in RUNS_DIR.glob('run_*') if p.is_dir()]
    return max(runs, key=lambda p: p.stat().st_mtime) if runs else None


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for raw in path.read_text(encoding='utf-8', errors='replace').splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except Exception:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def _literal_list_from_file(path: Path, name: str) -> list[str]:
    if not path.exists():
        return []
    tree = ast.parse(path.read_text(encoding='utf-8', errors='replace'))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    try:
                        value = ast.literal_eval(node.value)
                    except Exception:
                        return []
                    if isinstance(value, list):
                        return [str(x) for x in value]
    return []


def _load_decision_engine_columns() -> list[str]:
    path = ROOT / 'tools' / 'live_decision_engine.py'
    return _literal_list_from_file(path, 'ML_COLUMNS')


def _load_training_columns() -> list[str]:
    path = ROOT / 'tools' / 'train_ml_model.py'
    num = _literal_list_from_file(path, 'NUMERIC_COLUMNS')
    flags = _literal_list_from_file(path, 'PATTERN_FLAGS')
    cols = _literal_list_from_file(path, 'COLUMNS')
    return cols or (num + flags)


def _model_load_status(model_path: Path) -> dict[str, Any]:
    status: dict[str, Any] = {'path': str(model_path), 'exists': model_path.exists(), 'loads': False, 'error': None, 'class': None}
    if not model_path.exists():
        return status
    try:
        import joblib  # type: ignore
        model = joblib.load(model_path)
        status['loads'] = True
        status['class'] = model.__class__.__name__
        if hasattr(model, 'n_features_in_'):
            status['n_features_in'] = int(getattr(model, 'n_features_in_'))
    except Exception as exc:
        status['error'] = repr(exc)
    return status


def summarize(run_id: str = 'latest') -> dict[str, Any]:
    if run_id == 'latest':
        run_dir = _latest_run_dir()
    else:
        candidate = Path(run_id)
        run_dir = candidate if candidate.exists() else RUNS_DIR / run_id
    live_cols = _load_decision_engine_columns()
    train_cols = _load_training_columns()
    model_path = ROOT / 'models' / 'ml_model.pkl'
    model_status = _model_load_status(model_path)

    decision_rows: list[dict[str, Any]] = []
    if run_dir and run_dir.exists():
        decision_rows = _jsonl(run_dir / 'artifacts' / 'paper_decisions.jsonl')
    ml_score_rows = [r for r in decision_rows if r.get('ml_signal_score') is not None]
    coverage_values: list[float] = []
    for row in decision_rows:
        try:
            if row.get('ml_feature_coverage') is not None:
                coverage_values.append(float(row.get('ml_feature_coverage') or 0.0))
        except Exception:
            pass
    active_rows = [r for r in decision_rows if r.get('ml_scoring_active')]
    influenced_rows = [r for r in decision_rows if 'ml' in str(r.get('decision_path') or '').lower() or any(str((t or {}).get('stage') or '').lower().startswith('ml') for t in (r.get('decision_path_trace') or [] if isinstance(r.get('decision_path_trace'), list) else []))]

    return {
        'run_id': run_dir.name if run_dir else None,
        'model': model_status,
        'live_feature_count': len(live_cols),
        'training_feature_count': len(train_cols),
        'live_features': live_cols,
        'training_features': train_cols,
        'features_match_exactly': live_cols == train_cols,
        'missing_from_live': [x for x in train_cols if x not in live_cols],
        'extra_in_live': [x for x in live_cols if x not in train_cols],
        'recent_decisions': {
            'rows': len(decision_rows),
            'ml_score_rows': len(ml_score_rows),
            'ml_active_rows': len(active_rows),
            'ml_influenced_or_traced_rows': len(influenced_rows),
            'avg_feature_coverage': round(sum(coverage_values) / len(coverage_values), 4) if coverage_values else None,
            'coverage_rows': len(coverage_values),
        },
        'verdict': _verdict(live_cols, train_cols, model_status, decision_rows, ml_score_rows, coverage_values),
    }


def _verdict(live_cols: list[str], train_cols: list[str], model_status: dict[str, Any], decision_rows: list[dict[str, Any]], ml_score_rows: list[dict[str, Any]], coverage_values: list[float]) -> str:
    if not model_status.get('exists'):
        return 'blocked_no_model_file'
    if not model_status.get('loads'):
        return 'blocked_model_load_failed'
    if live_cols != train_cols:
        return 'blocked_feature_mismatch'
    if not decision_rows:
        return 'unknown_no_recent_decisions'
    if not ml_score_rows:
        return 'not_live_no_ml_scores_in_recent_decisions'
    if coverage_values and max(coverage_values) <= 0.0:
        return 'not_live_zero_feature_coverage'
    return 'ready_or_active'


def write_report(summary: dict[str, Any]) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / 'ml_readiness_report.txt'
    lines = [
        'ACC ML Readiness Report',
        '=' * 24,
        f"Run: {summary.get('run_id')}",
        f"Verdict: {summary.get('verdict')}",
        '',
        'Model:',
    ]
    for key, value in summary['model'].items():
        lines.append(f'- {key}: {value}')
    lines += [
        '',
        f"Live feature count: {summary['live_feature_count']}",
        f"Training feature count: {summary['training_feature_count']}",
        f"Features match exactly: {summary['features_match_exactly']}",
        f"Missing from live: {summary['missing_from_live']}",
        f"Extra in live: {summary['extra_in_live']}",
        '',
        'Recent decisions:',
    ]
    for key, value in summary['recent_decisions'].items():
        lines.append(f'- {key}: {value}')
    lines += ['', 'Feature order:',]
    lines.append('- live: ' + ', '.join(summary['live_features']))
    lines.append('- train: ' + ', '.join(summary['training_features']))
    text = '\n'.join(lines).rstrip() + '\n'
    path.write_text(text, encoding='utf-8')
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description='Verify ACC ML model, feature alignment, and recent inference coverage.')
    parser.add_argument('--run-id', default='latest', help='Run id, run path, or latest.')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    summary = summarize(args.run_id)
    path = write_report(summary)
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        print(path.read_text(encoding='utf-8'))
        print(f'Report saved to: {path}')


if __name__ == '__main__':
    main()
