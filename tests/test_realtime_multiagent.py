import json
from collections.abc import Iterator

from orkio_platform.application.services import PlatformService
from orkio_platform.domain.models import ChatRequest, PrincipalContext
from orkio_platform.infrastructure.repositories import InMemoryRepository
from orkio_platform.llm.contracts import (
    LLMCompletionRequest,
    LLMResult,
    LLMStreamEvent,
)
from orkio_platform.realtime.sse import stream_chat


class MultiAgentProvider:
    provider_name = "fake_multiagent"
    model_name = "fake-model"

    def __init__(self):
        self.complete_requests: list[LLMCompletionRequest] = []
        self.stream_requests: list[LLMCompletionRequest] = []

    def complete(self, request: LLMCompletionRequest) -> LLMResult:
        self.complete_requests.append(request)
        return LLMResult(
            content=f"Contribution from {request.agent_id}",
            provider=self.provider_name,
            model=self.model_name,
            input_tokens=3,
            output_tokens=2,
            total_tokens=5,
        )

    def stream(
        self,
        request: LLMCompletionRequest,
    ) -> Iterator[LLMStreamEvent]:
        self.stream_requests.append(request)
        yield LLMStreamEvent.text_delta("Final ")
        yield LLMStreamEvent.text_delta("answer")
        yield LLMStreamEvent.completed(
            LLMResult(
                content="Final answer",
                provider=self.provider_name,
                model=self.model_name,
                response_id="resp-owner",
                input_tokens=10,
                output_tokens=4,
                total_tokens=14,
            )
        )


def principal() -> PrincipalContext:
    return PrincipalContext(
        tenant_id="tenant-a",
        user_id="user-a",
        role="member",
    )


def parse_events(text: str) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    current: dict[str, object] = {}
    for line in text.splitlines():
        if line.startswith("event: "):
            current["event"] = line[7:]
        elif line.startswith("data: "):
            current["data"] = json.loads(line[6:])
        elif line == "" and current:
            events.append(current)
            current = {}
    return events


def test_team_executes_real_contributors_and_streams_owner():
    repository = InMemoryRepository()
    provider = MultiAgentProvider()
    service = PlatformService(
        repository,
        llm_provider=provider,
        realtime_streaming_enabled=True,
        multiagent_enabled=True,
        multiagent_max_contributors=3,
        multiagent_team_agents=("Orion", "Chris", "Laura"),
    )
    thread = service.create_thread(principal(), "Team")

    encoded = "".join(
        stream_chat(
            service,
            principal(),
            ChatRequest(
                thread_id=thread.thread_id,
                content="Crie uma análise técnica, estratégica e de UX.",
                requested_agent="Team",
                request_id="request-team",
            ),
        )
    )
    events = parse_events(encoded)
    event_types = [item["event"] for item in events]

    assert event_types[-2:] == ["agent_done", "done"]
    chunks = [
        item["data"]["payload"]["content"]
        for item in events
        if item["event"] == "agent_chunk"
    ]
    assert chunks == ["Final ", "answer"]

    node_events = [
        item["data"]["payload"]
        for item in events
        if item["event"] == "execution"
        and item["data"]["payload"].get("phase")
        in {"node_started", "node_completed"}
    ]
    assert {
        item["agent_id"]
        for item in node_events
        if item["phase"] == "node_completed"
    } == {"Orion", "Chris", "Laura"}

    assert [item.agent_id for item in provider.complete_requests] == [
        "Orion",
        "Chris",
        "Laura",
    ]
    assert [item.agent_id for item in provider.stream_requests] == [
        "Orkio"
    ]
    assert "Contribution from Orion" in (
        provider.stream_requests[0].system_prompt
    )
    assert "Contribution from Chris" in (
        provider.stream_requests[0].system_prompt
    )
    assert "Contribution from Laura" in (
        provider.stream_requests[0].system_prompt
    )

    message = next(
        item["data"]["payload"]["message"]
        for item in events
        if item["event"] == "agent_done"
    )
    assert message["agent_id"] == "Orkio"
    assert message["turn_owner"] == "Orkio"
    assert message["final_speaker"] == "Orkio"
    assert len(message["execution_trace"]) == 4
    assert message["token_usage"] == {
        "input_tokens": 19,
        "output_tokens": 10,
        "total_tokens": 29,
    }

    persisted = repository.list_messages(
        "tenant-a",
        thread.thread_id,
    )
    assert [item.role for item in persisted] == ["user", "assistant"]
    assert persisted[-1].content == "Final answer"
    assert persisted[-1].agent_id == persisted[-1].turn_owner == "Orkio"


