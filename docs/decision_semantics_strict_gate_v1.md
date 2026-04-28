# Decision Semantics Strict Gate v1

This patch tightens V2 paper trading decision semantics.

## Problem
Recent reports showed executed BUY actions while the weighted evidence winner was WAIT. That means the ranking/selection layer could promote a WAIT candidate into BUY even after the evidence layer preferred caution.

## Changes

- `tools/live_run.py` now only promotes WAIT candidates when there is explicit bullish pattern/3-candle confirmation.
- WAIT candidates with `evidence_winner=WAIT` are blocked from post-ranking promotion.
- Real-OHLC fallback promotion in the selector is removed.
- `tools/live_decision_engine.py` disables real-OHLC bootstrap promotion by default. It can only be restored intentionally with:

```bash
ACC_ALLOW_REAL_OHLC_BOOTSTRAP=1
```

## Expected effect

- Fewer impulsive BUYs.
- Reports should stop showing BUY actions whose evidence winner was WAIT.
- The bot becomes more selective until the broader universe-ranking / 3-candle target engine is implemented.
