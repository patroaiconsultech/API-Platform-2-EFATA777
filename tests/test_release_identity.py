from fastapi.testclient import TestClient

from orkio_platform.config import get_settings
from orkio_platform.main import create_app
from orkio_platform.version import (
    RELEASE_CANDIDATE,
    RELEASE_VERSION,
)


def test_auth_status_uses_canonical_release_identity(
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "PLATFORM_RELEASE_SHA",
        "test-sha-r042",
    )
    get_settings.cache_clear()
    client = TestClient(create_app())

    response = client.get("/api/auth/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["candidate"] == RELEASE_CANDIDATE
    assert payload["release_version"] == RELEASE_VERSION
    assert payload["release_sha"] == "test-sha-r042"


def test_governance_status_uses_same_release_identity(
    client,
    member_headers,
) -> None:
    response = client.get(
        "/api/governance/status",
        headers=member_headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["candidate"] == RELEASE_CANDIDATE
    assert payload["release_version"] == RELEASE_VERSION
