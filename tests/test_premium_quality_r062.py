import json
from collections.abc import Iterator

from orkio_platform.application.catalog import resolve_agent
from orkio_platform.application.services import PlatformService
from orkio_platform.domain.models import ChatRequest, PrincipalContext
from orkio_platform.infrastructure.repositories import InMemoryRepository
from orkio_platform.llm.contracts import (
    LLMCompletionRequest,
    LLMResult,
    LLMStreamEvent,
)
from orkio_platform.llm.prompts import (
    contribution_prompt_for_agent,
    system_prompt_for_agent,
)
from orkio_platform.orchestration.capabilities import list_capabilities
from orkio_platform.orchestration.output_normalization import (
    contains_cross_agent_heading,
    normalize_agent_viewpoint,
)
from orkio_platform.realtime.sse import stream_chat


def _principal() -> PrincipalContext:
    return PrincipalContext(
        tenant_id="tenant-a",
        user_id="user-a",
        role="member",
    )


def _parse_events(text: str) -> list[dict[str, object]]:
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


def test_roundtable_output_normalizer_keeps_only_canonical_speaker():
    recursive = (
        "### Orion\nTechnical view\n\n"
        "### Chris\nBusiness view\n\n"
        "### Orkio\nCanonical next step"
    )

    assert normalize_agent_viewpoint(recursive, "Orkio") == (
        "Canonical next step"
    )
    assert normalize_agent_viewpoint(recursive, "Chris") == (
        "Business view"
    )
    assert contains_cross_agent_heading(recursive, "Orkio") is True


def test_plain_viewpoint_is_preserved_and_bounded():
    plain = "Evidence, risk and recommended action."
    assert normalize_agent_viewpoint(plain, "Orion") == plain

    bounded = normalize_agent_viewpoint(
        "x" * 8_100,
        "Orion",
        max_chars=100,
    )
    assert bounded.startswith("x" * 100)
    assert "limitada pelo runtime" in bounded


def test_agent_prompts_fix_persona_and_capability_truthfulness():
    chris = system_prompt_for_agent(resolve_agent("Chris"))
    laura = system_prompt_for_agent(resolve_agent("Laura"))
    orion_contribution = contribution_prompt_for_agent(
        resolve_agent("Orion")
    )

    assert "executive strategy and business specialist" in chris
    assert "communication, product-experience and adoption" in laura
    assert "do not have repository" in chris
    assert "Recommendations are not executions" in laura
    assert "Do not write headings or sections named" in orion_contribution


def test_capability_registry_separates_available_gated_and_planned():
    items = list_capabilities()
    by_id = {item.capability_id: item for item in items}

    assert by_id["platform_orchestration"].availability == "available"
    assert (
        by_id["assisted_evolution_proposal"].availability
        == "feature_gated"
    )
    assert by_id["document_analysis"].availability == "planned"
    assert by_id["architecture_indexer"].runtime == "not_connected"
    assert by_id["realtime_voice_webrtc"].limitations
    assert by_id["artifact_generation"].human_approval_required is True


class RecursiveRoundtableProvider:
    provider_name = "fake_recursive"
    model_name = "fake-model"

    def complete(self, request: LLMCompletionRequest) -> LLMResult:
        if "OWNER CONTRACT RETRY" in request.system_prompt:
            content = "DECISION: Prioritize the smallest safe next step.\nPRIORITY: Speaker integrity.\nNEXT STEP: Re-run the roundtable.\nMAIN RISK: Recursive authorship.\nVERDICT: GO CONDITIONAL."
        elif "CONTRACT RETRY" in request.system_prompt:
            content = f"Own viewpoint from {request.agent_id}"
        else:
            content = (
                f"### {request.agent_id}\n"
                f"Own viewpoint from {request.agent_id}\n\n"
                "### Orkio\nImpersonated coordinator"
            )
        return LLMResult(
            content=content,
            provider=self.provider_name,
            model=self.model_name,
            total_tokens=5,
        )

    def stream(
        self,
        request: LLMCompletionRequest,
    ) -> Iterator[LLMStreamEvent]:
        recursive = (
            "### Orion\nRepeated technical view\n\n"
            "### Chris\nRepeated business view\n\n"
            "### Laura\nRepeated experience view\n\n"
            "### Orkio\nDECISION: Prioritize the smallest safe next step.\nPRIORITY: Speaker integrity.\nNEXT STEP: Re-run the roundtable.\nMAIN RISK: Recursive authorship.\nVERDICT: GO CONDITIONAL."
        )
        yield LLMStreamEvent.text_delta(recursive)
        yield LLMStreamEvent.completed(
            LLMResult(
                content=recursive,
                provider=self.provider_name,
                model=self.model_name,
                total_tokens=12,
            )
        )


def test_roundtable_stream_hides_recursive_owner_sections():
    repository = InMemoryRepository()
    provider = RecursiveRoundtableProvider()
    service = PlatformService(
        repository,
        llm_provider=provider,
        realtime_streaming_enabled=True,
        multiagent_enabled=True,
        multiagent_max_contributors=3,
        multiagent_team_agents=("Orion", "Chris", "Laura"),
    )
    thread = service.create_thread(_principal(), "Roundtable")

    events = _parse_events(
        "".join(
            stream_chat(
                service,
                _principal(),
                ChatRequest(
                    thread_id=thread.thread_id,
                    content="Cada agente responda.",
                    requested_agent="Team",
                    interaction_mode="roundtable",
                    request_id="request-r062-roundtable",
                ),
            )
        )
    )

    chunks = [
        item["data"]["payload"]["content"]
        for item in events
        if item["event"] == "agent_chunk"
    ]
    assert chunks == ["DECISION: Prioritize the smallest safe next step.\nPRIORITY: Speaker integrity.\nNEXT STEP: Re-run the roundtable.\nMAIN RISK: Recursive authorship.\nVERDICT: GO CONDITIONAL."]
    assert [item["event"] for item in events][-2:] == [
        "agent_done",
        "done",
    ]

    message = next(
        item["data"]["payload"]["message"]
        for item in events
        if item["event"] == "agent_done"
    )
    content = message["content"]
    assert content.count("### Orion") == 1
    assert content.count("### Chris") == 1
    assert content.count("### Laura") == 1
    assert content.count("### Orkio") == 1
    assert "Repeated technical view" not in content
    assert "Impersonated coordinator" not in content
    assert "Own viewpoint from Orion" in content
    assert "Own viewpoint from Chris" in content
    assert "Own viewpoint from Laura" in content
    assert content.endswith("VERDICT: GO CONDITIONAL.")

    persisted = repository.list_messages(
        "tenant-a",
        thread.thread_id,
    )
    assert persisted[-1].content == content
    assert persisted[-1].turn_owner == "Orkio"
