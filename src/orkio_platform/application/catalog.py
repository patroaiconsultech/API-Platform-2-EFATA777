from orkio_platform.domain.errors import NotFoundError
from orkio_platform.domain.models import Agent


AGENTS = (
    Agent(
        agent_id="Orkio",
        display_name="Orkio",
        description="Primary platform orchestrator and canonical synthesizer.",
        capabilities=("chat", "routing", "coordination", "synthesis"),
    ),
    Agent(
        agent_id="Orion",
        display_name="Orion",
        description="Technical architecture, engineering and production audit specialist.",
        capabilities=("architecture", "engineering", "audit", "security"),
    ),
    Agent(
        agent_id="Chris",
        display_name="Chris",
        description="Business, strategy and executive analysis specialist.",
        capabilities=("strategy", "business", "analysis", "economics"),
    ),
    Agent(
        agent_id="Laura",
        display_name="Laura",
        description="Communication and customer experience specialist.",
        capabilities=("communication", "customer_experience", "presentation"),
    ),
    Agent(
        agent_id="Team",
        display_name="Team",
        description="Meta-selection that coordinates specialists under Orkio ownership.",
        capabilities=("multiagent", "coordination"),
    ),
)


def list_agents() -> tuple[Agent, ...]:
    return tuple(agent for agent in AGENTS if agent.status == "active")


def resolve_agent(requested_agent: str | None) -> Agent:
    target = requested_agent or "Orkio"
    for agent in list_agents():
        if agent.agent_id == target:
            return agent
    raise NotFoundError(
        "AGENT_NOT_FOUND",
        f"Agent '{target}' is not available.",
    )
