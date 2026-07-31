from datetime import timedelta

import pytest

from orkio_platform.application.services import PlatformService
from orkio_platform.domain.errors import ConflictError
from orkio_platform.domain.models import (
    ChatRequest,
    ExecutionRecord,
    PrincipalContext,
    utc_now,
)
from orkio_platform.infrastructure.repositories import InMemoryRepository


def seed_running_execution(
    *,
    service: PlatformService,
    repository: InMemoryRepository,
    principal: PrincipalContext,
    request: ChatRequest,
    age_seconds: int,
) -> ExecutionRecord:
    context = service.prepare_turn(principal, request)
    started = utc_now() - timedelta(seconds=age_seconds)
    execution = ExecutionRecord(
        tenant_id=context.tenant_id,
        request_id=context.request_id,
        execution_id=context.execution_id,
        thread_id=context.thread_id,
        user_id=context.user_id,
        requested_agent=context.requested_agent,
        resolved_agent=context.resolved_agent,
        turn_owner=context.turn_owner,
        display_name=context.display_agent,
        route_family=context.route_family,
        request_fingerprint_sha256=service.request_fingerprint(
            context,
            request,
        ),
        lease_owner=context.execution_id,
        heartbeat_at=started,
        lease_expires_at=started + timedelta(seconds=60),
        started_at=started,
    )
    reserved, created = repository.reserve_execution(execution)
    assert created is True
    return reserved


def build_case(age_seconds: int):
    repository = InMemoryRepository()
    service = PlatformService(
        repository,
        execution_lease_seconds=60,
        execution_stale_after_seconds=60,
    )
    principal = PrincipalContext(
        tenant_id="tenant-a",
        user_id="user-a",
        role="member",
    )
    thread = service.create_thread(principal, "Stale execution")
    request = ChatRequest(
        thread_id=thread.thread_id,
        content="Executar com idempotência",
        requested_agent="Orion",
        request_id="request-running",
    )
    execution = seed_running_execution(
        service=service,
        repository=repository,
        principal=principal,
        request=request,
        age_seconds=age_seconds,
    )
    return repository, service, principal, request, execution


def test_expired_running_execution_requires_governed_recovery():
    repository, service, principal, request, execution = build_case(61)

    with pytest.raises(ConflictError) as captured:
        service.complete_chat(principal, request)

    assert captured.value.code == "STALE_EXECUTION_REQUIRES_RECOVERY"
    current = repository.get_execution(
        principal.tenant_id,
        request.request_id,
    )
    assert current == execution
    assert current.status == "running"
    assert repository.list_messages(
        principal.tenant_id,
        request.thread_id,
    ) == []


def test_recent_running_execution_remains_in_progress():
    repository, service, principal, request, execution = build_case(30)

    with pytest.raises(ConflictError) as captured:
        service.complete_chat(principal, request)

    assert captured.value.code == "REQUEST_IN_PROGRESS"
    current = repository.get_execution(
        principal.tenant_id,
        request.request_id,
    )
    assert current == execution
    assert current.status == "running"
