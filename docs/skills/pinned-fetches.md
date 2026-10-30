---
name: pinned-fetches
description: Author and run the "pinned fetches" supply-chain gate (projectbluefin/utah#902, Option A). Use when adding a check that fails builds downloading tools/source by a mutable reference with no checksum, when wiring reusable-pinned-fetches.yml into a consumer repo's CI, when tuning the check-pinned-fetches.sh rules or allowlist, or when explaining why a curl|sh, git clone, or image-by-tag fetch is unsafe. Covers the five rules, --root/--mode/--allowlist args, the warn-then-fail rollout, and the grep-scan limit.
metadata:
  type: reference
---

# Pinned-Fetches Gate in the projectbluefin Actions Factory

## When to Use

Use when a build or test pipeline downloads a tool or source file from the
internet by a **mutable reference** — a moving tag, a branch head, `latest`, or
a bare `git clone` with no commit — and then uses those bytes without first
proving they are exactly what the author intended. That shape is a supply-chain
hole: if the download site is tampered with (or the tag is force-pushed), the
altered file runs inside the build and can end up in a signed release or forge a
test result.

This is projectbluefin/utah#902, resolved as **Option A**: one shared check,
implemented as a grep-based script plus a `workflow_call` reusable workflow,
consumed by every image repo.

## When NOT to Use

- To gate a fetch that already carries an immutable marker on the same line —
  a `@sha256:` digest, a `--branch <40-hex>` clone SHA, a full release URL, or a
  `… | sha256sum -c -` verify. The gate only flags the *absence* of such a
  marker; an already-pinned download is not a finding.
- As a substitute for a real verifier (SBOM, cosign/attestation check, or a
  checksum you actually compute). It is a cheap grep that reports the common
  download shapes; it does not compute digests, resolve tags, or verify a
  signature.
- To gate third-party composite actions (`bootc-build/*`) or unrelated lint —
  this check is specifically about tools and source a build downloads by a
  mutable reference from the internet.
- As a pre-merge fail on the warn baseline. `warn` never fails; flip to `fail`
  only after the baseline is clean or fully allowlisted, or every consumer
  fails on noise it cannot yet act on (see Roll-Out).

## Core Process

1. Add or edit the download so the immutable marker is on the *same line* as
   the fetch: `@sha256:` digest for images, `--branch <40-hex>` for clones, a
   full version URL for releases, or `curl -fSL url -o f && echo "$SHA  f" | sha256sum -c -`
   for a piped install.
2. Run the gate in warn mode to see the baseline:

   ```bash
   ./scripts/check-pinned-fetches.sh --root . --mode warn --allowlist .github/pinned-fetches-allowlist.txt
   ```

3. Fix each genuine finding. For a reviewed exception you cannot fix now, add a
   one-line entry to the allowlist — a bare rule id to disable a rule, or a
   substring unique to that case (`ghcr.io/tuna-os/tacklebox:latest`).
4. Re-run in warn mode until the baseline is clean or fully allowlisted, then
   flip `--mode` to `fail`.
5. In a consumer repo, opt in with a job using
   `reusable-pinned-fetches.yml@v1` (see Consuming It in a Consumer Repo).

## The Rules

`scripts/check-pinned-fetches.sh` reports five shapes. Each finding carries a
severity; the gate fails on any non-allowlisted finding in `fail` mode.

| Rule | Severity | Flags |
|---|---|---|
| `mutable-url` | high | a URL pinned to a moving target: `/releases/latest/download/`, `@Main`, `@master`, `@stable`, or `:latest` |
| `pipe-download` | high | `curl`/`wget` piped straight into an interpreter (`| bash`, `| sh`, `| zsh`) with no checksum/verify on the same line |
| `unpinned-clone` | medium | `git clone` with no immutable commit SHA (`--branch <40-hex>`) |
| `unpinned-image` | medium | a `FROM` image referenced by tag with no `@sha256:` digest |
| `unpinned-ostree` | high | `bootc switch`/`ostree rebase` to a tag with no container signature policy (`--sigpolicy` / `--enforce-policy-path`) |

The gate is a **grep scan, not a parser**: it looks for a mutable reference and
the absence of a marker *on the same line*. It does not cross-check a verified
download across lines (a `curl` on one line and `sha256sum -c` on the next are
each judged alone), and it does not resolve whether a bare URL is truly mutable.
That limit is intentional — a parser would be far larger and would false-positive
on templated refs — and is documented in the script header and in the reusable
workflow comment.

## The Script

```bash
# scan the repo under ., warn-only baseline (never fails)
./scripts/check-pinned-fetches.sh --root . --mode warn --allowlist .github/pinned-fetches-allowlist.txt

# same scan, but exit 1 on any finding that is not allowlisted
./scripts/check-pinned-fetches.sh --root . --mode fail --allowlist .github/pinned-fetches-allowlist.txt
```

- `--root DIR` — repository root to scan (default: current directory).
- `--mode warn|fail` — `warn` prints findings and exits 0; `fail` exits 1 on any
  non-allowlisted finding. This is the only knob that decides pass/fail.
- `--allowlist FILE` — plain-text list of rule ids or substrings to skip.
- `-h, --help` — usage; exits 0.
- Unknown `--mode` exits 2 (usage error).

It only scans files that can carry a fetch: `.github/**/*.yml`, `*.sh`,
`Justfile*`, `Containerfile*`, `*.container.in`, and `*.toml`. A `notes.txt`
with an unsafe line is not part of the scan set.

Exit code summary:

| Exit | Meaning |
|---|---|
| 0 | clean, or `warn` mode with findings |
| 1 | `fail` mode with a non-allowlisted finding |
| 2 | usage error (bad `--mode`) |

## The Allowlist

`.github/pinned-fetches-allowlist.txt`, one entry per line, `#` for comments.
Two kinds of entry:

- A **bare rule id** disables that rule for the whole scan (`unpinned-image`).
- Any **other line** suppresses one finding whose printed text — the summary
  line *or* the reported source line — contains it. Use the URL, image ref, or
  path that is actually unique to the case (`ghcr.io/tuna-os/tacklebox:latest`).

The allowlist is for exceptions you have reviewed and deliberately kept, with a
reason. Fix the fetch instead whenever you can.

## Consuming It in a Consumer Repo

Consumer repos add a **job** — `workflow_call` reusables can only be invoked at
`jobs.<id>.uses`, never as a step:

```yaml
jobs:
  pinned-fetches:
    uses: projectbluefin/actions/.github/workflows/reusable-pinned-fetches.yml@v1
    with:
      mode: fail            # warn for the baseline cycle, then fail
      allowlist: .github/pinned-fetches-allowlist.txt
      actions_ref: v1       # where the gate script is fetched from (default)
```

The reusable does two checkouts: the code under scan (the consumer's own repo),
then `projectbluefin/actions` at `actions_ref` (default `v1`) to take
`scripts/check-pinned-fetches.sh`. Keeping the gate in one shared place means
fixing a rule here fixes it for every consumer, instead of one copy per repo.

## Enforcing It in This Repo

`projectbluefin/actions` **cannot** call its own reusable with `uses:` — the
`check-self-repository-references.py` gate rejects implementation-time
self-references so a repo never depends on a not-yet-released `@v1` of itself.
So, exactly as `factory-drift.yml` runs the canonical
`scripts/validate_thin_caller.py` directly instead of via
`reusable-thin-caller-gate.yml`, this repo runs the gate directly in
`.github/workflows/pinned-fetches.yml`:

```yaml
- run: ./scripts/check-pinned-fetches.sh \
    --root . --mode warn --allowlist .github/pinned-fetches-allowlist.txt
```

It is `warn`-only for the baseline cycle (records findings, never fails). Once
the baseline is clean or fully allowlisted, flip `--mode` to `fail` in that file.

## Roll-Out (utah#902)

Warn-only for one baseline cycle with an allowlist for deliberate exceptions,
then required (`mode: fail`). Do not skip the baseline: flip to `fail` before the
allowlist has captured the real findings and you will fail every consumer on
noise they cannot yet act on.

## Common Rationalizations

- "It's just curl|sh from a well-known site." — that is the exact
  supply-chain-forgery shape; a tampered mirror or a pushed tag changes the
  bytes, and the signature is on the result.
- "We verify the checksum a few lines later." — the gate judges the download
  line alone; move the verify onto the same line (`curl -fSL url -o f && echo
  "$SHA  f" | sha256sum -c -`) so the marker is on the line that fetches.
- "A bare `git clone` of an issue-tracking mirror is harmless." — it is
  unpinned by the same rule; add `--branch <40-hex>` so the clone is a snapshot,
  not a moving pointer.
- "The allowlist will just list everything." — an allowlist that suppresses all
  findings is a gate that never runs; each entry should be a reviewed exception,
  not a blanket pass.

## Red Flags

- A consumer repo that has not opted into `reusable-pinned-fetches.yml` while
  siblings have — it is drifting from the contract.
- An allowlist file that suppresses whole rules or broad substrings for every
  finding, with no reason and no plan to fix the fetch.
- A fetch that is verified on a *different* line than the one that downloads.
- Copying the opt-in snippet as a step (`- uses: ...`) instead of a job —
  GitHub Actions rejects `workflow_call` reusables used at step level, so the
  gate silently never runs.

## Verification

- `shellcheck scripts/check-pinned-fetches.sh` is clean.
- `bats --print-output-on-failure tests/bats/test_check_pinned_fetches.bats`
  passes (17 tests) — it covers every rule firing in `fail` mode, a clean tree
  passing, `warn` mode never blocking, comment lines not reported as real
  fetches, the allowlist suppressing a rule by id and a finding by substring,
  file-type filtering, and usage errors.
- `python3 scripts/check-self-repository-references.py` reports no
  self-repository references in the new workflows.
- `.github/workflows/actionlint.yml` lints the reusable workflow on every PR
  (actionlint is not runnable offline; it runs in CI).
