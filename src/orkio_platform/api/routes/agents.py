from fastapi import APIRouter, Depends

from orkio_platform.api.dependencies import get_principal
from orkio_platform.application.catalog import list_agents
from orkio_platform.domain.models import Agent, PrincipalContext

router = APIRouter(prefix="/api/agents", tags=["agents"])


@router.get("", response_model=list[Agent])
def agents(_: PrincipalContext = Depends(get_principal)) -> list[Agent]:
    return list(list_agents())
