from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from orkio_platform.config import get_settings
from orkio_platform.infrastructure.repositories import repository
from orkio_platform.main import create_app


@pytest.fixture(autouse=True)
def reset_repository(monkeypatch):
    monkeypatch.setenv(
        "PLATFORM_ENVIRONMENT",
        "local-sandbox",
    )
    monkeypatch.setenv(
        "PLATFORM_AUTH_MODE",
        "demo_headers",
    )
    monkeypatch.setenv(
        "PLATFORM_DEMO_IDENTITY_HEADERS_ENABLED",
        "true",
    )
    monkeypatch.setenv(
        "PLATFORM_DEMO_ALLOWED_TENANTS",
        "tenant-a,tenant-b",
    )
    monkeypatch.setenv(
        "PLATFORM_DEMO_ALLOWED_USERS",
        "user-a,user-b,admin-a",
    )
    monkeypatch.setenv(
        "PLATFORM_DEMO_ADMIN_ENABLED",
        "true",
    )
    monkeypatch.setenv(
        "PLATFORM_DEMO_ADMIN_USERS",
        "admin-a",
    )
    get_settings.cache_clear()
    repository.reset()
    yield
    repository.reset()
    get_settings.cache_clear()


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


@pytest.fixture
def member_headers() -> dict[str, str]:
    return {
        "X-Tenant-ID": "tenant-a",
        "X-User-ID": "user-a",
        "X-Role": "member",
    }


@pytest.fixture
def admin_headers() -> dict[str, str]:
    return {
        "X-Tenant-ID": "tenant-a",
        "X-User-ID": "admin-a",
        "X-Role": "admin",
    }
