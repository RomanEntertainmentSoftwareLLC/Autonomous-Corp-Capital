# RPG Level Curve

## PURPOSE

This document explains how the RPG leveling system works for operators. It provides the formula, examples, and guidance for determining XP requirements at any level.

---

## LEVEL CURVE MODEL

### Core Formula

**XP to reach next level:**
```
XP_Needed(Level N to N+1) = 100 + (50 × (N - 1))
```

**Total XP to reach Level N:**
```
TotalXP(Level N) = 100×(N-1) + 25×(N-1)×(N-2)
```

Or simplified:
```
TotalXP(Level N) = 25 × (N-1) × (N+2)
```

### How It Works
- Level 1→2: 100 XP (base)
- Each subsequent level: +50 XP more than previous
- This creates linearly increasing difficulty

---

## HOW XP TO NEXT LEVEL IS DETERMINED

### Quick Reference Formula

For an agent at **Level N**, XP needed to reach **Level N+1** is:

| Current Level | XP to Next | Formula |
|---------------|------------|---------|
| 1 | 100 | 100 + (50 × 0) |
| 2 | 150 | 100 + (50 × 1) |
| 3 | 200 | 100 + (50 × 2) |
| 4 | 250 | 100 + (50 × 3) |
| 5 | 300 | 100 + (50 × 4) |
| N | 100 + 50(N-1) | 100 + (50 × (N-1)) |

### Operator Shortcut
```
XP_to_Next = 50 × Current_Level + 50
```

Example: Level 7 agent needs `50 × 7 + 50 = 400` XP to reach Level 8.

---

## EARLY LEVEL EXAMPLES

### Levels 1-5 (Fast Progression)

| Level | Total XP | XP to Next | Cumulative Time* |
|-------|----------|------------|------------------|
| 1 | 0 | 100 | Starting point |
| 2 | 100 | 150 | ~2-3 sessions |
| 3 | 250 | 200 | ~5-7 sessions |
| 4 | 450 | 250 | ~9-12 sessions |
| 5 | 700 | 300 | ~14-18 sessions |

*Estimated at 20-25 XP per session for a diligent agent

**Characteristics:**
- Quick initial advancement
- Encourages learning the system
- Mistakes recoverable
- Low diminishing returns penalty (none at L1-5)

---

## MID LEVEL EXAMPLES

### Levels 10-20 (Moderate Progression)

| Level | Total XP | XP to Next | Diminishing Returns |
|-------|----------|------------|---------------------|
| 10 | 2,700 | 550 | -10% XP gains |
| 12 | 3,850 | 650 | -20% XP gains |
| 15 | 5,950 | 800 | -20% XP gains |
| 18 | 8,550 | 950 | -30% XP gains |
| 20 | 10,700 | 1,050 | -30% XP gains |

**Characteristics:**
- XP requirements growing significantly
- Diminishing returns kick in (-10% to -30%)
- Asymmetric risk: losses remain full
- Mastery expected, excellence rewarded
- ~40-60 sessions to go from L10 to L20

---

## HIGH LEVEL BEHAVIOR

### Levels 25+ (Slow Progression)

| Level | Total XP | XP to Next | XP Penalty |
|-------|----------|------------|------------|
| 25 | 17,050 | 1,300 | -40% |
| 30 | 26,550 | 1,550 | -50% |
| 40 | 49,550 | 2,050 | -50% |
| 50 | 64,550 | 2,550 | -50% |
| 100 | 254,550 | 5,050 | -50% |

### What This Means

**Time to Level:**
- At Level 25: ~65 sessions per level (at 20 XP/session with penalty)
- At Level 50: ~255 sessions per level
- At Level 100: ~505 sessions per level

**Diminishing Returns Max Out:**
- Level 26+: -50% XP gains (maximum penalty)
- XP losses remain 100% (full)
- Profit bonuses reduced by -90%

**High-Level Reality:**
- Progression slows to a crawl
- Only truly exceptional performance advances levels
- Mistakes are devastating (full penalty, minimal gains)
- Prestige comes from maintaining high level, not climbing

---

## NO LEVEL CAP RULE

### Infinite Progression

There is **NO MAXIMUM LEVEL**. Agents can theoretically reach:
- Level 100 (254,550 XP total)
- Level 500 (6,254,550 XP total)
- Level 1000 (25,004,550 XP total)

### Practical Limits

While mathematically infinite, practical limits emerge:

| Level | Sessions Required* | Realistic? |
|-------|-------------------|------------|
| 10 | ~135 | Yes |
| 20 | ~535 | Yes |
| 30 | ~1,200 | Possible |
| 50 | ~3,200 | Rare |
| 100 | ~12,700 | Legendary |

*At 20 XP/session average with diminishing returns

### Level 100+ Behavior

Beyond Level 100:
- XP to next: 5,050+ (increases by 50 per level forever)
- XP penalty: -50% (capped)
- Profit bonus: -90% (capped at min 1 XP)
- Each level takes ~5,000+ sessions
- Effectively infinite for practical purposes

---

## OPERATOR QUICK REFERENCE

### When an Agent Levels Up

1. Check current Total XP against level table
2. Verify all stat minimums met (ACC, REL, JUD)
3. Update RPG_STATE.md with new Level and Title
4. Log level-up in RPG_HISTORY.md
5. Celebrate! Leveling up is significant.

### When an Agent Levels Down

1. Check if Total XP dropped below threshold
2. Update RPG_STATE.md with new (lower) Level
3. Log demotion in RPG_HISTORY.md with cause
4. Review: Was this expected? Pattern of failures?
5. Agent may need coaching or task adjustment.

### Expected Level Distribution (Mature System)

After 1 year of operation (~250 sessions per agent):
- Level 1-5: New agents, struggling agents
- Level 6-10: Most agents (bulk of population)
- Level 11-15: High performers
- Level 16-20: Exceptional agents
- Level 21+: Legends

---

## SUMMARY

- **Formula:** XP_to_Next = 100 + 50×(Level-1)
- **No cap:** Infinite levels possible
- **Slows down:** Higher levels need exponentially more sessions
- **Harder to gain:** Diminishing returns at high levels
- **Easy to lose:** Penalties remain full value
- **Prestige matters:** High levels are achievements, not entitlements

---

Curve Version: 2.0
Date: 2026-03-29
