from __future__ import annotations

import hashlib
import logging
import unicodedata
from typing import Any

from orkio_platform.application.services import PlatformService
from orkio_platform.config import Settings
from orkio_platform.domain.errors import (
    ConflictError,
    DomainError,
    ServiceUnavailableError,
)
from orkio_platform.domain.models import (
    ChatRequest,
    PrincipalContext,
    ResponseEnvelope,
    new_id,
    utc_now,
)
from orkio_platform.realtime.openai_realtime import (
    RealtimeVoiceProvider,
)
from orkio_platform.realtime.voice_models import (
    VoiceAudioReportRequest,
    VoiceCallAnswer,
    VoiceCallOfferRequest,
    VoiceCloseRequest,
    VoiceEventAppendRequest,
    VoiceEventRecord,
    VoiceResumeTokenRecord,
    VoiceSessionCreateRequest,
    VoiceSessionRecord,
    VoiceSessionStatusEnvelope,
    VoiceTurnCreateRequest,
    VoiceTurnRecord,
    VoiceTurnResult,
)
from orkio_platform.realtime.resume_tokens import (
    VoiceResumeCredential,
    VoiceResumeTokenManager,
)
from orkio_platform.realtime.voice_store import VoiceStoreProtocol


logger = logging.getLogger("orkio.voice")


def canonical_text_bytes(value: str) -> bytes:
    normalized = unicodedata.normalize("NFC", value)
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    return normalized.encode("utf-8")


def canonical_text_sha256(value: str) -> str:
    return hashlib.sha256(canonical_text_bytes(value)).hexdigest()


