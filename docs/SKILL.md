# Actions Skill Router

Agent entry point for `projectbluefin/actions`. Load only the skill relevant to your task.

## Task → Skill

| I need to... | Load |
|---|---|
| Detect changed paths for PR build matrix | `docs/skills/composite-actions.md` → "detect-changes" |
| Validate a PR (just check, shellcheck, hadolint, pre-commit) | `docs/skills/composite-actions.md` → "validate-pr" |
| Author or modify a composite action | `docs/skills/composite-actions.md` |
| Add a new action to the repo | `docs/skills/composite-actions.md` → "Adding a new action" |
| Debug a CI failure in a consuming repo | `docs/skills/composite-actions.md` → "Known workarounds" |
| Configure or understand Renovate auto-merge | `docs/skills/factory-operations.md` → "Renovate" |
| Update a pinned SHA | `docs/skills/composite-actions.md` → "SHA pinning" |
| Understand the sign-and-publish flow | `docs/skills/composite-actions.md` → "sign-and-publish" |
| Understand the push-image push + digest pattern | `docs/skills/composite-actions.md` → "push-image" |
| Generate OCI image tags in a custom pipeline | `docs/skills/composite-actions.md` → "generate-tags" |
| Assemble a multi-arch OCI manifest index | `docs/skills/composite-actions.md` → "create-manifest" |
| Understand chunkah rechunking | `docs/skills/composite-actions.md` → "chunka" |
| Author or modify the reusable build workflow | `docs/skills/composite-actions.md` → "Reusable workflow" |
| Understand when to use `generate-tags` vs `just generate-build-tags` | `docs/skills/composite-actions.md` → "generate-tags" + "Reusable workflow" |
| Wire a consuming repo to the shared reusable workflow | `docs/skills/composite-actions.md` → "Reusable workflow" |
| Validate action changes against consumers before merge | `docs/skills/consumer-validation.md` |
| Understand the consumer-validation PR check | `docs/skills/consumer-validation.md` |
| Add upgrade/rollback testing to a bootc image repo | `docs/skills/consumer-guide.md` → "Upgrade test" |
| Use these actions in a new or external bootc image repo | `docs/skills/consumer-guide.md` |
| Understand the Justfile contract for the reusable workflow | `docs/skills/consumer-guide.md` → "Justfile contract" |
| Wire a skill-drift check to a consumer repo | `docs/skills/consumer-guide.md` → "Checklist" + `docs/skills/factory-operations.md` |
| Understand `force-compression` for CentOS Stream consumers | `docs/skills/composite-actions.md` → "Force-compression input rationale" |
| Understand zstd:chunked compression invariants or run regression tests | `docs/skills/composite-actions.md` → "Compression regression tests" |
| Audit non-deterministic surfaces in the factory | `docs/skills/determinism.md` |
| Verify SHA pins are correct and comments are accurate | `docs/skills/determinism.md` → "Already pinned" |
| Add or scan an image for CVEs before push | `docs/skills/supply-chain.md` → "shift-left CVE scanning" + `docs/skills/composite-actions.md` → "scan-image" |
| Generate release notes and create a GitHub Release | `docs/skills/composite-actions.md` → "generate-release-notes" + "reusable-release.yml" |
| Enforce Conventional Commits PR title format | `docs/skills/composite-actions.md` → "validate-pr-title" |
| Understand SLSA Build L2 posture and scope | `docs/skills/supply-chain.md` → "SLSA Build L2 posture" |
| Verify a built image attestation | `docs/skills/supply-chain.md` → "Verification" |
| Add or update cosign verify scoping | `docs/skills/supply-chain.md` → "scope cosign verify" |
| Add or update Trivy CVE scanning | `docs/skills/supply-chain.md` → "shift-left CVE scanning" |
| Vendor or hash-verify an external build file | `docs/skills/supply-chain.md` → "vendor external build instruction files" |
| Understand or configure the production gate (2-human approval) | `docs/skills/factory-operations.md` → "Production Gate" |
| Understand the skill-drift PR check | `docs/skills/factory-operations.md` → "Skill-Drift PR Check" |
| Understand the weekly skill audit | `docs/skills/factory-operations.md` → "Skill Audit" |
| Debug a stuck or missing Environment approval gate | `docs/skills/factory-operations.md` → "Troubleshooting" |

## Full Skill Index

| Skill | Covers |
|---|---|
| [`composite-actions.md`](skills/composite-actions.md) | Authoring conventions, known workarounds, action-by-action reference |
| [`consumer-guide.md`](skills/consumer-guide.md) | Onboarding a new image repo: full reusable workflow and à la carte composite actions |
| [`consumer-validation.md`](skills/consumer-validation.md) | Required consumer validation flow and blast radius before merge |
| [`determinism.md`](skills/determinism.md) | Non-deterministic surfaces in the factory: classification, mitigations, investigations |
| [`factory-operations.md`](skills/factory-operations.md) | Production gate (2-human approval), skill-drift PR check, scheduled skill audit, and Renovate auto-merge |
| [`supply-chain.md`](skills/supply-chain.md) | SLSA Build L2 posture, SBOM attestation, cosign verify scoping, Trivy CVE scanning, vendoring external build files |
