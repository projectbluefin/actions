# Security Policy

## Supported Versions

Security fixes are applied to the current `@v1` tag only. Previous major versions are not maintained.

| Version | Supported |
|---------|-----------|
| `@v1` (current) | ✅ |
| older tags | ❌ |

## Reporting a Vulnerability

**Please do not open a public GitHub issue for security vulnerabilities.**

Report security vulnerabilities via GitHub Security Advisories:
👉 https://github.com/projectbluefin/actions/security/advisories/new

We aim to acknowledge reports within **5 business days** and will coordinate a disclosure timeline with the reporter.

## Scope

This repository contains shared composite GitHub Actions and reusable workflows used by bootc image builders (bluefin, aurora, bazzite, and related consumers).

Security issues in scope include:
- Script injection vulnerabilities in composite action shell steps
- Supply chain risks (unverified external downloads, floating action refs)
- Privilege escalation in runner jobs (excessive `GITHUB_TOKEN` permissions)
- Secrets exposure in workflow logs

Out of scope:
- Vulnerabilities in upstream tools such as Trivy, cosign, and buildah — report those to their respective projects
- Vulnerabilities in consumer images built using these actions — report those to the consuming repository

## Security Practices

This repository follows these security practices:
- All third-party `uses:` references are pinned to full commit SHAs
- OIDC keyless signing via Sigstore/Fulcio is supported for published images
- SLSA Build Level 2 provenance is emitted for GitHub-hosted reusable builds
- SPDX SBOM generation and attestation are supported by the publish pipeline
- Trivy CVE scanning is available before image push, with SARIF upload to GitHub Security
- Reusable workflows default to `permissions: {}` and grant access per job as needed
- External build files must be vendored or verified with SHA-256 before use
