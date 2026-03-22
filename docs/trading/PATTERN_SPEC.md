# PATTERN_SPEC.md

Deterministic internal spec for initial live-runtime candle patterns.

## Scope

This is a feature layer, not a trade-trigger engine.
Patterns contribute a bounded secondary score to live ranking.
They do not replace ML, signal logic, Orion, Lucian, or Bianca.

## Candle anatomy primitives

Per candle:
- `open`
- `high`
- `low`
- `close`
- `real_body = abs(close - open)`
- `upper_shadow = high - max(open, close)`
- `lower_shadow = min(open, close) - low`
- `high_low_range = high - low`
- `candle_color = 1 | 0 | -1`
  - `1` bullish (`close > open`)
  - `-1` bearish (`close < open`)
  - `0` doji/flat (`close == open`)
- `real_body_gap_up/down`
- `candle_gap_up/down`

Invalid OHLC is normalized conservatively:
- `high >= max(open, close)`
- `low <= min(open, close)`
- last-three flat/zero-range candles do not produce pattern matches

Candle quality labeling:
- `real_ohlc` = true bar data source
- `pseudo_snapshot_ohlc` = reconstructed from sequential live snapshots; lower confidence by design
- initial live runtime uses `pseudo_snapshot_ohlc` until a real OHLC feed is wired in

## TA-Lib default settings used

- `BodyLong`: avgPeriod 10, factor 1.0, rangeType RealBody
- `BodyShort`: avgPeriod 10, factor 1.0, rangeType RealBody
- `BodyDoji`: avgPeriod 10, factor 0.1, rangeType HighLow
- `ShadowVeryShort`: avgPeriod 10, factor 0.1, rangeType HighLow
- `Near`: avgPeriod 5, factor 0.2, rangeType HighLow
- `Far`: avgPeriod 5, factor 0.6, rangeType HighLow
- `Equal`: avgPeriod 5, factor 0.05, rangeType HighLow
- Morning/Evening Star penetration: `0.3`

Rolling averages use available lookback up to the configured window when full history is not yet present.

## TheStrat bar typing

Relative to the prior candle:
- `1` = inside bar (breaks neither prior high nor prior low)
- `2U` = breaks prior high only
- `2D` = breaks prior low only
- `3` = breaks both prior high and prior low

## Supported patterns

### TheStrat
- `strat_212_bull`
- `strat_212_bear`
- `strat_312_bull`
- `strat_312_bear`
- `strat_22_continuation_bull`
- `strat_22_continuation_bear`
- `strat_22_reversal_bull`
- `strat_22_reversal_bear`
- `strat_122_revstrat_bull`
- `strat_122_revstrat_bear`
- `strat_13_revstrat_bull`
- `strat_13_revstrat_bear`

### Classical three-candle
- `morning_star`
- `evening_star`
- `three_white_soldiers`
- `three_black_crows`
- `three_inside_up`
- `three_inside_down`
- `three_outside_up`
- `three_outside_down`
- `abandoned_baby_bull`
- `abandoned_baby_bear`

## Confirmation rules

A pattern is only trade-usable if at least one confirmation signal is present:
- break of pattern high/low
- supportive ML score
- supportive signal score
- supportive Orion bias/thesis
- volume/volatility confirmation when available

Without confirmation:
- pattern may still be logged
- `pattern_strength` is forced to `0.0`
- `pattern_contribution` is forced to `0.0`

## Ranking integration

- Start weight: `w_pattern = 0.04`
- Contribution formula: `pattern_dir * pattern_strength * w_pattern`
- Hard clamp: `[-0.10, +0.10]`
- Pattern contribution is additive to ranking score only
- No pattern-only execution path

## Output contract

```python
{
  "pattern_flags": dict[str, int],
  "pattern_dir": -1 | 0 | 1,
  "pattern_strength": float,      # [0, 1]
  "pattern_contribution": float,  # tightly clamped secondary ranking effect
  "pattern_confirmation": {
    "satisfied": bool,
    "signals": list[str],
  },
  "pattern_debug": {
    "matched_patterns": list[str],
    "strat_debug": dict,
    "classical_debug": dict,
    "raw_strength": float,
  },
  "matched_context": {
    "symbol": str | None,
    "timeframe": str,
    "candle_source": "real_ohlc" | "pseudo_snapshot_ohlc" | "unknown",
    "candle_confidence": float,
  },
}
```

## Edge-case handling

- fewer than 3 candles => no pattern match
- invalid OHLC => no pattern match
- flat/zero-range candles in the active window => no pattern match
- ambiguous bull vs bear balance => `pattern_dir = 0`
- patterns can coexist; direction is net bullish vs bearish match count
- unsupported missing data should degrade to neutral output, not exceptions
