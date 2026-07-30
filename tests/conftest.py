from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest
from fastapi.testclient import TestClient

from orkio_platform.infrastructure.repositories import repository
from orkio_platform.main import create_app


@pytest.fixture(autouse=True)
def reset_repository():
    repository.reset()
    yield
    repository.reset()


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
