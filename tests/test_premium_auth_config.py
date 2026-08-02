import pytest

from orkio_platform.config import get_settings


OIDC_ENV = {
    "PLATFORM_AUTH_MODE": "oidc_introspection",
    "PLATFORM_OIDC_ISSUER": "https://issuer.example",
    "PLATFORM_OIDC_AUDIENCE": "orkio-api",
    "PLATFORM_OIDC_AUTHORIZATION_ENDPOINT":
        "https://issuer.example/authorize",
    "PLATFORM_OIDC_TOKEN_ENDPOINT":
        "https://issuer.example/token",
    "PLATFORM_OIDC_INTROSPECTION_ENDPOINT":
        "https://issuer.example/introspect",
    "PLATFORM_OIDC_PUBLIC_CLIENT_ID": "orkio-spa",
    "PLATFORM_OIDC_INTROSPECTION_CLIENT_ID":
        "orkio-api",
    "PLATFORM_OIDC_INTROSPECTION_CLIENT_SECRET":
        "synthetic-test-secret",
    "PLATFORM_OIDC_REDIRECT_URI":
        "https://app.example/auth/callback",
}


def apply(monkeypatch, values):
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()


def test_oidc_mode_requires_complete_configuration(
    monkeypatch,
):
    monkeypatch.setenv(
        "PLATFORM_AUTH_MODE",
        "oidc_introspection",
    )
    get_settings.cache_clear()
    with pytest.raises(
        ValueError,
        match="OIDC_CONFIGURATION_INCOMPLETE",
    ):
        get_settings()


def test_production_oidc_configuration_is_accepted(
    monkeypatch,
):
    apply(
        monkeypatch,
        {
            **OIDC_ENV,
            "PLATFORM_ENVIRONMENT": "production",
            "PLATFORM_ALLOWED_ORIGINS":
                "https://app.example",
        },
    )
    settings = get_settings()
    assert settings.oidc_configured is True
    assert settings.allow_demo_identity_headers is False


def test_demo_headers_fail_closed_in_production(
    monkeypatch,
):
    apply(
        monkeypatch,
        {
            "PLATFORM_ENVIRONMENT": "production",
            "PLATFORM_AUTH_MODE": "demo_headers",
        },
    )
    with pytest.raises(
        ValueError,
        match=(
            "DEMO_IDENTITY_HEADERS_FORBIDDEN_IN_PRODUCTION"
        ),
    ):
        get_settings()


def test_demo_admin_requires_explicit_user_allowlist(
    monkeypatch,
):
    monkeypatch.delenv(
        "PLATFORM_DEMO_ADMIN_USERS",
        raising=False,
    )
    apply(
        monkeypatch,
        {
            "PLATFORM_ENVIRONMENT": "rc1-test",
            "PLATFORM_AUTH_MODE": "demo_headers",
            "PLATFORM_DEMO_ALLOWED_USERS":
                "user-demo,admin-demo",
            "PLATFORM_DEMO_ADMIN_ENABLED": "true",
        },
    )
    with pytest.raises(
        ValueError,
        match="DEMO_ADMIN_USERS_REQUIRED",
    ):
        get_settings()
