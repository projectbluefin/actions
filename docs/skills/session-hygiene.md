---
name: session-hygiene
description: Working-session discipline. Use when asked to "review this PR" (especially with a generic /pulls link), when a review request might tempt file edits, when ending or handing off a session, or when you find a dirty working tree you did not create. Prevents reviewing the wrong target, unprompted edits, and stranded uncommitted debris.
metadata:
  type: reference
---

# Session Hygiene

Rules of engagement for working sessions in this repo. Each rule exists because
it was violated in a real session and the maintainer had to course-correct
multiple times.

## When to Use

- The user asks to "review this PR" but links the generic pull-request index
  (`.../pulls`, no PR number) or gives an ambiguous target
- Any request containing the word "review" — before touching any file
- Before ending a session, opening a PR, or handing off
- `git status` shows uncommitted changes you did not create this session

## When NOT to Use

- The user explicitly names a PR number or `/pull/NNN` URL — review exactly
  that diff, no disambiguation needed
- The user explicitly says "fix it", "apply that", "go ahead" — edits are
  authorized; proceed

## Core Process

### 1. Disambiguate the review target before reviewing

1. If the target is ambiguous (generic `/pulls` link), run
   `gh pr list --repo projectbluefin/actions` and confirm which PR the user
   means. The most recent PR is a guess, not an answer.
2. **Never substitute the local working tree as the review target.** A dirty
   working tree is not a PR. If `git status` shows uncommitted changes, note
   them in one sentence and set them aside — they belong to a prior session
   until the user says otherwise.
3. Review exactly the diff of the confirmed PR (`gh pr diff NNN`), nothing
   else.

### 2. Reviews are read-only

1. Present findings and proposed fixes as text with `file:line` references.
2. Edit files only after the user explicitly asks for the fix.
3. If you realize mid-review that you edited something unasked, revert your
   own edits immediately and restore the prior state exactly — including any
   pre-existing uncommitted changes you overwrote.

### 3. Leave the working tree clean at session end

Before ending a session, every uncommitted change must be either:

- committed to a feature branch (with a PR or a stated reason), or
- stashed with a descriptive message
  (`git stash push -u -m "wip: <what and why>"`), or
- reverted deliberately.

If you *find* a dirty tree you didn't create, leave it untouched and tell the
user — do not build on top of it, review it, or "fix" it unprompted. If it is
abandoned agent debris from a prior session and the user asks for cleanup,
clean it up yourself (stash with a descriptive message); never hand cleanup of
agent-made state back to the user.

### 4. Answer-first communication

1. Lead with the one-line direct answer, then the evidence.
2. When two unrelated issues are in play (e.g. a local working-tree problem
   AND an unrelated open PR), label them separately up front and give each its
   own verdict before recommending anything.
3. "Do not merge" and "merge this" must never appear without naming exactly
   which artifact each applies to.
4. If the user says they don't understand, stop explaining and restructure:
   table of the distinct items, one verdict per item, one action per item.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "The dirty working tree is probably what they want reviewed." | It wasn't. Reviewing scratch work as if it were the PR derails the whole session. Confirm the target first. |
| "I'll just make the quick fix while I'm here." | An unprompted edit during a review reads as "destroying everything." Propose as text; wait for approval. |
| "I'll commit these leftovers next session." | You won't. Stranded debris gets mistaken for in-flight work by the next session. Stash or commit now. |
| "The user can run one git command to clean up." | Agent-made mess is the agent's job. Clean it up yourself. |

## Red Flags

- You are reviewing files that are not part of any PR
- You ran an edit/write tool during a session whose only request was "review"
- A session is ending and `git status` is not clean
- You found uncommitted changes you didn't create and started building on them
- Your status update mixes verdicts for two different artifacts in one paragraph

## Verification

- [ ] The reviewed artifact is exactly what the user pointed at (PR number confirmed or explicit)
- [ ] Zero files were modified during any review-only request
- [ ] `git status` is clean, or every remaining change is committed to a branch / stashed with a message
- [ ] Each distinct issue discussed has its own labeled verdict and its own action
- [ ] Any cleanup of prior-session debris was done by the agent, not delegated to the user
