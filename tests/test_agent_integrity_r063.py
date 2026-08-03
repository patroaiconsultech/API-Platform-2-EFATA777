from __future__ import annotations

import json
from collections.abc import Iterator

import pytest

from orkio_platform.application.services import PlatformService
from orkio_platform.domain.models import (
    ChatRequest,
    MessageRecord,
    PrincipalContext,
)
from orkio_platform.infrastructure.repositories import InMemoryRepository
from orkio_platform.knowledge.snapshot import (
    KNOWLEDGE_SNAPSHOT,
    KNOWLEDGE_SNAPSHOT_VERSION,
)
from orkio_platform.llm.contracts import (
    LLMCompletionRequest,
    LLMProviderError,
    LLMResult,
    LLMStreamEvent,
)
from orkio_platform.orchestration.output_normalization import (
    assess_agent_output,
    assess_owner_output,
)
from orkio_platform.realtime.sse import stream_chat


def principal() -> PrincipalContext:
    return PrincipalContext(
        tenant_id="tenant-a",
        user_id="user-a",
        role="member",
    )


@pytest.mark.parametrize(
    ("content", "agent_id", "expected"),
    [
        (
            "### ORION — ARQUITETURA E ENGENHARIA\nVisão técnica.",
            "Orion",
            "Visão técnica.",
        ),
        (
            "### Chris - NEGÓCIO E ESTRATÉGIA\nDecisão comercial.",
            "Chris",
            "Decisão comercial.",
        ),
        (
            "### laura: PRODUTO E UX\nJornada prioritária.",
            "Laura",
            "Jornada prioritária.",
        ),
        (
            "Orion: Risco técnico prioritário.",
            "Orion",
            "Risco técnico prioritário.",
        ),
        (
            "### Orkio – COORDENAÇÃO\nDecisão final.",
            "Orkio",
            "Decisão final.",
        ),
    ],
)
def test_speaker_contract_accepts_heading_variants(
    content: str,
    agent_id: str,
    expected: str,
):
    assessment = assess_agent_output(content, agent_id)
    assert assessment.status == "success"
    assert assessment.content == expected
    assert assessment.contract_version == "speaker_contract_v4"


def test_cross_agent_heading_is_rejected_not_silently_extracted():
    assessment = assess_agent_output(
        (
            "### ORION — ARQUITETURA\nVisão técnica.\n\n"
            "### CHRIS — NEGÓCIO\nVisão comercial."
        ),
        "Orion",
    )

    assert assessment.status == "contract_violation"
    assert assessment.reason == "cross_agent_heading"
    assert assessment.content == ""
    assert assessment.cross_agent_headings == ("CHRIS",)


def test_repeated_canonical_heading_is_contract_violation():
    assessment = assess_agent_output(
        "### Orion\nPrimeiro.\n\n### ORION — TÉCNICO\nSegundo.",
        "Orion",
    )

    assert assessment.status == "contract_violation"
    assert assessment.reason == "repeated_canonical_speaker_heading"


@pytest.mark.parametrize(
    "content",
    [
        "I'm sorry, but I can't assist with that.",
        "I am unable to help with this request.",
        "Desculpe, mas não posso ajudar com isso.",
        "Não consigo auxiliar nessa solicitação.",
    ],
)
def test_generic_refusal_is_not_success(content: str):
    assessment = assess_agent_output(content, "Laura")
    assert assessment.status == "refused"
    assert assessment.reason == "generic_refusal"
    assert assessment.generic_refusal is True


def test_owner_requires_decision_priority_and_next_step():
    missing = assess_owner_output(
        "Priorize o menor passo seguro.",
        "Orkio",
    )
    assert missing.status == "contract_violation"
    assert missing.reason.startswith("decision_v1_fields_missing:")

    valid = assess_owner_output(
        (
            "DECISÃO: Prosseguir condicionalmente.\n"
            "PRIORIDADE: Integridade de autoria.\n"
            "PRÓXIMO PASSO: Reexecutar a War Room.\n"
            "RISCO PRINCIPAL: Regressão.\n"
            "VEREDITO: GO CONDICIONAL."
        ),
        "Orkio",
    )
    assert valid.status == "success"
    assert valid.contract_version == "owner_decision_v4"


