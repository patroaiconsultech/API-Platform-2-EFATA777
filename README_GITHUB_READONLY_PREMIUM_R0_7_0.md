# ORKIO R0.7.0 — GitHub Readonly Premium Connector

Status: audit candidate  
Contract: `github_readonly_v1`  
Orion bridge: `orion_repository_audit_v1`

## Purpose

This connector gives Orion bounded, backend-only, read-only access to
explicitly allowlisted GitHub repositories for evidence-based audits.

It does not expose repository credentials to the browser or to the model.
It does not implement repository writes, branch creation, commits, pull
requests, merges, workflow dispatch, migrations, or deployment.

## Security contract

The connector enforces:

- GitHub App or token authentication on the backend only;
- explicit repository allowlist;
- official GitHub REST API host only;
- REST API version pinning;
- role, tenant, and user authorization gates;
- bounded tree, file, response, character, and deadline limits;
- UTF-8 text-only file reads;
- denied paths for `.env`, credentials, secrets, private keys, and `.git`;
- secret redaction before repository evidence reaches the LLM;
- prompt-injection boundary around untrusted repository content;
- fail-closed startup when any write flag is enabled;
- metadata-only structured audit logs.

GitHub App is the recommended production authentication mode.

## Required GitHub App permissions

Repository permissions:

```text
Contents: Read-only
Metadata: Read-only
```

Install the App only on the repositories approved for ORKIO audits.

## Backend environment block

```dotenv
PLATFORM_GITHUB_INTEGRATION_ENABLED=true
PLATFORM_GITHUB_READ_ONLY=true
PLATFORM_GITHUB_AUTH_MODE=github_app

PLATFORM_GITHUB_APP_ID=<GITHUB_APP_ID>
PLATFORM_GITHUB_APP_INSTALLATION_ID=<INSTALLATION_ID>
PLATFORM_GITHUB_APP_PRIVATE_KEY_B64=<BASE64_PEM_PRIVATE_KEY>

PLATFORM_GITHUB_API_BASE_URL=https://api.github.com
PLATFORM_GITHUB_API_VERSION=2026-03-10

PLATFORM_GITHUB_ALLOWED_REPOSITORIES=patroaiconsultech/ORKIO_FRONTEND_AO67L_CONSOLIDATED_RC_FULL,patroaiconsultech/ORKIO_BACKEND_AO67K_CONSOLIDATED_RC_FULL
PLATFORM_GITHUB_DEFAULT_REF=main

PLATFORM_GITHUB_ALLOWED_ROLES=admin
PLATFORM_GITHUB_ALLOWED_TENANTS=<AUTHORIZED_TENANT_ID>
PLATFORM_GITHUB_ALLOWED_USERS=<AUTHORIZED_ADMIN_USER_ID>
PLATFORM_GITHUB_ORION_AUTO_AUDIT_ENABLED=true

PLATFORM_GITHUB_HTTP_TIMEOUT_SECONDS=20
PLATFORM_GITHUB_AUDIT_DEADLINE_SECONDS=60
PLATFORM_GITHUB_MAX_RESPONSE_BYTES=8000000
PLATFORM_GITHUB_MAX_TREE_ENTRIES=5000
PLATFORM_GITHUB_MAX_FILES_PER_AUDIT=24
PLATFORM_GITHUB_MAX_FILE_BYTES=250000
PLATFORM_GITHUB_MAX_TOTAL_CHARS=80000

PLATFORM_GITHUB_ALLOW_METADATA_READ=true
PLATFORM_GITHUB_ALLOW_CONTENT_READ=true
PLATFORM_GITHUB_ALLOW_DIFF_READ=true

PLATFORM_GITHUB_ALLOW_WRITE=false
PLATFORM_GITHUB_ALLOW_BRANCH_CREATE=false
PLATFORM_GITHUB_ALLOW_COMMIT=false
PLATFORM_GITHUB_ALLOW_PULL_REQUEST=false
PLATFORM_GITHUB_ALLOW_MERGE=false
PLATFORM_GITHUB_ALLOW_WORKFLOW_DISPATCH=false
```

Do not create any `VITE_GITHUB_*` variable. Secrets belong only to the backend.

## Private key encoding

Encode the complete PEM private key as one base64 value before storing it in
the backend secret manager. Do not commit the PEM file or the encoded value.

## Controlled activation

1. Upload the patch to an isolated branch.
2. Review the diff.
3. Deploy with `PLATFORM_GITHUB_INTEGRATION_ENABLED=false`.
4. Register the GitHub App and install it only on approved repositories.
5. Add backend-only secrets.
6. Enable the connector while keeping Orion auto-audit disabled.
7. Call the admin probe endpoint.
8. Confirm all repositories return a commit SHA and `read_only=true`.
9. Enable `PLATFORM_GITHUB_ORION_AUTO_AUDIT_ENABLED=true`.
10. Run an Orion readonly audit and inspect structured logs.

## Admin endpoints

```text
GET  /api/agents/repository-connector/status
POST /api/agents/repository-connector/probe
```

Both endpoints require the canonical `admin` role.

## Rollback

```text
PLATFORM_GITHUB_ORION_AUTO_AUDIT_ENABLED=false
PLATFORM_GITHUB_INTEGRATION_ENABLED=false
```

Then redeploy the previous backend artifact or revert the isolated patch
commit. No database migration is introduced by this connector.
