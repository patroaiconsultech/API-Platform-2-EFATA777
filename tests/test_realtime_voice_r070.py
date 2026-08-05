
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

import httpx
import pytest

from orkio_platform.application.services import PlatformService
from orkio_platform.application.voice_service import (
    VoiceService,
    canonical_text_sha256,
)
from orkio_platform.config import get_settings
from orkio_platform.domain.errors import ConflictError, ServiceUnavailableError
from orkio_platform.domain.models import PrincipalContext
from orkio_platform.infrastructure.repositories import InMemoryRepository
from orkio_platform.realtime.openai_realtime import (
    OpenAIRealtimeVoiceProvider,
    RealtimeCallResult,
)
from orkio_platform.realtime.voice_models import (
    VoiceAudioReportRequest,
    VoiceCallOfferRequest,
    VoiceCloseRequest,
    VoiceResumeTokenRecord,
    VoiceSessionCreateRequest,
    VoiceSessionRecord,
    VoiceTurnCreateRequest,
)
from orkio_platform.realtime.voice_store import InMemoryVoiceStore


@dataclass
class FakeRealtimeProvider:
    calls: int = 0
    hangups: int = 0

    def create_call(self, *, sdp_offer, session):
        self.calls += 1
        assert sdp_offer.startswith("v=0")
        assert session.turn_owner == "Orkio"
        return RealtimeCallResult(
            sdp_answer="v=0\\r\\nanswer",
            provider_call_id="call_test_01",
        )

    def hangup(self, provider_call_id):
        self.hangups += 1
        return provider_call_id == "call_test_01"


def voice_settings(monkeypatch):
    monkeypatch.setenv("PLATFORM_LLM_PROVIDER", "deterministic")
    monkeypatch.setenv("PLATFORM_REALTIME_VOICE_ENABLED", "true")
    monkeypatch.setenv("PLATFORM_VOICE_PROVIDER", "openai_realtime")
    monkeypatch.setenv(
        "PLATFORM_VOICE_PROVIDER_RETENTION_CONFIRMED",
        "true",
    )
    monkeypatch.setenv("OPENAI_API_KEY", "test-server-secret")
    monkeypatch.setenv(
        "PLATFORM_VOICE_RESUME_TOKEN_SECRET",
        "synthetic-resume-token-secret-32-bytes-minimum",
    )
    get_settings.cache_clear()
    return get_settings()


def build_service(monkeypatch):
    settings = voice_settings(monkeypatch)
    repository = InMemoryRepository()
    platform = PlatformService(repository)
    principal = PrincipalContext(
        tenant_id="tenant-a",
        user_id="user-a",
        role="member",
    )
    thread = platform.create_thread(principal, "Golden Voice")
    store = InMemoryVoiceStore()
    provider = FakeRealtimeProvider()
    voice = VoiceService(
        settings=settings,
        store=store,
        platform_service=platform,
        provider=provider,
    )
    return voice, platform, store, provider, principal, thread


def test_voice_config_is_fail_closed_by_default(monkeypatch):
    monkeypatch.delenv("PLATFORM_REALTIME_VOICE_ENABLED", raising=False)
    monkeypatch.delenv("PLATFORM_VOICE_PROVIDER", raising=False)
    monkeypatch.delenv(
        "PLATFORM_VOICE_PROVIDER_RETENTION_CONFIRMED",
        raising=False,
    )
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.realtime_voice_enabled is False
    assert settings.voice_provider == "disabled"


def test_voice_config_requires_provider_retention_confirmation(monkeypatch):
    monkeypatch.setenv("PLATFORM_LLM_PROVIDER", "deterministic")
    monkeypatch.setenv("PLATFORM_REALTIME_VOICE_ENABLED", "true")
    monkeypatch.setenv("PLATFORM_VOICE_PROVIDER", "openai_realtime")
    monkeypatch.setenv("OPENAI_API_KEY", "test-server-secret")
    monkeypatch.setenv(
        "PLATFORM_VOICE_PROVIDER_RETENTION_CONFIRMED",
        "false",
    )
    get_settings.cache_clear()
    with pytest.raises(
        ValueError,
        match="VOICE_PROVIDER_RETENTION_CONFIRMATION_REQUIRED",
    ):
        get_settings()


