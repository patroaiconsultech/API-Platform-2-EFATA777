import json

from orkio_platform.application.services import PlatformService
from orkio_platform.domain.models import (
    ChatRequest,
    MessageRecord,
    PrincipalContext,
)
from orkio_platform.infrastructure.repositories import InMemoryRepository
from orkio_platform.llm.contracts import (
    LLMCompletionRequest,
    LLMProviderError,
    LLMResult,
)
from orkio_platform.realtime.sse import stream_chat


class CapturingProvider:
    provider_name = "fake_real_llm"
    model_name = "fake-model"

    def __init__(self):
        self.requests: list[LLMCompletionRequest] = []

    def complete(self, request: LLMCompletionRequest) -> LLMResult:
        self.requests.append(request)
        return LLMResult(
            content="Resposta gerada pelo modelo.",
            provider=self.provider_name,
            model=self.model_name,
            response_id="resp_test",
            input_tokens=8,
            output_tokens=6,
            total_tokens=14,
        )


class FailingProvider:
    provider_name = "fake_failing_llm"
    model_name = "fake-model"

    def complete(self, request: LLMCompletionRequest) -> LLMResult:
        raise LLMProviderError(
            "LLM_PROVIDER_TIMEOUT",
            "The language model provider timed out.",
            retryable=True,
        )


def principal(tenant_id="tenant-a", user_id="user-a"):
    return PrincipalContext(
        tenant_id=tenant_id,
        user_id=user_id,
        role="member",
    )


def parse_events(text):
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


def test_real_provider_preserves_identity_persistence_and_usage():
    repository = InMemoryRepository()
    provider = CapturingProvider()
    service = PlatformService(
        repository,
        llm_provider=provider,
    )
    thread = service.create_thread(principal(), "Chat")

    response = service.complete_chat(
        principal(),
        ChatRequest(
            thread_id=thread.thread_id,
            content="Analise a arquitetura.",
            requested_agent="Orion",
            request_id="request-llm",
        ),
    )

    assert response.status == "success"
    assert response.content == "Resposta gerada pelo modelo."
    assert response.agent_id == response.turn_owner == "Orion"
    assert response.token_usage == {
        "input_tokens": 8,
        "output_tokens": 6,
        "total_tokens": 14,
    }

    messages = repository.list_messages(
        "tenant-a",
        thread.thread_id,
    )
    assert [message.role for message in messages] == [
        "user",
        "assistant",
    ]
    assert messages[-1].content == response.content
    assert messages[-1].agent_id == messages[-1].turn_owner == "Orion"

    captured = provider.requests[0]
    assert captured.tenant_id == "tenant-a"
    assert captured.agent_id == "Orion"
    assert captured.messages[-1].content == "Analise a arquitetura."
    assert "tenant-a" not in captured.system_prompt


def test_history_is_tenant_scoped_and_error_messages_are_excluded():
    repository = InMemoryRepository()
    provider = CapturingProvider()
    service = PlatformService(
        repository,
        llm_provider=provider,
        llm_history_messages=10,
    )
    thread_a = service.create_thread(principal(), "A")
    repository.create_thread(
        thread_a.model_copy(
            update={
                "tenant_id": "tenant-b",
                "created_by": "user-b",
                "title": "B",
            }
        )
    )
    repository.add_message(
        MessageRecord(
            message_id="a-user",
            thread_id=thread_a.thread_id,
            tenant_id="tenant-a",
            user_id="user-a",
            role="user",
            content="Contexto A",
            status="success",
        )
    )
    repository.add_message(
        MessageRecord(
            message_id="a-error",
            thread_id=thread_a.thread_id,
            tenant_id="tenant-a",
            user_id="user-a",
            role="assistant",
            content="Erro interno",
            status="error",
        )
    )
    repository.add_message(
        MessageRecord(
            message_id="b-user",
            thread_id=thread_a.thread_id,
            tenant_id="tenant-b",
            user_id="user-b",
            role="user",
            content="SEGREDO TENANT B",
            status="success",
        )
    )

    service.complete_chat(
        principal(),
        ChatRequest(
            thread_id=thread_a.thread_id,
            content="Nova pergunta",
            request_id="request-history",
        ),
    )

    contents = [
        message.content
        for message in provider.requests[0].messages
    ]
    assert contents == ["Contexto A", "Nova pergunta"]
    assert "SEGREDO TENANT B" not in contents
    assert "Erro interno" not in contents


def test_provider_failure_persists_error_and_sse_always_ends():
    repository = InMemoryRepository()
    service = PlatformService(
        repository,
        llm_provider=FailingProvider(),
    )
    thread = service.create_thread(principal(), "Failure")
    request = ChatRequest(
        thread_id=thread.thread_id,
        content="Teste",
        requested_agent="Orion",
        request_id="request-provider-error",
    )

    encoded = "".join(stream_chat(service, principal(), request))
    events = parse_events(encoded)

    assert [event["event"] for event in events][-2:] == [
        "error",
        "done",
    ]
    assert events[-2]["data"]["payload"]["code"] == (
        "LLM_PROVIDER_TIMEOUT"
    )
    assert events[-1]["data"]["payload"]["outcome"] == "error"

    messages = repository.list_messages(
        "tenant-a",
        thread.thread_id,
    )
    assert [message.role for message in messages] == [
        "user",
        "assistant",
    ]
    assert messages[-1].status == "error"
    assert messages[-1].error_code == "LLM_PROVIDER_TIMEOUT"


def test_history_budget_keeps_a_contiguous_recent_tail():
    repository = InMemoryRepository()
    provider = CapturingProvider()
    service = PlatformService(
        repository,
        llm_provider=provider,
        llm_history_messages=10,
        llm_max_context_chars=1_000,
    )
    thread = service.create_thread(principal(), "Budget")
    repository.add_message(
        MessageRecord(
            message_id="older-short",
            thread_id=thread.thread_id,
            tenant_id="tenant-a",
            user_id="user-a",
            role="user",
            content="Older short context",
            status="success",
        )
    )
    repository.add_message(
        MessageRecord(
            message_id="newer-large",
            thread_id=thread.thread_id,
            tenant_id="tenant-a",
            user_id="user-a",
            role="assistant",
            content="x" * 950,
            status="success",
        )
    )

    service.complete_chat(
        principal(),
        ChatRequest(
            thread_id=thread.thread_id,
            content="y" * 100,
            request_id="request-budget",
        ),
    )

    assert [
        message.content
        for message in provider.requests[0].messages
    ] == ["y" * 100]
