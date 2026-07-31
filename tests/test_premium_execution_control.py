from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
import logging

import pytest

from orkio_platform.api.routes.chat import service as route_service
from orkio_platform.application.services import PlatformService
from orkio_platform.domain.errors import ConflictError
from orkio_platform.domain.models import (
    ChatRequest,
    ExecutionRecord,
    PrincipalContext,
    ThreadRecord,
    utc_now,
)
from orkio_platform.infrastructure.database import create_database_engine
from orkio_platform.infrastructure.repositories import (
    InMemoryRepository,
    repository,
)
from orkio_platform.infrastructure.sqlalchemy_repository import (
    SQLAlchemyRepository,
)


def parse_events(text: str) -> list[dict]:
    result = []
    current = {}
    for line in text.splitlines():
        if line.startswith("event: "):
            current["event"] = line[7:]
        elif line.startswith("data: "):
            current["data"] = json.loads(line[6:])
        elif line == "" and current:
            result.append(current)
            current = {}
    return result


def principal() -> PrincipalContext:
    return PrincipalContext(
        tenant_id="tenant-a",
        user_id="user-a",
        role="member",
    )


def test_heartbeat_extends_owned_lease():
    repo = InMemoryRepository()
    service = PlatformService(
        repo,
        execution_lease_seconds=60,
        execution_stale_after_seconds=300,
    )
    actor = principal()
    thread = service.create_thread(actor, "Lease")
    request = ChatRequest(
        thread_id=thread.thread_id,
        content="heartbeat",
        requested_agent="Orion",
        request_id="request-heartbeat",
    )
    context = service.prepare_turn(actor, request)
    _, execution, created = service.reserve_turn(context, request)
    assert created is True
    refreshed = service.heartbeat_turn(execution)
    assert refreshed.heartbeat_at >= execution.heartbeat_at
    assert refreshed.lease_expires_at > execution.lease_expires_at


def test_heartbeat_rejects_wrong_lease_owner():
    repo = InMemoryRepository()
    service = PlatformService(repo)
    actor = principal()
    thread = service.create_thread(actor, "Lease owner")
    request = ChatRequest(
        thread_id=thread.thread_id,
        content="owner",
        requested_agent="Orion",
        request_id="request-owner",
    )
    context = service.prepare_turn(actor, request)
    _, execution, _ = service.reserve_turn(context, request)
    now = utc_now()
    with pytest.raises(ConflictError) as captured:
        repo.heartbeat_execution(
            execution.tenant_id,
            execution.request_id,
            lease_owner="another-worker",
            heartbeat_at=now,
            lease_expires_at=now + timedelta(seconds=60),
        )
    assert captured.value.code == "EXECUTION_LEASE_LOST"


def test_duplicate_request_race_reserves_exactly_once():
    repo = InMemoryRepository()
    now = utc_now()
    execution = ExecutionRecord(
        tenant_id="tenant-a",
        request_id="request-race",
        execution_id="execution-race",
        thread_id="thread-race",
        user_id="user-a",
        requested_agent="Orion",
        resolved_agent="Orion",
        turn_owner="Orion",
        display_name="Orion",
        route_family="explicit_agent",
        request_fingerprint_sha256="b" * 64,
        lease_owner="execution-race",
        heartbeat_at=now,
        lease_expires_at=now + timedelta(seconds=60),
        started_at=now,
    )

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(
            pool.map(
                lambda _: repo.reserve_execution(execution),
                range(32),
            )
        )

    assert sum(1 for _, created in results if created) == 1
    assert {
        item.execution_id
        for item, _ in results
    } == {"execution-race"}


def test_running_execution_survives_repository_restart(tmp_path):
    database = tmp_path / "restart.sqlite"
    first = SQLAlchemyRepository(
        create_database_engine(f"sqlite+pysqlite:///{database}")
    )
    first.create_schema_for_tests()
    service_first = PlatformService(first)
    actor = principal()
    thread = service_first.create_thread(actor, "Restart")
    request = ChatRequest(
        thread_id=thread.thread_id,
        content="persist running",
        requested_agent="Orion",
        request_id="request-restart",
    )
    context = service_first.prepare_turn(actor, request)
    _, execution, created = service_first.reserve_turn(context, request)
    assert created is True

    second = SQLAlchemyRepository(
        create_database_engine(f"sqlite+pysqlite:///{database}")
    )
    service_second = PlatformService(second)
    restored = second.get_execution("tenant-a", "request-restart")
    assert restored is not None
    assert restored.execution_id == execution.execution_id
    assert restored.status == "running"

    with pytest.raises(ConflictError) as captured:
        service_second.complete_chat(actor, request)
    assert captured.value.code == "REQUEST_IN_PROGRESS"


