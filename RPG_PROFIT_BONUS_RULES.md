# RPG Profit Bonus Rules

## PURPOSE

Reward agents for exceptional performance that exceeds expected targets. Profit bonus recognizes going above and beyond routine execution—not just doing the job, but doing it exceptionally well.

**Important:** Profit bonus is discretionary, rare, and secondary to safety, compliance, and system survival.

---

## WHEN PROFIT BONUS APPLIES

### All Conditions Must Be Met

1. **Real Live Run**
   - Must be actual runtime work
   - Not planning, discussion, or preparation
   - Must produce verifiable outcomes

2. **Verified Profit Exceeds Target**
   - Target must be defined before the run
   - Actual results must exceed target by 50% or more
   - Profit must be measurable and documented
   - Operator must verify the numbers

3. **Exceptional Performance**
   - Not just "doing the job well"
   - Must be truly above-and-beyond
   - Operator discretion applies
   - Should be rare, not routine

4. **Clean Execution**
   - No violations during the run
   - No safety incidents
   - No compliance breaches
   - No shortcuts that created risk

### Profit Bonus Tiers

| Exceeds Target By | Base Bonus Range | Typical Award |
|-------------------|------------------|---------------|
| 50-75% | +10 to +20 XP | +15 XP |
| 76-100% | +20 to +35 XP | +25 XP |
| 101-150% | +35 to +45 XP | +40 XP |
| 150%+ | +45 to +50 XP | +50 XP (max) |

### Stat Assignment

Profit bonus XP is assigned to the stat most relevant to the achievement:

| Achievement Type | Assigned Stat |
|------------------|---------------|
| Efficiency/cost savings | REL |
| Quality/correctness | ACC |
| Decision-making under pressure | JUD |

---

## WHEN PROFIT BONUS DOES NOT APPLY

### Explicit Exclusions

| Scenario | Why Excluded |
|----------|--------------|
| **Planning phase** | No runtime outcomes yet |
| **Target not defined first** | Cannot exceed undefined target |
| **Less than 50% over target** | Not exceptional enough |
| **Violations occurred** | Safety/compliance trumps profit |
| **Reckless shortcuts** | Risk-taking is not rewarded |
| **Self-reported only** | Must be operator-verified |
| **Routine performance** | Expected excellence, not exceptional |
| **Chatter or discussion** | No runtime work performed |

### The Safety Filter

Even if profit targets were exceeded, bonus is VOID if:
- UNIVERSAL.md was violated
- Safety protocols were skipped
- Compliance rules were bent
- Risk limits were exceeded
- Long-term stability was compromised

**Rule:** A profitable unsafe run is worse than a safe mediocre run.

---

## DIMINISHING RETURNS ON PROFIT BONUS

### High-Level Agent Reduction

Like standard XP, profit bonuses are reduced at high levels:

| Level Range | Bonus Multiplier | Example: +40 Bonus |
|-------------|------------------|-------------------|
| 1-5 | 1.0x (full) | +40 XP |
| 6-10 | 0.75x (-25%) | +30 XP |
| 11-15 | 0.5x (-50%) | +20 XP |
| 16-20 | 0.25x (-75%) | +10 XP |
| 21+ | 0.1x (-90%, min 1) | +4 XP |

### Why Diminish Profit Bonuses?

1. **Prevents inflation:** High-level agents can't farm bonuses
2. **Maintains rarity:** Exceptional at Level 30 is different from Level 5
3. **Encourages longevity:** Long-term consistency over one big win
4. **Limits gaming:** Can't spike one run for massive gains

### Calculation Order

1. Determine base profit bonus (operator discretion, +10 to +50)
2. Check agent level for diminishing returns multiplier
3. Apply multiplier
4. Round to nearest integer (0.5 rounds up)
5. Assign to appropriate stat

---

## RISK AND SAFETY OVERRIDE RULE

### The Hierarchy (Unbreakable)

1. **System Survival** - Highest priority
2. **Compliance** - Legal/regulatory requirements
3. **Safety** - No harm to people or systems
4. **Risk Limits** - Stay within authority boundaries
5. **Profit** - Only after 1-4 are satisfied

### Profit Bonus Is Always Conditional

```
Profit Bonus = Base × Level_Multiplier × Safety_Score

Where Safety_Score:
- 1.0 = Perfect execution, no issues
- 0.0 = Any violation, incident, or breach (bonus VOID)
```

### Real Examples

