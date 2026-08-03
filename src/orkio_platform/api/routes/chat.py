from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from orkio_platform.api.dependencies import get_principal
from orkio_platform.application.services import PlatformService
from orkio_platform.config import get_settings
from orkio_platform.domain.models import (
    CancelExecutionRequest,
    ChatRequest,
    PrincipalContext,
    ResponseEnvelope,
)
from orkio_platform.infrastructure.repositories import repository
from orkio_platform.llm.factory import build_llm_provider
from orkio_platform.realtime.sse import stream_chat

router = APIRouter(prefix="/api/chat", tags=["chat"])
settings = get_settings()
service = PlatformService(
    repository,
    execution_lease_seconds=settings.execution_lease_seconds,
    execution_stale_after_seconds=(
        settings.execution_stale_after_seconds
    ),
    llm_provider=build_llm_provider(settings),
    llm_history_messages=settings.llm_history_messages,
    llm_max_context_chars=settings.llm_max_context_chars,
    realtime_streaming_enabled=(
        settings.realtime_streaming_enabled
    ),
    multiagent_enabled=settings.multiagent_enabled,
    multiagent_max_contributors=(
        settings.multiagent_max_contributors
    ),
    multiagent_team_agents=settings.multiagent_team_agents,
    multiagent_contribution_max_chars=(
        settings.multiagent_contribution_max_chars
    ),
    multiagent_contribution_max_output_tokens=(
        settings.multiagent_contribution_max_output_tokens
    ),
    multiagent_owner_max_output_tokens=(
        settings.multiagent_owner_max_output_tokens
    ),
    multiagent_contribution_latency_budget_ms=(
        settings.multiagent_contribution_latency_budget_ms
    ),
    multiagent_turn_latency_budget_ms=(
        settings.multiagent_turn_latency_budget_ms
    ),
    multiagent_history_messages=(
        settings.multiagent_history_messages
    ),
    multiagent_max_context_chars=(
        settings.multiagent_max_context_chars
    ),
    multiagent_turn_max_total_tokens=(
        settings.multiagent_turn_max_total_tokens
    ),
)


@router.post("", response_model=ResponseEnvelope)
def chat(
    payload: ChatRequest,
    principal: PrincipalContext = Depends(get_principal),
) -> ResponseEnvelope:
    return service.complete_chat(principal, payload)


@router.post("/stream")
def chat_stream(
    payload: ChatRequest,
    principal: PrincipalContext = Depends(get_principal),
) -> StreamingResponse:
    return StreamingResponse(
        stream_chat(service, principal, payload),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/executions/{request_id}/cancel",
    response_model=ResponseEnvelope,
)
def cancel_execution(
    request_id: str,
    payload: CancelExecutionRequest,
    principal: PrincipalContext = Depends(get_principal),
) -> ResponseEnvelope:
    return service.cancel_execution(
        principal,
        request_id,
        reason=payload.reason,
    )
