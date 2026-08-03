from __future__ import annotations

from orkio_platform.domain.models import (
    EvolutionProposalEnvelope,
    EvolutionProposalRequest,
    PrincipalContext,
    new_id,
)
from orkio_platform.llm.contracts import (
    LLMCompletionRequest,
    LLMMessage,
    LLMProvider,
)
from orkio_platform.llm.prompts import evolution_proposal_prompt


class EvolutionProposalService:
    def __init__(self, llm_provider: LLMProvider) -> None:
        self.llm_provider = llm_provider

    def create_proposal(
        self,
        principal: PrincipalContext,
        payload: EvolutionProposalRequest,
    ) -> EvolutionProposalEnvelope:
        evidence = "\n".join(
            f"- {item.strip()}"
            for item in payload.evidence
            if item.strip()
        ) or "- No evidence supplied."
        constraints = "\n".join(
            f"- {item.strip()}"
            for item in payload.constraints
            if item.strip()
        ) or "- Proposal only; no execution."

        request = LLMCompletionRequest(
            tenant_id=principal.tenant_id,
            user_id=principal.user_id,
            thread_id="evolution-proposal",
            agent_id="Orion",
            display_name="Orion",
            system_prompt=evolution_proposal_prompt(),
            messages=(
                LLMMessage(
                    role="user",
                    content=(
                        f"Objective:\n{payload.objective.strip()}\n\n"
                        f"Evidence:\n{evidence}\n\n"
                        f"Constraints:\n{constraints}"
                    ),
                ),
            ),
        )
        result = self.llm_provider.complete(request)
        return EvolutionProposalEnvelope(
            proposal_id=new_id("proposal"),
            tenant_id=principal.tenant_id,
            requested_by=principal.user_id,
            content=result.content,
            provider=result.provider,
            model=result.model,
            token_usage=result.token_usage(),
        )
