from dataclasses import asdict

from fastapi import APIRouter, Depends

from orkio_platform.api.dependencies import get_principal
from orkio_platform.application.catalog import list_agents
from orkio_platform.domain.models import Agent, PrincipalContext
from orkio_platform.orchestration.capabilities import list_capabilities

router = APIRouter(prefix="/api/agents", tags=["agents"])


@router.get("", response_model=list[Agent])
def agents(_: PrincipalContext = Depends(get_principal)) -> list[Agent]:
    return list(list_agents())


@router.get("/capabilities")
def capabilities(
    _: PrincipalContext = Depends(get_principal),
) -> list[dict[str, object]]:
    return [asdict(item) for item in list_capabilities()]
