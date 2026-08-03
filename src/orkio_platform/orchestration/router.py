from __future__ import annotations

from orkio_platform.application.catalog import resolve_agent
from orkio_platform.orchestration.contracts import OrchestrationPlan


TECHNICAL_TERMS = {
    "api", "arquitetura", "architecture", "backend", "banco", "bug",
    "código", "code", "deploy", "engenharia", "frontend", "infra",
    "migration", "produção", "security", "segurança", "sse", "tenant",
    "teste", "tests",
}
BUSINESS_TERMS = {
    "business", "cliente", "estratégia", "estratégico", "strategy",
    "mercado", "marketing", "negócio", "produto", "receita",
    "valuation", "vendas",
}
COMMUNICATION_TERMS = {
    "apresentação", "comunicação", "customer", "experiência", "mensagem",
    "pitch", "texto", "ux",
}


def _matches(text: str, terms: set[str]) -> bool:
    normalized = text.casefold()
    return any(term in normalized for term in terms)


def build_orchestration_plan(
    requested_agent: str | None,
    content: str,
    *,
    enabled: bool,
    max_contributors: int,
    team_agents: tuple[str, ...],
) -> OrchestrationPlan:
    requested = requested_agent or "Orkio"

    if requested == "Team":
        resolve_agent("Team")
        contributors = tuple(
            agent_id
            for agent_id in team_agents
            if agent_id != "Orkio"
        )[:max_contributors]
        for agent_id in contributors:
            resolve_agent(agent_id)
        return OrchestrationPlan(
            requested_agent="Team",
            owner_agent="Orkio",
            contributors=contributors if enabled else (),
            route_family=(
                "team_multiagent"
                if enabled and contributors
                else "team_owner_only"
            ),
        )

    owner = resolve_agent(requested)
    if not enabled or max_contributors == 0:
        return OrchestrationPlan(
            requested_agent=requested,
            owner_agent=owner.agent_id,
            contributors=(),
            route_family=(
                "explicit_agent"
                if requested_agent
                else "default_orchestrator"
            ),
        )

    candidates: list[str] = []
    if _matches(content, TECHNICAL_TERMS):
        candidates.append("Orion")
    if _matches(content, BUSINESS_TERMS):
        candidates.append("Chris")
    if _matches(content, COMMUNICATION_TERMS):
        candidates.append("Laura")

    # Orkio may coordinate multiple domains. Explicit specialists remain owners
    # and receive only complementary peers.
    contributors: list[str] = []
    for candidate in candidates:
        if candidate == owner.agent_id or candidate in contributors:
            continue
        resolve_agent(candidate)
        contributors.append(candidate)
        if len(contributors) >= max_contributors:
            break

    return OrchestrationPlan(
        requested_agent=requested,
        owner_agent=owner.agent_id,
        contributors=tuple(contributors),
        route_family=(
            "multiagent_orchestration"
            if contributors
            else (
                "explicit_agent"
                if requested_agent
                else "default_orchestrator"
            )
        ),
    )
