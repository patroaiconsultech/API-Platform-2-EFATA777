from __future__ import annotations

from dataclasses import replace

from orkio_platform.config import get_settings
from orkio_platform.orchestration.contracts import CapabilityDefinition


CAPABILITIES: tuple[CapabilityDefinition, ...] = (
    CapabilityDefinition(
        capability_id="platform_orchestration",
        agent_id="Orkio",
        description="Coordinate specialists and synthesize a canonical final answer.",
        inputs=("user_request", "peer_contributions"),
        outputs=("canonical_response",),
        permissions=("read_context", "invoke_specialists"),
        risk_level="medium",
        governance_required=False,
        runtime="llm",
        status="active",
        version="1.1.0",
        availability="available",
        evidence=(
            "team_synthesis route",
            "team_roundtable route",
            "typed contribution events",
        ),
        limitations=(
            "trace_lite only",
            "no persistent execution graph",
        ),
    ),
    CapabilityDefinition(
        capability_id="technical_architecture",
        agent_id="Orion",
        description="Advisory architecture, engineering, security and production-audit analysis.",
        inputs=("technical_request", "provided_evidence"),
        outputs=("technical_analysis", "risk_assessment"),
        permissions=("read_context",),
        risk_level="medium",
        governance_required=False,
        runtime="llm",
        status="active",
        version="1.1.0",
        availability="available",
        evidence=("agent-specific prompt contract",),
        limitations=(
            "no repository tool connected",
            "no database or log-query tool connected",
            "cannot execute patches or deploys",
        ),
    ),
    CapabilityDefinition(
        capability_id="business_strategy",
        agent_id="Chris",
        description="Advisory market, positioning, economics and executive strategy analysis.",
        inputs=("business_request", "provided_context"),
        outputs=("strategy_analysis",),
        permissions=("read_context",),
        risk_level="medium",
        governance_required=False,
        runtime="llm",
        status="active",
        version="1.1.0",
        availability="available",
        evidence=("agent-specific prompt contract",),
        limitations=(
            "no live market intelligence connector",
            "assumptions require user-provided evidence or research",
        ),
    ),
    CapabilityDefinition(
        capability_id="communication_experience",
        agent_id="Laura",
        description="Advisory UX, communication, adoption and customer-journey analysis.",
        inputs=("experience_request", "provided_context"),
        outputs=("experience_analysis",),
        permissions=("read_context",),
        risk_level="low",
        governance_required=False,
        runtime="llm",
        status="active",
        version="1.1.0",
        availability="available",
        evidence=("agent-specific prompt contract",),
        limitations=(
            "no analytics or session-replay connector",
            "cannot modify the frontend directly",
        ),
    ),
    CapabilityDefinition(
        capability_id="assisted_evolution_proposal",
        agent_id="Orion",
        description="Generate governed technical evolution proposals without executing writes.",
        inputs=("objective", "evidence", "constraints"),
        outputs=(
            "audit_report",
            "issue_map",
            "patch_plan",
            "risk_assessment",
            "rollback_plan",
            "smoke_plan",
        ),
        permissions=("read_context", "proposal_only"),
        risk_level="high",
        governance_required=True,
        runtime="llm",
        status="feature_gated",
        version="1.1.0",
        availability="feature_gated",
        evidence=(
            "admin-only proposal endpoint",
            "non-execution envelope",
        ),
        limitations=(
            "no file write",
            "no commit, merge, migration or deploy",
        ),
        human_approval_required=True,
    ),
    CapabilityDefinition(
        capability_id="document_analysis",
        agent_id="Orkio",
        description="Upload, parse and analyze governed user documents.",
        inputs=("document", "analysis_objective"),
        outputs=("document_analysis",),
        permissions=(),
        risk_level="medium",
        governance_required=True,
        runtime="not_connected",
        status="planned",
        version="roadmap",
        availability="planned",
        evidence=(),
        limitations=("upload and document runtime are not connected",),
        human_approval_required=True,
    ),
    CapabilityDefinition(
        capability_id="artifact_generation",
        agent_id="Orkio",
        description="Create DOCX, XLSX, PPTX and PDF artifacts through a governed runtime.",
        inputs=("artifact_brief", "source_data"),
        outputs=("artifact_file",),
        permissions=(),
        risk_level="medium",
        governance_required=True,
        runtime="not_connected",
        status="planned",
        version="roadmap",
        availability="planned",
        evidence=(),
        limitations=("artifact runtime is not connected",),
        human_approval_required=True,
    ),
    CapabilityDefinition(
        capability_id="architecture_indexer",
        agent_id="Orion",
        description="Index repositories, runtime paths, commits and technical evidence.",
        inputs=("repository_ref", "commit", "environment"),
        outputs=("architecture_index", "evidence_map"),
        permissions=(),
        risk_level="high",
        governance_required=True,
        runtime="not_connected",
        status="planned",
        version="roadmap",
        availability="planned",
        evidence=(),
        limitations=("repository and runtime connectors are not connected",),
        human_approval_required=True,
    ),
    CapabilityDefinition(
        capability_id="market_intelligence_plane",
        agent_id="Chris",
        description="Research and version market evidence for strategy decisions.",
        inputs=("market_question", "approved_sources"),
        outputs=("market_evidence", "strategy_options"),
        permissions=(),
        risk_level="medium",
        governance_required=True,
        runtime="not_connected",
        status="planned",
        version="roadmap",
        availability="planned",
        evidence=(),
        limitations=("live research connector is not connected",),
        human_approval_required=True,
    ),
    CapabilityDefinition(
        capability_id="realtime_voice_webrtc",
        agent_id="Orkio",
        description="WebRTC voice session routed through the canonical ORKIO orchestration pipeline.",
        inputs=("audio", "tenant_context", "thread_context", "consent"),
        outputs=("final_transcript", "canonical_response", "spoken_response"),
        permissions=("microphone", "read_thread", "write_thread_messages"),
        risk_level="high",
        governance_required=True,
        runtime="openai_realtime+canonical_bridge",
        status="feature_gated",
        version="1.0.0",
        availability="feature_gated",
        evidence=(
            "voice session/turn/event contracts",
            "backend-only canonical journal",
            "Orkio-only canonical turn bridge",
        ),
        limitations=(
            "requires provider configuration and retention confirmation",
            "multiagent voice and governed voice actions are disabled",
            "real browser/provider runtime proof remains required",
        ),
        human_approval_required=True,
    ),
    CapabilityDefinition(
        capability_id="agent_core_extension",
        agent_id="Orkio",
        description="Governed discovery and activation of additional ORKIO core agents.",
        inputs=("agent_contract", "capability_contract", "approval"),
        outputs=("registered_agent",),
        permissions=(),
        risk_level="high",
        governance_required=True,
        runtime="not_connected",
        status="planned",
        version="roadmap",
        availability="planned",
        evidence=(),
        limitations=("additional core agents are not registered in this release",),
        human_approval_required=True,
    ),
)


def list_capabilities() -> tuple[CapabilityDefinition, ...]:
    settings = get_settings()
    items: list[CapabilityDefinition] = []
    for item in CAPABILITIES:
        if item.capability_id != "realtime_voice_webrtc":
            items.append(item)
            continue
        if (
            settings.realtime_voice_enabled
            and settings.voice_provider == "openai_realtime"
            and settings.voice_provider_retention_confirmed
        ):
            items.append(
                replace(
                    item,
                    status="active",
                    availability="available",
                    evidence=item.evidence
                    + (
                        "runtime feature gate enabled",
                        "provider retention confirmed",
                    ),
                )
            )
        else:
            items.append(item)
    return tuple(items)


def capabilities_for_agent(agent_id: str) -> tuple[CapabilityDefinition, ...]:
    return tuple(
        item for item in list_capabilities() if item.agent_id == agent_id
    )
