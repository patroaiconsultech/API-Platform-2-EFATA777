from fastapi import APIRouter, Depends
from orkio_platform.api.dependencies import get_principal, require_admin
from orkio_platform.domain.models import PrincipalContext
from orkio_platform.infrastructure.repositories import repository

router = APIRouter(prefix="/api/admin", tags=["admin"])

@router.get("/overview")
def admin_overview(principal: PrincipalContext = Depends(get_principal)) -> dict[str,object]:
    principal = require_admin(principal)
    return {"tenant_id":principal.tenant_id,"stats":repository.stats(principal.tenant_id),"scope":"tenant_only"}
