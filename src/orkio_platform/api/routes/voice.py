from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from orkio_platform.api.dependencies import get_principal
from orkio_platform.api.routes.chat import service as platform_service
from orkio_platform.application.voice_service import VoiceService
from orkio_platform.config import get_settings
from orkio_platform.domain.models import PrincipalContext
from orkio_platform.infrastructure.repositories import repository
from orkio_platform.realtime.openai_realtime import (
    build_realtime_voice_provider,
)
from orkio_platform.realtime.voice_models import (
    VoiceAudioReportRequest,
    VoiceCallAnswer,
    VoiceCallOfferRequest,
    VoiceCloseRequest,
    VoiceEventAppendRequest,
    VoiceEventRecord,
    VoiceResumeRequest,
    VoiceSessionCreateRequest,
    VoiceSessionRecord,
    VoiceSessionStatusEnvelope,
    VoiceTurnCreateRequest,
    VoiceTurnRecord,
    VoiceTurnResult,
)
from orkio_platform.realtime.voice_store import build_voice_store


router = APIRouter(prefix="/api/voice", tags=["voice"])
settings = get_settings()
voice_store = build_voice_store(repository)
voice_service = VoiceService(
    settings=settings,
    store=voice_store,
    platform_service=platform_service,
    provider=build_realtime_voice_provider(settings),
)


@router.post("/sessions", response_model=VoiceSessionRecord)
def create_voice_session(
    payload: VoiceSessionCreateRequest,
    principal: PrincipalContext = Depends(get_principal),
) -> VoiceSessionRecord:
    return voice_service.create_session(principal, payload)


@router.post(
    "/sessions/{session_id}/calls",
    response_model=VoiceCallAnswer,
)
def create_voice_call(
    session_id: str,
    payload: VoiceCallOfferRequest,
    principal: PrincipalContext = Depends(get_principal),
) -> VoiceCallAnswer:
    return voice_service.create_call(principal, session_id, payload)


@router.post(
    "/sessions/{session_id}/resume",
    response_model=VoiceSessionStatusEnvelope,
)
def resume_voice_session(
    session_id: str,
    payload: VoiceResumeRequest,
    principal: PrincipalContext = Depends(get_principal),
) -> VoiceSessionStatusEnvelope:
    session, credential = voice_service.resume_session(
        principal,
        session_id,
        resume_token=payload.resume_token,
        expected_generation=payload.expected_session_generation,
        source_connection_id=payload.source_connection_id,
    )
    status = voice_service.status(
        principal,
        session.session_id,
        after_sequence=payload.last_received_canonical_sequence,
    )
    return status.model_copy(
        update={
            "resume_token": credential.token,
            "resume_token_expires_at": credential.expires_at,
        }
    )


@router.post(
    "/sessions/{session_id}/events",
    response_model=VoiceEventRecord,
)
def append_voice_event(
    session_id: str,
    payload: VoiceEventAppendRequest,
    principal: PrincipalContext = Depends(get_principal),
) -> VoiceEventRecord:
    return voice_service.append_event(principal, session_id, payload)


@router.post(
    "/sessions/{session_id}/turns",
    response_model=VoiceTurnResult,
)
def complete_voice_turn(
    session_id: str,
    payload: VoiceTurnCreateRequest,
    principal: PrincipalContext = Depends(get_principal),
) -> VoiceTurnResult:
    return voice_service.complete_turn(principal, session_id, payload)


@router.post(
    "/sessions/{session_id}/turns/{turn_id}/audio",
    response_model=VoiceTurnRecord,
)
def report_voice_audio(
    session_id: str,
    turn_id: str,
    payload: VoiceAudioReportRequest,
    principal: PrincipalContext = Depends(get_principal),
) -> VoiceTurnRecord:
    return voice_service.report_audio(
        principal,
        session_id,
        turn_id,
        payload,
    )


@router.post(
    "/sessions/{session_id}/close",
    response_model=VoiceSessionRecord,
)
def close_voice_session(
    session_id: str,
    payload: VoiceCloseRequest,
    principal: PrincipalContext = Depends(get_principal),
) -> VoiceSessionRecord:
    return voice_service.close_session(principal, session_id, payload)


@router.get(
    "/sessions/{session_id}",
    response_model=VoiceSessionStatusEnvelope,
)
def voice_session_status(
    session_id: str,
    after_sequence: int = Query(default=0, ge=0),
    principal: PrincipalContext = Depends(get_principal),
) -> VoiceSessionStatusEnvelope:
    return voice_service.status(
        principal,
        session_id,
        after_sequence=after_sequence,
    )
