from fastapi import APIRouter, Depends

from orkio_platform.api.dependencies import get_principal
from orkio_platform.domain.models import PrincipalContext

router = APIRouter(prefix="/api/governance", tags=["governance"])


@router.get("/status")
def governance_status(
    _: PrincipalContext = Depends(get_principal),
) -> dict[str, object]:
    return {
        "candidate": "ORKIO-PLATFORM-2-FULLSTACK-RC0",
        "proposal_only": False,
        "local_execution": True,
        "repository_write_executed": False,
        "commit_executed": False,
        "merge_executed": False,
        "deploy_executed": False,
        "migration_executed": False,
        "production_authorization": False,
    }
