from fastapi import APIRouter

from orkio_platform.config import get_settings
from orkio_platform.infrastructure.repositories import repository

router = APIRouter(tags=["health"])


@router.get("/api/health")
def health() -> dict[str, object]:
    settings = get_settings()
    return {
        "status": "ok",
        "application": settings.app_name,
        "environment": settings.environment,
        "release_sha": settings.release_sha,
        "llm_provider": settings.llm_provider,
        "real_llm_enabled": (
            settings.llm_provider == "openai_responses"
        ),
        "llm_model": settings.openai_default_model,
        "realtime_streaming_enabled": (
            settings.realtime_streaming_enabled
        ),
        "multiagent_enabled": settings.multiagent_enabled,
        "assisted_evolution_enabled": (
            settings.assisted_evolution_enabled
        ),
        "execution_graph": "trace_lite",
    }


@router.get("/api/readiness")
def readiness() -> dict[str, object]:
    settings = get_settings()
    try:
        database_ready = repository.ping()
    except Exception:
        database_ready = False
    backend = repository.backend_name
    real_llm_enabled = (
        settings.llm_provider == "openai_responses"
    )
    return {
        "status": "ready_for_rc1_test" if database_ready else "not_ready",
        "database": backend,
        "database_ready": database_ready,
        "persistent_repository": backend != "memory",
        "llm_provider": settings.llm_provider,
        "real_llm_enabled": real_llm_enabled,
        "realtime_streaming_enabled": (
            settings.realtime_streaming_enabled
        ),
        "multiagent_enabled": settings.multiagent_enabled,
        "assisted_evolution_enabled": (
            settings.assisted_evolution_enabled
        ),
        "execution_graph": "trace_lite",
        "production_ready": False,
    }
