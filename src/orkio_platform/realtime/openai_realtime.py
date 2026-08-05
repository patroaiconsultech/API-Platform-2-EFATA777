from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol

import httpx

from orkio_platform.config import Settings
from orkio_platform.domain.errors import ServiceUnavailableError
from orkio_platform.realtime.voice_models import VoiceSessionRecord


@dataclass(frozen=True, slots=True)
class RealtimeCallResult:
    sdp_answer: str
    provider_call_id: str


class RealtimeVoiceProvider(Protocol):
    def create_call(
        self,
        *,
        sdp_offer: str,
        session: VoiceSessionRecord,
    ) -> RealtimeCallResult: ...

    def hangup(self, provider_call_id: str) -> bool: ...


class DisabledRealtimeVoiceProvider:
    def create_call(
        self,
        *,
        sdp_offer: str,
        session: VoiceSessionRecord,
    ) -> RealtimeCallResult:
        raise ServiceUnavailableError(
            "REALTIME_VOICE_DISABLED",
            "Realtime voice provider is disabled.",
        )

    def hangup(self, provider_call_id: str) -> bool:
        return False


class OpenAIRealtimeVoiceProvider:
    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        if settings.openai_api_key is None:
            raise ValueError("OPENAI_API_KEY_REQUIRED_FOR_VOICE")
        self.settings = settings
        self.client = client or httpx.Client(
            timeout=httpx.Timeout(settings.openai_timeout_seconds),
        )

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": (
                "Bearer "
                + self.settings.openai_api_key.get_secret_value()
            ),
        }
        if self.settings.openai_organization_id:
            headers["OpenAI-Organization"] = (
                self.settings.openai_organization_id
            )
        if self.settings.openai_project_id:
            headers["OpenAI-Project"] = (
                self.settings.openai_project_id
            )
        return headers

    def _session_payload(
        self,
        session: VoiceSessionRecord,
    ) -> dict[str, object]:
        instructions = (
            "You are the realtime media transport for ORKIO. "
            "Do not answer user questions directly. "
            "Input audio must be transcribed. Automatic model responses are "
            "disabled. When the client requests an out-of-band response, "
            "read the supplied canonical ORKIO text exactly, without adding, "
            "removing, translating or paraphrasing content. "
            f"Canonical owner: {session.turn_owner}. "
            f"Voice session: {session.session_id}."
        )
        return {
            "type": "realtime",
            "model": self.settings.openai_realtime_model,
            "instructions": instructions,
            "output_modalities": ["audio"],
            "audio": {
                "input": {
                    "transcription": {
                        "model": (
                            self.settings
                            .openai_realtime_transcription_model
                        ),
                        "language": "pt",
                    },
                    "turn_detection": {
                        "type": "server_vad",
                        "create_response": False,
                        "interrupt_response": True,
                        "prefix_padding_ms": 300,
                        "silence_duration_ms": 650,
                        "idle_timeout_ms": (
                            self.settings.voice_idle_timeout_seconds
                            * 1000
                        ),
                    },
                },
                "output": {
                    "voice": self.settings.openai_realtime_voice,
                    "speed": 1.0,
                },
            },
            "max_output_tokens": min(
                self.settings.openai_max_output_tokens,
                4096,
            ),
            "tracing": None,
        }

    @staticmethod
    def _provider_call_id(response: httpx.Response) -> str:
        location = response.headers.get("location", "").rstrip("/")
        call_id = location.rsplit("/", 1)[-1] if location else ""
        if not call_id:
            call_id = response.headers.get("x-request-id", "")
        if not call_id:
            raise ServiceUnavailableError(
                "REALTIME_CALL_ID_MISSING",
                "Realtime provider did not return a call identifier.",
            )
        return call_id

    def create_call(
        self,
        *,
        sdp_offer: str,
        session: VoiceSessionRecord,
    ) -> RealtimeCallResult:
        url = f"{self.settings.openai_base_url}/realtime/calls"
        files = {
            "sdp": (
                "offer.sdp",
                sdp_offer.encode("utf-8"),
                "application/sdp",
            ),
            "session": (
                None,
                json.dumps(
                    self._session_payload(session),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                "application/json",
            ),
        }
        try:
            response = self.client.post(
                url,
                headers=self._headers(),
                files=files,
            )
        except httpx.HTTPError as exc:
            raise ServiceUnavailableError(
                "REALTIME_PROVIDER_UNREACHABLE",
                "Realtime provider could not be reached.",
            ) from exc
        if response.status_code not in {200, 201}:
            raise ServiceUnavailableError(
                "REALTIME_PROVIDER_REJECTED_CALL",
                (
                    "Realtime provider rejected the call "
                    f"with status {response.status_code}."
                ),
            )
        answer = response.text.strip()
        if not answer:
            raise ServiceUnavailableError(
                "REALTIME_SDP_ANSWER_MISSING",
                "Realtime provider returned an empty SDP answer.",
            )
        return RealtimeCallResult(
            sdp_answer=answer,
            provider_call_id=self._provider_call_id(response),
        )

    def hangup(self, provider_call_id: str) -> bool:
        url = (
            f"{self.settings.openai_base_url}/realtime/calls/"
            f"{provider_call_id}/hangup"
        )
        try:
            response = self.client.post(
                url,
                headers=self._headers(),
            )
        except httpx.HTTPError:
            return False
        return response.status_code in {200, 202, 204}


def build_realtime_voice_provider(
    settings: Settings,
) -> RealtimeVoiceProvider:
    if (
        settings.realtime_voice_enabled
        and settings.voice_provider == "openai_realtime"
    ):
        return OpenAIRealtimeVoiceProvider(settings)
    return DisabledRealtimeVoiceProvider()
