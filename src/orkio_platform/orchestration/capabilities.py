from __future__ import annotations

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
        version="1.0.0",
    ),
    CapabilityDefinition(
        capability_id="technical_architecture",
        agent_id="Orion",
        description="Architecture, software engineering, security and production audit.",
        inputs=("technical_request", "evidence"),
        outputs=("technical_analysis", "risk_assessment"),
        permissions=("read_context",),
        risk_level="medium",
        governance_required=False,
        runtime="llm",
        status="active",
        version="1.0.0",
    ),
    CapabilityDefinition(
        capability_id="business_strategy",
        agent_id="Chris",
        description="Business strategy, positioning, economics and executive analysis.",
        inputs=("business_request", "context"),
        outputs=("strategy_analysis",),
        permissions=("read_context",),
        risk_level="medium",
        governance_required=False,
        runtime="llm",
        status="active",
        version="1.0.0",
    ),
    CapabilityDefinition(
        capability_id="communication_experience",
        agent_id="Laura",
        description="Communication quality, customer experience and clear presentation.",
        inputs=("communication_request", "context"),
        outputs=("communication_analysis",),
        permissions=("read_context",),
        risk_level="low",
        governance_required=False,
        runtime="llm",
        status="active",
        version="1.0.0",
    ),
    CapabilityDefinition(
        capability_id="assisted_evolution_proposal",
        agent_id="Orion",
        description="Generate governed evolution proposals without executing writes.",
        inputs=("objective", "evidence", "constraints"),
        outputs=("audit_report", "issue_map", "patch_plan", "risk_assessment", "rollback_plan", "smoke_plan"),
        permissions=("read_context", "proposal_only"),
        risk_level="high",
        governance_required=True,
        runtime="llm",
        status="active",
        version="1.0.0",
    ),
)


def list_capabilities() -> tuple[CapabilityDefinition, ...]:
    return CAPABILITIES


def capabilities_for_agent(agent_id: str) -> tuple[CapabilityDefinition, ...]:
    return tuple(item for item in CAPABILITIES if item.agent_id == agent_id)
