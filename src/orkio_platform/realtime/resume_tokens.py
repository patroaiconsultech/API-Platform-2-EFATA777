from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from orkio_platform.config import Settings
from orkio_platform.domain.errors import ConflictError
from orkio_platform.realtime.voice_models import VoiceSessionRecord


@dataclass(frozen=True, slots=True)
class VoiceResumeCredential:
    token: str
    expires_at: datetime


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(value + padding)
    except Exception as exc:
        raise ConflictError(
            "VOICE_RESUME_TOKEN_INVALID",
            "Voice resume token is invalid.",
        ) from exc


class VoiceResumeTokenManager:
    """Issues short-lived, session-bound and generation-bound resume tokens."""

    def __init__(self, settings: Settings) -> None:
        secret = settings.voice_resume_token_secret
        if secret is None:
            self._secret: bytes | None = None
        else:
            self._secret = secret.get_secret_value().encode("utf-8")
        self._ttl_seconds = min(
            settings.voice_resume_token_ttl_seconds,
            settings.voice_reconnect_deadline_seconds,
        )

    def _require_secret(self) -> bytes:
        if self._secret is None:
            raise ConflictError(
                "VOICE_RESUME_TOKEN_SECRET_UNAVAILABLE",
                "Voice resume token signing is unavailable.",
            )
        return self._secret

    def issue(self, session: VoiceSessionRecord) -> VoiceResumeCredential:
        secret = self._require_secret()
        issued_at = int(time.time())
        expires_at_epoch = issued_at + self._ttl_seconds
        claims = {
            "v": 1,
            "tenant_id": session.tenant_id,
            "user_id": session.user_id,
            "thread_id": session.thread_id,
            "session_id": session.session_id,
            "session_generation": session.session_generation,
            "iat": issued_at,
            "exp": expires_at_epoch,
            "jti": secrets.token_urlsafe(16),
        }
        payload = json.dumps(
            claims,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        encoded_payload = _b64url_encode(payload)
        signature = hmac.new(
            secret,
            encoded_payload.encode("ascii"),
            hashlib.sha256,
        ).digest()
        token = f"{encoded_payload}.{_b64url_encode(signature)}"
        return VoiceResumeCredential(
            token=token,
            expires_at=datetime.fromtimestamp(
                expires_at_epoch,
                tz=timezone.utc,
            ),
        )

    def verify(
        self,
        token: str,
        session: VoiceSessionRecord,
        *,
        expected_generation: int,
    ) -> dict[str, object]:
        secret = self._require_secret()
        try:
            encoded_payload, encoded_signature = token.split(".", 1)
        except ValueError as exc:
            raise ConflictError(
                "VOICE_RESUME_TOKEN_INVALID",
                "Voice resume token is invalid.",
            ) from exc

        supplied_signature = _b64url_decode(encoded_signature)
        expected_signature = hmac.new(
            secret,
            encoded_payload.encode("ascii"),
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(
            supplied_signature,
            expected_signature,
        ):
            raise ConflictError(
                "VOICE_RESUME_TOKEN_INVALID",
                "Voice resume token is invalid.",
            )

        try:
            claims = json.loads(
                _b64url_decode(encoded_payload).decode("utf-8")
            )
        except Exception as exc:
            raise ConflictError(
                "VOICE_RESUME_TOKEN_INVALID",
                "Voice resume token is invalid.",
            ) from exc

        now = int(time.time())
        if claims.get("v") != 1:
            raise ConflictError(
                "VOICE_RESUME_TOKEN_INVALID",
                "Voice resume token version is invalid.",
            )
        if not isinstance(claims.get("exp"), int) or claims["exp"] < now:
            raise ConflictError(
                "VOICE_RESUME_TOKEN_EXPIRED",
                "Voice resume token has expired.",
            )

        required_matches = {
            "tenant_id": session.tenant_id,
            "user_id": session.user_id,
            "thread_id": session.thread_id,
            "session_id": session.session_id,
            "session_generation": expected_generation,
        }
        if any(
            claims.get(name) != value
            for name, value in required_matches.items()
        ):
            raise ConflictError(
                "VOICE_RESUME_TOKEN_SCOPE_MISMATCH",
                "Voice resume token does not match this session.",
            )
        if session.session_generation != expected_generation:
            raise ConflictError(
                "VOICE_STALE_GENERATION",
                "Voice session generation is stale.",
            )
        return claims
