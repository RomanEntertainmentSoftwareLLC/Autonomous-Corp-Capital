#!/usr/bin/env python3
"""Simple ML training harness for the trading feature dataset."""

from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

import joblib
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
from sklearn.model_selection import train_test_split

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "ml_dataset.csv"
MODELS_DIR = ROOT / "models"
NUMERIC_COLUMNS = [
    "ema_fast",
    "ema_slow",
    "ema_spread",
    "rsi",
    "price_change_1",
    "price_change_2",
    "price_change_3",
    "momentum_3",
    "slope_3",
]
PATTERN_FLAGS = [
    "pattern_three_rising",
    "pattern_three_falling",
    "pattern_reversal_after_two_decline",
    "pattern_reversal_after_two_rise",
    "pattern_short_momentum_burst",
    "pattern_short_exhaustion",
    "higher_highs",
    "higher_lows",
    "lower_highs",
    "lower_lows",
]
COLUMNS = NUMERIC_COLUMNS + PATTERN_FLAGS


def load_dataset(path: Path, label: str) -> List[Dict[str, Any]]:
    rows = []
    with open(path, "r", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for record in reader:
            value = record.get(label)
            if value is None or value == "":
                continue
            rows.append(record)
    return rows


def featurize(records: List[Dict[str, Any]], label: str) -> (List[List[float]], List[int]):
    X = []
    y = []
    for record in records:
        features = []
        for col in NUMERIC_COLUMNS:
            val = record.get(col)
            try:
                features.append(float(val) if val not in (None, "") else 0.0)
            except ValueError:
                features.append(0.0)
        for flag in PATTERN_FLAGS:
            features.append(1.0 if record.get(flag) in ("True", "true", True) else 0.0)
        X.append(features)
        y.append(int(record[label]))
    return X, y


def train_model(X: List[List[float]], y: List[int], model_path: Path) -> None:
    clf = RandomForestClassifier(n_estimators=100, random_state=42)
    clf.fit(X, y)
    joblib.dump(clf, model_path)
    return clf


def report_metrics(clf, X_test, y_test) -> None:
    preds = clf.predict(X_test)
    acc = accuracy_score(y_test, preds)
    print(f"Accuracy: {acc:.4f}")
    print("Class balance:", dict(Counter(y_test)))
    print("Confusion matrix:")
    print(confusion_matrix(y_test, preds))
    print("Classification report:")
    print(classification_report(y_test, preds))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train an ML model from the prepared dataset")
    parser.add_argument("--label", default="future_direction_5_ticks")
    parser.add_argument("--dataset", type=Path, default=DATA_FILE)
    parser.add_argument("--output", type=Path, default=MODELS_DIR / "ml_model.pkl")
    args = parser.parse_args()

    if not args.dataset.exists():
        print("Dataset not found. Run build_ml_dataset.py first.")
        sys.exit(1)

    records = load_dataset(args.dataset, args.label)
    if not records:
        print("No data available after filtering.")
        sys.exit(1)

    X, y = featurize(records, args.label)
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    clf = train_model(X_train, y_train, args.output)
    report_metrics(clf, X_test, y_test)
    print(f"Model saved to {args.output}")
