from __future__ import annotations

import json
from threading import RLock
from typing import Protocol

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from orkio_platform.domain.errors import ConflictError, NotFoundError
from orkio_platform.domain.models import new_id, utc_now
from orkio_platform.infrastructure.database import (
    voice_events,
    voice_sessions,
    voice_turns,
)
from orkio_platform.realtime.voice_models import (
    VoiceEventRecord,
    VoiceSessionRecord,
    VoiceTurnRecord,
)


class VoiceStoreProtocol(Protocol):
    def reset(self) -> None: ...

    def create_session(
        self,
        session: VoiceSessionRecord,
    ) -> VoiceSessionRecord: ...

    def get_session(
        self,
        tenant_id: str,
        session_id: str,
    ) -> VoiceSessionRecord: ...

    def count_active_sessions(
        self,
        tenant_id: str,
        user_id: str,
    ) -> int: ...

    def connect_session(
        self,
        tenant_id: str,
        session_id: str,
        *,
        expected_generation: int,
        source_connection_id: str,
        provider_call_id: str,
    ) -> VoiceSessionRecord: ...

    def resume_session(
        self,
        tenant_id: str,
        session_id: str,
        *,
        expected_generation: int,
        source_connection_id: str,
    ) -> VoiceSessionRecord: ...

    def close_session(
        self,
        tenant_id: str,
        session_id: str,
        *,
        expected_generation: int,
        close_reason: str,
        microphone_released: bool,
        player_released: bool,
    ) -> VoiceSessionRecord: ...

    def append_event(
        self,
        *,
        tenant_id: str,
        session_id: str,
        source: str,
        source_event_key: str,
        event_type: str,
        session_generation: int,
        source_sequence: int | None = None,
        source_connection_id: str | None = None,
        turn_id: str | None = None,
        execution_id: str | None = None,
        payload: dict[str, object] | None = None,
    ) -> tuple[VoiceEventRecord, bool]: ...

    def list_events(
        self,
        tenant_id: str,
        session_id: str,
        *,
        after_sequence: int = 0,
    ) -> list[VoiceEventRecord]: ...

    def reserve_turn(
        self,
        turn: VoiceTurnRecord,
    ) -> tuple[VoiceTurnRecord, bool]: ...

    def get_turn(
        self,
        tenant_id: str,
        session_id: str,
        turn_id: str,
    ) -> VoiceTurnRecord: ...

    def get_turn_by_transcript(
        self,
        tenant_id: str,
        session_id: str,
        transcript_id: str,
    ) -> VoiceTurnRecord | None: ...

    def update_turn(
        self,
        turn: VoiceTurnRecord,
    ) -> VoiceTurnRecord: ...


def _event_source_key(
    *,
    session_id: str,
    source: str,
    source_event_key: str,
) -> tuple[str, str, str]:
    # session_generation is intentionally excluded. A provider/browser event
    # redelivered after reconnect must resolve to the original canonical event.
    return (session_id, source, source_event_key)


