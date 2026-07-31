from fastapi import APIRouter
from orkio_platform.config import get_settings
from orkio_platform.infrastructure.repositories import repository

router = APIRouter(tags=["health"])

@router.get("/api/health")
def health() -> dict[str,object]:
    settings = get_settings()
    return {"status":"ok","application":settings.app_name,"environment":settings.environment,"release_sha":settings.release_sha}

@router.get("/api/readiness")
def readiness() -> dict[str,object]:
    try:
        database_ready = repository.ping()
    except Exception:
        database_ready = False
    backend = repository.backend_name
    return {
        "status":"ready_for_rc1_test" if database_ready else "not_ready",
        "database":backend, "database_ready":database_ready,
        "persistent_repository":backend != "memory",
        "production_ready":False,
    }