class VoiceService:
    def __init__(
        self,
        *,
        settings: Settings,
        store: VoiceStoreProtocol,
        platform_service: PlatformService,
        provider: RealtimeVoiceProvider,
    ) -> None:
        self.settings = settings
        self.store = store
        self.platform_service = platform_service
        self.provider = provider
        self.resume_tokens = VoiceResumeTokenManager(settings)

    def _require_enabled(self) -> None:
        if not self.settings.realtime_voice_enabled:
            raise ServiceUnavailableError(
                "REALTIME_VOICE_DISABLED",
                "Realtime voice is disabled.",
            )
        if self.settings.voice_provider != "openai_realtime":
            raise ServiceUnavailableError(
                "REALTIME_VOICE_PROVIDER_DISABLED",
                "Realtime voice provider is disabled.",
            )
        if not self.settings.voice_provider_retention_confirmed:
            raise ServiceUnavailableError(
                "VOICE_PROVIDER_RETENTION_UNCONFIRMED",
                "Provider retention must be confirmed before voice is enabled.",
            )

    def _append_backend_event(
        self,
        session: VoiceSessionRecord,
        event_type: str,
        *,
        source_event_key: str,
        turn_id: str | None = None,
        execution_id: str | None = None,
        payload: dict[str, object] | None = None,
    ) -> VoiceEventRecord:
        event, _ = self.store.append_event(
            tenant_id=session.tenant_id,
            session_id=session.session_id,
            source="backend",
            source_event_key=source_event_key,
            event_type=event_type,
            session_generation=session.session_generation,
            source_connection_id=session.source_connection_id,
            turn_id=turn_id,
            execution_id=execution_id,
            payload=payload,
        )
        return event

    def _issue_resume_credential(
        self,
        session: VoiceSessionRecord,
    ) -> VoiceResumeCredential:
        credential = self.resume_tokens.issue(session)
        self.store.register_resume_token(
            VoiceResumeTokenRecord(
                tenant_id=session.tenant_id,
                session_id=session.session_id,
                user_id=session.user_id,
                resume_token_jti=credential.jti,
                session_generation=session.session_generation,
                issued_at=credential.issued_at,
                expires_at=credential.expires_at,
            )
        )
        return credential

    def create_session(
        self,
        principal: PrincipalContext,
        payload: VoiceSessionCreateRequest,
    ) -> VoiceSessionRecord:
        self._require_enabled()
        if payload.requested_agent != "Orkio":
            raise ConflictError(
                "VOICE_SESSION_ORKIO_ONLY",
                "R0.7.0 voice sessions are Orkio-only.",
            )
        if payload.interaction_mode != "single":
            raise ConflictError(
                "VOICE_SESSION_SINGLE_MODE_ONLY",
                "R0.7.0 voice sessions use single-agent mode.",
            )
        if self.settings.voice_consent_required and not payload.consent_granted:
            raise DomainError(
                "VOICE_CONSENT_REQUIRED",
                "Microphone consent is required.",
                status_code=400,
            )

        self.platform_service.repository.get_thread(
            principal.tenant_id,
            payload.thread_id,
        )
        active_sessions = self.store.count_active_sessions(
            principal.tenant_id,
            principal.user_id,
        )
        if active_sessions >= self.settings.voice_max_active_sessions_per_user:
            raise ConflictError(
                "VOICE_ACTIVE_SESSION_LIMIT_REACHED",
                "Active voice session limit reached for this user.",
            )
        session = VoiceSessionRecord(
            tenant_id=principal.tenant_id,
            session_id=new_id("voice_session"),
            thread_id=payload.thread_id,
            user_id=principal.user_id,
            provider=self.settings.voice_provider,
        )
        created = self.store.create_session(session)
        self._append_backend_event(
            created,
            "voice.session.created",
            source_event_key=f"{created.session_id}:created",
            payload={
                "requested_agent": "Orkio",
                "resolved_agent": "Orkio",
                "turn_owner": "Orkio",
                "ownership_locked": True,
                "raw_audio_retention": (
                    self.settings.voice_raw_audio_retention
                ),
            },
        )
        return self.store.get_session(
            principal.tenant_id,
            created.session_id,
        )

    def create_call(
        self,
        principal: PrincipalContext,
        session_id: str,
        payload: VoiceCallOfferRequest,
    ) -> VoiceCallAnswer:
        self._require_enabled()
        session = self.store.get_session(
            principal.tenant_id,
            session_id,
        )
        if session.user_id != principal.user_id and principal.role != "admin":
            raise DomainError(
                "VOICE_SESSION_FORBIDDEN",
                "Voice session belongs to another user.",
                status_code=403,
            )
        if session.session_generation != payload.expected_session_generation:
            raise ConflictError(
                "VOICE_STALE_GENERATION",
                "Voice session generation is stale.",
            )
        if session.status == "closed":
            raise ConflictError(
                "VOICE_SESSION_CLOSED",
                "Voice session is already closed.",
            )

        result = self.provider.create_call(
            sdp_offer=payload.sdp,
            session=session,
        )
        connected = self.store.connect_session(
            principal.tenant_id,
            session_id,
            expected_generation=payload.expected_session_generation,
            source_connection_id=payload.source_connection_id,
            provider_call_id=result.provider_call_id,
        )
        self._append_backend_event(
            connected,
            "voice.session.connected",
            source_event_key=f"{result.provider_call_id}:connected",
            payload={
                "provider": connected.provider,
                "provider_call_id": result.provider_call_id,
                "session_generation": connected.session_generation,
            },
        )
        current = self.store.get_session(
            principal.tenant_id,
            session_id,
        )
        credential = self._issue_resume_credential(current)
        return VoiceCallAnswer(
            session=current,
            sdp=result.sdp_answer,
            provider_call_id=result.provider_call_id,
            resume_token=credential.token,
            resume_token_expires_at=credential.expires_at,
        )

    def resume_session(
        self,
        principal: PrincipalContext,
        session_id: str,
        *,
        resume_token: str,
        expected_generation: int,
        source_connection_id: str,
    ) -> tuple[VoiceSessionRecord, VoiceResumeCredential]:
        self._require_enabled()
        current = self.store.get_session(
            principal.tenant_id,
            session_id,
        )
        if current.user_id != principal.user_id and principal.role != "admin":
            raise DomainError(
                "VOICE_SESSION_FORBIDDEN",
                "Voice session belongs to another user.",
                status_code=403,
            )
        claims = self.resume_tokens.verify(
            resume_token,
            current,
            expected_generation=expected_generation,
        )
        resume_token_jti = str(claims["jti"])
        if current.reconnect_attempts >= (
            self.settings.voice_max_reconnect_attempts
        ):
            raise ConflictError(
                "VOICE_RECONNECT_LIMIT_REACHED",
                "Voice reconnect limit reached.",
            )
        resumed = self.store.resume_session(
            principal.tenant_id,
            session_id,
            expected_generation=expected_generation,
            source_connection_id=source_connection_id,
            resume_token_jti=resume_token_jti,
        )
        self._append_backend_event(
            resumed,
            "voice.session.resumed",
            source_event_key=(
                f"{session_id}:resumed:{resumed.session_generation}"
            ),
            payload={
                "session_generation": resumed.session_generation,
                "resume_cursor": resumed.last_canonical_sequence,
            },
        )
        current = self.store.get_session(
            principal.tenant_id,
            session_id,
        )
        return current, self._issue_resume_credential(current)

    def append_event(
        self,
        principal: PrincipalContext,
        session_id: str,
        payload: VoiceEventAppendRequest,
    ) -> VoiceEventRecord:
        session = self.store.get_session(
            principal.tenant_id,
            session_id,
        )
        if session.user_id != principal.user_id and principal.role != "admin":
            raise DomainError(
                "VOICE_SESSION_FORBIDDEN",
                "Voice session belongs to another user.",
                status_code=403,
            )
        try:
            source_delivery_id = payload.source_delivery_key()
            semantic_operation_id = payload.semantic_operation_key()
        except ValueError as exc:
            raise DomainError(
                str(exc),
                "A stable source event identifier is required.",
                status_code=400,
            ) from exc
        event, _ = self.store.append_event(
            tenant_id=principal.tenant_id,
            session_id=session_id,
            source=payload.source,
            source_event_key=semantic_operation_id,
            source_delivery_id=source_delivery_id,
            semantic_operation_id=semantic_operation_id,
            event_type=payload.event_type,
            session_generation=payload.session_generation,
            source_sequence=payload.source_sequence,
            source_connection_id=payload.source_connection_id,
            turn_id=payload.turn_id,
            execution_id=payload.execution_id,
            payload=payload.payload,
        )
        return event

    @staticmethod
    def _turn_result(turn: VoiceTurnRecord) -> VoiceTurnResult:
        if turn.response_payload is None:
            raise ConflictError(
                "VOICE_TURN_RESPONSE_NOT_READY",
                "Voice turn response is not ready.",
            )
        response = ResponseEnvelope(**turn.response_payload)
        if not turn.assistant_content_sha256 or not turn.tts_input_sha256:
            raise ConflictError(
                "VOICE_TURN_HASH_NOT_READY",
                "Voice turn content hash is not ready.",
            )
        return VoiceTurnResult(
            turn=turn,
            response=response,
            assistant_content_sha256=turn.assistant_content_sha256,
            tts_input_sha256=turn.tts_input_sha256,
        )

    def complete_turn(
        self,
        principal: PrincipalContext,
        session_id: str,
        payload: VoiceTurnCreateRequest,
    ) -> VoiceTurnResult:
        self._require_enabled()
        session = self.store.get_session(
            principal.tenant_id,
            session_id,
        )
        if session.user_id != principal.user_id and principal.role != "admin":
            raise DomainError(
                "VOICE_SESSION_FORBIDDEN",
                "Voice session belongs to another user.",
                status_code=403,
            )
        if session.status == "closed":
            raise ConflictError(
                "VOICE_SESSION_CLOSED",
                "Voice session is already closed.",
            )
        if session.session_generation != payload.session_generation:
            # Semantic transcript dedupe is checked before generation rejection.
            existing = self.store.get_turn_by_transcript(
                principal.tenant_id,
                session_id,
                payload.transcript_id,
            )
            if existing is not None and existing.response_payload is not None:
                return self._turn_result(existing)
            raise ConflictError(
                "VOICE_STALE_GENERATION",
                "Voice session generation is stale.",
            )

        existing = self.store.get_turn_by_transcript(
            principal.tenant_id,
            session_id,
            payload.transcript_id,
        )
        if existing is not None:
            if existing.response_payload is not None:
                return self._turn_result(existing)
            if existing.status in {"accepted", "processing"}:
                raise ConflictError(
                    "VOICE_TURN_IN_PROGRESS",
                    "Voice turn is still being processed.",
                )
            raise ConflictError(
                "VOICE_TURN_ALREADY_TERMINAL",
                "Voice turn is already terminal.",
            )

        turn_id = new_id("voice_turn")
        request_id = (
            "request_voice_"
            + hashlib.sha256(
                (
                    f"{principal.tenant_id}:{session_id}:"
                    f"{payload.transcript_id}"
                ).encode("utf-8")
            ).hexdigest()[:32]
        )
        turn = VoiceTurnRecord(
            tenant_id=principal.tenant_id,
            session_id=session_id,
            turn_id=turn_id,
            transcript_id=payload.transcript_id,
            request_id=request_id,
            status="accepted",
            user_transcript=payload.transcript,
        )
        turn, created = self.store.reserve_turn(turn)
        if not created:
            if turn.response_payload is not None:
                return self._turn_result(turn)
            raise ConflictError(
                "VOICE_TURN_IN_PROGRESS",
                "Voice turn is still being processed.",
            )

        self.store.append_event(
            tenant_id=principal.tenant_id,
            session_id=session_id,
            source="browser",
            source_event_key=payload.transcript_id,
            source_delivery_id=payload.client_event_id,
            semantic_operation_id=payload.transcript_id,
            event_type="voice.transcript.final",
            session_generation=payload.session_generation,
            source_connection_id=session.source_connection_id,
            turn_id=turn.turn_id,
            payload={
                "transcript_id": payload.transcript_id,
                "speaker_type": "user",
                "speaker_id": principal.user_id,
                "content_sha256": canonical_text_sha256(
                    payload.transcript
                ),
            },
        )
        self._append_backend_event(
            session,
            "voice.turn.accepted",
            source_event_key=f"{turn.turn_id}:accepted",
            turn_id=turn.turn_id,
            payload={"transcript_id": turn.transcript_id},
        )
        turn = self.store.update_turn(
            turn.model_copy(update={"status": "processing"})
        )

        try:
            response = self.platform_service.complete_chat(
                principal,
                ChatRequest(
                    thread_id=session.thread_id,
                    content=payload.transcript,
                    requested_agent="Orkio",
                    interaction_mode="single",
                    request_id=request_id,
                ),
            )
            if response.turn_owner != "Orkio":
                raise ConflictError(
                    "VOICE_OWNER_DIVERGENCE",
                    "Voice response owner diverged from Orkio.",
                )
            content_hash = canonical_text_sha256(response.content)
            completed = turn.model_copy(
                update={
                    "execution_id": response.execution_id,
                    "response_envelope_id": response.message_id,
                    "status": "processing",
                    "assistant_content": response.content,
                    "assistant_content_sha256": content_hash,
                    "tts_input_sha256": content_hash,
                    "audio_status": "pending",
                    "spoken_content_complete": False,
                    "canonical_text_preserved": True,
                    "response_payload": response.model_dump(mode="json"),
                    "completed_at": None,
                }
            )
            completed = self.store.update_turn(completed)
            current_session = self.store.get_session(
                principal.tenant_id,
                session_id,
            )
            self._append_backend_event(
                current_session,
                "voice.assistant.transcript.final",
                source_event_key=f"{turn.turn_id}:assistant-transcript-final",
                turn_id=turn.turn_id,
                execution_id=response.execution_id,
                payload={
                    "response_envelope_id": response.message_id,
                    "assistant_content_sha256": content_hash,
                    "tts_input_sha256": content_hash,
                    "owner": "Orkio",
                },
            )
            return self._turn_result(completed)
        except DomainError as exc:
            failed = turn.model_copy(
                update={
                    "status": "failed",
                    "error_code": exc.code,
                    "error_message": exc.message,
                    "completed_at": utc_now(),
                    "audio_status": "failed",
                }
            )
            self.store.update_turn(failed)
            current_session = self.store.get_session(
                principal.tenant_id,
                session_id,
            )
            self._append_backend_event(
                current_session,
                "voice.turn.failed",
                source_event_key=f"{turn.turn_id}:failed:{exc.code}",
                turn_id=turn.turn_id,
                payload={"error_code": exc.code},
            )
            raise
        except Exception as exc:
            failed = turn.model_copy(
                update={
                    "status": "failed",
                    "error_code": "VOICE_TURN_FAILED",
                    "error_message": "Canonical voice turn failed.",
                    "completed_at": utc_now(),
                    "audio_status": "failed",
                }
            )
            self.store.update_turn(failed)
            current_session = self.store.get_session(
                principal.tenant_id,
                session_id,
            )
            self._append_backend_event(
                current_session,
                "voice.turn.failed",
                source_event_key=f"{turn.turn_id}:failed",
                turn_id=turn.turn_id,
                payload={"error_code": "VOICE_TURN_FAILED"},
            )
            raise ServiceUnavailableError(
                "VOICE_TURN_FAILED",
                "Canonical voice turn failed.",
            ) from exc

    def report_audio(
        self,
        principal: PrincipalContext,
        session_id: str,
        turn_id: str,
        payload: VoiceAudioReportRequest,
    ) -> VoiceTurnRecord:
        session = self.store.get_session(
            principal.tenant_id,
            session_id,
        )
        if session.user_id != principal.user_id and principal.role != "admin":
            raise DomainError(
                "VOICE_SESSION_FORBIDDEN",
                "Voice session belongs to another user.",
                status_code=403,
            )
        turn = self.store.get_turn(
            principal.tenant_id,
            session_id,
            turn_id,
        )
        if session.session_generation != payload.session_generation:
            raise ConflictError(
                "VOICE_STALE_GENERATION",
                "Voice session generation is stale.",
            )

        terminal_status = {
            "completed": "completed",
            "interrupted": "interrupted",
            "failed": "failed",
        }.get(payload.audio_status)
        if turn.status in {"completed", "interrupted", "failed"}:
            if terminal_status == turn.status:
                return turn
            raise ConflictError(
                "VOICE_TURN_ALREADY_TERMINAL",
                "Voice turn is already terminal.",
            )

        spoken_hash = canonical_text_sha256(payload.spoken_transcript)
        expected_hash = turn.assistant_content_sha256
        if expected_hash is None:
            raise ConflictError(
                "VOICE_TURN_HASH_NOT_READY",
                "Voice turn content hash is not ready.",
            )

        if payload.audio_status == "completed" and spoken_hash != expected_hash:
            failed = turn.model_copy(
                update={
                    "status": "failed",
                    "completed_at": utc_now(),
                    "audio_status": "failed",
                    "spoken_content_complete": False,
                    "canonical_text_preserved": True,
                    "tts_input_sha256": expected_hash,
                    "error_code": "VOICE_TTS_CONTENT_MISMATCH",
                    "error_message": (
                        "Spoken transcript diverged from canonical text."
                    ),
                }
            )
            failed = self.store.update_turn(failed)
            self.store.append_event(
                tenant_id=principal.tenant_id,
                session_id=session_id,
                source="provider",
                source_event_key=(
                    payload.response_id
                    or f"{turn_id}:voice.turn.failed"
                ),
                source_delivery_id=payload.provider_event_id,
                semantic_operation_id=(
                    payload.response_id
                    or f"{turn_id}:voice.turn.failed"
                ),
                event_type="voice.turn.failed",
                session_generation=payload.session_generation,
                source_connection_id=session.source_connection_id,
                turn_id=turn_id,
                execution_id=turn.execution_id,
                payload={
                    "error_code": "VOICE_TTS_CONTENT_MISMATCH",
                    "assistant_content_sha256": expected_hash,
                    "tts_input_sha256": expected_hash,
                    "tts_output_sha256": spoken_hash,
                    "canonical_text_preserved": True,
                },
            )
            raise ConflictError(
                "VOICE_TTS_CONTENT_MISMATCH",
                "Spoken transcript diverged from canonical text.",
            )

        status_update = turn.status
        completed_at = turn.completed_at
        if terminal_status is not None:
            status_update = terminal_status
            completed_at = utc_now()

        updated = turn.model_copy(
            update={
                "status": status_update,
                "completed_at": completed_at,
                "audio_status": payload.audio_status,
                "spoken_content_complete": (
                    payload.audio_status == "completed"
                    and spoken_hash == expected_hash
                ),
                "canonical_text_preserved": True,
                # This field represents the canonical text supplied to TTS,
                # never the provider's partial/observed output transcript.
                "tts_input_sha256": expected_hash,
            }
        )
        updated = self.store.update_turn(updated)
        event_type = {
            "speaking": "voice.assistant.audio.started",
            "completed": "voice.turn.completed",
            "interrupted": "voice.turn.interrupted",
            "failed": "voice.turn.failed",
            "pending": "voice.assistant.transcript.final",
        }[payload.audio_status]
        self.store.append_event(
            tenant_id=principal.tenant_id,
            session_id=session_id,
            source="provider",
            source_event_key=(
                payload.response_id
                or f"{turn_id}:{event_type}"
            ),
            source_delivery_id=payload.provider_event_id,
            semantic_operation_id=(
                payload.response_id
                or f"{turn_id}:{event_type}"
            ),
            event_type=event_type,
            session_generation=payload.session_generation,
            source_connection_id=session.source_connection_id,
            turn_id=turn_id,
            execution_id=turn.execution_id,
            payload={
                "response_id": payload.response_id,
                "audio_status": payload.audio_status,
                "turn_status": updated.status,
                "spoken_content_complete": updated.spoken_content_complete,
                "canonical_text_preserved": True,
                "assistant_content_sha256": expected_hash,
                "tts_input_sha256": expected_hash,
                "tts_output_sha256": spoken_hash,
            },
        )
        return updated


    def close_session(
        self,
        principal: PrincipalContext,
        session_id: str,
        payload: VoiceCloseRequest,
    ) -> VoiceSessionRecord:
        session = self.store.get_session(
            principal.tenant_id,
            session_id,
        )
        if session.user_id != principal.user_id and principal.role != "admin":
            raise DomainError(
                "VOICE_SESSION_FORBIDDEN",
                "Voice session belongs to another user.",
                status_code=403,
            )
        if session.status == "closed":
            return session

        provider_hangup = True
        if session.provider_call_id:
            provider_hangup = self.provider.hangup(
                session.provider_call_id
            )

        # Provider hangup is attempted before the database transaction so no
        # external network call is performed while the session row is locked.
        # The closing event, closed event and session terminal state are then
        # committed atomically by the store.
        closed = self.store.close_session(
            principal.tenant_id,
            session_id,
            expected_generation=payload.expected_session_generation,
            close_reason=payload.close_reason,
            microphone_released=True,
            player_released=True,
            provider_hangup=provider_hangup,
            source_connection_id=session.source_connection_id,
        )
        logger.info(
            "voice_session_closed session_id=%s tenant_id=%s reason=%s",
            closed.session_id,
            closed.tenant_id,
            closed.close_reason,
        )
        return closed

    def status(
        self,
        principal: PrincipalContext,
        session_id: str,
        *,
        after_sequence: int = 0,
    ) -> VoiceSessionStatusEnvelope:
        session = self.store.get_session(
            principal.tenant_id,
            session_id,
        )
        if session.user_id != principal.user_id and principal.role != "admin":
            raise DomainError(
                "VOICE_SESSION_FORBIDDEN",
                "Voice session belongs to another user.",
                status_code=403,
            )
        return VoiceSessionStatusEnvelope(
            session=session,
            events=self.store.list_events(
                principal.tenant_id,
                session_id,
                after_sequence=after_sequence,
            ),
        )
