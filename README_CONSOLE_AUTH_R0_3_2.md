# ORKIO Backend — Console Auth Hardening R0.3.2

## RC1 test mode

```text
PLATFORM_ENVIRONMENT=rc1-test
PLATFORM_AUTH_MODE=demo_headers
PLATFORM_DEMO_ALLOWED_TENANTS=tenant-demo
PLATFORM_DEMO_ALLOWED_USERS=user-demo
PLATFORM_DEMO_ADMIN_ENABLED=false
```

The browser identity is accepted only when it matches the configured
tenant/user allowlists. Demo administrator access is disabled by default.

## Production-safe mode

```text
PLATFORM_ENVIRONMENT=production
PLATFORM_AUTH_MODE=external_required
```

In this mode the public `/api/auth/status` route reports that external
authentication is required. Protected routes reject demo identity headers.

Setting `demo_headers` while `PLATFORM_ENVIRONMENT=production` fails closed
during settings validation.

## Public/authenticated routes

```text
GET /api/auth/status   public
GET /api/auth/me       protected
```

This package does not implement an external identity provider. Production
authentication remains a separate gate.
