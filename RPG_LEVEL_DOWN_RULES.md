# RPG Level-Down Rules

## PURPOSE

Define when and how agents lose XP and levels. Level-down is not a punishment—it is a reflection of current capability. High performance earns levels; sustained problems lose them.

---

## WHEN XP LOSS HAPPENS

### Sources of XP Loss

XP is lost when agents fail to meet standards:

| Failure Type | XP Loss | Stat |
|--------------|---------|------|
| Fake completion (no proof) | -15 | ACC |
| UNIVERSAL.md violation | -20 | ACC, JUD |
| Overreach (outside authority) | -12 | JUD |
| Invalid tool name | -5 | REL |
| Repeated same invalid tool | -8 | REL |
| Tool call failure | -3 | REL |
| Wrong file edited | -10 | ACC |
| Edit without re-read | -5 | REL |
| Missing proof | -7 | ACC |
| Same mistake twice | -8 | ACC |
| Same mistake three times | -15 | ACC |

### Full Penalty Always Applies

**XP losses are never reduced by level.** A Level 50 agent loses the same XP for a mistake as a Level 1 agent.

| Level | Create File (Gain) | Wrong File (Loss) | Asymmetric Risk |
|-------|-------------------|-------------------|-----------------|
| 1 | +5 | -10 | Net -5 |
| 10 | +4 (-20%) | -10 (full) | Net -6 |
| 20 | +3 (-40%) | -10 (full) | Net -7 |
| 50 | +2 (-60%) | -10 (full) | Net -8 |

### Accumulation Over Time

Small penalties add up:
- One -5 REL: Minor setback
- Five -5 REL: -25 total, significant impact
- Ten -5 REL: -50 total, potential level-down

---

## WHEN LEVEL-DOWN HAPPENS

### The Threshold Rule

Level-down occurs **immediately** when:
```
Total XP < Minimum XP for Current Level
```

No warnings. No grace period. No appeals.

### Current Thresholds (First 10 Levels)

| Level | Minimum XP | XP to Drop to Previous |
|-------|------------|------------------------|
| 2 | 100 | Drop to L1 if < 100 |
| 3 | 250 | Drop to L2 if < 250 |
| 4 | 450 | Drop to L3 if < 450 |
| 5 | 700 | Drop to L4 if < 700 |
| 6 | 1,000 | Drop to L5 if < 1,000 |
| 7 | 1,350 | Drop to L6 if < 1,350 |
| 8 | 1,750 | Drop to L7 if < 1,750 |
| 9 | 2,200 | Drop to L8 if < 2,200 |
| 10 | 2,700 | Drop to L9 if < 2,700 |

### Level-Down Chain

If an agent drops multiple levels in one penalty (rare but possible):

**Example:** Level 5 agent with 710 XP
- Major violation: -30 XP
- New total: 680 XP
- Level 5 requires 700 XP minimum
- Level 4 requires 450 XP minimum
- **Result:** Drops to Level 4 (not Level 1)

The agent lands at the highest level they still qualify for.

### Stat Minimum Violations

Level-down also occurs if **any** stat drops below the minimum for current level:

| Level | ACC Min | REL Min | JUD Min |
|-------|---------|---------|---------|
| 5 | 20 | 20 | 20 |
| 10 | 70 | 70 | 70 |

**Example:** Level 10 agent has 2,800 XP (qualifies) but ACC drops to 65 (below 70).
- **Result:** Level-down to Level 9 (or lower if ACC continues to drop)

---

## WHY HIGH-LEVEL AGENTS CAN STILL FALL

### No Protection for Seniority

**High level is not a shield.** It is a badge of trust that can be lost.

| Myth | Reality |
|------|---------|
| "Level 20 agents are safe" | False. One major violation can drop them multiple levels |
| "Past performance protects future mistakes" | False. Each run is judged independently |
| "High level = forgiveness" | False. Standards are higher, not lower |

### Why This Design

1. **Accountability:** Trust must be maintained, not inherited
2. **Fresh start is possible:** Demoted agents can rebuild
3. **Prevents coasting:** High-level agents must stay sharp
4. **Levels mean something:** A Level 20 agent is genuinely capable, not just old

### Real Consequences

**Level 10 → Level 9:**
- Loses "Expert" title
- May lose unlocked capabilities
- Reputation hit
- Must re-earn the level

**Level 20 → Level 15:**
- Catastrophic collapse
- Likely pattern of failures
- Requires operator intervention
- May indicate agent needs retirement

---

## OPERATOR APPROVAL RULE

### Level-Down Is Automatic

The system does not wait for operator approval to level-down. Math is math.

