---
name: skill-improvement
description: Canonical format reference for skill files in the projectbluefin org. Use when creating or updating a skill file in any projectbluefin repo — specifies required YAML frontmatter, naming conventions, description rules, progressive disclosure structure, and the self-improvement loop mandate.
metadata:
  type: reference
---

# Skill File Format Reference — projectbluefin

This is the canonical format reference for skill files across the projectbluefin org. Follow this
structure when creating or updating any skill file in `docs/skills/` or `.github/skills/`.

Referenced from: [`projectbluefin/.github/AGENTS.md`](https://github.com/projectbluefin/.github/blob/main/AGENTS.md)

---

## Required YAML frontmatter

Every SKILL.md must start with a frontmatter block:

```yaml
---
name: kebab-case-name          # lowercase, hyphens only, max 64 chars
description: >-                # what it does + when to use it, max 1024 chars, third person
  Does X and Y. Use when working on Z or when the user asks about A, B, or C.
metadata:
  type: reference | procedure | runbook
---
```

**`name` rules:**
- Lowercase letters, numbers, and hyphens only
- Maximum 64 characters
- Use gerund form where natural: `authoring-actions`, `validating-consumers`
- No reserved words: `anthropic`, `claude`

**`description` rules:**
- Write in **third person** — the description is injected into the system prompt
  - ✅ "Validates consumer repos before merging action changes"
  - ❌ "I can help you validate consumer repos"
- Include both *what it does* and *when to invoke it* (triggers, contexts)
- Maximum 1024 characters — be specific, not exhaustive

---

## File structure

```
docs/skills/
├── <skill-name>.md        # SKILL.md body: overview + navigation
└── <skill-name>/          # Optional: split files for long skills
    ├── reference.md
    └── examples.md

.github/skills/
└── <skill-name>/
    └── SKILL.md           # Cloud Agent variant (mirrors docs/skills/ for this repo)
```

**For `projectbluefin/actions`:** learnings live in **both** `docs/skills/` (Copilot CLI) and
`.github/skills/` (Cloud Agent). For all other projectbluefin repos, use `docs/skills/` only.

---

## Body structure

### Keep SKILL.md under 500 lines

Files longer than 500 lines get truncated or partially read. Use progressive disclosure:
- Put the 80% case in SKILL.md
- Put edge cases, full API references, and examples in linked sub-files

### Table of contents (required for files > 100 lines)

```markdown
## Contents
- [Section 1](#section-1)
- [Section 2](#section-2)
- [Section 3](#section-3)
```

### Progressive disclosure pattern

```markdown
# My Skill

## Quick start
[The 80% case — enough to solve most tasks]

## Advanced: edge case A
See [edge-case-a.md](edge-case-a.md)

## Reference
See [reference.md](reference.md)
```

Claude loads linked files only when needed. Keep references **one level deep** from SKILL.md —
do not chain references (SKILL.md → A.md → B.md), as nested references may be partially read.

---

## Degrees of freedom

Match specificity to the task's fragility:

| Task type | Approach |
|---|---|
| Many valid paths | High-level guidance, let Claude choose |
| Preferred pattern exists | Show the pattern with inline comments |
| Fragile, must follow exact sequence | Exact commands with "do not modify" |

**Example — fragile (low freedom):**

```markdown
## Database migration

Run exactly this script. Do not add flags or skip steps:

```bash
python scripts/migrate.py --verify --backup
```
```

**Example — flexible (high freedom):**

```markdown
## Code review process

1. Analyze structure and organization
2. Check for bugs and edge cases
3. Suggest readability improvements
4. Verify adherence to project conventions
```

---

## Self-improvement mandate

Every time you work on a task and discover something non-obvious, update the relevant skill file in
the **same PR** as your change. Do not open a separate follow-up PR.

**Before marking work complete:**
- [ ] Did I discover a workaround, non-obvious pattern, or convention?
- [ ] Is there a skill file for the area I worked in?
- [ ] If yes — did I update it?
- [ ] If no — did I create one and add it to `docs/SKILL.md`?
- [ ] Is the skill file committed in this same PR?

### What belongs in a skill file

| Write it | Don't write it |
|---|---|
| Workaround for upstream bug (with issue link) | One-off task notes |
| Non-obvious pattern required for correctness | Obvious things any developer would know |
| Convention not visible from the code | Ephemeral state ("currently broken") |
| Discovery from trial and error | Specific SHA hashes or PR numbers |

**Skill files are procedures, not logs.** Never record specific SHAs, PR numbers, current
deployment state, or point-in-time snapshots — those become misleading after the next commit.

---

## Adding a skill file to an existing repo

1. Create `docs/skills/<name>.md` with the YAML frontmatter above.
2. Add a row to the routing table in `docs/SKILL.md`.
3. If working in `projectbluefin/actions`, also create `.github/skills/<name>/SKILL.md`.
4. Commit in the same PR as the change that prompted the new skill.

---

## Example skill file

```markdown
---
name: validating-consumers
description: Validates that action changes in projectbluefin/actions do not break consuming repos. Use before merging any change to bootc-build/ actions or reusable workflows.
metadata:
  type: procedure
---

# Consumer Validation

## Contents
- [Blast radius](#blast-radius)
- [Validation steps](#validation-steps)
- [N/A rules](#na-rules)

---

## Blast radius

| Consumer | Notified? |
|---|---|
| projectbluefin/bluefin | ✅ Direct access |
| ublue-os/aurora | ⚠️ No CI visibility |

## Validation steps

1. Open draft PR in projectbluefin/bluefin pinned to your branch SHA
2. Wait for CI green
3. Fill PR template evidence fields

## N/A rules

`Consumer PR:` and `Consumer CI run:` never accept N/A.
`Out-of-org consumer impact:` accepts N/A.
```
