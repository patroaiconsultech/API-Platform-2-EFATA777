from fastapi import APIRouter

from orkio_platform.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/api/health")
def health() -> dict[str, object]:
    settings = get_settings()
    return {
        "status": "ok",
        "application": settings.app_name,
        "environment": settings.environment,
        "release_sha": settings.release_sha,
    }


@router.get("/api/readiness")
def readiness() -> dict[str, object]:
    return {
        "status": "ready_for_local_dry_run",
        "database": "in_memory_only",
        "production_ready": False,
    }