**Process:**
1. Penalty applied → Total XP drops
2. Check against level thresholds
3. If below: Level-down triggers immediately
4. RPG_STATE.md updated automatically
5. Operator reviews after the fact

### Operator Discretion

While level-down is automatic, operator can:

**Investigate:**
- Was penalty correct?
- Is there a pattern?
- Does agent need support?

**Override (rare):**
- If penalty was applied in error
- If system bug caused incorrect calculation
- Document reason for override

**Intervene:**
- Assign easier tasks to rebuild XP
- Provide coaching
- Consider agent retirement if pattern continues

---

## SIMPLE EXAMPLES

### Example 1: Minor Slip

**Agent:** Level 3 (250 XP)
**Event:** Invalid tool attempt (-5 REL)
**New Total:** 245 XP
**Level 3 Minimum:** 250 XP

| Check | Result |
|-------|--------|
| Total XP 245 < 250? | Yes |
| Level-down triggered? | Yes |
| New Level | 2 |

**Result:** Agent drops from Level 3 to Level 2.

**Recovery:** Needs +5 XP to re-reach Level 3 (1-2 successful tasks).

---

### Example 2: Major Violation

**Agent:** Level 8 (1,800 XP)
**Event:** UNIVERSAL.md violation (-20 ACC, -20 JUD)
**New Total:** 1,760 XP
**Level 8 Minimum:** 1,750 XP

| Check | Result |
|-------|--------|
| Total XP 1,760 < 1,750? | No |
| Level-down triggered? | No |

**Result:** Agent stays Level 8, but close to edge.

**Recovery:** Needs +90 XP buffer before safe.

**Note:** If violation was -25 instead of -20, agent would drop to Level 7.

---

### Example 3: Catastrophic Collapse

**Agent:** Level 12 (3,900 XP)
**Events:** Pattern of failures
- Fake completion: -15 ACC
- Overreach: -12 JUD
- Wrong file: -10 ACC
- Missing proof: -7 ACC
- Same mistake again: -8 ACC

**Total Penalty:** -52 XP
**New Total:** 3,848 XP
**Level 12 Minimum:** 3,850 XP

| Check | Result |
|-------|--------|
| Total XP 3,848 < 3,850? | Yes |
| Level-down triggered? | Yes |
| New Level | 11 |

**Result:** Agent drops from Level 12 to Level 11.

**Analysis:** This was a bad run. Operator should review if this is a pattern or one-time collapse.

---

### Example 4: Stat Minimum Violation

**Agent:** Level 10 (2,750 XP, qualifies)
**Stats:**
- ACC: 65 XP → Stat level 6
- REL: 70 XP → Stat level 7
- JUD: 75 XP → Stat level 7

**Level 10 Stat Minimums:**
- ACC: 70, REL: 70, JUD: 70

| Check | Result |
|-------|--------|
| ACC 65 < 70? | Yes |
| Level-down triggered? | Yes |
| New Level | 9 |

**Result:** Agent drops from Level 10 to Level 9 (even though Total XP qualifies for L10).

**Why:** Level requires meeting ALL minimums, not just Total XP.

---

### Example 5: Recovery After Level-Down

**Agent:** Dropped from Level 5 to Level 4 (680 XP)
**Goal:** Rebuild to Level 5 (needs 700 XP)
**Gap:** +20 XP needed

**Recovery Plan:**
- Run 1: Create file + re-read = +11 REL (691 XP)
- Run 2: Edit file + risk notes = +13 ACC/JUD (704 XP)

**Result:** Agent reaches 704 XP, re-qualifies for Level 5.

**Level-up:** Automatic (same as level-down, math is math).

---

## LEVEL-DOWN VS RETIREMENT

### When to Consider Retirement

| Scenario | Action |
|----------|--------|
| One-time level-down | Normal, agent can recover |
| Repeated level-downs | Investigate pattern |
| Cannot maintain Level 5+ | Consider task reassignment |
| Violates UNIVERSAL.md repeatedly | Retirement candidate |

### Retirement Is Not Punishment

Retirement is appropriate when:
- Agent consistently fails to meet standards
- Agent cannot maintain minimum level
- Pattern shows agent is not suited for role
- Better to retire with dignity than decline indefinitely

---

## SUMMARY

- **XP loss:** Full penalty at all levels (no protection)
- **Level-down:** Automatic when XP < threshold
- **No grace period:** Math triggers immediately
- **High-level agents:** Same risk as everyone (actually more, due to diminishing returns)
- **Recovery:** Possible with solid performance
- **Retirement:** Consider if pattern emerges

**Levels are earned, maintained, and can be lost. That is what makes them meaningful.**

---

Rules Version: 2.0
Date: 2026-03-29
