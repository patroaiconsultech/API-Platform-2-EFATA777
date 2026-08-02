from types import SimpleNamespace

import pytest

from orkio_platform.auth.introspection import (
    AuthProviderError,
    map_introspection_claims,
)


def settings(**overrides):
    values = {
        "oidc_issuer": "https://issuer.example",
        "oidc_audience": "orkio-api",
        "oidc_user_claim": "sub",
        "oidc_tenant_claim": "tenant_id",
        "oidc_roles_claim": "roles",
        "oidc_admin_roles": ("orkio_admin",),
        "oidc_member_roles": ("orkio_member",),
        "oidc_clock_skew_seconds": 30,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def claims(**overrides):
    values = {
        "active": True,
        "iss": "https://issuer.example",
        "aud": ["orkio-api"],
        "exp": 2_000,
        "sub": "user-1",
        "tenant_id": "tenant-1",
        "roles": ["orkio_member"],
    }
    values.update(overrides)
    return values


def test_member_identity_is_mapped_from_verified_claims():
    principal = map_introspection_claims(
        claims(),
        settings(),
        now=1_000,
    )
    assert principal.tenant_id == "tenant-1"
    assert principal.user_id == "user-1"
    assert principal.role == "member"


def test_admin_role_is_server_resolved():
    principal = map_introspection_claims(
        claims(roles=["orkio_member", "orkio_admin"]),
        settings(),
        now=1_000,
    )
    assert principal.role == "admin"


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"active": False}, "AUTH_TOKEN_INACTIVE"),
        (
            {"iss": "https://wrong.example"},
            "AUTH_TOKEN_ISSUER_INVALID",
        ),
        (
            {"aud": ["another-api"]},
            "AUTH_TOKEN_AUDIENCE_INVALID",
        ),
        ({"exp": 900}, "AUTH_TOKEN_EXPIRED"),
        (
            {"tenant_id": ""},
            "AUTH_MEMBERSHIP_CLAIMS_REQUIRED",
        ),
        (
            {"roles": ["unrelated"]},
            "AUTH_ROLE_NOT_AUTHORIZED",
        ),
    ],
)
def test_invalid_identity_fails_closed(change, code):
    with pytest.raises(AuthProviderError) as captured:
        map_introspection_claims(
            claims(**change),
            settings(),
            now=1_000,
        )
    assert captured.value.code == code


def test_nested_claim_paths_are_supported():
    principal = map_introspection_claims(
        claims(
            identity={
                "user": "user-nested",
                "tenant": "tenant-nested",
                "roles": ["orkio_member"],
            }
        ),
        settings(
            oidc_user_claim="identity.user",
            oidc_tenant_claim="identity.tenant",
            oidc_roles_claim="identity.roles",
        ),
        now=1_000,
    )
    assert principal.user_id == "user-nested"
    assert principal.tenant_id == "tenant-nested"
