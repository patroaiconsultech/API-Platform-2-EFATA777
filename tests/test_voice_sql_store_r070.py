
from sqlalchemy import insert

from orkio_platform.infrastructure.database import (
    create_database_engine,
    metadata,
    threads,
)
from orkio_platform.realtime.voice_models import VoiceSessionRecord
from orkio_platform.realtime.voice_store import SQLAlchemyVoiceStore


def test_sql_voice_journal_deduplicates_across_generations():
    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            insert(threads).values(
                tenant_id="tenant-a",
                thread_id="thread-a",
                created_by="user-a",
                title="Voice SQL",
                created_at=VoiceSessionRecord(
                    tenant_id="tenant-a",
                    session_id="temp",
                    thread_id="thread-a",
                    user_id="user-a",
                    provider="openai_realtime",
                ).created_at,
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
    first, created = store.append_event(
        tenant_id="tenant-a",
        session_id=session.session_id,
        source="provider",
        source_event_key="provider-event-1",
        event_type="voice.transcript.final",
        session_generation=1,
    )
    assert created is True
    resumed = store.resume_session(
        "tenant-a",
        session.session_id,
        expected_generation=1,
        source_connection_id="connection-2",
    )
    duplicate, created = store.append_event(
        tenant_id="tenant-a",
        session_id=session.session_id,
        source="provider",
        source_event_key="provider-event-1",
        event_type="voice.transcript.final",
        session_generation=resumed.session_generation,
    )
    assert created is False
    assert duplicate.event_id == first.event_id
    assert store.get_session(
        "tenant-a",
        session.session_id,
    ).last_canonical_sequence == 1
