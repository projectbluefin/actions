---
name: session-hygiene
description: Working-session discipline — disambiguate review targets, reviews are read-only, leave the working tree clean, answer-first communication. Prevents the failure modes where agents review the wrong thing, edit unprompted, or strand uncommitted debris.
metadata:
  type: reference
---

# Session Hygiene

Rules of engagement for working sessions in this repo. These exist because each
one was violated in a real session and required the maintainer to course-correct
multiple times.

---

## 1. Disambiguate the review target before reviewing

When the user says "review this PR" but links the generic pull-request index
(`https://github.com/projectbluefin/actions/pulls` — no PR number), **do not
guess the target**.

- List open PRs (`gh pr list --repo projectbluefin/actions`) and confirm which
  one the user means. The most recent PR is a guess, not an answer.
- **Never substitute the local working tree as the review target.** A dirty
  working tree is not a PR. If `git status` shows uncommitted changes, note
  them in one sentence and set them aside — they belong to a prior session
  until the user says otherwise.
- If the user gives a PR number or a `/pull/NNN` URL, review exactly that PR's
  diff (`gh pr diff NNN`), nothing else.

## 2. Reviews are read-only

A request to "review" never modifies files — not in this repo, not in a
consumer repo.

- Present findings and proposed fixes as text with file:line references.
- Edit files only after the user explicitly asks for the fix ("fix it",
  "apply that", "go ahead").
- If you realize mid-review that you edited something unasked, revert your own
  edits immediately and restore the prior state exactly — including restoring
  any pre-existing uncommitted changes you overwrote.

## 3. Leave the working tree clean at session end

Never end a session with uncommitted changes stranded in the working tree.
Uncommitted debris from an abandoned session gets mistaken for in-flight work
by the next session (this has happened — a broken half-refactor sat uncommitted
for two weeks and was presented to the maintainer as if it were their work).

Before ending a session, every uncommitted change must be either:

- committed to a feature branch (with a PR or a stated reason), or
- stashed with a descriptive message (`git stash push -m "wip: <what and why>"`), or
- reverted deliberately.

If you *find* a dirty tree you didn't create, leave it untouched and tell the
user — do not build on top of it, review it, or "fix" it unprompted.

## 4. Answer-first communication

- Lead with the one-line direct answer, then the evidence.
- When two unrelated issues are in play (e.g. a local working-tree problem AND
  an unrelated open PR), label them separately up front and give each its own
  verdict before recommending anything. Never blend two workstreams into one
  narrative — the reader cannot tell which verdict applies to which thing.
- "Do not merge" and "merge this" must never appear in the same breath without
  naming exactly which artifact each applies to.
- If the user says they don't understand, stop explaining and restructure:
  table of the distinct items, one verdict per item, one action per item.
