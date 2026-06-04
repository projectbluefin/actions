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
| Add upgrade/rollback testing to a bootc image repo | `docs/skills/consumer-guide.md` → "Upgrade test" |
| Use these actions in a new or external bootc image repo | `docs/skills/consumer-guide.md` |
| Understand the Justfile contract for the reusable workflow | `docs/skills/consumer-guide.md` → "Justfile contract" |
| Wire a skill-drift check to a consumer repo | `docs/skills/consumer-guide.md` → "Checklist" + `docs/skills/factory-operations.md` |
| Understand `force-compression` for CentOS Stream consumers | `docs/skills/composite-actions.md` → "Force-compression input rationale" |
| Understand zstd:chunked compression invariants or run regression tests | `docs/skills/composite-actions.md` → "Compression regression tests" |
| Audit non-deterministic surfaces in the factory | `docs/skills/determinism.md` |
| Verify SHA pins are correct and comments are accurate | `docs/skills/determinism.md` → "Already pinned" |
| Run a security audit of actions | `docs/skills/composite-actions.md` → "Shell steps" + "SHA Pinning" + `docs/skills/determinism.md` |
| Understand or configure the production gate (2-human approval) | `docs/skills/factory-operations.md` → "Production Gate" |
| Understand the skill-drift PR check | `docs/skills/factory-operations.md` → "Skill-Drift PR Check" |
| Understand the weekly skill audit | `docs/skills/factory-operations.md` → "Skill Audit" |
| Debug a stuck or missing Environment approval gate | `docs/skills/factory-operations.md` → "Troubleshooting" |

## Full Skill Index

| Skill | Covers |
|---|---|
| [`composite-actions.md`](skills/composite-actions.md) | Authoring conventions, known workarounds, action-by-action reference |
| [`consumer-guide.md`](skills/consumer-guide.md) | Onboarding a new image repo: full reusable workflow and à la carte composite actions |
| [`determinism.md`](skills/determinism.md) | Non-deterministic surfaces in the factory: classification, mitigations, investigations |
| [`factory-operations.md`](skills/factory-operations.md) | Production gate (2-human approval), skill-drift PR check, scheduled skill audit, and Renovate auto-merge |
