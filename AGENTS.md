# AGENTS.md — projectbluefin/actions

> **Part of an agentic operating system, built by agentic workflows.**
> This repo is the canonical CI skills hub for the projectbluefin org. Every agent session here
> compounds the knowledge of all future agents. See the org-wide operating model:
> [`projectbluefin/.github/AGENTS.md`](https://github.com/projectbluefin/.github/blob/main/AGENTS.md)

Shared composite GitHub Actions for bootc image builders (bluefin, aurora, bazzite).

Load **[docs/SKILL.md](docs/SKILL.md)** before modifying any action.

---

## The System You Are Part Of

```
┌─────────────────────────────────────────────────────────────────┐
│  KubeStellar Hive  https://kubestellar.io/live/hive/bluefin/    │
│  AI-native Continuous Maturity Model (ACMM) orchestration       │
│  Agents run at increasing autonomy levels — you are one of them │
└────────────────────────┬────────────────────────────────────────┘
                         │
          ┌──────────────┴──────────────┐
          ▼                             ▼
┌─────────────────────┐     ┌──────────────────────────┐
│  bonedigger         │     │  kubestellar-bot          │
│  (client + bot)     │     │  (repo automation)        │
│                     │     │                           │
│  ujust report       │     │  Processes issues from    │
│  └─ agent collects  │────▶│  bonedigger pipeline      │
│     system state    │     │  Implements fixes, ships  │
│     humans can't    │     │  improvements back to     │
│  └─ files issue to  │     │  the image                │
│     image repo      │     │                           │
└─────────────────────┘     └──────────────────────────┘
         ▲                             │
         │                             │
         └─────────── ships ───────────┘
              better OS → better bonedigger → loop
```

**bonedigger** ([projectbluefin/bonedigger](https://github.com/projectbluefin/bonedigger)) is the
client + lifecycle bot. Users run `ujust report` — an agent collects system diagnostics, scrubs PII
on-device, and files an issue to the image repo. The bonedigger GitHub Actions lifecycle bot then
manages the pipeline: `filed → approved → queued → claimed → done`.

**kubestellar-bot** is the repo automation layer built on
[KubeStellar Hive](https://kubestellar.io/live/hive/bluefin/). It picks up queued issues,
dispatches agents to implement fixes and improvements, and ships them back.

**You** are an agent in this system. Your work compounds. Keep workflows deterministic and
repeatable for humans via Just.

---

## The Self-Improvement Loop

> **This is the core operating model. Read it before starting any task.**

Every agent session here produces two outputs:
1. **The work** — the PR, fix, or improvement.
2. **The learning** — what you discovered that a future agent should know.

Output 1 without Output 2 leaves the system no smarter. **The loop only compounds if agents write back.**

```
Agent works on task
  └─ discovers pattern / workaround / convention
       └─ writes it to the relevant skill file
            └─ commits in the same PR
                 └─ next agent starts smarter
                      └─ loop
```

### Skill-improvement mandate — applies to every repo in this org

**Before marking your work complete / before requesting final review:**

- [ ] Did I discover any workaround, non-obvious pattern, or convention?
- [ ] Is there a skill file for the area I worked in?
- [ ] If yes — did I update it?
- [ ] If no — did I create one?
- [ ] Is the skill file committed in this same PR?

For the full skill file format and where to write things, see the org-wide:
[`projectbluefin/.github/AGENTS.md`](https://github.com/projectbluefin/.github/blob/main/AGENTS.md)

### What counts as a learning worth writing back

**Write it:**
- A workaround for an upstream bug (include component + issue link)
- A non-obvious pattern required for correctness
- A convention that isn't obvious from the code
- Something you had to discover by trial and error

**Don't write it:**
- One-off task notes ("use commit message X for this PR")
- Obvious things any developer would know
- Ephemeral state ("currently broken, fix pending")

---

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

## Human Decision Points — Stop and Ask

Agents implement autonomously **except** at these gates. Stop and request human input:

| Gate | When |
|---|---|
| **Design Gate** | Architecture changes, new subsystem design, behavioral changes visible to consumers |
| **Security Gate** | Auth, signing, supply chain, secrets handling, SHA pinning for security-critical actions |
| **Breakage Gate** | Cross-repo breaking changes — removing/renaming inputs, changing defaults that affect consuming repos |
| **Merge Gate** | Final PR approval and merge — always human |

When in doubt, open a draft PR with your implementation and ask explicitly.

---

## Verification — Agents Implement and Verify; Humans Approve and Merge

Do not request review without evidence. Before opening a PR for review:

- Link to a CI run, workflow run, or test output that exercises your change
- If no automated test exists, describe how you manually verified the change
- Skill file update must be committed in the same PR (not a follow-up)

---

## Mandatory gates

**Read-first:** Read `AGENTS.md`, `docs/SKILL.md`, and `.github/copilot-instructions.md` before touching any action.

**Skill contribution (enforced):** If you discover a pattern, fix a recurring mistake, or learn something that would help future agents — update the relevant file in `docs/skills/` in the **same PR** as your change. If no skill file exists for the area, create one and add it to the routing table in `docs/SKILL.md`. Skills live here, not in per-agent configs.

**Supply chain gates:** Every action that downloads external files (Containerfiles, scripts, configs) at build time must vendor those files into the action directory or verify their SHA-256 before use. Never pass a mutable URL directly to `buildah build` or `bash`. See `docs/skills/supply-chain.md` for the full pattern, the chunkah `Containerfile.splitter` vendoring procedure, and the manifest-index-vs-platform-digest rule for OCI image pins. Routine chunkah upgrades are now fully automated via Renovate + `vendor-chunka-files.yml` — no manual steps required.

**SHA pinning:** Every `uses:` referencing a third-party action must be pinned to a full commit SHA with a version comment. PRs that introduce floating tags (`@main`, `@v3`) will be rejected.

**Pre-commit guard:** `no-floating-action-tags` blocks third-party `@main`/`@v*` floating action tags in workflow and composite action files. This repo's own `@v1` refs in consumer repos are exempted from the guard in those repos — they are managed floating tags deliberately advanced by this repo's release process.

**No breaking changes without a version signal:** Removing or renaming an input, or changing default behavior, requires coordinating with consuming repos. Document the blast radius in the PR description.

**Consumer validation (required before merging):** For any action change, open a draft PR in at least one consuming repo (`projectbluefin/bluefin` is the primary) pinned to your feature branch SHA. CI must pass there before merging to `main` and moving the `@v1` tag. The PR template's `Consumer PR`, `Consumer CI run`, and `Out-of-org consumer impact` fields are enforced by `.github/workflows/consumer-validation.yml`. See `docs/skills/consumer-validation.md` for the full protocol.

**Consumer validation "N/A" rules (enforced by CI):** `Consumer PR:` and `Consumer CI run:` must be real GitHub URLs — `https://github.com/projectbluefin/(bluefin|bluefin-lts|dakota)/pull/NNN` and `.../actions/runs/NNN` respectively. "N/A" is **only** accepted for `Out-of-org consumer impact:`. Even additive-only changes need a draft consumer PR to get a run URL. Bot/Renovate PRs (author login ending in `[bot]` or starting with `app/`) are exempt automatically.

**Consumer repo branches differ:** `projectbluefin/bluefin` uses `testing` as its active dev branch; `projectbluefin/bluefin-lts` uses `main`. When opening consumer validation PRs: target `testing` for bluefin, `main` for bluefin-lts. Never target `main` for bluefin — PRs opened there will need to be reverted.

**`gh run rerun` does not pick up workflow changes from `main`.** After merging a fix to a workflow file (e.g. `consumer-validation.yml`), re-running an old failed run still executes the original workflow from the HEAD branch commit. To trigger a run with the updated workflow, push a new commit to the PR branch (triggering a `synchronize` event) or admin-merge the PR directly.

**Skill files are procedures, not logs.** `docs/skills/` files must describe *how to do things* — patterns, commands, decision rules. Never record specific SHA hashes, PR numbers, current deployment status, or any point-in-time snapshot. Those become stale on the next commit and mislead future agents.

**Verification:** Every PR must confirm that the action change was exercised in a real workflow (link to a CI run or test job). No untested changes.

**Agents MUST NOT push directly to `main`.** All changes via PR from a feature branch. Branch protection enforces this; direct pushes are blocked for non-admins.

**`@v1` tag moves require human authorization.** Force-pushing the shared tag affects every consumer repo simultaneously. A human must run `git tag -f v1 && git push --force origin v1` after verifying CI is green. Do not initiate this as an agent action. Recommended cadence: after a batch of Renovate SHA pin bumps has landed on `main`, not after every individual merge.

**SBOM alignment:** the factory standard is Syft → SPDX-JSON, attached via ORAS and stored as a GitHub Actions artifact. `sign-and-publish` handles this for Fedora-based images. BST/dakota uses `just sbom` (also SPDX-JSON). All release notes must be generated from these SBOMs — never from separate container inspection scripts. bluefin-lts is the exception until issue bluefin-lts#74 is resolved.

**Production promotion in consumer repos is 2-human gated.** The `environment: production` gate on promotion/release workflows cannot be bypassed by changing actions here. Any change that could affect the promotion path requires explicit maintainer review. Admin bypasses are permanently logged in the Environment deployment history.

---

## 🚫 Absolute prohibition — ublue-os org

**NEVER create issues, pull requests, comments, forks, webhook calls, API writes, automated reports, or any other programmatic action targeting any `ublue-os/*` repository.**

This applies in every situation, without exception:
- Issues, comments, PRs, forks → **BANNED**
- Automated reports (CI notifications, diagnostic uploads) → **BANNED**
- `workflow_dispatch` or `repository_dispatch` calls to `ublue-os/*` → **BANNED**
- Any `gh` CLI command that writes to `ublue-os/*` → **BANNED**

If a task seems to require touching an upstream `ublue-os` repo → **stop and tell the human to report it manually.**

---

## PR Comment Policy

**One comment per PR event, max.** Combine all findings into a single comment.

**Never duplicate GitHub UI state.** Do not post CI pass/fail summaries or approval counts.

**When in doubt, don't post.** "Tests pass" = post nothing.

---

## Development Standards

### Commit format (required)

[Conventional Commits](https://www.conventionalcommits.org/): `<type>(<scope>): <description>`

Common types: `feat` `fix` `docs` `ci` `refactor` `chore` `build`

### AI attribution (required on every commit)

```
feat(actions): add container build optimization

Optimize multi-stage build to reduce image size.

Assisted-by: Claude Sonnet 4.6 via GitHub Copilot
Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>
```

Both trailers are required when an AI agent authors or substantially revises a commit.

---

## Knowledge routing

**All learnings go to `docs/skills/`** — never to `.github/copilot-instructions.md` (pointer-only wrapper, read-only), and never to a personal agent config outside this repo.

| You are working in... | Write to |
|---|---|
| `projectbluefin/actions` | `docs/skills/` |
| Any other projectbluefin repo | That repo's `docs/skills/` (create if absent) |
| ublue-os repos (aurora, bazzite) | **NEVER write to these repos** — see prohibition above |
| Cross-cutting (affects multiple repos) | Local first, then open propagation issue in `projectbluefin/actions` |

After editing a skill file, commit it in the same PR as the triggering change.

> **Why:** Skills in this repo are the canonical reference. Personal agent configs are ephemeral and siloed. A fix discovered here belongs to every future agent working in this repo — not just the one that found it.

---

## Repositories

### Core repos in scope for this actions library

| Repo | Role |
|---|---|
| [projectbluefin/bluefin](https://github.com/projectbluefin/bluefin) | Main OS image (Path 1 — reusable-build.yml) |
| [projectbluefin/bluefin-lts](https://github.com/projectbluefin/bluefin-lts) | LTS variant on CentOS Stream 10 (Path 2 — à la carte) |
| [projectbluefin/dakota](https://github.com/projectbluefin/dakota) | BuildStream image build (Path 2, partial adoption) |
| [projectbluefin/actions](https://github.com/projectbluefin/actions) | **This repo** — shared CI actions + canonical skills hub |
| [ublue-os/aurora](https://github.com/ublue-os/aurora) | KDE variant (Path 1, external — read-only) |
| [ublue-os/bazzite](https://github.com/ublue-os/bazzite) | Gaming variant (external — read-only) |

### Infrastructure

| Repo | Role |
|---|---|
| [projectbluefin/testsuite](https://github.com/projectbluefin/testsuite) | QA pipeline — Argo + KubeVirt + AT-SPI |
| [projectbluefin/bonedigger](https://github.com/projectbluefin/bonedigger) | Client reporting + issue lifecycle bot |
| [projectbluefin/housekeeping](https://github.com/projectbluefin/housekeeping) | Deprecated placeholder repo — org-wide automation lives in `projectbluefin/actions` |

---

## Build Tools

- **Just** — command runner (`just build`, `just test`, `just validate`, `just sbom`)
- **Podman / Buildah** — container building and layer manipulation
- **GitHub Actions** — CI/CD via composite actions and reusable workflows
- **Renovate** — automated dependency updates (SHA pins, digest bumps) — inherits from [projectbluefin/renovate-config](https://github.com/projectbluefin/renovate-config)
- **cosign** — keyless signing + attestation verification
- **syft / oras** — SBOM generation and OCI referrer attachment
- **Trivy** — CVE scanning before push
