from datetime import timedelta

import pytest
from sqlalchemy import insert, select

from orkio_platform.domain.errors import ConflictError
from orkio_platform.infrastructure.database import (
    create_database_engine,
    metadata,
    threads,
    voice_events,
    voice_resume_tokens,
    voice_sessions,
)
from orkio_platform.realtime.voice_models import (
    VoiceResumeTokenRecord,
    VoiceSessionRecord,
)
from orkio_platform.realtime.voice_store import SQLAlchemyVoiceStore


def build_sql_store():
    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(engine)
    template = VoiceSessionRecord(
        tenant_id="tenant-a",
        session_id="temp",
        thread_id="thread-a",
        user_id="user-a",
        provider="openai_realtime",
    )
    with engine.begin() as connection:
        connection.execute(
            insert(threads).values(
                tenant_id="tenant-a",
                thread_id="thread-a",
                created_by="user-a",
                title="Voice SQL",
                created_at=template.created_at,
            )
        )
    store = SQLAlchemyVoiceStore(engine)
    session = VoiceSessionRecord(
        tenant_id="tenant-a",
        session_id="voice-session-sql",
        thread_id="thread-a",
        user_id="user-a",
        provider="openai_realtime",
    )
    store.create_session(session)
    return engine, store, session


def register_test_token(
    store: SQLAlchemyVoiceStore,
    session: VoiceSessionRecord,
    *,
    jti: str = "resume-token-jti-sql-0001",
) -> VoiceResumeTokenRecord:
    token = VoiceResumeTokenRecord(
        tenant_id=session.tenant_id,
        session_id=session.session_id,
        user_id=session.user_id,
        resume_token_jti=jti,
        session_generation=session.session_generation,
        issued_at=session.created_at,
        expires_at=session.created_at + timedelta(minutes=1),
    )
    store.register_resume_token(token)
    return token


def test_sql_voice_journal_deduplicates_across_generations():
    _, store, session = build_sql_store()
    first, created = store.append_event(
        tenant_id="tenant-a",
        session_id=session.session_id,
        source="provider",
        source_event_key="semantic-provider-event-1",
        source_delivery_id="provider-delivery-1",
        semantic_operation_id="semantic-provider-event-1",
        event_type="voice.transcript.final",
        session_generation=1,
    )
    assert created is True
    token = register_test_token(store, session)
    resumed = store.resume_session(
        "tenant-a",
        session.session_id,
        expected_generation=1,
        source_connection_id="connection-2",
        resume_token_jti=token.resume_token_jti,
    )
    duplicate, created = store.append_event(
        tenant_id="tenant-a",
        session_id=session.session_id,
        source="provider",
        source_event_key="semantic-provider-event-1",
        source_delivery_id="provider-delivery-2",
        semantic_operation_id="semantic-provider-event-1",
        event_type="voice.transcript.final",
        session_generation=resumed.session_generation,
    )
    assert created is False
    assert duplicate.event_id == first.event_id
    assert duplicate.canonical_event_id == first.canonical_event_id
    assert store.get_session(
        "tenant-a",
        session.session_id,
    ).last_canonical_sequence == 1


def test_sql_resume_token_is_consumed_in_generation_transaction():
    engine, store, session = build_sql_store()
    token = register_test_token(store, session, jti="resume-token-jti-sql-once")
    resumed = store.resume_session(
        session.tenant_id,
        session.session_id,
        expected_generation=1,
        source_connection_id="connection-resume-once",
        resume_token_jti=token.resume_token_jti,
    )
    assert resumed.session_generation == 2

    with engine.connect() as connection:
        consumed_at = connection.execute(
            select(voice_resume_tokens.c.resume_token_consumed_at).where(
                voice_resume_tokens.c.tenant_id == session.tenant_id,
                voice_resume_tokens.c.resume_token_jti
                == token.resume_token_jti,
            )
        ).scalar_one()
    assert consumed_at is not None

    with pytest.raises(ConflictError, match="already been consumed"):
        store.resume_session(
            session.tenant_id,
            session.session_id,
            expected_generation=1,
            source_connection_id="connection-resume-replay",
            resume_token_jti=token.resume_token_jti,
        )


def test_sql_close_commits_terminal_events_and_row_atomically():
    engine, store, session = build_sql_store()
    closed = store.close_session(
        session.tenant_id,
        session.session_id,
        expected_generation=1,
        close_reason="user_end",
        microphone_released=True,
        player_released=True,
        provider_hangup=True,
        source_connection_id="connection-close",
    )
    assert closed.status == "closed"
    assert closed.last_canonical_sequence == 2

    with engine.connect() as connection:
        event_types = connection.execute(
            select(voice_events.c.event_type)
            .where(
                voice_events.c.tenant_id == session.tenant_id,
                voice_events.c.session_id == session.session_id,
            )
            .order_by(voice_events.c.canonical_sequence)
        ).scalars().all()
    assert event_types == [
        "voice.session.closing",
        "voice.session.closed",
    ]


def test_sql_close_rolls_back_journal_when_terminal_append_fails(
    monkeypatch,
):
    engine, store, session = build_sql_store()
    original = SQLAlchemyVoiceStore._append_event_in_connection.__func__

    def fail_closed_event(cls, connection, **kwargs):
        if kwargs["event_type"] == "voice.session.closed":
            raise RuntimeError("synthetic-terminal-write-failure")
        return original(cls, connection, **kwargs)

    monkeypatch.setattr(
        SQLAlchemyVoiceStore,
        "_append_event_in_connection",
        classmethod(fail_closed_event),
    )
    with pytest.raises(RuntimeError, match="synthetic-terminal-write-failure"):
        store.close_session(
            session.tenant_id,
            session.session_id,
            expected_generation=1,
            close_reason="fatal_error",
            microphone_released=True,
            player_released=True,
            provider_hangup=False,
        )

    with engine.connect() as connection:
        status = connection.execute(
            select(voice_sessions.c.status).where(
                voice_sessions.c.tenant_id == session.tenant_id,
                voice_sessions.c.session_id == session.session_id,
            )
        ).scalar_one()
        event_count = len(
            connection.execute(
                select(voice_events.c.event_id).where(
                    voice_events.c.tenant_id == session.tenant_id,
                    voice_events.c.session_id == session.session_id,
                )
            ).all()
        )
    assert status != "closed"
    assert event_count == 0
