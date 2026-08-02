# Railway RC1 Test Profile

Apply only to the isolated RC1 backend service:

```text
PLATFORM_ENVIRONMENT=rc1-test
PLATFORM_AUTH_MODE=demo_headers
PLATFORM_DEMO_IDENTITY_HEADERS_ENABLED=true
PLATFORM_DEMO_TENANT_ID=tenant-demo
PLATFORM_DEMO_USER_ID=user-demo
PLATFORM_DEMO_ALLOWED_TENANTS=tenant-demo
PLATFORM_DEMO_ALLOWED_USERS=user-demo
PLATFORM_DEMO_ADMIN_ENABLED=false
```

Preserve the existing database and Psycopg R0.3.1 settings.

Do not use this profile for a service containing real tenants or production
data. Production must remain `external_required` until a real provider is
implemented and validated.
