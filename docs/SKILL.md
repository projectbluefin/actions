# Actions Skill Router

Agent entry point for `projectbluefin/actions`. Load only the skill relevant to your task.

> Skill format reference: [`projectbluefin/.github/AGENTS.md`](https://github.com/projectbluefin/.github/blob/main/AGENTS.md)

## Task → Skill

| I need to... | Load |
|---|---|
| Create or update a skill file (format, frontmatter, structure) | [`projectbluefin/.github/AGENTS.md`](https://github.com/projectbluefin/.github/blob/main/AGENTS.md) |
| Detect changed paths for PR build matrix | `docs/skills/composite-actions/action-reference.md` → "detect-changes" |
| Validate a PR (just check, shellcheck, hadolint, pre-commit) | `docs/skills/composite-actions/action-reference.md` → "validate-pr" |
| Author or modify a composite action | `docs/skills/composite-actions.md` |
| Add a new action to the repo | `docs/skills/composite-actions.md` → "Adding a new action" |
| Debug a CI failure in a consuming repo | `docs/skills/composite-actions.md` → "Known workarounds" |
| Configure or understand Renovate auto-merge | `docs/skills/factory-operations.md` → "Renovate" |
| Update a third-party SHA pin | `docs/skills/composite-actions.md` → "SHA Pinning" |
| Understand `@v1` tag and how to advance it | AGENTS.md → "@v1 tag" section |
| Understand or change the promotion PR body format (Design C) | `docs/skills/factory-operations.md` → "Promotion PR Format" |
| Understand the sign-and-publish flow | `docs/skills/composite-actions/action-reference.md` → "sign-and-publish" |
| Understand the push-image push + digest pattern | `docs/skills/composite-actions/action-reference.md` → "push-image" |
| Generate OCI image tags in a custom pipeline | `docs/skills/composite-actions/action-reference.md` → "generate-tags" |
| Assemble a multi-arch OCI manifest index | `docs/skills/composite-actions/action-reference.md` → "create-manifest" |
| Understand chunkah rechunking | `docs/skills/composite-actions/action-reference.md` → "chunka" |
| Author or modify the reusable build workflow | `docs/skills/composite-actions/reusable-workflow.md` |
| Understand when to use `generate-tags` vs `just generate-build-tags` | `docs/skills/composite-actions/action-reference.md` → "generate-tags" + `docs/skills/composite-actions/reusable-workflow.md` → "Tag generation" |
| Wire a consuming repo to the shared reusable workflow | `docs/skills/consumer-guide.md` |
| Validate action changes against consumers before merge | `docs/skills/consumer-validation.md` |
| Understand the consumer-validation PR check | `docs/skills/consumer-validation.md` |
| Add upgrade/rollback testing to a bootc image repo | `docs/skills/consumer-guide/upgrade-and-migration.md` → "Upgrade test" |
| Use these actions in a new or external bootc image repo | `docs/skills/consumer-guide.md` |
| Understand the Justfile contract for the reusable workflow | `docs/skills/consumer-guide.md` → "Path 1" |
| Wire a new bootc image repo to use these actions | `docs/skills/consumer-guide.md` → "Checklist" |
| Understand `force-compression` for CentOS Stream consumers | `docs/skills/composite-actions.md` → "Force-compression input rationale" |
| Understand zstd:chunked compression invariants or run regression tests | `docs/skills/composite-actions/action-reference.md` → "chunka" |
| Audit non-deterministic surfaces in the factory | `docs/skills/determinism.md` |
| Verify SHA pins are correct and comments are accurate | `docs/skills/determinism.md` → "Already pinned" |
| Add or scan an image for CVEs before push | `docs/skills/supply-chain.md` → "shift-left CVE scanning" + `docs/skills/composite-actions/action-reference.md` → "scan-image" |
| Add or modify Python unit tests | `docs/skills/testing.md` |
| Understand or change the pytest coverage threshold | `docs/skills/testing.md` |
| Add bats tests for a shell script or inline action shell step | `docs/skills/testing.md` → "Shell scripts (bats)" + "Testing shell logic embedded in action YAML" |
| Wire a new bats test into CI | `docs/skills/testing.md` → "Shell scripts (bats)" (bats job in `unit-tests.yml`) |
| Debug why unit-tests CI fails (coverage or test failures) | `docs/skills/testing.md` |
| Understand or debug the promotion PR body or gate checklist | `docs/skills/factory-operations.md` → "Promotion PR Format" |
| Create a release with SBOM diff, release card, and supply chain verification instructions | `docs/skills/composite-actions/action-reference.md` → "create-release" |
| Enforce Conventional Commits PR title format | `docs/skills/composite-actions/action-reference.md` → "validate-pr-title" |
| Understand SLSA Build L2 posture and scope | `docs/skills/supply-chain.md` → "SLSA Build L2 posture" |
| Verify a built image attestation | `docs/skills/supply-chain.md` → "Verification" |
| Add or update cosign verify scoping | `docs/skills/supply-chain.md` → "scope cosign verify" |
| Add or update Trivy CVE scanning | `docs/skills/supply-chain.md` → "shift-left CVE scanning" |
| Vendor or hash-verify an external build file | `docs/skills/supply-chain.md` → "vendor external build instruction files" |
| Understand or configure the production gate (2-human approval) | `docs/skills/factory-operations.md` → "Production Gate" |
| Monitor factory success rates or configure scheduled health alerts | `docs/skills/factory-operations.md` → "Factory Health Monitor" |
| Debug a stuck or missing Environment approval gate | `docs/skills/factory-operations.md` → "Troubleshooting" |
| Understand dakota-specific action adoption | `docs/skills/consumer-guide/upgrade-and-migration.md` → "Dakota" |
| Wire migration testing across registries | `docs/skills/consumer-guide/upgrade-and-migration.md` → "Migration test" |

## Full Skill Index

| Skill | Covers |
|---|---|
| [`testing.md`](skills/testing.md) | pytest setup, coverage baseline (60%), uncovered lines, threshold rules |
| [`composite-actions.md`](skills/composite-actions.md) | Authoring conventions, action catalog, rollout strategy, CI-fix-first workflow, known workarounds |
| [`composite-actions/action-reference.md`](skills/composite-actions/action-reference.md) | Full action-by-action reference for all bootc-build composite actions |
| [`composite-actions/reusable-workflow.md`](skills/composite-actions/reusable-workflow.md) | reusable-build.yml and reusable-release.yml details, cross-repo refs, digest shape |
| [`consumer-guide.md`](skills/consumer-guide.md) | Onboarding a new image repo: Path 1 (reusable workflow) and Path 2 (à la carte), checklist |
| [`consumer-guide/upgrade-and-migration.md`](skills/consumer-guide/upgrade-and-migration.md) | Upgrade test gate, migration test, dakota Path 2 notes, live consumer examples |
| [`consumer-validation.md`](skills/consumer-validation.md) | Required consumer validation flow and blast radius before merge |
| [`determinism.md`](skills/determinism.md) | Non-deterministic surfaces in the factory: classification, mitigations, investigations |
| [`factory-operations.md`](skills/factory-operations.md) | Production gate (2-human approval), factory health monitor, Renovate auto-merge, promotion PR format (Design C) |
| [`supply-chain.md`](skills/supply-chain.md) | SLSA Build L2 posture, SBOM attestation, cosign verify scoping, Trivy CVE scanning, vendoring external build files |
