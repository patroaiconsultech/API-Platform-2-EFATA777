from __future__ import annotations

from fastapi import Header, HTTPException

from orkio_platform.domain.models import PrincipalContext


def get_principal(
    x_tenant_id: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_role: str = Header(default="member"),
) -> PrincipalContext:
    if not x_tenant_id or not x_user_id:
        raise HTTPException(
            status_code=401,
            detail={
                "code": "AUTH_CONTEXT_REQUIRED",
                "message": "X-Tenant-ID and X-User-ID are required in RC0.",
            },
        )
    try:
        return PrincipalContext(
            tenant_id=x_tenant_id,
            user_id=x_user_id,
            role=x_role,
        )
    except Exception:
        raise HTTPException(
            status_code=401,
            detail={
                "code": "AUTH_CONTEXT_INVALID",
                "message": "Invalid principal context.",
            },
        ) from None


def require_admin(principal: PrincipalContext) -> PrincipalContext:
    if principal.role != "admin":
        raise HTTPException(
            status_code=403,
            detail={
                "code": "ADMIN_ROLE_REQUIRED",
                "message": "Administrator role is required.",
            },
        )
    return principal
