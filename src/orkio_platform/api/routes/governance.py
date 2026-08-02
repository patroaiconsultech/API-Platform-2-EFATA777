from fastapi import APIRouter, Depends

from orkio_platform.api.dependencies import (
    get_principal,
    require_admin,
)
from orkio_platform.application.services import PlatformService
from orkio_platform.config import get_settings
from orkio_platform.domain.models import (
    PrincipalContext,
    RecoveryDecisionCreate,
    RecoveryDecisionRecord,
)
from orkio_platform.infrastructure.repositories import repository
from orkio_platform.version import (
    RELEASE_CANDIDATE,
    RELEASE_VERSION,
)

router = APIRouter(prefix="/api/governance", tags=["governance"])
settings = get_settings()
service = PlatformService(
    repository,
    execution_lease_seconds=settings.execution_lease_seconds,
    execution_stale_after_seconds=(
        settings.execution_stale_after_seconds
    ),
)


@router.get("/status")
def governance_status(
    _: PrincipalContext = Depends(get_principal),
) -> dict[str, object]:
    return {
        "candidate": RELEASE_CANDIDATE,
        "release_version": RELEASE_VERSION,
        "release_sha": settings.release_sha,
        "proposal_only": False,
        "local_execution": True,
        "repository_backend": repository.backend_name,
        "execution_lease_seconds": settings.execution_lease_seconds,
        "execution_stale_after_seconds": (
            settings.execution_stale_after_seconds
        ),
        "automatic_recovery": False,
        "repository_write_executed": False,
        "commit_executed": False,
        "merge_executed": False,
        "deploy_executed": False,
        "migration_executed": False,
        "production_authorization": False,
    }


@router.post(
    "/executions/{request_id}/recovery-decisions",
    response_model=RecoveryDecisionRecord,
)
def record_recovery_decision(
    request_id: str,
    payload: RecoveryDecisionCreate,
    principal: PrincipalContext = Depends(get_principal),
) -> RecoveryDecisionRecord:
    principal = require_admin(principal)
    return service.record_recovery_decision(
        principal,
        request_id,
        payload,
    )


@router.get(
    "/executions/{request_id}/recovery-decisions",
    response_model=list[RecoveryDecisionRecord],
)
def list_recovery_decisions(
    request_id: str,
    principal: PrincipalContext = Depends(get_principal),
) -> list[RecoveryDecisionRecord]:
    principal = require_admin(principal)
    execution = repository.get_execution(
        principal.tenant_id,
        request_id,
    )
    if execution is None:
        from orkio_platform.domain.errors import NotFoundError

        raise NotFoundError(
            "EXECUTION_NOT_FOUND",
            "Execution not found.",
        )
    return repository.list_recovery_decisions(
        principal.tenant_id,
        request_id,
    )
