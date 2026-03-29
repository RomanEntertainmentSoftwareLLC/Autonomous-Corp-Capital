# RPG Operator Cheat Sheet

## ACTIVE V1 STATS

| Stat | Measures | Think... |
|------|----------|----------|
| **ACC** | First-try correctness | "Did they get it right the first time?" |
| **REL** | Consistency over time | "Do they reliably execute without errors?" |
| **JUD** | Decision quality | "Did they escalate appropriately? Take smart risks?" |

**Speed (SPD):** Dormant in v1. Do not score.

---

## GAIN RULE

### Base XP
- Create file: +5 REL
- Edit file: +8 ACC
- Read file (in task): +2 REL
- Tool success: +3 REL
- Re-read verification: +2 REL
- Log mistake + fix: +5 ACC, +3 JUD
- Add risk notes: +3 JUD
- Appropriate escalation: +5 JUD

### Multipliers
- First-try success: 1.5x
- Complex task (3+ steps): 1.3x
- Self-caught error: 1.2x

### Diminishing Returns (Apply After Multipliers)

| Agent Level | XP Penalty | Example: +10 becomes... |
|-------------|------------|------------------------|
| 1-5 | None | +10 |
| 6-10 | -10% | +9 |
| 11-15 | -20% | +8 |
| 16-20 | -30% | +7 |
| 21-25 | -40% | +6 |
| 26+ | -50% | +5 |

### Formula
```
Final XP = round(Base × Multiplier × LevelPenalty)
```

---

## LOSS RULE

### Full Penalty Always (No Diminishing Returns)

| Failure | XP Loss | Stat |
|---------|---------|------|
| Fake completion | -15 | ACC |
| UNIVERSAL.md violation | -20 | ACC, JUD |
| Overreach (outside authority) | -12 | JUD |
| Invalid tool | -5 | REL |
| Repeated invalid tool | -8 | REL |
| Tool failure | -3 | REL |
| Wrong file edited | -10 | ACC |
| Edit without re-read | -5 | REL |
| Missing proof | -7 | ACC |
| Same mistake twice | -8 | ACC |
| Same mistake three times | -15 | ACC |

### Asymmetric Risk
High-level agents lose more than they gain:
- Level 12: Create file +4, Wrong file -10 = Net -6
- Level 30: Create file +3, Wrong file -10 = Net -7

---

## PROFIT BONUS RULE

### When to Award
- Real live run: ✓
- Exceeds target by 50%+: ✓
- Clean execution (no violations): ✓
- Exceptional, not routine: ✓

### Base Bonus
| Over Target | Bonus |
|-------------|-------|
| 50-75% | +10 to +20 |
| 76-100% | +20 to +35 |
| 101-150% | +35 to +45 |
| 150%+ | +45 to +50 (max) |

### Diminishing Returns on Bonus

| Level | Bonus Multiplier |
|-------|------------------|
| 1-5 | 1.0x (full) |
| 6-10 | 0.75x (-25%) |
| 11-15 | 0.5x (-50%) |
| 16-20 | 0.25x (-75%) |
| 21+ | 0.1x (-90%, min 1) |

### Safety Override
**ANY violation = NO BONUS** (even if target exceeded)

Hierarchy: Survival > Compliance > Safety > Risk > Profit

---

## LEVEL-DOWN RULE

### Trigger
Automatic when:
```
Total XP < Current Level Threshold
```

### Thresholds (First 10 Levels)
| Level | Min XP | XP to Next |
|-------|--------|------------|
| 1 | 0 | 100 |
| 2 | 100 | 150 |
| 3 | 250 | 200 |
| 4 | 450 | 250 |
| 5 | 700 | 300 |
| 6 | 1,000 | 350 |
| 7 | 1,350 | 400 |
| 8 | 1,750 | 450 |
| 9 | 2,200 | 500 |
| 10 | 2,700 | 550 |

### Also Triggers If...
Any stat drops below minimum for current level:
- L5: ACC≥20, REL≥20, JUD≥20
- L10: ACC≥70, REL≥70, JUD≥70

### No Grace Period
Level-down is immediate. No warnings.

---

## DO NOT REWARD

| Activity | Why Not |
|----------|---------|
| **Chatter** | No verifiable outcome |
| **Planning only** | Not runtime execution |
| **Self-generated tasks** | Cannot farm XP |
| **Reading "for curiosity"** | Must lead to action |
| **Vanity edits** | No functional impact |
| **Questions/answers** | No tool use |

### The Test
> "Did this produce a verifiable outcome that I can inspect?"

If no → **0 XP**

---

## QUICK CHECKLIST

Before approving XP:
- [ ] Work was requested (not self-generated)
- [ ] Outcome is verifiable
- [ ] Proof is documented
- [ ] Was runtime execution
- [ ] Calculated base XP
- [ ] Applied multipliers
- [ ] Applied level penalty (for gains only)
- [ ] Rounded to nearest integer
- [ ] No violations occurred

---

Cheat Sheet Version: 2.0
Date: 2026-03-29