class ScriptedProvider:
    provider_name = "scripted"
    model_name = "scripted-model"

    def __init__(self, scripts: dict[str, list[object]]):
        self.scripts = {
            agent_id: list(items)
            for agent_id, items in scripts.items()
        }
        self.requests: list[LLMCompletionRequest] = []

    def complete(self, request: LLMCompletionRequest) -> LLMResult:
        self.requests.append(request)
        queue = self.scripts.setdefault(request.agent_id, [])
        if not queue:
            raise AssertionError(
                f"No scripted response for {request.agent_id}"
            )
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return LLMResult(
            content=str(item),
            provider=self.provider_name,
            model=self.model_name,
            input_tokens=10,
            output_tokens=5,
            total_tokens=15,
        )

    def stream(
        self,
        request: LLMCompletionRequest,
    ) -> Iterator[LLMStreamEvent]:
        result = self.complete(request)
        yield LLMStreamEvent.text_delta(result.content)
        yield LLMStreamEvent.completed(result)


def make_roundtable_service(
    provider: ScriptedProvider,
) -> tuple[PlatformService, InMemoryRepository, str]:
    repository = InMemoryRepository()
    service = PlatformService(
        repository,
        llm_provider=provider,
        realtime_streaming_enabled=True,
        multiagent_enabled=True,
        multiagent_max_contributors=3,
        multiagent_team_agents=("Orion", "Chris", "Laura"),
    )
    thread = service.create_thread(principal(), "R0.6.3")
    return service, repository, thread.thread_id


def prepare_context(
    service: PlatformService,
    thread_id: str,
) -> tuple[object, ChatRequest]:
    request = ChatRequest(
        thread_id=thread_id,
        content="Cada agente responda no próprio papel.",
        requested_agent="Team",
        interaction_mode="roundtable",
        request_id="request-r063-integrity",
    )
    return service.prepare_turn(principal(), request), request


def test_refusal_retries_once_and_recovers():
    provider = ScriptedProvider(
        {
            "Orion": [
                "I'm sorry, but I can't assist with that.",
                "DIAGNOSIS: Risco técnico.\nVERDICT: GO CONDITIONAL.",
            ]
        }
    )
    service, _repository, thread_id = make_roundtable_service(provider)
    context, request = prepare_context(service, thread_id)

    contribution = service._complete_contribution(
        context,
        request,
        "Orion",
    )

    assert contribution.status == "success"
    assert contribution.retry_count == 1
    assert "Risco técnico" in contribution.content
    assert len(provider.requests) == 2
    assert provider.requests[1].messages == (
        provider.requests[1].messages[-1],
    )


def test_persistent_refusal_remains_refused_after_one_retry():
    provider = ScriptedProvider(
        {
            "Laura": [
                "I'm sorry, but I can't assist with that.",
                "Desculpe, mas não posso ajudar com isso.",
            ]
        }
    )
    service, _repository, thread_id = make_roundtable_service(provider)
    context, request = prepare_context(service, thread_id)

    contribution = service._complete_contribution(
        context,
        request,
        "Laura",
    )

    assert contribution.status == "refused"
    assert contribution.status_reason == "generic_refusal"
    assert contribution.retry_count == 1
    assert len(provider.requests) == 2


def test_persistent_cross_agent_output_remains_contract_violation():
    contaminated = (
        "### ORION — ARQUITETURA\nVisão técnica.\n\n"
        "### CHRIS — NEGÓCIO\nConteúdo indevido."
    )
    provider = ScriptedProvider({"Orion": [contaminated, contaminated]})
    service, _repository, thread_id = make_roundtable_service(provider)
    context, request = prepare_context(service, thread_id)

    contribution = service._complete_contribution(
        context,
        request,
        "Orion",
    )

    assert contribution.status == "contract_violation"
    assert contribution.status_reason == "cross_agent_heading"
    assert contribution.content == ""
    assert contribution.retry_count == 1