class InMemoryVoiceStore:
    def __init__(self) -> None:
        self._lock = RLock()
        self._sessions: dict[tuple[str, str], VoiceSessionRecord] = {}
        self._events: dict[tuple[str, str, str, str], VoiceEventRecord] = {}
        self._events_by_session: dict[
            tuple[str, str], list[VoiceEventRecord]
        ] = {}
        self._turns: dict[
            tuple[str, str, str], VoiceTurnRecord
        ] = {}
        self._turn_by_transcript: dict[
            tuple[str, str, str], tuple[str, str, str]
        ] = {}

    def reset(self) -> None:
        with self._lock:
            self._sessions.clear()
            self._events.clear()
            self._events_by_session.clear()
            self._turns.clear()
            self._turn_by_transcript.clear()

    def create_session(
        self,
        session: VoiceSessionRecord,
    ) -> VoiceSessionRecord:
        key = (session.tenant_id, session.session_id)
        with self._lock:
            if key in self._sessions:
                raise ConflictError(
                    "VOICE_SESSION_ALREADY_EXISTS",
                    "Voice session already exists.",
                )
            self._sessions[key] = session
            self._events_by_session[key] = []
        return session

    def get_session(
        self,
        tenant_id: str,
        session_id: str,
    ) -> VoiceSessionRecord:
        with self._lock:
            session = self._sessions.get((tenant_id, session_id))
        if session is None:
            raise NotFoundError(
                "VOICE_SESSION_NOT_FOUND",
                "Voice session not found.",
            )
        return session

    def _replace_session(
        self,
        session: VoiceSessionRecord,
    ) -> VoiceSessionRecord:
        self._sessions[(session.tenant_id, session.session_id)] = session
        return session

    def count_active_sessions(
        self,
        tenant_id: str,
        user_id: str,
    ) -> int:
        with self._lock:
            return sum(
                1
                for session in self._sessions.values()
                if session.tenant_id == tenant_id
                and session.user_id == user_id
                and session.status != "closed"
            )

    def connect_session(
        self,
        tenant_id: str,
        session_id: str,
        *,
        expected_generation: int,
        source_connection_id: str,
        provider_call_id: str,
    ) -> VoiceSessionRecord:
        with self._lock:
            current = self.get_session(tenant_id, session_id)
            if current.status == "closed":
                raise ConflictError(
                    "VOICE_SESSION_CLOSED",
                    "Voice session is already closed.",
                )
            if current.session_generation != expected_generation:
                raise ConflictError(
                    "VOICE_STALE_GENERATION",
                    "Voice session generation is stale.",
                )
            updated = current.model_copy(
                update={
                    "status": "connected",
                    "source_connection_id": source_connection_id,
                    "provider_call_id": provider_call_id,
                    "connected_at": current.connected_at or utc_now(),
                }
            )
            return self._replace_session(updated)

    def resume_session(
        self,
        tenant_id: str,
        session_id: str,
        *,
        expected_generation: int,
        source_connection_id: str,
    ) -> VoiceSessionRecord:
        with self._lock:
            current = self.get_session(tenant_id, session_id)
            if current.status == "closed":
                raise ConflictError(
                    "VOICE_SESSION_CLOSED",
                    "Voice session is already closed.",
                )
            if current.session_generation != expected_generation:
                raise ConflictError(
                    "VOICE_STALE_GENERATION",
                    "Voice session generation is stale.",
                )
            updated = current.model_copy(
                update={
                    "session_generation": current.session_generation + 1,
                    "source_connection_id": source_connection_id,
                    "reconnect_attempts": current.reconnect_attempts + 1,
                    "status": "connected",
                }
            )
            return self._replace_session(updated)

    def close_session(
        self,
        tenant_id: str,
        session_id: str,
        *,
        expected_generation: int,
        close_reason: str,
        microphone_released: bool,
        player_released: bool,
    ) -> VoiceSessionRecord:
        if not microphone_released or not player_released:
            raise ConflictError(
                "VOICE_MEDIA_RELEASE_REQUIRED",
                "Microphone and player must be released before close.",
            )
        with self._lock:
            current = self.get_session(tenant_id, session_id)
            if current.status == "closed":
                return current
            if current.session_generation != expected_generation:
                raise ConflictError(
                    "VOICE_STALE_GENERATION",
                    "Voice session generation is stale.",
                )
            updated = current.model_copy(
                update={
                    "status": "closed",
                    "close_reason": close_reason,
                    "microphone_released": True,
                    "player_released": True,
                    "closed_at": utc_now(),
                }
            )
            return self._replace_session(updated)

    def append_event(
        self,
        *,
        tenant_id: str,
        session_id: str,
        source: str,
        source_event_key: str,
        event_type: str,
        session_generation: int,
        source_sequence: int | None = None,
        source_connection_id: str | None = None,
        turn_id: str | None = None,
        execution_id: str | None = None,
        payload: dict[str, object] | None = None,
    ) -> tuple[VoiceEventRecord, bool]:
        semantic = (
            tenant_id,
            *_event_source_key(
                session_id=session_id,
                source=source,
                source_event_key=source_event_key,
            ),
        )
        with self._lock:
            existing = self._events.get(semantic)
            if existing is not None:
                return existing, False
            current = self.get_session(tenant_id, session_id)
            if current.status == "closed":
                raise ConflictError(
                    "VOICE_EVENT_AFTER_CLOSED",
                    "No event may be appended after session close.",
                )
            if session_generation != current.session_generation:
                raise ConflictError(
                    "VOICE_STALE_GENERATION",
                    "Voice session generation is stale.",
                )
            sequence = current.last_canonical_sequence + 1
            event = VoiceEventRecord(
                tenant_id=tenant_id,
                session_id=session_id,
                event_id=new_id("voice_event"),
                canonical_sequence=sequence,
                source=source,  # type: ignore[arg-type]
                source_event_key=source_event_key,
                event_type=event_type,
                session_generation=session_generation,
                source_sequence=source_sequence,
                source_connection_id=source_connection_id,
                turn_id=turn_id,
                execution_id=execution_id,
                payload=payload or {},
            )
            self._events[semantic] = event
            self._events_by_session[
                (tenant_id, session_id)
            ].append(event)
            self._replace_session(
                current.model_copy(
                    update={"last_canonical_sequence": sequence}
                )
            )
            return event, True

    def list_events(
        self,
        tenant_id: str,
        session_id: str,
        *,
        after_sequence: int = 0,
    ) -> list[VoiceEventRecord]:
        self.get_session(tenant_id, session_id)
        with self._lock:
            return [
                item
                for item in self._events_by_session.get(
                    (tenant_id, session_id),
                    [],
                )
                if item.canonical_sequence > after_sequence
            ]

    def reserve_turn(
        self,
        turn: VoiceTurnRecord,
    ) -> tuple[VoiceTurnRecord, bool]:
        key = (turn.tenant_id, turn.session_id, turn.turn_id)
        transcript_key = (
            turn.tenant_id,
            turn.session_id,
            turn.transcript_id,
        )
        with self._lock:
            existing_key = self._turn_by_transcript.get(transcript_key)
            if existing_key is not None:
                return self._turns[existing_key], False
            if key in self._turns:
                return self._turns[key], False
            self._turns[key] = turn
            self._turn_by_transcript[transcript_key] = key
            return turn, True

    def get_turn(
        self,
        tenant_id: str,
        session_id: str,
        turn_id: str,
    ) -> VoiceTurnRecord:
        with self._lock:
            item = self._turns.get((tenant_id, session_id, turn_id))
        if item is None:
            raise NotFoundError(
                "VOICE_TURN_NOT_FOUND",
                "Voice turn not found.",
            )
        return item

    def get_turn_by_transcript(
        self,
        tenant_id: str,
        session_id: str,
        transcript_id: str,
    ) -> VoiceTurnRecord | None:
        with self._lock:
            key = self._turn_by_transcript.get(
                (tenant_id, session_id, transcript_id)
            )
            return None if key is None else self._turns[key]

    def update_turn(
        self,
        turn: VoiceTurnRecord,
    ) -> VoiceTurnRecord:
        key = (turn.tenant_id, turn.session_id, turn.turn_id)
        with self._lock:
            if key not in self._turns:
                raise NotFoundError(
                    "VOICE_TURN_NOT_FOUND",
                    "Voice turn not found.",
                )
            self._turns[key] = turn
        return turn


class SQLAlchemyVoiceStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def reset(self) -> None:
        with self.engine.begin() as connection:
            connection.execute(delete(voice_events))
            connection.execute(delete(voice_turns))
            connection.execute(delete(voice_sessions))

    @staticmethod
    def _session_from_row(row) -> VoiceSessionRecord:
        return VoiceSessionRecord(**dict(row))

    @staticmethod
    def _event_from_row(row) -> VoiceEventRecord:
        data = dict(row)
        data["payload"] = json.loads(data.pop("payload_json"))
        return VoiceEventRecord(**data)

    @staticmethod
    def _turn_from_row(row) -> VoiceTurnRecord:
        data = dict(row)
        payload = data.pop("response_payload_json")
        data["response_payload"] = (
            None if payload is None else json.loads(payload)
        )
        return VoiceTurnRecord(**data)

    @staticmethod
    def _turn_values(turn: VoiceTurnRecord) -> dict[str, object]:
        data = turn.model_dump(exclude={"response_payload"})
        data["response_payload_json"] = (
            None
            if turn.response_payload is None
            else json.dumps(
                turn.response_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return data

    def create_session(
        self,
        session: VoiceSessionRecord,
    ) -> VoiceSessionRecord:
        try:
            with self.engine.begin() as connection:
                connection.execute(
                    insert(voice_sessions).values(**session.model_dump())
                )
        except IntegrityError as exc:
            raise ConflictError(
                "VOICE_SESSION_ALREADY_EXISTS",
                "Voice session already exists.",
            ) from exc
        return session

    def get_session(
        self,
        tenant_id: str,
        session_id: str,
    ) -> VoiceSessionRecord:
        statement = select(voice_sessions).where(
            voice_sessions.c.tenant_id == tenant_id,
            voice_sessions.c.session_id == session_id,
        )
        with self.engine.connect() as connection:
            row = connection.execute(statement).mappings().first()
        if row is None:
            raise NotFoundError(
                "VOICE_SESSION_NOT_FOUND",
                "Voice session not found.",
            )
        return self._session_from_row(row)

    def count_active_sessions(
        self,
        tenant_id: str,
        user_id: str,
    ) -> int:
        statement = select(func.count()).select_from(voice_sessions).where(
            voice_sessions.c.tenant_id == tenant_id,
            voice_sessions.c.user_id == user_id,
            voice_sessions.c.status != "closed",
        )
        with self.engine.connect() as connection:
            return int(connection.execute(statement).scalar_one())

    def connect_session(
        self,
        tenant_id: str,
        session_id: str,
        *,
        expected_generation: int,
        source_connection_id: str,
        provider_call_id: str,
    ) -> VoiceSessionRecord:
        with self.engine.begin() as connection:
            result = connection.execute(
                update(voice_sessions)
                .where(
                    voice_sessions.c.tenant_id == tenant_id,
                    voice_sessions.c.session_id == session_id,
                    voice_sessions.c.session_generation
                    == expected_generation,
                    voice_sessions.c.status != "closed",
                )
                .values(
                    status="connected",
                    source_connection_id=source_connection_id,
                    provider_call_id=provider_call_id,
                    connected_at=utc_now(),
                )
            )
            if result.rowcount != 1:
                current = self.get_session(tenant_id, session_id)
                if current.status == "closed":
                    raise ConflictError(
                        "VOICE_SESSION_CLOSED",
                        "Voice session is already closed.",
                    )
                raise ConflictError(
                    "VOICE_STALE_GENERATION",
                    "Voice session generation is stale.",
                )
        return self.get_session(tenant_id, session_id)

    def resume_session(
        self,
        tenant_id: str,
        session_id: str,
        *,
        expected_generation: int,
        source_connection_id: str,
    ) -> VoiceSessionRecord:
        with self.engine.begin() as connection:
            result = connection.execute(
                update(voice_sessions)
                .where(
                    voice_sessions.c.tenant_id == tenant_id,
                    voice_sessions.c.session_id == session_id,
                    voice_sessions.c.session_generation
                    == expected_generation,
                    voice_sessions.c.status != "closed",
                )
                .values(
                    session_generation=expected_generation + 1,
                    source_connection_id=source_connection_id,
                    reconnect_attempts=(
                        voice_sessions.c.reconnect_attempts + 1
                    ),
                    status="connected",
                )
            )
            if result.rowcount != 1:
                current = self.get_session(tenant_id, session_id)
                if current.status == "closed":
                    raise ConflictError(
                        "VOICE_SESSION_CLOSED",
                        "Voice session is already closed.",
                    )
                raise ConflictError(
                    "VOICE_STALE_GENERATION",
                    "Voice session generation is stale.",
                )
        return self.get_session(tenant_id, session_id)

    def close_session(
        self,
        tenant_id: str,
        session_id: str,
        *,
        expected_generation: int,
        close_reason: str,
        microphone_released: bool,
        player_released: bool,
    ) -> VoiceSessionRecord:
        if not microphone_released or not player_released:
            raise ConflictError(
                "VOICE_MEDIA_RELEASE_REQUIRED",
                "Microphone and player must be released before close.",
            )
        with self.engine.begin() as connection:
            current = connection.execute(
                select(voice_sessions)
                .where(
                    voice_sessions.c.tenant_id == tenant_id,
                    voice_sessions.c.session_id == session_id,
                )
                .with_for_update()
            ).mappings().first()
            if current is None:
                raise NotFoundError(
                    "VOICE_SESSION_NOT_FOUND",
                    "Voice session not found.",
                )
            if current["status"] == "closed":
                return self._session_from_row(current)
            if current["session_generation"] != expected_generation:
                raise ConflictError(
                    "VOICE_STALE_GENERATION",
                    "Voice session generation is stale.",
                )
            connection.execute(
                update(voice_sessions)
                .where(
                    voice_sessions.c.tenant_id == tenant_id,
                    voice_sessions.c.session_id == session_id,
                )
                .values(
                    status="closed",
                    close_reason=close_reason,
                    microphone_released=True,
                    player_released=True,
                    closed_at=utc_now(),
                )
            )
        return self.get_session(tenant_id, session_id)

    def append_event(
        self,
        *,
        tenant_id: str,
        session_id: str,
        source: str,
        source_event_key: str,
        event_type: str,
        session_generation: int,
        source_sequence: int | None = None,
        source_connection_id: str | None = None,
        turn_id: str | None = None,
        execution_id: str | None = None,
        payload: dict[str, object] | None = None,
    ) -> tuple[VoiceEventRecord, bool]:
        # The session row is the canonical per-session sequencer. Locking it
        # before dedupe/append makes sequence allocation and semantic
        # idempotency one transaction under PostgreSQL.
        with self.engine.begin() as connection:
            session_row = connection.execute(
                select(voice_sessions)
                .where(
                    voice_sessions.c.tenant_id == tenant_id,
                    voice_sessions.c.session_id == session_id,
                )
                .with_for_update()
            ).mappings().first()
            if session_row is None:
                raise NotFoundError(
                    "VOICE_SESSION_NOT_FOUND",
                    "Voice session not found.",
                )

            # Dedupe is intentionally checked before generation validation.
            # A source event redelivered after reconnect must return the
            # original canonical event instead of becoming a new effect.
            existing = connection.execute(
                select(voice_events).where(
                    voice_events.c.tenant_id == tenant_id,
                    voice_events.c.session_id == session_id,
                    voice_events.c.source == source,
                    voice_events.c.source_event_key == source_event_key,
                )
            ).mappings().first()
            if existing is not None:
                return self._event_from_row(existing), False

            if session_row["status"] == "closed":
                raise ConflictError(
                    "VOICE_EVENT_AFTER_CLOSED",
                    "No event may be appended after session close.",
                )
            if session_row["session_generation"] != session_generation:
                raise ConflictError(
                    "VOICE_STALE_GENERATION",
                    "Voice session generation is stale.",
                )

            sequence = int(session_row["last_canonical_sequence"]) + 1
            event = VoiceEventRecord(
                tenant_id=tenant_id,
                session_id=session_id,
                event_id=new_id("voice_event"),
                canonical_sequence=sequence,
                source=source,  # type: ignore[arg-type]
                source_event_key=source_event_key,
                event_type=event_type,
                session_generation=session_generation,
                source_sequence=source_sequence,
                source_connection_id=source_connection_id,
                turn_id=turn_id,
                execution_id=execution_id,
                payload=payload or {},
            )
            values = event.model_dump(exclude={"payload"})
            values["payload_json"] = json.dumps(
                event.payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            connection.execute(insert(voice_events).values(**values))
            connection.execute(
                update(voice_sessions)
                .where(
                    voice_sessions.c.tenant_id == tenant_id,
                    voice_sessions.c.session_id == session_id,
                )
                .values(last_canonical_sequence=sequence)
            )
            return event, True

    def list_events(
        self,
        tenant_id: str,
        session_id: str,
        *,
        after_sequence: int = 0,
    ) -> list[VoiceEventRecord]:
        self.get_session(tenant_id, session_id)
        statement = (
            select(voice_events)
            .where(
                voice_events.c.tenant_id == tenant_id,
                voice_events.c.session_id == session_id,
                voice_events.c.canonical_sequence > after_sequence,
            )
            .order_by(voice_events.c.canonical_sequence.asc())
        )
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [self._event_from_row(row) for row in rows]

    def reserve_turn(
        self,
        turn: VoiceTurnRecord,
    ) -> tuple[VoiceTurnRecord, bool]:
        try:
            with self.engine.begin() as connection:
                connection.execute(
                    insert(voice_turns).values(**self._turn_values(turn))
                )
            return turn, True
        except IntegrityError:
            existing = self.get_turn_by_transcript(
                turn.tenant_id,
                turn.session_id,
                turn.transcript_id,
            )
            if existing is None:
                raise
            return existing, False

    def get_turn(
        self,
        tenant_id: str,
        session_id: str,
        turn_id: str,
    ) -> VoiceTurnRecord:
        statement = select(voice_turns).where(
            voice_turns.c.tenant_id == tenant_id,
            voice_turns.c.session_id == session_id,
            voice_turns.c.turn_id == turn_id,
        )
        with self.engine.connect() as connection:
            row = connection.execute(statement).mappings().first()
        if row is None:
            raise NotFoundError(
                "VOICE_TURN_NOT_FOUND",
                "Voice turn not found.",
            )
        return self._turn_from_row(row)

    def get_turn_by_transcript(
        self,
        tenant_id: str,
        session_id: str,
        transcript_id: str,
    ) -> VoiceTurnRecord | None:
        statement = select(voice_turns).where(
            voice_turns.c.tenant_id == tenant_id,
            voice_turns.c.session_id == session_id,
            voice_turns.c.transcript_id == transcript_id,
        )
        with self.engine.connect() as connection:
            row = connection.execute(statement).mappings().first()
        return None if row is None else self._turn_from_row(row)

    def update_turn(
        self,
        turn: VoiceTurnRecord,
    ) -> VoiceTurnRecord:
        values = self._turn_values(turn)
        with self.engine.begin() as connection:
            result = connection.execute(
                update(voice_turns)
                .where(
                    voice_turns.c.tenant_id == turn.tenant_id,
                    voice_turns.c.session_id == turn.session_id,
                    voice_turns.c.turn_id == turn.turn_id,
                )
                .values(**values)
            )
            if result.rowcount != 1:
                raise NotFoundError(
                    "VOICE_TURN_NOT_FOUND",
                    "Voice turn not found.",
                )
        return self.get_turn(
            turn.tenant_id,
            turn.session_id,
            turn.turn_id,
        )


def build_voice_store(repository) -> VoiceStoreProtocol:
    engine = getattr(repository, "engine", None)
    if engine is None:
        return InMemoryVoiceStore()
    return SQLAlchemyVoiceStore(engine)
