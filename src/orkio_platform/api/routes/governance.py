from fastapi import APIRouter, Depends

from orkio_platform.api.dependencies import (
    get_principal,
    require_admin,
)
from orkio_platform.application.services import PlatformService
from orkio_platform.domain.errors import DomainError
from orkio_platform.evolution.service import EvolutionProposalService
from orkio_platform.config import get_settings
from orkio_platform.domain.models import (
    EvolutionProposalEnvelope,
    EvolutionProposalRequest,
    PrincipalContext,
    RecoveryDecisionCreate,
    RecoveryDecisionRecord,
)
from orkio_platform.infrastructure.repositories import repository
from orkio_platform.knowledge.snapshot import KNOWLEDGE_SNAPSHOT_VERSION
from orkio_platform.llm.factory import build_llm_provider
from orkio_platform.orchestration.capabilities import list_capabilities
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
evolution_service = EvolutionProposalService(
    build_llm_provider(settings)
)


@router.get("/status")
def governance_status(
    _: PrincipalContext = Depends(get_principal),
) -> dict[str, object]:
    return {
        "candidate": RELEASE_CANDIDATE,
        "release_version": RELEASE_VERSION,
        "release_sha": settings.release_sha,
        "proposal_only": settings.assisted_evolution_enabled,
        "assisted_evolution_enabled": (
            settings.assisted_evolution_enabled
        ),
        "realtime_streaming_enabled": (
            settings.realtime_streaming_enabled
        ),
        "multiagent_enabled": settings.multiagent_enabled,
        "multiagent_max_contributors": (
            settings.multiagent_max_contributors
        ),
        "execution_graph": "trace_lite",
        "capability_registry_entries": len(list_capabilities()),
        "capability_registry_contract": "evidence_aware_v1",
        "roundtable_output_normalization": "speaker_contract_v4",
        "owner_contract": "adaptive_owner_contract_v1",
        "task_decomposition": "task_slice_v1",
        "partial_owner_preservation": True,
        "knowledge_snapshot_version": KNOWLEDGE_SNAPSHOT_VERSION,
        "multiagent_budget": {
            "contribution_max_chars": (
                settings.multiagent_contribution_max_chars
            ),
            "contribution_max_output_tokens": (
                settings.multiagent_contribution_max_output_tokens
            ),
            "owner_max_output_tokens": (
                settings.multiagent_owner_max_output_tokens
            ),
            "contribution_latency_budget_ms": (
                settings.multiagent_contribution_latency_budget_ms
            ),
            "turn_latency_budget_ms": (
                settings.multiagent_turn_latency_budget_ms
            ),
            "history_messages": settings.multiagent_history_messages,
            "max_context_chars": (
                settings.multiagent_max_context_chars
            ),
            "turn_max_total_tokens": (
                settings.multiagent_turn_max_total_tokens
            ),
        },
        "agent_capability_truthfulness": True,
        "local_execution": True,
        "repository_backend": repository.backend_name,
        "llm_provider": settings.llm_provider,
        "real_llm_enabled": (
            settings.llm_provider == "openai_responses"
        ),
        "llm_model": settings.openai_default_model,
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
    "/evolution/proposals",
    response_model=EvolutionProposalEnvelope,
)
def create_evolution_proposal(
    payload: EvolutionProposalRequest,
    principal: PrincipalContext = Depends(get_principal),
) -> EvolutionProposalEnvelope:
    principal = require_admin(principal)
    if not settings.assisted_evolution_enabled:
        raise DomainError(
            "ASSISTED_EVOLUTION_DISABLED",
            "Assisted evolution proposal mode is disabled.",
            status_code=403,
        )
    return evolution_service.create_proposal(
        principal,
        payload,
    )


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