def test_provider_error_is_failed_without_contract_retry():
    provider = ScriptedProvider(
        {
            "Chris": [
                LLMProviderError(
                    "LLM_PROVIDER_TIMEOUT",
                    "Provider timed out.",
                    retryable=True,
                )
            ]
        }
    )
    service, _repository, thread_id = make_roundtable_service(provider)
    context, request = prepare_context(service, thread_id)

    contribution = service._complete_contribution(
        context,
        request,
        "Chris",
    )

    assert contribution.status == "failed"
    assert contribution.status_reason == "LLM_PROVIDER_TIMEOUT"
    assert contribution.retry_count == 0
    assert len(provider.requests) == 1


def valid_owner_decision() -> str:
    return (
        "DECISION: Proceed conditionally.\n"
        "PRIORITY: Speaker integrity.\n"
        "NEXT STEP: Validate the wire.\n"
        "MAIN RISK: Regression.\n"
        "VERDICT: GO CONDITIONAL."
    )


def test_owner_recursion_gets_one_retry_and_clean_decision():
    provider = ScriptedProvider(
        {
            "Orion": ["DIAGNOSIS: Technical.\nVERDICT: Conditional."],
            "Chris": ["DIAGNOSIS: Commercial.\nVERDICT: Conditional."],
            "Laura": ["DIAGNOSIS: Experience.\nVERDICT: Conditional."],
            "Orkio": [
                (
                    "### ORION — TECH\nTechnical.\n\n"
                    "### ORKIO — OWNER\nDecision."
                ),
                valid_owner_decision(),
            ],
        }
    )
    service, _repository, thread_id = make_roundtable_service(provider)

    response = service.complete_chat(
        principal(),
        ChatRequest(
            thread_id=thread_id,
            content="Execute a War Room.",
            requested_agent="Team",
            interaction_mode="roundtable",
            request_id="request-owner-retry",
        ),
    )

    assert response.status == "success"
    assert response.owner_contract["status"] == "success"
    assert response.owner_contract["retry_count"] == 1
    assert response.content.count("### Orion") == 1
    assert response.content.count("### Chris") == 1
    assert response.content.count("### Laura") == 1
    assert response.content.count("### Orkio") == 1
    assert "### ORION — TECH" not in response.content


def test_owner_persistent_violation_preserves_contributors_as_partial():
    contaminated = (
        "### ORION — TECH\nTechnical.\n\n"
        "### ORKIO — OWNER\nDecision."
    )
    provider = ScriptedProvider(
        {
            "Orion": ["DIAGNOSIS: Technical."],
            "Chris": ["DIAGNOSIS: Commercial."],
            "Laura": ["DIAGNOSIS: Experience."],
            "Orkio": [contaminated, contaminated],
        }
    )
    service, _repository, thread_id = make_roundtable_service(provider)

    response = service.complete_chat(
        principal(),
        ChatRequest(
            thread_id=thread_id,
            content="Execute a War Room.",
            requested_agent="Team",
            interaction_mode="roundtable",
            request_id="request-owner-fail",
        ),
    )

    assert response.status == "partial"
    assert response.error["code"] == "OWNER_CONTRACT_PARTIAL"
    assert response.owner_contract["status"] == "partial"
    assert response.owner_contract["retry_count"] == 1
    assert response.owner_contract["contributors_preserved"] is True
    assert "Technical." in response.content
    assert "Commercial." in response.content
    assert "Experience." in response.content


def test_multiagent_request_applies_history_context_and_output_budgets():
    provider = ScriptedProvider({"Orion": ["Technical view."]})
    service, repository, thread_id = make_roundtable_service(provider)

    for index in range(7):
        repository.add_message(
            MessageRecord(
                message_id=f"history-{index}",
                thread_id=thread_id,
                tenant_id="tenant-a",
                user_id="user-a",
                role="user" if index % 2 == 0 else "assistant",
                content=("x" * 6_000) + str(index),
                status="success",
            )
        )

    context, request = prepare_context(service, thread_id)
    llm_request = service._contribution_request(
        context,
        request,
        "Orion",
    )

    assert llm_request.max_output_tokens == 900
    assert len(llm_request.messages) <= 5
    assert sum(len(item.content) for item in llm_request.messages) <= 20_000


