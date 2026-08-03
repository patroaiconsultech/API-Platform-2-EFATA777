from fastapi import APIRouter, Depends

from orkio_platform.api.dependencies import get_principal
from orkio_platform.config import get_settings
from orkio_platform.domain.models import PrincipalContext
from orkio_platform.version import (
    RELEASE_CANDIDATE,
    RELEASE_VERSION,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/status")
def auth_status() -> dict[str, object]:
    settings = get_settings()
    demo_enabled = settings.auth_mode == "demo_headers"
    oidc_enabled = (
        settings.auth_mode == "oidc_introspection"
        and settings.oidc_configured
    )

    demo_profile = None
    demo_admin_profile = None
    if demo_enabled:
        demo_profile = {
            "tenant_id": settings.demo_allowed_tenants[0],
            "user_id": settings.demo_allowed_users[0],
            "role": "member",
        }
        if (
            settings.demo_admin_enabled
            and settings.demo_admin_users
        ):
            demo_admin_profile = {
                "tenant_id": settings.demo_allowed_tenants[0],
                "user_id": settings.demo_admin_users[0],
                "role": "admin",
            }

    oidc_public_config = None
    if oidc_enabled:
        oidc_public_config = {
            "issuer": settings.oidc_issuer,
            "authorization_endpoint": (
                settings.oidc_authorization_endpoint
            ),
            "token_endpoint": (
                settings.oidc_token_endpoint
            ),
            "client_id": (
                settings.oidc_public_client_id
            ),
            "redirect_uri": settings.oidc_redirect_uri,
            "scopes": list(settings.oidc_scopes),
        }

    return {
        "candidate": RELEASE_CANDIDATE,
        "release_version": RELEASE_VERSION,
        "release_sha": settings.release_sha,
        "auth_mode": settings.auth_mode,
        "authenticated": False,
        "demo_available": demo_enabled,
        "demo_admin_enabled": (
            settings.demo_admin_enabled
            if demo_enabled
            else False
        ),
        "demo_profile": demo_profile,
        "demo_admin_profile": demo_admin_profile,
        "external_provider_configured": oidc_enabled,
        "oidc": oidc_public_config,
    }


@router.get("/me")
def authenticated_principal(
    principal: PrincipalContext = Depends(get_principal),
) -> dict[str, str]:
    return {
        "tenant_id": principal.tenant_id,
        "user_id": principal.user_id,
        "role": principal.role,
    }
