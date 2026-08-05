from dataclasses import asdict

from fastapi import APIRouter, Depends

from orkio_platform.api.dependencies import get_principal, require_admin
from orkio_platform.application.catalog import list_agents
from orkio_platform.config import get_settings
from orkio_platform.domain.errors import DomainError
from orkio_platform.domain.models import Agent, PrincipalContext
from orkio_platform.integrations.github import GitHubConnectorError
from orkio_platform.integrations.repository_audit import (
    GitHubRepositoryAuditProvider,
)
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


@router.get("/repository-connector/status")
def repository_connector_status(
    principal: PrincipalContext = Depends(get_principal),
) -> dict[str, object]:
    require_admin(principal)
    provider = GitHubRepositoryAuditProvider(get_settings())
    return provider.status()


@router.post("/repository-connector/probe")
def repository_connector_probe(
    principal: PrincipalContext = Depends(get_principal),
) -> dict[str, object]:
    require_admin(principal)
    provider = GitHubRepositoryAuditProvider(get_settings())
    try:
        return provider.probe()
    except GitHubConnectorError as exc:
        raise DomainError(
            exc.code,
            exc.message,
            status_code=exc.status_code,
        ) from exc
