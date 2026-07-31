from orkio_platform.domain.errors import NotFoundError
from orkio_platform.domain.models import Agent

AGENTS = (
    Agent(agent_id="Orkio", display_name="Orkio", description="Primary platform orchestrator.", capabilities=("chat","routing","coordination")),
    Agent(agent_id="Orion", display_name="Orion", description="Technical architecture and engineering specialist.", capabilities=("architecture","engineering","audit")),
    Agent(agent_id="Chris", display_name="Chris", description="Business and strategy specialist.", capabilities=("strategy","business","analysis")),
    Agent(agent_id="Laura", display_name="Laura", description="Communication and customer experience specialist.", capabilities=("communication","customer_experience")),
)

def list_agents() -> tuple[Agent, ...]:
    return tuple(agent for agent in AGENTS if agent.status == "active")

def resolve_agent(requested_agent: str | None) -> Agent:
    target = requested_agent or "Orkio"
    for agent in list_agents():
        if agent.agent_id == target:
            return agent
    raise NotFoundError("AGENT_NOT_FOUND", f"Agent '{target}' is not available.")
