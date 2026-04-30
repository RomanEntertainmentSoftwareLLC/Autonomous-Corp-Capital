# ACC V3-A Regime + Market Posture Contract

## Purpose

V3-A adds a deterministic market-awareness layer to ACC.

The goal is not to make the bot trade more often. The goal is to make ACC better at understanding when the market is favorable, hostile, noisy, selective, or unknown.

V3-A should help ACC answer:

- What kind of market are we in?
- Should we prefer cash / WAIT?
- Are BTC and ETH confirming the broader move?
- Is the universe broadly red, broadly green, mixed, or shocked?
- Which symbols are worth watching first?
- Why did ACC wait?

## Non-negotiable boundaries

V3-A Batch 1 is report/skeleton only.

It must not:

- place trades
- change BUY / SELL / WAIT behavior
- call agents
- call OpenClaw
- call Hermes
- call paid LLMs
- mutate portfolios
- mutate company state
- bypass V2 gates
- affect --live-trade behavior

## Core data objects

### market_regime

Allowed initial values:

- unknown
- uptrend
- downtrend
- sideways_chop
- broad_red_market
- mixed_selective
- volatility_shock

Future values may include:

- risk_on_rotation
- fake_pump_environment
- low_liquidity_disorderly

### risk_posture

Allowed initial values:

- observe
- wait
- restricted
- defensive
- selective_long

### best_posture

Operator-facing recommendation derived from market_regime:

- observe
- wait_for_confirmation
- defensive_wait
- selective_long
- wait_or_reduce

### wait_reason

Initial planned values:

- WAIT_NO_EDGE
- WAIT_NEEDS_CONFIRMATION
- WAIT_MARKET_CONTEXT_UNKNOWN
- WAIT_MARKET_HOSTILE
- WAIT_CAPITAL_OR_SLOT_LIMIT
- WAIT_ALREADY_FLAT
- WAIT_DATA_QUALITY_BAD

Batch 1 does not wire wait_reason into runtime. Later batches may add these fields to candidate rows.

### universe_rank_score

A deterministic score used for explainable symbol/candidate ranking.

Initial score components:

- policy signal strength
- ML signal strength
- model confidence distance from neutral
- pattern contribution
- Orion bias if present
- volatility penalty
- risk penalty

The ranker must explain the score with reasons.

## Intended runtime path later

Later V3-A batches may attach these fields to candidate_decisions.jsonl:

- market_regime
- risk_posture
- best_posture
- universe_rank
- universe_rank_score
- wait_reason
- wait_reason_detail

## Broad red market rule later

Later, after tests, broad_red_market may become a soft safety gate:

- New BUY entries may be demoted to WAIT_MARKET_HOSTILE.
- Existing positions may still be held or sold.
- SELL should not be blocked merely because the market is hostile.
- Unknown data should produce caution, not crashes.

## Testing doctrine

Every V3-A behavior must be covered by deterministic tests before runtime wiring.

Initial tests:

- market regime classification
- market weather summary
- universe ranking order
- empty/unknown input behavior
- broad red market detection
- uptrend detection
- sideways chop detection

## Operator doctrine

V3-A is the first market-awareness organ.

It is not a replacement for:

- Helena risk limits
- Selene treasury discipline
- Ledger cost controls
- V2 gates
- ML readiness
- human review
- future live-trade safety gates
