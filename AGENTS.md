# AGENTS.md — projectbluefin/actions

Shared composite GitHub Actions for bootc image builders (bluefin, aurora, bazzite).

Load **[docs/SKILL.md](docs/SKILL.md)** before modifying any action.

## Org pipeline — projectbluefin

```
projectbluefin/actions  ←── shared CI building blocks
        │
        ├── projectbluefin/bluefin      (bootc desktop image, Path 1 — reusable-build.yml)
        ├── projectbluefin/bluefin-lts  (LTS on CentOS Stream 10, Path 2 — à la carte)
        ├── projectbluefin/dakota       (BST/BuildStream image, Path 2 — à la carte, deferred)
        ├── ublue-os/aurora             (Aurora desktop image)
        └── ublue-os/bazzite            (Bazzite gaming image)
```

**Path 1** (full reusable workflow): consumer calls `reusable-build.yml@v1` and satisfies the Justfile contract. Used by bluefin and aurora.

**Path 2** (à la carte composite actions): consumer calls individual actions. Used by bluefin-lts (CentOS Stream 10 base, multi-arch, `chunka` not `rechunk`) and dakota (BST build engine — `create-release` and `sign-and-publish` adopted; see issue #16 for remaining actions).

Actions are referenced as `projectbluefin/actions/bootc-build/<name>@v1`. Breaking changes to an action require a version bump and coordinated update across all consuming repos.

**Release path:** all three repos (bluefin, bluefin-lts, dakota) use `bootc-build/create-release` as the factory-standard release action. It reads the SPDX-JSON SBOM already produced by `sign-and-publish`/`just sbom`, diffs it against the previous release, renders a release card (light + dark PNG), and generates supply-chain release notes with CNCF verification instructions (cosign, oras, slsa-verifier). bluefin-lts is stubbed pending SBOM artifact upload — see issue bluefin-lts#74.

---

## Mandatory gates

**Read-first:** Read `AGENTS.md`, `docs/SKILL.md`, and `.github/copilot-instructions.md` before touching any action.

**Skill contribution (enforced):** If you discover a pattern, fix a recurring mistake, or learn something that would help future agents — update the relevant file in `docs/skills/` in the **same PR** as your change. If no skill file exists for the area, create one and add it to the routing table in `docs/SKILL.md`. Skills live here, not in per-agent configs.

**Supply chain gates:** Every action that downloads external files (Containerfiles, scripts, configs) at build time must vendor those files into the action directory or verify their SHA-256 before use. Never pass a mutable URL directly to `buildah build` or `bash`. See `docs/skills/supply-chain.md` for the full pattern and the chunkah `Containerfile.splitter` vendoring procedure.

**SHA pinning:** Every `uses:` referencing a third-party action must be pinned to a full commit SHA with a version comment. PRs that introduce floating tags (`@main`, `@v3`) will be rejected.

**Pre-commit guard:** `no-floating-action-tags` blocks third-party `@main`/`@v*` floating action tags in workflow and composite action files. This repo's own `@v1` refs in consumer repos are exempted from the guard in those repos — they are managed floating tags deliberately advanced by this repo's release process.

**No breaking changes without a version signal:** Removing or renaming an input, or changing default behavior, requires coordinating with consuming repos. Document the blast radius in the PR description.

**Consumer validation (required before merging):** For any action change, open a draft PR in at least one consuming repo (`projectbluefin/bluefin` is the primary) pinned to your feature branch SHA. CI must pass there before merging to `main` and moving the `@v1` tag. The PR template's `Consumer PR`, `Consumer CI run`, and `Out-of-org consumer impact` fields are enforced by `.github/workflows/consumer-validation.yml`. See `docs/skills/consumer-validation.md` for the full protocol.

**Consumer validation "N/A" rules (enforced by CI):** `Consumer PR:` and `Consumer CI run:` must be real GitHub URLs — `https://github.com/projectbluefin/(bluefin|bluefin-lts|dakota)/pull/NNN` and `.../actions/runs/NNN` respectively. "N/A" is **only** accepted for `Out-of-org consumer impact:`. Even additive-only changes need a draft consumer PR to get a run URL. Bot/Renovate PRs (author login ending in `[bot]` or starting with `app/`) are exempt automatically.

**Consumer repos use `testing` as their active dev branch.** When opening consumer validation PRs or reading state in `projectbluefin/bluefin` or `projectbluefin/bluefin-lts`, always target `testing` — not `main`. Reading `main` gives stale state; PRs opened against `main` will need to be reverted.

**`gh run rerun` does not pick up workflow changes from `main`.** After merging a fix to a workflow file (e.g. `consumer-validation.yml`), re-running an old failed run still executes the original workflow from the HEAD branch commit. To trigger a run with the updated workflow, push a new commit to the PR branch (triggering a `synchronize` event) or admin-merge the PR directly.

**Skill files are procedures, not logs.** `docs/skills/` files must describe *how to do things* — patterns, commands, decision rules. Never record specific SHA hashes, PR numbers, current deployment status, or any point-in-time snapshot. Those become stale on the next commit and mislead future agents.

**Verification:** Every PR must confirm that the action change was exercised in a real workflow (link to a CI run or test job). No untested changes.

**Agents MUST NOT push directly to `main`.** All changes via PR from a feature branch. Branch protection enforces this; direct pushes are blocked for non-admins.

**`@v1` tag moves require human authorization.** Force-pushing the shared tag affects every consumer repo simultaneously. A human must run `git tag -f v1 && git push --force origin v1` after verifying CI is green. Do not initiate this as an agent action. Recommended cadence: after a batch of Renovate SHA pin bumps has landed on `main`, not after every individual merge.

**SBOM alignment:** the factory standard is Syft → SPDX-JSON, attached via ORAS and stored as a GitHub Actions artifact. `sign-and-publish` handles this for Fedora-based images. BST/dakota uses `just sbom` (also SPDX-JSON). All release notes must be generated from these SBOMs — never from separate container inspection scripts. bluefin-lts is the exception until issue bluefin-lts#74 is resolved.

**Production promotion in consumer repos is 2-human gated.** The `environment: production` gate on promotion/release workflows cannot be bypassed by changing actions here. Any change that could affect the promotion path requires explicit maintainer review. Admin bypasses are permanently logged in the Environment deployment history.

---

## PR Comment Policy

**One comment per PR event, max.** Combine all findings into a single comment.

**Never duplicate GitHub UI state.** Do not post CI pass/fail summaries or approval counts.

**When in doubt, don't post.** "Tests pass" = post nothing.

---

## Knowledge routing

**All learnings go to `docs/skills/`** — never to `.github/copilot-instructions.md` (that file is a pointer-only wrapper, read-only), and never to a personal agent config outside this repo.

After editing a skill file, commit it in the same PR as the triggering change.

> **Why:** Skills in this repo are the canonical reference. Personal agent configs are ephemeral and siloed. A fix discovered here belongs to every future agent working in this repo — not just the one that found it.
