# Actions Skill Router

Agent entry point for `projectbluefin/actions`. Load only the skill relevant to your task.

## Task → Skill

| I need to... | Load |
|---|---|
| Author or modify a composite action | `docs/skills/composite-actions.md` |
| Add a new action to the repo | `docs/skills/composite-actions.md` → "Adding a new action" |
| Debug a CI failure in a consuming repo | `docs/skills/composite-actions.md` → "Known workarounds" |
| Update a pinned SHA | `docs/skills/composite-actions.md` → "SHA pinning" |
| Understand the sign-and-publish flow | `docs/skills/composite-actions.md` → "sign-and-publish" |
| Understand the push-image push + digest pattern | `docs/skills/composite-actions.md` → "push-image" |
| Understand chunkah rechunking | `docs/skills/composite-actions.md` → "chunka" |
| Author or modify the reusable build workflow | `docs/skills/composite-actions.md` → "Reusable workflow" |
| Wire a consuming repo to the shared reusable workflow | `docs/skills/composite-actions.md` → "Reusable workflow" |
| Use these actions in a new or external bootc image repo | `docs/skills/consumer-guide.md` |
| Understand the Justfile contract for the reusable workflow | `docs/skills/consumer-guide.md` → "Justfile contract" |
| Wire a skill-drift check to a consumer repo | `docs/skills/consumer-guide.md` → "Checklist" + `docs/skills/factory-operations.md` |
| Audit non-deterministic surfaces in the factory | `docs/skills/determinism.md` |
| Find or report floating action tags | `docs/skills/determinism.md` → "Already pinned" or file a GitHub issue |
| Understand the gold standards for determinism | `docs/skills/determinism.md` → "Gold standards" |
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
| [`factory-operations.md`](skills/factory-operations.md) | Production gate (2-human approval), skill-drift PR check, and scheduled skill audit |