def test_voice_config_requires_resume_token_secret(monkeypatch):
    monkeypatch.setenv("PLATFORM_LLM_PROVIDER", "deterministic")
    monkeypatch.setenv("PLATFORM_REALTIME_VOICE_ENABLED", "true")
    monkeypatch.setenv("PLATFORM_VOICE_PROVIDER", "openai_realtime")
    monkeypatch.setenv("OPENAI_API_KEY", "test-server-secret")
    monkeypatch.setenv(
        "PLATFORM_VOICE_PROVIDER_RETENTION_CONFIRMED",
        "true",
    )
    monkeypatch.delenv(
        "PLATFORM_VOICE_RESUME_TOKEN_SECRET",
        raising=False,
    )
    get_settings.cache_clear()
    with pytest.raises(
        ValueError,
        match="PLATFORM_VOICE_RESUME_TOKEN_SECRET_REQUIRED",
    ):
        get_settings()


def test_resume_token_is_rotated_and_generation_bound(monkeypatch):
    voice, _, _, _, principal, thread = build_service(monkeypatch)
    session = voice.create_session(
        principal,
        VoiceSessionCreateRequest(
            thread_id=thread.thread_id,
            consent_granted=True,
        ),
    )
    call = voice.create_call(
        principal,
        session.session_id,
        VoiceCallOfferRequest(
            sdp="v=0\\r\\noffer",
            source_connection_id="connection_1",
            expected_session_generation=1,
        ),
    )
    assert call.resume_token
    resumed, credential = voice.resume_session(
        principal,
        session.session_id,
        resume_token=call.resume_token,
        expected_generation=1,
        source_connection_id="connection_2",
    )
    assert resumed.session_generation == 2
    assert credential.token != call.resume_token

    with pytest.raises(ConflictError):
        voice.resume_session(
            principal,
            session.session_id,
            resume_token=call.resume_token,
            expected_generation=2,
            source_connection_id="connection_3",
        )


def test_active_voice_session_limit_is_enforced(monkeypatch):
    voice, _, _, _, principal, thread = build_service(monkeypatch)
    voice.create_session(
        principal,
        VoiceSessionCreateRequest(
            thread_id=thread.thread_id,
            consent_granted=True,
        ),
    )
    with pytest.raises(
        ConflictError,
        match="Active voice session limit",
    ):
        voice.create_session(
            principal,
            VoiceSessionCreateRequest(
                thread_id=thread.thread_id,
                consent_granted=True,
            ),
        )


def test_cross_generation_redelivery_returns_original_event(monkeypatch):
    _, _, store, _, _, _ = build_service(monkeypatch)
    session = VoiceSessionRecord(
        tenant_id="tenant-a",
        session_id="voice_session_1",
        thread_id="thread_1",
        user_id="user-a",
        provider="openai_realtime",
    )
    store.create_session(session)
    first, created = store.append_event(
        tenant_id="tenant-a",
        session_id=session.session_id,
        source="provider",
        source_event_key="provider_evt_1",
        event_type="voice.transcript.final",
        session_generation=1,
    )
    assert created is True
    token = VoiceResumeTokenRecord(
        tenant_id="tenant-a",
        session_id=session.session_id,
        user_id="user-a",
        resume_token_jti="resume-token-jti-0001",
        session_generation=1,
        issued_at=session.created_at,
        expires_at=session.created_at + timedelta(minutes=1),
    )
    store.register_resume_token(token)
    resumed = store.resume_session(
        "tenant-a",
        session.session_id,
        expected_generation=1,
        source_connection_id="connection_2",
        resume_token_jti=token.resume_token_jti,
    )
    duplicate, created = store.append_event(
        tenant_id="tenant-a",
        session_id=session.session_id,
        source="provider",
        source_event_key="provider_evt_1",
        event_type="voice.transcript.final",
        session_generation=resumed.session_generation,
    )
    assert created is False
    assert duplicate.event_id == first.event_id
    assert duplicate.canonical_sequence == first.canonical_sequence


