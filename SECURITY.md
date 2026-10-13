# Security

Do not open a public issue with credentials or an exploitable vulnerability.
Use this repository's **Security → Report a vulnerability** private reporting
feature. If it is unavailable, ask the maintainers to enable private reporting
without disclosing vulnerability details publicly.

This is a template, not a hosted service. Maintain your derived project's
dependencies, access controls, deployment environments, and security policy.
Only the latest release receives fixes.

Before production use:

- Enable GitHub secret scanning, push protection, dependency alerts, and code scanning.
- Configure production reviewers and main-only deployment branches.
- Keep Easy Auth enabled at ingress; principal headers are not credentials on
  an unprotected origin. Assign only the required application role.
- Verify image attestations and deploy immutable digests.
- Use managed identities, not credentials in source or command-line arguments.
