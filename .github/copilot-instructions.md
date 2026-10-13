# Repository instructions

Follow AGENTS.md and REVIEW.md. Use existing Makefile checks and focused pytest
regressions. Keep domain/application code independent of FastAPI and Azure SDKs;
read environment configuration only in settings modules. Do not introduce
credentials, log settings, run paid evaluations, or deploy/delete Azure resources.
Workflow changes must retain SHA pinning, least privilege, merge-queue coverage,
credential-free checkout, attestation verification, and environment approvals.