def test_stale_generation_and_event_after_close_fail_closed(monkeypatch):
    _, _, store, _, _, _ = build_service(monkeypatch)
    session = VoiceSessionRecord(
        tenant_id="tenant-a",
        session_id="voice_session_2",
        thread_id="thread_2",
        user_id="user-a",
        provider="openai_realtime",
    )
    store.create_session(session)
    with pytest.raises(ConflictError, match="generation"):
        store.append_event(
            tenant_id="tenant-a",
            session_id=session.session_id,
            source="browser",
            source_event_key="client_evt_stale",
            event_type="voice.input.started",
            session_generation=2,
        )
    store.close_session(
        "tenant-a",
        session.session_id,
        expected_generation=1,
        close_reason="user_end",
        microphone_released=True,
        player_released=True,
    )
    with pytest.raises(ConflictError, match="after session close"):
        store.append_event(
            tenant_id="tenant-a",
            session_id=session.session_id,
            source="browser",
            source_event_key="client_evt_after_close",
            event_type="voice.input.started",
            session_generation=1,
        )


def test_canonical_voice_turn_persists_once_and_preserves_owner(monkeypatch):
    voice, platform, _, provider, principal, thread = build_service(monkeypatch)
    session = voice.create_session(
        principal,
        VoiceSessionCreateRequest(
            thread_id=thread.thread_id,
            requested_agent="Orkio",
            interaction_mode="single",
            consent_granted=True,
        ),
    )
    call = voice.create_call(
        principal,
        session.session_id,
        VoiceCallOfferRequest(
            sdp="v=0\\r\\noffer",
            source_connection_id="connection_1",
            expected_session_generation=1,
        ),
    )
    assert call.session.status == "connected"
    payload = VoiceTurnCreateRequest(
        transcript_id="transcript_1",
        transcript="Orkio, responda Efatà 777.",
        client_event_id="provider_evt_transcript_1",
        session_generation=1,
    )
    first = voice.complete_turn(principal, session.session_id, payload)
    duplicate = voice.complete_turn(principal, session.session_id, payload)

    assert duplicate.turn.turn_id == first.turn.turn_id
    assert duplicate.response.message_id == first.response.message_id
    assert first.response.turn_owner == "Orkio"
    assert first.response.agent_id == "Orkio"
    assert first.assistant_content_sha256 == canonical_text_sha256(
        first.response.content
    )
    assert first.tts_input_sha256 == first.assistant_content_sha256

    messages = platform.list_messages(principal, thread.thread_id)
    assert len(messages) == 2
    assert [message.role for message in messages] == ["user", "assistant"]
    assert provider.calls == 1


def test_tts_hash_mismatch_is_rejected(monkeypatch):
    voice, _, _, _, principal, thread = build_service(monkeypatch)
    session = voice.create_session(
        principal,
        VoiceSessionCreateRequest(
            thread_id=thread.thread_id,
            consent_granted=True,
        ),
    )
    voice.create_call(
        principal,
        session.session_id,
        VoiceCallOfferRequest(
            sdp="v=0\\r\\noffer",
            source_connection_id="connection_1",
            expected_session_generation=1,
        ),
    )
    result = voice.complete_turn(
        principal,
        session.session_id,
        VoiceTurnCreateRequest(
            transcript_id="transcript_hash",
            transcript="Teste de hash",
            client_event_id="provider_evt_hash",
            session_generation=1,
        ),
    )
    with pytest.raises(ConflictError, match="diverged"):
        voice.report_audio(
            principal,
            session.session_id,
            result.turn.turn_id,
            VoiceAudioReportRequest(
                provider_event_id="provider_evt_audio_done",
                session_generation=1,
                spoken_transcript="Conteúdo diferente",
                audio_status="completed",
                response_id="response_1",
            ),
        )


