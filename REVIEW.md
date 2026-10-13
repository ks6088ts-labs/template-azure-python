# Review checklist

- Are changed code paths covered by regression tests and type checks?
- Does the API reject stale updates, malformed identities, and oversized pages?
- Are readiness probes checking dependencies without returning sensitive details?
- Do production settings disable API documentation and require protected ingress?
- Do logs avoid secrets and retain trace correlation without duplicate handlers?
- Are workflow permissions least-privilege, inputs passed through environment
  variables, external actions pinned, and fork PRs isolated from deployment tokens?
- Does deployment verify provenance and promote the tested image digest?
- Are production approvals and environment-scoped OIDC prerequisites documented?
