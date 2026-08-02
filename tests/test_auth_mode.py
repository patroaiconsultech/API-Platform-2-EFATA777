import pytest
from fastapi.testclient import TestClient

from orkio_platform.config import get_settings
from orkio_platform.main import create_app


def test_auth_status_is_public_and_declares_demo_profile(client):
    response = client.get("/api/auth/status")
    assert response.status_code == 200
    body = response.json()
    assert body["auth_mode"] == "demo_headers"
    assert body["demo_available"] is True
    assert body["demo_profile"] == {
        "tenant_id": "tenant-a",
        "user_id": "user-a",
        "role": "member",
    }
    assert body["external_provider_configured"] is False


def test_auth_me_returns_validated_principal(
    client,
    member_headers,
):
    response = client.get(
        "/api/auth/me",
        headers=member_headers,
    )
    assert response.status_code == 200
    assert response.json() == {
        "tenant_id": "tenant-a",
        "user_id": "user-a",
        "role": "member",
    }


def test_disallowed_demo_tenant_fails_closed(client):
    response = client.get(
        "/api/agents",
        headers={
            "X-Tenant-ID": "tenant-not-allowed",
            "X-User-ID": "user-a",
            "X-Role": "member",
        },
    )
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == (
        "AUTH_CONTEXT_INVALID"
    )


def test_disallowed_demo_user_fails_closed(client):
    response = client.get(
        "/api/agents",
        headers={
            "X-Tenant-ID": "tenant-a",
            "X-User-ID": "user-not-allowed",
            "X-Role": "member",
        },
    )
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == (
        "AUTH_CONTEXT_INVALID"
    )


def test_demo_admin_requires_explicit_gate(
    monkeypatch,
    admin_headers,
):
    monkeypatch.setenv(
        "PLATFORM_DEMO_ADMIN_ENABLED",
        "false",
    )
    get_settings.cache_clear()
    client = TestClient(create_app())

    response = client.get(
        "/api/admin/overview",
        headers=admin_headers,
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == (
        "DEMO_ADMIN_DISABLED"
    )


def test_external_required_status_is_public_but_routes_are_locked(
    monkeypatch,
):
    monkeypatch.setenv(
        "PLATFORM_AUTH_MODE",
        "external_required",
    )
    get_settings.cache_clear()
    client = TestClient(create_app())

    status = client.get("/api/auth/status")
    assert status.status_code == 200
    assert status.json()["auth_mode"] == (
        "external_required"
    )
    assert status.json()["demo_profile"] is None

    protected = client.get(
        "/api/agents",
        headers={
            "X-Tenant-ID": "tenant-a",
            "X-User-ID": "user-a",
            "X-Role": "member",
        },
    )
    assert protected.status_code == 401
    assert protected.json()["detail"]["code"] == (
        "AUTH_PROVIDER_REQUIRED"
    )


def test_demo_headers_are_forbidden_in_production(
    monkeypatch,
):
    monkeypatch.setenv(
        "PLATFORM_ENVIRONMENT",
        "production",
    )
    monkeypatch.setenv(
        "PLATFORM_AUTH_MODE",
        "demo_headers",
    )
    get_settings.cache_clear()

    with pytest.raises(
        ValueError,
        match=(
            "DEMO_IDENTITY_HEADERS_FORBIDDEN_IN_PRODUCTION"
        ),
    ):
        get_settings()
