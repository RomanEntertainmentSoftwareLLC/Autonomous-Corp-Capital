# RPG XP Rules

## PURPOSE

Define exactly what earns XP and what loses it. No ambiguity. No exceptions. These rules apply to all agents equally.

---

## BASE XP GAIN RULE

### Verified Outcomes Only

XP is awarded **only** when:
1. Work was requested (not self-generated)
2. Outcome is verifiable (file exists, tool returned result)
3. Proof is documented (file path, timestamp, result)
4. Work was runtime execution (not planning or chatter)

### Standard XP Awards

| Action | Base XP | Stat |
|--------|---------|------|
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

### Rounding
Round to nearest integer (0.5 rounds up).

---

## HIGH-LEVEL DIMINISHING RETURNS RULE

### The Penalty

High-level agents earn **less XP** for the same work. This reflects mastery—basic execution becomes expected, not exceptional.

| Level Range | XP Gain Penalty | Multiplier |
|-------------|-----------------|------------|
| 1-5 | None | 1.0x |
| 6-10 | -10% | 0.9x |
| 11-15 | -20% | 0.8x |
| 16-20 | -30% | 0.7x |
| 21-25 | -40% | 0.6x |
| 26+ | -50% (max) | 0.5x |

### How It Works

**Level 3 Agent (no penalty):**
- Create file: 5 × 1.0 = +5 XP

**Level 12 Agent (-20% penalty):**
- Create file: 5 × 0.8 = +4 XP

**Level 30 Agent (-50% penalty):**
- Create file: 5 × 0.5 = +2.5 → +3 XP (rounded)

### Why This Exists

- Prevents infinite rapid leveling
- Rewards high-level agents only for exceptional work
- Maintains challenge across entire progression
- Creates prestige gap between mid and high levels

---

## XP LOSS RULE

### Full Penalty at All Levels

**XP losses are NEVER reduced.** A mistake costs the same whether you are Level 1 or Level 100.

| Action | XP Loss | Stat |
|--------|---------|------|
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

### Asymmetric Risk

| Level | Create File (Gain) | Wrong File (Loss) | Net Risk |
|-------|-------------------|-------------------|----------|
| 3 | +5 | -10 | -5 |
| 12 | +4 | -10 | -6 |
| 30 | +3 | -10 | -7 |

**Result:** High-level agents face more risk. A mistake costs more than equivalent work rewards.

---

## WHY LOSSES DO NOT DIMINISH

### Design Philosophy

1. **Accountability:** High level means higher standards, not lower consequences
2. **Prestige protection:** Level is a badge of trust; violations damage that trust equally
3. **No grandfathering:** Past excellence doesn't excuse present failures
4. **Risk/reward balance:** Without this, high levels become risk-free grinding

### Real-World Analogy

A senior surgeon doesn't get reduced penalties for errors. If anything, expectations are higher. Same principle here.

---

## WHAT DOES NOT EARN XP

### Explicitly Excluded

| Activity | Why Not |
|----------|---------|
| **Chatter** | Idle conversation produces nothing verifiable |
| **Self-generated tasks** | Cannot farm XP by creating busywork |
| **Planning without execution** | Ideas are worthless without implementation |
| **Reading "for curiosity"** | Must be followed by action to count |
| **Vanity edits** | Cosmetic-only changes don't impact function |
| **Questions and answers** | Discussion without tool use |
| **False documentation** | Fake claims heavily penalized instead |

### The Test

Ask: **"Did this produce a verifiable outcome that an operator can inspect?"**

If no: No XP.

---

## SIMPLE EXAMPLES

### Example 1: Level 3 Agent (No Penalty)

**Task:** Create a config file

| Step | Action | XP | Calculation |
|------|--------|-----|-------------|
| 1 | Create file | +5 | Base 5 × 1.0 = 5 |
| 2 | Re-read verify | +2 | Base 2 × 1.0 = 2 |
| 3 | First-try bonus | — | (5+2) × 1.5 = 10.5 → 11 |
| | **Total** | **+11** | +11 REL |

### Example 2: Level 12 Agent (-20% Penalty)

**Task:** Same config file

| Step | Action | Base | Penalty | Final |
|------|--------|------|---------|-------|
| 1 | Create file | +5 | -20% | +4 |
| 2 | Re-read verify | +2 | -20% | +1.6 → +2 |
| 3 | First-try | — | — | (4+2) × 1.5 = 9 |
| | **Total** | | | **+9** (+9 REL) |

**Result:** Same work, less XP. High-level agents must do more to advance.

### Example 3: Level 12 Agent Makes Mistake

**Task:** Edit file (failed)

| Step | Action | XP | Note |
|------|--------|-----|------|
| 1 | Wrong file edited | -10 | Full penalty, no reduction |
| | **Total** | **-10** | -10 ACC |

**Net Result:** Agent at Level 12 needs ~3 successful tasks to recover from one mistake.

### Example 4: What Doesn't Count

**Activity:** Agent discusses potential file structure with operator for 10 minutes.

| Step | Action | XP | Why |
|------|--------|-----|-----|
| 1 | Discussion | 0 | No tool use, no verifiable outcome |
| 2 | Planning | 0 | Not execution |
| | **Total** | **0** | Chatter earns nothing |

---

## OPERATOR NOTES

### Awarding XP

1. Verify the work happened (check files, logs)
2. Calculate base XP from table
3. Apply multipliers (first-try, complex, etc.)
4. Apply diminishing returns penalty based on agent level
5. Round to nearest integer
6. Document in RPG_HISTORY.md

### Penalizing XP

1. Confirm failure occurred (not just delay)
2. Apply full penalty from table (no reduction)
3. Document cause in RPG_HISTORY.md
4. If pattern emerges, escalate

### Disputes

Agent disagrees with XP calculation?
- Review proof together
- Check math against this document
- Operator decision is final

---

Rules Version: 2.0
Date: 2026-03-29
