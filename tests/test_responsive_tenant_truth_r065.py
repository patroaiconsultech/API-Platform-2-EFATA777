from orkio_platform.domain.models import Agent
from orkio_platform.knowledge.snapshot import (
    KNOWLEDGE_SNAPSHOT,
    KNOWLEDGE_SNAPSHOT_VERSION,
    platform_knowledge_prompt,
)
from orkio_platform.llm.prompts import system_prompt_for_agent
from orkio_platform.version import (
    RELEASE_CANDIDATE,
    RELEASE_VERSION,
)


def _agent(agent_id: str) -> Agent:
    return Agent(
        agent_id=agent_id,
        display_name=agent_id,
        description="ORKIO test specialist",
        capabilities=("advisory",),
    )


def test_r065_release_identity_is_consistent():
    assert RELEASE_VERSION == "0.7.0"
    assert (
        RELEASE_CANDIDATE
        == "ORKIO-PREMIUM-REALTIME-VOICE-CORE-R0-7-0"
    )
    assert KNOWLEDGE_SNAPSHOT_VERSION == "orkio-platform-r070-v1"
    assert (
        KNOWLEDGE_SNAPSHOT["release_id"]
        == "ORKIO-PREMIUM-REALTIME-VOICE-CORE-R0-7-0"
    )


def test_tenant_denials_are_explicit_security_invariants():
    prompt = system_prompt_for_agent(_agent("Orion")).lower()

    assert "security invariants are not defects" in prompt
    assert "tenant a being unable to read, rename or mutate tenant b" in prompt
    assert "member being denied admin access" in prompt
    assert "request without a valid tenant failing" in prompt
    assert "never recommend enabling cross-tenant access" in prompt
    assert "weakening authorization" in prompt


def test_snapshot_preserves_known_orkio_stack_and_tenant_truth():
    prompt = platform_knowledge_prompt()

    assert "React/Vite" in prompt
    assert "FastAPI" in prompt
    assert "PostgreSQL" in prompt
    assert "OpenAI Responses" in prompt
    assert "textual SSE" in prompt
    assert "expected security invariant" in prompt


def test_agent_language_and_stack_contract_are_explicit():
    prompt = system_prompt_for_agent(_agent("Laura"))

    assert "Answer entirely in the user's language" in prompt
    assert "including headings, labels and examples" in prompt
    assert "preserve the known stack" in prompt
    assert "do not substitute unrelated frameworks" in prompt
