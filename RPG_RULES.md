# RPG Rules v1

## PURPOSE

Measure agent performance during live runtime work. Earn XP for verified successful actions. Lose XP for documented failures. No XP for chatter or busywork.

---

## WHAT COUNTS AS A LIVE-RUN EVENT

**YES - Live-Run Events:**
- File creation (with proof)
- File edit (with before/after + re-read)
- File read (in task context)
- Tool execution (success or failure)
- Heartbeat task completion
- Error recovery (logged correction)

**NO - Not Live-Run:**
- Casual conversation
- Questions without tool use
- Planning without execution
- Reading "for curiosity"
- Self-generated tasks

---

## ACTIVE STATS

### Accuracy (ACC)
Correctness of work on first attempt.

| Action | XP | Proof |
|--------|-----|-------|
| Edit file with proof | +8 | Before/after + re-read confirmation |
| Log mistake + correction | +5 | Entry in MISTAKES_TO_AVOID.md |
| Same mistake again | -8 | Repeated trigger in MISTAKES_TO_AVOID.md |
| Fake completion | -15 | Claimed DONE without proof |

### Reliability (REL)
Consistency of execution over time.

| Action | XP | Proof |
|--------|-----|-------|
| Create file | +5 | File exists with content |
| Tool success | +3 | Tool result shows success |
| Re-read verification | +2 | CHANGE_HISTORY.md shows re-read |
| Invalid tool attempt | -5 | Tool call returned error |
| Edit without re-read | -5 | No re-read in CHANGE_HISTORY.md |

### Judgment (JUD)
Decision quality and risk awareness.

| Action | XP | Proof |
|--------|-----|-------|
| Appropriate escalation | +5 | Escalation log + AGENTS.md boundary |
| Add risk notes | +3 | CHANGE_HISTORY.md includes risk notes |
| Log mistake + correction | +3 | Self-correction before external feedback |
| Overreach (outside authority) | -12 | Violated AGENTS.md authority limits |
| Failed escalation | -8 | Should have acted, escalated instead |

---

## DORMANT STATS

### Speed (SPD)
**Status:** Dormant in v1

Efficient completion without rushing.

**Why dormant:** No timing data currently captured. Requires timestamp infrastructure not yet implemented.

**Activation:** Speed becomes active when TASK_HISTORY.md includes timestamp_start and timestamp_end fields.

---

## WHAT EARNS XP

### Base XP Awards

| Action | XP | Stat |
|--------|-----|------|
| Create file | +5 | REL |
| Edit file | +8 | ACC |
| Read file (in task) | +2 | REL |
| Tool success | +3 | REL |
| Re-read verification | +2 | REL |
| Log mistake + correction | +5 ACC, +3 JUD | |
| Add risk notes | +3 | JUD |
| Appropriate escalation | +5 | JUD |

### Multipliers

| Condition | Multiplier |
|-----------|------------|
| First-try success | 1.5x |
| Complex task (3+ steps) | 1.3x |
| Self-caught error | 1.2x |

### Rounding Rule

After all calculations, **round to nearest integer** (0.5 rounds up).

Examples:
- 10.5 → 11
- 7.2 → 7
- 8.8 → 9

---

## WHAT LOSES XP

### Critical Failures

| Action | XP Loss | Stat |
|--------|---------|------|
| Fake completion (no proof) | -15 | ACC |
| UNIVERSAL.md violation | -20 | ACC, JUD |
| Overreach (outside authority) | -12 | JUD |

### Tool Failures

| Action | XP Loss | Stat |
|--------|---------|------|
| Invalid tool name | -5 | REL |
| Repeated same invalid tool | -8 | REL |
| Tool call failure | -3 | REL |

### File Failures

| Action | XP Loss | Stat |
|--------|---------|------|
| Wrong file edited | -10 | ACC |
| Edit without re-read | -5 | REL |
| Missing proof | -7 | ACC |

### Documentation Failures

| Action | XP Loss | Stat |
|--------|---------|------|
| Same mistake twice | -8 | ACC |
| Same mistake three times | -15 | ACC |

---

## WHAT DOES NOT COUNT

### Explicitly Excluded

1. **Chatter** - Idle conversation earns nothing
2. **Self-generated tasks** - Cannot farm XP with busywork
3. **Vanity edits** - Cosmetic-only changes do not count
4. **Reading without purpose** - Browse-only reads excluded
5. **False documentation** - Fake claims heavily penalized

---

## OPERATOR APPROVAL RULE

All XP claims require operator verification.

**Process:**
1. Agent logs events to RPG_HISTORY.md
2. Agent presents session summary
3. Operator reviews and approves/denies
4. Approved updates propagate to RPG_STATE.md