**Scenario A:** Agent exceeds profit target by 80%, but violated UNIVERSAL.md by claiming fake completion.
- Profit bonus: VOID
- Penalty: -20 ACC, -20 JUD
- Result: Net loss, not gain

**Scenario B:** Agent meets target exactly, but with perfect safety and compliance.
- Profit bonus: None (didn't exceed target)
- Standard XP: Awarded normally
- Result: Solid, reliable execution

**Scenario C:** Agent exceeds target by 60%, clean execution, Level 12.
- Base bonus: +20 XP (operator discretion)
- Level reduction: 20 × 0.75 = +15 XP
- Assigned to: JUD (strategic decision-making)
- Result: +15 JUD bonus awarded

---

## SIMPLE EXAMPLES

### Example 1: Valid Profit Bonus

**Context:** Trading agent runs live session
**Target:** $1,000 profit
**Result:** $1,700 profit (70% over target)
**Execution:** Clean, no violations
**Agent Level:** 8

| Step | Calculation | Result |
|------|-------------|--------|
| Base bonus | 70% over target | +25 XP (operator discretion) |
| Level penalty | Level 8 (-25%) | 25 × 0.75 = 18.75 |
| Rounding | Nearest integer | +19 XP |
| Stat | Trading decisions | +19 JUD |

**Awarded:** +19 JUD profit bonus

### Example 2: Voided Profit Bonus

**Context:** File processing agent
**Target:** Process 100 files
**Result:** Processed 160 files (60% over target)
**Execution:** Skipped re-read verification to save time

| Step | Calculation | Result |
|------|-------------|--------|
| Base bonus | Would be +20 XP | — |
| Safety check | Skipped re-read | VIOLATION |
| Bonus outcome | VOID | 0 XP |
| Penalty | No re-read | -5 REL |

**Result:** No bonus, -5 REL penalty instead

### Example 3: No Bonus (Below Threshold)

**Context:** Data analysis agent
**Target:** 95% accuracy
**Result:** 97% accuracy (2% over target)

| Step | Calculation | Result |
|------|-------------|--------|
| Over target | 2% over | Below 50% threshold |
| Profit bonus | Not applicable | 0 XP |
| Standard XP | Accurate work | +8 ACC (standard) |

**Result:** Standard XP only, no bonus

### Example 4: High-Level Diminishing Returns

**Context:** Senior agent (Level 22) executes complex migration
**Target:** Zero downtime, 99% data integrity
**Result:** Zero downtime, 99.9% integrity, 20% faster than expected
**Execution:** Flawless

| Step | Calculation | Result |
|------|-------------|--------|
| Base bonus | Exceptional performance | +50 XP (max) |
| Level penalty | Level 22 (-90%) | 50 × 0.1 = 5 |
| Rounding | Nearest integer | +5 XP |
| Stat | Execution excellence | +5 REL |

**Awarded:** +5 REL profit bonus (significantly reduced due to level)

**Note:** Even with max base bonus, high-level agent only receives +5. This is intentional—at Level 22, exceptional execution is expected, not extraordinary.

---

## OPERATOR GUIDELINES

### When to Award Profit Bonus

**Award when:**
- Target was clear and defined beforehand
- Results significantly exceeded expectations
- Execution was clean and compliant
- Achievement was genuinely exceptional

**Do NOT award when:**
- Target was vague or undefined
- Results were good but not exceptional
- Any shortcuts or risks were taken
- Achievement feels routine for the agent's level

### Frequency Expectations

| Level Range | Expected Bonuses per Year |
|-------------|---------------------------|
| 1-5 | 2-4 (learning phase) |
| 6-10 | 1-3 (solid performance) |
| 11-15 | 0-2 (high expectations) |
| 16-20 | 0-1 (exceptional only) |
| 21+ | Rare (legendary moments) |

If you're awarding bonuses more frequently than this, the bar is too low.

### Documentation Required

Every profit bonus must be documented with:
1. Pre-run target (what was expected)
2. Post-run result (what was achieved)
3. Percentage over target (calculation)
4. Why it was exceptional (operator justification)
5. Safety/compliance check (pass/fail)
6. Final bonus amount (with math shown)

---

## SUMMARY

- **Profit bonus:** Rare reward for exceptional performance
- **Threshold:** Must exceed target by 50%+
- **Safety first:** Any violation voids bonus
- **Diminishing returns:** High-level agents get less
- **Operator discretion:** Not automatic, requires judgment
- **Documentation:** Every bonus must be justified

**Remember:** Profit is fifth priority. Survival, compliance, safety, and risk limits come first.

---

Rules Version: 2.0
Date: 2026-03-29