def test_explicit_agent_remains_owner_with_peer_contribution():
    repository = InMemoryRepository()
    provider = MultiAgentProvider()
    service = PlatformService(
        repository,
        llm_provider=provider,
        realtime_streaming_enabled=True,
        multiagent_enabled=True,
        multiagent_max_contributors=2,
    )
    thread = service.create_thread(principal(), "Owner")

    events = parse_events(
        "".join(
            stream_chat(
                service,
                principal(),
                ChatRequest(
                    thread_id=thread.thread_id,
                    content=(
                        "Orion, avalie a arquitetura e o impacto "
                        "estratégico no negócio."
                    ),
                    requested_agent="Orion",
                    request_id="request-owner",
                ),
            )
        )
    )

    assert [item.agent_id for item in provider.complete_requests] == [
        "Chris"
    ]
    assert provider.stream_requests[0].agent_id == "Orion"
    message = next(
        item["data"]["payload"]["message"]
        for item in events
        if item["event"] == "agent_done"
    )
    assert message["agent_id"] == "Orion"
    assert message["turn_owner"] == "Orion"
    assert message["final_speaker"] == "Orion"


class CancellableProvider:
    provider_name = "fake_cancellable"
    model_name = "fake-model"

    def __init__(self):
        self.closed = False
        self.stream_calls = 0

    def complete(self, request: LLMCompletionRequest) -> LLMResult:
        return LLMResult(
            content="fallback",
            provider=self.provider_name,
            model=self.model_name,
        )

    def stream(
        self,
        request: LLMCompletionRequest,
    ) -> Iterator[LLMStreamEvent]:
        self.stream_calls += 1
        try:
            yield LLMStreamEvent.text_delta("first ")
            yield LLMStreamEvent.text_delta("second")
            yield LLMStreamEvent.completed(
                LLMResult(
                    content="first second",
                    provider=self.provider_name,
                    model=self.model_name,
                )
            )
        finally:
            self.closed = True


def test_realtime_cancel_closes_upstream_and_ends_terminally():
    repository = InMemoryRepository()
    provider = CancellableProvider()
    service = PlatformService(
        repository,
        llm_provider=provider,
        realtime_streaming_enabled=True,
    )
    thread = service.create_thread(principal(), "Cancel")
    request = ChatRequest(
        thread_id=thread.thread_id,
        content="Generate",
        requested_agent="Orion",
        request_id="request-cancel",
    )

    generator = stream_chat(service, principal(), request)
    encoded: list[str] = []
    while True:
        item = next(generator)
        encoded.append(item)
        if "event: agent_chunk" in item:
            break

    service.cancel_execution(
        principal(),
        "request-cancel",
        reason="User interrupted the response.",
    )
    encoded.extend(list(generator))
    events = parse_events("".join(encoded))

    assert [item["event"] for item in events][-2:] == [
        "cancelled",
        "done",
    ]
    assert events[-1]["data"]["payload"]["outcome"] == "cancelled"
    assert provider.closed is True
    assert provider.stream_calls == 1


def test_realtime_replay_does_not_call_provider_or_duplicate_messages():
    repository = InMemoryRepository()
    provider = MultiAgentProvider()
    service = PlatformService(
        repository,
        llm_provider=provider,
        realtime_streaming_enabled=True,
    )
    thread = service.create_thread(principal(), "Replay")
    request = ChatRequest(
        thread_id=thread.thread_id,
        content="Replay safely",
        requested_agent="Orion",
        request_id="request-replay",
    )

    first = parse_events(
        "".join(stream_chat(service, principal(), request))
    )
    second = parse_events(
        "".join(stream_chat(service, principal(), request))
    )

    assert [item["event"] for item in first][-2:] == [
        "agent_done",
        "done",
    ]
    assert [item["event"] for item in second][-2:] == [
        "agent_done",
        "done",
    ]
    assert provider.stream_requests and len(provider.stream_requests) == 1
    persisted = repository.list_messages(
        "tenant-a",
        thread.thread_id,
    )
    assert [item.role for item in persisted] == ["user", "assistant"]
    second_message = next(
        item["data"]["payload"]["message"]
        for item in second
        if item["event"] == "agent_done"
    )
    assert second_message["content"] == "Final answer"