def test_cancel_endpoint_persists_terminal_message_and_retry_stream(
    client,
    member_headers,
):
    thread = client.post(
        "/api/threads",
        headers=member_headers,
        json={"title": "Cancel"},
    ).json()
    payload = {
        "thread_id": thread["thread_id"],
        "content": "cancel this",
        "requested_agent": "Orion",
        "request_id": "request-cancel",
    }
    actor = principal()
    request = ChatRequest(**payload)
    context = route_service.prepare_turn(actor, request)
    _, execution, created = route_service.reserve_turn(
        context,
        request,
    )
    assert created is True
    assert execution.status == "running"

    cancelled = client.post(
        "/api/chat/executions/request-cancel/cancel",
        headers=member_headers,
        json={"reason": "Operator requested cancellation."},
    )
    assert cancelled.status_code == 200
    body = cancelled.json()
    assert body["status"] == "cancelled"
    assert body["turn_owner"] == "Orion"

    repeated = client.post(
        "/api/chat/executions/request-cancel/cancel",
        headers=member_headers,
        json={"reason": "Repeated cancellation."},
    )
    assert repeated.status_code == 200
    assert repeated.json()["message_id"] == body["message_id"]

    messages = client.get(
        f"/api/threads/{thread['thread_id']}/messages",
        headers=member_headers,
    ).json()
    assert len(messages) == 1
    assert messages[0]["role"] == "assistant"
    assert messages[0]["status"] == "cancelled"
    assert messages[0]["error_code"] == "EXECUTION_CANCELLED"

    stream = client.post(
        "/api/chat/stream",
        headers=member_headers,
        json=payload,
    )
    observed = parse_events(stream.text)
    assert [item["event"] for item in observed][-2:] == [
        "cancelled",
        "done",
    ]
    assert observed[-1]["data"]["payload"]["outcome"] == "cancelled"
    assert observed[-1]["data"]["payload"]["replayed"] is True


def test_admin_records_recovery_decision_without_mutation(
    client,
    admin_headers,
):
    thread = client.post(
        "/api/threads",
        headers=admin_headers,
        json={"title": "Recovery decision"},
    ).json()
    actor = PrincipalContext(
        tenant_id="tenant-a",
        user_id="admin-a",
        role="admin",
    )
    request = ChatRequest(
        thread_id=thread["thread_id"],
        content="recovery",
        requested_agent="Orion",
        request_id="request-recovery",
    )
    context = route_service.prepare_turn(actor, request)
    _, execution, _ = route_service.reserve_turn(context, request)

    response = client.post(
        "/api/governance/executions/request-recovery/recovery-decisions",
        headers=admin_headers,
        json={
            "decision": "abandon",
            "reason": "Human review rejected automatic recovery.",
        },
    )
    assert response.status_code == 200
    assert response.json()["decision"] == "abandon"

    listed = client.get(
        "/api/governance/executions/request-recovery/recovery-decisions",
        headers=admin_headers,
    )
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    current = repository.get_execution(
        "tenant-a",
        "request-recovery",
    )
    assert current == execution
    assert current.status == "running"


def test_execution_logs_include_correlation_fields(caplog):
    repo = InMemoryRepository()
    service = PlatformService(repo)
    actor = principal()
    thread = service.create_thread(actor, "Logs")
    request = ChatRequest(
        thread_id=thread.thread_id,
        content="log me",
        requested_agent="Orion",
        request_id="request-log",
    )
    with caplog.at_level(
        logging.INFO,
        logger="orkio.execution",
    ):
        response = service.complete_chat(actor, request)

    assert response.status == "success"
    payloads = [
        json.loads(record.message)
        for record in caplog.records
        if record.name == "orkio.execution"
    ]
    assert payloads
    assert all(item["request_id"] == "request-log" for item in payloads)
    assert all(item["execution_id"] for item in payloads)
    assert any(
        item["event"] == "execution_terminal_success"
        for item in payloads
    )
