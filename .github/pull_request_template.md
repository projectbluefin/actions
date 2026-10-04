## What does this change?

<!-- Brief description -->

## Consumer validation

Required for consumer-facing composites and reusable workflows. Production uses managed `@v1`; a reviewed first-party candidate source is permitted only in the read-only onboarding preview.

Consumer PR: <!-- actual opted-in consumer PR URL -->
Consumer CI run: <!-- actual matching consumer run exercising this change -->
Out-of-org consumer impact: <!-- explain why aurora/bazzite are safe, or say N/A -->

- [ ] Opened a consumer PR using `@v1` production references (read-only candidate preview only when bootstrapping)
- [ ] Linked a passing consumer CI run that exercised this change
- [ ] Evaluated out-of-org consumers (`ublue-os/aurora`, `ublue-os/bazzite`) and documented the impact above

## Checklist

- [ ] I am using an agent and I take responsibility for this PR (if AI-assisted)
- [ ] Conventional commit message (`feat:`, `fix:`, `chore:`, etc.)
- [ ] No hardcoded secrets or credentials