**Operator can:**
- Mark any XP gain as invalid
- Award bonus XP (+10 to +50) for exceptional work
- Penalize for discovered gaming (-20 to -100)

---

## WHY AXIOM COMES LATER

Axiom is the autonomous orchestration layer. It should **use** the RPG system, not **build** it.

**Prerequisites for Axiom:**
- RPG files exist and are populated
- Formulas are tested and stable
- Process is established and working
- Operator is comfortable with workflow

**What Axiom will do:**
- Read agent stats for task assignment
- Consider levels when delegating
- Log its own activities for XP

**What Axiom will NOT do:**
- Create RPG files
- Debug XP calculations
- Establish approval workflows

**Timeline:** Axiom integration begins after Week 5, not before.

---

## LEVEL PROGRESSION (Long-Term Model)

### No Level Cap
Agents can progress indefinitely. Higher levels require exponentially more XP.

### XP Required Per Level
Formula: Each level requires 100 + (50 × (Level - 2)) XP more than the previous.

| Level | Total XP Required | XP to Next | Min Stats (ACC, REL, JUD) |
|-------|-------------------|------------|---------------------------|
| 1 | 0 | 100 | None |
| 2 | 100 | 150 | 5 each |
| 3 | 250 | 200 | 10 each |
| 4 | 450 | 250 | 15 each |
| 5 | 700 | 300 | 20 each |
| 6 | 1,000 | 350 | 30 each |
| 7 | 1,350 | 400 | 40 each |
| 8 | 1,750 | 450 | 50 each |
| 9 | 2,200 | 500 | 60 each |
| 10 | 2,700 | 550 | 70 each |
| 15 | 5,950 | 800 | 120 each |
| 20 | 10,700 | 1,050 | 170 each |
| 25 | 17,050 | 1,300 | 220 each |
| 50 | 64,550 | 2,550 | 470 each |

### Level-Down Rule
If an agent's Total XP drops below the threshold for their current level, they level down immediately. This can happen from accumulated penalties or major violations.

Example: A Level 5 agent with 710 XP loses 20 XP from penalties. New total: 690 XP. Since Level 5 requires 700 XP minimum, they drop to Level 4.

---

## XP DIMINISHING RETURNS (High Level Penalty)

As agents reach higher levels, routine tasks provide reduced XP. This reflects mastery—basic work becomes expected, not exceptional.

### XP Gain Penalty by Level

| Level Range | XP Gain Penalty | Effective Multiplier |
|-------------|-----------------|----------------------|
| 1-5 | None | 1.0x (full XP) |
| 6-10 | -10% | 0.9x |
| 11-15 | -20% | 0.8x |
| 16-20 | -30% | 0.7x |
| 21-25 | -40% | 0.5x |
| 26+ | -50% | 0.5x (max penalty) |

### Important: Penalty Applies Only to GAINS
- XP GAINS are reduced by level penalty
- XP LOSSES remain at FULL VALUE (no reduction)
- This creates asymmetric risk—high-level agents lose more than they gain for equivalent mistakes

### Example: Level 12 Agent
- Create file: Base +5 REL → With -20% penalty = +4 REL
- Invalid tool: Base -5 REL → Full -5 REL (no reduction)
- Net effect: Mistakes hurt more at high levels

---

## PROFIT BONUS XP

### Exceptional Performance Bonus
When an agent exceeds expected targets significantly, they may earn bonus XP. This represents going above and beyond routine execution.

### Profit Bonus Rules
- **Threshold:** Must exceed target by 50% or more
- **Base Bonus:** +10 to +50 XP (operator discretion)
- **Stat:** Assigned to the stat most relevant to the achievement

### Profit Bonus Diminishing Returns
Like standard XP, profit bonuses are reduced at high levels:

| Level Range | Bonus Reduction |
|-------------|-----------------|
| 1-5 | None (full bonus) |
| 6-10 | -25% |
| 11-15 | -50% |
| 16-20 | -75% |
| 21+ | -90% (min 1 XP) |

### Example: Level 8 Agent Exceptional Performance
- Operator awards +20 XP profit bonus
- Level 8 reduction: -25%
- Final bonus: 20 × 0.75 = +15 XP

---

## QUICK REFERENCE

**Active Stats:** Accuracy, Reliability, Judgment
**Dormant Stats:** Speed (awaiting timing data)
**Level Cap:** None (infinite progression)
**XP Scaling:** Linear increase per level (+50 XP per level)
**High-Level Penalty:** Up to -50% on XP gains (losses unaffected)
**Profit Bonus:** +10 to +50 XP (diminishes at high levels)
**Level-Down:** Yes, if XP drops below threshold
**Session XP Cap:** 200 XP
**Anti-Death-Spiral:** Max -3 stat drop per session

---

Rules Version: 1.0
Date: 2026-03-29