def test_audio_completion_is_the_single_turn_terminal(monkeypatch):
    voice, _, store, _, principal, thread = build_service(monkeypatch)
    session = voice.create_session(
        principal,
        VoiceSessionCreateRequest(
            thread_id=thread.thread_id,
            consent_granted=True,
        ),
    )
    voice.create_call(
        principal,
        session.session_id,
        VoiceCallOfferRequest(
            sdp="v=0\\r\\noffer",
            source_connection_id="connection_1",
            expected_session_generation=1,
        ),
    )
    result = voice.complete_turn(
        principal,
        session.session_id,
        VoiceTurnCreateRequest(
            transcript_id="transcript_terminal",
            transcript="Efatà 777",
            client_event_id="provider_evt_terminal",
            session_generation=1,
        ),
    )
    assert result.turn.status == "processing"

    completed = voice.report_audio(
        principal,
        session.session_id,
        result.turn.turn_id,
        VoiceAudioReportRequest(
            provider_event_id="provider_evt_audio_terminal",
            session_generation=1,
            spoken_transcript=result.response.content,
            audio_status="completed",
            response_id="response_terminal",
        ),
    )
    assert completed.status == "completed"
    assert completed.tts_input_sha256 == completed.assistant_content_sha256
    terminals = [
        event.event_type
        for event in store.list_events("tenant-a", session.session_id)
        if event.turn_id == result.turn.turn_id
        and event.event_type in {
            "voice.turn.completed",
            "voice.turn.failed",
            "voice.turn.interrupted",
        }
    ]
    assert terminals == ["voice.turn.completed"]


def test_barge_in_preserves_hash_and_terminalizes_as_interrupted(monkeypatch):
    voice, _, store, _, principal, thread = build_service(monkeypatch)
    session = voice.create_session(
        principal,
        VoiceSessionCreateRequest(
            thread_id=thread.thread_id,
            consent_granted=True,
        ),
    )
    voice.create_call(
        principal,
        session.session_id,
        VoiceCallOfferRequest(
            sdp="v=0\\r\\noffer",
            source_connection_id="connection_1",
            expected_session_generation=1,
        ),
    )
    result = voice.complete_turn(
        principal,
        session.session_id,
        VoiceTurnCreateRequest(
            transcript_id="transcript_interrupt",
            transcript="Resposta longa",
            client_event_id="provider_evt_interrupt",
            session_generation=1,
        ),
    )
    interrupted = voice.report_audio(
        principal,
        session.session_id,
        result.turn.turn_id,
        VoiceAudioReportRequest(
            provider_event_id="provider_evt_audio_interrupt",
            session_generation=1,
            spoken_transcript=result.response.content[:3],
            audio_status="interrupted",
            response_id="response_interrupt",
        ),
    )
    assert interrupted.status == "interrupted"
    assert interrupted.spoken_content_complete is False
    assert interrupted.canonical_text_preserved is True
    assert interrupted.tts_input_sha256 == interrupted.assistant_content_sha256
    terminals = [
        event.event_type
        for event in store.list_events("tenant-a", session.session_id)
        if event.turn_id == result.turn.turn_id
        and event.event_type in {
            "voice.turn.completed",
            "voice.turn.failed",
            "voice.turn.interrupted",
        }
    ]
    assert terminals == ["voice.turn.interrupted"]


def test_close_requires_released_media_and_is_terminal(monkeypatch):
    voice, _, store, provider, principal, thread = build_service(monkeypatch)
    session = voice.create_session(
        principal,
        VoiceSessionCreateRequest(
            thread_id=thread.thread_id,
            consent_granted=True,
        ),
    )
    voice.create_call(
        principal,
        session.session_id,
        VoiceCallOfferRequest(
            sdp="v=0\\r\\noffer",
            source_connection_id="connection_1",
            expected_session_generation=1,
        ),
    )
    closed = voice.close_session(
        principal,
        session.session_id,
        VoiceCloseRequest(
            close_reason="user_end",
            microphone_released=True,
            player_released=True,
            expected_session_generation=1,
        ),
    )
    assert closed.status == "closed"
    assert closed.close_reason == "user_end"
    assert closed.microphone_released is True
    assert closed.player_released is True
    assert provider.hangups == 1
    terminal = [
        event
        for event in store.list_events("tenant-a", session.session_id)
        if event.event_type == "voice.session.closed"
    ]
    assert len(terminal) == 1
    assert terminal[0].payload["close_reason"] == "user_end"