def test_budget_metadata_records_observed_overage_without_false_enforcement():
    service = PlatformService(
        InMemoryRepository(),
        multiagent_turn_max_total_tokens=7_000,
    )

    within = service._budget_metadata(
        latency_ms=10_000,
        token_usage={"total_tokens": 6_999},
    )
    exceeded = service._budget_metadata(
        latency_ms=30_000,
        token_usage={"total_tokens": 7_001},
    )

    assert within["turn_token_budget_exceeded"] is False
    assert within["turn_latency_exceeded"] is False
    assert exceeded["turn_token_budget_exceeded"] is True
    assert exceeded["turn_latency_exceeded"] is True


def _parse_events(encoded: str) -> list[dict[str, object]]:
    events = []
    current = {}
    for line in encoded.splitlines():
        if line.startswith("id: "):
            current["id"] = line[4:]
        elif line.startswith("event: "):
            current["event"] = line[7:]
        elif line.startswith("data: "):
            current["data"] = json.loads(line[6:])
        elif line == "" and current:
            events.append(current)
            current = {}
    return events


def test_sse_done_payload_matches_wire_sequence():
    provider = ScriptedProvider(
        {
            "Orkio": ["Single owner response."],
        }
    )
    repository = InMemoryRepository()
    service = PlatformService(
        repository,
        llm_provider=provider,
        realtime_streaming_enabled=False,
    )
    thread = service.create_thread(principal(), "Wire")

    events = _parse_events(
        "".join(
            stream_chat(
                service,
                principal(),
                ChatRequest(
                    thread_id=thread.thread_id,
                    content="Teste wire.",
                    requested_agent="Orkio",
                    interaction_mode="single",
                    request_id="request-wire-r063",
                ),
            )
        )
    )

    done = events[-1]
    assert done["event"] == "done"
    assert done["data"]["payload"]["transport"] == "sse"
    assert done["data"]["payload"]["terminal_source"] == "wire"
    assert done["data"]["payload"]["done_observed"] is True
    assert done["data"]["payload"]["event_count"] == len(events)
    assert done["data"]["payload"]["last_event_id"] == done["id"]


def test_knowledge_snapshot_is_versioned_read_only_and_honest():
    assert KNOWLEDGE_SNAPSHOT_VERSION == "orkio-platform-r064-v1"
    assert KNOWLEDGE_SNAPSHOT["source_commit"] == "NOT_PROVEN"
    assert "persistent execution graph" in (
        KNOWLEDGE_SNAPSHOT["planned_not_connected"]
    )
    assert any(
        "not live repository" in item.lower()
        for item in KNOWLEDGE_SNAPSHOT["limitations"]
    )


def test_openai_request_respects_per_call_output_budget():
    from orkio_platform.llm.openai_responses import (
        OpenAIResponsesProvider,
    )

    provider = OpenAIResponsesProvider(
        api_key="test-key",
        model="test-model",
        base_url="https://api.openai.com/v1",
        timeout_seconds=30,
        max_retries=0,
        max_output_tokens=4_096,
        store_responses=False,
        client=object(),
    )
    request = LLMCompletionRequest(
        tenant_id="tenant-a",
        user_id="user-a",
        thread_id="thread-a",
        agent_id="Orion",
        display_name="Orion",
        system_prompt="Test.",
        messages=(
            # The provider only requires the final message to be user.
            __import__(
                "orkio_platform.llm.contracts",
                fromlist=["LLMMessage"],
            ).LLMMessage(role="user", content="Test."),
        ),
        max_output_tokens=900,
    )

    arguments = provider._request_arguments(request)
    assert arguments["max_output_tokens"] == 900
