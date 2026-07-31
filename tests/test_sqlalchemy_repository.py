from pathlib import Path
import pytest
from orkio_platform.domain.errors import NotFoundError
from orkio_platform.domain.models import MessageRecord, ThreadRecord
from orkio_platform.infrastructure.database import create_database_engine
from orkio_platform.infrastructure.sqlalchemy_repository import SQLAlchemyRepository

def build_repository(path: Path) -> SQLAlchemyRepository:
    repository = SQLAlchemyRepository(create_database_engine(f"sqlite+pysqlite:///{path}"))
    repository.create_schema_for_tests()
    return repository

def test_persists_across_repository_instances(tmp_path):
    database = tmp_path/"orkio.sqlite"
    first = build_repository(database)
    thread = ThreadRecord(thread_id="thread-1",tenant_id="tenant-a",created_by="user-a",title="Persistente")
    first.create_thread(thread)
    first.add_message(MessageRecord(
        message_id="message-1",thread_id="thread-1",tenant_id="tenant-a",
        user_id="user-a",role="user",content="Olá",
    ))
    second = build_repository(database)
    assert second.get_thread("tenant-a","thread-1").title == "Persistente"
    assert [item.content for item in second.list_messages("tenant-a","thread-1")] == ["Olá"]

def test_composite_tenant_key_blocks_cross_tenant_access(tmp_path):
    repository = build_repository(tmp_path/"tenant.sqlite")
    repository.create_thread(ThreadRecord(
        thread_id="same-id",tenant_id="tenant-a",created_by="user-a",title="A",
    ))
    with pytest.raises(NotFoundError):
        repository.get_thread("tenant-b","same-id")
