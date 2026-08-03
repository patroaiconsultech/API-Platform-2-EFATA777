from datetime import timedelta
from pathlib import Path

import pytest

from orkio_platform.domain.models import (
    ExecutionRecord,
    MessageRecord,
    ThreadRecord,
    utc_now,
)
from orkio_platform.infrastructure.database import create_database_engine
from orkio_platform.infrastructure.sqlalchemy_repository import (
    SQLAlchemyRepository,
)


def build_repository(
    path: Path,
    *,
    failure_injector=None,
) -> SQLAlchemyRepository:
    repository = SQLAlchemyRepository(
        create_database_engine(f"sqlite+pysqlite:///{path}"),
        failure_injector=failure_injector,
    )
    repository.create_schema_for_tests()
    return repository


def seed_execution(repository: SQLAlchemyRepository) -> ExecutionRecord:
    repository.create_thread(
        ThreadRecord(
            thread_id="thread-1",
            tenant_id="tenant-a",
            created_by="user-a",
            title="Atomic",
        )
    )
    now = utc_now()
    execution = ExecutionRecord(
        tenant_id="tenant-a",
        request_id="request-1",
        execution_id="execution-1",
        thread_id="thread-1",
        user_id="user-a",
        requested_agent="Orion",
        resolved_agent="Orion",
        turn_owner="Orion",
        display_name="Atlas",
        route_family="explicit_agent",
        request_fingerprint_sha256="a" * 64,
        lease_owner="execution-1",
        heartbeat_at=now,
        lease_expires_at=now + timedelta(seconds=60),
        started_at=now,
    )
    reserved, created = repository.reserve_execution(execution)
    assert created is True
    return reserved


def messages_for(execution: ExecutionRecord):
    user = MessageRecord(
        message_id="message-user",
        request_id=execution.request_id,
        execution_id=execution.execution_id,
        thread_id=execution.thread_id,
        tenant_id=execution.tenant_id,
        user_id=execution.user_id,
        role="user",
        content="Olá",
        route_family=execution.route_family,
        status="success",
    )
    assistant = MessageRecord(
        message_id="message-assistant",
        request_id=execution.request_id,
        execution_id=execution.execution_id,
        thread_id=execution.thread_id,
        tenant_id=execution.tenant_id,
        user_id=execution.user_id,
        role="assistant",
        content="Resposta",
        agent_id="Orion",
        agent_name="Orion",
        display_name="Atlas",
        final_speaker="Orion",
        turn_owner="Orion",
        route_family=execution.route_family,
        status="success",
    )
    return user, assistant


def test_success_completion_is_atomic(tmp_path):
    repository = build_repository(tmp_path / "success.sqlite")
    execution = seed_execution(repository)
    user, assistant = messages_for(execution)
    completed = repository.complete_execution(
        execution,
        user,
        assistant,
    )
    assert completed.status == "success"
    assert completed.user_message_id == user.message_id
    assert completed.assistant_message_id == assistant.message_id
    assert [
        item.message_id
        for item in repository.list_messages("tenant-a", "thread-1")
    ] == ["message-user", "message-assistant"]


def test_failure_before_terminal_update_rolls_back_both_messages(tmp_path):
    def fail(stage: str) -> None:
        if stage == "before_success_terminal_update":
            raise RuntimeError("injected")

    repository = build_repository(
        tmp_path / "rollback.sqlite",
        failure_injector=fail,
    )
    execution = seed_execution(repository)
    user, assistant = messages_for(execution)

    with pytest.raises(RuntimeError, match="injected"):
        repository.complete_execution(
            execution,
            user,
            assistant,
        )

    assert repository.list_messages("tenant-a", "thread-1") == []
    current = repository.get_execution("tenant-a", "request-1")
    assert current is not None
    assert current.status == "running"

    aborted = repository.abort_execution(
        "tenant-a",
        "request-1",
        error_code="TURN_PERSISTENCE_FAILED",
        error_message="Atomic completion rolled back.",
    )
    assert aborted.status == "error"
    assert aborted.error_code == "TURN_PERSISTENCE_FAILED"


def test_tenant_request_id_is_unique(tmp_path):
    repository = build_repository(tmp_path / "idempotency.sqlite")
    first = seed_execution(repository)
    duplicate = first.model_copy(
        update={"execution_id": "execution-other"}
    )
    existing, created = repository.reserve_execution(duplicate)
    assert created is False
    assert existing.execution_id == "execution-1"


def test_partial_completion_is_atomic(tmp_path):
    repository = build_repository(tmp_path / "partial.sqlite")
    execution = seed_execution(repository)
    user, assistant = messages_for(execution)
    partial_message = assistant.model_copy(
        update={
            "status": "partial",
            "content": "Contribuições preservadas.",
            "error_code": "OWNER_CONTRACT_PARTIAL",
            "error_message": "Owner synthesis was blocked.",
        }
    )

    completed = repository.partial_execution(
        execution,
        user,
        partial_message,
    )

    assert completed.status == "partial"
    assert completed.error_code == "OWNER_CONTRACT_PARTIAL"
    assert [
        item.status
        for item in repository.list_messages("tenant-a", "thread-1")
    ] == ["success", "partial"]


def test_partial_failure_rolls_back_messages(tmp_path):
    def fail(stage: str) -> None:
        if stage == "before_partial_terminal_update":
            raise RuntimeError("partial injected")

    repository = build_repository(
        tmp_path / "partial-rollback.sqlite",
        failure_injector=fail,
    )
    execution = seed_execution(repository)
    user, assistant = messages_for(execution)
    partial_message = assistant.model_copy(
        update={
            "status": "partial",
            "error_code": "OWNER_CONTRACT_PARTIAL",
            "error_message": "Owner synthesis was blocked.",
        }
    )

    with pytest.raises(RuntimeError, match="partial injected"):
        repository.partial_execution(
            execution,
            user,
            partial_message,
        )

    assert repository.list_messages("tenant-a", "thread-1") == []
    current = repository.get_execution("tenant-a", "request-1")
    assert current is not None
    assert current.status == "running"
