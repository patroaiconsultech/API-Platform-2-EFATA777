from fastapi import Header, HTTPException

from orkio_platform.auth.introspection import (
    AuthProviderError,
    verify_bearer_token,
)
from orkio_platform.config import get_settings
from orkio_platform.domain.models import PrincipalContext


def _auth_error(
    code: str,
    message: str,
    *,
    status_code: int = 401,
) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={
            "code": code,
            "message": message,
        },
    )


def _bearer_token(
    authorization: str | None,
) -> str:
    if not authorization:
        raise _auth_error(
            "AUTH_TOKEN_REQUIRED",
            "A bearer access token is required.",
        )
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise _auth_error(
            "AUTH_TOKEN_INVALID",
            "The authorization header is invalid.",
        )
    return token.strip()


def get_principal(
    authorization: str | None = Header(default=None),
    x_tenant_id: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_role: str | None = Header(default=None),
) -> PrincipalContext:
    settings = get_settings()

    if settings.auth_mode == "oidc_introspection":
        if x_tenant_id or x_user_id or x_role:
            raise _auth_error(
                "AUTH_CONTEXT_CONFLICT",
                "Browser-controlled identity headers are forbidden.",
            )
        token = _bearer_token(authorization)
        try:
            verified = verify_bearer_token(
                token,
                settings,
            )
        except AuthProviderError as exc:
            raise _auth_error(
                exc.code,
                exc.message,
                status_code=exc.status_code,
            ) from exc
        return PrincipalContext(
            tenant_id=verified.tenant_id,
            user_id=verified.user_id,
            role=verified.role,
        )

    if settings.auth_mode == "external_required":
        raise _auth_error(
            "AUTH_PROVIDER_REQUIRED",
            "External authentication is required in this environment.",
        )

    if authorization:
        raise _auth_error(
            "AUTH_CONTEXT_CONFLICT",
            "Bearer tokens are not accepted in demo mode.",
        )
    if not x_tenant_id or not x_user_id:
        raise _auth_error(
            "AUTH_CONTEXT_REQUIRED",
            "Demo tenant and user headers are required.",
        )
    if (
        x_tenant_id not in settings.demo_allowed_tenants
        or x_user_id not in settings.demo_allowed_users
    ):
        raise _auth_error(
            "AUTH_CONTEXT_INVALID",
            "The demo identity is not allowed.",
        )

    normalized_role = (x_role or "member").strip().lower()
    if normalized_role == "admin":
        if (
            not settings.demo_admin_enabled
            or x_user_id not in settings.demo_admin_users
        ):
            raise _auth_error(
                "DEMO_ADMIN_DISABLED",
                "Demo administrator access is disabled.",
                status_code=403,
            )
    elif normalized_role != "member":
        raise _auth_error(
            "AUTH_CONTEXT_INVALID",
            "The demo identity is not allowed.",
        )

    try:
        return PrincipalContext(
            tenant_id=x_tenant_id,
            user_id=x_user_id,
            role=normalized_role,
        )
    except Exception:
        raise _auth_error(
            "AUTH_CONTEXT_INVALID",
            "The demo identity is not allowed.",
        ) from None


def require_admin(
    principal: PrincipalContext,
) -> PrincipalContext:
    if principal.role != "admin":
        raise _auth_error(
            "ADMIN_ROLE_REQUIRED",
            "Administrator role is required.",
            status_code=403,
        )
    return principal
