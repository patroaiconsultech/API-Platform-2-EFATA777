# ORKIO Railway Docker Runtime Patch

Status: proposal-only. No repository or deployment was modified.

## Root cause addressed

Railpack build imports succeeded, but the final runtime image started without
`uvicorn`. This patch uses a single Docker image where dependency installation
and runtime share the same Python environment.

## Files to upload to the repository

- `Dockerfile` at repository root
- `.dockerignore` at repository root
- `src/orkio_platform/config.py`
- `src/orkio_platform/main.py`

## Railway cleanup

Remove these variables before redeploying:

- RAILPACK_INSTALL_CMD
- RAILPACK_BUILD_CMD
- RAILPACK_START_CMD
- RAILPACK_DISABLE_CACHES
- RAILPACK_VERBOSE
- RAILPACK_PYTHON_VERSION

Clear custom Build Command and Start Command in the Railway dashboard.
The Dockerfile CMD becomes the start command.

Keep:

- PLATFORM_ALLOWED_ORIGINS=https://app-platform-2-efata777-production.up.railway.app
- PLATFORM_PUBLIC_BASE_URL=https://api-platform-2-efata777-production.up.railway.app
- PLATFORM_DEMO_IDENTITY_HEADERS_ENABLED=true (recovery only)
- PLATFORM_TENANT_RESOLUTION_MODE=demo_headers (recovery only)

Healthcheck:

- `/api/health`
- timeout 300 seconds

## Validation

Build log must show Dockerfile detection and successful `pip install .`.
Deploy log must show Uvicorn listening on `0.0.0.0`.
`GET /api/health` must return HTTP 200.
Preflight `OPTIONS /api/agents` must return a non-502 response with the
frontend origin allowed.
