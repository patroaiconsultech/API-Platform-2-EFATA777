from orkio_platform.domain.models import (
    EvolutionProposalRequest,
    PrincipalContext,
)
from orkio_platform.evolution.service import EvolutionProposalService
from orkio_platform.llm.contracts import LLMCompletionRequest, LLMResult


class ProposalProvider:
    provider_name = "fake-proposal"
    model_name = "fake-model"

    def __init__(self):
        self.requests: list[LLMCompletionRequest] = []

    def complete(self, request: LLMCompletionRequest) -> LLMResult:
        self.requests.append(request)
        return LLMResult(
            content=(
                "OBJECTIVE\nImprove realtime\n\n"
                "APPROVAL_GATE\nHuman approval required."
            ),
            provider=self.provider_name,
            model=self.model_name,
            total_tokens=12,
        )


def test_assisted_evolution_is_proposal_only_and_non_executing():
    provider = ProposalProvider()
    service = EvolutionProposalService(provider)
    principal = PrincipalContext(
        tenant_id="tenant-a",
        user_id="user-a",
        role="member",
    )

    proposal = service.create_proposal(
        principal,
        EvolutionProposalRequest(
            objective="Improve realtime",
            evidence=("SSE is buffered",),
            constraints=("No deploy",),
        ),
    )

    assert proposal.status == "proposal_only"
    assert proposal.write_executed is False
    assert proposal.commit_executed is False
    assert proposal.merge_executed is False
    assert proposal.deploy_executed is False
    assert proposal.migration_executed is False
    assert proposal.human_approval_required is True
    assert proposal.tenant_id == "tenant-a"
    assert proposal.token_usage == {"total_tokens": 12}
    request = provider.requests[0]
    assert request.agent_id == "Orion"
    assert "No deploy" in request.messages[0].content
    assert "write_executed=false" in request.system_prompt
