from collections import Counter
from dataclasses import asdict

from fastapi import APIRouter, Depends

from orkio_platform.api.dependencies import get_principal, require_admin
from orkio_platform.config import get_settings
from orkio_platform.domain.models import PrincipalContext, utc_now
from orkio_platform.infrastructure.repositories import repository
from orkio_platform.orchestration.capabilities import list_capabilities
from orkio_platform.version import RELEASE_CANDIDATE, RELEASE_VERSION


router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/overview")
def admin_overview(
    principal: PrincipalContext = Depends(get_principal),
) -> dict[str, object]:
    principal = require_admin(principal)
    settings = get_settings()
    capabilities = list_capabilities()
    availability = Counter(
        item.availability for item in capabilities
    )
    return {
        "tenant_id": principal.tenant_id,
        "stats": repository.stats(principal.tenant_id),
        "scope": "tenant_only",
        "generated_at": utc_now(),
        "runtime": {
            "candidate": RELEASE_CANDIDATE,
            "release_version": RELEASE_VERSION,
            "release_sha": settings.release_sha,
            "repository_backend": repository.backend_name,
            "llm_provider": settings.llm_provider,
            "llm_model": settings.openai_default_model,
            "real_llm_enabled": (
                settings.llm_provider == "openai_responses"
            ),
            "realtime_streaming_enabled": (
                settings.realtime_streaming_enabled
            ),
            "multiagent_enabled": settings.multiagent_enabled,
            "execution_graph": "trace_lite",
            "voice_webrtc": "planned",
        },
        "capability_summary": {
            "total": len(capabilities),
            "available": availability.get("available", 0),
            "feature_gated": availability.get("feature_gated", 0),
            "planned": availability.get("planned", 0),
            "unavailable": availability.get("unavailable", 0),
        },
        "governance": {
            "proposal_only": settings.assisted_evolution_enabled,
            "write_executed": False,
            "commit_executed": False,
            "merge_executed": False,
            "deploy_executed": False,
            "migration_executed": False,
            "human_approval_required": True,
        },
        "capabilities": [asdict(item) for item in capabilities],
    }
