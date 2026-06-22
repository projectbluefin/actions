# Factory Improvements

Append one line per meaningful shipped improvement.
Format: `- YYYY-MM-DD: <description> ([#NNN](url))`

---

- 2026-06-18: sync 7 skill files with code patterns from 2 weeks of CI fixes (chunka tmpdir, push-image buildah+authfile, Syft large-image patterns, promote-squash enqueuePullRequest, E2E gate SHA locking, sync-branches GH_TOKEN) ([#258](https://github.com/projectbluefin/actions/pull/258))
- 2026-06-18: add detect-changes image_flavors bats tests; wire 89-test bats suite into CI (was running locally-only) ([#259](https://github.com/projectbluefin/actions/pull/259))
- 2026-06-18: add push-image retry/alias/force-compression tests (16) and sign-and-publish keyless/key validation tests (12); document inline YAML shell testing pattern ([#260](https://github.com/projectbluefin/actions/pull/260))
- 2026-06-18: close 5 stale/duplicate issues (#192 #197 #200 #203 already fixed by PR #217; #205 already fixed by PR #217)
