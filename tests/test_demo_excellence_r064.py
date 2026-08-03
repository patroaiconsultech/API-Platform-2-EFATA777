from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterator

from orkio_platform.application.services import PlatformService
from orkio_platform.domain.models import (
    ChatRequest,
    PrincipalContext,
)
from orkio_platform.infrastructure.repositories import InMemoryRepository
from orkio_platform.llm.contracts import (
    LLMCompletionRequest,
    LLMResult,
    LLMStreamEvent,
)
from orkio_platform.orchestration.task_decomposition import (
    classify_owner_contract,
    decompose_user_request,
)
from orkio_platform.realtime.sse import stream_chat


def principal(
    tenant_id: str = "tenant-a",
    user_id: str = "user-a",
) -> PrincipalContext:
    return PrincipalContext(
        tenant_id=tenant_id,
        user_id=user_id,
        role="member",
    )


class ScriptedProvider:
    provider_name = "scripted-r064"
    model_name = "scripted-r064-model"

    def __init__(self, scripts: dict[str, list[str]]):
        self.scripts = {
            agent_id: list(values)
            for agent_id, values in scripts.items()
        }
        self.requests: list[LLMCompletionRequest] = []

    def complete(self, request: LLMCompletionRequest) -> LLMResult:
        self.requests.append(request)
        values = self.scripts.setdefault(request.agent_id, [])
        if not values:
            raise AssertionError(
                f"No scripted response for {request.agent_id}"
            )
        content = values.pop(0)
        return LLMResult(
            content=content,
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


def make_service(
    provider: ScriptedProvider,
    *,
    realtime: bool = True,
) -> tuple[PlatformService, InMemoryRepository, str]:
    repository = InMemoryRepository()
    service = PlatformService(
        repository,
        llm_provider=provider,
        realtime_streaming_enabled=realtime,
        multiagent_enabled=True,
        multiagent_max_contributors=3,
        multiagent_team_agents=("Orion", "Chris", "Laura"),
    )
    thread = service.create_thread(principal(), "R0.6.4")
    return service, repository, thread.thread_id


def roundtable_request(
    thread_id: str,
    content: str,
    request_id: str = "request-r064",
) -> ChatRequest:
    return ChatRequest(
        thread_id=thread_id,
        content=content,
        requested_agent="Team",
        interaction_mode="roundtable",
        request_id=request_id,
    )


def test_explicit_tasks_are_sliced_per_agent():
    content = """
Este é um pedido benigno.

Orion:
indique dois riscos técnicos.

Chris:
proponha uma hipótese de monetização.

Laura:
desenhe uma jornada de onboarding em cinco etapas.

Orkio:
entregue somente decisão, prioridade e próximo passo.
"""
    decomposition = decompose_user_request(content)

    orion = decomposition.for_agent("Orion")
    chris = decomposition.for_agent("Chris")
    laura = decomposition.for_agent("Laura")
    orkio = decomposition.for_agent("Orkio")

    assert orion.explicit_assignment is True
    assert "riscos técnicos" in orion.assigned_task
    assert "monetização" not in orion.user_message
    assert "onboarding" not in orion.user_message

    assert chris.explicit_assignment is True
    assert "monetização" in chris.assigned_task
    assert "riscos técnicos" not in chris.user_message
    assert "onboarding" not in chris.user_message

    assert laura.explicit_assignment is True
    assert "onboarding" in laura.assigned_task
    assert "monetização" not in laura.user_message
    assert "riscos técnicos" not in laura.user_message

    assert orkio.explicit_assignment is True
    assert "decisão" in orkio.assigned_task
    assert "riscos técnicos" not in orkio.user_message
    assert "monetização" not in orkio.user_message
    assert decomposition.version == "task_slice_v1"


def test_short_ack_slices_override_general_role_analysis():
    decomposition = decompose_user_request(
        "Cada agente responda somente com seu nome e a palavra OK."
    )

    for agent_id in ("Orion", "Chris", "Laura"):
        task = decomposition.for_agent(agent_id)
        assert task.assigned_task.startswith("Return only OK")
        assert "technical" not in task.assigned_task.casefold()
        assert "business" not in task.assigned_task.casefold()
        assert "product" not in task.assigned_task.casefold()


def test_owner_contract_classifier_is_intent_adaptive():
    assert classify_owner_contract(
        "Classifique como comprovado, planejado ou não conectado."
    ) == "classification_v1"
    assert classify_owner_contract(
        "Cada agente responda somente com seu nome e a palavra OK."
    ) == "short_ack_v1"
    assert classify_owner_contract(
        "Faça uma auditoria dos principais riscos."
    ) == "risk_assessment_v1"
    assert classify_owner_contract(
        "Qual nome devemos escolher e qual é a prioridade?"
    ) == "decision_v1"
    assert classify_owner_contract(
        "Resuma os fatos sobre a plataforma."
    ) == "factual_summary_v1"


def test_provider_receives_only_each_agent_task_and_owner_task():
    prompt = """
Este é um pedido benigno.

Orion:
indique dois riscos técnicos.

Chris:
proponha uma hipótese de monetização.

Laura:
desenhe uma jornada de onboarding em cinco etapas.

Orkio:
entregue somente decisão, prioridade e próximo passo.
"""
    provider = ScriptedProvider(
        {
            "Orion": ["Riscos técnicos: autenticação e isolamento."],
            "Chris": ["Monetização: assinatura mensal validada por piloto."],
            "Laura": ["Onboarding: convite, perfil, objetivo, tour e ativação."],
            "Orkio": [
                (
                    "DECISÃO: Validar um piloto controlado.\n"
                    "PRIORIDADE: Onboarding seguro.\n"
                    "PRÓXIMO PASSO: Recrutar cinco usuários-piloto."
                )
            ],
        }
    )
    service, _repository, thread_id = make_service(provider)

    response = service.complete_chat(
        principal(),
        roundtable_request(thread_id, prompt),
    )

    assert response.status == "success"
    by_agent = {
        request.agent_id: request.messages[-1].content
        for request in provider.requests
    }
    assert "riscos técnicos" in by_agent["Orion"]
    assert "monetização" not in by_agent["Orion"]
    assert "onboarding" not in by_agent["Orion"]

    assert "monetização" in by_agent["Chris"]
    assert "riscos técnicos" not in by_agent["Chris"]
    assert "onboarding" not in by_agent["Chris"]

    assert "onboarding" in by_agent["Laura"]
    assert "monetização" not in by_agent["Laura"]
    assert "riscos técnicos" not in by_agent["Laura"]

    assert "decisão" in by_agent["Orkio"]
    assert "riscos técnicos" not in by_agent["Orkio"]
    assert "monetização" not in by_agent["Orkio"]
    assert response.owner_contract["owner_contract"] == "decision_v1"


def test_short_ack_owner_does_not_repeat_specialists():
    prompt = """
Cada agente responda somente com seu nome e a palavra OK.

Orkio finalize exatamente com:
Teste concluído.
"""
    provider = ScriptedProvider(
        {
            "Orion": ["OK"],
            "Chris": ["OK"],
            "Laura": ["OK"],
            "Orkio": ["Teste concluído."],
        }
    )
    service, _repository, thread_id = make_service(provider)

    response = service.complete_chat(
        principal(),
        roundtable_request(
            thread_id,
            prompt,
            request_id="request-short-ack",
        ),
    )

    assert response.status == "success"
    assert response.owner_contract["owner_contract"] == "short_ack_v1"
    assert response.content.count("### Orion") == 1
    assert response.content.count("### Chris") == 1
    assert response.content.count("### Laura") == 1
    assert response.content.count("### Orkio") == 1
    owner_block = response.content.split("### Orkio", 1)[1]
    assert "Orion OK" not in owner_block
    assert "Chris OK" not in owner_block
    assert "Laura OK" not in owner_block
    assert "Teste concluído." in owner_block


def test_only_owner_is_retried_after_owner_violation():
    prompt = """
Cada agente responda somente com seu nome e a palavra OK.

Orkio finalize exatamente com:
Teste concluído.
"""
    provider = ScriptedProvider(
        {
            "Orion": ["OK"],
            "Chris": ["OK"],
            "Laura": ["OK"],
            "Orkio": [
                "Orion OK\nChris OK\nLaura OK\nTeste concluído.",
                "Teste concluído.",
            ],
        }
    )
    service, _repository, thread_id = make_service(provider)

    response = service.complete_chat(
        principal(),
        roundtable_request(
            thread_id,
            prompt,
            request_id="request-owner-only-retry",
        ),
    )

    assert response.status == "success"
    calls = Counter(request.agent_id for request in provider.requests)
    assert calls == Counter(
        {"Orion": 1, "Chris": 1, "Laura": 1, "Orkio": 2}
    )
    assert response.owner_contract["retry_count"] == 1
    assert response.owner_contract["retry_scope"] == "owner_only"


def test_persistent_owner_violation_is_partial_and_persisted():
    prompt = """
Cada agente responda somente com seu nome e a palavra OK.

Orkio finalize exatamente com:
Teste concluído.
"""
    contaminated = "Orion OK\nChris OK\nLaura OK\nTeste concluído."
    provider = ScriptedProvider(
        {
            "Orion": ["OK"],
            "Chris": ["OK"],
            "Laura": ["OK"],
            "Orkio": [contaminated, contaminated],
        }
    )
    service, repository, thread_id = make_service(provider)
    request = roundtable_request(
        thread_id,
        prompt,
        request_id="request-partial-owner",
    )

    first = service.complete_chat(principal(), request)
    replay = service.complete_chat(principal(), request)
    messages = repository.list_messages("tenant-a", thread_id)

    assert first.status == "partial"
    assert first.error["code"] == "OWNER_CONTRACT_PARTIAL"
    assert first.owner_contract["contributors_preserved"] is True
    assert replay.status == "partial"
    assert [message.role for message in messages] == [
        "user",
        "assistant",
    ]
    assert messages[-1].status == "partial"
    assert "contribuições validadas foram preservadas" in (
        messages[-1].content
    )
    assert "### Orion" in messages[-1].content
    assert "### Chris" in messages[-1].content
    assert "### Laura" in messages[-1].content


def _parse_events(encoded: str) -> list[dict[str, object]]:
    events = []
    current: dict[str, object] = {}
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


def test_partial_stream_emits_partial_then_done_without_error():
    prompt = """
Cada agente responda somente com seu nome e a palavra OK.

Orkio finalize exatamente com:
Teste concluído.
"""
    contaminated = "Orion OK\nChris OK\nLaura OK\nTeste concluído."
    provider = ScriptedProvider(
        {
            "Orion": ["OK"],
            "Chris": ["OK"],
            "Laura": ["OK"],
            "Orkio": [contaminated, contaminated],
        }
    )
    service, _repository, thread_id = make_service(provider)

    events = _parse_events(
        "".join(
            stream_chat(
                service,
                principal(),
                roundtable_request(
                    thread_id,
                    prompt,
                    request_id="request-partial-sse",
                ),
            )
        )
    )
    types = [item["event"] for item in events]

    assert "partial" in types
    assert "error" not in types
    assert types[-1] == "done"
    done = events[-1]["data"]["payload"]
    assert done["outcome"] == "partial"
    assert done["done_observed"] is True
    assert done["event_count"] == len(events)


def test_thread_rename_is_persisted_and_tenant_scoped(
    client,
    member_headers,
):
    created = client.post(
        "/api/threads",
        headers=member_headers,
        json={"title": "Antes"},
    ).json()

    renamed = client.patch(
        f"/api/threads/{created['thread_id']}",
        headers=member_headers,
        json={"title": "  Auditoria   UX   R0.6.4  "},
    )

    assert renamed.status_code == 200
    assert renamed.json()["title"] == "Auditoria UX R0.6.4"
    listed = client.get(
        "/api/threads",
        headers=member_headers,
    ).json()
    assert listed[0]["title"] == "Auditoria UX R0.6.4"

    other_tenant = {
        "X-Tenant-ID": "tenant-b",
        "X-User-ID": "user-b",
        "X-Role": "member",
    }
    cross = client.patch(
        f"/api/threads/{created['thread_id']}",
        headers=other_tenant,
        json={"title": "Não autorizado"},
    )
    assert cross.status_code == 404
    assert cross.json()["error"]["code"] == "THREAD_NOT_FOUND"


def test_thread_rename_rejects_whitespace_title(
    client,
    member_headers,
):
    created = client.post(
        "/api/threads",
        headers=member_headers,
        json={"title": "Antes"},
    ).json()

    response = client.patch(
        f"/api/threads/{created['thread_id']}",
        headers=member_headers,
        json={"title": "   "},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "THREAD_TITLE_REQUIRED"