def test_transcript_final_uses_browser_provenance_and_split_identity(
    monkeypatch,
):
    voice, _, store, _, principal, thread = build_service(monkeypatch)
    session = voice.create_session(
        principal,
        VoiceSessionCreateRequest(
            thread_id=thread.thread_id,
            consent_granted=True,
        ),
    )
    voice.create_call(
        principal,
        session.session_id,
        VoiceCallOfferRequest(
            sdp="v=0\\r\\noffer",
            source_connection_id="connection_identity",
            expected_session_generation=1,
        ),
    )
    voice.complete_turn(
        principal,
        session.session_id,
        VoiceTurnCreateRequest(
            transcript_id="semantic-transcript-1",
            transcript="Efatà 777",
            client_event_id="browser-delivery-1",
            session_generation=1,
        ),
    )
    transcript_event = next(
        event
        for event in store.list_events("tenant-a", session.session_id)
        if event.event_type == "voice.transcript.final"
    )
    assert transcript_event.source == "browser"
    assert transcript_event.semantic_operation_id == "semantic-transcript-1"
    assert transcript_event.source_delivery_id == "browser-delivery-1"
    assert transcript_event.canonical_event_id == transcript_event.event_id


def test_resume_token_jti_is_consumed_exactly_once(monkeypatch):
    _, _, store, _, _, _ = build_service(monkeypatch)
    session = VoiceSessionRecord(
        tenant_id="tenant-a",
        session_id="voice_session_resume_once",
        thread_id="thread_resume_once",
        user_id="user-a",
        provider="openai_realtime",
    )
    store.create_session(session)
    token = VoiceResumeTokenRecord(
        tenant_id=session.tenant_id,
        session_id=session.session_id,
        user_id=session.user_id,
        resume_token_jti="resume-token-jti-once",
        session_generation=1,
        issued_at=session.created_at,
        expires_at=session.created_at + timedelta(minutes=1),
    )
    store.register_resume_token(token)
    store.resume_session(
        session.tenant_id,
        session.session_id,
        expected_generation=1,
        source_connection_id="connection_once_1",
        resume_token_jti=token.resume_token_jti,
    )
    with pytest.raises(
        ConflictError,
        match="already been consumed",
    ):
        store.resume_session(
            session.tenant_id,
            session.session_id,
            expected_generation=1,
            source_connection_id="connection_once_2",
            resume_token_jti=token.resume_token_jti,
        )


def test_semantic_operation_deduplicates_new_delivery_after_reconnect(
    monkeypatch,
):
    _, _, store, _, _, _ = build_service(monkeypatch)
    session = VoiceSessionRecord(
        tenant_id="tenant-a",
        session_id="voice_session_semantic",
        thread_id="thread_semantic",
        user_id="user-a",
        provider="openai_realtime",
    )
    store.create_session(session)
    first, created = store.append_event(
        tenant_id=session.tenant_id,
        session_id=session.session_id,
        source="browser",
        source_event_key="semantic-operation-1",
        source_delivery_id="delivery-1",
        semantic_operation_id="semantic-operation-1",
        event_type="voice.transcript.final",
        session_generation=1,
    )
    assert created is True
    duplicate, created = store.append_event(
        tenant_id=session.tenant_id,
        session_id=session.session_id,
        source="browser",
        source_event_key="semantic-operation-1",
        source_delivery_id="delivery-2",
        semantic_operation_id="semantic-operation-1",
        event_type="voice.transcript.final",
        session_generation=1,
    )
    assert created is False
    assert duplicate.canonical_event_id == first.canonical_event_id
    assert duplicate.source_delivery_id == "delivery-1"


def test_openai_provider_keeps_primary_key_server_side(monkeypatch):
    settings = voice_settings(monkeypatch)
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers.get("authorization")
        captured["content_type"] = request.headers.get("content-type")
        assert request.url.path == "/v1/realtime/calls"
        return httpx.Response(
            200,
            text="v=0\\r\\nanswer",
            headers={"location": "/v1/realtime/calls/call_123"},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = OpenAIRealtimeVoiceProvider(settings, client=client)
    result = provider.create_call(
        sdp_offer="v=0\\r\\noffer",
        session=VoiceSessionRecord(
            tenant_id="tenant-a",
            session_id="voice_session_provider",
            thread_id="thread-provider",
            user_id="user-a",
            provider="openai_realtime",
        ),
    )
    assert result.provider_call_id == "call_123"
    assert captured["authorization"] == "Bearer test-server-secret"
    assert "multipart/form-data" in captured["content_type"]
